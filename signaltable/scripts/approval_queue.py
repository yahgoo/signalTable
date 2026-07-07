#!/usr/bin/env python3
"""Pending event-registration approvals for SignalTable Telegram YES/NO flow."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
from registration_gateway import build_register_prompt, build_registration_handoff, resolve_registration_target

SGT = ZoneInfo("Asia/Singapore")
DEFAULT_QUEUE = Path.home() / ".hermes/profiles/signaltable/pending_approvals.json"
HERMES_BIN = Path.home() / ".local/bin/hermes"
SIGNALTABLE_BIN = Path.home() / ".local/bin/signaltable"


def _hermes_cmd() -> list[str]:
    if HERMES_BIN.is_file():
        return [str(HERMES_BIN)]
    return ["hermes"]


def _hermes_send(*args: str) -> None:
    subprocess.run(_hermes_cmd() + ["send", "--quiet", *args], check=False)


def _now_iso() -> str:
    return datetime.now(SGT).isoformat()


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"pending": []}
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        return {"pending": []}
    data.setdefault("pending", [])
    return data


def _save(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    tmp.replace(path)


def format_message(event: dict[str, Any]) -> str:
    reg_url = event.get("registration_url") or event.get("url") or ""
    platform = event.get("registration_platform") or "unknown"
    gateway_line = ""
    if platform == "konfhub":
        gateway_line = f"Gateway: KonfHub\nRegister at: {reg_url}\n"
    return (
        "Approve registration?\n"
        f"Event: {event['title']}\n"
        f"When: {event['when']}\n"
        f"Source: {event['source']}\n"
        f"{gateway_line}"
        f"Why flagged: {event['reason']}\n"
        "Reply YES to register, NO to skip."
    )


def cmd_add(args: argparse.Namespace) -> int:
    base = {
        "title": args.title,
        "when": args.when,
        "source": args.source,
        "reason": args.reason,
        "url": args.url or "",
        "tier": args.tier,
        "score": args.score,
    }
    if args.description:
        base["description"] = args.description
    if args.registration_url:
        base["registration_url"] = args.registration_url
    if args.registration_platform:
        base["registration_platform"] = args.registration_platform
    resolved = resolve_registration_target(base)
    event = {
        "id": args.id or uuid.uuid4().hex[:12],
        "title": resolved.get("title") or args.title,
        "when": args.when,
        "source": args.source,
        "reason": args.reason,
        "url": resolved.get("event_page_url") or resolved.get("url") or args.url or "",
        "event_page_url": resolved.get("event_page_url") or resolved.get("url") or "",
        "registration_url": resolved.get("registration_url") or "",
        "registration_platform": resolved.get("registration_platform") or "",
        "registration_gateway_evidence": resolved.get("registration_gateway_evidence") or "",
        "tier": args.tier,
        "score": args.score,
        "created_at": _now_iso(),
        "telegram_message_id": None,
    }
    path = Path(args.queue)
    data = _load(path)
    data["pending"].append(event)
    _save(path, data)
    if args.print_message:
        print(format_message(event))
    if args.json:
        print(json.dumps(event, ensure_ascii=False))
    return 0


def cmd_send(args: argparse.Namespace) -> int:
    path = Path(args.queue)
    data = _load(path)
    if not data["pending"]:
        print("No pending approvals to send.", file=sys.stderr)
        return 1
    event = data["pending"][-1]
    message = format_message(event)
    target = args.to or "telegram"
    cmd = _hermes_cmd() + ["send", "--quiet", "--to", target, message]
    if args.dry_run:
        print(message)
        return 0
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stderr or result.stdout, file=sys.stderr)
        return result.returncode
    if args.json:
        print(json.dumps({"sent": True, "event": event}, ensure_ascii=False))
    else:
        print(f"Sent approval for: {event['title']}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    data = _load(Path(args.queue))
    if args.json:
        print(json.dumps(data["pending"], indent=2, ensure_ascii=False))
    elif not data["pending"]:
        print("No pending approvals.")
    else:
        for item in data["pending"]:
            print(f"- {item['id']}: {item['title']} ({item['when']})")
    return 0


def _normalize_reply(text: str) -> str | None:
    token = text.strip().upper()
    if token in {"YES", "Y"}:
        return "yes"
    if token in {"NO", "N", "SKIP"}:
        return "no"
    return None


def cmd_resolve(args: argparse.Namespace) -> int:
    decision = _normalize_reply(args.decision)
    if decision is None:
        print(json.dumps({"matched": False}))
        return 0
    path = Path(args.queue)
    data = _load(path)
    if not data["pending"]:
        out = {"matched": False, "reason": "no_pending"}
        print(json.dumps(out))
        return 0
    event = data["pending"].pop(0)
    _save(path, data)
    out = {
        "matched": True,
        "decision": decision,
        "event": event,
        "message": (
            f"Approved registration for {event['title']}"
            if decision == "yes"
            else f"Skipped registration for {event['title']}"
        ),
    }
    print(json.dumps(out, ensure_ascii=False))
    return 0


def cmd_handle_reply(args: argparse.Namespace) -> int:
    decision = _normalize_reply(args.text)
    if decision is None:
        if args.json:
            print(json.dumps({"matched": False}))
        return 0
    path = Path(args.queue)
    data = _load(path)
    if not data["pending"]:
        if args.notify:
            _hermes_send("--to", "telegram", "No pending registration approval. Discovery may have already completed.")
        if args.json:
            print(json.dumps({"matched": False, "reason": "no_pending"}))
        return 0
    event = data["pending"].pop(0)
    _save(path, data)
    spawned = False
    if decision == "yes":
        msg = f"Approved: {event['title']}. Starting registration."
        handoff = build_registration_handoff(event)
        prompt = build_register_prompt(handoff)
        if args.spawn_register:
            signaltable = SIGNALTABLE_BIN if SIGNALTABLE_BIN.is_file() else Path("signaltable")
            log_dir = Path.home() / ".hermes/profiles/signaltable/logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_path = log_dir / "approval-register.log"
            log = log_path.open("a", encoding="utf-8")
            log.write(f"\n--- spawn {_now_iso()} ---\n")
            log.flush()
            subprocess.Popen(
                [
                    str(signaltable),
                    "-z",
                    prompt,
                    "--skill",
                    "event-register",
                    "--accept-hooks",
                ],
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            spawned = True
    else:
        msg = f"Skipped: {event['title']}."
    if args.json:
        print(
            json.dumps(
                {
                    "matched": True,
                    "decision": decision,
                    "event": event,
                    "spawned": spawned,
                },
                ensure_ascii=False,
            )
        )
    if args.notify:
        try:
            _hermes_send("--to", "telegram", msg)
        except OSError as exc:
            print(f"notify failed: {exc}", file=sys.stderr)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="SignalTable Telegram approval queue")
    parser.add_argument(
        "--queue",
        default=os.environ.get("SIGNALTABLE_APPROVAL_QUEUE", str(DEFAULT_QUEUE)),
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    add = sub.add_parser("add", help="Queue a pending approval")
    add.add_argument("--title", required=True)
    add.add_argument("--when", required=True)
    add.add_argument("--source", required=True)
    add.add_argument("--reason", required=True)
    add.add_argument("--url", default="")
    add.add_argument("--description", default="", help="Event description for gateway URL extraction")
    add.add_argument("--registration-url", default="")
    add.add_argument("--registration-platform", default="")
    add.add_argument("--tier", type=int, default=None)
    add.add_argument("--score", type=int, default=None)
    add.add_argument("--id", default="")
    add.add_argument("--print-message", action="store_true")
    add.add_argument("--json", action="store_true")
    add.set_defaults(func=cmd_add)

    send = sub.add_parser("send", help="Send latest queued approval via hermes send")
    send.add_argument("--to", default="telegram")
    send.add_argument("--dry-run", action="store_true")
    send.add_argument("--json", action="store_true")
    send.set_defaults(func=cmd_send)

    lst = sub.add_parser("list", help="List pending approvals")
    lst.add_argument("--json", action="store_true")
    lst.set_defaults(func=cmd_list)

    resolve = sub.add_parser("resolve", help="Resolve YES/NO against oldest pending")
    resolve.add_argument("decision")
    resolve.set_defaults(func=cmd_resolve)

    handle = sub.add_parser("handle-reply", help="Handle inbound YES/NO Telegram text")
    handle.add_argument("text")
    handle.add_argument("--notify", action="store_true")
    handle.add_argument("--spawn-register", action="store_true")
    handle.add_argument("--json", action="store_true")
    handle.set_defaults(func=cmd_handle_reply)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
