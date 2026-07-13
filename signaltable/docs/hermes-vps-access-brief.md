# Hermes VPS Access Brief — reuse for NightDesk

> Reuse of existing Hermes-on-Tencent-VPS setup for a new project, "NightDesk" (After-Hours Booking Nurturer). No secrets included — only env var names and placeholder tags.

## 1. VPS Details
- **Provider:** Tencent Cloud (CVM)
- **OS:** Ubuntu 24.04.4 LTS (kernel 6.8.0-101-generic, x86_64)
- **Region / Zone:** ap-singapore / ap-singapore-1 (Tencent Cloud Singapore)
- **SSH access pattern:** `ssh ubuntu@<TODO: fill real IP or DNS> -p 22`
  - (default port 22 confirmed in `/etc/ssh/sshd_config`; port not changed)
- **Auth method:** SSH public-key auth. Key file lives on the operator's machine at `~/.ssh/<TODO: key filename, e.g. id_ed25519_tencent>`. Do not move or overwrite the key on the VPS.
- **User / privilege:** non-root user `ubuntu`; has **passwordless sudo** (`sudo -n` works). Run admin tasks as `ubuntu` + `sudo`, not as root.

## 2. Hermes Installation Details
- **Install type:** Native, via `pipx` (NOT Docker). Symlink: `~/.local/bin/hermes -> ~/.local/share/pipx/venvs/hermes-agent/bin/hermes`. Python 3.12 venv.
- **Main Hermes directories:**
  - Root config: `~/.hermes/config.yaml` (and `.bak.*` timestamped backups)
  - Root env: `~/.hermes/.env`
  - Logs: `~/.hermes/logs/` (`agent.log`, `gateway.log`, `errors.log`, `gateway-exit-diag.log`)
  - Hooks: `~/.hermes/hooks/`, cron: `~/.hermes/cron/`, skills root: `~/.hermes/skills/` (per-profile; see below)
  - State DB: `~/.hermes/state.db`, kanban: `~/.hermes/kanban.db`
- **Profiles (under `~/.hermes/profiles/`):**
  - `signaltable` — the ONLY existing profile. Used by the SignalTable project (Singapore tech-event automation: Luma/Meetup/Eventbrite discovery, Telegram approvals, Google Calendar, Apify). Active live workflows run under this profile.
  - **NightDesk profile:** NOT yet created. Expected future path `~/.hermes/profiles/nightdesk/` (create via `hermes profile create nightdesk --clone` when starting).
- **How Hermes is started:**
  - CLI: `hermes` (pipx venv binary) — for interactive/chat use.
  - Gateway: **systemd user service** `hermes-gateway.service` (also `hermes-upgrade-guard.service`, `wiki-server.service` in same dir).
    - Unit path: `~/.config/systemd/user/hermes-gateway.service` (+ drop-in dir `~/.config/systemd/user/hermes-gateway.service.d/`)
    - `ExecStart`: `/home/ubuntu/.local/share/pipx/venvs/hermes-agent/bin/python -m hermes_cli.main gateway run`
    - `WorkingDirectory`: `/home/ubuntu/.hermes`
    - Manage: `systemctl --user status hermes-gateway`, `start/stop/restart hermes-gateway`.
  - No tmux sessions currently hold Hermes (verified: `tmux ls` empty). Gateway persists via systemd, not tmux.

## 3. Gateway / Telegram Details
- **Gateway running:** YES — `gateway_state: running`, Telegram platform `state: connected` (as of 2026-07-08 05:32 UTC; last heartbeat then).
- **Gateway process:** PID 2033925, user `ubuntu`, argv `.../hermes_cli.main gateway run`. Tracked by `~/.hermes/gateway.pid` + `~/.hermes/gateway_state.json`.
- **Working directory:** `/home/ubuntu/.hermes`
- **Gateway logs:** `~/.hermes/logs/gateway.log` (main), plus `~/.hermes/logs/gateway-exit-diag.log` and `~/.hermes/logs/gateway-shutdown-diag.log`.
- **Telegram config (env var names only, in `~/.hermes/.env` and profile `.env`):** `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USERS`, `TELEGRAM_HOME_CHANNEL`, `TELEGRAM_HOME_CHANNEL_THREAD_ID`.

## 4. Providers & Models
- **Provider:** Tencent **TokenHub** custom OpenAI-compatible endpoint.
  - `base_url: https://tokenhub-intl.tencentcloudmaas.com/v1` (in `~/.hermes/config.yaml` under `providers` / `fallback_providers`).
  - API key referenced as env var `TENCENT_TOKENHUB_API_KEY` (do NOT hardcode; lives in `.env`).
