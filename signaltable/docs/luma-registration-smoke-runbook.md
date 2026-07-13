# Luma Registration Smoke Test — `aic-si-7-8`

Dedicated smoke for **full Luma form submit + LobsterMail confirmation**, not a Register-click-only session.

| Field | Value |
|-------|--------|
| Smoke ID | `luma-aic-si-7-8` |
| Event URL | https://luma.com/aic-si-7-8 |
| Title | AI Governance for SMEs: Practical Solutions (without the Enterprise headache) w/ The AI Collective |
| Inbox | `signaltable-reg@lobstermail.ai` |
| Scripts | `luma_registration_smoke.py`, `lobstermail_poll.py --luma` |

**Known blocker:** This event page mentions **wallet token verification**. Automation may stop at `WALLET_MANUAL_REQUIRED` before email confirmation. Treat that as a documented fail/manual gate, not smoke success.

---

## a) Exact test steps

### Phase 1 — Browser registration (operator / `signaltable`)

1. Print the agent prompt:
   ```bash
   python3 signaltable/scripts/luma_registration_smoke.py prompt
   ```
2. Run **one** registration attempt via `signaltable chat` (preferred) or interactive browser — **not** `signaltable -z` one-shot if it exits after one click.
3. **Navigate** to https://luma.com/aic-si-7-8
4. **Click Register** (opens modal — **not** success)
5. **Fill** required name + email (`signaltable-reg@lobstermail.ai`)
6. **Submit** the registration form once
7. Capture post-submit page state (registered / waitlist / wallet gate / error)
8. Save session log JSON (use template):
   ```bash
   python3 signaltable/scripts/luma_registration_smoke.py template -o /tmp/luma-aic-si-7-8-session.json
   ```
   Fill `browser_actions`, `form_submitted`, `outcome`, `ended_at`.

### Phase 2 — Session contract validation

```bash
python3 signaltable/scripts/luma_registration_smoke.py validate \
  --input /tmp/luma-aic-si-7-8-session.json \
  --output /tmp/luma-aic-si-7-8-contract.json
```

Exit `0` only when `action=accepted` and `contract=LUMA_REGISTRATION_COMPLETE`.

### Phase 3 — LobsterMail confirmation (production poll only)

After successful form submit, wait for real Luma email:

```bash
python3 signaltable/scripts/lobstermail_poll.py \
  --watch \
  --luma \
  --event-title "AI Governance for SMEs: Practical Solutions (without the Enterprise headache) w/ The AI Collective" \
  --source-url "https://luma.com/aic-si-7-8" \
  --interval 30 \
  --max-wait 1800 \
  --output /tmp/luma-aic-si-7-8-confirmed.json
```

Poll loop must show `action=pending` until a matching `noreply@lu.ma` / `luma.com` message is found, then `action=accepted_notified` with `owner_notified_at`.

### Phase 4 — Calendar gate (unchanged)

Only after `accepted_notified`:

```bash
python3 signaltable/scripts/calendar_write.py \
  --input /tmp/luma-aic-si-7-8-confirmed.json \
  --dry-run
```

Then `--write` only after dry-run approval.

---

## b) Success criteria

| Stage | Requirement |
|-------|-------------|
| Session | `browser_action_count` > 1; `form_submitted=true`; outcome `REGISTRATION_SUBMITTED` or `CONFIRMATION_PENDING`; contract `LUMA_REGISTRATION_COMPLETE` |
| Not success | Register click alone, early session exit, waitlist-only, wallet gate |
| Email | `lobstermail_poll.py --luma --watch` → `action=accepted_notified`; `confirmation_source=luma_email`; `confirmation_evidence` contains `lobstermail_poll`; real `raw_email_id` (not placeholder) |
| Notify | Telegram sent via `hermes send`; `owner_notified_at` stamped |
| Calendar | `calendar_write_allowed=true` only after notify; dry-run passes validator |

**Fixture reference (passing session shape):** `fixtures/luma-registration-success.sample.json`

---

## c) Failure criteria

| Contract | Meaning |
|----------|---------|
| `EARLY_EXIT_ONE_CLICK` | ≤1 browser action (KonfHub-style `-z` exit) — **Register click is not success** |
| `FORM_NOT_SUBMITTED` | Modal opened but no submit |
| `WAITLIST_NOT_SUCCESS` | Joined waitlist, not confirmed guest |
| `WALLET_MANUAL_REQUIRED` | Wallet/token verification blocks automation |
| `NO_POST_SUBMIT_SUCCESS` | Submit attempted but no valid outcome / on-page confirmation |
| Poll `pending_timeout` | No Luma email in inbox within wait window |
| Poll `rejected` / `notify_failed` | Validator or Telegram failure |
| Calendar before notify | Any write without `owner_notified_at` |

**Fixture reference (one-click fail):** `fixtures/luma-registration-one-click-fail.sample.json`

Self-check:

```bash
python3 signaltable/scripts/luma_registration_smoke.py --self-test
python3 signaltable/scripts/lobstermail_poll.py --self-test
```

---

## d) Code / docs updates

| Path | Purpose |
|------|---------|
| `scripts/luma_registration_smoke.py` | Luma session contract, prompt, template, validate, `--self-test` |
| `scripts/lobstermail_poll.py` | `--luma` poll/watch; sender domains `lu.ma`, `luma.com`; `confirmation_source=luma_email` |
| `scripts/registration_gateway.py` | Luma `waitlist` → failed; `wallet_required` → manual |
| `fixtures/luma-aic-si-7-8-event.sample.json` | Event metadata |
| `fixtures/luma-registration-success.sample.json` | Passing session log |
| `fixtures/luma-registration-one-click-fail.sample.json` | One-click failure case |
| `fixtures/lobstermail-inbox-luma-aic.sample.json` | Luma confirmation inbox fixture |
| `docs/luma-registration-smoke-runbook.md` | This runbook |

---

## Luma vs KonfHub

| Topic | KonfHub | Luma |
|-------|---------|------|
| Registration URL | External `konfhub.com/...` from Meetup description | Native `luma.com/...` event page |
| Form | Often multi-step / custom fields | Usually name + email in modal |
| Email sender | `@konfhub.com` | `@lu.ma` / `@luma.com` |
| `confirmation_source` | `konfhub_email` | `luma_email` |
| Poll flag | `--konfhub` | `--luma` |
| Ticket ID in email | Often `KH-...` | Usually none (URL/title match) |
| Waitlist | Less common on smoke path | Explicit stop — not success |
| Wallet verify | Uncommon | **Present on `aic-si-7-8`** — manual gate |
| One-click false success | Observed on VPS `-z` sessions | Same guard via session contract |
| Custom fields gate | `KONFHUB_SAFE_FIELDS` check | Typically name/email only |

Shared pipeline (unchanged): **poll → validate → Telegram → `owner_notified_at` → calendar dry-run → write**.

---

## Session log format

Required fields for `validate`:

```json
{
  "smoke_id": "luma-aic-si-7-8",
  "event_url": "https://luma.com/aic-si-7-8",
  "registration_platform": "luma",
  "browser_actions": [{"name": "browser_navigate", "detail": "..."}, {"name": "browser_click", "detail": "Register"}, "..."],
  "form_submitted": true,
  "on_page_confirmed": true,
  "waitlist": false,
  "wallet_required": false,
  "outcome": "REGISTRATION_SUBMITTED"
}
```

Log file naming (VPS): `~/.hermes/profiles/signaltable/logs/luma-aic-si-7-8-<YYYY-MM-DD>.log` — append session JSON or Hermes transcript excerpt for audit.
