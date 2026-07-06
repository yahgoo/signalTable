#!/bin/bash
# ============================================================
# SignalTable Deployment Script
# Run this on the Tencent VPS as user 'ubuntu':
#   bash deploy.sh
# ============================================================
set -e

PROFILE="signaltable"
HERMES_HOME="${HOME}/.hermes"
PROFILE_DIR="${HOME}/.hermes/profiles/${PROFILE}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PARENT_DIR="$(dirname "${SCRIPT_DIR}")"
LOG="${PROFILE_DIR}/logs/setup.log"

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║   SignalTable Deployment Script          ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# ── 0. Pre-flight ────────────────────────────────────────────
if ! command -v hermes &>/dev/null; then
  echo "ERROR: hermes not found in PATH. Ensure Hermes is installed via pipx." >&2
  exit 1
fi

HERMES_VERSION=$(hermes --version 2>/dev/null || echo "unknown")
echo "  ✅ Hermes found: ${HERMES_VERSION}"

# ── 1. Full backup ───────────────────────────────────────────
echo ""
echo "Step 1/9: Taking full Hermes backup..."
BACKUP_FILE="${HOME}/hermes-backup-$(date +%Y%m%d-%H%M%S).tar.gz"
tar -czf "${BACKUP_FILE}" -C "${HOME}" .hermes 2>/dev/null || true
echo "  ✅ Backup saved to: ${BACKUP_FILE}"

# ── 2. Create signaltable profile ────────────────────────────
echo ""
echo "Step 2/9: Creating '${PROFILE}' profile..."
if hermes profile list 2>/dev/null | grep -q "^${PROFILE}"; then
  echo "  ℹ️  Profile '${PROFILE}' already exists — skipping creation."
else
  hermes profile create "${PROFILE}" --clone
  echo "  ✅ Profile '${PROFILE}' created at ${PROFILE_DIR}"
fi

# Create log directory
mkdir -p "${PROFILE_DIR}/logs"
touch "${PROFILE_DIR}/logs/signaltable.log"
touch "${PROFILE_DIR}/logs/events-seen.jsonl"
echo "  ✅ Log files initialized."

# Start logging setup
echo "[$(date '+%Y-%m-%d %H:%M:%S %Z')] DEPLOY: Starting SignalTable deployment v1" >> "${LOG}" 2>/dev/null || true

# ── 3. Deploy SOUL.md ─────────────────────────────────────────
echo ""
echo "Step 3/9: Deploying SOUL.md..."
if [ -f "${PARENT_DIR}/SOUL.md" ]; then
  cp -f "${PARENT_DIR}/SOUL.md" "${PROFILE_DIR}/SOUL.md"
  echo "  ✅ SOUL.md deployed."
else
  echo "  ⚠️  SOUL.md not found in ${PARENT_DIR}. Skipping."
fi

# ── 4. Deploy skills ─────────────────────────────────────────
echo ""
echo "Step 4/9: Deploying custom skills..."
SKILLS_DEST="${PROFILE_DIR}/skills"
mkdir -p "${SKILLS_DEST}"

for skill_file in "${PARENT_DIR}/skills/"*.md; do
  skill_name=$(basename "${skill_file}" .md)
  dest="${SKILLS_DEST}/${skill_name}"
  mkdir -p "${dest}"
  cp -f "${skill_file}" "${dest}/SKILL.md"
  echo "  ✅ Skill deployed: ${skill_name}"
done

# ── 5. Install optional Scrapling skill ──────────────────────
echo ""
echo "Step 5/9: Installing Scrapling skill..."
if hermes -p "${PROFILE}" skills list 2>/dev/null | grep -q "scrapling"; then
  echo "  ℹ️  Scrapling already installed."
else
  hermes -p "${PROFILE}" skills install official/research/scrapling && \
    echo "  ✅ Scrapling skill installed." || \
    echo "  ⚠️  Scrapling install failed. Install manually: hermes -p ${PROFILE} skills install official/research/scrapling"
fi

# Install Scrapling Python package + browser binaries (required for stealth mode)
echo "  Installing Scrapling Python dependencies..."
HERMES_PIP="/home/ubuntu/.local/share/pipx/venvs/hermes-agent/bin/pip"
if [ -f "${HERMES_PIP}" ]; then
  "${HERMES_PIP}" install --quiet "scrapling[all]" 2>/dev/null && echo "  ✅ scrapling[all] installed in Hermes venv." || true
else
  pip3 install --quiet "scrapling[all]" 2>/dev/null && echo "  ✅ scrapling[all] installed." || true
fi
# Install browser binaries for Scrapling (camoufox + playwright)
python3 -m scrapling install 2>/dev/null && echo "  ✅ Scrapling browsers installed." || \
  echo "  ⚠️  scrapling install (browser binaries) failed. Run manually: python3 -m scrapling install"

# ── 6. Install PortEden CLI ───────────────────────────────────
echo ""
echo "Step 6/9: Installing PortEden CLI..."
if command -v porteden &>/dev/null; then
  echo "  ℹ️  porteden already installed: $(porteden --version 2>/dev/null)"
else
  echo "  Installing porteden CLI..."
  curl -sSfL https://raw.githubusercontent.com/porteden/cli/main/install.sh | bash && \
    echo "  ✅ porteden installed." || \
    echo "  ⚠️  porteden install failed. Manual install: curl -sSfL https://raw.githubusercontent.com/porteden/cli/main/install.sh | bash"
fi

