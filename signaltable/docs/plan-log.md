# SignalTable 20-Day Transition Plan

**Project**: SignalTable — Hermes-based Singapore tech event automation  
**Start date**: 2026-07-03  
**End date**: 2026-07-22  
**VPS**: ubuntu@43.156.46.66 (Tencent Cloud Singapore)  
**Profile**: `~/.hermes/profiles/signaltable/`

---

## Phase 1: Foundation (Days 1–4)

### Day 1 — Environment Setup
- [ ] SSH into VPS, take full Hermes backup
- [ ] Create `signaltable` Hermes profile (`hermes profile create signaltable --clone`)
- [ ] Deploy SOUL.md, skills, config overlay to VPS profile
- [ ] Verify gateway still running (default profile); confirm signaltable profile isolated
- [ ] Install Scrapling skill: `signaltable skills install official/research/scrapling`
- [ ] Install LobsterMail MCP in signaltable config
- [ ] Install PortEden CLI, authenticate
- [ ] Install Steel browser (API key required from owner)

### Day 2 — Integration Smoke Tests
- [ ] LobsterMail: create `signaltable-reg` inbox, verify address
- [ ] PortEden: `porteden calendar calendars -jc` — confirm Google Calendar accessible
- [ ] Create "SignalTable Events" calendar (manual via Google Calendar or PortEden)
- [ ] Steel: basic browser session test (navigate to eventbrite.sg)
- [ ] Scrapling: fetch test (`scrapling fetch https://www.eventbrite.sg/d/singapore--singapore/tech--events/`)
- [ ] Telegram: send test message via signaltable_bot to verify gateway

### Day 3 — Discovery Dry Run (Apify Comparison Day 1)
- [ ] Run event-discovery skill manually: `signaltable chat "Run the event-discovery skill"`
- [ ] Compare results against Apify actor output (manual side-by-side in comparison.csv)
- [ ] Log discrepancies: events found by Apify but not Hermes, and vice versa
- [ ] Tune relevance scoring in event-discovery.md if needed

### Day 4 — Registration Dry Run (MuleRun Comparison Day 1)
- [ ] Pick 1 Tier 1 event from Day 3 discovery
- [ ] Run event-register skill manually in dry-run mode (no actual submit)
- [ ] Compare form-fill steps with MuleRun/manual flow
- [ ] Document any form fields that need special handling

---

## Phase 2: Core Flows (Days 5–10)

### Day 5 — First Live Registration
- [ ] Pick 1 Tier 1 free event (confirmed safe)
- [ ] Run event-register skill live — submit actual registration
- [ ] Run email-parser skill — verify LobsterMail receives confirmation
- [ ] Run calendar-updater — verify event in SignalTable Events calendar
- [ ] Run telegram-reporter — verify Telegram summary received
- [ ] Log result in comparison.csv

### Day 6 — Tier 2 Approval Flow
- [ ] Find 1 Tier 2 event from latest discovery run
- [ ] Verify Telegram approval message is sent correctly
- [ ] Test "YES" reply triggers registration
- [ ] Test "NO" reply skips event and logs correctly

### Day 7 — Cron Job Setup
- [ ] Create daily cron job (8:00 AM SGT):
  ```bash
  signaltable cron create "0 0 * * *" \
    "Run event-discovery skill, then for each Tier 1 event run event-register, email-parser, calendar-updater, and telegram-reporter skills. Send daily digest via telegram-reporter." \
    --skill event-discovery --skill event-register --skill email-parser \
    --skill calendar-updater --skill telegram-reporter \
    --name "signaltable-daily"
  ```
- [ ] Verify cron job registered: `signaltable cron list`
- [ ] Run a manual trigger: `signaltable cron run signaltable-daily`

### Day 8 — Cron Validation
- [ ] Wait for next scheduled 8 AM run, review logs
- [ ] Check `~/.hermes/profiles/signaltable/logs/signaltable.log`
- [ ] Check Telegram for daily digest
- [ ] Check calendar for any new entries

### Day 9 — Apify Comparison Day 2
- [ ] Run both Apify (via existing actor) and Hermes discovery for same date
- [ ] Fill comparison.csv with results
- [ ] Calculate: events found, false positives, missed events

