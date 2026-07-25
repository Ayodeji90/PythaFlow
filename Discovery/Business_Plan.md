# PythaFlow — Business Plan

**The AI concierge for premium Lagos hospitality: answers every guest 24/7 on
WhatsApp/Instagram/web, grounded in the venue's real menu & policies, and turns
after-hours enquiries into human-approved bookings.**

**Date:** 2026-07-25 · **Stage:** pre-revenue, product in build (Week 2 of sprint),
first pilots targeted for Sept–Oct 2026 (ahead of Detty December).
**Companion docs:** `Business_Model_Options.md` (money model), `Business_Proposal.md`
(customer-facing), `Research_Nigeria_Hospitality_AI.md` + `Research_Nigeria_SMB_AI_Assistant.md`
(evidence base). Every market claim here traces to those research reports.

---

## 1. Executive summary

Premium Lagos restaurants, lounges and boutique hotels take most of their bookings
through Instagram DMs, WhatsApp voice notes and a paper book — and lose the ones that
arrive after staff clock out or during the dinner rush. No incumbent, local (Reisty,
MoreTables) or global (OpenTable/Resy — effectively absent), owns this
**DM-to-booking workflow.** PythaFlow is an AI concierge that sits on the channels
guests already use, answers only from the venue's real facts (no hallucinated
prices), and drafts every booking as a **human-approved request** — the venue's staff
stays in charge.

- **Market:** ~200–500 Lagos venues fit the "premium, reservation-taking,
  Instagram-active" profile; beachhead is **60–100 fine-dining venues in
  VI/Ikoyi/Lekki**, win 15–20.
- **Why now:** the dining scene is booming (continuous premium openings; Detty
  December 2024 = ~1.2M visitors, ₦54bn in hotel revenue), and AI concierge tech just
  got validated in Sub-Saharan Africa (CityBlue×Inntelo, Kenya, April 2026) — but no
  one is doing venue-side AI guest messaging in Nigeria yet.
- **Model:** flat retainer, **₦100k restaurants / ₦150k hotels**, ~80% gross margin
  (compute cost measured — see `Business_Model_Options.md`), sold on a weekly
  recovered-revenue report, entered via a ₦50k paid pilot.
- **Moat vs Meta:** Meta Business Agent (June 2026) commoditizes generic "AI answers
  DMs." PythaFlow is *not* that — it's hospitality-specific, grounded-in-your-facts,
  human-in-the-loop, cross-channel, sold white-glove by a founder who shows up. Meta
  ships a feature; PythaFlow delivers a staffed outcome.
- **Ask / plan:** bootstrap to 10 paying Lagos venues by Q1 2027 on founder-led
  walk-in sales; use the December surge as the proof engine.

**Honest headline:** by raw SaaS math Lagos is not a *big* first market (a few hundred
venues, a hostile software price anchor). It *is* the right first market because the
buying behavior — WhatsApp bookings, walk-in trust, December surges — matches exactly
what PythaFlow does and how a Nigerian founder can sell it.

---

## 2. Problem

1. **Bookings happen in DMs, and DMs leak.** "Most Lagos restaurants take bookings
   through DMs, voice notes, and a paper book" (MoreTables positioning). Slow replies
   during service, unanswered messages overnight, voice notes nobody transcribes — each
   is a booking that goes to the venue down the street.
2. **The leak is worst exactly when value is highest.** During Detty December demand
   10×'s for weeks; humans don't scale for six weeks and then unscale. Top clubs ran
   ₦1.2M tables; a single missed fine-dining table of four is ₦200k–600k.
