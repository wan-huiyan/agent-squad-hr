---
name: git-rebase-stalls-async-post-commit-hook
description: |
  Fix `git rebase origin/main` (or any multi-commit rebase) silently stalling
  mid-replay with `hint: pick <SHA> ... It has been rescheduled; To edit the
  command before continuing, please edit the todo list first` output, leaving
  a stuck `.git/worktrees/<name>/rebase-merge/` directory that `git rebase
  --abort` does NOT clear. Use when: (1) you ran `git rebase origin/main` on a
  branch with N commits to replay, (2) the rebase output shows partial
  progress (`Rebasing (1/N)... Rebasing (2/N)...`) then hangs or returns with
  `It has been rescheduled` hint for a specific commit SHA, (3) `git status`
  reports `## HEAD (no branch)` (detached), (4) `git rebase --abort` returns
  silently but the next `git rebase` reports `fatal: It seems that there is
  already a rebase-merge directory`, (5) the project has an async `post-commit`
  hook that spawns a long-running subprocess in background (the canonical
  signature is `[post-commit] ... running ... in background` printed during
  the rebase output, OR a `.git/hooks/post-commit` that contains `( cmd ... &)`
  / `nohup` / spawns `claude -p`, `npm run`, `bundle exec`, etc. in a
  detached subshell). Root cause: each rebase-applied commit fires the
  post-commit hook, which spawns a background subprocess that holds open
  file descriptors / locks / process-group resources git's internal commit
  machinery is also trying to use; under load (multi-commit rebases) this
  produces a race that git interprets as a failed apply and "reschedules"
  the commit. The fix is to disable hooks for the duration of the rebase via
  `git -c core.hooksPath=/dev/null rebase origin/main`. Sister skill to
  `worktree-index-corrupt-async-post-commit-hook` (same family — sibling
  worktree index corruption from blob GC race) and
  `git-add-u-after-async-post-commit-hook` (same family — mass deletion
  staging in the SAME worktree). NOT for: real merge conflicts during
  rebase (those print `CONFLICT (content):` lines and require manual
  resolution), pre-commit hook failures (different signal — pre-commit runs
  on `git commit`, not on rebase apply), or genuine commit-message-edit
  prompts (those open `$EDITOR` rather than printing "rescheduled").
author: Claude Code
version: 1.1.0
date: 2026-06-05
disable-model-invocation: true
---

# `git rebase` stalls mid-replay because async post-commit hook holds resources

## Problem

You run `git rebase origin/main` on a branch with several commits ahead. The
rebase begins applying commits one by one and partway through prints output
like:

```
Rebasing (1/10)Rebasing (2/10)...Rebasing (5/10)
[post-commit] Python files changed — running doc update in background...
hint:
hint:     pick 8b625b6b8b... fix(runbook): split verification probe ...
hint:
hint: It has been rescheduled; To edit the command before continuing, please
hint: edit the todo list first:
hint:
hint:     git rebase --edit-todo
hint:     git rebase --continue
```

`git status` reports `## HEAD (no branch)` (detached HEAD), the rebase is
not complete, but no merge conflict was raised. `git rebase --abort`
appears to succeed silently, but the next `git rebase` reports:

```
fatal: It seems that there is already a rebase-merge directory, and
I wonder if you are in the middle of another rebase.
```

You're stuck. The branch can't move forward and the rebase machinery
won't reset cleanly.

## Trigger conditions

All of these together:

1. Multi-commit rebase (`origin/main` is several commits ahead).
2. Output contains "rescheduled" hint for a specific commit SHA, NOT a
   `CONFLICT (content):` line.
3. `git status` reports detached HEAD post-stall.
4. `git rebase --abort` runs silently but does NOT clear
   `.git/worktrees/<name>/rebase-merge/` (or `.git/rebase-merge/` for
   non-worktree repos).
5. Project has an async post-commit hook — confirm with:
   ```sh
   cat .git/hooks/post-commit 2>/dev/null | head -30
   ```
   Look for `&` / `nohup` / `( ... ) &` / "running ... in background" /
   `claude -p` / `npm run` spawned non-interactively. The diagnostic
   signature in the rebase output is the literal string
   `[post-commit] ... running ... in background` printed between
   `Rebasing (N/M)` lines.

If only (2) matches but the hook is absent, you have a genuine real-conflict
or other rebase failure mode — this skill doesn't apply.

## Root cause

Each commit `git rebase` applies fires the `post-commit` hook. The hook
spawns a long-running subprocess in a backgrounded subshell — common
patterns include:

