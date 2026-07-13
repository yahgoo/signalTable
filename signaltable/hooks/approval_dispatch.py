#!/usr/bin/env python3
"""Hermes pre_gateway_dispatch hook: Version A shortlist + registration approval routing."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT = Path.home() / ".hermes/profiles/signaltable/scripts/telegram_reply_router.py"


def _load_payload() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _event_text(payload: dict[str, Any]) -> str:
    extra = payload.get("extra") or {}
    event = extra.get("event")
    if isinstance(event, dict):
        return str(event.get("text") or "")
    if isinstance(event, str):
        for pattern in (
            r"\btext='([^']*)'",
            r'\btext="([^"]*)"',
            r"\btext=([^,\)]+)",
        ):
            match = re.search(pattern, event)
            if match:
                return match.group(1).strip()
    return ""


def _event_platform(payload: dict[str, Any]) -> str:
    extra = payload.get("extra") or {}
    event = extra.get("event")
    if isinstance(event, dict):
        source = event.get("source") or {}
        if isinstance(source, dict):
            platform = source.get("platform")
            if isinstance(platform, dict):
                return str(platform.get("value") or platform.get("name") or "")
            return str(platform or "")
    if isinstance(event, str):
        match = re.search(r"platform=<Platform\.(\w+)", event)
        if match:
            return match.group(1).lower()
        match = re.search(r"Platform\.(\w+)", event)
        if match:
            return match.group(1).lower()
    return ""


def _looks_like_reply(text: str) -> bool:
    token = text.strip().lower()
    return token in {"y", "yes", "n", "no", "skip", "m", "maybe"}


def main() -> int:
    payload = _load_payload()
    text = _event_text(payload).strip()
    platform = _event_platform(payload).strip().lower()

    if platform and platform != "telegram":
        return 0

    if not _looks_like_reply(text):
        return 0

    if not SCRIPT.is_file():
        return 0

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            text,
            "--live",
            "--spawn-register",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        print(result.stderr or result.stdout, file=sys.stderr)
        return 0

    try:
        data = json.loads((result.stdout or "").strip() or "{}")
    except json.JSONDecodeError:
        return 0

    if not data.get("matched"):
        return 0

    route = data.get("route", "unknown")
    if route == "shortlist":
        label = data.get("label", "")
        title = (data.get("event") or {}).get("title", "event")
        print(
            json.dumps(
                {
                    "action": "skip",
                    "reason": f"signaltable v1 feedback {label} for {title}",
                }
            )
        )
        return 0

    decision = data.get("decision", "")
    title = (data.get("event") or {}).get("title", "event")
    print(
        json.dumps(
            {
                "action": "skip",
                "reason": f"signaltable approval {decision} for {title}",
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