3. **No one owns the workflow.** OpenTable/Resy never localized (card-on-file doesn't
   fit Nigeria's transfer-first rails). Reisty (~100 venues, ~2,000 users) is
   consumer *discovery*, not venue-side ops. The inbox is unowned software territory.

**What PythaFlow is NOT solving:** staff replacement. Labor is too cheap (₦85k Lagos
min wage; host ₦75–150k). The pitch is *recovered revenue and after-hours coverage*,
never "fire your receptionist."

---

## 3. Solution & product

An AI concierge that:
- **Answers 24/7** on web chat + WhatsApp (+ Instagram roadmap), in the guest's
  language, in the venue's brand voice.
- **Grounds every answer in the venue's real facts** (menu, hours, policies) via
  retrieval with a calibrated similarity floor — if it doesn't know, it says a team
  member will follow up rather than inventing a price.
- **Creates structured booking Requests** that a human approves before anything is
  confirmed (the "Request" + approval queue — Week 2 build). Staff stays in charge.
- **Hands off gracefully** to a human on request or on anything sensitive (guardrails).
- **Reports weekly:** every after-hours conversation handled, every booking captured,
  and the revenue those represent — the retention engine that keeps the subscription
  framed as *revenue, not cost.*

**Architectural edges that matter in Lagos:** runs on the *guest's* phone/cloud, so it
keeps answering when the venue's power/internet dies (a real advantage over venue-side
POS/PMS); provider-agnostic LLM seam (swap vendors in one `.env` line — a genuine
answer to "what if your AI provider hikes prices?").

**Build status:** grounded chat + guardrails live; Week 2 adds the tool-calling
framework and the Request/approval queue (the thing owners see in the demo). Voice is
a later phase — the plan sells only what's built (text concierge).

---

## 4. Market

**Sizing (from `Research_Nigeria_Hospitality_AI.md`; treat as order-of-magnitude):**

| Layer | Figure |
|---|---|
| Nigeria foodservice market | ~$10–12bn (2024→26), dine-in ~64% |
| Lagos registered restaurants | ~8,477 (~29.5% of Nigeria) — *includes QSR/buka, mostly out of scope* |
| **SAM — premium, reservation-taking, IG-active Lagos venues** | **~200–500** (analyst estimate; no official census) |
| **SOM — beachhead (VI/Ikoyi/Lekki fine dining, yr 1)** | **60–100 target → 15–20 won** |
| Lagos 5-star hotels | 25+ (rooms from ~₦110k/night) |
| Detty December 2024 | ~1.2M visitors, ~$71.6M injected; hotels ₦54bn; top-15 clubs ₦4.32bn |

This is deliberately a **small, dense** market — which is a feature for a bootstrapper:
the island hospitality scene is tightly networked (Eat.Drink.Lagos, festivals, shared
owners), so 3 flagship logos create market-wide word of mouth.

---

## 5. Competition & moat

| Competitor | What they are | Why PythaFlow wins / coexists |
|---|---|---|
| **Meta Business Agent** (June 2026) | Free, built-in AI DM answering on WA/IG | Generic, not grounded in the venue's facts, no approval queue, Meta-channels only, no white-glove. We are hospitality-specific + human-in-the-loop + cross-channel + a founder who sets it up. Meta is a feature; we're an outcome. **Biggest threat — positioning must stay off "we answer DMs."** |
| **Reisty** (~100 venues) | Consumer reservation/discovery app | Demand aggregation, not venue-side inbox ops. **Partner/channel, not rival** — we answer the DMs Reisty never sees. |
| **MoreTables / Dineazi** | Early reservation/no-show tools | Booking-widget model; we meet guests in the DMs they actually use. |
| **OpenTable / Resy** | Global reservation platforms | Effectively absent in Nigeria (card-on-file ≠ transfer rails). Ceded market. |
| **Orda → Moniepoint "Moniebook"** | Restaurant POS/back-office | Different job (payments/back-of-house). Sets a *cheap software price anchor* we must avoid being compared to. Potential future channel/partner. |
| **DIY (Synthflow + Zapier / generic chatbot builder)** | Owner assembles their own | Owners want a *staffed outcome*, not a toolbox: we ingest their facts, ground every answer, route bookings through approval, and hand them a revenue report. White-glove + hospitality-specific is the product; the APIs are plumbing. |

**The moat is not the model — it's the wrapper:** proprietary venue knowledge
ingestion + brand-voice fidelity + the human-approval workflow + the weekly
revenue-proof report + founder-led trust, in a market where the buyer answers WhatsApp
and buys from "people like them." None of that is what Meta ships.

---

## 6. Positioning

> **Not** "an AI chatbot for your restaurant."
> **Yes:** "a member of your team that answers every guest the moment they message —
> day or night — and never lets a booking slip, while your staff approves everything."

Category: **revenue recovery / demand capture** (price-anchored to marketing spend),
**never** software (Orda anchor) or labor (host salary). See
`Business_Model_Options.md §0`.

---

## 7. Go-to-market — the options

