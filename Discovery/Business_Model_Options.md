# PythaFlow — Business Model: Options, Analysis & Recommendation

**Purpose:** decide *how PythaFlow makes money* — grounded in a real, measured cost
stack, not vibes. This is the document that turns your "we'll set the price after
we measure what the system actually costs" decision into a defensible number.

**Date:** 2026-07-25 · **Planning FX:** ₦1,450/$ (conservative — official ~₦1,380,
parallel ~₦1,420 as of July 2026; costed high on purpose so margins are understated,
not overstated).

**How to read this:** every section lays out *all the viable options*, explains the
trade-offs, and ends with **▶ Recommendation** and why. Nothing here contradicts the
two market-research reports (`Research_Nigeria_Hospitality_AI.md`,
`Research_Nigeria_SMB_AI_Assistant.md`) — it builds the money model on top of them.

---

## 0. The one principle that governs everything

> **Category positioning is the whole pricing game.** If a Lagos owner files
> PythaFlow under *software* (Orda POS: ₦1k–₦20k/mo) we are 5–10× overpriced. If
> they file it under *demand generation / revenue recovery* (social retainers
> ₦300–400k/mo, one influencer post ₦500k+), ₦100k/mo is cheap.

Every model choice below is judged by one test: **does it make the buyer experience
PythaFlow as recovered revenue, not as a software cost?** A cost line gets cut in the
first slow month (the Q1 churn cliff the research flags). A revenue line does not.

---

## 1. The cost stack (measured, July 2026)

You can't price what you haven't measured. Here is what the system actually costs to
run, per line, with sources.

