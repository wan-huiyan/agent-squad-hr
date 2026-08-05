---
name: gha-pr-merge-ref-shows-upstream-changes
description: |
  Diagnose "my CI failed on a file I didn't change — the test passes locally
  but CI insists there's a duplicate / conflict / lint violation that isn't
  in my branch." Caused by GitHub Actions checking out `refs/pull/N/merge`
  (the auto-computed merge of PR head + base) on `pull_request` events.
  Use when: (1) CI fails on a `git`/lint/whole-tree check (duplicate IDs,
  schema drift, file-content audit) that PASSES on the same SHA locally,
  (2) you're working in a dense parallel-PR window where main is moving
  faster than your CI runs, (3) `gh run view N --json headSha` matches
  your latest force-push but `git fetch origin main && git diff
  origin/main..HEAD` shows main is ahead by N commits, (4) the failure
  references symbols / IDs / values that are present in MAIN but absent
  from your branch. Root cause: GitHub re-computes the merge ref every
  time the base moves, so CI on `pull_request` sees `main-at-CI-start +
  your-branch`, NOT just `your-branch`. Sister concept to
  `gha-billing-failure-fast-fail-pattern` (different GHA gotcha) and
  `pr-conflict-site-regen` Step 2b (when this surfaces during
  tracker collision sweeps).
author: Claude Code
version: 1.0.0
date: 2026-05-11
disable-model-invocation: true
---

# GHA `pull_request` Event Uses Merge-Ref, Not Head-Ref

## Problem

You push a commit to a PR branch at T0. CI starts running at T0+10s. A
sibling PR merges to main at T0+5s. Your CI run **sees the sibling's
changes mixed into your branch** and fails on something neither side
introduced alone.

Most confusingly: locally on the exact same commit SHA, every check
passes. `gh run view <N> --json headSha` reports your SHA correctly.
`git show <SHA>:<file>` shows your file is clean. But CI failed on that
SHA citing duplicates / conflicts / violations that aren't there.

## Context / Trigger Conditions

- CI failure on a `pull_request` event (NOT `push`)
- Failure cites a violation in a file you didn't touch in your last push
- The same SHA passes the same check locally
- `gh run view <N> --json headSha` matches your local HEAD
- `git fetch origin main && git rev-list --left-right --count origin/main...HEAD`
  shows main is ahead by 1+ commits since your push
- The failure message references identifiers / strings present in main
  but not in your branch (e.g. "duplicate ID `X`" where `X` was added
  to main by a PR that merged seconds before your CI ran)
- You're in a dense parallel-PR window (multiple PRs merging within
  minutes — release day, mass-merge sweep, several agents shipping
  concurrently)

## Root cause

GitHub Actions, when triggered by `pull_request: [opened, synchronize,
reopened, ...]`, checks out a SYNTHETIC ref called `refs/pull/<N>/merge`.
This ref is the **3-way merge of `refs/pull/<N>/head` + `refs/heads/main`
+ their merge-base**, recomputed by GitHub every time either side
changes.

Concretely:

```
Local view:  your-branch-HEAD  (clean)
CI view:     merge(your-branch-HEAD, main-HEAD-at-CI-start)  (may have collisions)
```

GitHub regenerates the merge ref whenever:
- The PR branch is pushed
- The base branch (main) receives a new commit
- The PR is rebased / force-pushed

If main moves between your push and your CI's checkout step, the merge
ref includes main's NEW state plus your branch.

The `headSha` field in `gh run view` reflects your branch's commit,
which makes the failure look like "my branch broke this" rather than
"main + my branch combined broke this."

The `actions/checkout@v4` default behavior:
- `pull_request` event → `ref: refs/pull/N/merge` (the merge ref)
- `push` event → `ref: <pushed-sha>` (your actual commit)
- Explicit `ref: ${{ github.event.pull_request.head.sha }}` →
  force checkout of branch head only (no merge preview)

Default is "merge preview" because it tests what would happen post-merge,
which is genuinely useful for catching integration conflicts. The
downside is that base-side breakage can fail YOUR CI without anything in
your branch causing it.

## Solution

### Quick diagnosis

```bash
# 1. Confirm CI ran on your SHA
gh run view <run-id> --json headSha
git rev-parse HEAD   # should match

# 2. Check whether main moved since your push
git fetch origin --quiet
git log --oneline origin/main ^HEAD | head -5
# Any output = main moved. Empty = main is at or behind your branch.

# 3. Inspect the failure's specific accusation
# If it cites symbols/IDs/strings, search for them on main vs your branch:
git show origin/main:<path> | grep <accused-symbol>
git show HEAD:<path>        | grep <accused-symbol>
# If they BOTH show different occurrences = merge preview surfaced
# a collision your branch alone doesn't have.
```

