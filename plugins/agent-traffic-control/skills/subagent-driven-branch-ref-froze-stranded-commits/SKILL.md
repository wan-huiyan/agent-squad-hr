---
name: subagent-driven-branch-ref-froze-stranded-commits
description: |
  Diagnose and recover from "PR merged, but half my work is missing from main"
  cases in `superpowers:subagent-driven-development` (or similar
  one-fresh-subagent-per-task) sessions, where committed work survives in the worktree's
  `HEAD` chain but never makes it into the pushed branch ref. Use when ANY of
  these appears:
  (1) `gh pr view <N>` body claims "M files changed, N insertions" but
  `gh pr diff <N> --name-only | wc -l` returns a smaller number than you
  expect (canary: PR-body file count > actual squash-commit file count),
  (2) the merged squash commit on main is MISSING entire files you remember
  creating (Dockerfile, route handler, deploy artefact, etc.) — and you wrote
  AND committed them per the subagent reports,
  (3) `git rev-parse HEAD` ≠ `git rev-parse <feature-branch>` in the
  worktree (HEAD is ahead),
  (4) `git reflog show <feature-branch>` ends earlier than `git log --oneline`
  on the same worktree (reflog gap = stranded zone),
  (5) tests that passed locally during the session now fail on main because
  files referenced by the committed code never landed,
  (6) the receiving session (or human running CI) discovers `ModuleNotFoundError`,
  `sql_path missing`, or similar "file referenced by code does not exist"
  symptom on freshly-pulled main.
  Root cause: one of the implementer subagents committed in a detached-HEAD
  state (e.g., after a `git checkout <sha>`, post-stash, post-cherry-pick
  abort, or an internal worktree reset by a tool). Subsequent subagents
  inherit the detached HEAD; each `git commit` advances HEAD but never
  updates the named branch. `git log` (without an explicit ref) walks from
  HEAD, so every per-task diagnostic looked correct. `git push <branch>`
  ships the branch ref — i.e. the truncated tree. The squash captures only
  the truncated portion. Sister to `working-tree-edits-stranded-on-squash-merge`
  (uncommitted Edit() — different mechanism, same symptom class) and
  `pr-followup-commit-stranded-after-squash` (commits pushed after merge —
  different timing). Distinct from `pr-hijack-via-stale-worktree-branch-ref`
  (which is about overwriting a different branch upstream).
author: Claude Code
version: 1.0.1
date: 2026-08-04
disable-model-invocation: true
---

# Subagent-driven session left commits stranded — branch ref froze while worktree HEAD advanced

## Problem

You ran a long `superpowers:subagent-driven-development` (or similar fresh-
subagent-per-task) session in a worktree. Each subagent did its task, committed
its work, the controlling session ran spec + code-quality review per task, all
green. At the end you pushed the worktree's branch to origin, opened a PR, CI
went green, you squash-merged.

Hours or one session later, somebody runs `pytest` on freshly-pulled main and
gets a `ModuleNotFoundError`, a missing-file assertion, or a `sql_path missing`
error pointing at code that **was definitely committed** during the session.
`git log` in your old worktree still shows all the commits at the top of the
branch. But on main, half of them are gone.

The squash commit on main contains only the early portion of your work —
typically the first N tasks before some specific transition point. Tasks
after that point exist as commits in the worktree (`git log` shows them)
but did not reach origin, did not reach the PR, did not reach the merge.

## Context / Trigger Conditions

Strong signal **after** the merge:

1. `gh pr view <N>` body claims a file count (e.g. "55 files changed") that
   doesn't match the actual squash-commit file count
   (`git diff-tree --no-commit-id --name-only -r <merge-sha> | wc -l`).
2. A test that passed locally during the session now fails on main because a
   file the test depends on isn't there.
3. Receiving session's first `pip install` or `pytest` surfaces
   `ModuleNotFoundError`, `sql_path missing`, or "no such file" referencing
   work the previous session reported as DONE.

Strong signal **during** the session (catch it before pushing):

4. `git rev-parse HEAD` ≠ `git rev-parse <feature-branch>` in the worktree.
   The branch ref is behind.
5. `git reflog show <feature-branch>` has a reflog gap — the most recent
   `worktree-...@{0}` entry is older than the most recent commit shown by
   `git log`. The commits between branch-ref's frozen point and current HEAD
   are stranded.
6. `git status` in the worktree may or may not report `HEAD detached at <sha>`
   — sometimes the detach happened mid-stream and a later subagent created
   the symbolic-ref linkage on its own, leaving an inconsistent state.

Strong signal **across sessions**:

7. The pattern is specific to subagent-driven sessions because each
   subagent's tool calls run in an isolated process tree. A detached-HEAD
   transition introduced by one subagent (e.g. for a quick `git show` or
   post-stash recovery) propagates silently to every later subagent. A
   single human running the same workflow would notice the prompt change
   to `(HEAD detached at <sha>)`.

## Solution

### Prevention (the cheap path)

Add an explicit pre-merge verification step before any `gh pr merge`:

```bash
# 1. All three of these should produce the SAME sha:
git rev-parse HEAD
git rev-parse <feature-branch>
git rev-parse origin/<feature-branch>

# 2. This should print NOTHING (zero commits ahead of remote):
git log origin/<feature-branch>..HEAD --oneline

# 3. PR body file-count canary:
#    "N files changed" in the PR body should match
gh pr diff <N> --repo <owner>/<repo> --name-only | wc -l

# 4. Reflog must extend to current HEAD:
#    Compare the topmost entry from each — they should agree.
git reflog show <feature-branch> | head -1
git log -1 --oneline
```

If any one of those is misaligned, **STOP**. Do not merge. Recover with the
hotfix path below before pushing the merge button.

### Recovery (post-merge)

If the merge already happened and you're seeing the symptom:

```bash
# 0. Confirm the diagnosis.
git -C <worktree-path> rev-parse HEAD                   # the "true" tip
git -C <worktree-path> rev-parse <branch>               # the frozen ref
# If these differ, you have stranded commits.

# 1. List exactly which commits are stranded (in topological order).
git -C <worktree-path> log <branch>..HEAD --oneline

# 2. Branch a recovery branch from current origin/main.
git fetch origin
git checkout -B recover/<short-name> origin/main

# 3. Cherry-pick the stranded commits in order.
git cherry-pick <oldest-stranded-sha>..<newest-stranded-sha>
# (or list them individually if the range is non-linear)

# 4. If the cherry-picks reference paths that have moved on main since
#    the original work was authored (common when other PRs landed
#    concurrently and reorganized files), add a follow-up commit that
#    fixes the path references. Don't try to fix them inside the
#    cherry-picks — that breaks the audit trail.

# 5. Run tests against the merged result of recovery + main.
<test command>

# 6. Push, PR, merge.
git push -u origin recover/<short-name>
gh pr create --base main --title "fix: recover <N> commits stranded by PR #<original> squash" \
  --body "<post-mortem-ish explanation; cite the original PR's merge commit>"
```

The recovery PR should bundle BOTH the cherry-picks AND any path fixes
required for the merged tree to function. Splitting them produces a
half-broken main between the two merges.

### Forensic verification

You can confirm the diagnosis precisely:

```bash
# The reflog gap tells you WHERE the freeze happened.
git -C <worktree-path> reflog show <branch> | head -1
# vs
git -C <worktree-path> log --oneline -1
# The gap is everything between those two.

# Pre-squash file count vs post-squash file count.
gh pr diff <N> --repo <owner>/<repo> --name-only | wc -l    # what GitHub saw
git -C <main-repo> diff-tree --no-commit-id --name-only -r <merge-sha> | wc -l
# These should agree. If both are smaller than your mental model, the
# strand is the gap to your mental model.
```

## Verification

After the recovery PR lands:

- `git diff origin/main origin/recover/<name>` (BEFORE the recovery merge)
  should show only the stranded commits + the path fix.
- After merge, the receiving session's pytest should be green.
- `git -C <main-repo> ls-tree -r --name-only main | grep <previously-missing-file>`
  should return the file.
- The original symptom (e.g. `sql_path missing`, `ModuleNotFoundError`) is
  gone.

## Example

the-handover-repo project, session 6 (2026-05-18). Plan B's 18 TDD tasks executed
via `superpowers:subagent-driven-development` in a worktree at
`.claude/worktrees/plan-b-brief-runner` on branch
`worktree-plan-b-brief-runner`.

Each implementer subagent reported DONE with a commit SHA. The controlling
session's per-task reviewers ran `pytest` from inside the worktree and saw
all green. At the end, the controlling session ran:

```bash
git push -u origin worktree-plan-b-brief-runner
gh pr create --title "feat(plan-b): brief-runner core backend" ...
# CI green; squash-merge.
```

