---
name: merge-queue-thrash-stop-inflow-and-open-prs-as-drafts
description: |
  When main moves faster than the slowest CI leg, every open branch goes stale
  before it can merge and the whole queue jams with nothing red. Use when: (1)
  several PRs sit at mergeStateStatus BEHIND with auto-merge armed and none of
  them lands; (2) branches are being updated, re-running CI and going stale again
  before that run finishes; (3) you are landing work continuously and wondering
  why the queue is not draining — you are the cause, not a victim; (4) you are
  deciding how a fleet of agents should open pull requests in the first place.
  The immediate fix is to STOP THE INFLOW and land one at a time, newest-CI
  first. The structural fix is to open every pull request as a DRAFT and mark it
  ready only when it is next to land: on the repo this was measured, a draft run
  cost about 46 seconds against about 16 minutes for a full one, and over 8 days
  draft-by-default would have saved 23-48% of every CI minute, because 36% of
  pull-request runs were merges of main carrying no new code at all. NOT for a
  PR that conflicts — BEHIND is not DIRTY, and nothing here resolves a conflict.
author: Claude Code
version: 1.0.0
date: 2026-08-17
disable-model-invocation: true
---

# Queue thrash: main moves faster than CI, so nothing can land

## Problem

Six pull requests, all green when they were pushed, all with auto-merge armed. None of
them merges.

Nothing is wrong with any of them. `mergeStateStatus` reads `BEHIND` on every one —
not `DIRTY`, so there are no conflicts and nothing needs resolving. Each is simply
behind a `main` that moved after its last run finished.

The loop:

```
branch is BEHIND  →  update it from main  →  CI re-runs (16 min)
                          ↑                        ↓
                  someone lands on main  ←  branch is BEHIND again
```

If the interval between merges into `main` is shorter than the slowest required CI
leg, **the queue cannot drain**. Every branch is stale before its own run finishes.
Auto-merge does not help: it is waiting for a state — up to date and green — that no
branch is ever in for long enough.

**The cause is almost always you.** In the observed run, the inflow was a single
session landing work continuously, all night. Each individual merge was correct and
wanted. Together they made every other branch unlandable. This is worth stating plainly
because the instinct when nothing merges is to go looking for a broken check, and there
isn't one.

## Context / Trigger Conditions

- Two or more PRs at `mergeStateStatus: BEHIND` with auto-merge armed, and no merges
  landing.
- A branch that just finished a green run is BEHIND again before you can act on it.
- CI minutes are climbing and the runs are mostly `Merge branch 'main' into …` commits
  that changed nothing in the branch's own code.
- You are designing how a fleet of agents opens PRs — this is much cheaper to fix here
  than later.

```bash
# The one-line diagnosis: how many are BEHIND, and is anything DIRTY?
gh pr list --json number,title,mergeStateStatus \
  --jq 'group_by(.mergeStateStatus)[] | {state: .[0].mergeStateStatus, n: length}'
```

`BEHIND` in bulk is this skill. `DIRTY` is
[`pr-conflict-from-mid-flight-merges`](../pr-conflict-from-mid-flight-merges/SKILL.md)
— a real conflict, a different job, and nothing here will resolve it.

## Solution

### 1. Immediate — stop the inflow, then land one at a time

The queue drains only if `main` holds still. So:

1. **Stop merging anything else.** Including the small, safe, obviously-fine one. Each
   merge re-stales every remaining branch.
2. **Pick one PR and land it.** Prefer the one whose CI finished most recently — it has
   the least distance to make up and the best chance of merging before the next change.
3. **Only then start the next one.** Serially. The instinct to update all six branches
   at once is what produces six runs that will all be stale, and it also multiplies the
   CI bill by six.
4. **Do not fire `gh pr update-branch` while a run is in progress on that branch** —
   it invalidates work already underway. The safe predicate is per-branch, and getting
   its scope wrong stalls the lane completely:
   [`orchestrator-rule-too-strict-stalls-agent-silently`](../orchestrator-rule-too-strict-stalls-agent-silently/SKILL.md).

### 2. Structural — open every pull request as a DRAFT

The deeper problem is that a PR pays full CI from the moment it opens, and then again
every time main moves under it, for as long as it stays open. Most of that spend buys
nothing: it is testing a branch nobody is about to land.

**So open the PR as a draft, and mark it ready only when it is next to land.**

```bash
gh pr create --draft --title "..." --body "..."   # every PR, by default
# ... work, review, sit in the queue as long as you like ...
gh pr ready <N>                                   # only when it is next to merge
gh pr merge <N> --squash --auto
```

For this to save anything, the expensive workflows must actually skip drafts. That is
one condition on the job, and it is the whole mechanism:

```yaml
jobs:
  expensive-suite:
    if: github.event.pull_request.draft == false
```

**Measured on the repo this was learned on:**

| | duration |
|---|---|
| a draft PR's run (cheap gates only) | **~46 seconds** |
| a full PR run (all suites) | **~16 minutes** |

