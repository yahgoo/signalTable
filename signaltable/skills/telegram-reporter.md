# SignalTable: Telegram Reporter Skill

## Purpose
Post clean, structured summaries of discovered and registered events to the owner's Telegram (user 1697120790 / signaltable_bot).

## Report Types

### A. Daily Discovery Summary (sent after each cron run)
Format:
```
📅 SignalTable Daily Digest — <date SGT>

Found <N> new events matching your criteria:

1. 🟢 [Tier 1 – Auto-registered] Singapore AI Meetup: Building with LLMs
   📆 Thu 10 Jul 2026, 7:00 PM SGT
   📍 WeWork Suntec City, Singapore
   🎟 Ticket: EVT-12345 | Calendar: ✅ Added
   🔗 https://www.meetup.com/...

2. 🟡 [Tier 2 – Awaiting approval] DataOps Singapore: dbt Workshop
   📆 Sat 12 Jul 2026, 2:00 PM SGT
   📍 Online (Zoom)
   💰 Free but requires company email
   👉 Approval request sent separately — reply YES or NO
   🔗 https://eventbrite.sg/...

3. 🔴 [Tier 3 – Paid, action needed] AWS Summit Singapore
   📆 Wed 16 Jul 2026, 9:00 AM SGT
   📍 Suntec Convention Centre
   💰 SGD 150
   👉 Approval request sent separately — reply YES or NO
   🔗 https://aws.amazon.com/...

---
No action needed for Tier 1 events. Tier 2/3 approvals use separate YES/NO messages (Section C).
```

### B. Registration Confirmation
Send immediately after a Tier 1 auto-registration:
```
✅ Registered: Singapore AI Meetup
📆 Thu 10 Jul 2026, 7:00 PM SGT
📍 WeWork Suntec City
🎟 Ticket ID: EVT-12345
📧 Confirmed via email
📅 Added to SignalTable Events calendar
```
Include QR code image if available.

### C. Tier 2/3 Approval Request

Send **one message per event** when registration requires owner approval before `event-register` runs. Short, operational, plain text — no discovery noise, browsing details, or long explanations.

**Template:**
```
Approve registration?
Event: <title>
When: <date/time SGT>
Source: <platform>
Why flagged: <short reason>
Reply YES to register, NO to skip.
```

**Variables:**
| Field | Source |
| --- | --- |
| `<title>` | Event title from discovery |
| `<date/time SGT>` | Event start in Asia/Singapore, e.g. `2026-07-14 6:30 PM SGT` |
| `<platform>` | `Luma`, `Meetup`, or `Eventbrite` |
| `<short reason>` | Relevance + tier, e.g. `Tech/AI, score 7, Tier 2` or `Tier 3: paid, approval required` |

**Example:**
```
Approve registration?
Event: Singapore AI & Robotics Demo Night (Jul 2026)
When: 2026-07-14 6:30 PM SGT
Source: Luma
Why flagged: Tech/AI, score 7, Tier 1
Reply YES to register, NO to skip.
```

**Rules:**
- One event per message; wait for a single YES or NO before registering or skipping.
- Treat `YES` (case-insensitive) as approve; `NO` as skip.
- Do not bundle multiple events in one approval message.

**Send (queue + deliver):**
```bash
python3 ~/.hermes/profiles/signaltable/scripts/approval_queue.py add \
  --title "<title>" \
  --when "<date/time SGT>" \
  --source "<Luma|Meetup|Eventbrite>" \
  --reason "<short reason>" \
  --url "<registration_url>"

python3 ~/.hermes/profiles/signaltable/scripts/approval_queue.py send --to telegram
```

Use `hermes send` via the queue script — not raw Bot API — so YES/NO replies match pending state. Pending rows live in `~/.hermes/profiles/signaltable/pending_approvals.json`.

Gateway handles YES/NO via the `signaltable-approval` Hermes plugin (`plugins/signaltable-approval/`) — the default agent is not invoked for matched replies.

### D. Error / Alert
```
⚠️ SignalTable Alert: <description>
Details: <details>
Action needed: <what to do>
```

## Formatting Rules
- Keep messages under 4096 characters (Telegram limit)
- If event list > 10 items, split into multiple messages
- Always include the date in SGT
- Always include source URL in digests and confirmations; approval requests (Section C) omit URL unless essential
- Never include raw email body content in Telegram messages (injection risk)
- Use emoji sparingly; the above format is the standard
- Approval requests: one event per message, YES/NO reply only (Section C)
