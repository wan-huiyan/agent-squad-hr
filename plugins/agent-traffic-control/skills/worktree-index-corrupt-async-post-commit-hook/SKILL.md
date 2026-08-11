---
name: worktree-index-corrupt-async-post-commit-hook
description: |
  Fix `fatal: unable to read <sha>` or `invalid sha1 pointer in cache-tree of
  .git/worktrees/<name>/index` errors that surface when running git operations
  (`git status`, `git rebase`, `git pull`) in worktree B shortly after committing
  in sibling worktree A — when the project has an async post-commit hook (a hook
  that runs `&`, `nohup`, or "running ... in background"). Use when:
  (1) error message points at worktree B's index but you weren't editing B,
  (2) you just merged/squashed/committed in worktree A and immediately switched,
  (3) the project has a `[post-commit] ... running ... in background` log line
  on commit, (4) `git fsck` reports `missing blob` errors across MULTIPLE worktree
  indexes simultaneously. NOT for: stale lock files (.git/index.lock — separate
  pattern), branch-checked-out-elsewhere errors (use `gh-pr-merge-worktree-checkout-trap`),
  or single-worktree corruption (different cause).
author: Claude Code
version: 1.0.0
date: 2026-05-06
disable-model-invocation: true
---

# Worktree index corruption from async post-commit hooks

## Problem

You commit in worktree A. Immediately afterwards (within seconds), you run
`git status` / `git rebase origin/main` / `git fetch && git rebase` in
sibling worktree B and get:

```
fatal: unable to read cd2a732cd2d5ad030414b953e21b9e403ab88699
```

or

```
error: cd2a732c...: invalid sha1 pointer in cache-tree of
       .../.git/worktrees/<name>/index
error: missing blob b007cf60...
error: missing blob d4077a21...
```

The error blames worktree B, but worktree B was clean and untouched.
`git status` itself fails. `git rebase` aborts before doing anything.

## Why this happens

Linked git worktrees share the underlying object database (`.git/objects/`)
but have **per-worktree index files** at `.git/worktrees/<name>/index`. Each
index's cache-tree caches `(path → tree-sha)` mappings to make `git status`
fast.

When the project has an async post-commit hook — common patterns:

```bash
# hooks/post-commit
[post-commit] Python files changed — running doc update in background...
nohup python3 docs/generate_website.py > /dev/null 2>&1 &
```

— or any hook that writes new objects/refs/files asynchronously after
returning — the sequence

1. commit in worktree A → post-commit hook starts writing to `.git/objects/`
2. **before** the async write finishes, you switch to worktree B
3. worktree B reads its cached cache-tree, which references object SHAs
   that A's hook is mid-creating

means worktree B's cache-tree points at SHAs that are either not-yet-flushed
or were transiently visible and then replaced. The cache-tree is now
inconsistent with the actual object DB. Every subsequent git command in B
that consults the index fails before it even reads HEAD.

The `fsck` confirms it cross-cuts ALL siblings:

```
error: <sha>: invalid sha1 pointer in cache-tree of
       .../.git/worktrees/<other-worktree-A>/index
error: <different-sha>: invalid sha1 pointer in cache-tree of
       .../.git/worktrees/<other-worktree-B>/index
error: <yet-another-sha>: invalid sha1 pointer in cache-tree of
       .../.git/worktrees/<other-worktree-C>/index
```

Multiple worktrees' indexes are corrupted simultaneously — that's the
fingerprint that distinguishes this from a normal index lock or a
branch-elsewhere error.

## Fix (one-liner per affected worktree)

```sh
# In the broken worktree:
rm /path/to/main/repo/.git/worktrees/<this-worktree>/index
git reset --mixed HEAD
```

That's it. The index is a derived cache; deleting it forces git to rebuild
from the on-disk files + HEAD. No data loss because the working tree's
actual file content is untouched. Any staged changes are lost — but if
you got here, you weren't mid-edit anyway.

For `<this-worktree>`: it's the basename of the worktree directory. Or
look at the `.git` file in your worktree dir:

```sh
cat .git
# gitdir: /path/to/main/repo/.git/worktrees/<NAME>
```

## Prevention

Before running git ops in a sibling worktree right after a commit elsewhere,
either:

1. **Wait for the hook to finish.** If the hook line says "running in
   background" you can usually wait 5-10 seconds and the race vanishes.
