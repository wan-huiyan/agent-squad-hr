---
name: pr-hijack-via-stale-worktree-branch-ref
description: |
  Diagnose and recover from accidentally overwriting another session's open PR
  when `git push -u origin <branch>` in a long-lived worktree silently
  replaces the remote branch ref. Use when ANY of the following appears:
  (1) you ran `git checkout -b <branch> origin/main` and `git push -u` and
  git reported `* [new branch]` even though the branch already existed
  upstream, (2) `gh pr create` then errors with
  `a pull request for branch "<branch>" into branch "main" already exists`
  pointing to a PR you didn't author, (3) `gh pr view N --json commits` on
  that PR shows YOUR commit instead of the one the title/body describes,
  (4) you discover your worktree's session-start git status banner was stale
  (showed branch X but actual branch was Y). Pattern surfaces when a prior
  session in the SAME worktree opened a PR on a generically-named feature
  branch, then reset the worktree's local refs without cleaning the remote.
  Recovery requires `git push --force-with-lease` — a destructive op
  requiring explicit user authorization. Sister to `git-recover-lost-branch`
  (mechanics of recovering an orphaned commit via reflog) and
  `gh-pr-merge-worktree-checkout-trap` (different worktree-vs-gh gotcha).
author: Claude Code
version: 1.0.0
date: 2026-05-12
disable-model-invocation: true
---

# PR-Hijack via Stale Worktree Branch Ref

## Problem

In a long-lived git worktree (especially `.claude/worktrees/<name>/` patterns
created by a parallel-session harness), a same-named local branch can be
created via `git checkout -b X origin/main` even when branch `X` already
exists upstream with an open PR. Pushing that local branch with
`git push -u origin X` succeeds — git reports `* [new branch]` — and
silently replaces the remote ref. The result:

