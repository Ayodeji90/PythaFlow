# Balance Website — UI/UX & Frontend Audit

**Date:** 2026-07-25
**Scope:** `balance-site/` (337 HTML / 532 CSS / 178 JS)
**Verdict:** 9/10 brochure. Strong craft, weak conversion. Gorgeous but doesn't match the Lagos fine-dining pivot or defend against Meta's free bot.

---

## P0 — Conversion & positioning (highest leverage)

| # | Finding | Why it matters | Proposed change |
|---|---|---|---|
| 1 | **No WhatsApp anywhere.** Every CTA is a `mailto:hello@getbalance.ai`. | Lagos B2B buyers answer WhatsApp before email (own research §7). A mailto is high-friction and dated. | Add a `wa.me` click-to-chat as the primary CTA ("Message us on WhatsApp"), keep email secondary. |
| 2 | **The hero chat is a movie, not a demo.** It's a canned, looping fake conversation. | The chosen pitch mechanism is the live phone demo. The site should let a visitor actually try the concierge. | Add a "Try it now — text our concierge" block with a real `wa.me` link + QR. This is the highest-conversion single change on the page. |
| 3 | **Zero differentiation vs Meta / free bots.** Meta Business Agent (June 2026) now answers DMs for free. | If a visitor thinks "Meta does this free," you're dead. This is the #1 strategic threat and the site never addresses it. | Add a short "Why not just the free bot?" beat: grounded in facts, human-approves every booking, your voice, cross-channel. |
| 4 | **Doesn't fit the Lagos pivot.** Copy says "restaurants, hotels and resorts," generic/global tone, no local trust signals. | Pivoted to premium Lagos fine-dining. "Resorts" dilutes the beachhead; a Nigerian founder's #1 barrier is trust, which local signals build. | Tighten ICP to fine-dining/hospitality; add a "Built in Lagos, for Lagos venues" trust cue; consider naira/December framing. |
| 5 | **No trust scaffolding.** No founder, no face, no "who's behind this," no data/privacy section, no guarantee. | New, unknown, Nigerian B2B product selling to skeptical premium owners — trust is the whole game. | Add a founder line + photo, a data-safety note, and surface the recovered-bookings guarantee from the proposal. |

## P1 — Content & information architecture

| # | Finding | Proposed change |
|---|---|---|
| 6 | **No objection handling / FAQ.** Owners silently ask: "Will it sound robotic? What if it's wrong? Does it replace my staff? Is my data safe? What's it cost?" | Add an FAQ section (also helps SEO). Answer the staff-replacement fear head-on (your positioning). |
| 7 | **The grounding + human-approval story is buried.** The core credibility feature — never invents a price, staff approves every booking — is one line in "How it works." | Make it a hero-adjacent promise and show it in the chat: an "I'll check with the team" moment + a staff-approval step. |
| 8 | **"See it in action" is fabricated data.** "7 reservations… Sample data shown." Honest, but it's fiction dressed as proof. | Reframe around the mechanism + the guarantee now; swap in a real named venue + real numbers the moment the first pilot lands. |
| 9 | **No pilot / pricing signpost.** Price is deferred (fine), but there's zero cost cue. | Add a light "Start with a paid pilot" / founding-venue hook to set expectations and match GTM. |

## Accessibility (concrete, verified)

| # | Finding | Fix |
|---|---|---|
| 10 | **Decorative glyphs are announced by screen readers.** Capability icons (◎ ↑ ✦ ≈ ✎ ☾), value-bar ✓, and → arrows are raw text, not `aria-hidden`. | Wrap decorative glyphs in `aria-hidden="true"` (or move to inline SVG). |
| 11 | **Muted caption contrast fails AA on tinted panels.** `--ink-mute #6C6F74` on `--smoke-2 #ECEDE8` ≈ 4.37:1 — below the 4.5:1 AA threshold for `.sample-note` and similar small italic text. | Darken `--ink-mute` a notch, or bump those captions' size/weight. |
| 12 | **No `<main>` landmark and no skip link.** | Wrap content in `<main>`; add a "skip to content" link. Cheap, standard. |

## P2 — Craft polish & code quality

| # | Finding | Fix |
|---|---|---|
| 13 | **Single-glyph icons cheapen an otherwise premium page.** ◎ ↑ ✦ ≈ ✎ θ are arbitrary and inconsistent in weight vs the Fraunces/Inter refinement. | Replace with a cohesive line-icon SVG set. Biggest visual uplift for the effort. |
| 14 | **Conceptual dissonance in the summary card.** The JS clock shows the visitor's current time — so at noon it says "while you were closed" next to 12:04:33. | Show a fixed overnight time (e.g. 03:14), not `new Date()`. |
| 15 | **Dead CSS + inline styles.** `.proof-card`, `.metric`, `.mv`, `.ml`, `.proof-note` are defined but unused; the dark 6th capability card and section backgrounds use inline `style="…"`. | Delete dead rules; move inline styles to modifier classes (`.cap--dark`, etc.). |
| 16 | **Fonts loaded from Google CDN, multiple weights, render-blocking.** Audience on metered mobile data (~₦637/GB). | Self-host subset woff2 (Fraunces + Inter, only the weights used); keep `font-display: swap`. Faster + private + cheaper for the visitor. |
| 17 | **No og:image, no Twitter card.** When shared on WhatsApp — the exact sales channel — the preview has no image. | Add a branded `og:image` + `twitter:card`. High-value for a WhatsApp-shared link. |
| 18 | **No JSON-LD, canonical, or robots/sitemap.** | Add Organization/Product JSON-LD, a canonical tag, basic SEO meta. |

## Proposed implementation phases

- **Phase 1 (the money moves):** WhatsApp CTA + "try our concierge" block · "why not the free bot?" differentiator · surface grounding/human-approval + the guarantee · tighten ICP copy toward Lagos fine-dining · add founder + data-safety trust row.
- **Phase 2 (structure):** FAQ/objections · og:image + SEO meta · fix the a11y items (glyphs, contrast, `<main>`, skip link).
- **Phase 3 (polish):** Real SVG icon set · self-hosted fonts · kill dead CSS/inline styles · fix the overnight-clock.  (Clock fix pulled into Phase 1 as it's a one-liner.)