2. **Pre-emptively rebuild the index** in any worktree you're about to
   operate on, immediately after commits land in siblings:

   ```sh
   rm .git/worktrees/<name>/index 2>/dev/null
   git reset --mixed HEAD
   ```

   Cheap (~50ms) and idempotent — safe to run unconditionally as a defensive
   step in scripts that orchestrate multi-worktree merges.

3. **Make the hook synchronous** if the project allows. `wait` at the end
   of the hook, or just drop the `&`/`nohup`. Slower commits but no race.

## Verification

After the fix:

```sh
git status              # should report clean / branch state without error
git fsck --no-dangling  # should report no errors on this worktree's index
```

If `fsck` still complains about other worktrees' indexes, run the same fix
in each of them. The corruption can hit several worktrees simultaneously
because they all share the object DB.

## Example (a client analytics repo, S130 merge orchestration)

Context: 5 parallel feature-branch worktrees, sequentially squash-merging
PRs via `gh pr merge`. The project's post-commit hook prints
`[post-commit] Python files changed — running doc update in background...`
and forks a generator. Right after merging PR #244 in worktree A and
running `git fetch && git rebase origin/main` in worktree B (record-drawer-ux):

```
$ git rebase origin/main
error: cannot rebase: You have unstaged changes.
$ git status
fatal: unable to read cd2a732cd2d5ad030414b953e21b9e403ab88699
$ git fsck --no-dangling
error: 7c813df3...: invalid sha1 pointer in cache-tree of
       .../.git/worktrees/new-dashboard-bugs/index
error: 6c1ddfb5...: invalid sha1 pointer in cache-tree of
       .../.git/worktrees/record-drawer-ux/index
error: 6c1ddfb5...: invalid sha1 pointer in cache-tree of
       .../.git/worktrees/clarify/index
error: 7c813df3...: invalid sha1 pointer in cache-tree of
       .../.git/worktrees/110b/index
missing blob b007cf60...
missing blob d4077a21...
[...]
```

Four worktrees corrupted simultaneously — the cross-cut signature. Fix:

```sh
rm /Users/.../the-project-repo/.git/worktrees/record-drawer-ux/index
git reset --mixed HEAD
# clean
git rebase origin/main   # works
```

Same one-liner applied to each subsequent worktree before its rebase.
Pre-emptively running it on the *next* worktree before rebasing it
eliminated the race for the rest of the merge sequence.

## Notes

- This is distinct from `.git/index.lock` errors (different fix: just
  remove the lock file) and from `error: cannot lock ref` (concurrent
  ref-update race, different fix).
- The error message is misleading. It names the worktree where the command
  was run, not the worktree whose hook caused the race. `git fsck` is the
  diagnostic that reveals the cross-cut.
- `git read-tree HEAD` is an alternative to `git reset --mixed HEAD` for
  rebuilding the index, slightly more surgical (doesn't touch HEAD's
  staging state) but `--mixed` is more familiar.
- If the hook also writes to shared paths inside `.git/info/` or
  `.git/refs/`, even more bizarre symptoms can surface. The same root-cause
  applies — the fix is to ensure the hook's writes are synchronous OR to
  rebuild the affected index before next use.
- Project hooks that match this pattern usually log `[post-commit] ...
  running ... in background` or `[post-commit] ... &` to stdout/stderr.
  If you see such a line on commit, treat the whole repo as
  race-vulnerable across worktrees.

## See also

- `git-add-u-after-async-post-commit-hook` — sister skill, **same root
  cause family** (async post-commit hook side effects), different
  symptom: `git add -u && git commit --amend` accidentally rolls
  thousands of unrelated tracked-file deletions into the amended
  commit, then force-push propagates the catastrophe to the remote PR.
  This worktree-index skill covers the cross-worktree blob-GC race;
  the `git-add-u-after-...` skill covers the same-worktree index
  staging trap.
- `git-rebase-stalls-async-post-commit-hook` — sister skill, **same
  root cause family**, different symptom: multi-commit `git rebase
  origin/main` stalls mid-replay with `hint: ... It has been
  rescheduled` output, leaving stuck `rebase-merge` directories that
  `git rebase --abort` does NOT clear. Each rebase-applied commit
  fires the hook; the hook's spawned background subprocess races
  git's atomic apply machinery. Fix: `git -c core.hooksPath=/dev/null
  rebase origin/main`. Distinct symptom from the cross-worktree blob
  GC race covered here.
- `gh-pr-merge-worktree-checkout-trap` — *different* problem: gh refuses
  to delete a remote branch that's checked out in a sibling worktree.
- `using-git-worktrees` / `git-worktree` — general worktree workflow.
