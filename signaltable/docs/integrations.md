# SignalTable Integrations Status

Last updated: 2026-07-03

| Integration | Purpose | Method | Status | Notes |
|---|---|---|---|---|
| Hermes Profile | Isolated agent for signaltable | `hermes profile create signaltable --clone` | pending | |
| GLM-5.2 / TokenHub | Main reasoning model | Already in config.yaml | active | URL: tokenhub-intl.tencentcloudmaas.com/v1 |
| Telegram Gateway | Owner notifications, approvals | systemd (default profile) | active | signaltable_bot, user 1697120790 |
| Scrapling | Web scraping for event discovery | `hermes skills install official/research/scrapling` | pending | |
| LobsterMail MCP | Agent email inbox + injection scanner | `npx @lobsterkit/lobstermail-mcp@latest` via mcp_servers config | pending | Needs: LM_API_KEY or auto-signup |
| PortEden MCP | Google Calendar read/write | `npx mcp-remote https://mcp.porteden.com/calendar` via mcp_servers | pending | OAuth on first tool call |
| Steel Browser | Headless browser for event registration | `browser.cloud_provider: steel` + STEEL_API_KEY | pending | Needs: STEEL_API_KEY |
| native-mcp | MCP server support | Built into Hermes (hermes mcp) | active | No extra install needed |
| hermes setup | Hermes configuration tool | Built into Hermes (`hermes setup`) | active | No separate install; use `hermes setup tools` to configure browser |

## Secrets Required from Owner

| Secret | Where to get it | Where it goes |
|--------|----------------|---------------|
| SSH password | (owner knows) | Needed to SSH into VPS |
| STEEL_API_KEY | https://app.steel.dev/ | `~/.hermes/profiles/signaltable/.env` |
| PE_API_KEY | https://my.porteden.com → API Keys | `~/.hermes/profiles/signaltable/.env` |
| LOBSTERMAIL_API_KEY | Auto-generated on first run (or https://app.lobstermail.ai) | `~/.hermes/profiles/signaltable/.env` |
| PORTEDEN_CALENDAR_ID | `porteden calendar calendars -jc` after auth | `~/.hermes/profiles/signaltable/.env` |
| SIGNALTABLE_FULL_NAME | Your name for event registration | `~/.hermes/profiles/signaltable/.env` |

## Config File Locations (on VPS)

| File | Path | Purpose |
|------|------|---------|
| Profile config | `~/.hermes/profiles/signaltable/config.yaml` | All Hermes settings for this profile |
| Secrets | `~/.hermes/profiles/signaltable/.env` | API keys and bot tokens |
| Identity | `~/.hermes/profiles/signaltable/SOUL.md` | Agent persona and rules |
| Skills | `~/.hermes/profiles/signaltable/skills/` | Custom skills for this project |
| Cron jobs | `~/.hermes/profiles/signaltable/cron/` | Scheduled task definitions |
| Log | `~/.hermes/profiles/signaltable/logs/signaltable.log` | Main operation log |
| Events seen | `~/.hermes/profiles/signaltable/logs/events-seen.jsonl` | Deduplication cache |
| Plan log | `~/.hermes/profiles/signaltable/plan-log.md` | This transition plan |
| Integrations | `~/.hermes/profiles/signaltable/integrations.md` | This file |
| Comparison | `~/.hermes/profiles/signaltable/comparison.csv` | Hermes vs Apify/MuleRun results |

## Backup Locations

| Backup | Path |
|--------|------|
| Pre-setup full backup | `~/hermes-backup-YYYYMMDD.tar.gz` |
| Pre-GLM52 backup | `/Users/kmsum/Downloads/Hermes/hermes-backup-full-before-GLM52.zip` (local) |
