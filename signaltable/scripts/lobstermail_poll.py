#!/usr/bin/env python3
"""Direct LobsterMail inbox poll — fetch messages first, parse only fetched rows.

KonfHub confirmation flow:
  1. GET inbox emails from LobsterMail API (or fixture file)
  2. Match KonfHub sender + event subject/body
  3. Build confirmation JSON only from the matched fetched message
  4. Validate via email_confirm_validate (reject placeholders)

Operator rule: Hermes runs this script; user does not inspect the inbox manually.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from email_confirm_validate import (
    make_pending_payload,
    process_confirmation_payload,
    validate_inbox_evidence,
)

SGT = ZoneInfo("Asia/Singapore")
API_BASE = "https://api.lobstermail.ai/v1"
HERMES_BIN = Path.home() / ".local/bin/hermes"
DEFAULT_POLL_INTERVAL_SEC = 30
DEFAULT_MAX_WAIT_SEC = 7200

KONFHUB_SENDER_DOMAINS = ("konfhub.com",)
LUMA_SENDER_DOMAINS = ("lu.ma", "luma.com")
CONFIRMATION_WORDS = ("confirm", "registration", "registered", "ticket", "booking")
TICKET_ID_RE = re.compile(
    r"(?:ticket\s*(?:id|#|number)?\s*[:#]?\s*)([A-Za-z0-9][A-Za-z0-9._-]{3,})",
    re.IGNORECASE,
)


def _first_str(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _now_iso() -> str:
    return datetime.now(SGT).isoformat()


def _hermes_cmd() -> list[str]:
    if HERMES_BIN.is_file():
        return [str(HERMES_BIN)]
    return ["hermes"]


def format_confirmation_telegram(payload: dict[str, Any], meta: dict[str, Any] | None = None) -> str:
    """Evidence summary for owner Telegram — no raw email body."""
    meta = meta or {}
    lines = [
        "KonfHub confirmation received",
        "",
        f"Event: {_first_str(payload.get('event_title'))}",
    ]
    event_date = _first_str(payload.get("event_date"))
    if event_date:
        lines.append(f"When: {event_date}")
    ticket_id = _first_str(payload.get("ticket_id"))
    if ticket_id:
        lines.append(f"Ticket: {ticket_id}")
    message_from = _first_str(payload.get("message_from"), meta.get("matched_from"))
    if message_from:
        lines.append(f"From: {message_from}")
    message_subject = _first_str(payload.get("message_subject"), meta.get("matched_subject"))
    if message_subject:
        lines.append(f"Subject: {message_subject}")
    raw_id = _first_str(payload.get("raw_email_id"), meta.get("matched_email_id"))
    if raw_id:
        lines.append(f"Message ID: {raw_id}")
    source_url = _first_str(payload.get("source_url"))
    if source_url:
        lines.append(f"Source: {source_url}")
    lines.extend(
        [
            "",
            "Inbox evidence validated. Calendar write is now allowed.",
        ]
    )
    return "\n".join(lines)


def notify_owner_confirmed(
    payload: dict[str, Any],
    *,
    meta: dict[str, Any] | None = None,
    dry_run: bool = False,
) -> tuple[bool, str]:
    message = format_confirmation_telegram(payload, meta)
    if dry_run:
        return True, message
    cmd = _hermes_cmd() + ["send", "--quiet", "--to", "telegram", message]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        detail = _first_str(result.stderr, result.stdout, "hermes send failed")
        return False, detail
    return True, message


def finalize_confirmed_with_owner_notify(
    result: dict[str, Any],
    *,
    dry_run_notify: bool = False,
) -> dict[str, Any]:
    """Send Telegram and stamp owner_notified_at before calendar write is allowed."""
    if result.get("action") != "accepted":
        return result

    payload = dict(result.get("payload") or {})
    ok, detail = notify_owner_confirmed(payload, meta=result, dry_run=dry_run_notify)
    if not ok:
        return {
            **result,
            "action": "notify_failed",
            "reason": f"Telegram notify failed: {detail}",
            "calendar_write_allowed": False,
        }

    payload["owner_notified_at"] = _now_iso()
    source = _first_str(payload.get("confirmation_source"), "confirmation_email")
    payload["telegram_notify_evidence"] = f"hermes send --to telegram {source}"
    finalized = {
        **result,
        "action": "accepted_notified",
        "payload": payload,
        "owner_notified_at": payload["owner_notified_at"],
        "calendar_write_allowed": True,
        "telegram_message_preview": detail[:500],
        "next_step": "calendar_write.py --input <output> --dry-run then --write when approved",
    }
    return finalized


PROFILE_ENV = Path.home() / ".hermes/profiles/signaltable/.env"


def _load_profile_env_var(name: str) -> str:
    val = _first_str(os.environ.get(name))
    if val:
        return val
    if not PROFILE_ENV.is_file():
        return ""
    for line in PROFILE_ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, raw = line.partition("=")
        if key.strip() == name:
            return raw.strip().strip('"').strip("'")
    return ""


def _load_api_token() -> str:
    token = _first_str(
        os.environ.get("LM_API_KEY"),
        os.environ.get("LOBSTERMAIL_API_KEY"),
        _load_profile_env_var("LM_API_KEY"),
        _load_profile_env_var("LOBSTERMAIL_API_KEY"),
    )
    if token:
        return token
    token_path = Path.home() / ".lobstermail" / "token"
    if token_path.is_file():
        raw = token_path.read_text(encoding="utf-8").strip()
        if raw.startswith("{"):
            try:
                data = json.loads(raw)
                if isinstance(data, dict):
                    return _first_str(data.get("token"), data.get("apiKey"), data.get("api_key"))
            except json.JSONDecodeError:
                pass
        return raw
    return ""


def _api_request(method: str, path: str, *, token: str, query: dict[str, str] | None = None) -> Any:
    url = f"{API_BASE}{path}"
    if query:
        url = f"{url}?{urllib.parse.urlencode(query)}"
    req = urllib.request.Request(
        url,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "lobstermail-poll/1.0 signaltable",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
            if not body.strip():
                return None
            return json.loads(body)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"LobsterMail API {method} {path} failed: HTTP {exc.code} {detail}") from exc


def _normalize_messages(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [m for m in payload if isinstance(m, dict)]
    if isinstance(payload, dict):
        for key in ("data", "emails", "items", "messages"):
            val = payload.get(key)
            if isinstance(val, list):
                return [m for m in val if isinstance(m, dict)]
    return []


def resolve_inbox_id(*, token: str, inbox_id: str = "", inbox_address: str = "") -> str:
    if inbox_id:
        return inbox_id
    address = inbox_address or _load_profile_env_var("LOBSTERMAIL_INBOX_ADDRESS")
    if not address:
        raise RuntimeError("missing inbox id/address (set LOBSTERMAIL_INBOX_ID or LOBSTERMAIL_INBOX_ADDRESS)")

    listing = _api_request("GET", "/inboxes", token=token)
    inboxes = _normalize_messages(listing)
    want = address.lower()
    for inbox in inboxes:
        addr = _first_str(inbox.get("address"), inbox.get("email")).lower()
        if addr == want:
            return _first_str(inbox.get("id"), inbox.get("inboxId"))
    raise RuntimeError(f"inbox not found for address {address}")


def fetch_inbox_messages(
    *,
    token: str,
    inbox_id: str,
    since_hours: int = 48,
    limit: int = 50,
) -> list[dict[str, Any]]:
    since_dt = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    since = since_dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    payload = _api_request(
        "GET",
        f"/inboxes/{inbox_id}/emails",
        token=token,
        query={"limit": str(min(limit, 50)), "since": since},
    )
    return _normalize_messages(payload)


def load_fixture_messages(path: Path) -> tuple[str, list[dict[str, Any]]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return "", data
    if isinstance(data, dict):
        inbox_id = _first_str(data.get("inbox_id"), data.get("inboxId"))
        messages = data.get("messages") or data.get("emails") or data.get("data") or []
        if isinstance(messages, list):
            return inbox_id, [m for m in messages if isinstance(m, dict)]
    raise ValueError("fixture must be a message list or {messages: [...]} object")


def _sender_domain(from_addr: str) -> str:
    addr = from_addr.strip().lower()
    if "@" not in addr:
        return ""
    return addr.rsplit("@", 1)[-1]


def _is_konfhub_sender(from_addr: str) -> bool:
    domain = _sender_domain(from_addr)
    return any(domain == d or domain.endswith(f".{d}") for d in KONFHUB_SENDER_DOMAINS)


def _is_luma_sender(from_addr: str) -> bool:
    domain = _sender_domain(from_addr)
    return any(domain == d or domain.endswith(f".{d}") for d in LUMA_SENDER_DOMAINS)


def _event_match_text(event_title: str, source_url: str, subject: str, body: str) -> bool:
    blob = f"{subject}\n{body}".lower()
    if source_url and source_url.lower() in blob:
        return True
    title = event_title.lower().strip()
    if not title:
        return False
    tokens = [t for t in re.split(r"[^\w]+", title) if len(t) >= 4]
    if not tokens:
        return title in blob
    hits = sum(1 for t in tokens if t in blob)
    return hits >= max(2, len(tokens) // 2)


def _looks_like_confirmation(subject: str, body: str) -> bool:
    blob = f"{subject}\n{body}".lower()
    return any(word in blob for word in CONFIRMATION_WORDS)


def _extract_ticket_id(body: str) -> str:
    match = TICKET_ID_RE.search(body or "")
    return match.group(1).strip() if match else ""


def _extract_event_date(body: str) -> str:
    patterns = [
        r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2})",
        r"((?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)?,?\s*\d{1,2}\s+[A-Za-z]{3}\s+\d{4}[^<\n]{0,40})",
    ]
    for pat in patterns:
        match = re.search(pat, body or "", re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return ""


def build_confirmed_from_message(
    message: dict[str, Any],
    *,
    event_title: str,
    source_url: str,
    inbox_id: str = "",
    registration_email: str = "",
    confirmation_source: str = "konfhub_email",
) -> dict[str, Any]:
    raw_id = _first_str(message.get("id"), message.get("emailId"), message.get("email_id"))
    message_from = _first_str(message.get("from"), message.get("sender"))
    message_subject = _first_str(message.get("subject"))
    body = _first_str(message.get("body"), message.get("preview"), message.get("text"))
    received = _first_str(message.get("receivedAt"), message.get("createdAt"), message.get("received_at"))

    return {
        "event_title": event_title,
        "event_date": _extract_event_date(body),
        "event_location": "",
        "confirmation_status": "confirmed",
        "confirmation_source": confirmation_source,
        "raw_email_id": raw_id,
        "ticket_id": _extract_ticket_id(body),
        "message_from": message_from,
        "message_subject": message_subject,
        "message_received_at": received,
        "inbox_fetched_at": _now_iso(),
        "confirmation_evidence": (
            f"lobstermail_poll inbox={inbox_id or 'unknown'} message_id={raw_id}"
        ),
        "source_url": source_url,
        "registration_email": registration_email or _load_profile_env_var("LOBSTERMAIL_INBOX_ADDRESS"),
        "message_body_excerpt": body[:400],
    }


def find_konfhub_confirmation(
    messages: list[dict[str, Any]],
    *,
    event_title: str,
    source_url: str = "",
) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    for message in messages:
        sender = _first_str(message.get("from"), message.get("sender"))
        subject = _first_str(message.get("subject"))
        body = _first_str(message.get("body"), message.get("preview"), message.get("text"))
        if not _is_konfhub_sender(sender):
            continue
        if not _looks_like_confirmation(subject, body):
            continue
        if not _event_match_text(event_title, source_url, subject, body):
            continue
        candidates.append(message)

    if not candidates:
        return None

    def sort_key(msg: dict[str, Any]) -> str:
        return _first_str(msg.get("receivedAt"), msg.get("createdAt"), msg.get("received_at"))

    candidates.sort(key=sort_key, reverse=True)
    return candidates[0]


def find_luma_confirmation(
    messages: list[dict[str, Any]],
    *,
    event_title: str,
    source_url: str = "",
) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    for message in messages:
        sender = _first_str(message.get("from"), message.get("sender"))
        subject = _first_str(message.get("subject"))
        body = _first_str(message.get("body"), message.get("preview"), message.get("text"))
        if not _is_luma_sender(sender):
            continue
        if not _looks_like_confirmation(subject, body):
            continue
        if not _event_match_text(event_title, source_url, subject, body):
            continue
        candidates.append(message)

    if not candidates:
        return None

    def sort_key(msg: dict[str, Any]) -> str:
        return _first_str(msg.get("receivedAt"), msg.get("createdAt"), msg.get("received_at"))

    candidates.sort(key=sort_key, reverse=True)
    return candidates[0]


def _poll_platform_confirmation(
    *,
    platform: str,
    find_fn: Any,
    confirmation_source: str,
    pending_label: str,
    event_title: str,
    source_url: str = "",
    messages: list[dict[str, Any]] | None = None,
    inbox_id: str = "",
    token: str = "",
    since_hours: int = 48,
) -> dict[str, Any]:
    fetched = messages
    fetch_meta: dict[str, Any] = {"fetched_count": 0, "inbox_id": inbox_id}

    if fetched is None:
        try:
            if not token:
                token = _load_api_token()
            if not token:
                return {
                    "action": "rejected",
                    "reason": "missing LobsterMail API token (~/.lobstermail/token or LM_API_KEY)",
                    "calendar_write_allowed": False,
                }
            inbox_id = resolve_inbox_id(token=token, inbox_id=inbox_id)
            fetched = fetch_inbox_messages(token=token, inbox_id=inbox_id, since_hours=since_hours)
            fetch_meta = {"fetched_count": len(fetched), "inbox_id": inbox_id, "source": "lobstermail_api"}
        except RuntimeError as exc:
            return {
                "action": "rejected",
                "reason": str(exc),
                "calendar_write_allowed": False,
            }

    else:
        fetch_meta = {"fetched_count": len(fetched), "inbox_id": inbox_id, "source": "fixture"}

    match = find_fn(fetched, event_title=event_title, source_url=source_url)
    if match is None:
        pending = make_pending_payload(
            event_title=event_title,
            reason=f"no matching {pending_label} confirmation email in LobsterMail inbox",
        )
        return {
            "action": "pending",
            "reason": pending["reason"],
            "calendar_write_allowed": False,
            "payload": pending,
            "platform": platform,
            **fetch_meta,
        }

    built = build_confirmed_from_message(
        match,
        event_title=event_title,
        source_url=source_url,
        inbox_id=inbox_id,
        confirmation_source=confirmation_source,
    )
    validated = process_confirmation_payload(built)
    validated.update(fetch_meta)
    validated["platform"] = platform
    validated["matched_email_id"] = _first_str(match.get("id"))
    validated["matched_from"] = _first_str(match.get("from"))
    validated["matched_subject"] = _first_str(match.get("subject"))
    return validated


def poll_konfhub_confirmation(
    *,
    event_title: str,
    source_url: str = "",
    messages: list[dict[str, Any]] | None = None,
    inbox_id: str = "",
    token: str = "",
    since_hours: int = 48,
) -> dict[str, Any]:
    return _poll_platform_confirmation(
        platform="konfhub",
        find_fn=find_konfhub_confirmation,
        confirmation_source="konfhub_email",
        pending_label="KonfHub",
        event_title=event_title,
        source_url=source_url,
        messages=messages,
        inbox_id=inbox_id,
        token=token,
        since_hours=since_hours,
    )


def poll_luma_confirmation(
    *,
    event_title: str,
    source_url: str = "",
    messages: list[dict[str, Any]] | None = None,
    inbox_id: str = "",
    token: str = "",
    since_hours: int = 48,
) -> dict[str, Any]:
    return _poll_platform_confirmation(
        platform="luma",
        find_fn=find_luma_confirmation,
        confirmation_source="luma_email",
        pending_label="Luma",
        event_title=event_title,
        source_url=source_url,
        messages=messages,
        inbox_id=inbox_id,
        token=token,
        since_hours=since_hours,
    )


def _watch_platform_confirmation(
    *,
    poll_fn: Any,
    platform_label: str,
    event_title: str,
    source_url: str = "",
    messages: list[dict[str, Any]] | None = None,
    inbox_id: str = "",
    token: str = "",
    since_hours: int = 48,
    interval_sec: int = DEFAULT_POLL_INTERVAL_SEC,
    max_wait_sec: int = DEFAULT_MAX_WAIT_SEC,
    max_attempts: int = 0,
    dry_run_notify: bool = False,
    emit_pending: bool = True,
) -> dict[str, Any]:
    """Poll LobsterMail repeatedly until confirmed+notified, timeout, or rejection."""
    started = time.monotonic()
    attempt = 0
    last_pending: dict[str, Any] | None = None

    while True:
        attempt += 1
        result = poll_fn(
            event_title=event_title,
            source_url=source_url,
            messages=messages,
            inbox_id=inbox_id,
            token=token,
            since_hours=since_hours,
        )
        result["poll_attempt"] = attempt
        result["interval_sec"] = interval_sec

        if result.get("action") == "accepted":
            finalized = finalize_confirmed_with_owner_notify(result, dry_run_notify=dry_run_notify)
            finalized["poll_attempt"] = attempt
            if emit_pending:
                print(json.dumps(finalized, ensure_ascii=False), flush=True)
            return finalized

        if result.get("action") == "rejected":
            result["poll_attempt"] = attempt
            if emit_pending:
                print(json.dumps(result, ensure_ascii=False), flush=True)
            return result

        elapsed = time.monotonic() - started
        result["waiting"] = True
        result["elapsed_sec"] = int(elapsed)
        result["next_poll_in_sec"] = interval_sec
        last_pending = result
        if emit_pending:
            print(json.dumps(result, ensure_ascii=False), flush=True)

        if max_attempts and attempt >= max_attempts:
            timeout = dict(last_pending)
            timeout["action"] = "pending_timeout"
            timeout["reason"] = (
                f"no {platform_label} confirmation after {attempt} poll(s); "
                "still waiting for LobsterMail inbox message"
            )
            timeout["calendar_write_allowed"] = False
            return timeout

        if elapsed >= max_wait_sec:
            timeout = dict(last_pending or result)
            timeout["action"] = "pending_timeout"
            timeout["reason"] = (
                f"no {platform_label} confirmation after {int(elapsed)}s; "
                "still waiting for LobsterMail inbox message"
            )
            timeout["calendar_write_allowed"] = False
            return timeout

        time.sleep(interval_sec)


def watch_konfhub_confirmation(
    *,
    event_title: str,
    source_url: str = "",
    messages: list[dict[str, Any]] | None = None,
    inbox_id: str = "",
    token: str = "",
    since_hours: int = 48,
    interval_sec: int = DEFAULT_POLL_INTERVAL_SEC,
    max_wait_sec: int = DEFAULT_MAX_WAIT_SEC,
    max_attempts: int = 0,
    dry_run_notify: bool = False,
    emit_pending: bool = True,
) -> dict[str, Any]:
    return _watch_platform_confirmation(
        poll_fn=poll_konfhub_confirmation,
        platform_label="KonfHub",
        event_title=event_title,
        source_url=source_url,
        messages=messages,
        inbox_id=inbox_id,
        token=token,
        since_hours=since_hours,
        interval_sec=interval_sec,
        max_wait_sec=max_wait_sec,
        max_attempts=max_attempts,
        dry_run_notify=dry_run_notify,
        emit_pending=emit_pending,
    )


def watch_luma_confirmation(
    *,
    event_title: str,
    source_url: str = "",
    messages: list[dict[str, Any]] | None = None,
    inbox_id: str = "",
    token: str = "",
    since_hours: int = 48,
    interval_sec: int = DEFAULT_POLL_INTERVAL_SEC,
    max_wait_sec: int = DEFAULT_MAX_WAIT_SEC,
    max_attempts: int = 0,
    dry_run_notify: bool = False,
    emit_pending: bool = True,
) -> dict[str, Any]:
    return _watch_platform_confirmation(
        poll_fn=poll_luma_confirmation,
        platform_label="Luma",
        event_title=event_title,
        source_url=source_url,
        messages=messages,
        inbox_id=inbox_id,
        token=token,
        since_hours=since_hours,
        interval_sec=interval_sec,
        max_wait_sec=max_wait_sec,
        max_attempts=max_attempts,
        dry_run_notify=dry_run_notify,
        emit_pending=emit_pending,
    )


def run_self_test() -> int:
    fixture_path = Path(__file__).resolve().parent.parent / "fixtures" / "lobstermail-inbox-konfhub.sample.json"
    empty_fixture = Path(__file__).resolve().parent.parent / "fixtures" / "lobstermail-inbox-empty.sample.json"
    _, messages = load_fixture_messages(fixture_path)
    _, empty_messages = load_fixture_messages(empty_fixture)

    accepted = poll_konfhub_confirmation(
        event_title="KSUG.AI Singapore #47 Meetup @Nutanix on 22 Jul 2026",
        source_url="https://konfhub.com/ksug-sg-2026-07-22",
        messages=messages,
        inbox_id="ibx_fixture",
    )
    pending = poll_konfhub_confirmation(
        event_title="Nonexistent Event Title That Will Not Match",
        source_url="https://konfhub.com/does-not-exist",
        messages=messages,
        inbox_id="ibx_fixture",
    )
    fake = process_confirmation_payload(
        {
            "confirmation_status": "confirmed",
            "confirmation_source": "konfhub_email",
            "raw_email_id": "123456",
            "ticket_id": "EVT-12345",
            "registration_email": "registration@konfhub.com",
        }
    )
    notified = finalize_confirmed_with_owner_notify(accepted, dry_run_notify=True)
    watch_timeout = watch_konfhub_confirmation(
        event_title="KSUG.AI Singapore #47 Meetup @Nutanix on 22 Jul 2026",
        source_url="https://konfhub.com/ksug-sg-2026-07-22",
        messages=empty_messages,
        inbox_id="ibx_empty",
        interval_sec=1,
        max_attempts=1,
        emit_pending=False,
    )

    luma_fixture = Path(__file__).resolve().parent.parent / "fixtures" / "lobstermail-inbox-luma-aic.sample.json"
    _, luma_messages = load_fixture_messages(luma_fixture)
    luma_title = (
        "AI Governance for SMEs: Practical Solutions (without the Enterprise headache) "
        "w/ The AI Collective"
    )
    luma_accepted = poll_luma_confirmation(
        event_title=luma_title,
        source_url="https://luma.com/aic-si-7-8",
        messages=luma_messages,
        inbox_id="ibx_fixture",
    )

    checks = {
        "real_message_accepted": accepted.get("action") == "accepted",
        "accepted_blocks_calendar_until_notify": accepted.get("calendar_write_allowed") is False,
        "no_match_pending": pending.get("action") == "pending",
        "placeholder_rejected": fake.get("action") == "rejected",
        "built_from_real_id": accepted.get("matched_email_id", "").startswith("eml_"),
        "notify_sets_owner_notified": bool(notified.get("owner_notified_at")),
        "calendar_allowed_after_notify": notified.get("calendar_write_allowed") is True,
        "watch_empty_inbox_times_out": watch_timeout.get("action") == "pending_timeout",
        "luma_message_accepted": luma_accepted.get("action") == "accepted",
        "luma_source_tagged": luma_accepted.get("payload", {}).get("confirmation_source") == "luma_email",
    }
    payload = {
        "accepted": accepted,
        "luma_accepted": luma_accepted,
        "notified": notified,
        "pending": pending,
        "placeholder": fake,
        "watch_timeout": watch_timeout,
        "checks": checks,
        "pass": all(checks.values()),
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if payload["pass"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Poll LobsterMail and parse KonfHub/Luma confirmations")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--konfhub", action="store_true", help="Poll for KonfHub confirmation")
    parser.add_argument("--luma", action="store_true", help="Poll for Luma confirmation")
    parser.add_argument("--event-title", required=False, default="")
    parser.add_argument("--source-url", default="")
    parser.add_argument(
        "--fixture",
        help="Offline fixture inbox (blocked in production; use --self-test for fixture checks)",
    )
    parser.add_argument(
        "--inbox-id",
        default=_load_profile_env_var("LOBSTERMAIL_INBOX_ID"),
    )
    parser.add_argument("--since-hours", type=int, default=48)
    parser.add_argument("--watch", action="store_true", help="Poll until confirmed+notified or timeout")
    parser.add_argument("--interval", type=int, default=DEFAULT_POLL_INTERVAL_SEC, help="Seconds between polls")
    parser.add_argument(
        "--max-wait",
        type=int,
        default=DEFAULT_MAX_WAIT_SEC,
        help="Stop waiting after this many seconds (watch mode)",
    )
    parser.add_argument("--max-attempts", type=int, default=0, help="Stop after N polls (watch mode; 0=use max-wait)")
    parser.add_argument(
        "--dry-run-notify",
        action="store_true",
        help="Stamp owner_notified_at without calling hermes send (tests)",
    )
    parser.add_argument(
        "--notify",
        action="store_true",
        help="On single accepted poll, send Telegram before enabling calendar write",
    )
    parser.add_argument("--output", "-o", help="Write payload JSON (accepted or pending)")
    args = parser.parse_args()

    if args.self_test:
        return run_self_test()

    if args.konfhub and args.luma:
        parser.error("choose one of --konfhub or --luma")
    if not args.konfhub and not args.luma:
        parser.error("--konfhub or --luma required (or use --self-test)")
    if not args.event_title:
        parser.error("--event-title required")
    platform = "konfhub" if args.konfhub else "luma"
    if not args.source_url:
        args.source_url = (
            "https://konfhub.com/ksug-sg-2026-07-22"
            if platform == "konfhub"
            else "https://luma.com/aic-si-7-8"
        )
    if args.fixture and not args.self_test:
        print(
            json.dumps(
                {
                    "action": "rejected",
                    "reason": (
                        f"production forbids --fixture; use lobstermail_poll.py --watch --{platform} "
                        "against live API"
                    ),
                    "calendar_write_allowed": False,
                }
            ),
            file=sys.stderr,
        )
        return 2

    messages = None
    inbox_id = args.inbox_id
    if args.fixture:
        inbox_id, messages = load_fixture_messages(Path(args.fixture))

    poll_fn = poll_konfhub_confirmation if platform == "konfhub" else poll_luma_confirmation
    watch_fn = watch_konfhub_confirmation if platform == "konfhub" else watch_luma_confirmation

    if args.watch:
        result = watch_fn(
            event_title=args.event_title,
            source_url=args.source_url,
            messages=messages,
            inbox_id=inbox_id,
            since_hours=args.since_hours,
            interval_sec=args.interval,
            max_wait_sec=args.max_wait,
            max_attempts=args.max_attempts,
            dry_run_notify=args.dry_run_notify,
            emit_pending=True,
        )
    else:
        result = poll_fn(
            event_title=args.event_title,
            source_url=args.source_url,
            messages=messages,
            inbox_id=inbox_id,
            since_hours=args.since_hours,
        )
        if result.get("action") == "accepted" and (args.notify or args.dry_run_notify):
            result = finalize_confirmed_with_owner_notify(result, dry_run_notify=args.dry_run_notify)

    if not args.watch:
        print(json.dumps(result, indent=2, ensure_ascii=False))

    if args.output:
        out_payload = result.get("payload") if result.get("action") in {
            "accepted",
            "accepted_notified",
            "pending",
            "pending_timeout",
        } else result
        if isinstance(out_payload, dict):
            Path(args.output).write_text(json.dumps(out_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if result.get("action") in {"rejected", "notify_failed"}:
        return 2
    if result.get("action") in {"pending", "pending_timeout"}:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
