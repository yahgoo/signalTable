# Apify Luma Discovery — Handoff (2026-07-06)

**Status:** Apify-first Luma path **live in production on VPS** (2026-07-06). Hermes skill Step 1 documents the preferred pipeline; browser fallback retained. Cron not switched yet.

---

## Operator note (Hermes / VPS)

| Item | Detail |
|------|--------|
| **Required** | `APIFY_TOKEN` in `~/.hermes/profiles/signaltable/.env` |
| **Optional** | `APIFY_ACTOR_ID` (default `solidcode/luma-scraper`), `APIFY_TASK_ID` (overrides actor) |
| **Scripts** | `scripts/apify_luma.py`, `scripts/luma_normalize.py`, `scripts/luma_discovery_report.py` |
| **Default scoring** | `min_score=4` in report script — production discovery |
| **Debug only** | `--min-score 2` or `--debug-filter` for inspection |
| **Read-only** | No Luma signup/login/registration |

**Hermes preferred command:**

```bash
python3 ~/.hermes/profiles/signaltable/scripts/apify_luma.py \
  --location singapore --queries data,algorithm,compute --max-items 50 \
  | python3 ~/.hermes/profiles/signaltable/scripts/luma_discovery_report.py
```

Fall back to read-only browser (one navigate + one snapshot) only if Apify fails — see Step 1b in `event-discovery.md`.

---

## Files added/changed

| File | Change |
|------|--------|
| `signaltable/scripts/apify_luma.py` | Fetch / normalize public Luma events via Apify |
| `signaltable/scripts/luma_normalize.py` | Shared normalize + deterministic filters |
| `signaltable/scripts/luma_discovery_report.py` | Filter, score, render `Luma: N` + markdown table |
| `signaltable/skills/event-discovery.md` | **Apify-first Luma** (Step 1a/1b); browser fallback |
| `signaltable/docs/architecture.md` | Step 6b + diagram note for Apify-assisted Luma |
| `signaltable/env-template.env` | `APIFY_TOKEN` (+ optional actor/task overrides) |

**Not touched:** Telegram gateway, LobsterMail, Google Calendar (`gcal.py`), cron, config.yaml, VPS `.env`.

---

## Default Apify actor (chosen)

**`solidcode/luma-scraper`** (override with `APIFY_ACTOR_ID` or `--actor`)

| | **solidcode/luma-scraper** (default) | **haketa/luma-event-scraper** (alt) |
|---|---|---|
| **Pros** | City slug + search queries + category filters; pay-per-result (~$2.50/1K); public discover feed; date filters | Simple `cities` + `category` input; no login; good for city/category sweeps |
| **Cons** | Paid per result; actor input schema specific to this actor | City slugs may differ (`singapore` vs `sg` — verify in Apify console); less search-query flexibility |

Use **`APIFY_TASK_ID`** when you have a preconfigured Apify task (saved input, schedule, billing cap).

---

## Manual setup required (owner)

1. **Apify account + token** — create at [apify.com](https://apify.com); set `APIFY_TOKEN` in VPS `~/.hermes/profiles/signaltable/.env`.
2. **Verify actor access** — run once in Apify console with input:
   ```json
   {
     "discoverCity": "singapore",
     "searchQueries": ["data", "algorithm", "compute"],
     "lumaUrls": ["https://lu.ma/singapore"],
     "maxItems": 20
   }
   ```
3. **Optional task** — if you create a saved task, set `APIFY_TASK_ID=my-task-name` (overrides actor).
4. **Deploy scripts to VPS:**
   ```bash
   scp signaltable/scripts/{apify_luma,luma_normalize,luma_discovery_report}.py \
     ubuntu@43.156.46.66:~/.hermes/profiles/signaltable/scripts/
   scp signaltable/skills/event-discovery.md \
     ubuntu@43.156.46.66:~/.hermes/profiles/signaltable/skills/event-discovery/SKILL.md
   ```

No secrets in git. Credits consume per Apify run (~$2.50/1K events on default actor).

---

## CLI examples

### Fetch normalized JSON (local or VPS)

```bash
export APIFY_TOKEN=apify_api_...
python3 signaltable/scripts/apify_luma.py \
  --location singapore \
  --queries data,algorithm,compute \
  --max-items 50 \
  --output json
```

### One-command discovery report

```bash
python3 signaltable/scripts/apify_luma.py \
  --location singapore \
  --queries data,algorithm,compute \
  --max-items 50 \
  | python3 signaltable/scripts/luma_discovery_report.py
```

Expected output:

```
Luma: N

| title | date | score | tier | source | URL |
| --- | --- | ---: | ---: | --- | --- |
...
```

### Use Apify task instead of actor

```bash
export APIFY_TASK_ID=your-task-id
python3 signaltable/scripts/apify_luma.py --location singapore
```

### Save JSON then report

```bash
python3 signaltable/scripts/apify_luma.py --location singapore --output json > /tmp/luma.json
python3 signaltable/scripts/luma_discovery_report.py --input /tmp/luma.json
```

---

## Hermes integration

Step 1 of `skills/event-discovery.md` documents the **preferred Apify pipeline**. Hermes should run the scripts via `terminal` or `execute_code` before any Luma browser tools. Browser fallback is Step 1b only.

Full production cron switch deferred until one successful VPS run with live `APIFY_TOKEN`.

---

## Read-only guardrails

- Scripts call **public** Apify actors only.
- No Luma signup, login, registration, or session cookies.
- Browser discovery remains as **fallback only** in `event-discovery.md`.
