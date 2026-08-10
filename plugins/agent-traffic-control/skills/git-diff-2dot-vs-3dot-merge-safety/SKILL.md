---
name: git-diff-2dot-vs-3dot-merge-safety
description: |
  Avoid false-positive "this PR will delete files on main" alarms when reviewing a
  PR that was branched off an older commit. Use when: (1) `git diff origin/main..pr-branch`
  shows files being deleted that you DON'T want to lose, but (2) GitHub reports
  `mergeable: MERGEABLE / mergeStateStatus: CLEAN`, (3) you're about to demand a
  rebase or block the merge to "preserve" those files. The 2-dot diff is misleading
  — it shows everything different between two trees, including files added on `main`
  AFTER the branch point that the branch never saw. The 3-dot diff
  (`origin/main...pr-branch --diff-filter=D`) respects the merge-base and shows only
  what the branch actually deleted. Also covers the empty-cherry-pick signal that a
  "divergent" local commit's content is already on main under a different hash.
author: Claude Code
version: 1.1.0
date: 2026-05-01
---

# Git Diff 2-dot vs 3-dot — Merge Safety Assessment

## Problem

You're reviewing a PR before merging and run `git diff origin/main..pr-branch --stat`.
The output shows files being **deleted** — files that just landed on `main` via another
PR yesterday and that you absolutely don't want to lose. Looks like merging this PR
will wipe them out.

It won't. The 2-dot diff is showing the **symmetric difference between two trees**, not
"what the branch will change about main." Files added to main AFTER the PR's branch
point appear in the diff as "deletions" simply because the branch's tree doesn't have
them yet. GitHub's 3-way merge will preserve them.

Same trap appears when assessing a "divergent" local commit: `git log main..origin/main`
may show commits "missing" that are actually present under a different SHA (squash
merges produce new hashes; rebases rewrite history).

## Context / Trigger Conditions

Any of these:

1. **PR review:** `git diff origin/main..pr-branch --stat` shows file deletions, BUT
   `gh pr view N --json mergeable,mergeStateStatus` returns
   `{"mergeable":"MERGEABLE","mergeStateStatus":"CLEAN"}`.
2. **Divergent local branch:** `git status` says "Your branch and 'origin/main' have
   diverged, and have N and M different commits each, respectively." But you don't
   recall making real local commits.
3. **Suspicious orphan commit:** `git log origin/main..local-branch` shows a commit
   you'd expect to be on origin already (e.g., an `[auto-docs]` commit from a sibling
   session, or a cherry-pick from a since-merged PR).
4. **About to take a destructive action** — demanding a rebase, force-push, or
   `git reset --hard origin/main` "to clean up" — based purely on a 2-dot diff.

## Solution

### For "will this PR delete files?" questions

```sh
# WRONG — shows everything different between trees, including files
# added on main since the branch point
git diff origin/main..pr-branch --stat                 # misleading

# RIGHT — shows only what THIS BRANCH changed since the merge-base
git diff origin/main...pr-branch --stat                # symmetric, since merge-base
git diff origin/main...pr-branch --diff-filter=D --name-only   # ONLY deletions

# If the second command is empty, the PR deletes nothing.
```

The third dot in `A...B` tells git "diff from `merge-base(A,B)` to B" — which is
exactly what GitHub uses to decide what the merge will change. If
`--diff-filter=D` returns no names, the PR deletes nothing on main, full stop.
Trust GitHub's `mergeable: MERGEABLE` over your eyeballing of a 2-dot stat.

### For "is my divergent commit actually present on main?" questions

```sh
# Step 1: identify the divergent commit
git log origin/main..my-local-branch --oneline

# Step 2: cherry-pick onto a fresh branch off origin/main
git checkout -b probe/empty-pick origin/main
git cherry-pick <sha>
```

Three outcomes:

| `git status` after cherry-pick                                         | Meaning                                                                  |
|-----------------------------------------------------------------------|---------------------------------------------------------------------------|
| New commit on probe branch with the expected diff                      | Content is genuinely missing from main — open a PR to push it             |
| `nothing to commit, working tree clean` + "all conflicts fixed: run --continue" | **Empty pick** — content already on main under a different SHA. Abort and discard the local commit. |
| Real merge conflicts                                                   | Content partially overlaps; resolve manually                              |

The "all conflicts fixed: run --continue" + "nothing to commit" combination is the
canonical empty-cherry-pick fingerprint — it means git applied the patch and found
the result identical to HEAD. The local commit is redundant.

