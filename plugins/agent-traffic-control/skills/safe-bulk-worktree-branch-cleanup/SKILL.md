---
name: safe-bulk-worktree-branch-cleanup
description: |
  Bulk delete accumulated git worktrees and branches without losing anything — "this repo is messy
  with worktrees", "too many branches", "tidy it up but keep X". Use when `git worktree list` or
  `git branch -a` prints dozens of stale entries. The trap: `git branch --merged` and `git
  merge-base --is-ancestor` report a squash merged branch as NOT merged, so they call almost
  everything unmerged and you stop, or delete believing you are losing work. Gate on the pull
  request's state instead. Salvages untracked files before `git worktree remove` discards them.
  Not for one branch that will not merge.
author: Claude Code
version: 1.0.0
date: 2026-05-20
---
# Safe Bulk Worktree & Branch Cleanup

## Problem

A repo accumulates dozens of git worktrees and branches over many sessions.
The user wants them cleaned up "without losing progress." Bulk-deleting is
risky in two non-obvious ways:

1. **Ancestry tests lie about squash-merged branches.** `git branch --merged`
   and `git merge-base --is-ancestor` only detect merge-commit / fast-forward
   merges. A squash merge creates a *new* commit on the trunk — the original
   branch tip is never an ancestor. In a squash-merge repo (PR titles ending
   `(#NN)`), these tools flag *almost every* merged branch as "NOT merged."
   Trusting them either blocks the cleanup or, worse, makes you think real
   work would be lost.
2. **`git worktree remove` silently discards untracked files.** Removing a
   worktree never deletes commits (the branch + history persist), but any
   *uncommitted / untracked* files in that worktree's directory are gone.

## Context / Trigger Conditions

- User: "this repo is messy with all the worktrees", "clean up the branches",
  "review the rest and help me clean up without losing progress".
- `git worktree list` shows many `.claude/worktrees/*` or `/tmp/*` entries.
- `git branch -a` shows dozens of stale `feature/*`, `claude/*`, `docs/*` branches.
- A bulk branch/worktree deletion where the user named something to keep.

## Solution

### 1. Inventory (read-only)

```bash
git worktree list                              # prunable = directory gone
git branch -a --sort=-committerdate
git fetch --all --prune                        # refresh remote-tracking refs
# per-worktree uncommitted check:
git worktree list --porcelain | awk '/^worktree /{print $2}' | while read w; do
  [ -d "$w" ] && echo "$(git -C "$w" status --porcelain | wc -l) dirty :: $w" \
              || echo "MISSING (prunable) :: $w"
done
```

### 2. Classify each branch — the verify-before-delete gate

A branch is **safe to delete** (zero progress lost) if ANY holds:
- **Tip is on a remote**: `git branch -r --contains <sha>` is non-empty.
- **Merged into the trunk**: `git merge-base --is-ancestor <sha> origin/<trunk>`.
- **Has a MERGED or CLOSED PR**: see step 3.

If NONE holds, the branch has local-only unmerged work → **keep it** (or push
it first). Do not delete it on the user's "without losing progress" instruction.

### 3. Resolve squash merges via PR state — NOT ancestry

When ancestry says "not merged," do not conclude work is unmerged. Map every
branch to its PR and use the PR's state:

```bash
gh pr list --state all --limit 300 --json number,headRefName,state,mergedAt
```

- PR **MERGED** → branch work is in the trunk (as a squash commit) → safe delete.
- PR **CLOSED** (unmerged) → team chose not to merge → stale → safe delete.
- PR **OPEN** → **keep** the branch; deleting it auto-closes the PR.
- **No PR ever** → no merge trail; treat as unverified → keep, or confirm with user.

### 4. Salvage untracked files before removing worktrees

For every worktree with untracked/modified files you intend to remove, copy
those files out first. A dedicated **salvage branch** keeps them durable:

