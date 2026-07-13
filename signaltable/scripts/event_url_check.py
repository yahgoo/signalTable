#!/usr/bin/env python3
"""Canonical event page URLs and lightweight URL audit for Version A debug."""

from __future__ import annotations

import json
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

GATEWAY_HOSTS = frozenset(
    {
        "konfhub.com",
        "konfhub.io",
        "forms.gle",
        "typeform.com",
    }
)

REVIEW_FLAGS = frozenset(
    {
        "missing_url",
        "duplicate_url",
        "unreachable",
        "synthetic_fixture",
        "gateway_only_source",
        "registration_url_differs",
    }
)


def _first_str(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def normalize_url(url: str) -> str:
    return (url or "").strip().lower().rstrip("/").split("#", 1)[0]


def canonical_event_url(event: dict[str, Any]) -> str:
    """Return the source event page URL, not a registration gateway when possible."""
    page = _first_str(event.get("event_page_url"), event.get("url"), event.get("source_url"))
    if page:
        return page
    return _first_str(event.get("registration_url"))


def _host(url: str) -> str:
    from urllib.parse import urlparse

    return (urlparse(url).netloc or "").lower().removeprefix("www.")


def _is_gateway_only(url: str) -> bool:
    host = _host(url)
    return any(host == gateway or host.endswith(f".{gateway}") for gateway in GATEWAY_HOSTS)


def probe_url(url: str, *, timeout: float = 8.0) -> tuple[str, str]:
    """Return (status, detail) without raising."""
    if not url:
        return "missing", "no URL"
    try:
        req = Request(url, method="HEAD", headers={"User-Agent": "SignalTable/1.0 URL audit"})
        with urlopen(req, timeout=timeout) as resp:
            code = getattr(resp, "status", None) or resp.getcode()
        if code and code >= 400:
            return "unreachable", f"HTTP {code}"
        return "ok", f"HTTP {code}"
    except HTTPError as exc:
        if exc.code in {405, 501}:
            return probe_url_get(url, timeout=timeout)
        if exc.code == 404:
            return "unreachable", "HTTP 404"
        if exc.code >= 400:
            return "unreachable", f"HTTP {exc.code}"
        return "ok", f"HTTP {exc.code}"
    except URLError as exc:
        reason = getattr(exc, "reason", exc)
        return "unreachable", str(reason)
    except Exception as exc:  # pragma: no cover - defensive
        return "unreachable", str(exc)


def probe_url_get(url: str, *, timeout: float = 8.0) -> tuple[str, str]:
    try:
        req = Request(url, headers={"User-Agent": "SignalTable/1.0 URL audit"})
        with urlopen(req, timeout=timeout) as resp:
            code = getattr(resp, "status", None) or resp.getcode()
        if code and code >= 400:
            return "unreachable", f"HTTP {code}"
        return "ok", f"HTTP {code}"
    except HTTPError as exc:
        if exc.code == 404:
            return "unreachable", "HTTP 404"
        if exc.code >= 400:
            return "unreachable", f"HTTP {exc.code}"
        return "ok", f"HTTP {exc.code}"
    except URLError as exc:
        return "unreachable", str(reason if (reason := getattr(exc, "reason", exc)) else exc)
    except Exception as exc:  # pragma: no cover
        return "unreachable", str(exc)


def audit_event_urls(
    events: list[dict[str, Any]],
    *,
    probe_network: bool = False,
) -> list[dict[str, Any]]:
    """Flag URL issues for manual review. Never mutates or drops events."""
    url_counts: dict[str, int] = {}
    normalized: list[str] = []
    for event in events:
        url = canonical_event_url(event)
        key = normalize_url(url)
        normalized.append(key)
        if key:
            url_counts[key] = url_counts.get(key, 0) + 1

    audits: list[dict[str, Any]] = []
    for idx, event in enumerate(events):
        url = canonical_event_url(event)
        key = normalize_url(url)
        flags: list[str] = []
        is_synthetic = bool(event.get("synthetic_fixture"))

        # Synthetic fixtures are known intentional placeholders — flag explicitly
        # so they are never confused with real stale/broken URLs.
        if is_synthetic:
            flags.append("synthetic_fixture")

        if not url:
            flags.append("missing_url")
        if key and url_counts.get(key, 0) > 1:
            flags.append("duplicate_url")
        reg = _first_str(event.get("registration_url"))
        if url and reg and normalize_url(url) != normalize_url(reg) and _is_gateway_only(reg):
            flags.append("registration_url_differs")
        elif url and _is_gateway_only(url):
            flags.append("gateway_only_source")

        probe_status = ""
        probe_detail = ""
        if probe_network and url:
            if is_synthetic:
                # Probing synthetic fixtures is expected to 404; note it without
                # treating it as an actionable production issue.
                probe_status, probe_detail = probe_url(url)
                probe_detail = f"{probe_detail} [synthetic fixture — expected]"
            else:
                probe_status, probe_detail = probe_url(url)
                if probe_status == "unreachable":
                    flags.append("unreachable")

        audits.append(
            {
                "index": idx + 1,
                "title": _first_str(event.get("title"), "Untitled"),
                "platform": _first_str(event.get("source"), event.get("platform")),
                "canonical_url": url,
                "registration_url": reg,
                "synthetic_fixture": is_synthetic,
                "flags": flags,
                "review": any(flag in REVIEW_FLAGS for flag in flags),
                "probe_status": probe_status or None,
                "probe_detail": probe_detail or None,
            }
        )
    return audits


def format_url_audit_lines(audits: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for row in audits:
        if not row.get("review"):
            continue
        flags = row.get("flags") or []
        flag_str = ", ".join(flags)
        url = row.get("canonical_url") or "no URL"
        if row.get("synthetic_fixture"):
            lines.append(
                f"url_review #{row.get('index')} {row.get('title')}: {flag_str} "
                f"[SYNTHETIC FIXTURE — placeholder URL not a real event] ({url})"
            )
        else:
            lines.append(
                f"url_review #{row.get('index')} {row.get('title')}: {flag_str} ({url})"
            )
    return lines


def self_test_checks() -> dict[str, bool]:
    meetup = {
        "source": "meetup",
        "title": "Singapore dbt Meetup",
        "event_page_url": "https://www.meetup.com/singapore-dbt-meetup/events/315295343/",
        "url": "https://www.meetup.com/singapore-dbt-meetup/events/315295343/",
        "registration_url": "https://konfhub.com/e/sg-dbt-meetup-jul-2026",
    }
    gateway_only = {
        "source": "meetup",
        "title": "Gateway only",
        "registration_url": "https://konfhub.com/e/only-source",
    }
    dup_a = {"title": "A", "url": "https://luma.com/foo"}
    dup_b = {"title": "B", "url": "https://luma.com/foo/"}

    # Synthetic fixture cases — must be labeled synthetic, never "unreachable"
    synthetic = {
        "source": "luma",
        "title": "LLM Eval Night: Reliable AI Pipelines for Production",
        "url": "https://luma.com/llm-eval-night-sg",
        "synthetic_fixture": True,
    }
    synthetic_audit = audit_event_urls([synthetic])[0]
    synthetic_audit_no_probe = audit_event_urls([synthetic], probe_network=False)[0]

    # Luma compact item: url (not source_url) must survive normalize_canonical
    from luma_normalize import normalize_canonical as _luma_norm
    luma_compact = {
        "source": "luma",
        "start_time": "2026-07-22T19:00:00+08:00",
        "title": "LLM Test",
        "url": "https://luma.com/llm-eval-night-sg",
        "city": "Singapore",
        "country": "SG",
        "is_free": True,
        "is_in_person": True,
    }
    luma_norm = _luma_norm(luma_compact, source_query="data")

    return {
        "prefers_event_page": canonical_event_url(meetup)
        == "https://www.meetup.com/singapore-dbt-meetup/events/315295343/",
        "not_registration_url": "konfhub.com" not in canonical_event_url(meetup),
        "gateway_fallback": canonical_event_url(gateway_only) == "https://konfhub.com/e/only-source",
        "duplicate_flag": "duplicate_url"
        in (audit_event_urls([dup_a, dup_b])[1].get("flags") or []),
        "missing_flag": "missing_url" in (audit_event_urls([{}])[0].get("flags") or []),
        "registration_differs_flag": "registration_url_differs"
        in (audit_event_urls([meetup])[0].get("flags") or []),
        # Synthetic fixture: flagged as synthetic, NOT as unreachable (no probe needed)
        "synthetic_flagged": "synthetic_fixture" in (synthetic_audit_no_probe.get("flags") or []),
        "synthetic_not_unreachable_without_probe": "unreachable"
        not in (synthetic_audit_no_probe.get("flags") or []),
        "synthetic_flag_in_review": synthetic_audit_no_probe.get("review") is True,
        "synthetic_label_in_format_line": "[SYNTHETIC FIXTURE"
        in "\n".join(format_url_audit_lines([synthetic_audit_no_probe])),
        # Luma normalize_canonical: url field must survive for compact items
        "luma_compact_url_preserved": luma_norm.get("url") == "https://luma.com/llm-eval-night-sg",
        "luma_compact_event_page_url_set": luma_norm.get("event_page_url") == "https://luma.com/llm-eval-night-sg",
    }


def run_self_test() -> int:
    checks = self_test_checks()
    payload = {"checks": checks, "pass": all(checks.values())}
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if payload["pass"] else 1


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Event URL canonicalization and audit")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return run_self_test()
    parser.error("--self-test required")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
