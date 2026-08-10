---
name: subagent-pre-existing-misattribution
description: |
  Catch subagent reviewers misattributing test failures across the
  pre-existing / PR-introduced boundary — in BOTH directions. Use when:
  (1) a multi-task subagent-driven plan reports "N pre-existing failures,
  unrelated" across consecutive tasks and the count never changes,
  (2) an architectural / final reviewer at the end catches assertions that
  should have been updated 5 tasks ago, (3) an implementer reports "verified
  pre-existing on clean tree by running git stash" but the breaking change is
  already committed on the branch, (4) you're building or executing a
  multi-task plan with subagent reviewers that compare suite-wide pass/fail
  counts to a "baseline", (5) **a single code-review subagent reviewing one
  PR flags failures as "Critical / PR-introduced" and reasons "the PR
  correctly updated X but forgot the test" — without ever diffing against
  origin/main** (the over-flagging mirror image: the reviewer infers
  causation from the *current file state* and assumes your PR made a change
  it never made). Root cause (both directions): the reviewer never compared
  to mainline. `git stash` only stashes UNCOMMITTED changes — it does NOT
  reset to mainline; and reading the current file state tells you nothing
  about whether *this PR* changed it. Fix: verify the pre-existing/introduced
  boundary with `git diff origin/main...HEAD -- <file>` (did THIS pr touch
  it?) + `git show origin/main:<file>` (what was the value before?) +
  running the flagged tests on a real `origin/main` checkout — not by
  `git stash`, and not by eyeballing the working tree.
author: Claude Code
version: 1.1.1
date: 2026-05-14
disable-model-invocation: true
---

# Subagent-Driven Development: Pre-Existing Failure Misattribution

## Problem

In subagent-driven development, each task's reviewer evaluates spec compliance + code quality for THAT task in isolation. When the implementer or reviewer runs the full suite and finds N failures, they look up whether those failures are "new from this task" or "pre-existing baseline." If they classify them wrong, the failures get carried forward as "known unrelated failures" through every subsequent task — and the final architectural reviewer is the only checkpoint that catches the misattribution.

The specific failure mode: an early task removes an item from a list (e.g., a sidebar nav entry, a collection of dashboard cards). Other test files have HARDCODED COUNT ASSERTIONS for that list (`assert count == 5`) that nobody notices because:

1. The implementer of the breaking task fixes the parametrize lists they SEE but misses count assertions in OTHER test files.
2. The implementer reports "8 failures, all pre-existing — verified on clean tree."
3. Subsequent task implementers/reviewers see "baseline = 8 failures" and treat anything matching that count as expected.
4. The architectural final reviewer compares against the actual mainline branch (not the branch tip pre-commit) and discovers N of those "pre-existing" failures are actually caused by the early task.

## Context / Trigger Conditions

- Multi-task plan executed via `superpowers:subagent-driven-development` or similar
- Reviewer report contains "N pre-existing failures, verified unrelated to this task"
- Reviewer cites `git stash` or "clean tree check" as verification mechanism
- Failure count is suspiciously stable across consecutive tasks (e.g., "8 pre-existing" through Tasks 7, 8, 9, 10 — even after the suite grew)
- A test file references a count of items in a list that the plan modifies (sidebar tabs, library cards, sub-nav entries, primary routes, etc.)
- Final architectural review surfaces failures that map directly to changes from earlier tasks

## Why `git stash` is Insufficient

`git stash` saves the working directory's **uncommitted** modifications and restores HEAD to a clean state. But on a feature branch where the breaking commit has already landed, the working directory IS HEAD — there's nothing to stash. The "clean tree" the stash produces is identical to the dirty tree, because the breaking change is part of HEAD itself.

```
$ git status                    # already clean — no uncommitted changes
$ git stash                     # "No local changes to save"
$ pytest tests/ -q              # same failures as before — they're committed
$ # but reviewer reports: "verified failures pre-existing on clean tree"
```

The reviewer isn't lying — `git stash` ran and the suite ran "on the clean tree" — but that "clean tree" is the post-breaking-change branch state, not mainline.

## Variant: the over-flagging mirror image (single-PR code-review agent)

The original pattern is **under-flagging**: a reviewer calls a PR-introduced
failure "pre-existing." The mirror image is **over-flagging**: a single
code-review subagent reviewing one PR calls a *pre-existing* failure
"Critical / PR-introduced." Same root cause — the reviewer never diffed
against `origin/main` — opposite error.

The mechanism: the reviewer reads the *current file state*, sees a mismatch
(e.g. `_ACTIONS_COLD_OPEN_HISTORICAL["a1"]["peer"] == "~5.3-7.4%"` but a test
asserts `== "4.84%"`), and **infers** "this PR updated the value and forgot
the test." It never checks whether the PR actually touched that value. If a
*prior* PR changed it and left the test stale, the failure predates this PR
entirely — but the reviewer's report says "Critical, PR-introduced, must fix
before merge."

Trigger signs for this variant:

- A single `code-review` / `feature-dev:code-reviewer` subagent on **one** PR
  (not a multi-task plan) returns a "Critical" finding phrased as *"the PR
  correctly updated X but didn't update the test"* — note the unverified
  assumption baked into "the PR updated X."