```bash
git checkout -b salvage/worktree-cleanup-$(date +%F)
mkdir -p _salvage/<worktree-name>/ && cp <files> _salvage/<worktree-name>/
git add -f _salvage && git commit -m "chore: salvage untracked worktree files"
```

Ignore `?? .claude/` — that is Claude Code's per-worktree session dir, not content.

### 5. Write a SHA recovery manifest BEFORE deleting

Record `branch  full-sha  status` for every branch you will delete. Commit it
on the salvage branch. This makes every deletion 100 % reversible:
`git branch <name> <sha>` (then `git push origin <name>` for remotes).

### 6. Execute in order

```bash
# worktrees first (frees their branches for deletion)
git worktree remove --force <path>     # repeat; --force handles leftover untracked
git worktree prune                     # clears entries whose dir is already gone
# then branches
git branch -D <branch> ...             # -D (not -d): -d refuses squash-merged branches
git push origin --delete <b1> <b2> ... # remote branches, one push, multiple refs
```

You cannot remove the worktree you are currently inside — hand the user that
one command.

## Verification

```bash
git worktree list          # only the intended survivors
git branch -a              # keepers + trunk + protected open-PR branches
git fsck --connectivity-only --no-progress   # no corruption
```
Confirm protected items survived (the branch the user named, `main`, every
open-PR branch).

## Example

Session result: **27→5 worktrees, 79→11 local branches, 39→6 remote branches.**
Mid-run, `git merge-base --is-ancestor` flagged 32 of 33 remote branches as
"NOT MERGED" — alarming until recognised as the squash-merge artefact. Re-gating
on `gh pr list --state all` showed 21 MERGED + 5 CLOSED + 7 no-PR: all genuinely
stale. Every deleted SHA was recorded on a `salvage/worktree-cleanup-*` branch.

## Notes

- **Removing a worktree ≠ deleting a branch.** `git worktree remove` leaves the
  branch and all commits intact. The only loss surface is untracked files.
- **`git branch -d` vs `-D`:** `-d` refuses branches it thinks are unmerged
  (i.e. all squash-merged ones). Use `-D` *after* you have independently
  verified safety via step 2/3 — never as a shortcut to skip verification.
- **zsh word-splitting trap:** if your shell is zsh (the Claude Code Bash tool
  often is), `for b in $LIST` does NOT split a space-separated string — it
  iterates once over the whole blob. Wrap loops over string lists in
  `bash -c '...'`, or use zsh's `${=LIST}`. A silent off-by-everything bug.
- **Confirm before pushing remote deletions** — it is an outward action on a
  shared repo. Protect `main`, the default branch, and every open-PR branch.
- See also: `gh-pr-merge-worktree-checkout-trap` (merging when a sibling
  worktree holds the base branch), `git-recover-lost-branch` (post-hoc
  recovery), `git-pull-after-squash-merge` and
  `working-tree-edits-stranded-on-squash-merge` (other squash-merge effects).

## References

- `git worktree` docs — https://git-scm.com/docs/git-worktree
- `git branch --merged` / `--is-ancestor` only detect ancestor merges, not
  squash or rebase merges — https://git-scm.com/docs/git-merge-base

## Reference-only siblings in this toolkit

These carry `disable-model-invocation: true`. They never appear in the skill
listing and the Skill tool refuses them, so the only way in is to open the file
with Read when one of these matches what you are looking at.

- [`pr-hijack-via-stale-worktree-branch-ref`](../pr-hijack-via-stale-worktree-branch-ref/SKILL.md) — `git push -u origin <branch>` from a long-lived worktree overwrote another session's open PR
- [`deploy-from-stale-worktree-silent-rollback`](../deploy-from-stale-worktree-silent-rollback/SKILL.md) — a deploy built from a stale worktree silently rolled back recently merged fixes in production
- [`docs-branch-off-feature-branch-smuggles-code`](../docs-branch-off-feature-branch-smuggles-code/SKILL.md) — a docs-only follow-up PR ships the parent feature's code because the branch was cut from the wrong place
