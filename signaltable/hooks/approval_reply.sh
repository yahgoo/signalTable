#!/usr/bin/env bash
# Hermes pre_llm_call hook: route Telegram y/n/m to Version A shortlist, YES/NO to registration.
set -euo pipefail

PAYLOAD="$(cat)"
USER_MSG="$(printf '%s' "$PAYLOAD" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("user_message",""))')"
PLATFORM="$(printf '%s' "$PAYLOAD" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("platform",""))')"

if [[ "$PLATFORM" != "telegram" ]]; then
  exit 0
fi

TRIMMED="$(printf '%s' "$USER_MSG" | tr '[:upper:]' '[:lower:]' | xargs)"
case "$TRIMMED" in
  y|yes|n|no|skip|m|maybe) ;;
  *) exit 0 ;;
esac

ROUTER="$HOME/.hermes/profiles/signaltable/scripts/telegram_reply_router.py"
if [[ ! -f "$ROUTER" ]]; then
  exit 0
fi

RESULT="$(python3 "$ROUTER" "$USER_MSG" --live --spawn-register 2>/dev/null || true)"
MATCHED="$(printf '%s' "$RESULT" | python3 -c 'import json,sys
try:
  d=json.load(sys.stdin)
  print("1" if d.get("matched") else "")
except Exception:
  print("")' 2>/dev/null || true)"

if [[ -z "$MATCHED" ]]; then
  exit 0
fi

python3 - <<'PY' "$RESULT"
import json, sys
data = json.loads(sys.argv[1])
route = data.get("route")
event = data.get("event", {})
title = event.get("title", "event")
if route == "shortlist":
    label = data.get("label", "")
    ctx = (
        f"[SignalTable v1] Owner replied {label.upper()} for: {title}. "
        "Preference saved. Acknowledge briefly; do not register or re-send the card."
    )
else:
    decision = data.get("decision")
    if decision == "yes":
        ctx = (
            f"[SignalTable approval] Owner replied YES for: {title}. "
            "Registration has been dispatched to the signaltable profile. "
            "Acknowledge briefly; do not re-register or ask for confirmation."
        )
    else:
        ctx = (
            f"[SignalTable approval] Owner replied NO for: {title}. "
            "Skip registration and acknowledge briefly."
        )
print(json.dumps({"context": ctx}))
PY
