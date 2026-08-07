---
name: concurrent-session-checkout-clobbers-shared-worktree
description: |
  A second Claude Code session (or agent/person) sharing the same working
  directory runs `git checkout`/`git switch`, flipping the branch for the whole
  working tree underneath your session and clobbering your uncommitted work.
  Use when: (1) a file you just edited has silently reverted — often with a
  "file was modified, either by the user or by a linter" system reminder,
  (2) `git branch --show-current` shows a branch you didn't switch to,
  (3) `git reflog` shows a `checkout: moving from X to Y` you never ran,
  (4) unfamiliar files/changes appear in `git status`, (5) you are ABOUT to
  dispatch parallel agents whose prompts say they are isolated — prose is not
  configuration, and the tool's `isolation: "worktree"` parameter is what
  actually creates one. Covers detecting the collision, recovering via an
  isolated git worktree, and the pre-dispatch check that prevents it.
author: Claude Code
version: 1.2.0
date: 2026-06-23
disable-model-invocation: true
---

# Concurrent session's `git checkout` clobbers your shared working directory

## Problem

Two Claude Code sessions (or any two agents/people) operate in the **same**
working directory on the same clone. `git checkout` / `git switch` changes
`HEAD` for the *entire working tree* — it is not per-session. When session B
switches branches, session A's tree changes underneath it:

- Uncommitted edits to tracked files may be carried across, reverted, or left
  in a confusing half-state.
- Untracked files (new files you created) stay on disk but risk being swept
  into session B's next `git add -A`.
- Edits get silently lost — e.g. a config field you added disappears.

It is invisible until something breaks: a function you wrote is "gone", a test
errors on a symbol you defined, or a harness emits *"file was modified, either
by the user or by a linter"* for a file you didn't expect to change.

## Context / Trigger Conditions

- A file you edited reverted to an older version with no action from you.
- `git branch --show-current` is not the branch you were working on.
- `git status` lists changes or untracked files you don't recognize.
- **Decisive:** `git reflog` shows `checkout: moving from <yours> to <other>`
  that you never performed.

## Solution

Do **not** keep fighting inside the shared directory — you will collide again.
Isolate into a git worktree.

1. **Confirm the collision** — `git reflog -5` reveals the foreign checkout.
   `git log <your-branch> --oneline` confirms your committed work is still safe
   on its branch (commits survive a checkout; only uncommitted work is at risk).
2. **Create a worktree for your existing branch** (not a new branch):
   ```bash
   git worktree add /path/outside/repo/my-worktree <your-branch>
   ```
   Place it *outside* the repo (a sibling dir) to avoid `.gitignore` edits that
   would themselves collide.
3. **Migrate uncommitted work into the worktree:**
   - Copy untracked files (`cp` the new files you created).
   - Re-apply tracked-file edits in the worktree (apply them fresh; the
     worktree has the clean branch tip).
   - Re-apply any edit that was *clobbered* — recover it from conversation
     context.
4. **Clean your pollution out of the shared dir** so the other session gets it
   back as expected: `git checkout <files-you-modified>` and `rm` your untracked
   files (you copied them already).
5. **Switch your session into the worktree** and continue there.
6. **Commit early and often** to your feature branch — committed work cannot be
   clobbered by a foreign checkout.

## Verification

- `git worktree list` shows your isolated worktree on your branch.
- Your work (files + edits) is present in the worktree; tests pass there.
- The shared directory's `git status` shows only the *other* session's files.

## Example

Session A is on `team-1-iap-deploy` with an uncommitted `app/config.py` edit.
The parallel session runs `git checkout team-1-web-app` in the shared `repo/`.
Session A's `app/config.py` edit vanishes; `git reflog` shows
`checkout: moving from team-1-iap-deploy to team-1-web-app`. Recovery:
`git worktree add ../iap-worktree team-1-iap-deploy`, copy the untracked new
files in, re-apply the lost `config.py` edit, `git checkout app/main.py` + `rm`
the strays in `repo/`, then `EnterWorktree` and carry on — committing each task.

## Prevention — the case where YOU caused it: the prompt said "isolated" and nothing was

Everything above is recovery, and it only starts once damage shows. The variant that
costs the most is the one where **you** fanned agents out and believe they are already
isolated — so none of the triggers above ever prompts you to look.

**Prose in a dispatch prompt is not configuration.** The isolation comes from the tool
parameter — `isolation: "worktree"` on the Workflow/Agent call — and from nothing else.
A prompt opening *"You are in your OWN isolated git worktree"* creates no worktree. It
only makes every agent report as though it had one.

