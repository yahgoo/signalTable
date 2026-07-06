# Session End — 2026-07-06

**Status:** Paused. Resume end-to-end smoke test tomorrow.

## Done today

| Area | State |
|------|--------|
| Luma discovery | Apify-first pipeline production-verified on VPS |
| Browser fallback | Only when Apify fails or normalized output empty |
| Telegram approval | Concise YES/NO format; `signaltable-approval` plugin intercepts replies |
| Runbooks | `event-discovery-runbook.md`, `e2e-smoke-test-runbook.md` |
| Approval queue | `scripts/approval_queue.py` + `plugins/signaltable-approval/` |

## Verified on VPS

- Apify Luma pipeline returns `Luma: N` + scored table
- Telegram YES → `Approved: … Starting registration.` (no fresh-session confusion)
- `gcal.py` list works after Google API packages installed on VPS

## Not done / blocked

- Full e2e smoke test on a **real** Luma event (confirmed attendee + confirmation email + calendar write)
- Calendar empty for test event (waitlist/placeholder URL; registration did not complete)
- `qwen3.6-flash` quota notice on default profile (signaltable uses `qwen-turbo`)

## Resume tomorrow

1. Pick a real free Luma event with instant confirmation (not waitlist).
2. Follow `docs/e2e-smoke-test-runbook.md`.
3. Confirm LobsterMail receives Luma confirmation email before `calendar-updater`.
4. Verify entry in SignalTable Events calendar via `gcal.py list`.

## Key paths (VPS)

```
~/.hermes/profiles/signaltable/
~/.hermes/plugins/signaltable-approval/
~/.hermes/profiles/signaltable/scripts/{apify_luma,luma_normalize,luma_discovery_report,approval_queue,gcal}.py
```
