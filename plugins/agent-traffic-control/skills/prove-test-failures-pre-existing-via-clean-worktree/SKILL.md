---
name: prove-test-failures-pre-existing-via-clean-worktree
description: |
  After making a change you run the test suite and it shows failures — especially in files/areas
  your diff never touched, or a count that "feels unrelated." Before you either panic-debug them OR
  wave them off as "probably pre-existing," PROVE it: run the exact failing tests against a clean
  checkout of origin/main (a throwaway `git worktree`). Identical failures = pre-existing (ship + note
  them); different = your change caused it. Use when: (1) a broad/full test run after your edit reports
  failures and you must decide "mine or pre-existing?"; (2) you're tempted to attribute failures to your
  change without evidence, or to dismiss them without evidence; (3) you can't `git checkout main`
  because you're in a worktree where main is checked out elsewhere, or you have uncommitted work.
author: Claude Code
version: 1.0.0
date: 2026-06-06
disable-model-invocation: true
---

# Prove test failures are pre-existing against a clean main worktree — don't guess "mine or theirs"

## Problem
You finish a change, run the test suite (or a broad blast-radius set), and it reports failures. Two
failure modes follow, both costly:
1. **False attribution → wasted debugging.** You assume your change broke them and burn time
   investigating failures your diff never caused.
2. **Unproven dismissal → shipped regression.** You wave them off as "probably pre-existing" with no
   evidence, and a real regression you DID introduce slips through under that cover.

The honest move is neither — it's a 30-second proof.

## Context / Trigger conditions
- A post-change test run shows failures, particularly in modules/areas your diff did NOT touch.
- You're about to write "these are pre-existing, unrelated to my change" in a PR/handoff — but haven't
  proven it.
- You're in a git **worktree** where `main` is checked out in another worktree (so `git checkout main`
  fails with `fatal: 'main' is already used by worktree at ...`), and/or you have uncommitted changes,
  so the usual "switch to main and run" is awkward.

## Solution
1. **Spin a throwaway clean checkout of the baseline** (merge base / `origin/main`):
   ```sh
   git fetch origin --quiet
   git worktree add /tmp/clean origin/main      # isolated; zero-touch to your working tree
   ```
   A worktree beats `git stash`: it doesn't disturb your edits, survives untracked files + new test
   assertions, and works when your own cwd is a worktree that can't switch to main.
2. **Run the EXACT failing tests there** (the specific node ids, not the whole suite):
   ```sh
   ( cd /tmp/clean/<test-root> && <runner> <exact::failing::test::ids> )
   ```
3. **Compare:**
   - **Identical failures** → pre-existing. Ship your change; note "N failures pre-existing on
     origin/main, not introduced here" in the PR/handoff (with the proof).
   - **Different / fewer failures** → your change caused the delta. Now debug — you know exactly which.
4. **Clean up:** `git worktree remove /tmp/clean --force`.

## Verification
- The failing test ids (and the pass/fail tally) on clean `origin/main` match your post-change run for
  the flagged set, AND the tests covering the area you actually changed pass.
- Your PR/handoff states the pre-existing failures explicitly so a reviewer doesn't re-flag them.

## Example (origin, S244, 2026-06-06)
A small client-facing UI change (added a nav pill to 3 templates + a CSS class) was followed by a broad
suite run showing **16 failed, 367 passed** — all 16 in `test_phase5_sidebar.py` (sidebar IA tooltips)
+ `test_actions_phase3.py::test_methodology_card_removed`, none of which the diff touched. Rather than
debug them or assume they were fine: `git worktree add /tmp/clean origin/main`, ran those exact files
there → **identical 16 failed, 30 passed** → proven pre-existing. Shipped with a note; the PR's own
reviewer later independently confirmed the failing files were byte-identical on main. Zero time wasted,
zero regression risk.

## Notes
- Pair with the project reality that **CI may `--ignore` a test dir** (so the "real gate" is the local
  targeted blast-radius suite), and that **full local suites can HANG on real-DB/network tests** — run
  the suite with `--ignore=<documented-staller>` or just the targeted node ids; don't let a stalling
  unrelated test block the proof.
- Reviewer-side analog: `agent-review-panel`'s "Codebase State Check" (a review panel must not flag code
  as "missing" when it exists on main but not the reviewed branch). This skill is the author-side twin:
  don't attribute a *failure* to your change without checking the baseline.
- **The baseline worktree is not automatically clean.** A worktree isolates the SOURCE TREE only;
  a shared venv, an installed app keyed by bundle id, or a build cache keyed by project path is shared
  by every worktree on the machine, so the baseline run can silently exercise ANOTHER worktree's
  artefact and hand you a fictional failure set. Check provenance before comparing sets — the source
  paths a test binary compiles in are the cheapest tell. See
  `worktree-does-not-isolate-shared-installed-artefacts`.
- See also: `using-git-worktrees` (worktree mechanics), `concurrent-session-checkout-clobbers-shared-worktree`.
