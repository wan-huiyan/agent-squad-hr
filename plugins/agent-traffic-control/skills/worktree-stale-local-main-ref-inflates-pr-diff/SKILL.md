---
name: worktree-stale-local-main-ref-inflates-pr-diff
description: |
  Stop a false "my PR is reverting/touching dozens of upstream files" alarm when
  `git diff main...<branch>` reports far more files than your commit changed, in a
  multi-worktree repo. Use when: (1) you're in a worktree at
  `<repo>/.claude/worktrees/<X>/` (or any `git worktree`), (2) `git diff main...HEAD`
  (3-dot) or `--stat` shows tens/hundreds of files + thousands of lines but your
  actual commit (`git show --stat HEAD`) touched only a handful, (3) you're about to
  panic about the `stale-base-pr-silently-reverts-upstream-content` trap or block your
  own merge. Root cause: the LOCAL `main` ref is stale — it's parked many commits
  behind `origin/main` (often checked out in the PRIMARY worktree, which nobody pulled),
  so the merge-base of (local main, your branch) is ancient and the 3-dot diff includes
  every file that landed on origin/main since. The REAL PR diff is against `origin/main`.
  Verify with `git diff origin/main...HEAD --stat` (after `git fetch`) and
  `gh pr view <N> --json files`. Sibling of git-diff-2dot-vs-3dot-merge-safety
  (operator semantics) and worktree-outer-ls-mistaken-for-main-state (stale state via ls).
  Also fires when a CODE-REVIEW SUBAGENT claims your PR "carries unrelated code / a
  subsystem you didn't author" — same stale-local-main root cause; the authoritative
  check is `gh pr diff <N> --name-only` (the reviewer likely read the full-file context
  and mistook already-merged code for this PR's hunks).
author: Claude Code
version: 1.2.0
date: 2026-06-23
disable-model-invocation: true
---

# Worktree: a stale local `main` ref inflates `git diff main...branch`

## Problem

In a multi-worktree repo, `git diff main...<your-branch>` (or `--stat`) reports
**far more files and lines than your commit actually changed** — e.g. 92 files /
8,000+ insertions when your one commit touched 6 files. The instinct is to panic
that your PR is silently reverting or re-touching a pile of upstream work (the
`stale-base-pr-silently-reverts-upstream-content` trap) and to block your own
merge or demand a rebase. Almost always, nothing is wrong with the PR — the
**local `main` ref is stale**.

## Context / Trigger Conditions

All of:
- You're working inside a git worktree (`git rev-parse --is-inside-work-tree`;
  path contains `.claude/worktrees/<name>/` or `git worktree list` shows 2+ paths).
- `git diff main...HEAD --stat` (3-dot) shows tens/hundreds of files, but
  `git show --stat HEAD` (your actual commit) shows only a few.
- You branched off what you *thought* was current `main`, and `gh pr view <N>`
  reports the PR as `mergeable: MERGEABLE / mergeStateStatus: CLEAN`.

Why it happens: `main...branch` (3-dot) diffs from the **merge-base** of the two
refs. The merge-base uses your **LOCAL** `main` ref. In a multi-worktree setup the
local `main` ref is whatever the **primary worktree** last checked out / pulled —
frequently many commits behind `origin/main` because sibling sessions merge via
GitHub (squash) and nobody runs `git pull` on the parked primary checkout. So the
merge-base is ancient, and the 3-dot diff includes every file that landed on
`origin/main` since that old point — none of which your branch is actually
reverting. (This is the REF being stale, distinct from
`git-diff-2dot-vs-3dot-merge-safety`, which is about 2-dot-vs-3-dot operator
semantics against a *correct* `origin/main`.)

## Solution

Diff against the **remote** ref, not the local `main` ref:

```bash
git fetch origin main -q

# The TRUE PR diff (what GitHub will merge):
git diff origin/main...HEAD --stat

# Confirm divergence is small:
git rev-list --count HEAD..origin/main   # commits origin/main has, your branch doesn't
git rev-list --count origin/main..HEAD   # YOUR commits

# Is your branch's base actually on origin/main's history? (necessary, NOT sufficient
# — see the Verification note below; this does not rule out a revert on its own)
git merge-base --is-ancestor <your-branch-base-sha> origin/main && echo "clean base"

# The check that DOES rule out a revert — deletions, from the merge-base:
git diff --diff-filter=D --name-only origin/main...HEAD   # empty ⇒ deletes nothing

# Ground truth from GitHub — the actual file list the PR will change:
gh pr view <N> --json files -q '.files[].path'
gh pr view <N> --json mergeable,mergeStateStatus
```

If `git show --stat HEAD` matches `gh pr view <N> --json files` (your handful of
files) and the PR is `MERGEABLE / CLEAN`, the 92-file `main...branch` number was a
pure local-ref artifact — **proceed**. Do not rebase, do not block.

