#!/usr/bin/env python3
"""Conservative food-status detection for Version A event cards."""

from __future__ import annotations

import argparse
import json
import re
from typing import Any

FOOD_PROVIDED = "provided"
FOOD_DRINKS_SNACKS = "drinks_snacks"
FOOD_NOT_PROVIDED = "not_provided"
FOOD_NOT_MENTIONED = "not_mentioned"

FOOD_CARD_LABELS = {
    FOOD_PROVIDED: "Provided",
    FOOD_DRINKS_SNACKS: "Drinks/snacks mentioned",
    FOOD_NOT_PROVIDED: "Not provided",
    FOOD_NOT_MENTIONED: "Not mentioned",
}

FOOD_NEGATIVE_PHRASES = (
    "no food",
    "no refreshments",
    "no snacks",
    "no drinks",
    "refreshments not provided",
    "food not provided",
    "food will not be provided",
    "bring your own food",
)

FOOD_PROVIDED_TERMS = (
    " lunch",
    " dinner",
    " breakfast",
    " brunch",
    " meal",
    " meals",
    " catering",
    " pizza",
    " buffet",
    " free food",
    " food provided",
    " food included",
    " food and drink",
    " food & drink",
    " food and drinks",
    " served dinner",
    " served lunch",
)

FOOD_DRINKS_SNACKS_TERMS = (
    " snacks",
    " snack",
    " refreshments",
    " drinks",
    " light bites",
    " coffee and",
    " tea and",
    " beverages",
)

FOOD_GENERIC_PROVIDED_TERMS = (
    " food",
    "food provided",
)


def _norm_text(value: Any) -> str:
    text = str(value or "").lower().replace("&", " and ")
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def food_source_text(event: dict[str, Any]) -> str:
    """Text fields used for food detection. Venue/address are excluded on purpose."""
    parts = [
        event.get("title"),
        event.get("description"),
        event.get("summary"),
        event.get("agenda"),
        event.get("food"),
        event.get("food_notes"),
        " ".join(str(t) for t in (event.get("raw_tags") or [])),
    ]
    return f" {' '.join(_norm_text(p) for p in parts if p)} "


def _contains_phrase(text: str, phrase: str) -> bool:
    phrase = phrase.strip().lower()
    if not phrase:
        return False
    if " " in phrase:
        return phrase in text
    return re.search(rf"\b{re.escape(phrase)}\b", text) is not None


def _contains_any(text: str, terms: tuple[str, ...]) -> str | None:
    for term in terms:
        if _contains_phrase(text, term.strip()):
            return term.strip()
    return None


def detect_food_status(event: dict[str, Any]) -> dict[str, str]:
    """Return food_status, food_card_line, and food_evidence."""
    text = food_source_text(event)

    negative = _contains_any(text, FOOD_NEGATIVE_PHRASES)
    if negative:
        return {
            "food_status": FOOD_NOT_PROVIDED,
            "food_card_line": f"Food: {FOOD_CARD_LABELS[FOOD_NOT_PROVIDED]}",
            "food_evidence": f"explicit: {negative}",
        }

    provided = _contains_any(text, FOOD_PROVIDED_TERMS)
    if provided:
        return {
            "food_status": FOOD_PROVIDED,
            "food_card_line": f"Food: {FOOD_CARD_LABELS[FOOD_PROVIDED]}",
            "food_evidence": f"mentions {provided.strip()}",
        }

    generic = _contains_any(text, FOOD_GENERIC_PROVIDED_TERMS)
    if generic:
        return {
            "food_status": FOOD_PROVIDED,
            "food_card_line": f"Food: {FOOD_CARD_LABELS[FOOD_PROVIDED]}",
            "food_evidence": f"mentions {generic.strip()}",
        }

    light = _contains_any(text, FOOD_DRINKS_SNACKS_TERMS)
    if light:
        return {
            "food_status": FOOD_DRINKS_SNACKS,
            "food_card_line": f"Food: {FOOD_CARD_LABELS[FOOD_DRINKS_SNACKS]}",
            "food_evidence": f"mentions {light.strip()}",
        }

    return {
        "food_status": FOOD_NOT_MENTIONED,
        "food_card_line": f"Food: {FOOD_CARD_LABELS[FOOD_NOT_MENTIONED]}",
        "food_evidence": "",
    }


def apply_food_status(event: dict[str, Any]) -> dict[str, Any]:
    """Attach food_status fields to an event dict."""
    info = detect_food_status(event)
    event.update(info)
    return event


def food_score_delta(food_status: str) -> tuple[int, str]:
    if food_status == FOOD_PROVIDED:
        return 1, "food provided (+1)"
    return 0, ""


def run_self_test() -> int:
    samples = [
        (
            {"title": "AI Lunch and Learn", "description": "Talk plus lunch included."},
            FOOD_PROVIDED,
            "Provided",
        ),
        (
            {"title": "Data Meetup", "description": "Light refreshments and snacks available."},
            FOOD_DRINKS_SNACKS,
            "Drinks/snacks mentioned",
        ),
        (
            {"title": "Workshop", "description": "No food provided. BYO water."},
            FOOD_NOT_PROVIDED,
            "Not provided",
        ),
        (
            {"title": "GPU inference night", "description": "Hands-on session on batching."},
            FOOD_NOT_MENTIONED,
            "Not mentioned",
        ),
        (
            {
                "title": "Meetup",
                "description": "Networking.",
                "venue_name": "Food Republic Singapore",
            },
            FOOD_NOT_MENTIONED,
            "Not mentioned",
        ),
    ]

    checks = {}
    for idx, (event, status, label) in enumerate(samples):
        info = detect_food_status(event)
        checks[f"sample_{idx}_status"] = info["food_status"] == status
        checks[f"sample_{idx}_label"] = label in info["food_card_line"]
        checks[f"sample_{idx}_one_line"] = info["food_card_line"].count("\n") == 0

    checks["score_boost_provided"] = food_score_delta(FOOD_PROVIDED)[0] == 1
    checks["score_boost_snacks"] = food_score_delta(FOOD_DRINKS_SNACKS)[0] == 0
    checks["score_boost_unknown"] = food_score_delta(FOOD_NOT_MENTIONED)[0] == 0

    payload = {"checks": checks, "pass": all(checks.values())}
    print(json.dumps(payload, indent=2))
    return 0 if payload["pass"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Food status detection for Version A")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return run_self_test()
    parser.error("--self-test required")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
