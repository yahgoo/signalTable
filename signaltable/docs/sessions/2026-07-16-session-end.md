# Session End: Eventbrite Phase 2 WAF Block & Deferral

## Outcome

- **Option (c) confirmed:** Eventbrite cutover deferred indefinitely.
- `eventbrite_scrape_fetch.py` is **fully validated** but **shelved**.
- Meetup + Luma cutovers **complete and live** (self-hosted scrapers running).

## Apify Expiry Risk (Critical)

- **2026-07-20 is an account-wide expiry.** No Eventbrite-specific exception exists.
- Eventbrite actor (`eventbrite-science-tech-singapore-free`) **will stop** on 2026-07-20.
- This is an **unresolved risk** requiring post-deadline action:
  - Renew Apify subscription for Eventbrite continuity, OR
  - Rebuild Eventbrite discovery using residential-proxy egress to avoid WAF blocks.

## WAF Block Summary

- VPS IP `43.156.46.66` **WAF-penalized** by Eventbrite (CloudFront).
- Listing pages → **HTTP 405 + captcha**.
- Per-event pages → **HTTP 200** (JSON-LD intact, but unreachable).
- Legacy `app_key` token is **valid** (v1 JSON API works, but IP blocked).
- No further Eventbrite requests from VPS IP.

## Commits

- `1674c17`: Final decision (defer), risk documented
- `052cc2d`: WAF diagnosis (API-key test, IP-penalty root cause)
- `2dca1b2`: Eventbrite diagnostic round (sitemap, Platform API, RSS)
- `b8830b0`: Live fetch blocked by WAF
- `32f2bfe`: Local build (self-test PASS, score-parity PASS)

## Next Steps (Post-2026-07-20)

1. Decide on Apify renewal, or
2. Rebuild Eventbrite discovery without time pressure (residential proxy or API access).