- The finding cites current file contents, never a `git diff` or `git show`.
- The flagged tests are in a file your PR's diff doesn't meaningfully touch.

Don't merge on the reviewer's say-so and don't reflexively "fix" the flagged
tests (that's scope creep onto a pre-existing bug). **Verify the boundary
first** (see Solution). If the failures are pre-existing: leave them, note it
in the PR test plan, and spawn a separate follow-up task for the real bug.
The reviewer's *other* findings still stand — only the attribution was wrong.

## Solution

### For implementers/reviewers

When reporting "N failures, all pre-existing":

1. **Cite the exact mainline ref you compared against**, not "clean tree":
   ```bash
   git fetch origin main                    # ensure mainline ref is current
   git stash 2>/dev/null                    # save WIP if any
   git checkout origin/main -- tests/       # restore tests dir to mainline state
   pytest tests/<failing-file> -q           # verify failures on actual mainline
   git checkout HEAD -- tests/              # restore branch state
   ```
2. **Or compare the specific test file** between branch and mainline:
   ```bash
   git diff origin/main...HEAD -- tests/<file>
   ```
   If the file has changed in your branch, "pre-existing" claims need extra scrutiny.
3. **Run the failing tests against `origin/main` directly**:
   ```bash
   git worktree add /tmp/main-check origin/main
   cd /tmp/main-check && pytest tests/<failing-file>
   git worktree remove /tmp/main-check
   ```

### For orchestrators

When a subagent reports "N pre-existing failures":

- Reject the report if the subagent didn't cite the mainline ref used for verification.
- Cross-check by maintaining a baseline FAILURE LIST (test names, not just count) at the start of execution. If a "pre-existing" failure isn't in the original baseline list, it was introduced by the plan.
- Run a final-task suite-wide comparison BEFORE opening the PR:
  ```bash
  git fetch origin main
  diff <(pytest tests/ --co -q 2>/dev/null) <(git checkout origin/main -- tests/ && pytest tests/ --co -q 2>/dev/null)
  ```

### For plan authors

If your plan removes items from a UI list (sidebar tabs, library cards, sub-navs, primary routes), add an explicit task step:

```
- [ ] Grep for hardcoded COUNT assertions on the affected list. Update both the
      parametrize/fixture lists AND any `assert count == N` integer assertions.
      Search: `rg "count == [0-9]" tests/ | grep -i <list_concept>`.
```

## Verification

A claim of "pre-existing failures" is verified when:

1. The reviewer cites `git diff origin/main...HEAD -- <test_file>` showing the file unchanged.
2. OR the reviewer ran the same test on `origin/main` directly (worktree, checkout, or `git show origin/main:<file>` extraction) and observed the same failure.
3. AND the failure name (not just count) appears in a baseline list captured BEFORE plan execution started.

## Example

In session 2026-05-06, a 12-task plan executed via subagent-driven-development for issue #272 (Drivers tab + per-value drilldown):

- Task 6 removed the Methods card from the Library hub + Methods sub-nav entry.
- Task 6's implementer/reviewer fixed the parametrize lists they saw but missed `tests/test_loading_overlay_wiring.py` lines 109 and 133 with `assert count == 5` for `.library-card` and `.library-subtab`.
- Task 7's full-suite run reported 8 failures, including 5 from `test_loading_overlay_wiring.py`.
- Task 10's implementer reported "8 pre-existing — verified by running them on `git stash`'d clean tree." `git stash` saved nothing (no uncommitted changes); the suite ran identically.
- Tasks 8, 9, 10 all carried "8 pre-existing failures" forward in their reports.
- The final architectural reviewer compared against `origin/main` and surfaced 5 of those 8 failures as direct consequences of Task 6.

Fix landed in commit `0361a582`: change `5` → `4` in two places + comment refresh.

Total cost of misattribution: ~4 task cycles where reviewers didn't catch the issue + final-review cycle to surface it. Could have been caught at Task 6 review with the right verification framing.

## Notes

- This is a SISTER pattern to `lint-allowlist-substring-stale-after-rewrite` (which covers stale STRING substring assertions); this skill covers stale NUMERIC count assertions specifically.
- The git-worktree variant of the verification is most robust but slow. The `git diff origin/main...HEAD -- <file>` quick-check is sufficient for most cases. **Three dots, not two** — 2-dot compares tip to tip, so a file that main changed after your branch point shows as changed by *you*, which is the exact misattribution this skill exists to stop. (This file's own description has prescribed the 3-dot form since 1.1.0; the body said 2-dot in three places until 1.1.1.)
- Subagent reviewer prompts in `superpowers:subagent-driven-development` should require the verification ref. Consider amending the reviewer template to explicitly forbid "verified on clean tree" and require "verified vs origin/main at SHA <X>."
- This pattern compounds across long plans: if Task K introduces N stale assertions and the misattribution survives until Task K+5's review, a third of the plan's review cycles operated on a wrong baseline.

## References

- Originated session: PR #303 final-review fix at commit `0361a582` (issue #272)
- Related skill: `lint-allowlist-substring-stale-after-rewrite` (string-version sibling)
- Related skill: `multi-agent-skill-silent-phase-compression` (different failure mode in multi-agent orchestration)
