# PythaFlow — Go-To-Market Plan (v1: land the first paying venue)

*The build is ahead of the go-to-market. This plan closes that gap. Nothing here
requires new product beyond the current sprint.*

---

## 1. The one goal

> **One Nassau venue paying anything (even $50/mo) for the concierge, with a
> measured "recovered bookings" number, within 30 days of pilot start.**

One paying pilot converts our positioning from theory to proof. It answers the
market's real questions better than any feature we could ship.

## 2. Beachhead: Nassau, Bahamas — and why

The old target doc listed 30+ countries. That was the horizontal trap. We pick
**one city** where we have unfair advantages:

| Advantage | Detail |
|---|---|
| **Warm anchor** | Graycliff relationship already open (outreach sent 2026-07-10) |
| **Named data** | 120 real venues in `bahamas_restaurants.csv` → `Target_List_Nassau.md` |
| **Market shape** | Tourism-driven: guests message at all hours, in many languages — the exact pain we solve |
| **Small pond** | ~120 venues; hospitality owners talk to each other. 3 happy venues = market-wide word of mouth |
| **English + WhatsApp-heavy** | Matches the Phase-0 product exactly (web chat + WhatsApp text) |

US/Canada/Europe wait until Nassau produces a case study. **Beachhead, then expand.**

## 3. What we sell (pilot offer)

**The Founding Venue Pilot** — see `Pilot_Offer_OnePager.md`:
- 30 days free, white-glove: we ingest their menu/hours/policies and put the
  concierge on their website + a WhatsApp number. Zero effort from their staff.
- Human-in-the-loop: every booking confirmed by their team; weekly transcript +
  recovered-bookings report.
- After 30 days: **$99/mo founding-partner rate** (locked for 12 months) in
  exchange for a named case study + referral intro to 2 peer venues.
- Cancel anytime; their data deleted on request.

Why ~$99 and not more: the goal of pilot #1 is **proof velocity**, not revenue.
The founding rate is deliberately under-priced against the value math (§5) and
priced *above zero* because a $0 pilot proves nothing about willingness to pay.

## 4. The funnel (numbers, not vibes)

```
45 named venues (Target_List_Nassau.md)
  → 12 Tier-A contacted week 1  (email + follow-up + WhatsApp/walk-in)
  → expect 3–5 conversations    (25–40% — small market, personalized notes)
  → 2–3 agree to free pilot
  → 1+ converts to paying at day 30
```

**Weekly motion (repeats until pilot #1 is signed):**
- Mon: send 6 personalized emails (template v2) · Tue: 6 more
- Wed: follow up anyone silent ≥3 days (follow-up template)
- Thu: WhatsApp/phone touch on any venue with a listed number; walk-ins if local
- Fri: update `Outreach_Tracker.md`; move Tier-B names up to replace dead Tier-A

**Graycliff:** follow-up was due 2026-07-17 → **send it now** (template in
`Outreach_Email_Template.md` §Follow-up). Graycliff is the anchor but NOT the only
egg in the basket — the Tier-A 12 run in parallel.

## 5. The ROI math (what we claim, and how we prove it)

Formula (conservative, per venue):

```
recovered revenue / month =
    missed after-hours enquiries per week      (measure in pilot; owners estimate 5–15)
  × booking conversion when answered            (assume 40%)
  × average party size                          (assume 3)
  × average spend per cover                     (Nassau casual ~$45; fine dining ~$95)
  × 4.3 weeks
```

Worked example (casual venue, conservative inputs):
`8/wk × 40% × 3 × $45 × 4.3 ≈ $1,858/mo recovered` → vs $99/mo = **~19× ROI**.
Fine dining at the same volume: `≈ $3,922/mo` → **~40× ROI**.

**Rule: we never assert these numbers — we measure them.** The pilot's weekly
report counts actual after-hours conversations handled and bookings drafted.
Day-23 analytics instruments this in-product; until then it's a manual count from
the transcripts (which we already persist).

## 6. Answering the four hard questions (the brutal-review test)

1. **Which businesses, by name?** → `Target_List_Nassau.md`: 45 named venues,
   tiered, with websites/phones. Graycliff as warm anchor. Not demographics — names.
2. **Exact 30-day ROI?** → §5 formula, measured not asserted; weekly recovered-
   bookings report is the deliverable.
3. **Why not Synthflow + Zapier?** → An owner doesn't want a toolbox, they want a
   *staffed outcome*: we ingest their menu/policies, ground every answer in their
   real facts (no hallucinated prices — calibrated similarity floor), route every
   booking through their staff's approval, and hand them a weekly revenue report.
   White-glove + hospitality-specific + human-in-the-loop is the product; the
   APIs are plumbing. (This answer gets stronger with each integration we ship.)
4. **Provider price shock?** → Provider-agnostic seam, already demonstrated live
   (NVIDIA ↔ Groq via one `.env` edit). Embeddings and LLM decoupled. No single-
   vendor dependency anywhere in the brain.

## 7. What we do NOT do (scope discipline)

- No US/EU outreach until a Nassau case study exists.
- No voice promises in outreach — text concierge only (voice is Phase 1; we sell
  what's built).
- No "proactive campaigns" language anywhere. We sell **reliable + supervised**.
- No custom feature commitments to close a pilot beyond KB content and branding.

## 8. Risks & honest mitigations

| Risk | Mitigation |
|---|---|
| Nobody replies to cold email | Small market: WhatsApp + phone + walk-in touches; Graycliff referral ask; 45 names is 3 full weekly cycles |
| Pilot venue goes quiet | Weekly report keeps us in their inbox with *their* revenue number |
| "Free pilot" freeloaders | 30-day hard stop; converts at $99 or churns — either result is data |
| WhatsApp BSP approval lag | Start pilots on web chat (zero approval needed); add WhatsApp when verified |
| Solo-founder bandwidth | GTM motion is ~5 hrs/week; sprint continues on the other days |
```