| Input | Rate | Source |
|---|---|---|
| Groq — Llama 3.3 70B (recommended quality tier) | $0.59 in / $0.79 out per 1M tok | [CloudZero](https://www.cloudzero.com/blog/groq-pricing/) |
| OpenAI — gpt-4o-mini (cheap fallback) | $0.15 in / $0.60 out per 1M tok | [devtk](https://devtk.ai/en/models/gpt-4o-mini/) |
| Claude Haiku 4.5 (premium tier, best instruction-following) | $1.00 in / $5.00 out per 1M tok; cache −90% | [CloudZero](https://www.cloudzero.com/blog/claude-api-pricing/) |
| NVIDIA NIM (current dev default) | Free tier | current build |
| WhatsApp **service** msgs (guest-initiated, 24h window) | **$0.00** | [Blueticks](https://blueticks.co/blog/whatsapp-business-api-pricing-2026) |
| WhatsApp **utility** template (booking confirmation) | ~$0.004 / msg (+ BSP markup $0.003–0.010) | [Blueticks](https://blueticks.co/blog/whatsapp-business-pricing-change-2026-per-message) |
| Managed Postgres + pgvector | ~$25/mo (platform-wide) | Neon/Supabase/DO class |
| App server (Hetzner CX32-class) | ~€12/mo (~₦19k) | [Hetzner](https://betterstack.com/community/guides/web-servers/hetzner-cloud-review/) |
| Paystack (collect the monthly invoice) | 1.5% + ₦100, **capped ₦2,000** | [Paystack](https://support.paystack.com/en/articles/2130306) |

**The critical fact:** the concierge's main mode — a guest messaging the venue on
WhatsApp — is a **service** conversation, which is **free** on Meta's platform since
Nov 2024. Our per-message channel cost is effectively ₦0. Compute is our only real
variable cost, and it's small.

### Per-venue monthly economics (worked, conservative)

Assumptions: busy island venue ≈ **500 guest conversations/month** (≈1,200 in the
December surge); 8 AI replies per conversation; ~2,500 input + 200 output tokens per
reply.

| Cost line | Groq 70B (recommended) | Claude Haiku 4.5 (premium) |
|---|---|---|
| LLM (500 convos) | ~$6.5 → **₦9,400** | ~$14 → **₦20,300** (₦12k with prompt cache) |
| Embeddings (query-time) | ~₦300 | ~₦300 |
| Infra allocation (@10 tenants) | ~₦8,000 | ~₦8,000 |
| WhatsApp utility templates (~200 confirmations) | ~₦1,200 | ~₦1,200 |
| Paystack (1 invoice) | ~₦1,600 | ~₦1,600 |
| **Total marginal COGS / venue / mo** | **≈ ₦20,500** | **≈ ₦23,600** |
| **Gross margin at ₦100k price** | **≈ 80%** | **≈ 76%** |
| December surge (1,200 convos), Groq | COGS ≈ ₦34,000 | margin ≈ 66% |

Add a part-time ops person at scale (₦150k/mo covering ~20 venues ≈ ₦7,500/venue) and
the **fully-loaded margin is still ~70%.** The economics are *not* the risk. The risk
is distribution (CAC = founder hours) and churn — exactly what the research says.

**Takeaway for your pricing decision:** at the research's recommended **₦100k/month**,
compute leaves you ~80% gross margin with generous headroom for the December spike and
a support hire. You do not need to fear the cost side. What you're really waiting to
measure before *finalizing* price is (a) real conversation volume per venue and (b)
whether the quality tier needs to be Haiku (premium) or Groq is good enough — both of
which the pilot instrumentation (the Day-8 `Action`/token logging) will give you.

---

## 2. Revenue model — the options

Seven ways PythaFlow could charge. Each judged on: fit to the "revenue not software"
principle, margin safety, and Nigeria-market reality (FX risk, buyer psychology).

### A. Flat monthly subscription (one price, all-you-can-use)
- **How:** ₦X/month, unlimited conversations.
- **Pros:** dead simple to sell and to invoice (matches your manual-invoice decision);
  predictable for the venue; no "meter anxiety" that suppresses usage; margin is fat
  enough (§1) to absorb heavy users.
- **Cons:** a single whale venue in December could compress margin; leaves
  value-based upside on the table for high-volume venues.
- **Fit:** ★★★★★ — simplicity is a feature in a market that has "never bought software."

### B. Tiered subscription (Good / Better / Best by channels & volume)
- **How:** e.g. Web-only < Web+WhatsApp < Multi-channel+hotel features, with soft
  volume bands.
- **Pros:** Nigerian SMBs "never buy the cheapest tier — they buy mid" (research);
  tiers create a natural mid-anchor; lets hotels pay more for more.
- **Cons:** more to explain; premature before you know the feature lines that matter.
- **Fit:** ★★★★☆ — the *right destination*, but only after 5–10 venues reveal which
  features cluster.

### C. Usage / per-conversation (metered)
- **How:** ₦Y per conversation, or a bucket + overage.
- **Pros:** aligns cost to price; "pay for what you use" feels fair.
- **Cons:** **meter anxiety kills the product** — an owner who sees a per-message
  counter will discourage the very usage that creates value; unpredictable invoices
  erode trust; re-introduces the "software cost" framing we must avoid.
- **Fit:** ★★☆☆☆ — good for *your* internal cost model, bad as the *customer's* bill.

### D. Per-outcome / commission on bookings (₦ per confirmed booking or % of covers)
- **How:** ₦Z per approved reservation, or a small % of the recovered cover value.
- **Pros:** the *purest* "revenue not software" framing — you literally only earn when
  they earn; devastating in a pitch ("we only get paid when you get a booking").
- **Cons:** requires trustworthy attribution (was this booking *because of* PythaFlow?)
  which is disputable and gameable; owners hate variable %-of-revenue deals with
  vendors; measurement burden; slow to invoice manually.
- **Fit:** ★★★☆☆ — magic in the *narrative*, painful in *practice*. Use the outcome
  as the **proof metric** (the weekly recovered-bookings report), not the **billing
  mechanism.** (See recommendation.)

### E. Setup/onboarding fee + monthly retainer
- **How:** one-time white-glove setup fee (₦W) + monthly ₦X.
- **Pros:** the setup fee filters tyre-kickers, funds your onboarding labor, and
  signals seriousness (free = "no value" in this market, per research); retainer
  framing matches how venues already pay agencies.
- **Cons:** the upfront ask adds friction to the very first close.
- **Fit:** ★★★★☆ — strong once you have proof; for pilot #1, a *paid pilot fee*
  plays this role.

### F. Annual prepay (with a December guarantee)
- **How:** 12 months paid up front (often discounted), or a Sept–Jan "Detty December"
  package.
- **Pros:** smooths the Q1 churn cliff the research warns about; locks the customer
  through the one season where value is undeniable; improves cash flow massively for a
  bootstrapper; hedges FX (you hold naira now).
- **Cons:** large upfront ask; harder for a first-time buyer; you owe service all year.
- **Fit:** ★★★★☆ — excellent as an *option to offer* (esp. to hotels and post-proof
  venues), not as the only way to buy.

### G. Freemium / free tier
- **How:** free basic bot, pay to unlock.
- **Pros:** viral-ish; low friction.
- **Cons:** **actively harmful here** — Meta already ships free DM answering (Meta
  Business Agent, June 2026); competing on "free" means competing with Meta and
  signalling zero value; the graveyard (Kippa, Sabi) is full of huge free user counts
  that never converted. Free pilots "signal zero value" (research §7).
- **Fit:** ★☆☆☆☆ — avoid.

### ▶ Recommendation: **Flat monthly subscription (A), sold with the recovered-bookings report as the value proof, priced as a retainer, with an annual/December option (F) and a paid pilot fee (E) as the on-ramp.**

Concretely, the model is:
1. **Bill:** a simple **flat ₦/month** (option A) — trivial to invoice manually, no
   meter anxiety, ~80% margin absorbs heavy months.
2. **Sell:** on **outcome** (option D's *narrative*) — the weekly recovered-bookings
   report is what renews the subscription; you show revenue, you bill a flat fee.
3. **On-ramp:** a **paid pilot fee** (option E) — never free.
4. **Upside:** offer **annual prepay / Sept–Jan December package** (option F) to
   hotels and proven venues to beat the Q1 cliff.
5. **Later:** graduate to **tiers** (option B) once features cluster.

This gives you Meta-proof positioning (outcome, not "a bot"), a bootstrapper-friendly
cash model, and margins that survive the December surge.

---

## 3. Packaging — the options

| Option | Shape | Verdict |
|---|---|---|
| **Single plan** | one product, one price | ★★★★★ **start here** — clarity wins in a first market; zero decision friction |
| **Restaurant vs Hotel** | two SKUs, hotel priced higher (multi-channel, guest-services) | ★★★★☆ the natural *first* split; research already prices hotels higher (₦150k) |
| **Channel tiers** | Web / +WhatsApp / +IG+multi | ★★★☆☆ defer — channels will bundle; don't fragment early |
| **Feature tiers** | e.g. +deposit collection, +no-show analytics, +CRM | ★★★★☆ the real long-term tier axis — but only after pilots reveal willingness |

**▶ Recommendation:** launch with **one plan for restaurants + a higher Hotel plan**
(two SKUs, no more). Add feature tiers only when a pilot venue asks to pay for
something specific (deposit collection is the likely first one — research §6 flags it
as a high-value natural extension).

---

## 4. Price level — the options (and honoring your "measure first" decision)

You decided: **don't finalize price until the system's real cost + volume are
measured.** §1 already de-risks the *cost* half of that. What remains to measure is
*volume per venue* and *required quality tier* — both delivered by the pilot's token
logging. So the discipline is right; here are the options for where it lands.

| Anchor | Monthly price | Logic | Risk |
|---|---|---|---|
| **Software anchor** | ₦20–40k | matches Orda's top tier | ✗ death — no headroom, filed as "software", churns |
| **Sub-salary anchor** | ₦60–85k | "cheaper than a host (₦85k)" | ✗ invites "then I'll just hire someone"; Lagos values human service |
| **Marketing-budget anchor** (recommended) | **₦100k restaurants / ₦150k hotels** | vs ₦300–400k social retainer, ₦159k Starlink, ₦500k+ influencer post | ✓ headroom, ~80% margin, "revenue" framing |
| **Value/premium anchor** | ₦200k+ | one recovered ₦150k table/week justifies it | ○ true but unprovable pre-pilot; raise *after* case studies |

**▶ Recommendation:** **Launch anchor ₦100k/mo (restaurants), ₦150k/mo (hotels),**
positioned against the marketing line — *the exact number the hospitality research
independently landed on.* Treat it as the **launch price to validate**, not a
permanent number:
- **Pilot month:** ₦50k paid pilot (with recovered-bookings guarantee).
- **After 8–12 weeks of telemetry:** confirm or adjust using real per-venue volume &
  the actual quality tier cost from §1. If volumes run low and Groq quality holds, you
  have room to *hold* ₦100k at even fatter margin (don't cut — you're not competing on
  price with Meta, you're competing on outcome). If a premium Haiku tier proves
  necessary and volumes are high, you still clear ~70%.
- **Post-proof (3+ named case studies):** introduce a ₦150–200k premium/flagship tier.

This is fully consistent with your decision: **you are deferring the final commit, but
you now have the cost half measured and a defensible launch anchor to test against.**

---

## 5. Billing & collections — the options

| Option | Fit | Notes |
|---|---|---|
| **Manual monthly invoice + Paystack/transfer link** (your decision) | ★★★★★ | Right for pilot phase: zero billing code, human relationship, Paystack fee ≤₦2,000/venue is negligible. Matches Lagos "relationship-first" buying. |
| Paystack recurring / card-on-file | ★★☆☆☆ | Nigeria is transfer-first, not card-first (research §6) — card mandates fail; premature |
| Direct debit (NIBSS e-mandate) | ★★★☆☆ | Real option *later* for retention (harder to churn), but setup overhead now |
| Prepaid credits/wallet | ★★☆☆☆ | Reintroduces meter anxiety; skip |
| Annual invoice (prepay) | ★★★★☆ | Offer alongside monthly (see §2F) for cash flow + Q1 hedge |

**▶ Recommendation:** **keep your manual monthly invoice + Paystack link** as the
default, and **add an annual-prepay invoice option** for hotels and renewers. Move to
NIBSS direct-debit only once you have >10 paying venues and churn data justifies the
retention play. **Invoice in naira, always** (research: dollar pricing spikes churn).

---

## 6. Provider/cost strategy — the options (this is a margin lever *and* a sales asset)

Your provider-agnostic seam means the LLM vendor is an `.env` change. That's both a
cost lever and a pitch answer ("what if your AI provider raises prices?" → "we swap in
one line, already demonstrated").

| Provider | Cost/venue/mo (500 convos) | Quality | Role |
|---|---|---|---|
| **NVIDIA NIM** | Free tier | Good, slow to first token | Dev / cost-floor fallback |
| **Groq Llama 3.3 70B** | ~₦9,400 | Good + fastest (276 tok/s) | **▶ recommended default** — speed matters for chat |
| OpenAI gpt-4o-mini | ~₦4,000 | Decent | cheapest paid fallback |
| **Claude Haiku 4.5** | ~₦12–20k | Best instruction-following/brand-voice | premium tier for flagship venues |

**▶ Recommendation:** **default to Groq** (speed + margin), keep **NVIDIA free tier**
as the zero-cost fallback, and offer **Claude Haiku 4.5** as the quality tier for
flagship/hotel accounts where brand-voice fidelity justifies the ~₦8k/mo extra. Let the
pilot's token telemetry decide whether Groq quality is sufficient venue-by-venue. The
seam makes this a per-tenant knob, not a company-wide bet.

---

## 7. The recommended model, assembled (one paragraph)

**PythaFlow sells a flat monthly retainer — ₦100k for restaurants, ₦150k for hotels,
billed by manual naira invoice + Paystack link — entered through a ₦50k paid pilot with
a recovered-bookings guarantee, and offered as an annual/Sept–Jan prepay for cash flow
and December lock-in. It is *sold* on the weekly recovered-revenue report (outcome
narrative), never metered to the customer. It runs on Groq by default (~80% gross
margin), with NVIDIA free as a floor and Claude Haiku as a premium tier. The launch
price is the number to validate over 8–12 weeks of cost+volume telemetry; the cost half
is already measured and safe.** This is Meta-proof (outcome, not "a bot"),
bootstrapper-friendly (fat margin, upfront cash options), and matched to how Lagos
venues actually buy.

---

## 8. What still needs measuring before you *lock* the price (your decision, made concrete)

1. **Conversations/venue/month** — real distribution across pilot venues (Day-8 token
   logging gives this).
2. **Quality tier needed** — does Groq hold brand voice, or do flagship venues need
   Haiku? (A/B in pilot.)
3. **December multiplier** — measure the surge on live venues; it sets the annual/
   December package price.
4. **Onboarding hours/venue** — your true labor cost per venue; sets the setup fee and
   the point at which you hire ops.
5. **Willingness-to-pay ceiling** — did any pilot venue flinch at ₦100k, or would ₦150k
   have closed too? (Ask on every close/loss.)

When those five are in hand, the final price is arithmetic, not a guess — exactly the
discipline you asked for.
