# WhatsApp outbound templates (Day 16)

Meta's WhatsApp rules: inside the **24h service window** since the guest's last
message, a business can send **free-form text** (a *service* message) at no
cost. Outside the window, **every** proactive outbound message must use an
**approved template** — free-form text is silently dropped.

The code (see `app/channels/whatsapp/window.py` + `templates.py`) chooses
automatically. What it needs from you is the templates **approved**:

## Submission checklist (ops — approval takes days, start now)

1. Open the BSP dashboard (360dialog **or** Twilio sandbox **or** Meta
   Business) for the sandbox number.
2. Create each template below with the **exact name** and **body** — variable
   order matters (see "Variable order").
3. Submit for approval. Book this in as a **long-lead** item (same discipline
   as the Day-1 Meta verification): until a template is approved, an
   out-of-window send of that intent is a **loud error** in the logs, never a
   silent drop.
4. Confirm the approved names match the env config:
   - `WHATSAPP_TEMPLATE_CONFIRM=booking_confirmed`
   - `WHATSAPP_TEMPLATE_REMINDER=booking_reminder`

## The templates

### 1 · `booking_confirmed`

Sent when a reservation is fulfilled (outside the service window).

**Body:**
```
Your table for {{1}} on {{2}} at {{3}} is confirmed. We look forward to seeing you!
```

**Variable order:** `1=party_size` · `2=date` (ISO, e.g. `2026-08-14`) ·
`3=time` (24h, e.g. `20:30`) · optional `4=area`

### 2 · `booking_reminder`

Sent ~2h before the booking (the Day-12 reminder scheduler).

**Body:**
```
Reminder: you have a table for {{1}} on {{2}} at {{3}}. See you soon!
```

**Variable order:** same as above.

### 3 · `booking_updated`

Reserved for modification notifications (wired in Day 16; used when a guest
changes a booking and the update is confirmed).

**Body:**
```
Your booking has been updated: {{1}} guests on {{2}} at {{3}}. We'll see you then!
```

**Variable order:** same as above.

## How the code uses these

| Intent (`notify` payload `subject`) | Template | Send mode |
|---|---|---|
| `confirmation` | `booking_confirmed` | text if in-window, template if out |
| `reminder` | `booking_reminder` | template (almost always out of window) |
| explicit `payload["template"]` | whatever is named | overrides the subject mapping |

- In-window sends are free-form **text** (`send_text`) — the ₦0 cost lever from
  the business model.
- Out-of-window sends are `send_template(name, variables)` with variables
  filled from the confirmed `Reservation` row.
- If out-of-window **and** no approved template exists → the send is blocked,
  logged loudly, and persisted as a failed Message (visible in the Day-17
  console) — never a silent drop.
