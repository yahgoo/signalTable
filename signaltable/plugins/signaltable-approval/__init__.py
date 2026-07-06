"""SignalTable approval gateway plugin — handle YES/NO before the default agent."""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

QUEUE_SCRIPT = Path.home() / ".hermes/profiles/signaltable/scripts/approval_queue.py"


def _platform_name(source: Any) -> str:
    if source is None:
        return ""
    platform = getattr(source, "platform", None)
    if platform is None:
        return ""
    value = getattr(platform, "value", None)
    if value:
        return str(value).lower()
    return str(platform).lower()


def _normalize_reply(text: str) -> bool:
    token = (text or "").strip().upper()
    return token in {"YES", "Y", "NO", "N", "SKIP"}


def on_pre_gateway_dispatch(event=None, **kwargs: Any) -> dict[str, str] | None:
    if event is None:
        return None

    text = getattr(event, "text", "") or ""
    if not _normalize_reply(text):
        return None

    source = getattr(event, "source", None)
    platform = _platform_name(source)
    if platform and platform != "telegram":
        return None

    if not QUEUE_SCRIPT.is_file():
        logger.warning("signaltable-approval: queue script missing at %s", QUEUE_SCRIPT)
        return None

    try:
        result = subprocess.run(
            [
                sys.executable,
                str(QUEUE_SCRIPT),
                "handle-reply",
                text,
                "--notify",
                "--spawn-register",
                "--json",
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except Exception as exc:
        logger.warning("signaltable-approval: handle-reply failed: %s", exc)
        return None

    if result.returncode != 0:
        logger.warning(
            "signaltable-approval: handle-reply exit %s stderr=%s",
            result.returncode,
            (result.stderr or result.stdout or "")[:400],
        )
        return None

    try:
        data = json.loads((result.stdout or "").strip() or "{}")
    except json.JSONDecodeError:
        logger.warning("signaltable-approval: invalid JSON from handle-reply")
        return None

    if not data.get("matched"):
        return None

    title = (data.get("event") or {}).get("title", "event")
    decision = data.get("decision", "")
    logger.info("signaltable-approval: %s for %s", decision, title)
    return {
        "action": "skip",
        "reason": f"signaltable approval {decision} for {title}",
    }


def register(ctx) -> None:
    ctx.register_hook("pre_gateway_dispatch", on_pre_gateway_dispatch)