```sh
# Anti-pattern A: claude headless mode in background
( claude -p "..." --allowedTools "Read,Edit,Write,Bash,Grep,Glob" \
    > /tmp/claude.log 2>&1
  ... rest of background work
) &

# Anti-pattern B: nohup spawn
nohup ./regen-site.sh > /tmp/regen.log 2>&1 &

# Anti-pattern C: heavy work in process-group of git
python3 regen.py > /dev/null 2>&1 &
```

Even with `&` or `()` subshell + redirect, the spawned process inherits
git's process group and holds open file descriptors. During a rebase,
git's atomic commit operations (writing index, advancing HEAD, applying
the next patch) interact with these lingering resources and intermittently
fail in a way git interprets as "commit could not be applied — try
again later", emitting the "rescheduled" hint.

The race is most reproducible on commits that come early in the rebase
sequence (before the OS has had time to fully reap previous hook spawns)
and on machines under load. It can also produce stuck `rebase-merge`
directories because the abort path itself triggers post-commit-style
cleanup that hangs.

## Fix

### Step 1 — Clear the stuck `rebase-merge` directory

```sh
# Inspect first to confirm it exists
ls -la .git/worktrees/<your-worktree>/rebase-merge/ 2>/dev/null
# Or for non-worktree repos:
ls -la .git/rebase-merge/ 2>/dev/null

# Remove it
rm -rf .git/worktrees/<your-worktree>/rebase-merge
# Or:
rm -rf .git/rebase-merge

# Now switch back to your branch (you were on detached HEAD)
git checkout <your-branch>
```

If `rm -rf` is gated on "the dir doesn't look stale" (some teams),
verify no other rebase is genuinely in progress in another shell or
worktree before forcing.

### Step 2 — Re-run rebase with hooks disabled

```sh
git -c core.hooksPath=/dev/null rebase origin/main
```

This single-command override is per-invocation: it does NOT modify
`.git/config` and does NOT affect other developers / future commits.
The rebase will replay all commits without firing `post-commit`
(or any other hook), and should complete cleanly:

```
Rebasing (1/10)Rebasing (2/10)... Rebasing (10/10)
Successfully rebased and updated refs/heads/<your-branch>.
```

### Step 3 — Re-enable hooks for normal work

Nothing to do — the `-c core.hooksPath=/dev/null` was scoped to that one
git command. Subsequent `git commit` / `git push` invocations fire hooks
as normal.

### Optional: long-term mitigation

If your team frequently hits this, consider:

1. **Make the post-commit hook truly fire-and-forget.** Use `setsid` to
   detach the subprocess from git's process group:
   ```sh
   setsid bash -c "<background-work>" </dev/null >/tmp/log 2>&1 &
   disown
   ```
   `setsid` creates a new session; the process is no longer in git's
   process group, so git's commit machinery can't accidentally interact
   with it.

2. **Skip the hook on rebase apply.** Detect the rebase context and
   no-op early:
   ```sh
   # In .git/hooks/post-commit
   if [ -d "$(git rev-parse --git-dir)/rebase-merge" ] || \
      [ -d "$(git rev-parse --git-dir)/rebase-apply" ]; then
       exit 0  # we're inside a rebase; skip background work
   fi
   ```
   This is the cleanest fix because the hook's intent ("react to new
   commits") is wrong during rebase replay anyway — the rebase will
   apply many commits, and you don't want N background-doc-update
   subprocesses spawning in 10 seconds.

3. **Move the hook from `post-commit` to `post-rewrite`** if its work
   only needs to fire after explicit human commits, not rebase-apply
   commits. `post-rewrite` fires once at the end of a rebase, not per
   commit.

## Verification

After Step 2, confirm the rebase completed:

```sh
git rev-list --left-right --count <branch>...origin/main
# Expect: <N>  0  (you are N ahead, 0 behind — fully rebased)

git status -sb
# Expect: ## <branch>...origin/<branch> [ahead N]  (NOT "## HEAD (no branch)")
```

Then verify the commits replayed correctly (no orphans, no doubles):

```sh
git log --oneline origin/main..HEAD
# Expect: exactly your N commits, in order, with new SHAs (rebase rewrites)
```

## Example (a client propensity dashboard, 2026-05-11)

Repository: `wan-huiyan/the-project-repo` with an async
`post-commit` hook at `.git/hooks/post-commit` that spawns `claude -p`
in a subshell for headless documentation updates:

```sh
# .git/hooks/post-commit (excerpt)
echo "[post-commit] Python files changed — running doc update in background..."
(
  claude -p "Review the Python files changed in the last commit..." \
    --allowedTools "Read,Edit,Write,Bash,Grep,Glob" \
    > /tmp/claude-post-commit.log 2>&1
  ...
) &
```

