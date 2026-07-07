#!/usr/bin/env python3
"""Meetup → external registration gateway routing (KonfHub-first).

Resolves authoritative registration URLs, encodes safe stop conditions, and
hands off evidence to email-parser → calendar_write (confirmation-gated only).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

SGT = ZoneInfo("Asia/Singapore")

REGISTRATION_SUBMITTED = "REGISTRATION_SUBMITTED"
REGISTRATION_FAILED = "REGISTRATION_FAILED"
REGISTRATION_MANUAL_REQUIRED = "REGISTRATION_MANUAL_REQUIRED"
CONFIRMATION_PENDING = "CONFIRMATION_PENDING"

VALID_OUTCOMES = frozenset(
    {
        REGISTRATION_SUBMITTED,
        REGISTRATION_FAILED,
        REGISTRATION_MANUAL_REQUIRED,
        CONFIRMATION_PENDING,
    }
)

KONFHUB_URL_RE = re.compile(
    r"https?://(?:[a-z0-9-]+\.)*konfhub\.(?:com|io)/[^\s\)\]<>\"']+",
    re.IGNORECASE,
)

GENERIC_URL_RE = re.compile(r"https?://[^\s\)\]<>\"']+", re.IGNORECASE)

# Page signals reported by Steel/event-register skill (dry-run assess path).
STOP_SIGNALS: dict[str, str] = {
    "captcha": "CAPTCHA detected",
    "login_wall": "Login or OAuth required",
    "paid_gate": "Paid ticket or upgrade required",
    "phone_otp": "Phone OTP verification required",
    "custom_fields": "Required fields beyond name/email",
    "manual_only": "Registration marked manual-only by organizer",
    "iframe_blocked": "Registration form not accessible in browser",
}

KONFHUB_SAFE_FIELDS = frozenset({"name", "email", "full_name", "email_address"})


def _first_str(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _registration_text(event: dict[str, Any]) -> str:
    parts = [
        event.get("description", ""),
        event.get("summary", ""),
        " ".join(event.get("raw_tags") or []),
    ]
    return " ".join(str(p) for p in parts if p)


def extract_konfhub_url(text: str) -> str:
    match = KONFHUB_URL_RE.search(text or "")
    if not match:
        return ""
    return match.group(0).rstrip(".,;")


def detect_registration_platform(registration_url: str) -> str:
    url = (registration_url or "").lower()
    if "konfhub.com" in url or "konfhub.io" in url:
        return "konfhub"
    if "meetup.com" in url:
        return "meetup_native"
    if "lu.ma" in url or "luma.com" in url:
        return "luma"
    if "eventbrite" in url:
        return "eventbrite"
    if registration_url:
        return "unknown_external"
    return "missing"


def resolve_registration_target(event: dict[str, Any]) -> dict[str, Any]:
    """Return a copy with registration_url / platform / event_page_url resolved."""
    resolved = dict(event)
    event_page_url = _first_str(
        resolved.get("event_page_url"),
        resolved.get("url"),
        resolved.get("source_url"),
    )
    if event_page_url:
        resolved["event_page_url"] = event_page_url
        if not resolved.get("url"):
            resolved["url"] = event_page_url

    existing_reg = _first_str(resolved.get("registration_url"))
    if existing_reg:
        platform = _first_str(resolved.get("registration_platform")) or detect_registration_platform(
            existing_reg
        )
        resolved["registration_url"] = existing_reg
        resolved["registration_platform"] = platform
        resolved["registration_gateway_evidence"] = _first_str(
            resolved.get("registration_gateway_evidence"), "registration_url preset"
        )
        return resolved

    konfhub_url = extract_konfhub_url(_registration_text(resolved))
    if konfhub_url:
        resolved["registration_url"] = konfhub_url
        resolved["registration_platform"] = "konfhub"
        resolved["registration_gateway_evidence"] = f"KonfHub link in description: {konfhub_url}"
        return resolved

    fallback = event_page_url
    if fallback:
        resolved["registration_url"] = fallback
        resolved["registration_platform"] = detect_registration_platform(fallback) or "meetup_native"
        resolved["registration_gateway_evidence"] = "no external gateway; using event page URL"
    else:
        resolved["registration_url"] = ""
        resolved["registration_platform"] = "missing"
        resolved["registration_gateway_evidence"] = "no registration URL found"
    return resolved


def assess_stop_conditions(signals: dict[str, Any]) -> dict[str, Any]:
    """Map Steel/page observations to a registration outcome (no browser required)."""
    platform = _first_str(signals.get("registration_platform"), "unknown")
    hits = [key for key in STOP_SIGNALS if signals.get(key) is True]
    if hits:
        reasons = [STOP_SIGNALS[key] for key in hits]
        return {
            "outcome": REGISTRATION_MANUAL_REQUIRED,
            "reason": "; ".join(reasons),
            "stop_conditions": hits,
            "registration_platform": platform,
            "next_step": "Telegram owner for manual completion; do not guess fields or bypass CAPTCHA.",
        }

    if signals.get("submit_error") is True:
        return {
            "outcome": REGISTRATION_FAILED,
            "reason": _first_str(signals.get("error_message"), "form submit failed"),
            "stop_conditions": [],
            "registration_platform": platform,
            "next_step": "Log failure; do not retry unattended.",
        }

    if platform == "konfhub":
        unknown_fields = [
            str(f).lower()
            for f in (signals.get("required_fields") or [])
            if str(f).lower() not in KONFHUB_SAFE_FIELDS
        ]
        if unknown_fields:
            return {
                "outcome": REGISTRATION_MANUAL_REQUIRED,
                "reason": f"KonfHub required fields not safe to autofill: {', '.join(unknown_fields)}",
                "stop_conditions": ["custom_fields"],
                "registration_platform": platform,
                "next_step": "Telegram owner; do not invent answers for custom fields.",
            }

    if signals.get("submit_success") is True:
        if signals.get("on_page_confirmed") is True:
            return {
                "outcome": REGISTRATION_SUBMITTED,
                "reason": "Form submitted with on-page confirmation",
                "stop_conditions": [],
                "registration_platform": platform,
                "next_step": "Run email-parser; calendar_write only after LobsterMail confirms.",
            }
        return {
            "outcome": CONFIRMATION_PENDING,
            "reason": "Form submitted; awaiting email confirmation",
            "stop_conditions": [],
            "registration_platform": platform,
            "next_step": "Poll LobsterMail via email-parser; do not write calendar until confirmed.",
        }

    return {
        "outcome": REGISTRATION_FAILED,
        "reason": _first_str(signals.get("error_message"), "no safe automated path"),
        "stop_conditions": [],
        "registration_platform": platform,
        "next_step": "Stop; report to owner.",
    }


def build_registration_handoff(event: dict[str, Any]) -> dict[str, Any]:
    resolved = resolve_registration_target(event)
    return {
        "event_title": _first_str(resolved.get("title")),
        "event_page_url": _first_str(resolved.get("event_page_url"), resolved.get("url")),
        "registration_url": _first_str(resolved.get("registration_url")),
        "registration_platform": _first_str(resolved.get("registration_platform")),
        "registration_gateway_evidence": _first_str(resolved.get("registration_gateway_evidence")),
        "start_time": _first_str(resolved.get("start_time"), resolved.get("start_at")),
        "source": _first_str(resolved.get("source"), "meetup"),
        "tier": resolved.get("tier"),
        "relevance_score": resolved.get("relevance_score"),
        "allowed_autofill_fields": sorted(KONFHUB_SAFE_FIELDS),
        "stop_signals": STOP_SIGNALS,
        "valid_outcomes": sorted(VALID_OUTCOMES),
        "calendar_write_policy": "calendar_write.py --write only when confirmation_status=confirmed with evidence",
        "prepared_at": datetime.now(SGT).isoformat(),
    }


def build_register_prompt(handoff: dict[str, Any]) -> str:
    platform = _first_str(handoff.get("registration_platform"))
    reg_url = _first_str(handoff.get("registration_url"))
    page_url = _first_str(handoff.get("event_page_url"))
    gateway_note = ""
    if platform == "konfhub":
        gateway_note = (
            "KonfHub is the authoritative registration gateway. "
            f"Navigate to Registration URL ({reg_url}), NOT the Meetup page. "
            "Fill only name + email when fields are standard. "
        )
    return (
        "Owner approved registration via Telegram YES.\n"
        f"Title: {handoff.get('event_title')}\n"
        f"When: {handoff.get('start_time')}\n"
        f"Source: {handoff.get('source')}\n"
        f"Registration platform: {platform}\n"
        f"Event page URL: {page_url}\n"
        f"Registration URL (authoritative): {reg_url}\n"
        f"{gateway_note}"
        "Load event-register skill. STOP (do not guess) on CAPTCHA, login wall, paid gate, "
        "phone OTP, or custom required fields → outcome REGISTRATION_MANUAL_REQUIRED.\n"
        "After submit → REGISTRATION_SUBMITTED or CONFIRMATION_PENDING.\n"
        "Run email-parser next. Do NOT call calendar_write.py until LobsterMail returns "
        "confirmation_status=confirmed with evidence.\n"
        "Do not search for links. Do not ask for confirmation."
    )


def enrich_registration_fields(event: dict[str, Any]) -> dict[str, Any]:
    """In-place enrich for Meetup normalize path."""
    resolved = resolve_registration_target(event)
    event["event_page_url"] = resolved.get("event_page_url", "")
    event["registration_url"] = resolved.get("registration_url", "")
    event["registration_platform"] = resolved.get("registration_platform", "")
    event["registration_gateway_evidence"] = resolved.get("registration_gateway_evidence", "")
    return event


def record_outcome(payload: dict[str, Any]) -> dict[str, Any]:
    outcome = _first_str(payload.get("outcome"), payload.get("registration_status"))
    if outcome not in VALID_OUTCOMES:
        return {
            "ok": False,
            "error": f"invalid outcome {outcome!r}; expected one of {sorted(VALID_OUTCOMES)}",
        }
    recorded = {
        "ok": True,
        "outcome": outcome,
        "event_title": _first_str(payload.get("event_title"), payload.get("title")),
        "registration_url": _first_str(payload.get("registration_url")),
        "registration_platform": _first_str(payload.get("registration_platform")),
        "reason": _first_str(payload.get("reason")),
        "ticket_id": _first_str(payload.get("ticket_id")),
        "email_used": _first_str(payload.get("email_used"), payload.get("registration_email")),
        "recorded_at": datetime.now(SGT).isoformat(),
        "confirmation_status": "pending",
        "calendar_write_allowed": False,
    }
    if outcome in {REGISTRATION_SUBMITTED, CONFIRMATION_PENDING}:
        recorded["next_step"] = "email-parser → calendar_write.py only after confirmed"
    elif outcome == REGISTRATION_MANUAL_REQUIRED:
        recorded["next_step"] = "Telegram owner; no calendar write"
    else:
        recorded["next_step"] = "Stop pipeline for this event"
    return recorded


def _example_meetup_konfhub_event() -> dict[str, Any]:
    return {
        "source": "meetup",
        "title": "Singapore dbt Meetup (in-person) - Jul 2026",
        "description": (
            "Join us for talks on analytics engineering. "
            "Register on KonfHub: https://konfhub.com/e/sg-dbt-meetup-jul-2026 "
            "Free event with refreshments."
        ),
        "url": "https://www.meetup.com/singapore-dbt-meetup/events/315295343/",
        "start_time": "2026-07-09T18:30:00+08:00",
    }


def run_self_test() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from calendar_write import process_event

    sample = _example_meetup_konfhub_event()
    resolved = resolve_registration_target(sample)
    handoff = build_registration_handoff(sample)

    captcha = assess_stop_conditions(
        {"registration_platform": "konfhub", "captcha": True, "submit_success": False}
    )
    pending = assess_stop_conditions(
        {"registration_platform": "konfhub", "submit_success": True, "on_page_confirmed": False}
    )
    custom = assess_stop_conditions(
        {
            "registration_platform": "konfhub",
            "required_fields": ["name", "email", "company", "linkedin"],
            "submit_success": False,
        }
    )

    reg_outcome = record_outcome(
        {
            "outcome": CONFIRMATION_PENDING,
            "event_title": sample["title"],
            "registration_url": resolved["registration_url"],
            "registration_platform": "konfhub",
        }
    )
    calendar_blocked = process_event(
        {
            "title": sample["title"],
            "registration_status": CONFIRMATION_PENDING,
            "confirmation_status": "pending",
        },
        dry_run=True,
    )
    calendar_ok = process_event(
        {
            "event_title": sample["title"],
            "event_date": sample["start_time"],
            "confirmation_status": "confirmed",
            "confirmation_source": "konfhub_email",
            "raw_email_id": "ibxmsg_7f3a9c2e1b4d",
            "ticket_id": "KH-7842-ksug-sg",
            "message_from": "noreply@konfhub.com",
            "message_subject": "Registration confirmed for KSUG.AI Singapore #47",
            "message_received_at": "2026-07-07T19:40:00+08:00",
            "inbox_fetched_at": "2026-07-07T19:45:00+08:00",
            "confirmation_evidence": "list_emails message_id=ibxmsg_7f3a9c2e1b4d",
            "source_url": resolved["registration_url"],
            "registration_email": "signaltable-reg@lobstermail.ai",
        },
        dry_run=True,
    )

    checks = {
        "konfhub_url_extracted": resolved["registration_url"].startswith("https://konfhub.com/"),
        "platform_konfhub": resolved["registration_platform"] == "konfhub",
        "meetup_page_preserved": resolved["event_page_url"] == sample["url"],
        "captcha_manual": captcha["outcome"] == REGISTRATION_MANUAL_REQUIRED,
        "submit_pending": pending["outcome"] == CONFIRMATION_PENDING,
        "custom_fields_manual": custom["outcome"] == REGISTRATION_MANUAL_REQUIRED,
        "outcome_recorded": reg_outcome["ok"] is True,
        "calendar_blocks_pending": calendar_blocked.get("action") == "rejected",
        "calendar_allows_confirmed": calendar_ok.get("action") == "dry_run",
    }
    payload = {
        "resolved": {
            "registration_url": resolved["registration_url"],
            "registration_platform": resolved["registration_platform"],
            "event_page_url": resolved["event_page_url"],
        },
        "handoff_keys": sorted(handoff.keys()),
        "assess_captcha": captcha,
        "assess_pending": pending,
        "checks": checks,
        "pass": all(checks.values()),
    }
    print(json.dumps(payload, indent=2))
    return 0 if payload["pass"] else 1


def cmd_resolve(args: argparse.Namespace) -> int:
    event = json.loads(Path(args.input).read_text(encoding="utf-8"))
    if not isinstance(event, dict):
        print(json.dumps({"error": "input must be a JSON object"}), file=sys.stderr)
        return 2
    resolved = resolve_registration_target(event)
    handoff = build_registration_handoff(event)
    if args.handoff_only:
        print(json.dumps(handoff, indent=2, ensure_ascii=False))
    else:
        print(json.dumps(resolved, indent=2, ensure_ascii=False))
        if args.handoff:
            print("\n--- handoff ---")
            print(json.dumps(handoff, indent=2, ensure_ascii=False))
    return 0


def cmd_assess(args: argparse.Namespace) -> int:
    signals = json.loads(Path(args.input).read_text(encoding="utf-8"))
    print(json.dumps(assess_stop_conditions(signals), indent=2, ensure_ascii=False))
    return 0


def cmd_record(args: argparse.Namespace) -> int:
    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    result = record_outcome(payload)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("ok") else 2


def main() -> int:
    parser = argparse.ArgumentParser(description="SignalTable registration gateway")
    sub = parser.add_subparsers(dest="cmd")

    resolve = sub.add_parser("resolve", help="Resolve registration URL/platform from discovery event")
    resolve.add_argument("--input", "-i", required=True)
    resolve.add_argument("--handoff", action="store_true", help="Also print registration handoff JSON")
    resolve.add_argument("--handoff-only", action="store_true")
    resolve.add_argument("--json", action="store_true")
    resolve.set_defaults(func=cmd_resolve)

    assess = sub.add_parser("assess", help="Dry-run stop/outcome from page signals JSON")
    assess.add_argument("--input", "-i", required=True)
    assess.set_defaults(func=cmd_assess)

    record = sub.add_parser("record", help="Validate and normalize a registration outcome record")
    record.add_argument("--input", "-i", required=True)
    record.set_defaults(func=cmd_record)

    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return run_self_test()
    if not args.cmd:
        parser.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
