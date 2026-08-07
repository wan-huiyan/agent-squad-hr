---
name: large-redesign-parallel-branch-collision-audit
listing_tier: rich
description: |
  Before a large redesign, restructure or migration that will rewrite shared files — templates,
  the base layout, central views, shared CSS — audit every unmerged branch for commits on those
  same files. Use when the repo keeps long lived parallel branches (client variant, release,
  staging, whitelabel) and the plan replaces files wholesale rather than restyling in place.
  Symptom: the redesign merges cleanly, then cherry picking that branch's accessibility or hotfix
  commits collides with the new markup. Run it before the plan is locked. Not for two pull
  requests racing on one scope.
author: Claude Code
version: 1.0.0
date: 2026-05-28
---
# Large-Redesign Parallel-Branch Collision Audit

## Problem

You're about to start a large multi-PR redesign that branches from `main`. The branch is clean, tests are green, the plan is locked. You execute 14 PRs overnight, all merge cleanly to main.

The next day someone asks: "What about the changes on `release-uk` / `feature/whitelabel-X` / `staging-customer-Y`?" — and you discover that long-running branch has 10 unmerged commits, including a11y/safety hotfixes on a file (`progress.html`, `report.html`, `_base.html`) that your redesign has just **completely rewritten** with the bold-editorial markup.

Now those 10 commits can't be cherry-picked cleanly. The a11y improvements you'd want to keep (innerHTML→DOM migration, button-onclick→href fixes, focus-trap fixes) collide directly with the redesigned markup. Hand-merge required, possibly losing safety improvements if not careful.

The root cause: **the redesigner audited main, not main + parallel branches.**

## Context / Trigger Conditions

Use this audit BEFORE starting work when **all** of these apply:

1. The user requests a multi-PR redesign / migration / restructure (anything that will rewrite ≥3 templates, the base layout, central views, or shared CSS)
2. The repo has a multi-branch flow — long-running parallel branches that aren't trivially behind main:
   - Client-variant branches (`release-uk`, `client-acme`)
   - Staging branches (`feature/whitelabel-X`)
   - Pending feature branches with unmerged work
3. The redesign will REPLACE files (not just restyle in-place)

If only restyling in-place (CSS class renames, no structural rewrite), the audit is less critical — `git merge` can usually combine the changes.

## Solution

### Pre-flight audit (run BEFORE the implementation plan is locked)

```bash
# 1. List all non-stale branches with commits ahead of main
for branch in $(git branch -r --no-merged origin/main 2>/dev/null | grep -v HEAD); do
  count=$(git log --oneline origin/main..$branch 2>/dev/null | wc -l | tr -d ' ')
  if [ "$count" -gt 0 ]; then
    last_activity=$(git log -1 --format="%ar" $branch)
    echo "$count commits ahead — $branch (last: $last_activity)"
  fi
done

# 2. For each non-stale branch (last activity < 30 days), check file collisions
#    with the files your redesign will touch
PLANNED_FILES="webapp/templates/progress.html webapp/templates/report.html webapp/templates/_base.html"
for branch in $(git branch -r --no-merged origin/main | grep -v HEAD); do
  hits=$(git log --oneline origin/main..$branch -- $PLANNED_FILES 2>/dev/null | wc -l | tr -d ' ')
  if [ "$hits" -gt 0 ]; then
    echo "COLLISION RISK: $branch has $hits commits touching planned files:"
    git log --oneline origin/main..$branch -- $PLANNED_FILES
  fi
done
```

### Decisions to surface to the user BEFORE planning

For each collision-risk branch, ask:

1. **Promote first?** — Cherry-pick / merge the parallel branch's collision-risk commits into main BEFORE starting the redesign. The redesign then naturally absorbs them.
2. **Stake out scope?** — Carve the redesign to NOT touch the colliding files. (e.g. defer `progress.html` redesign until parallel branch lands.)
3. **Accept the cost?** — Proceed knowing that the parallel branch will need a careful hand-merge after the redesign. Document the planned conflict resolution upfront.

The user owns this decision. Don't decide unilaterally — surface it.

### Document the choice in the implementation plan

Add a section to the implementation plan: "Parallel-branch awareness." List each non-stale branch, file collisions if any, and the chosen disposition.

## Verification

After the redesign lands on main, run:

```bash
# Are there branches whose unmerged commits touch files we rewrote?
git log --oneline origin/main..origin/<parallel-branch> -- <files-we-rewrote>
```

If empty: clean — the parallel branch can be rebased onto main without manual file-level conflicts on the redesigned files.

If non-empty: the conflict resolution work was correctly anticipated and (per upfront planning) is queued for a follow-up PR.

## Example

**Scenario (S75 bold-editorial redesign, real)**:

Worktree on `worktree-redesigned-UI` branching from main `1ae1c4e`. Plan to redesign 13 templates including `progress.html`, `report.html`, `_base.html`, `home.html`, etc.

What was missed: `release-uk` branch had 10 commits ahead of main (last activity 1 week before S75 started), including:
- `f10b87c` per-test re-run buttons modifying validate.html / progress.html JS
- `bc913c0` progress.html a11y + innerHTML migration finish
- `125f178` progress.html innerHTML sinks → DOM construction
- `2410c37` decommission orphaned /permutation route

What happened: S75 PR #166 rewrote progress.html wholesale with bold-editorial markup. The a11y / innerHTML / DOM-construction improvements from #133 and #142 (still on release-uk) now conflict head-on. They can't be cherry-picked — they must be hand-merged into the new markup, preserving the safety improvements.

What the audit would have shown:

```
COLLISION RISK: origin/release-uk has 4 commits touching planned files:
f10b87c feat(report): per-test re-run buttons + /api/validation/rerun (#143)
bc913c0 fix(progress): a11y + finish innerHTML migration (#139 items 3-7) (#142)
125f178 fix(progress): migrate innerHTML sinks to DOM construction (#133) (#138)
2410c37 chore(routes): decommission orphaned /permutation route + dead helpers (#120) (#137)
```

The right move was to surface this in the kickoff `AskUserQuestion` and ask whether to:
(a) cherry-pick the 4 commits to main BEFORE starting the redesign
(b) defer progress.html / validate.html from the redesign scope
(c) accept the cost and plan a manual-merge follow-up PR

## Notes

- "Non-stale" is judgment — a branch with last activity 6 months ago and no open PR can usually be ignored. Branches with active commits in the last 30 days, or with an open PR, are the collision-risk set.
- The `--no-merged` filter excludes branches whose tips are already on main. Branches with squash-merged equivalents (different SHA, same content) will still show ahead — that's fine, the file-touch check is the actual filter.
- For monorepos with multiple deployable apps, run the file-touch audit per-app (different `PLANNED_FILES` set).
- This audit complements `pre-merge-client-variant-regression-audit` (which fires when bringing a variant branch INTO main, looking for regressions to the original client). Both should run on long-running multi-branch projects.
- If the user wants to proceed without the audit ("just go"), document the skipped audit in the plan's risk section so the post-merge surprise is at least anticipated.

## References

- Sister skill: `pre-merge-client-variant-regression-audit` (audit BEFORE merging a variant branch into main)
- Related: `parallel-pr-scope-overlap-tiebreaker-delta-check` (two simultaneous PRs vs one redesign on main + WIP elsewhere)
- Related: `flask-route-decommission-blast-radius` (similar audit, but for route consumers within a single branch)
