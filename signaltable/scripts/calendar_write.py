#!/usr/bin/env python3
"""Confirmation-gated Google Calendar write for SignalTable.

Maps a confirmed event (from email-parser or registration handoff) to gcal.py
inputs. Rejects discovery-only or unconfirmed events.

Examples:
  # Dry-run: show mapped gcal args (no API call)
  python3 calendar_write.py --input confirmed.json --dry-run

  # Reject unconfirmed (exit code 2)
  python3 calendar_write.py --input discovery_only.json --dry-run

  # Write after confirmation (uses gcal.py dedup + create)
  python3 calendar_write.py --input confirmed.json --write

  # Built-in gate/mapper checks (no API, no secrets)
  python3 calendar_write.py --self-test
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gcal import main as gcal_main
from email_confirm_validate import validate_inbox_evidence

SGT = ZoneInfo("Asia/Singapore")

CONFIRMED_STATUS = "confirmed"
EVIDENCE_FIELDS = (
    "confirmation_source",
    "ticket_id",
    "raw_email_id",
    "confirmation_evidence",
)


def _first_str(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=SGT)
    return dt.astimezone(SGT)


def _format_rfc3339_sgt(dt: datetime) -> str:
    local = dt.astimezone(SGT)
    return local.strftime("%Y-%m-%dT%H:%M:%S%z").replace("+0800", "+08:00")


def has_confirmation_evidence(event: dict[str, Any]) -> tuple[bool, str]:
    for field in EVIDENCE_FIELDS:
        val = event.get(field)
        if isinstance(val, str) and val.strip():
            return True, f"{field}={val.strip()[:80]}"
    return False, "missing confirmation evidence (need confirmation_source, ticket_id, raw_email_id, or confirmation_evidence)"


def confirmation_gate(event: dict[str, Any]) -> tuple[bool, str]:
    """Return (allowed, reason). Discovery-only rows must fail here."""
    status = _first_str(event.get("confirmation_status")).lower()
    if status != CONFIRMED_STATUS:
        if not status:
            return False, "missing confirmation_status; discovery-only events cannot be written"
        return False, f"confirmation_status={status!r} blocks calendar write (requires confirmed)"

    ok, ev = has_confirmation_evidence(event)
    if not ok:
        return False, ev

    inbox_ok, inbox_reason = validate_inbox_evidence(event)
    if not inbox_ok:
        return False, inbox_reason

    owner_notified = _first_str(event.get("owner_notified_at"))
    if not owner_notified:
        return False, "owner_notified_at missing; Telegram confirmation notify required before calendar write"

    return True, f"confirmation_status=confirmed; {ev}; {inbox_reason}; owner_notified_at={owner_notified}"


def map_confirmed_event(event: dict[str, Any]) -> dict[str, str]:
    """Map email-parser or discovery+confirmation payload to gcal.py create args."""
    summary = _first_str(event.get("event_title"), event.get("title"))
    if not summary:
        raise ValueError("missing event title (event_title or title)")

    start_raw = _first_str(
        event.get("event_date"),
        event.get("start_time"),
        event.get("start_at"),
    )
    start_dt = _parse_datetime(start_raw)
    if start_dt is None:
        raise ValueError(f"invalid or missing start time: {start_raw!r}")

    end_raw = _first_str(
        event.get("event_end"),
        event.get("end_time"),
        event.get("end_at"),
    )
    end_dt = _parse_datetime(end_raw) if end_raw else None
    if end_dt is None:
        end_dt = start_dt + timedelta(hours=2)

    location = _first_str(
        event.get("event_location"),
        event.get("location"),
        event.get("full_address"),
        event.get("venue_name"),
    )
    if event.get("venue_name") and event.get("full_address"):
        venue = str(event.get("venue_name")).strip()
        addr = str(event.get("full_address")).strip()
        if venue not in addr:
            location = f"{venue}, {addr}"
        else:
            location = addr

    source_url = _first_str(event.get("source_url"), event.get("url"))
    organizer = _first_str(event.get("organizer_name"), event.get("organizer"))
    ticket_id = _first_str(event.get("ticket_id"))
    reg_email = _first_str(event.get("registration_email"), event.get("lobstermail_address"))
    confirmation_source = _first_str(event.get("confirmation_source"))

    lines = []
    if organizer:
        lines.append(f"Organizer: {organizer}")
    if ticket_id:
        lines.append(f"Ticket: {ticket_id}")
    if source_url:
        lines.append(f"Source: {source_url}")
    if reg_email:
        lines.append(f"Registration email: {reg_email}")
    if confirmation_source:
        lines.append(f"Confirmation source: {confirmation_source}")
    lines.append("")
    lines.append(f"Confirmation: {CONFIRMED_STATUS}")
    description = "\n".join(lines)

    start_day = start_dt.date()
    dedup_from = (start_day - timedelta(days=1)).isoformat()
    dedup_to = (start_day + timedelta(days=1)).isoformat()

    mapped = {
        "summary": summary,
        "start": _format_rfc3339_sgt(start_dt),
        "end": _format_rfc3339_sgt(end_dt),
        "description": description.strip(),
        "dedup_from": dedup_from,
        "dedup_to": dedup_to,
    }
    if location:
        mapped["location"] = location
    return mapped


def process_event(
    event: dict[str, Any],
    *,
    dry_run: bool = True,
    write: bool = False,
    calendar_id: str = "",
    credentials: str = "",
) -> dict[str, Any]:
    allowed, gate_reason = confirmation_gate(event)
    if not allowed:
        return {
            "action": "rejected",
            "reason": gate_reason,
        }

    try:
        mapped = map_confirmed_event(event)
    except ValueError as exc:
        return {"action": "rejected", "reason": str(exc)}

    result: dict[str, Any] = {
        "action": "dry_run",
        "confirmation": gate_reason,
        "gcal_args": mapped,
    }

    if dry_run or not write:
        return result

    cal = calendar_id or os.environ.get("GOOGLE_CALENDAR_ID", "")
    if not cal:
        return {"action": "error", "reason": "GOOGLE_CALENDAR_ID not set", "gcal_args": mapped}

    creds = credentials or os.environ.get(
        "GOOGLE_CREDENTIALS_FILE",
        str(Path.home() / ".hermes/profiles/signaltable/gcal-credentials.json"),
    )

    argv = [
        "create",
        "--calendar",
        cal,
        "--credentials",
        creds,
        "--summary",
        mapped["summary"],
        "--start",
        mapped["start"],
        "--end",
        mapped["end"],
        "--description",
        mapped["description"],
        "--dedup-from",
        mapped["dedup_from"],
        "--dedup-to",
        mapped["dedup_to"],
    ]
    if mapped.get("location"):
        argv.extend(["--location", mapped["location"]])

    # Capture gcal stdout
    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    code = 0
    try:
        with redirect_stdout(buf):
            code = gcal_main(argv)
    except SystemExit as exc:
        code = int(exc.code) if isinstance(exc.code, int) else 1

    stdout = buf.getvalue().strip()
    if stdout == "DUPLICATE_SKIPPED":
        result["action"] = "duplicate_skipped"
        result["write_result"] = stdout
    elif code == 0 and stdout.startswith("{"):
        result["action"] = "created"
        result["write_result"] = json.loads(stdout)
    else:
        result["action"] = "error"
        result["reason"] = stdout or f"gcal exit code {code}"

    result["confirmation"] = gate_reason
    result["gcal_args"] = mapped
    return result


def _example_confirmed() -> dict[str, Any]:
    return {
        "event_title": "Singapore AI Meetup: Building with LLMs",
        "event_date": "2026-07-20T19:00:00+08:00",
        "event_end": "2026-07-20T21:00:00+08:00",
        "event_location": "WeWork Suntec City, Singapore",
        "confirmation_status": "confirmed",
        "confirmation_source": "email",
        "raw_email_id": "ibxmsg_a1b2c3d4e5f6",
        "ticket_id": "LUMA-20260720-abc12",
        "message_from": "noreply@lu.ma",
        "message_subject": "Registration confirmed: Singapore AI Meetup",
        "message_received_at": "2026-07-07T10:00:00+08:00",
        "inbox_fetched_at": "2026-07-07T10:05:00+08:00",
        "confirmation_evidence": "lobstermail_poll inbox=ibx_fixture message_id=ibxmsg_a1b2c3d4e5f6",
        "organizer_name": "Singapore AI Community",
        "source_url": "https://lu.ma/example-confirmed",
        "registration_email": "signaltable-reg@lobstermail.ai",
        "owner_notified_at": "2026-07-07T10:06:00+08:00",
        "telegram_notify_evidence": "hermes send --to telegram konfhub_confirmation",
    }


def _example_unconfirmed_discovery() -> dict[str, Any]:
    return {
        "title": "SHELLGym — Windows Forensics and Reverse Engineering basics",
        "start_time": "2026-07-18T14:00:00+08:00",
        "end_time": "2026-07-18T18:00:00+08:00",
        "url": "https://www.meetup.com/div0_sg/events/314638221/",
        "relevance_score": 10,
        "tier": 1,
    }


def run_self_test() -> int:
    confirmed = process_event(_example_confirmed(), dry_run=True)
    unconfirmed = process_event(_example_unconfirmed_discovery(), dry_run=True)
    confirmed_no_notify = dict(_example_confirmed())
    confirmed_no_notify.pop("owner_notified_at", None)
    confirmed_no_notify.pop("telegram_notify_evidence", None)
    missing_notify = process_event(confirmed_no_notify, dry_run=True)
    payload = {
        "confirmed_example": confirmed,
        "unconfirmed_example": unconfirmed,
        "missing_owner_notify": missing_notify,
        "pass": (
            confirmed.get("action") == "dry_run"
            and unconfirmed.get("action") == "rejected"
            and missing_notify.get("action") == "rejected"
            and "owner_notified_at" in (missing_notify.get("reason") or "")
        ),
    }
    print(json.dumps(payload, indent=2))
    return 0 if payload["pass"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Confirmation-gated calendar write")
    parser.add_argument("--input", "-i", help="JSON file with confirmed event (default: stdin)")
    parser.add_argument("--dry-run", action="store_true", help="Map and validate only (default if --write omitted)")
    parser.add_argument("--write", action="store_true", help="Call gcal.py create after confirmation gate")
    parser.add_argument("--self-test", action="store_true", help="Run built-in gate/mapper examples")
    parser.add_argument("--calendar", default=os.environ.get("GOOGLE_CALENDAR_ID", ""))
    parser.add_argument(
        "--credentials",
        default=os.environ.get(
            "GOOGLE_CREDENTIALS_FILE",
            str(Path.home() / ".hermes/profiles/signaltable/gcal-credentials.json"),
        ),
    )
    args = parser.parse_args()

    if args.self_test:
        return run_self_test()

    if args.input:
        raw = Path(args.input).read_text(encoding="utf-8")
    else:
        raw = sys.stdin.read()
    if not raw.strip():
        print(json.dumps({"error": "no input JSON"}), file=sys.stderr)
        return 2

    event = json.loads(raw)
    if not isinstance(event, dict):
        print(json.dumps({"error": "input must be a JSON object"}), file=sys.stderr)
        return 2

    dry_run = not args.write or args.dry_run
    result = process_event(
        event,
        dry_run=dry_run,
        write=args.write,
        calendar_id=args.calendar,
        credentials=args.credentials,
    )
    print(json.dumps(result, indent=2))

    if result.get("action") == "rejected":
        return 2
    if result.get("action") == "error":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