# ── 7. Add LobsterMail MCP to profile config ─────────────────
echo ""
echo "Step 7/9: Configuring LobsterMail MCP..."
PROFILE_CONFIG="${PROFILE_DIR}/config.yaml"

if grep -q "lobstermail" "${PROFILE_CONFIG}" 2>/dev/null; then
  echo "  ℹ️  LobsterMail MCP already in config."
else
  # Check if node/npx is available
  if ! command -v npx &>/dev/null; then
    echo "  ⚠️  npx not found. Installing Node.js..."
    curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash - && \
      sudo apt-get install -y nodejs && \
      echo "  ✅ Node.js installed." || \
      echo "  ⚠️  Node.js install failed. Install manually: https://nodejs.org"
  fi

  # Add LobsterMail MCP to config using Python (safe YAML manipulation)
  python3 - "${PROFILE_CONFIG}" << 'PYEOF'
import sys, re

config_path = sys.argv[1]
try:
    with open(config_path, 'r') as f:
        content = f.read()
except FileNotFoundError:
    content = ""

if "lobstermail" in content:
    print("  Already configured.")
    sys.exit(0)

mcp_block = """
mcp_servers:
  lobstermail:
    command: "npx"
    args: ["-y", "@lobsterkit/lobstermail-mcp@latest"]
"""

# Insert mcp_servers block if not present
if "mcp_servers:" not in content:
    content += mcp_block
else:
    # Add to existing mcp_servers block
    content = content.replace("mcp_servers:", "mcp_servers:\n  lobstermail:\n    command: \"npx\"\n    args: [\"-y\", \"@lobsterkit/lobstermail-mcp@latest\"]", 1)

with open(config_path, 'w') as f:
    f.write(content)
print("  LobsterMail MCP added to config.")
PYEOF
  echo "  ✅ LobsterMail MCP configured."
fi

# ── 8. Deploy env template (if .env doesn't exist) ───────────
echo ""
echo "Step 8/9: Setting up .env file..."
PROFILE_ENV="${PROFILE_DIR}/.env"
if [ -f "${PROFILE_ENV}" ]; then
  echo "  ℹ️  .env already exists. Checking for missing keys..."
  # Add any missing keys from template
  if [ -f "${PARENT_DIR}/env-template.env" ]; then
    while IFS= read -r line; do
      # Skip comments and empty lines
      [[ "$line" =~ ^#.*$ ]] && continue
      [[ -z "$line" ]] && continue
      KEY="${line%%=*}"
      if ! grep -q "^${KEY}=" "${PROFILE_ENV}" 2>/dev/null; then
        echo "${line}" >> "${PROFILE_ENV}"
        echo "  + Added missing key: ${KEY}"
      fi
    done < <(grep -v '^#' "${PARENT_DIR}/env-template.env" | grep '=')
  fi
else
  if [ -f "${PARENT_DIR}/env-template.env" ]; then
    cp "${PARENT_DIR}/env-template.env" "${PROFILE_ENV}"
    echo "  ✅ .env template deployed to ${PROFILE_ENV}"
    echo "  ⚠️  ACTION REQUIRED: Edit ${PROFILE_ENV} and fill in real API keys."
  else
    touch "${PROFILE_ENV}"
    echo "  ✅ Empty .env created."
  fi
fi

# ── 9. Deploy documentation files ────────────────────────────
echo ""
echo "Step 9/9: Deploying documentation files..."
for doc in plan-log.md integrations.md comparison.csv; do
  if [ -f "${PARENT_DIR}/docs/${doc}" ]; then
    cp -f "${PARENT_DIR}/docs/${doc}" "${PROFILE_DIR}/${doc}"
    echo "  ✅ ${doc} deployed."
  fi
done

# ── Summary ──────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════╗"
echo "║   Deployment Complete                    ║"
echo "╚══════════════════════════════════════════╝"
echo ""
echo "Profile directory: ${PROFILE_DIR}"
echo "Backup:            ${BACKUP_FILE}"
echo ""
echo "NEXT STEPS (manual actions required):"
echo ""
echo "  1. Edit your API keys:"
echo "     nano ${PROFILE_ENV}"
echo "     Required keys: STEEL_API_KEY, SIGNALTABLE_FULL_NAME"
echo ""
echo "  2. Add Steel browser config to ${PROFILE_DIR}/config.yaml:"
echo "     ${PROFILE} config set browser.cloud_provider steel"
echo ""
echo "  3. Authenticate PortEden (first tool call will prompt OAuth in browser):"
echo "     ${PROFILE} chat \"List my Google Calendars using PortEden\""
echo "     Then set PORTEDEN_CALENDAR_ID in ${PROFILE_ENV}"
echo ""
echo "  4. Run smoke tests:"
echo "     ${PROFILE} doctor"
echo "     ${PROFILE} chat \"Run a quick smoke test of the event-discovery skill\""
echo ""
echo "  5. Set up cron job (after smoke tests pass):"
echo "     ${PROFILE} cron create \"0 0 * * *\" \\"
echo "       \"Run event-discovery, register Tier 1 events, parse emails, update calendar, send Telegram digest\" \\"
echo "       --skill event-discovery --skill event-register --skill email-parser \\"
echo "       --skill calendar-updater --skill telegram-reporter \\"
echo "       --name signaltable-daily"
echo ""
echo "See ${PROFILE_DIR}/plan-log.md for the full 20-day transition plan."
echo ""

echo "[$(date '+%Y-%m-%d %H:%M:%S %Z')] DEPLOY: Deployment script completed." >> "${LOG}" 2>/dev/null || true