PR [#9](https://github.com/wan-huiyan/the-handover-repo/pull/9) merged at
`d84ceee7032f73a60dc0bb2af57939aa3f987625`. The PR body claimed "55 files
changed, 2,295 insertions" — but the merge commit's file list had only 42.

Diagnosis post-merge:

```
$ git rev-parse HEAD                                    # in worktree
b31d37349c8a1316883014d50108f90eb52f93f8     # Task 18 ✓

$ git rev-parse worktree-plan-b-brief-runner        # in worktree
e9bb471acdac9d14c2114097f3230e00a11bc493     # Task 11 ← FROZEN

$ git reflog show worktree-plan-b-brief-runner | head -3
e9bb471 worktree-plan-b-brief-runner@{0}: commit: feat(brief-runner): CUSTOM_PARAMETER ...
2dbed0e worktree-plan-b-brief-runner@{1}: commit: feat(brief-runner): inline SQL parametrizer ...
# No reflog entries for Tasks 12-18, but they exist as commits!
```

The seven commits between e9bb471 (Task 11) and b31d373 (Task 18) — sql_hash,
Run Pack generator, all four route handlers, Dockerfile + cloudbuild +
.gcloudignore + deploy runbook — were stranded.

Recovery via [PR #14](https://github.com/wan-huiyan/the-handover-repo/pull/14)
(squash `d808859`):

```bash
git checkout -B recover/s5-plan-b-stranded-commits origin/main
git cherry-pick bc9748b 947315a 77ff3ce 0a66933 29ff572 5972d34 b31d373
# All cherry-picks applied cleanly.

# Then a follow-up commit to repoint analysis/SQL/*.registry.toml
# sql_path values to analysis/SQL/handover/<file>.sql, because PR #11
# had moved the SQL files under us during the original session.

pytest -q                # 166 passed, 1 skipped
git push -u origin recover/s5-plan-b-stranded-commits
gh pr create ...
gh pr merge --squash --delete-branch
```

Time from discovery to recovered-on-main: ~25 minutes. Full post-mortem with
forensics in
`docs/analysis/2026-05-18-pr-9-stranded-commits.md` of the the-handover-repo repo.

## Notes

- **The reflog gap is the single most reliable forensic.** `git log` walks
  from HEAD and shows everything. `git reflog show <branch>` shows only what
  the branch ref actually saw — and a detached-HEAD commit doesn't update
  the branch ref. The asymmetry is your tell.

- **`gh pr merge` will not warn you.** GitHub's merge button operates on the
  remote branch state, which is exactly what you pushed. The mismatch
  between your local worktree HEAD and the pushed ref is invisible to
  GitHub.

- **The PR-body file count is the second canary.** Many session-handoff-style
  PR bodies summarize "M files changed, N insertions" from the controlling
  session's mental model. If that number is higher than
  `gh pr diff <N> --name-only | wc -l`, something is wrong.

- **A controlling session's `git log` is a false positive for "everything
  is fine".** Without `--branches=<branch>` it walks from HEAD. To validate
  the push will ship what you think, always compare against
  `origin/<branch>` explicitly.

- **Subagents may detach HEAD for innocuous reasons.** A subagent that runs
  `git show <sha>` followed by an interrupted `git checkout` (or relies on
  a tool that does so internally) can leave HEAD detached. Subsequent
  subagents will commit on the detached HEAD and never restore the branch
  ref. Adding `git symbolic-ref HEAD || echo DETACHED` to each implementer
  subagent's opening diagnostic catches this before the first commit.

- **Concurrent PRs amplify the damage.** If main moved while your worktree
  was open, the squash-merge silently reconciles your truncated tree
  against the new main — sometimes producing functioning but partial
  output, sometimes producing broken-reference output. See the example
  above where PR #11 moved SQL files under PR #9 while it was open;
  both the strand AND the path drift bit at once.

## References

- the-handover-repo [PR #9](https://github.com/wan-huiyan/the-handover-repo/pull/9)
  (the truncated original) and
  [PR #14](https://github.com/wan-huiyan/the-handover-repo/pull/14)
  (the cherry-pick recovery).
- the-handover-repo post-mortem at `docs/analysis/2026-05-18-pr-9-stranded-commits.md`
  (full forensic timeline + remediation recipe).
- Sister skills:
  [`working-tree-edits-stranded-on-squash-merge`](../working-tree-edits-stranded-on-squash-merge/SKILL.md)
  (uncommitted Edit() — different mechanism),
  [`pr-followup-commit-stranded-after-squash`](../pr-followup-commit-stranded-after-squash/SKILL.md)
  (commits pushed after merge — different timing),
  [`pr-hijack-via-stale-worktree-branch-ref`](../pr-hijack-via-stale-worktree-branch-ref/SKILL.md)
  (overwriting someone else's branch upstream — different problem entirely).
- `superpowers:subagent-driven-development` skill — where this pattern
  emerges. Worth adding the pre-merge verification snippet to that skill's
  "Common Mistakes" section.
- Pro Git §3.5 — [Remote Branches](https://git-scm.com/book/en/v2/Git-Branching-Remote-Branches)
  on why `git log` and `git reflog show <branch>` can disagree.
