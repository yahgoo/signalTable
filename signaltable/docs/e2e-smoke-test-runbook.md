# SignalTable — End-to-End Smoke Test

## 1. Goal

Validate the full path on **one real Luma event**:

**discovery → Telegram approval → registration → confirmation email → calendar write**

## 2. Do

- Pick a **real public Luma event** with a normal free registration flow (not waitlist-only, not paid).
- Run Luma discovery (Apify-first pipeline) and confirm the event appears in the shortlist.
- Escalate to Telegram approval if Tier 2/3; send approval via `approval_queue.py` + `hermes send`.
- Reply **YES** on Telegram and confirm the ack: `Approved: … Starting registration.`
- Complete registration through to **confirmed attendee** state (not waitlist).
- Wait for the **Luma registration confirmation email** and calendar invite in LobsterMail.
- Run **email-parser** on the confirmation.
- Run **calendar-updater** only after confirmation is received.
- Verify the event appears in **SignalTable Events** with correct title, date/time (SGT), and source URL.
- Check for duplicates before and after the write.

## 3. Don’t

- Don’t treat **joined waitlist** as success.
- Don’t write to Google Calendar before a **confirmation email** exists.
- Don’t use `indexedDateAfter` as a freshness filter.
- Don’t change Meetup or Eventbrite logic.
- Don’t modify gateway, cron, Google Calendar config, Telegram, or LobsterMail for this smoke test.
- Don’t use placeholder or fake event URLs.

## 4. Fallback

- If registration lands on a **waitlist**, **stop** — do not continue to calendar write.
- If the **confirmation email does not arrive** within a reasonable window (e.g. 15–30 min), treat the test as **incomplete** and investigate LobsterMail inbox + spam.
- If the calendar is still empty after a confirmed registration, check **calendar-updater** skill and **`gcal.py`** separately (credentials, `GOOGLE_CALENDAR_ID`, service account sharing).
- If discovery returns **`Luma: 0`** because scoring filtered everything out, that is **not** a registration failure — pick another event or lower `--min-score` for inspection only.

## 5. Pass Criteria

- Event found in discovery shortlist.
- Telegram approval sent and **YES** acknowledged.
- Registration completed successfully (confirmed attendee).
- Luma registration confirmation email received in LobsterMail.
- Calendar event created in SignalTable Events.
- Title, date/time, and source match the real event.
- No duplicate calendar entries.

## 6. Fail Criteria

- Waitlist only (no confirmed registration).
- No confirmation email after successful-looking registration.
- Calendar entry created before confirmation email.
- Wrong event title, date, or source on calendar.
- Duplicate calendar entry for the same event.

## 7. Notes

| Item | Detail |
|------|--------|
| Luma email | Luma sends a registration confirmation email with a calendar invite when the guest submits the registration form. |
| Paid / approval events | May authorize payment first and only capture after organizer approval — avoid for smoke test. |
| Waitlist / pending approval | Stop signal, not success. Do not proceed to calendar write. |
| Platform order | Luma only for this test. |
| Skills (in order) | `event-discovery` → approval → `event-register` → `email-parser` → `calendar-updater` → `telegram-reporter` |
| Calendar check | `python3 ~/.hermes/profiles/signaltable/scripts/gcal.py list --calendar "$GOOGLE_CALENDAR_ID" --from "<date-1d>" --to "<date+1d>" --q "<title>"` |

**Typical pass trace:** `Luma: N` → approval YES → registered → email in inbox → `CALENDAR_ADDED` in log → event visible in Google Calendar.
