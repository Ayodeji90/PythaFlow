# Contributing to Balance

How we use git on this repo. The whole point: **`main` always works, and every
change is tracked as a small, reviewable unit.**

This is a monorepo with three concerns that live side by side:

| Folder | What it is |
|---|---|
| `concierge/` | The product — FastAPI backend, the AI concierge |
| `balance-site/` | The marketing website (static) |
| `Discovery/` | Specs, research, GTM, business docs |

They are separated by **folder**, not by permanent branches. Do not create a
long-lived branch for the site (or anything else) — see "The one rule" below.

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

## `main` is protected (once we're more than one person)

When the team grows past one person, turn on **branch protection** on `main` in
GitHub settings:

- No direct pushes to `main` — changes land only via merged PRs.
- (Optional) require the test suite to pass before merge.

The only exception: repo-governance files (this file, `README`, `LICENSE`,
`.gitignore`) may be committed to `main` directly — they're the rules everything
else follows.

---

## Keeping a branch fresh

If `main` moves ahead while you're working, pull it into your branch so the
final merge is boring:

```bash
git checkout main && git pull
git checkout feat/your-branch
git merge main          # resolve any conflicts here, not at PR time
```
