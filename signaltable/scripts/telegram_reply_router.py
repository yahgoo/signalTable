#!/usr/bin/env python3
"""Route inbound Telegram replies: Version A shortlist first, then registration approval."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from feedback_store import load_pending, normalize_reply
from reply_capture import CAPTURE_LIVE, CAPTURE_TEST, cli_notify_error
from shortlist_reply import process_shortlist_reply

APPROVAL_SCRIPT = Path.home() / ".hermes/profiles/signaltable/scripts/approval_queue.py"
DEFAULT_PENDING = Path.home() / ".hermes/profiles/signaltable/pending_shortlist.json"
APPROVAL_QUEUE = Path.home() / ".hermes/profiles/signaltable/pending_approvals.json"


def _approval_pending() -> bool:
    if not APPROVAL_QUEUE.is_file():
        return False
    try:
        data = json.loads(APPROVAL_QUEUE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    return bool((data or {}).get("pending"))


def _is_approval_token(text: str) -> bool:
    token = (text or "").strip().upper()
    return token in {"YES", "Y", "NO", "N", "SKIP"}


def route_telegram_reply(
    text: str,
    *,
    capture_mode: str = CAPTURE_TEST,
    send_telegram: bool = False,
    spawn_register: bool = False,
    pending_path: Path | None = None,
    feedback_path: Path | None = None,
) -> dict[str, Any]:
    """Try Version A shortlist capture, then registration approval if queued."""
    pending_path = pending_path or DEFAULT_PENDING

    label = normalize_reply(text)
    if label is not None:
        shortlist = process_shortlist_reply(
            text,
            pending_path=pending_path,
            feedback_path=feedback_path,
            capture_mode=capture_mode,
            send_telegram=send_telegram,
        )
        if shortlist.get("matched"):
            return shortlist
        if shortlist.get("reason") in {"notify_not_allowed", "test_mode_forbids_telegram"}:
            return shortlist
        if shortlist.get("reason") == "no_awaiting_shortlist_reply":
            if label in {"y", "n", "m"} and (text or "").strip().lower() in {"y", "n", "m"}:
                return shortlist

    if not _is_approval_token(text) or not _approval_pending():
        return {"matched": False, "route": "none"}

    if not APPROVAL_SCRIPT.is_file():
        return {"matched": False, "route": "approval", "reason": "approval_script_missing"}

    cmd = [
        sys.executable,
        str(APPROVAL_SCRIPT),
        "handle-reply",
        text,
        "--json",
    ]
    if send_telegram and capture_mode == CAPTURE_LIVE:
        cmd.append("--notify")
    if spawn_register:
        cmd.append("--spawn-register")

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
    if result.returncode != 0:
        return {
            "matched": False,
            "route": "approval",
            "reason": "approval_handle_failed",
            "detail": (result.stderr or result.stdout or "")[:300],
        }
    try:
        data = json.loads((result.stdout or "").strip() or "{}")
    except json.JSONDecodeError:
        return {"matched": False, "route": "approval", "reason": "invalid_json"}
    data["route"] = "approval"
    data["capture_mode"] = capture_mode
    return data


def run_self_test() -> int:
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        pq = tmp / "pending.json"
        fb = tmp / "feedback.jsonl"
        pq.write_text(
            json.dumps(
                {
                    "pending": [{"event_key": "k1", "title": "T", "source": "meetup", "organizer_name": "Org"}],
                    "sent_index": 1,
                    "replied_index": 0,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        routed = route_telegram_reply(
            "y",
            pending_path=pq,
            feedback_path=fb,
            capture_mode=CAPTURE_TEST,
            send_telegram=False,
        )
        pq_block = tmp / "pending-block.json"
        pq_block.write_text(
            json.dumps(
                {
                    "pending": [{"event_key": "k2", "title": "Block", "source": "meetup", "organizer_name": "Org"}],
                    "sent_index": 1,
                    "replied_index": 0,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        blocked = route_telegram_reply(
            "y",
            pending_path=pq_block,
            feedback_path=fb,
            capture_mode=CAPTURE_TEST,
            send_telegram=True,
        )
        no_queue = route_telegram_reply("y", pending_path=tmp / "empty.json", feedback_path=fb)
        no_approval = route_telegram_reply("YES")

    checks = {
        "shortlist_routed": routed.get("matched") is True and routed.get("route") == "shortlist",
        "test_ack_one_line": "\n" not in (routed.get("ack") or ""),
        "test_ack_format": (routed.get("ack") or "") == "[TEST] yes: T · test",
        "test_notify_blocked": blocked.get("reason") == "test_mode_forbids_telegram",
        "no_pending_shortlist": no_queue.get("matched") is False,
        "approval_skipped_without_queue": no_approval.get("matched") is False,
    }
    payload = {"checks": checks, "pass": all(checks.values())}
    print(json.dumps(payload, indent=2))
    return 0 if payload["pass"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Route Telegram replies for SignalTable")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument(
        "--live",
        action="store_true",
        help="LIVE Telegram inbound (Hermes plugin/hooks only); sends Telegram ack",
    )
    parser.add_argument(
        "--dry-run-notify",
        action="store_true",
        help="TEST capture (default for CLI/SSH); JSON ack only, never sends Telegram",
    )
    parser.add_argument("--notify", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--spawn-register", action="store_true")
    parser.add_argument("--pending", default=str(DEFAULT_PENDING))
    parser.add_argument("text", nargs="?")
    args = parser.parse_args()

    if args.self_test:
        return run_self_test()

    if not args.text:
        parser.error("text required (or use --self-test)")

    if args.notify and not args.live:
        print(json.dumps({"matched": False, "error": cli_notify_error()}), file=sys.stderr)
        return 2
    if args.live and args.dry_run_notify:
        print(json.dumps({"matched": False, "error": "choose --live or --dry-run-notify, not both"}), file=sys.stderr)
        return 2

    capture_mode = CAPTURE_LIVE if args.live else CAPTURE_TEST
    send_telegram = args.live

    result = route_telegram_reply(
        args.text,
        capture_mode=capture_mode,
        send_telegram=send_telegram,
        spawn_register=args.spawn_register,
        pending_path=Path(args.pending),
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