```sh
# Confirm with grep on the actual files the commit touched
git show <sha> --stat
grep -F "<distinctive line from the commit>" <each touched file>
# If every line is present on main → safe to discard the orphan
```

### Cleanup once verified

```sh
# Worktree's local main is divergent but content-equivalent → just snap to remote
git branch -f main origin/main      # safe ONLY when main is not checked out anywhere
                                     # (other worktree branches are fine — only `main`
                                     # being checked out blocks this)
git worktree list | grep '\[main\]' # verify nothing is on main first
```

## Verification

- Did GitHub say `mergeable: MERGEABLE / mergeStateStatus: CLEAN` before you panicked?
  → trust it. The merge is safe.
- After 3-dot `--diff-filter=D --name-only`: is the list empty? → no deletions, done.
- After cherry-pick probe: did git report "nothing to commit" with the conflicts-fixed
  banner? → orphan is content-equivalent, discard.

## Example

**Session that triggered this skill (S118c, 2026-04-30):**

```sh
$ git diff origin/main..pr192 --stat | head
... [deletes 4 client-draft files added by PR #196 yesterday] ...
# PANIC: PR will wipe out the S118f deliverables!

$ gh pr view 192 --json mergeable,mergeStateStatus
{"mergeable":"MERGEABLE","mergeStateStatus":"CLEAN"}
# Wait, GitHub says it's clean. Let me check 3-dot.

$ git diff origin/main...pr192 --diff-filter=D --name-only
# (empty)
# OK, false alarm. PR was branched off cad7f45a BEFORE PR #196 landed.
# The "deletions" are just files the branch never saw. Merge is safe.
```

Same session, divergent local main with `47d0ff9d [auto-docs]`:

```sh
$ git checkout -b probe origin/main
$ git cherry-pick 47d0ff9d
... (all conflicts fixed: run "git cherry-pick --continue")
... nothing to commit, working tree clean

# Empty pick → content already on main under a different SHA.
# Confirmed by grep:
$ grep -c "S109b anti-drift" docs/data_dictionary.md
1   # already on main
$ git cherry-pick --abort && git branch -D probe
$ git branch -f main origin/main   # safe to snap, content is preserved
```

## Notes

- **GitHub's mergeable check is authoritative for "will this conflict?"** — it does
  the actual 3-way merge test. If it says CLEAN, file-level conflicts are impossible.
  Your local 2-dot diff is just a different question.
- **2-dot is still useful** when you genuinely want "everything different between
  these two trees right now" — e.g., porting a hand-curated subset of changes. Just
  don't use it for merge-impact assessment.
- **Squash merges always produce new SHAs.** A commit message like "feat: foo (#42)"
  on main with a different hash than the local `feat/foo` branch's tip is the norm,
  not a problem. Verify by content, not by hash.
- **`git branch -f main origin/main` blocks if `main` is currently checked out** in
  any worktree (including the parent repo). Check `git worktree list | grep '\[main\]'`
  first; switch any worktree off `main` before forcing.
- **3-dot against a STALE ref over-reports — always `git fetch` first, and diff against
  `origin/main`, not `main`.** The merge base is computed from whichever ref you name,
  so `git diff main...HEAD` in a multi-worktree repo (where the primary checkout's
  `main` is parked many commits behind) picks an ancient base and pulls in every file
  that landed on `origin/main` since — one measured case reported **92 files / 8,381
  insertions** for a commit that touched **6**. Switching from 2-dot to 3-dot without
  fixing the ref trades one false alarm for another. See
  `worktree-stale-local-main-ref-inflates-pr-diff`.
- Related: `git-pull-after-squash-merge` (overwriting-files error after squash);
  `pr-conflict-from-mid-flight-merges` (DIRTY status from sibling PRs landing);
  `worktree-stale-local-main-ref-inflates-pr-diff` (the complementary trap: a correct
  3-dot operator against a stale LOCAL `main` ref);
  `pr-from-stale-branch-silently-reverts-newer-main-files` (the case where deletions
  under 3-dot are REAL — a stale tree under a current pointer).

## References

- [git-diff(1) — TWO COMMIT SUMMARIES](https://git-scm.com/docs/git-diff#_two_commit_summaries) — the official "A..B vs A...B" definition
- [Pro Git §7.1 Three-dot syntax](https://git-scm.com/book/en/v2/Git-Tools-Revision-Selection#_triple_dot)
