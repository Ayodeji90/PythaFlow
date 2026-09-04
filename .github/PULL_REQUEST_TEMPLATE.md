## What & why

<!-- One or two sentences: the outcome this PR delivers and the problem it solves.
     The title is the what; this is the why. -->

## Plan & backlog links

<!-- Work starts with a plan. A reviewer should be able to open the plan and see
     the design decisions RESOLVED before the code was written. -->

- Plan: `.kilo/plans/<topic>.md` (product code) or a doc under `Discovery/` (docs/site)
- Backlog item: `concierge/docs/REVIEW_BACKLOG.md` P1/P2/P3, or `Closes #<issue>`

## Design decisions

<!-- Copy the RESOLVED decisions from the plan that a reviewer must check the
     code against (e.g. "Bot API only — one identity end-to-end"). If none were
     controversial, say so in one line. -->

-

## Validation

- [ ] `ruff check` clean
- [ ] `ruff format --check` clean
- [ ] `pyright` clean
- [ ] `pytest` green (full suite — needs the docker db/redis up)
- [ ] `uv run python -m evals.runner --baseline` → ✓ PASS (or note the delta + why)

Manual checks performed (webhook / console / pilot):

-

<!-- Rules from CONTRIBUTING.md that still apply:
     one branch → one PR → one merge → delete; main is protected; every change
     is a small, reviewable unit. -->