And across **8 days** of history, opening every PR as a draft would have saved
**23–48%** of every CI minute spent. The reason the saving is that large is the second
measurement: **36% of pull-request runs were merges of `main` into a branch, carrying
no new code at all** — over a third of the bill was re-testing other people's already-
tested work.

It also happens to give you a hold that GitHub enforces: a draft cannot merge, whatever
an agent does to it. See
[`auto-merge-rearms-while-agent-live-kill-then-disarm-verify`](../auto-merge-rearms-while-agent-live-kill-then-disarm-verify/SKILL.md).

### 3. Two things to check before you blame the queue

- **Is a required check one that will never report?** A `paths`-filtered workflow that
  did not trigger stays pending forever and blocks merge with no failure. Different
  jam, same symptom — `gh pr checks <N>` names it.
- **Is `main` actually the base?** A stacked PR whose base branch is another PR goes
  BEHIND for reasons that have nothing to do with inflow, and merging its base can
  auto-close it:
  [`stacked-pr-base-branch-deletion-auto-closes-dependent`](../stacked-pr-base-branch-deletion-auto-closes-dependent/SKILL.md).

## Verification

The queue is draining when:

```bash
# BEHIND count is falling between checks, and something has actually merged
gh pr list --json number,mergeStateStatus \
  --jq '[.[] | select(.mergeStateStatus == "BEHIND")] | length'
gh pr list --state merged --limit 5 --json number,mergedAt
```

Draft-by-default is actually in force when:

- `gh pr list --json number,isDraft` shows open PRs as drafts by default, not as an
  exception.
- The expensive jobs carry the `draft == false` condition — check the workflow file,
  not the intention.
- A draft PR's latest run is short. If a draft's run still takes the full time, the
  condition is not on the job that costs the money and the saving is zero.

## Example (real, this run)

**Six pull requests sat BEHIND with auto-merge armed and nothing landed.** No conflicts,
nothing red, every branch green at its last run and stale by the time anyone looked.

The cause was the orchestrating session itself, landing work continuously through the
night. Each merge was individually correct and collectively made the queue unlandable —
main moved faster than the slowest required leg, so every branch was stale before its
own run finished. Auto-merge armed on all six was waiting for a condition none of them
could reach.

The recovery was to stop landing anything else and take them one at a time, newest CI
first.

The invention that prevents it structurally was **draft-by-default**: open every PR as
a draft, promote it to ready only when it is next to land. On this repo a draft run
cost **~46 seconds** against **~16 minutes** for a full one, and over **8 days**
draft-by-default would have saved **23–48%** of every CI minute — because **36% of
pull-request runs were merges of `main` carrying no new code at all**.

## Notes

- **BEHIND is not DIRTY, and the distinction decides which skill you need.** BEHIND
  means "your base moved"; DIRTY means "the same lines changed on both sides". Only the
  second needs a human to resolve anything.
- **`--auto` is still right**; it is just not a queue-control mechanism. It waits for a
  condition. If the condition is unreachable it waits forever, quietly.
- **Draft-by-default costs one habit and one line of YAML**, and the habit is the
  fragile half: a PR opened ready by an agent whose brief predates the convention pays
  full price and nothing warns you. Put `--draft` in the brief, not in your memory.
- **The 23–48% is a range because it depends on how many drafts get promoted and when.**
  Quote it as a range measured over 8 days on one repo, not as a rate that transfers.
  The transferable number is the second one: **36% of runs carried no new code**, and
  that fraction is a property of how fast your main moves relative to CI, which you can
  measure in an afternoon.
- **Serial landing is temporary, drafts are permanent.** If you find yourself draining
  the queue by hand more than once, the inflow discipline did not stick and the fix is
  structural.

## References

- [`pr-conflict-from-mid-flight-merges`](../pr-conflict-from-mid-flight-merges/SKILL.md)
  — what to do when the same churn produced a real conflict (DIRTY, not BEHIND)
- [`auto-merge-rearms-while-agent-live-kill-then-disarm-verify`](../auto-merge-rearms-while-agent-live-kill-then-disarm-verify/SKILL.md)
  — the other use of draft: a hold GitHub enforces
- [`orchestrator-rule-too-strict-stalls-agent-silently`](../orchestrator-rule-too-strict-stalls-agent-silently/SKILL.md)
  — the per-branch predicate for when `gh pr update-branch` is safe, and what happens
  when that rule is scoped repo-wide instead
- [`gh-pr-merge-unstable-state-needs-auto-and-watch-branch-deletes`](../gh-pr-merge-unstable-state-needs-auto-and-watch-branch-deletes/SKILL.md)
  — UNSTABLE, BLOCKED and the rest of the `mergeStateStatus` table
- [`stacked-pr-base-branch-deletion-auto-closes-dependent`](../stacked-pr-base-branch-deletion-auto-closes-dependent/SKILL.md)
  — when BEHIND is about a stacked base rather than inflow
- [GitHub `mergeStateStatus` enum](https://docs.github.com/en/graphql/reference/enums#mergestatestatus)
