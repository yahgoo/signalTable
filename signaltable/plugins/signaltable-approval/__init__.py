"""SignalTable gateway plugin — Version A shortlist y/n/m, then registration YES/NO."""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ROUTER_SCRIPT = Path.home() / ".hermes/profiles/signaltable/scripts/telegram_reply_router.py"


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


def _looks_like_reply(text: str) -> bool:
    token = (text or "").strip().lower()
    return token in {"y", "yes", "n", "no", "skip", "m", "maybe"}


def on_pre_gateway_dispatch(event=None, **kwargs: Any) -> dict[str, str] | None:
    if event is None:
        return None

    text = getattr(event, "text", "") or ""
    if not _looks_like_reply(text):
        return None

    source = getattr(event, "source", None)
    platform = _platform_name(source)
    if platform and platform != "telegram":
        return None

    if not ROUTER_SCRIPT.is_file():
        logger.warning("signaltable-approval: router missing at %s", ROUTER_SCRIPT)
        return None

    try:
        result = subprocess.run(
            [
                sys.executable,
                str(ROUTER_SCRIPT),
                text,
                "--live",
                "--spawn-register",
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except Exception as exc:
        logger.warning("signaltable-approval: router failed: %s", exc)
        return None

    if result.returncode != 0:
        logger.warning(
            "signaltable-approval: router exit %s stderr=%s",
            result.returncode,
            (result.stderr or result.stdout or "")[:400],
        )
        return None

    try:
        data = json.loads((result.stdout or "").strip() or "{}")
    except json.JSONDecodeError:
        logger.warning("signaltable-approval: invalid JSON from router")
        return None

    if not data.get("matched"):
        return None

    route = data.get("route", "unknown")
    if route == "shortlist":
        title = (data.get("event") or {}).get("title", "event")
        label = data.get("label", "")
        logger.info("signaltable shortlist: %s for %s", label, title)
        return {
            "action": "skip",
            "reason": f"signaltable v1 feedback {label} for {title}",
        }

    title = (data.get("event") or {}).get("title", "event")
    decision = data.get("decision", "")
    logger.info("signaltable approval: %s for %s", decision, title)
    return {
        "action": "skip",
        "reason": f"signaltable approval {decision} for {title}",
    }


def register(ctx) -> None:
    ctx.register_hook("pre_gateway_dispatch", on_pre_gateway_dispatch)
