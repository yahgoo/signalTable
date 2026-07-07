#!/usr/bin/env python3
"""Validate confirmation payloads against real LobsterMail inbox evidence.

Blocks placeholder/sample IDs (EVT-12345, 123456) and requires output from
lobstermail_poll.py (confirmation_evidence must contain lobstermail_poll).
Used by email-parser handoff and calendar_write gate.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

PLACEHOLDER_TICKET_IDS = frozenset(
    {
        "evt-12345",
        "evt-67890",
        "evt-1234",
        "example",
        "test-123",
        "12345",
        "ticket-123",
    }
)

PLACEHOLDER_RAW_EMAIL_IDS = frozenset(
    {
        "123456",
        "12345",
        "lm-test-001",
        "test-001",
        "example",
        "raw_email_id",
        "<lobstermail email id>",
    }
)

EXAMPLE_ONLY_SENDERS = frozenset(
    {
        "example@example.com",
        "test@example.com",
    }
)

EXAMPLE_ONLY_REGISTRATION_EMAILS = frozenset(
    {
        "registration@konfhub.com",
        "example@example.com",
    }
)

INBOX_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{5,}$")


def _first_str(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _is_placeholder_ticket(ticket_id: str) -> bool:
    tid = ticket_id.strip().lower()
    if not tid:
        return False
    if tid in PLACEHOLDER_TICKET_IDS:
        return True
    if tid.startswith("evt-") and tid.replace("evt-", "").isdigit() and len(tid) <= 10:
        return True
    return False


def _is_placeholder_raw_email_id(raw_id: str) -> bool:
    rid = raw_id.strip().lower()
    if not rid:
        return True
    if rid in PLACEHOLDER_RAW_EMAIL_IDS:
        return True
    if rid.isdigit() and len(rid) <= 8:
        return True
    if rid.startswith("lm-test"):
        return True
    return False


def _has_inbox_message_reference(payload: dict[str, Any]) -> tuple[bool, str]:
    """Require proof the payload came from a fetched inbox row, not invented text."""
    raw_id = _first_str(payload.get("raw_email_id"))
    if not raw_id:
        return False, "missing raw_email_id from lobstermail_poll.py fetch"
    if _is_placeholder_raw_email_id(raw_id):
        return False, f"placeholder raw_email_id rejected ({raw_id})"
    if not INBOX_ID_RE.match(raw_id):
        return False, f"raw_email_id format invalid ({raw_id})"

    message_from = _first_str(payload.get("message_from"), payload.get("email_from"))
    message_subject = _first_str(payload.get("message_subject"), payload.get("email_subject"))
    message_received_at = _first_str(payload.get("message_received_at"), payload.get("received_at"))
    inbox_fetched_at = _first_str(payload.get("inbox_fetched_at"), payload.get("fetched_at"))
    evidence = _first_str(payload.get("confirmation_evidence"))

    if "lobstermail_poll" not in evidence.lower():
        return (
            False,
            "confirmation_evidence must come from lobstermail_poll.py "
            "(MCP/manual JSON paths are disabled in production)",
        )

    linkage_hits = sum(
        1
        for val in (message_from, message_subject, message_received_at, inbox_fetched_at)
        if val
    )

    if linkage_hits < 2:
        return (
            False,
            "missing inbox message linkage (need raw_email_id plus ≥1 of message_from, "
            "message_subject, message_received_at, inbox_fetched_at from lobstermail_poll)",
        )

    if message_from.lower() in EXAMPLE_ONLY_SENDERS:
        return False, f"example-only sender rejected ({message_from})"

    reg_email = _first_str(payload.get("registration_email"), payload.get("lobstermail_address"))
    if reg_email.lower() in EXAMPLE_ONLY_REGISTRATION_EMAILS:
        return False, f"example-only registration_email rejected ({reg_email})"

    return True, f"inbox evidence ok (raw_email_id={raw_id})"


def validate_inbox_evidence(payload: dict[str, Any]) -> tuple[bool, str]:
    """Return (ok, reason). For confirmed payloads only."""
    status = _first_str(payload.get("confirmation_status")).lower()
    if status != "confirmed":
        return False, f"confirmation_status={status or 'missing'} is not confirmed"

    ticket_id = _first_str(payload.get("ticket_id"))
    if ticket_id and _is_placeholder_ticket(ticket_id):
        return False, f"placeholder ticket_id rejected ({ticket_id})"

    ok, reason = _has_inbox_message_reference(payload)
    if not ok:
        return False, reason

    source = _first_str(payload.get("confirmation_source"))
    if not source:
        return False, "missing confirmation_source"

    return True, reason


def make_pending_payload(
    *,
    event_title: str = "",
    reason: str = "no matching confirmation email in LobsterMail inbox",
) -> dict[str, Any]:
    return {
        "confirmation_status": "pending",
        "reason": reason,
        "event_title": event_title,
        "calendar_write_allowed": False,
    }


def process_confirmation_payload(payload: dict[str, Any]) -> dict[str, Any]:
    status = _first_str(payload.get("confirmation_status")).lower()
    if status in {"", "pending", "waitlisted"}:
        return {
            "action": "pending",
            "confirmation_status": status or "pending",
            "reason": _first_str(payload.get("reason"), "no confirmed email"),
            "calendar_write_allowed": False,
        }

    if status != "confirmed":
        return {
            "action": "rejected",
            "reason": f"unsupported confirmation_status={status}",
            "calendar_write_allowed": False,
        }

    ok, reason = validate_inbox_evidence(payload)
    if not ok:
        return {
            "action": "rejected",
            "reason": reason,
            "calendar_write_allowed": False,
        }

    return {
        "action": "accepted",
        "reason": reason,
        "calendar_write_allowed": False,
        "payload": payload,
        "next_step": "owner Telegram notify required before calendar write",
    }


def _fixture_real_confirmed() -> dict[str, Any]:
    return {
        "event_title": "KSUG.AI Singapore #47 Meetup @Nutanix on 22 Jul 2026",
        "event_date": "2026-07-22T18:00:00+08:00",
        "event_location": "Nutanix, Singapore",
        "confirmation_status": "confirmed",
        "confirmation_source": "konfhub_email",
        "raw_email_id": "ibxmsg_7f3a9c2e1b4d",
        "ticket_id": "KH-7842-ksug-sg",
        "message_from": "noreply@konfhub.com",
        "message_subject": "Registration confirmed for KSUG.AI Singapore #47",
        "message_received_at": "2026-07-07T19:40:00+08:00",
        "inbox_fetched_at": "2026-07-07T19:45:00+08:00",
        "confirmation_evidence": "lobstermail_poll inbox=ibx_fixture message_id=ibxmsg_7f3a9c2e1b4d",
        "source_url": "https://konfhub.com/ksug-sg-2026-07-22",
        "registration_email": "signaltable-reg@lobstermail.ai",
    }


def _fixture_placeholder_confirmed() -> dict[str, Any]:
    return {
        "event_title": "KSUG.AI Singapore #47 Meetup @Nutanix on 22 Jul 2026",
        "event_date": "2026-07-22T19:00:00+08:00",
        "confirmation_status": "confirmed",
        "confirmation_source": "konfhub_email",
        "raw_email_id": "123456",
        "ticket_id": "EVT-12345",
        "registration_email": "registration@konfhub.com",
    }


def _fixture_mcp_manual_confirmed() -> dict[str, Any]:
    payload = _fixture_real_confirmed()
    payload["confirmation_evidence"] = "list_emails message_id=ibxmsg_7f3a9c2e1b4d"
    return payload


def run_self_test() -> int:
    real = process_confirmation_payload(_fixture_real_confirmed())
    pending = process_confirmation_payload(make_pending_payload(event_title="KSUG test"))
    fake = process_confirmation_payload(_fixture_placeholder_confirmed())
    mcp_manual = process_confirmation_payload(_fixture_mcp_manual_confirmed())

    checks = {
        "real_accepted": real.get("action") == "accepted",
        "pending_pending": pending.get("action") == "pending",
        "placeholder_rejected": fake.get("action") == "rejected",
        "mcp_manual_rejected": mcp_manual.get("action") == "rejected",
    }
    payload = {
        "real": real,
        "pending": pending,
        "placeholder": fake,
        "mcp_manual": mcp_manual,
        "checks": checks,
        "pass": all(checks.values()),
    }
    print(json.dumps(payload, indent=2))
    return 0 if payload["pass"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate LobsterMail confirmation payloads")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--input", "-i", help="Candidate confirmation JSON")
    parser.add_argument("--output", "-o", help="Write normalized result JSON")
    parser.add_argument("--pending", action="store_true", help="Emit pending payload")
    parser.add_argument("--event-title", default="")
    parser.add_argument("--reason", default="")
    args = parser.parse_args()

    if args.self_test:
        return run_self_test()

    if args.pending:
        result = make_pending_payload(
            event_title=args.event_title,
            reason=args.reason or "no matching confirmation email in LobsterMail inbox",
        )
        out = {"action": "pending", "payload": result}
        text = json.dumps(result, indent=2, ensure_ascii=False)
        print(text)
        if args.output:
            Path(args.output).write_text(text + "\n", encoding="utf-8")
        return 0

    if not args.input:
        parser.error("--input or --pending or --self-test required")

    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        print(json.dumps({"error": "input must be a JSON object"}), file=sys.stderr)
        return 2

    result = process_confirmation_payload(payload)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if args.output and result.get("action") == "accepted":
        Path(args.output).write_text(
            json.dumps(result["payload"], indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    elif args.output and result.get("action") == "pending":
        pending = make_pending_payload(
            event_title=_first_str(payload.get("event_title"), args.event_title),
            reason=_first_str(result.get("reason")),
        )
        Path(args.output).write_text(json.dumps(pending, indent=2) + "\n", encoding="utf-8")

    if result.get("action") == "rejected":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