### Fix path 1 — Rebase + force-push

The standard fix. Bring your branch onto current main, resolve any real
conflicts, force-push. CI's next merge-ref will be a clean fast-forward,
and the spurious failure goes away.

```bash
git fetch origin main
git rebase origin/main
# Resolve any conflicts that arise (these are the REAL ones — the CI was
# previewing them via the merge ref).
git push --force-with-lease
```

### Fix path 2 — Wait for the upstream sweep, then rebase

If main is moving because **other PRs are actively sweeping the same
file you're touching** (e.g. tracker collision fixes, schema migrations),
sometimes waiting 10-15 minutes lets the dust settle. Then rebase once
and merge. Each force-push you do during the wave triggers a fresh CI
cycle that's likely to re-surface the moving target.

### Fix path 3 — Pin to head ref (escape hatch)

Only if you're SURE the base-side check is wrong and you want to bypass
the merge preview:

```yaml
# In .github/workflows/your.yml
- uses: actions/checkout@v4
  with:
    ref: ${{ github.event.pull_request.head.sha }}
```

This makes CI test your branch in isolation. **Don't use as a default**
— you'll lose the integration-conflict catch. Use only for specific
checks (e.g. linting your branch's diff) where the merge preview is the
wrong question.

## Verification

After rebase + force-push, the next CI run on your branch should:
1. Have `headSha` matching your new HEAD
2. Pass the previously-failing check
3. (Often) the failure simply disappears with no further intervention

If CI still fails after rebase with the same accusation, it's a real
issue in your branch — the merge-ref theory was a red herring. Inspect
the file at HEAD directly.

## Example

Observed 2026-05-11 in the project repo during a dense parallel-PR
window. My PR #708 (UI tweaks + new tracker entry) pushed at T0. The
`test_tracker_no_id_collision` CI lint failed citing duplicate IDs
`cat7-7ho` and `cat7-7hp` that weren't in my branch's tracker file.

Locally: `pytest <analytics_pkg>/tests/test_tracker_no_id_collision.py
-v` → 2/2 PASSED.

CI: `gh run view 25665633945 --json headSha` → my exact SHA.

Investigation:

```bash
git fetch origin main --quiet
git log --oneline origin/main ^HEAD | head -3
# ab9deb13 docs(s170): handoff for magic-link soft-launch ... (#706)
# d18ec4e6 docs(s169): handoff + review report for /actions polish PR #696 (#704)
```

Main had absorbed 2 PRs in the 5 minutes between my push and CI's
checkout. Each of those PRs added new tracker entries with IDs
overlapping mine in the merge preview. CI's `refs/pull/708/merge` =
my branch + main's new state = duplicate IDs.

Resolution: `git rebase origin/main` (resolved 2 real tracker conflicts),
`git push --force-with-lease`. Next CI run: green.

The same trap recurred 2 more times in the same session as PRs #706
and #707 landed during subsequent rebases. Per `pr-conflict-site-regen`
v1.4.0 Step 2b, this is expected behavior in dense windows — the lint
is doing its job, just on a sliding target.

## Notes

- This is by design, not a GitHub bug. The merge preview catches real
  integration breakages that head-only CI would miss.
- The trap is worst when the base-side change overlaps semantically
  with your branch (same file, related symbols). Unrelated base changes
  rarely trigger this.
- `gh pr view <N> --json mergeStateStatus` reports `DIRTY` when there
  are content conflicts — that's a stronger signal than just CI failure.
  Always check this before assuming your branch is broken.
- For non-tracker file collisions (e.g. test fixtures, lint files, lock
  files), the diagnostic recipe is the same: rebase if main moved.
- The `pull_request_target` event uses the BASE branch's workflow file
  but checks out the PR's HEAD — different semantics entirely, used for
  permissioned workflows on forks. Don't confuse with `pull_request`.

## References

- [GitHub Docs: pull_request event](https://docs.github.com/en/actions/writing-workflows/choosing-when-workflows-run/events-that-trigger-workflows#pull_request)
- [GitHub Docs: actions/checkout default refs](https://github.com/actions/checkout#checkout-pull-request-head-commit-instead-of-merge-commit)
- Sister skills:
  - `gh-pr-merge-worktree-checkout-trap` (different gh subcommand
    failure mode)
