#!/usr/bin/env python3
"""Version A shortlist Telegram reply handler (y / n / m)."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from feedback_store import (
    DEFAULT_FEEDBACK,
    DEFAULT_PENDING,
    append_feedback,
    has_awaiting_shortlist_reply,
    load_pending,
    normalize_reply,
    pending_remaining,
    save_pending,
)
from reply_capture import (
    CAPTURE_LIVE,
    CAPTURE_MANUAL,
    CAPTURE_TEST,
    cli_notify_error,
    telegram_send_allowed,
)

HERMES_BIN = Path.home() / ".local/bin/hermes"


def _first_str(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _hermes_cmd() -> list[str]:
    if HERMES_BIN.is_file():
        return [str(HERMES_BIN)]
    return ["hermes"]


def _notify_telegram(message: str) -> None:
    subprocess.run(
        _hermes_cmd() + ["send", "--quiet", "--to", "telegram", message],
        check=False,
    )


def _decision_word(label: str) -> str:
    return {"y": "yes", "n": "no", "m": "maybe"}[label]


def format_reply_ack(
    *,
    label: str,
    event: dict[str, Any],
    queue_index: int = 0,
    queue_total: int = 0,
    feedback_id: str = "",
    capture_mode: str = CAPTURE_TEST,
) -> str:
    """One-line Telegram ack. Full metadata lives in JSON/logs only."""
    if capture_mode not in {CAPTURE_LIVE, CAPTURE_TEST, CAPTURE_MANUAL}:
        capture_mode = CAPTURE_TEST

    decision = _decision_word(label)
    title = _first_str(event.get("title"), "Untitled event")

    if capture_mode == CAPTURE_LIVE:
        return f"Got it — {decision}: {title} · live"
    if capture_mode == CAPTURE_MANUAL:
        return f"[MANUAL] {decision}: {title} · manual"
    return f"[TEST] {decision}: {title} · test"


def process_shortlist_reply(
    text: str,
    *,
    feedback_path: Path | None = None,
    pending_path: Path | None = None,
    capture_mode: str = CAPTURE_TEST,
    send_telegram: bool = False,
) -> dict[str, Any]:
    """Attach a y/n/m reply to the current awaiting shortlist item."""
    if capture_mode not in {CAPTURE_LIVE, CAPTURE_TEST, CAPTURE_MANUAL}:
        capture_mode = CAPTURE_TEST

    if send_telegram and capture_mode == CAPTURE_TEST:
        return {
            "matched": False,
            "route": "shortlist",
            "reason": "test_mode_forbids_telegram",
            "error": cli_notify_error(),
        }

    if send_telegram and not telegram_send_allowed(capture_mode):
        return {
            "matched": False,
            "route": "shortlist",
            "reason": "notify_not_allowed",
            "error": cli_notify_error(),
        }
    label = normalize_reply(text)
    if label is None:
        return {"matched": False, "route": "shortlist", "hint": "reply y, n, or m"}

    pending_path = pending_path or DEFAULT_PENDING
    if not has_awaiting_shortlist_reply(pending_path):
        return {
            "matched": False,
            "route": "shortlist",
            "reason": "no_awaiting_shortlist_reply",
        }

    data = load_pending(pending_path)
    replied = int(data.get("replied_index") or 0)
    sent = int(data.get("sent_index") or 0)
    events = data.get("pending") or []
    event = events[replied]
    queue_index = replied + 1
    queue_total = len(events)

    record = append_feedback(
        {
            "label": label,
            "event_key": event.get("event_key") or "",
            "title": event.get("title") or "",
            "platform": event.get("source") or event.get("platform") or "",
            "organizer": _first_str(event.get("organizer_name"), event.get("group_name")),
            "keywords": event.get("matched_keywords") or [],
            "base_score": event.get("base_score"),
            "final_score": event.get("relevance_score"),
            "queue_index": queue_index,
            "queue_total": queue_total,
            "reply_text": (text or "").strip(),
            "capture_mode": capture_mode,
        },
        feedback_path or DEFAULT_FEEDBACK,
    )

    data["replied_index"] = replied + 1
    data["last_replied_at"] = record["recorded_at"]
    data["last_label"] = label
    data["last_replied_queue_index"] = queue_index
    data["last_replied_title"] = event.get("title") or ""
    data["last_capture_mode"] = capture_mode
    save_pending(data, pending_path)

    ack = format_reply_ack(
        label=label,
        event=event,
        queue_index=queue_index,
        queue_total=queue_total,
        feedback_id=record["id"],
        capture_mode=capture_mode,
    )
    telegram_sent = False
    if send_telegram and telegram_send_allowed(capture_mode):
        _notify_telegram(ack)
        telegram_sent = True

    return {
        "matched": True,
        "route": "shortlist",
        "label": label,
        "capture_mode": capture_mode,
        "telegram_sent": telegram_sent,
        "queue_index": queue_index,
        "queue_total": queue_total,
        "sent_index": sent,
        "replied_index_before": replied,
        "event": {
            "title": event.get("title"),
            "platform": event.get("source"),
            "event_key": event.get("event_key"),
        },
        "feedback_id": record["id"],
        "remaining_to_send": pending_remaining(pending_path),
        "ack": ack,
    }


def run_self_test() -> int:
    import tempfile
    from datetime import datetime
    from zoneinfo import ZoneInfo

    SGT = ZoneInfo("Asia/Singapore")
    sample_event = {
        "event_key": "url:https://example.com/e1",
        "title": "Sample AI Meetup",
        "source": "luma",
        "organizer_name": "Test Org",
        "matched_keywords": ["ai", "data"],
        "base_score": 8,
        "relevance_score": 8,
    }

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        fb = tmp_path / "feedback.jsonl"
        events = [
            {**sample_event, "event_key": "url:https://example.com/e1", "title": "Event One"},
            {**sample_event, "event_key": "url:https://example.com/e2", "title": "Event Two"},
            {**sample_event, "event_key": "url:https://example.com/e3", "title": "Event Three"},
        ]
        pq = tmp_path / "pending.json"
        pq.write_text(
            json.dumps(
                {
                    "pending": events,
                    "sent_index": 3,
                    "replied_index": 0,
                }
            )
            + "\n",
            encoding="utf-8",
        )

        no_pending = process_shortlist_reply("y", feedback_path=fb, pending_path=tmp_path / "missing.json")
        pq_empty = tmp_path / "pending-empty.json"
        pq_empty.write_text(
            json.dumps({"pending": events, "sent_index": 0, "replied_index": 0}) + "\n",
            encoding="utf-8",
        )
        not_sent = process_shortlist_reply("y", feedback_path=fb, pending_path=pq_empty)

        y = process_shortlist_reply("y", feedback_path=fb, pending_path=pq, capture_mode=CAPTURE_TEST)
        n = process_shortlist_reply("n", feedback_path=fb, pending_path=pq, capture_mode=CAPTURE_TEST)
        m = process_shortlist_reply("m", feedback_path=fb, pending_path=pq, capture_mode=CAPTURE_TEST)
        bad = process_shortlist_reply("register", feedback_path=fb, pending_path=pq)
        after = process_shortlist_reply("y", feedback_path=fb, pending_path=pq)
        pq_block = tmp_path / "pending-block.json"
        pq_block.write_text(
            json.dumps(
                {
                    "pending": [events[0]],
                    "sent_index": 1,
                    "replied_index": 0,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        blocked = process_shortlist_reply(
            "y",
            feedback_path=fb,
            pending_path=pq_block,
            capture_mode=CAPTURE_TEST,
            send_telegram=True,
        )
        live_ack = format_reply_ack(
            label="y",
            event=events[0],
            capture_mode=CAPTURE_LIVE,
        )
        test_ack = format_reply_ack(
            label="n",
            event=events[1],
            capture_mode=CAPTURE_TEST,
        )
        manual_ack = format_reply_ack(
            label="m",
            event=events[2],
            capture_mode=CAPTURE_MANUAL,
        )

        checks = {
            "y_matched": y.get("matched") is True and y.get("label") == "y",
            "n_matched": n.get("matched") is True and n.get("label") == "n",
            "m_matched": m.get("matched") is True and m.get("label") == "m",
            "invalid_rejected": bad.get("matched") is False,
            "no_pending_file": no_pending.get("reason") == "no_awaiting_shortlist_reply",
            "nothing_sent_yet": not_sent.get("reason") == "no_awaiting_shortlist_reply",
            "no_double_capture": after.get("reason") == "no_awaiting_shortlist_reply",
            "three_feedback_rows": len(fb.read_text(encoding="utf-8").strip().splitlines()) == 3,
            "replied_index_advanced": json.loads(pq.read_text())["replied_index"] == 3,
            "live_ack_format": live_ack == "Got it — yes: Event One · live",
            "test_ack_format": test_ack == "[TEST] no: Event Two · test",
            "manual_ack_format": manual_ack == "[MANUAL] maybe: Event Three · manual",
            "ack_one_line": "\n" not in (y.get("ack") or ""),
            "ack_has_title": "Event One" in (y.get("ack") or ""),
            "ack_no_queue": "Queue:" not in (y.get("ack") or ""),
            "ack_no_feedback_id": "Feedback ID" not in (y.get("ack") or ""),
            "ack_no_source": "Source:" not in (y.get("ack") or ""),
            "json_keeps_metadata": all(
                y.get(k) is not None for k in ("queue_index", "queue_total", "feedback_id", "capture_mode")
            ),
            "test_ack_marked": (y.get("ack") or "").startswith("[TEST]"),
            "test_notify_blocked": blocked.get("reason") == "test_mode_forbids_telegram",
            "test_never_sent": y.get("telegram_sent") is False,
        }
        payload = {"checks": checks, "pass": all(checks.values())}
        print(json.dumps(payload, indent=2))
        return 0 if payload["pass"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Version A shortlist reply handler")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--feedback", default=str(DEFAULT_FEEDBACK))
    parser.add_argument("--pending", default=str(DEFAULT_PENDING))
    parser.add_argument(
        "--live",
        action="store_true",
        help="LIVE inbound capture (Hermes plugin only); may send Telegram ack",
    )
    parser.add_argument(
        "--dry-run-notify",
        action="store_true",
        help="TEST capture (default for CLI); builds ack JSON only, never sends Telegram",
    )
    parser.add_argument(
        "--notify",
        action="store_true",
        help=argparse.SUPPRESS,
    )
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
    result = process_shortlist_reply(
        args.text,
        feedback_path=Path(args.feedback),
        pending_path=Path(args.pending),
        capture_mode=capture_mode,
        send_telegram=args.live,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