DoodleRun, 2026-08-07: four parallel implementation agents were launched with exactly
that sentence in their prompts and the parameter unset. All four shared one checkout.
What that produced, none of it an error:

- **One agent's first commit landed on a DIFFERENT agent's branch.** It noticed,
  restored that branch without touching the other agent's uncommitted work, and rebuilt
  its own work elsewhere — a chunk of its run spent on repair nobody asked for.
  Recognising that from the *other* side is
  [`subagent-bash-cd-wrong-worktree`](https://github.com/wan-huiyan/agent-traffic-control/blob/main/plugins/agent-traffic-control/skills/subagent-bash-cd-wrong-worktree/SKILL.md):
  the reported SHA is real and `git branch --contains <sha>` finds it on a sibling
  branch.
- **The ORCHESTRATING session's own worktree branch was switched out from under it
  mid-run** — the failure at the top of this page, aimed at the session that started
  the fan-out.

### Two checks, both cheap

**1. Before you fan out, read the tool CALL back — not the prompt.** Every
Workflow/Agent invocation in the batch needs `isolation: "worktree"` actually set.
[`dispatched-bash-agent-git-checkout-clobbers-uncommitted-edit`](https://github.com/wan-huiyan/agent-traffic-control/blob/main/plugins/agent-traffic-control/skills/dispatched-bash-agent-git-checkout-clobbers-uncommitted-edit/SKILL.md)
already names this remedy; the point here is that it is a **field**, and a field is easy
to describe in English and forget to set.

**2. Make every agent prove where it is, in its first 30 seconds.** Require this as the
agent's FIRST bash call, and require both values echoed back in its report:

```bash
git rev-parse --show-toplevel      # which checkout am I in?
git branch --show-current          # on which branch?
```

Two agents naming the same toplevel means one shared tree — visible before either has
written a line. Reports that all cite the same directory are the entire signal; you do
not need to wait for a symptom.

### The tell, once it is already running

**A number that is TRUE of something, but not of the branch you are measuring.** In that
fan-out, an agent measuring its own branch read `pytest docs` as **446**; on the branch
it was **445**. The extra test was real — another agent had committed it into the shared
tree minutes earlier. Nothing errored, nothing conflicted, and 446 looked exactly like a
number.

Same reconciliation failure as
[`verifying-subagent-in-your-live-worktree-measures-your-uncommitted-work`](https://github.com/wan-huiyan/agent-traffic-control/blob/main/plugins/agent-traffic-control/skills/verifying-subagent-in-your-live-worktree-measures-your-uncommitted-work/SKILL.md),
where an agent in a dirty tree reports the branch plus your uncommitted edits. So treat
any total that moves with no merge in between as a **location** question first — run
`git rev-parse --show-toplevel` in the agent that reported it — before hunting for what
changed.

## Notes

### Variant — a stale `index.lock` blocks BOTH concurrent sessions (v1.1.0)
Symptom: `git commit`/`git add` fails with `Unable to create '.git/.../index.lock': File exists.
Another git process seems to be running`. In a shared worktree this often is **not** an active git
op — it's an **orphaned lock** from an earlier commit that was killed (e.g. a session interrupted
mid-commit), and it blocks *every* session sharing the directory, including a parallel one that's
sitting in a retry loop waiting for the lock to clear (so nobody makes progress). Diagnose stale vs
active before removing:
- **Lock age**: `python3 -c "import os,time;p='.git/worktrees/<wt>/index.lock';print(round(time.time()-os.path.getmtime(p)))"` — a multi-minute-old, 0-byte lock is almost certainly orphaned.
- **No active git op**: `ps aux | grep -E '[g]it (commit|add|push|merge|rebase)'` returns nothing (a sibling's *polling shell loop* may appear, but that's not a git op holding the lock — its own args often reveal it's waiting on the same lock).
Then `rm -f` the lock and commit **specific paths** with a short retry guard (the sibling may grab
the freed lock first; loop 3–5× with a `sleep 2`). Removing it unblocks *both* sessions. Only remove
after both checks pass — deleting a lock held by a live git process corrupts the index.

- Prevention: when starting isolated feature work, create a worktree *first*
  (the `using-git-worktrees` skill). Shared-directory work is only safe for a
  single session.
- A native `EnterWorktree` tool can enter an already-created worktree by `path`.
- Nothing is permanently lost even if the other session commits your strays —
  file *content* survives; you can recover it. But it is messy; isolate early.

## References

- `using-git-worktrees` — create an isolated workspace up front.
- `git reflog` is the source of truth for "who switched the branch."
