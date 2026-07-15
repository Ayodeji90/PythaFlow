# PythaFlow — company website

The marketing site for PythaFlow. Static, self-contained, no build step — it
runs from any static host or the existing FastAPI backend.

## Run locally

```bash
cd pythaflow-site
python3 -m http.server 8080
# open http://localhost:8080
```

That's it — plain HTML/CSS/JS, no dependencies, no compile.

## Files

| File | What |
|---|---|
| `index.html` | The single-page site (all sections, copy, structure) |
| `styles.css` | The full brand system, layout, and motion |
| `script.js` | Sticky header, mobile menu, staggered scroll reveals, scrollspy nav, count-up numbers, live clock, and the hero conversation player |
| `assets/mark.svg` | The logo mark (continuous flow-loop + always-on node) |
| `assets/favicon.svg` | Browser-tab icon |

### Motion — purposeful, and always optional

Every animation reinforces the idea of a concierge that never sleeps, and every
one is disabled under `prefers-reduced-motion`:

- **Living logo** — a teal pulse continuously travels the flow-loop (inline SVG
  sprite `#pf-mark`, animated in CSS).
- **Hero conversation** — a **WhatsApp-styled** chat plays a real guest booking a
  table on a loop (guest asks → concierge offers a time → books → confirms), with
  a typing indicator, per-message timestamps, and teal read-ticks. It pauses when
  scrolled off-screen; under reduced-motion it renders the full transcript
  statically. The channel is evoked through layout only (avatar, badge, ticks,
  input bar) — **not WhatsApp's green**, so the three-colour system holds. To
  re-skin as Instagram DM later, swap the `.wa-*` header/badge markup and styles.
- **Micro-interactions** — the hero **proof bar** (outcome bullets under the
  hero), nav underline-draw + scrollspy active state, count-up numbers (the
  overnight summary), capability-card accent hairline, focus-visible rings, and a
  faint teal aura + ink dot-grid for depth (no second colour).

## Positioning

PythaFlow is branded as **the AI concierge for restaurants and hotels** — a
concierge that works *alongside* the hospitality team (answering guests, booking
reservations, supporting staff after hours), not an "AI platform" or an
"automation agency." Copy leads with **who it's for** (restaurants, hotels,
resorts) and **business outcomes** (recovered bookings, answered guests, 24/7
service), not the underlying technology.

Hospitality is the explicit focus for now; other verticals can come later. There
is **no customer/case-study claim** on the page — the "See it in action" section
is clearly labelled illustrative sample data, not a client result.

## Brand system — three colors, disciplined

Smoke White carries ~90% of the page; graphite ink does all text and the dark
anchor bands; Deep Teal is the single accent, used sparingly (a button, a
hairline, one number). No gradients, no second accent. The restraint is the
premium signal.

| Token | Hex | Role |
|---|---|---|
| Smoke White | `#F3F4F1` | Primary — background |
| Graphite Ink | `#17191C` | Text + dark sections |
| Deep Teal | `#1E6E68` | The one accent |

Type: **Fraunces** (display serif) + **Inter** (UI/body), loaded from Google Fonts.

## Things to update before going live

- **Contact email** — currently the placeholder `hello@pythaflow.com`
  (in `index.html`, the CTA and footer). Swap for the real inbox.
- **"See it in action" numbers** are illustrative sample data, clearly labelled
  as such. Once you have a real customer, this section can become a genuine
  case study (with permission) — until then, keep the "illustrative" label.
- **Domain / analytics** wiring when you point a real domain at it.

## Optional: serve it from the backend

To host it under the existing FastAPI app (like the Graycliff `/site` mockup),
mount this folder as static files — e.g. in the backend app:

```python
from fastapi.staticfiles import StaticFiles
app.mount("/", StaticFiles(directory="pythaflow-site", html=True), name="site")
```

(or a subpath like `/company`). For most cases, though, a static host such as
Netlify, Cloudflare Pages, or GitHub Pages is the simplest path.