### Day 10 — LobsterMail & Email Parser Edge Cases
- [ ] Test with an event that sends HTML-heavy email
- [ ] Test waitlist email parsing
- [ ] Test with a spoofed/suspicious test email (inject risk score check)
- [ ] Document any parsing failures in plan-log.md

---

## Phase 3: Parallel Run (Days 11–16)

### Days 11–13 — Parallel Operation
- [ ] Both Apify and Hermes run daily; compare outputs
- [ ] MuleRun (or manual) registration for Tier 3 events; Hermes handles Tier 1
- [ ] Track in comparison.csv: Hermes coverage vs Apify coverage (target: ≥80%)

### Day 14 — Partial Cutover
- [ ] Disable Apify actor for Meetup (Hermes takes over)
- [ ] Keep Apify running for Eventbrite (monitoring only)
- [ ] Document which flows are now Hermes-owned

### Days 15–16 — Stabilization
- [ ] Review 14-day log for errors, missed events, false positives
- [ ] Fix any skill issues found
- [ ] Tune cron timing if needed (e.g., run twice daily if event coverage is low)

---

## Phase 4: Final Review (Days 17–20)

### Day 17 — Full Hermes Cutover Attempt
- [ ] Disable Apify entirely for 24 hours
- [ ] Review next-day results vs expected
- [ ] Decision: full cutover, partial cutover, or extend parallel run

### Day 18 — MuleRun Comparison Final
- [ ] Side-by-side comparison of Hermes vs MuleRun registration success rates
- [ ] Document platforms where Hermes succeeds / fails

### Day 19 — Success Metrics Review
- [ ] Discovery: Hermes finds ≥80% of what Apify found in parallel period?
- [ ] Registration: Hermes successfully registered on ≥2 platforms?
- [ ] Email parsing: ≥90% of confirmation emails correctly parsed?
- [ ] Calendar: No duplicate entries, all confirmed events present?
- [ ] Telegram: All daily digests delivered cleanly?
- [ ] Owner approval flow: Tier 2/3 escalation working correctly?

### Day 20 — Readiness Sign-off
- [ ] Owner reviews final state via Telegram and VPS
- [ ] Decide flows to fully hand over to Hermes
- [ ] Archive Apify actor (keep config, disable billing)
- [ ] Update integrations.md with final status
- [ ] Document rollback instructions

---

## Rollback Instructions

If any Hermes flow breaks production:
```bash
# Stop signaltable gateway (if running):
signaltable gateway stop

# Pause signaltable cron jobs:
signaltable cron pause signaltable-daily

# Re-enable Apify (if disabled):
# → Go to Apify console, enable actor scheduling

# Re-enable MuleRun (if disabled):
# → Go to MuleRun console, re-activate flow

# Restore Hermes default profile backup (if config was changed):
tar -xzf ~/hermes-backup-<date>.tar.gz -C ~ --strip-components=1 .hermes/config.yaml .hermes/.env
hermes gateway service install --replace
```

---

## Daily Log

| Date | Phase | Action | Status | Notes |
|------|-------|--------|--------|-------|
| 2026-07-10 | Luma | Schema hardening + live verification | **closed** | `inspect_luma_schema()`, fallbacks, `--self-test`; VPS batch `20260709-schema-verify`: 0 foreign warnings, 46/46 description warnings (Actor `description: null`); doc gap for flat `eventId`/`startAt` shape — see `docs/sessions/2026-07-10-luma-schema-hardening-session-end.md` |
| 2026-07-08 | Version A | **Working session** — live Luma e2e | **active** | 3 approved Luma cards sent via Telegram; quality batch not sent; relevance tuning pending — see `docs/sessions/2026-07-08-version-a-luma-handoff.md` |
| 2026-07-08 | Version A | Luma URL debug (synthetic fixtures) | **closed** | 404 slugs were synthetic fixture data, not production corruption; `synthetic_fixture` flag + Luma URL fallback documented |
| 2026-07-08 | Version A | Deployment parity (local ↔ VPS) | **complete** | Synced `version_a.py`, `event_url_check.py`, `meetup_normalize.py`, `meetup-konfhub-gateway.sample.json`; venue + `URL:` + `--debug-urls` verified on VPS |
| 2026-07-03 | Setup | Initial deployment | pending | |