Scenario: PR #727 had 10 commits ahead of `origin/main`. After two
successful rebases earlier in the session, a third rebase (triggered by
a parallel code-reviewer flagging a new tracker-ID collision from PR
#730) hung mid-replay with:

```
Rebasing (1/10)Rebasing (2/10)Rebasing (3/10)Rebasing (4/10)
[post-commit] Python files changed — running doc update in background...
hint:
hint:     pick 8b625b6b8b... fix(runbook): split verification probe ...
hint:
hint: It has been rescheduled; ...
```

`git rebase --abort` returned silently. Next `git rebase` reported the
stuck `rebase-merge` directory. Fix:

```sh
rm -rf .git/worktrees/check-bake/rebase-merge
git checkout worktree-check-bake
git -c core.hooksPath=/dev/null rebase origin/main
# → Successfully rebased and updated refs/heads/worktree-check-bake
```

Total time lost before recognizing the pattern: ~10 minutes (two failed
retries with different env-var combinations before zeroing in on
`core.hooksPath=/dev/null`).

## Notes

- The `core.hooksPath=/dev/null` trick works because git only fires hooks
  found at the configured path. Pointing at `/dev/null` makes the lookup
  fail silently (no hook = no fork). It's safer than `chmod -x
  .git/hooks/post-commit` (which persists) or moving the file aside
  (race-prone if you forget to restore).

- This is distinct from `worktree-index-corrupt-async-post-commit-hook`
  (sibling worktree index corruption from blob GC) and
  `git-add-u-after-async-post-commit-hook` (mass-stage of tracked-file
  deletions when post-commit mutates files between commit and amend).
  All three are members of the same "async post-commit hook side effects"
  family but have different symptoms and different fixes. If you're
  diagnosing in the same project, run a quick `cat .git/hooks/post-commit`
  to confirm async-spawn presence, then triage by symptom.

- "Rescheduled" hints with no `CONFLICT (content):` line are almost
  always either this race or a genuine rebase-todo edit attempt (which
  only triggers if you ran `git rebase -i`). For `git rebase
  origin/main` (non-interactive), "rescheduled" without a conflict is
  the diagnostic signature.

- A pre-flight check before a long rebase on a hook-heavy repo:
  ```sh
  cat .git/hooks/post-commit 2>/dev/null | grep -E '&\s*$|nohup|running.*background' >/dev/null && \
    echo "WARNING: post-commit hook spawns background work; consider running rebase with hooks disabled"
  ```
  Cheap insurance.

- The `claude -p` headless-spawn pattern is becoming more common in
  Claude Code-augmented projects (auto-docs, auto-tracker updates,
  auto-skill-extraction). If you maintain such a project, prefer the
  `setsid` + `post-rewrite` mitigations from Step 3's "Optional"
  section to make the hook resilient by default.

## Variant — `index.lock` / "Another git process seems to be running"

A second observed signature of the same race: the rebase aborts mid-replay with

```
Another git process seems to be running in this repository, e.g.
an editor opened by 'git commit'. ... remove the file manually to continue.
```

i.e. the background hook subprocess held `.git/.../index.lock` while the rebase
tried to apply the next commit. Two things that look alarming but are fine:

1. **The working tree shows your changes "reverted".** The rebase had checked out
   an *intermediate* replayed commit (e.g. an early `feat:` commit, before your
   later refactor commit). Editors/linters may report the touched files as
   "modified". **Your branch ref still points at the original tip** —
   `git rev-parse <branch>` and `git log --oneline <branch>` confirm all commits
   are intact (commits are immutable; only the working-tree checkout moved).
2. **Recovery:** `git rebase --abort` (restores the branch tip + working tree),
   confirm `feature/...` content is back, then retry. If the lock has cleared
   (the hook subprocess finished), a plain `git rebase origin/main` now succeeds
   cleanly. If it stalls again, use the deterministic fix above:
   `git -c core.hooksPath=/dev/null rebase origin/main`.

(2026-06-05: hit during an S98 docs/feature session — a background `gh`/test
process + the async doc hook coincided with a `git rebase origin/main`; abort +
retry recovered, all commits intact.)

## Sister skills

- `worktree-index-corrupt-async-post-commit-hook` — same root cause
  family, different symptom: `fatal: unable to read <sha>` errors in a
  SIBLING worktree after commit in this one. The post-commit hook
  GCs blobs while sibling worktrees are mid-read.
- `git-add-u-after-async-post-commit-hook` — same root cause family,
  different symptom: `git add -u` + `--amend` stages thousands of
  tracked-file deletions because the post-commit hook mutated tracked
  files between commit and amend.

## References

- Git documentation on `core.hooksPath`:
  https://git-scm.com/docs/githooks
- `git rebase` exit-code behavior:
  https://git-scm.com/docs/git-rebase#_behavioral_differences
- `setsid` for proper process detachment:
  https://man7.org/linux/man-pages/man1/setsid.1.html
