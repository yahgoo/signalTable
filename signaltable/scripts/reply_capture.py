#!/usr/bin/env python3
"""Capture-mode rules for Version A shortlist reply acknowledgements."""

from __future__ import annotations

CAPTURE_LIVE = "live"
CAPTURE_TEST = "test"
CAPTURE_MANUAL = "manual"

VALID_CAPTURE_MODES = frozenset({CAPTURE_LIVE, CAPTURE_TEST, CAPTURE_MANUAL})


def resolve_capture_mode(
    *,
    live: bool = False,
    dry_run_notify: bool = False,
    manual: bool = False,
) -> str:
    """Pick capture mode from CLI flags. Exactly one path should be active."""
    if sum(int(x) for x in (live, dry_run_notify, manual)) > 1:
        raise ValueError("choose only one of live, dry_run_notify, or manual capture mode")
    if live:
        return CAPTURE_LIVE
    if manual:
        return CAPTURE_MANUAL
    return CAPTURE_TEST


def telegram_send_allowed(capture_mode: str) -> bool:
    return capture_mode in {CAPTURE_LIVE, CAPTURE_MANUAL}


def cli_notify_error() -> str:
    return (
        "Refusing Telegram send: --notify is only for live inbound replies. "
        "Use --live with telegram_reply_router (Hermes plugin/hooks), "
        "or --dry-run-notify for SSH/local tests, "
        "or version_a.py handle-reply --notify for explicit MANUAL CLI acks."
    )