- **Configured models (from `config.yaml` `model:` / `providers`):**
  - `deepseek-v4-flash-202605`
  - `glm-5.2`
  - `qwen3.6-flash`
  - (Plus TTS/STT models: `gpt-4o-mini-tts`, `gemini-2.5-flash-preview-tts`, `voxtral-mini-tts-2603`, `neuphonic/neutts-air-q4-gguf`, `eleven_multilingual_v2`, `whisper-1`)
- **Other provider keys present (env var names, in `.env`):** `GROQ_API_KEY`, `GOOGLE_API_KEY`, `OPENROUTER_API_KEY`, `DEEPSEEK_API_KEY`.
- **Provider config file paths:**
  - Global: `~/.hermes/config.yaml` (providers, model catalog) and `~/.hermes/.env` (keys)
  - Per-profile override: `~/.hermes/profiles/<profile>/config.yaml` and `.env`
  - Note: `providers: {}` at top level means providers are likely defined under `fallback_providers` or profile-level config — inspect both when adding a model.

## 5. Existing Scripts, tmux Sessions, or Services
- **tmux sessions:** none currently active (gateway runs under systemd, not tmux).
- **systemd user services:** `hermes-gateway.service`, `hermes-upgrade-guard.service`, `wiki-server.service` (dir: `~/.config/systemd/user/`).
- **Startup scripts / bins:** `~/.hermes/bin/` (empty of gateway start scripts; gateway is systemd-managed). Profile `signaltable` has its own `scripts/` and `bin/` dirs for project tooling (e.g. Apify fetch, discovery pipeline) — NightDesk should create its own, not reuse these.
- **Cron:** Hermes-managed cron dir `~/.hermes/cron/` (with `.jobs.lock`, `output/`). SignalTable may have scheduled jobs here.

## 6. Security & Access Notes
- **Firewall:** `ufw status: inactive`. `iptables` has a `YJ-FIREWALL-INPUT` chain but currently all policies ACCEPT (no active blocking rules observed). Provider endpoint is outbound HTTPS to Tencent TokenHub; no inbound port restrictions noted.
- **⚠️ DO NOT restart, reconfigure, or kill existing Hermes/gateway processes without confirming with the owner first.** This VPS is running live workflows (SignalTable's Telegram gateway is connected and may be mid-task). `systemctl --user restart hermes-gateway` would drop the live Telegram connection. Treat the `signaltable` profile and the running gateway as PRODUCTION.
- Secrets are stored in `.env` files (mode 600) and `auth.json`; never echo, commit, or paste them. Reference only env var names.

## 7. Handoff Notes for NightDesk
This VPS + Hermes setup (Tencent Cloud Singapore, Ubuntu 24.04, native pipx Hermes, systemd gateway, TokenHub/GLM-5.2 models, Telegram connected) is being reused for a new project called **NightDesk — the After-Hours Booking Nurturer**. NightDesk is an independent agent/project that will operate alongside SignalTable on the same host.

**What NightDesk MAY touch:**
- Create its own Hermes profile: `hermes profile create nightdesk --clone` → `~/.hermes/profiles/nightdesk/` (own `config.yaml`, `.env`, `skills/`, `scripts/`, `logs/`).
- Add new project scripts under `~/.hermes/profiles/nightdesk/scripts/`.
- Add new models/providers under the `nightdesk` profile config only (or clearly-scoped global additions, after owner approval).
- Add new Hermes-managed cron jobs scoped to NightDesk.
- Add new HTTP endpoints under a dedicated path namespace, e.g. `/nightdesk/*` (if a web surface is introduced), without touching existing routes.

**What NightDesk MUST NOT touch:**
- The running `hermes-gateway.service` / live Telegram gateway (do not stop, restart, or reconfigure it).
- The `signaltable` profile directory, its config, scripts, or state — it is live production.
- Global `~/.hermes/config.yaml` or `~/.hermes/.env` provider/key definitions unless explicitly approved by the owner.
- Any firewall (`ufw`/`iptables`) rules, systemd unit files outside its own scope, or the `wiki-server`/`upgrade-guard` services.
- Existing SSH keys, `auth.json`, or other credentials.

**TODOs to fill before handoff is complete:**
- `<TODO: fill real VPS IP or DNS>` in SSH line (section 1).
- `<TODO: key filename>` in section 1 (or confirm key-based access pattern with owner).
- Confirm whether NightDesk needs its own Telegram bot (`TELEGRAM_BOT_TOKEN`) or reuses the existing one (section 3/7).
- Confirm whether NightDesk reuses TokenHub/GLM-5.2 or brings its own model provider (section 4).
