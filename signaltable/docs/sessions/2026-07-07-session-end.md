# SignalTable Session Summary — 2026-07-07

## Status snapshot

| Layer | State | VPS |
|-------|-------|-----|
| Discovery (Luma+Meetup) | Shared pipeline deployed | Live-validated |
| Telegram approval | Plugin intercept YES/NO | Working |
| Registration | Skill exists; e2e incomplete | Manual/browser |
| Email parse | Skill documented | Not wired to scripts |
| Calendar write | `gcal.py` + `calendar_write.py` gate | Live-validated (1 event) |
| Cron / batch | Not enabled | — |

## Pipeline (practical)

```
discovery → approval (Telegram) → register → email confirm → calendar_write → notify
   ✓            ✓                    ~partial      ~manual         ✓ gate         ✓ skill only
```

## Deployed VPS artifacts (2026-07-07)

**Discovery refactor backup:** `backups/discovery-refactor-2026-07-07_13-12-56/`  
**Calendar integration backup:** `backups/calendar-integration-2026-07-07_13-26-46/`

Scripts on VPS: `discovery_common.py`, `meetup_*`, `discovery_pipeline.py`, `luma_*` (updated), `calendar_write.py`, `gcal.py` (location flag).

Skills updated on VPS: `event-discovery/SKILL.md`, `calendar-updater/SKILL.md`.

## Live validation results

| Test | Result |
|------|--------|
| Luma Apify pipe | 45 raw → 3 scored (production path) |
| Meetup exports | 70 raw → 12 scored |
| Calendar create (SHELLGym) | Created + verified (`j743dl7qm4hppbjhu728sa64oo`) |
| `calendar_write.py --self-test` | pass |
| Confirmed duplicate write | `duplicate_skipped` |

## Local repo (uncommitted)

New: `discovery_common.py`, `meetup_normalize.py`, `discovery_pipeline.py`, `meetup_discovery_report.py`, `calendar_write.py`, `docs/calendar-write-runbook.md`

Modified: `luma_*`, `gcal.py`, skills (`event-discovery`, `calendar-updater`, `email-parser`), runbooks.

## Tier 3 — not done (requires explicit approval)

- Luma/Meetup registration submit
- Telegram sends (except existing approval flow tests)
- Cron enable
- Batch calendar writes
- Default profile changes

## Recommended next 3 steps

1. **Git commit** discovery + calendar integration (local only; user approves message)
2. **Deploy `email-parser/SKILL.md`** to VPS; dry-run sample confirmed JSON → `calendar_write.py --dry-run`
3. **One real Luma registration e2e** (Tier 3): register → wait for LobsterMail → `calendar_write.py --write`

## Operator commands (VPS)

```bash
# Discovery (production Luma)
python3 ~/.hermes/profiles/signaltable/scripts/apify_luma.py \
  --location singapore --queries data,algorithm,compute --max-items 50 \
  | python3 ~/.hermes/profiles/signaltable/scripts/luma_discovery_report.py --debug-filter

# Calendar gate self-test
python3 ~/.hermes/profiles/signaltable/scripts/calendar_write.py --self-test

# Confirmed write (after email parse)
python3 ~/.hermes/profiles/signaltable/scripts/calendar_write.py --input confirmed.json --write
```
