#!/usr/bin/env bash
# Hermes pre_llm_call hook: map Telegram YES/NO to pending SignalTable approvals.
set -euo pipefail

PAYLOAD="$(cat)"
USER_MSG="$(printf '%s' "$PAYLOAD" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("user_message",""))')"
PLATFORM="$(printf '%s' "$PAYLOAD" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("platform",""))')"

# Only intercept short approval replies on messaging platforms.
if [[ "$PLATFORM" != "telegram" ]]; then
  exit 0
fi

TRIMMED="$(printf '%s' "$USER_MSG" | tr '[:upper:]' '[:lower:]' | xargs)"
case "$TRIMMED" in
  yes|y|no|n|skip) ;;
  *) exit 0 ;;
esac

SCRIPT="$HOME/.hermes/profiles/signaltable/scripts/approval_queue.py"
if [[ ! -f "$SCRIPT" ]]; then
  exit 0
fi

RESULT="$("$SCRIPT" handle-reply "$USER_MSG" --notify --spawn-register --json 2>/dev/null || true)"
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
decision = data.get("decision")
event = data.get("event", {})
title = event.get("title", "event")
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
