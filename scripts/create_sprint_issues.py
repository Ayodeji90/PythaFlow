#!/usr/bin/env python3
"""Create one GitHub issue per day of the 30-day sprint, generated from
`Discovery/Concierge_30_Day_Sprint.md` (the single source of truth).

Requires the GitHub CLI (`gh`) to be installed and authenticated.

    python3 scripts/create_sprint_issues.py --dry-run        # preview, no writes
    python3 scripts/create_sprint_issues.py                  # create the issues
    python3 scripts/create_sprint_issues.py --done 1,2       # ...and close Days 1-2

Re-running is safe: issues whose title already exists are skipped.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "Discovery" / "Concierge_30_Day_Sprint.md"
DOC_REL = "Discovery/Concierge_30_Day_Sprint.md"
SPEC_REL = "Discovery/Concierge_Week1_Build_Spec.md"
MILESTONE = "Phase 0 — Text-first pilot"

WEEK_RE = re.compile(r"^# WEEK (\d+) — (.+)$")
DAY_RE = re.compile(r"^### Day (\d+) — (.+)$")
BOUNDARY = ("### ", "# ", "## ", "---")


def sh(args: list[str], check: bool = True) -> str:
    p = subprocess.run(args, capture_output=True, text=True)
    if check and p.returncode != 0:
        raise RuntimeError(f"{' '.join(args)}\n{p.stderr.strip()}")
    return p.stdout


def parse_days(text: str) -> list[dict]:
    days: list[dict] = []
    week: tuple[int, str] | None = None
    cur: dict | None = None

    for line in text.splitlines():
        if m := WEEK_RE.match(line):
            if cur:
                days.append(cur)
                cur = None
            week = (int(m.group(1)), m.group(2).strip())
            continue
        if m := DAY_RE.match(line):
            if cur:
                days.append(cur)
            title = m.group(2).strip().rstrip("★").strip()
            cur = {"day": int(m.group(1)), "title": title, "week": week, "lines": []}
            continue
        if cur is not None and any(line.startswith(b) for b in BOUNDARY):
            days.append(cur)
            cur = None
            continue
        if cur is not None:
            cur["lines"].append(line)

    if cur:
        days.append(cur)
    return days


def build_body(d: dict) -> str:
    wk_num, wk_title = d["week"] if d["week"] else (0, "")
    content = "\n".join(d["lines"]).strip()
    return (
        f"**Week {wk_num} — {wk_title}**\n\n"
        f"{content}\n\n"
        "---\n"
        f"_Generated from [`{DOC_REL}`](../blob/main/{DOC_REL})."
        f" Week-1 ticket detail: [`{SPEC_REL}`](../blob/main/{SPEC_REL})._\n"
        "_A day is done only when every box above is ticked._"
    )


def ensure_milestone() -> None:
    existing = json.loads(sh(["gh", "api", "repos/:owner/:repo/milestones?state=all"]))
    if any(m["title"] == MILESTONE for m in existing):
        print(f"milestone exists: {MILESTONE}")
        return
    sh(
        [
            "gh", "api", "repos/:owner/:repo/milestones",
            "-f", f"title={MILESTONE}",
            "-f", "description=Text-first concierge pilot: web chat + WhatsApp, "
                  "grounded answers, reservations with staff approval.",
        ]
    )
    print(f"created milestone: {MILESTONE}")


def ensure_labels(weeks: set[int]) -> None:
    labels = [("sprint", "0E8A16", "30-day Phase 0 sprint task")]
    for w in sorted(weeks):
        labels.append((f"week-{w}", "1D76DB", f"Sprint week {w}"))
    for name, color, desc in labels:
        p = subprocess.run(
            ["gh", "label", "create", name, "--color", color, "--description", desc],
            capture_output=True, text=True,
        )
        print(("created label: " if p.returncode == 0 else "label exists: ") + name)


def existing_titles() -> set[str]:
    out = sh(["gh", "issue", "list", "--state", "all", "--limit", "300", "--json", "title"])
    return {i["title"] for i in json.loads(out)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print what would be created")
    ap.add_argument("--done", default="", help="comma-separated day numbers to close, e.g. 1,2")
    args = ap.parse_args()

    if not DOC.exists():
        print(f"sprint doc not found: {DOC}", file=sys.stderr)
        return 1

    days = parse_days(DOC.read_text(encoding="utf-8"))
    print(f"parsed {len(days)} days from {DOC_REL}\n")

    if args.dry_run:
        for d in days:
            title = f"Day {d['day']:02d} — {d['title']}"
            boxes = sum(1 for ln in d["lines"] if ln.strip().startswith("- [ ]"))
            wk = d["week"][0] if d["week"] else "?"
            print(f"  {title}   [week-{wk}, {boxes} checklist items]")
        print("\n(dry run — nothing created)")
        return 0

    ensure_milestone()
    ensure_labels({d["week"][0] for d in days if d["week"]})
    have = existing_titles()
    close_days = {int(x) for x in args.done.split(",") if x.strip().isdigit()}

    for d in days:
        title = f"Day {d['day']:02d} — {d['title']}"
        if title in have:
            print(f"skip (exists): {title}")
            continue
        wk = d["week"][0] if d["week"] else 1
        url = sh(
            [
                "gh", "issue", "create",
                "--title", title,
                "--body", build_body(d),
                "--label", "sprint",
                "--label", f"week-{wk}",
                "--milestone", MILESTONE,
            ]
        ).strip()
        print(f"created: {title} -> {url}")

        if d["day"] in close_days:
            num = url.rstrip("/").split("/")[-1]
            sh(["gh", "issue", "close", num, "--comment", "Completed and verified ✅"])
            print(f"  closed Day {d['day']:02d} (already done)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