| GTM motion | Pros | Cons | Verdict |
|---|---|---|---|
| **Founder-led walk-ins** (Tue–Thu 3–5pm lull, demo on owner's phone, close on WhatsApp) | Proven motion (how Orda won, 91% retention); trust-first; zero cash CAC; instant demo | Founder-time bound (~5–8 hrs/wk); doesn't scale past ~solo | ★★★★★ **primary** |
| **Referral / flagship case study** | Island scene is densely networked; one flagship logo > any ad | Needs first proof to start | ★★★★★ **engine once seeded** |
| **WhatsApp/IG DM outreach + food-media ecosystem** (Eat.Drink.Lagos, festivals) | Buyers answer WhatsApp before email; ecosystem is concentrated | Noisy; needs warm intros | ★★★★☆ **support** |
| Cold email | Cheap, async | Lagos buyers under-answer email; low trust | ★★☆☆☆ |
| Paid ads / inbound | Scales | Wrong for a 200-venue market; expensive; low trust | ★☆☆☆☆ (later, if ever) |
| Channel partnership (Reisty / Moniebook / a food festival) | Distribution leverage | Slow; dependency; premature pre-proof | ★★★☆☆ (year 2) |

**▶ Recommendation:** **founder-led walk-ins as the primary motion, seeded now, with
the recovered-bookings case study as the referral engine, supported by WhatsApp
follow-up and the food-media network.** Sign venues **Sept–Nov** so the December surge
produces an undeniable proof number; use Q1 (slow season) as the real retention test.

**Sales math (beachhead):** 60–100 named target venues → contact 12/week → 3–5
conversations → 2–3 pilots → 1+ paying at day 30. Repeat.

---

## 8. Business model (summary — full analysis in `Business_Model_Options.md`)

- **Revenue:** flat monthly retainer, **₦100k restaurants / ₦150k hotels**; sold on the
  weekly recovered-revenue report; entered via **₦50k paid pilot** (never free);
  annual/Sept–Jan prepay offered for cash flow + December lock-in.
- **Billing:** manual naira invoice + Paystack link (your decision) — Paystack fee
  ≤₦2,000/venue is negligible.
- **Unit economics:** ~₦20.5k marginal COGS/venue/mo on Groq → **~80% gross margin**;
  ~70% fully-loaded with a support hire; survives the December surge (~66%).
- **Price discipline:** ₦100k is the **launch anchor to validate** over 8–12 weeks of
  cost+volume telemetry; the cost half is already measured and safe.

---

## 9. Financial scenarios (illustrative, bootstrap)

Naira, first 18 months. Assumes founder-led sales, one part-time ops hire at ~15
venues, ₦100k blended price, ~75% gross margin, ~5% monthly churn post-pilot.

| Milestone | Paying venues | MRR | Gross profit/mo | Notes |
|---|---|---|---|---|
| Pilot (Oct 2026) | 2–3 @ ₦50k | ~₦125k | ~₦95k | proof, not profit |
| Post-December (Jan 2027) | 6–8 | ~₦700k | ~₦525k | December proof converts pilots |
| Q2 2027 | 10–12 | ~₦1.1m | ~₦825k | referral engine live |
| End yr 1 of selling (Q3 2027) | 15–20 | ~₦1.7m | ~₦1.25m | add ops hire; hotel SKU |
| Stretch (18 mo) | 25–30 | ~₦2.8m | ~₦2.0m | Abuja as market #2 |

**Break-even for a solo founder** (personal runway + ~₦100k infra + part-time ops)
lands around **8–10 paying venues** — a realistic Q1–Q2 2027 target. This is a
**profitable small business** trajectory before it's a venture-scale one; that's the
right shape for this market and this founder.

*(All figures illustrative — the pilot replaces them with measured numbers.)*

---

## 10. Funding — the options

| Option | Fit | Why |
|---|---|---|
| **Bootstrap on pilot revenue** | ★★★★★ | Fat margins + upfront pilot/annual cash + near-zero CAC = self-funding at small scale. Retains full ownership. The graveyard (Kippa $14M, Sabi $38M) shows raising *into* Nigerian SMB commerce is where startups *die*, not where they win. |
| **Non-dilutive grants / accelerators** (e.g. African tech accelerators, Google/Meta SMB programs) | ★★★★☆ | Free money + credibility + LLM credits; worth applying opportunistically, not depending on. |
| **Angel / pre-seed (local)** | ★★★☆☆ | Only *after* 5–10 paying venues prove the model; raise for a specific accelerant (sales hires, second city), not to discover the model. |
| **Revenue-based financing** | ★★☆☆☆ | Possible later against recurring MRR; premature. |
| **VC seed** | ★★☆☆☆ | Wrong stage & arguably wrong shape — this is a dense, sub-500-venue beachhead; raise only if a multi-city, multi-vertical expansion thesis proves out. |

**▶ Recommendation:** **bootstrap to ~10 paying venues on pilot revenue**, apply to
non-dilutive grants/credits in parallel, and only consider a small local angel round
*after* proof — to fund a specific expansion (Abuja, or a first sales hire), never to
find product-market fit. Ownership + optionality + survival all point the same way.

---

## 11. Risks & mitigations (the kill risks, honestly)

| Risk | Severity | Mitigation |
|---|---|---|
| **Category mispricing** (filed as "software"/"cheaper than a person") | High | Anchor to marketing budget; lead with the recovered-revenue report; never mention salaries/POS |
| **Meta closes the gap** | High | Stay off "we answer DMs"; compete on grounding + approval + white-glove + cross-channel + trust; Meta targets self-serve, we target relationship-sold premium venues |
| **The inbox has a human gatekeeper** who loses status if AI answers | Med-High | Champion must be the *owner*; make the inbox operator the hero of the weekly report; approve-before-send keeps them in control |
| **Q1 churn cliff + macro/FX** | High | Annual/December prepay; price in naira; December proof; keep the price a *revenue* line |
| **WhatsApp API/BSP friction & ToS** | Med | Start pilots on web chat (zero approval); add WhatsApp via a proper BSP; never risk a venue's number with unofficial gateways |
| **Solo-founder bandwidth** | Med | GTM ~5–8 hrs/wk; engineering team handles build; ops hire at ~15 venues |
| **Willingness-to-pay unproven at ₦100k** | Med | Paid pilot at ₦50k de-risks; measure flinch on every close; ₦150k premium tier only post-proof |
| **AI hallucination damages a venue's credibility** | Med | Grounding + similarity floor + "I'll check with the team" fallback + human approval on every booking |

---

## 12. Roadmap & milestones (next ~12 months)

| Window | Product | GTM |
|---|---|---|
| **Now–Aug 2026** | Finish Week 2 (tool-calling + Request/approval queue); deploy a phone-accessible demo instance; instrument token/cost logging | Build 60–100 named target list (Google Places + food media); refine the live demo; update pilot one-pager to naira |
| **Sept–Oct 2026** | Harden onboarding (fast menu ingestion, brand-voice tuning); WhatsApp via BSP | **Walk-in sales push**; sign 2–3 paid pilots before December |
| **Nov–Dec 2026** | Deposit-collection extension (transfer-first); no-show data capture | Ride Detty December; capture the recovered-bookings proof number live |
| **Jan–Mar 2027** | Weekly-report analytics polish; hotel guest-services features | Convert pilots to annual; publish first named case study; referral engine; survive Q1 as the retention test |
| **Q2–Q3 2027** | Tiering; IG channel; ops tooling | Scale to 15–20 venues; hire part-time ops; open Abuja (Maitama/Wuse 2) as market #2 |

---

## 13. The 90-day plan (what actually happens next)

1. **Product:** finish the Request/approval queue and stand up a **live, phone-accessible
   demo** loaded with a realistic Lagos fine-dining menu (this is the pitch mechanism).
2. **Instrument cost:** ship token/model logging so pricing is data-driven (unblocks
   the price-finalization decision).
3. **GTM assets:** naira-ize the pilot one-pager (`Business_Proposal.md`), build the
   60–100 venue target list, script the 90-second live demo.
4. **Sell:** start Tue–Thu walk-ins in VI/Ikoyi/Lekki; goal = **2–3 paid pilots signed
   before December**.
5. **Measure:** per-venue conversation volume, quality tier needed, onboarding hours,
   WTP — the five inputs that finalize the price.

**Definition of success at 90 days:** ≥2 paid pilots live, real recovered-bookings
numbers accruing into December, and the five pricing inputs measured.
