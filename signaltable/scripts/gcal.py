#!/usr/bin/env python3
"""Google Calendar helper for the SignalTable signaltable Hermes profile.

Uses a Google service account JSON key (recommended) to list and create events
on a dedicated calendar shared with the service account email.

Environment defaults (override with CLI flags):
  GOOGLE_CREDENTIALS_FILE  path to service account JSON
  GOOGLE_CALENDAR_ID       target calendar ID

Dependencies (install in Hermes venv or system Python):
  pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

DEFAULT_CREDENTIALS = Path.home() / ".hermes/profiles/signaltable/gcal-credentials.json"
DEFAULT_TIMEZONE = "Asia/Singapore"
SCOPES = ["https://www.googleapis.com/auth/calendar"]


def _default_credentials() -> str:
    return os.environ.get("GOOGLE_CREDENTIALS_FILE", str(DEFAULT_CREDENTIALS))


def _load_service(credentials_file: str):
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError as exc:
        _die(
            "Missing Google API packages. Install with: "
            "pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib",
            code=2,
        )
        raise SystemExit from exc

    path = Path(credentials_file).expanduser()
    if not path.is_file():
        _die(f"Credentials file not found: {path}", code=2)

    creds = service_account.Credentials.from_service_account_file(
        str(path), scopes=SCOPES
    )
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def _die(message: str, code: int = 1) -> None:
    print(json.dumps({"error": message}), file=sys.stderr)
    raise SystemExit(code)


def _parse_day(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        _die(f"Invalid date '{value}'; use YYYY-MM-DD", code=2)


def _day_bounds_sgt(day: date) -> tuple[str, str]:
    iso = day.isoformat()
    return f"{iso}T00:00:00+08:00", f"{iso}T23:59:59+08:00"


def _event_start_day(event: dict[str, Any]) -> date | None:
    start = event.get("start") or {}
    if "dateTime" in start:
        return datetime.fromisoformat(start["dateTime"]).date()
    if "date" in start:
        return date.fromisoformat(start["date"])
    return None


def _normalize_title(title: str) -> str:
    return " ".join(title.strip().casefold().split())


def _list_events(
    service,
    calendar_id: str,
    date_from: date,
    date_to: date,
    query: str = "",
) -> list[dict[str, Any]]:
    time_min, _ = _day_bounds_sgt(date_from)
    _, time_max = _day_bounds_sgt(date_to)
    result = (
        service.events()
        .list(
            calendarId=calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            q=query or None,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )
    items = result.get("items") or []
    return [
        {
            "id": item.get("id"),
            "summary": item.get("summary", ""),
            "start": item.get("start", {}),
            "end": item.get("end", {}),
            "description": item.get("description", ""),
            "htmlLink": item.get("htmlLink", ""),
        }
        for item in items
    ]


def _find_duplicate(
    service,
    calendar_id: str,
    summary: str,
    start_rfc3339: str,
    date_from: date,
    date_to: date,
) -> dict[str, Any] | None:
    target_title = _normalize_title(summary)
    try:
        target_day = datetime.fromisoformat(start_rfc3339).date()
    except ValueError:
        _die(f"Invalid start datetime '{start_rfc3339}'; use RFC 3339 with offset", code=2)

    for event in _list_events(service, calendar_id, date_from, date_to, query=summary):
        if _normalize_title(event.get("summary", "")) != target_title:
            continue
        event_day = _event_start_day(event)
        if event_day == target_day:
            return event
    return None


def cmd_list(args: argparse.Namespace) -> int:
    service = _load_service(args.credentials)
    date_from = _parse_day(args.date_from)
    date_to = _parse_day(args.date_to)
    if date_to < date_from:
        _die("--to must be on or after --from", code=2)

    events = _list_events(service, args.calendar, date_from, date_to, args.q or "")
    print(json.dumps(events, indent=2))
    return 0


def cmd_create(args: argparse.Namespace) -> int:
    service = _load_service(args.credentials)
    date_from = _parse_day(args.dedup_from)
    date_to = _parse_day(args.dedup_to)

    duplicate = _find_duplicate(
        service,
        args.calendar,
        args.summary,
        args.start,
        date_from,
        date_to,
    )
    if duplicate:
        print("DUPLICATE_SKIPPED")
        return 0

    body: dict[str, Any] = {
        "summary": args.summary,
        "start": {"dateTime": args.start, "timeZone": DEFAULT_TIMEZONE},
        "end": {"dateTime": args.end, "timeZone": DEFAULT_TIMEZONE},
    }
    if args.description:
        body["description"] = args.description

    try:
        created = (
            service.events()
            .insert(calendarId=args.calendar, body=body)
            .execute()
        )
    except Exception as exc:  # googleapiclient.errors.HttpError and others
        _die(str(exc))

    print(
        json.dumps(
            {
                "id": created.get("id"),
                "summary": created.get("summary"),
                "htmlLink": created.get("htmlLink"),
                "start": created.get("start"),
                "end": created.get("end"),
            },
            indent=2,
        )
    )
    return 0


def _add_shared_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--calendar",
        default=os.environ.get("GOOGLE_CALENDAR_ID", ""),
        help="Google Calendar ID (env: GOOGLE_CALENDAR_ID)",
    )
    parser.add_argument(
        "--credentials",
        default=_default_credentials(),
        help="Service account JSON path (env: GOOGLE_CREDENTIALS_FILE)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="SignalTable Google Calendar helper (service account)"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    list_parser = sub.add_parser("list", help="List events in a date range")
    _add_shared_args(list_parser)
    list_parser.add_argument("--from", dest="date_from", required=True, help="Start date YYYY-MM-DD")
    list_parser.add_argument("--to", dest="date_to", required=True, help="End date YYYY-MM-DD")
    list_parser.add_argument("--q", default="", help="Free-text search query")
    list_parser.set_defaults(func=cmd_list)

    create_parser = sub.add_parser("create", help="Create an event (with dedup check)")
    _add_shared_args(create_parser)
    create_parser.add_argument("--summary", required=True, help="Event title")
    create_parser.add_argument(
        "--start",
        required=True,
        help="Start time RFC 3339, e.g. 2026-07-10T19:00:00+08:00",
    )
    create_parser.add_argument(
        "--end",
        required=True,
        help="End time RFC 3339, e.g. 2026-07-10T21:00:00+08:00",
    )
    create_parser.add_argument("--description", default="", help="Event description")
    create_parser.add_argument(
        "--dedup-from",
        help="Dedup window start YYYY-MM-DD (default: day before --start)",
    )
    create_parser.add_argument(
        "--dedup-to",
        help="Dedup window end YYYY-MM-DD (default: day after --start)",
    )
    create_parser.set_defaults(func=cmd_create)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.calendar:
        _die("Missing calendar ID. Set GOOGLE_CALENDAR_ID or pass --calendar.", code=2)

    if args.command == "create":
        start_day = datetime.fromisoformat(args.start).date()
        if not args.dedup_from:
            args.dedup_from = (start_day.fromordinal(start_day.toordinal() - 1)).isoformat()
        if not args.dedup_to:
            args.dedup_to = (start_day.fromordinal(start_day.toordinal() + 1)).isoformat()

    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
