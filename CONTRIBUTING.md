# Contributing to Balance

How we use git on this repo. The whole point: **`main` always works, and every
change is tracked as a small, reviewable unit.**

This is a monorepo with these concerns living side by side:

| Folder | What it is | Owned by |
|---|---|---|
| `concierge/` | The product — FastAPI backend, the AI concierge | `@balance-ai` / `@balance-backend` |
| `Graycliff/` | The 5-solution demo platform (forecasting, recommender, pricing, voice, marketing) | `@balance-ml` (only if productized; else demo, no owner) |
| `balance-site/` | The marketing website (static) | `@balance-front` |
| `Discovery/` | Specs, research, GTM, business docs | `@balance-founder` |
| `.kilo/plans/` | Design plans — one per work item, resolved before code | author of the work |

**This table is the living index of the repo.** Adding a new top-level
directory is a repo-governance change: it lands on `main` and updates this
table in the same commit. Full per-module ownership lives in `CODEOWNERS`.

They are separated by **folder**, not by permanent branches. Do not create a
long-lived branch for the site (or anything else) — see "The one rule" below.
`staging` exists only as a pre-release integration gate for pilots: work
merges to `main` short-lived, a release candidate collects on `staging`,
and `staging` is deleted after the pilot ships.

---

## The one rule

**Branches are short-lived and always aim back at `main`.**

Nothing lives on a branch forever except `main` itself. A branch that never
merges isn't tracking work — it's a fork that slowly rots until merging it is a
nightmare. Every branch has one job, gets merged, and is deleted.

---

## The workflow

```bash
# 1. Start from an up-to-date main
git checkout main
git pull

# 2. Branch for the thing you're about to do
git checkout -b feat/day10-request-queue

# 3. Work. Commit in small, sensible steps.
git add -p
git commit -m "..."

# 4. Push the branch and open a Pull Request
git push -u origin feat/day10-request-queue
#    → open a PR on GitHub, link the issue ("Closes #10")

# 5. After it's merged, delete the branch
git checkout main
git pull
git branch -d feat/day10-request-queue
```

One branch → one PR → one merge → delete. The **PR is the tracking unit**: its
title, description, and diff are the record of what changed and why.

---

## Work starts with a plan

Every non-trivial change begins as a **plan file** (`.kilo/plans/<topic>.md` for
product code, a doc under `Discovery/` for specs/site): goal, architecture
context, **design decisions with a `RESOLVED` outcome**, task list, failure
modes, validation.

- The plan's design decisions are settled *before* code is written. A reviewer
  does not start a review until the plan says `RESOLVED` — that is the gate
  that stops "implemented both halves of a contradiction" from shipping.
- The PR links its plan (see the PR template). The PR diff and the plan together
  are the record; close the plan when the PR merges.
- Multi-option calls that affect product behavior are the founder's to make;
  lock them in the plan and in `REVIEW_BACKLOG.md`'s decision table.

---

## Branch names

Prefix by intent, then a short kebab-case description:

| Prefix | For | Example |
|---|---|---|
| `feat/` | new product features / sprint days | `feat/day08-tool-calling` |
| `fix/`  | bug fixes | `fix/rag-distance-floor` |
| `site/` | the marketing website | `site/pricing-section` |
| `docs/` | Discovery / specs / GTM / business docs | `docs/business-decisions` |
| `chore/`| tooling, deps, config, cleanup | `chore/ruff-config` |

If a sprint day has a GitHub issue, tie the branch to it and close the issue
from the PR (`Closes #8`).

---

## Commit messages

- First line: imperative, under ~72 chars, says *what* changed.
- Blank line, then *why* / what's notable, if it isn't obvious.
- If a change is a partial slice of a larger task, say so (`(WIP)`), so nobody
  assumes it's finished.

---

## `main` is protected

**Branch protection on `main` is on** (GitHub settings):

- No direct pushes to `main` — changes land only via merged PRs.
- Required checks must pass before merge (see "The quality gate" below).
- (Recommended once reviewers exist) one approval required.

The only exception: repo-governance files (this file, `README`, `LICENSE`,
`.gitignore`, `CODEOWNERS`, the PR template) may be committed to `main`
directly — they're the rules everything else follows.

---

## The quality gate

CI runs all of these on every PR (`.github/workflows/ci.yml`):

1. `ruff check` — lint
2. `ruff format --check` — formatting (run `ruff format` before pushing)
3. `pyright` — type checking (`[tool.pyright]` in `concierge/pyproject.toml`)
4. `pytest` — the full suite (needs Postgres + Redis, CI provides them)
5. `python -m evals.runner --baseline` — conversation-quality replay gate

The eval baseline number lives in exactly **one file** —
`concierge/evals/BASELINE.md` (read by the runner, compared by CI). Any other
doc that cites the baseline links there and says when it was last verified;
never copy the number into a second place. To refresh it after intentional
changes: record live once (`uv run python -m evals.runner --live`), then replay
with `--baseline` to confirm the gate.

---

## Keeping a branch fresh

If `main` moves ahead while you're working, pull it into your branch so the
final merge is boring:

```bash
git checkout main && git pull
git checkout feat/your-branch
git merge main          # resolve any conflicts here, not at PR time
```