**Don't bother fixing the local `main` ref** from inside the worktree — you usually
can't (`git checkout main` fails: "main is already used by worktree at <primary>").
Just diff against `origin/main`; that's the ref that matters for the PR anyway.

## Verification

- `git show --stat HEAD` file count == `gh pr view <N> --json files` count.
- `git diff origin/main...HEAD --stat` shows only your files (small).
- `gh pr view <N>` → `mergeStateStatus: CLEAN`.
- `git diff --diff-filter=D --name-only origin/main...HEAD` is empty (or lists only
  files you meant to delete). **This is the check that proves no revert.**
- `git merge-base --is-ancestor <base-sha> origin/main` returns 0 — your base is on
  origin/main's history. Useful, but **it does not prove the merge won't revert
  upstream**, and treating it as proof is the mistake. A branch whose POINTER was
  moved onto current main while its TREE stayed old satisfies this condition exactly
  — 0 commits behind, ancestor check clean — and still records deleting every file
  that landed in between (`pr-from-stale-branch-silently-reverts-newer-main-files`,
  "the harder variant"). Only the `--diff-filter=D` line above closes that gap.

## Example

Worktree `chatbot`, one feature commit touching 6 files. `git diff main...HEAD --stat`
→ **92 files, 8,381 insertions** (TM v2/v3 + v7 analysis from other sessions). Alarm:
"is my PR reverting all of that?" Checks:
- `git show --stat HEAD` → exactly 6 files. ✓
- `git fetch origin main` then `git rev-list --count HEAD..origin/main` → **1** (just
  the sibling docs commit that added my own prompt file), `origin/main..HEAD` → 1.
- `git merge-base --is-ancestor 9fd95c95 origin/main` → 0 (clean ancestor).
- `gh pr view 1019 --json files` → the same 6 files; `mergeStateStatus: CLEAN`.

Conclusion: the 92-file number was the **stale local `main` ref** (parked far behind
origin/main in the primary worktree). PR was clean. Merged without rebase.

## Notes

- The cheap falsification is always `git show --stat HEAD` vs `gh pr view <N> --json
  files`. If those two agree and are small, the 3-dot `main...branch` number is noise.
- `git fetch` first — without it, even `origin/main` is whatever you last fetched.
- This is the *inverse* worry of a real stale-base revert: here the diff OVER-reports
  (local base too OLD); the real revert trap (`stale-base-pr-silently-reverts-upstream-content`)
  is when your branch's content actually overlaps and overwrites a merged upstream
  edit. Distinguish by checking `gh pr view --json files` (does it list the upstream
  files?) + reading the actual hunks, not the 3-dot file count.

## Variant — a code-review subagent flags "unrelated code riding along"

Same root cause, different messenger. A dispatched **code-reviewer** ran `gh pr diff <N>`
on a 1-commit PR (resolver fix touching 2 files) and reported that the PR *also* carried
"a conversation-export trace subsystem you didn't review" — because it read the **full
file** `chatbox_tools.py` (whose trace code was already on `origin/main` from prior merged
PRs) and conflated that ambient context with the PR's hunks. The author's own
`git diff main...branch` (stale local main) seemed to corroborate it.

Don't act on the reviewer's scope claim — falsify it first:
```bash
git fetch origin main -q
git log origin/main..<branch> --oneline      # how many commits the PR really has
gh pr diff <N> --name-only                    # AUTHORITATIVE file list GitHub will merge
gh pr diff <N> | grep -E '^\+def |^\+class '  # the actual ADDED hunks, not file context
```
If `--name-only` lists only your files and `git log origin/main..<branch>` is your single
commit, the "riding along" subsystem is pre-existing code the reviewer read for context —
proceed. The reviewer's *substantive* findings on your real hunks still stand; only its
**scope** claim is the artifact.

## See also

- `git-diff-2dot-vs-3dot-merge-safety` — 2-dot vs 3-dot operator semantics (assumes a
  correct `origin/main`); this skill is about the local `main` *ref* being stale.
  **The two are a pair and neither is safe alone:** switching to 3-dot fixes the
  operator and does nothing about the ref, so `git diff main...HEAD` against a stale
  local `main` still over-reports. Fetch, then name `origin/main`.
- `pr-from-stale-branch-silently-reverts-newer-main-files` — the case where the
  deletions are REAL rather than an artifact (a stale TREE under a current pointer).
  That is the one the ancestor check above cannot see.
- `worktree-outer-ls-mistaken-for-main-state` — same stale-local-state family, via `ls`.
- `stale-base-pr-silently-reverts-upstream-content` — the genuine revert trap (the
  thing this false alarm makes you fear); rule it out via the file list + hunks.
- `gh-pr-merge-worktree-checkout-trap` / session-handoff note — why `git checkout main`
  / `--delete-branch` fail from a worktree.
