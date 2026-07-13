#!/usr/bin/env python3
"""Luma registration smoke contract for SignalTable.

Validates that a registration session completed full form submit — not merely
opening the Register modal (one-click-only false success).

Target smoke event: https://luma.com/aic-si-7-8
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))

from registration_gateway import (
    CONFIRMATION_PENDING,
    REGISTRATION_FAILED,
    REGISTRATION_MANUAL_REQUIRED,
    REGISTRATION_SUBMITTED,
    VALID_OUTCOMES,
    assess_stop_conditions,
    record_outcome,
)

SGT = ZoneInfo("Asia/Singapore")

SMOKE_ID = "luma-aic-si-7-8"
DEFAULT_EVENT_URL = "https://luma.com/aic-si-7-8"
DEFAULT_EVENT_TITLE = (
    "AI Governance for SMEs: Practical Solutions (without the Enterprise headache) "
    "w/ The AI Collective"
)

# Minimum browser steps after navigate: Register click, name, email, submit.
MIN_BROWSER_ACTIONS_AFTER_NAVIGATE = 3
REQUIRED_ACTION_NAMES = frozenset(
    {
        "browser_navigate",
        "browser_click",
        "browser_type",
        "browser_fill",
        "browser_press_key",
    }
)

SUBMIT_ACTION_HINTS = frozenset(
    {
        "submit",
        "register",
        "complete",
        "confirm registration",
        "rsvp",
    }
)


def _first_str(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _now_iso() -> str:
    return datetime.now(SGT).isoformat()


def _normalize_actions(session: dict[str, Any]) -> list[dict[str, Any]]:
    raw = session.get("browser_actions") or session.get("actions") or []
    if not isinstance(raw, list):
        return []
    return [a for a in raw if isinstance(a, dict)]


def _action_names(actions: list[dict[str, Any]]) -> list[str]:
    return [_first_str(a.get("name"), a.get("tool")) for a in actions if _first_str(a.get("name"), a.get("tool"))]


def _has_submit_action(actions: list[dict[str, Any]]) -> bool:
    if any(a.get("submit") is True for a in actions):
        return True
    for action in actions:
        name = _first_str(action.get("name"), action.get("tool")).lower()
        detail = _first_str(action.get("detail"), action.get("label"), action.get("ref")).lower()
        blob = f"{name} {detail}"
        if name in {"browser_click", "browser_press_key"} and any(h in blob for h in SUBMIT_ACTION_HINTS):
            if "register" in blob and "submit" not in blob and "complete" not in blob:
                continue
            return True
    return False


def validate_luma_registration_session(session: dict[str, Any]) -> dict[str, Any]:
    """Return contract result: action=accepted|rejected, reason, smoke checks."""
    actions = _normalize_actions(session)
    action_names = _action_names(actions)
    browser_action_count = len(actions)

    checks: dict[str, bool] = {
        "has_navigate": "browser_navigate" in action_names,
        "minimum_actions": browser_action_count >= MIN_BROWSER_ACTIONS_AFTER_NAVIGATE + int("browser_navigate" in action_names),
        "not_one_click_only": browser_action_count > 1,
        "form_submitted": bool(session.get("form_submitted")) or _has_submit_action(actions),
        "not_waitlist": session.get("waitlist") is not True,
        "not_wallet_gate": session.get("wallet_required") is not True,
    }

    outcome = _first_str(session.get("outcome"), session.get("registration_status"))
    on_page = session.get("on_page_confirmed") is True
    valid_outcome = outcome in {REGISTRATION_SUBMITTED, CONFIRMATION_PENDING}

    if browser_action_count <= 1:
        return {
            "action": "rejected",
            "contract": "EARLY_EXIT_ONE_CLICK",
            "reason": "session ended after one browser action; Register click is not registration success",
            "browser_action_count": browser_action_count,
            "checks": checks,
            "calendar_write_allowed": False,
        }

    if session.get("waitlist") is True:
        return {
            "action": "rejected",
            "contract": "WAITLIST_NOT_SUCCESS",
            "reason": "Luma waitlist is not confirmed registration",
            "browser_action_count": browser_action_count,
            "checks": checks,
            "calendar_write_allowed": False,
        }

    if session.get("wallet_required") is True:
        return {
            "action": "rejected",
            "contract": "WALLET_MANUAL_REQUIRED",
            "reason": "Luma event requires wallet verification; manual registration required",
            "browser_action_count": browser_action_count,
            "checks": checks,
            "calendar_write_allowed": False,
        }

    if not checks["form_submitted"]:
        return {
            "action": "rejected",
            "contract": "FORM_NOT_SUBMITTED",
            "reason": "Register modal or click alone is not success; form_submitted required",
            "browser_action_count": browser_action_count,
            "checks": checks,
            "calendar_write_allowed": False,
        }

    if not valid_outcome and not on_page:
        return {
            "action": "rejected",
            "contract": "NO_POST_SUBMIT_SUCCESS",
            "reason": f"missing valid outcome (need {REGISTRATION_SUBMITTED} or {CONFIRMATION_PENDING})",
            "browser_action_count": browser_action_count,
            "checks": checks,
            "calendar_write_allowed": False,
        }

    return {
        "action": "accepted",
        "contract": "LUMA_REGISTRATION_COMPLETE",
        "reason": _first_str(session.get("reason"), "form submitted with post-submit success state"),
        "outcome": outcome or (REGISTRATION_SUBMITTED if on_page else CONFIRMATION_PENDING),
        "browser_action_count": browser_action_count,
        "checks": checks,
        "next_step": "lobstermail_poll.py --watch --luma for confirmation evidence",
        "calendar_write_allowed": False,
    }


def build_luma_smoke_prompt(*, event_url: str = DEFAULT_EVENT_URL, event_title: str = DEFAULT_EVENT_TITLE) -> str:
    return (
        f"Luma registration smoke ({SMOKE_ID}) — ONE attempt, full form submit required.\n"
        f"Load event-register skill.\n"
        f"Event: {event_title}\n"
        f"Registration URL: {event_url}\n"
        f"Platform: luma\n"
        f"Name: SIGNALTABLE_FULL_NAME from ~/.hermes/profiles/signaltable/.env\n"
        f"Email: signaltable-reg@lobstermail.ai (LOBSTERMAIL_INBOX_ADDRESS)\n\n"
        "Steps (all required):\n"
        f"1. browser_navigate → {event_url}\n"
        "2. browser_click Register (opens form — NOT success)\n"
        "3. Fill name + email\n"
        "4. Submit the registration form once\n"
        "5. Capture on-page success OR waitlist/wallet gate\n\n"
        "STOP → REGISTRATION_MANUAL_REQUIRED on CAPTCHA, login, paid gate, wallet verify, waitlist-only.\n"
        "Do NOT treat Register click alone as success.\n"
        "Do NOT invent confirmation JSON.\n"
        "After submit, operator runs:\n"
        "  python3 luma_registration_smoke.py validate --input session.json\n"
        "  python3 lobstermail_poll.py --watch --luma --event-title \"...\" --source-url \"...\"\n"
        "Do NOT call calendar_write.py until accepted_notified.\n"
    )


def new_session_log_template() -> dict[str, Any]:
    return {
        "smoke_id": SMOKE_ID,
        "event_url": DEFAULT_EVENT_URL,
        "event_title": DEFAULT_EVENT_TITLE,
        "registration_platform": "luma",
        "started_at": _now_iso(),
        "ended_at": "",
        "browser_actions": [],
        "form_submitted": False,
        "on_page_confirmed": False,
        "waitlist": False,
        "wallet_required": False,
        "outcome": "",
        "reason": "",
        "email_used": "signaltable-reg@lobstermail.ai",
    }


def run_self_test() -> int:
    fixtures = Path(__file__).resolve().parent.parent / "fixtures"
    success = json.loads((fixtures / "luma-registration-success.sample.json").read_text(encoding="utf-8"))
    one_click = json.loads((fixtures / "luma-registration-one-click-fail.sample.json").read_text(encoding="utf-8"))
    waitlist = dict(success)
    waitlist["waitlist"] = True
    waitlist["form_submitted"] = True
    waitlist["outcome"] = CONFIRMATION_PENDING

    ok = validate_luma_registration_session(success)
    bad_click = validate_luma_registration_session(one_click)
    bad_wait = validate_luma_registration_session(waitlist)
    assess_wait = assess_stop_conditions(
        {"registration_platform": "luma", "waitlist": True, "submit_success": True}
    )
    assess_wallet = assess_stop_conditions(
        {"registration_platform": "luma", "wallet_required": True, "submit_success": False}
    )
    recorded = record_outcome(
        {
            "outcome": CONFIRMATION_PENDING,
            "event_title": DEFAULT_EVENT_TITLE,
            "registration_url": DEFAULT_EVENT_URL,
            "registration_platform": "luma",
        }
    )

    checks = {
        "success_accepted": ok.get("action") == "accepted",
        "one_click_rejected": bad_click.get("contract") == "EARLY_EXIT_ONE_CLICK",
        "waitlist_rejected": bad_wait.get("contract") == "WAITLIST_NOT_SUCCESS",
        "assess_waitlist_failed": assess_wait.get("outcome") == REGISTRATION_FAILED,
        "assess_wallet_manual": assess_wallet.get("outcome") == REGISTRATION_MANUAL_REQUIRED,
        "outcome_recorded": recorded.get("ok") is True,
    }
    payload = {
        "success": ok,
        "one_click_fail": bad_click,
        "waitlist_fail": bad_wait,
        "assess_waitlist": assess_wait,
        "checks": checks,
        "pass": all(checks.values()),
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if payload["pass"] else 1


def cmd_validate(args: argparse.Namespace) -> int:
    session = json.loads(Path(args.input).read_text(encoding="utf-8"))
    result = validate_luma_registration_session(session)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if args.output:
        Path(args.output).write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0 if result.get("action") == "accepted" else 2


def cmd_template(args: argparse.Namespace) -> int:
    template = new_session_log_template()
    text = json.dumps(template, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    print(text)
    return 0


def cmd_prompt(args: argparse.Namespace) -> int:
    print(build_luma_smoke_prompt())
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Luma registration smoke contract")
    parser.add_argument("--self-test", action="store_true")
    sub = parser.add_subparsers(dest="cmd")

    validate = sub.add_parser("validate", help="Validate a session log JSON")
    validate.add_argument("--input", "-i", required=True)
    validate.add_argument("--output", "-o")
    validate.set_defaults(func=cmd_validate)

    template = sub.add_parser("template", help="Print empty session log template")
    template.add_argument("--output", "-o")
    template.set_defaults(func=cmd_template)

    prompt = sub.add_parser("prompt", help="Print signaltable registration prompt")
    prompt.set_defaults(func=cmd_prompt)

    args = parser.parse_args()
    if args.self_test:
        return run_self_test()
    if not args.cmd:
        parser.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