- The remote branch ref now points at YOUR commit
- The open PR (call it #N) on that branch now lists YOUR commit
- PR #N's title and body still describe the ORIGINAL author's work
- The original author's commit is orphaned on the remote but still
  reachable in YOUR local reflog (because the worktree's reflog captured
  it earlier)
- `gh pr create` fails with `a pull request for branch "X" into "main"
  already exists` and surfaces PR #N — which is now an artefact of two
  unrelated commits

The hijack is silent on both sides: git's push output doesn't warn, gh
doesn't either, and the PR's web view shows a perfectly plausible (but
wrong) state.

## Context / Trigger Conditions

Surfaces when ALL of:

1. You are working in a worktree (typically `.claude/worktrees/<name>/`)
   that has been used by a previous session
2. The session-start git status banner shows a branch name that does NOT
   match `git status -sb` once you actually run it (stale banner)
3. A prior session in the same worktree opened a PR on a generically-named
   feature branch (e.g., `feat/drivers-headline-and-stripe-removal`,
   `feat/refactor-foo`, `fix/bar-bug`)
4. The worktree's local refs were reset between sessions (`git reset
   --hard`, branch deletion, or worktree-recreation) WITHOUT a
   corresponding `git push --force` to clean up the remote
5. You create a local branch by the same generic name

Exact failure-signature triad:

```
# Symptom 1 — push reports new-branch despite upstream existing
$ git push -u origin feat/<name>
* [new branch]        feat/<name> -> feat/<name>

# Symptom 2 — gh pr create rejects with already-exists
$ gh pr create ...
a pull request for branch "feat/<name>" into branch "main" already exists:
https://github.com/<org>/<repo>/pull/N

# Symptom 3 — that PR's commits don't match its title/body
$ gh pr view N --json commits
{ "commits": [{ "oid": "<YOUR-SHA>", "messageHeadline": "<YOUR WORK>" }] }
```

If the gh-pr-view output shows YOUR work and the PR title describes
something entirely different — confirmed hijack.

## Solution

**Stop before doing anything else.** Recovery requires a destructive
force-push to a remote branch you don't own. Ask the user for explicit
authorization first.

### Step 1 — Locate the original SHA via reflog

```bash
git reflog --date=iso | grep -E "<branch-name>|<keyword-from-pr-title>" | head -10
```

The reflog entry will look like:

```
<orig-sha> HEAD@{<timestamp>}: commit: <ORIGINAL PR TITLE>
<base-sha> HEAD@{<timestamp>}: checkout: moving from <old> to <branch>
```

Verify the orphaned commit is still reachable:

```bash
git cat-file -t <orig-sha>   # should print "commit"
git log --oneline <orig-sha> -3
```

If the reflog is empty or doesn't contain the SHA, you may need to:
- `git fsck --unreachable` (orphan-walk)
- Pull the PR's HEAD via `gh pr view N --json headRefOid`

### Step 2 — Stash your work to a fresh branch FIRST

Critical ordering: create the rescue branch BEFORE resetting the current
branch. Otherwise you'll have nothing to push to a new branch.

```bash
git branch <new-branch-name> <YOUR-SHA>   # e.g., feat/<descriptive-new-name>
git branch -v | grep <descriptive>         # verify both branches exist
```

### Step 3 — Reset the hijacked branch back to the original SHA

```bash
git reset --hard <orig-sha>
git log --oneline -2   # confirm HEAD is now at the original commit
```

### Step 4 — Force-with-lease to restore PR #N

```bash
git push --force-with-lease=<branch>:<YOUR-SHA> origin <branch>
```

`--force-with-lease=<branch>:<YOUR-SHA>` says "only push if the remote
ref is currently exactly YOUR-SHA" — which it is, since you just pushed
it. This guards against clobbering anything a third party may have pushed
since.

After this, `gh pr view N --json commits` should show the original SHA
and the PR is fully restored.

### Step 5 — Push your work to the new branch

```bash
git checkout <new-branch-name>
git push -u origin <new-branch-name>
gh pr create --title "..." --body "..."
```

### Step 6 — Document the collision in the new PR

Cross-link to PR #N in the new PR's "branch history" or "notes for
reviewer" section. Mention the two PRs touch the same page/area but
different code paths. This avoids the reviewer wondering why two PRs on
sister branches exist.

## Verification

After recovery, verify all three sides:

```bash
# Local reflects truth
git log --oneline <original-branch>   # → original SHA on top
git log --oneline <new-branch>        # → your SHA on top

# Remote reflects truth
gh pr view N --json title,commits | python3 -m json.tool
# title and commits should describe ORIGINAL work

gh pr view <NEW-N> --json title,commits
# title and commits should describe YOUR work

# CI on both PRs should re-run automatically after the force-push
gh pr checks N
gh pr checks <NEW-N>
```

## Prevention

The trigger is **stale local refs in a long-lived worktree**. Two habits
prevent it:

1. **Verify branch state at session start.** When entering a worktree,
   `git status -sb && git log --oneline -3 && git ls-remote origin
   <branch-you-plan-to-create> | head -2`. If `ls-remote` shows the
   branch exists upstream and your local reflog has no record of it,
   pick a different name.

2. **Prefix branch names with session/date.** Generic names like
   `feat/refactor-foo` collide across sessions. `feat/<YYYYMMDD>-foo`,
   `feat/<session-id>-foo`, or worktree-scoped names eliminate the
   collision class entirely. The repos that have this convention
   (e.g., `pr-conflict-site-regen` Step 2a's `cat7-7XX` ID
   pattern) don't see this bug.

If your worktree harness shows a session-start git status banner, **don't
trust it**. The banner is captured at worktree creation and can be stale
after subsequent operations. Always run `git status -sb` first.

## Notes

- This is NOT the same as `stale-base-pr-silently-reverts-upstream-content`
  (that's about merging a stale PR clobbering main's progress). The trigger
  here is the OPPOSITE direction: your local clobbering the remote on push.
- It is also NOT the same as `gh-pr-merge-worktree-checkout-trap` (failed
  merge due to worktree-locks-main). Here the merge isn't involved; the
  collision happens at push time before any merge.
- Once force-with-lease restores PR #N, CI will re-run. If the original
  author's PR was already approved, the re-trigger will require re-approval
  (GitHub behavior). Warn the author.
- If the original branch had multiple commits and only some were captured
  in your reflog, the recovery is partial — pull `gh pr view N --json
  headRefOid` BEFORE resetting to capture the full upstream tip.
- The `git push -u origin <branch>` reporting `* [new branch]` is the
  EARLIEST detectable signal. If you see that message and the branch name
  is generic, immediately `gh pr list --head <branch>` to check for
  pre-existing PRs before continuing.

## Example

Real session (2026-05-12, the-project-repo repo, Opus 4.7):

1. Worktree `review-driver` was created from a session ~12:33Z that
   committed `e4796f17 Fix /drivers chevron: filter NULL raw_value rows`
   to `feat/drivers-headline-and-stripe-removal`, pushed, opened PR #761.
2. That session reverted the local branch ref to `origin/main` but left
   the remote branch + PR alone.
3. The next session entered the worktree, ran `/impeccable critique driver
   page`, decided to fix headline + side-stripes, did `git checkout -b
   feat/drivers-headline-and-stripe-removal origin/main` — collided
   with the upstream ref but git locally treated it as new.
4. Committed `5107c97f` and pushed; got `* [new branch]`.
5. `gh pr create` returned "a pull request for branch X already exists:
   #761". `gh pr view 761` showed PR #761's title was still the chevron
   fix, but the only commit listed was `5107c97f` (the hijacker).
6. Recovery: `git branch feat/drivers-headline-take 5107c97f` →
   `git reset --hard e4796f17` → `git push --force-with-lease=feat/
   drivers-headline-and-stripe-removal:5107c97f origin feat/
   drivers-headline-and-stripe-removal` → `git checkout feat/drivers-
   headline-take` → `git push -u origin feat/drivers-headline-take` →
   `gh pr create` → PR #762. Total recovery time: ~3 minutes once the
   hijack was diagnosed.

## References

- `git push --force-with-lease`:
  https://git-scm.com/docs/git-push#Documentation/git-push.txt---force-with-leaseltrefnamegt
- `gh-pr-merge-worktree-checkout-trap` (sister skill, different
  worktree-vs-gh failure mode)
