---
name: isolate-subagent-verification-from-live-worktree
description: |
  A verification / gate-running subagent you dispatched into YOUR OWN worktree silently
  measures the branch PLUS your uncommitted edits, and reports the mixture as the branch's
  result. Nothing is clobbered and nothing errors — the suite really ran, the counts are
  real, they are just counts of a tree nobody will ever merge. Use when: (1) you dispatched
  an agent to "run the gates" / "verify main" / "check the suites" and pointed it at the
  directory you are still editing or committing in; (2) an agent reports a total that does
  not match the same command run before or after it (a task/decision/test count that moved
  with no merge between); (3) an agent reports the working tree as modified with files it
  did not write, or says HEAD advanced under it mid-run; (4) you are about to write "all
  suites green at <sha>" on evidence gathered while your own edits were unstaged. Fix:
  a verifying agent needs a checkout nobody else writes to — `git worktree add --detach
  /tmp/<name> <sha>` in the agent's own prompt, or finish and push your commits first.
  Distinct from dispatched-bash-agent-git-checkout-clobbers-uncommitted-edit (the agent
  DESTROYS your edit), concurrent-session-checkout-clobbers-shared-worktree (someone else
  flips the branch), and subagent-read-stale-worktree-needs-head-pin (the agent reads the
  WRONG worktree — here it reads the RIGHT one, in a dirty state).
author: Claude Code
version: 1.0.0
date: 2026-08-05
disable-model-invocation: true
---

# A verifying agent in your live worktree measures your uncommitted work

## Problem

You dispatch a subagent to verify a merge: *"run the four suites and the validator against
`main`, report the numbers."* You point it at the worktree you are working in, because that
is where the venv is symlinked and the tooling is set up.

Then you keep working — editing, staging, committing, merging PRs.

**The agent's gate run measures the branch plus whatever is in your working tree at that
instant.** There is no clobber, no error, and nothing looks wrong: the suites really execute,
the numbers it reports are real numbers, and it prints them with a commit SHA next to them.
They are simply counts of a tree that exists only on your disk and will never be merged.

The report then becomes the session's evidence — pasted into a PR body, a handoff, a tracker
card — as "verified green at `<sha>`".

## Why this is worse than the clobber cases

The sibling failures in this collection are loud once you look:

- `dispatched-bash-agent-git-checkout-clobbers-uncommitted-edit` — your edit vanishes.
- `concurrent-session-checkout-clobbers-shared-worktree` — the branch changes under you.
- `subagent-read-stale-worktree-needs-head-pin` — the agent's cited lines contradict yours.

Here **nothing contradicts anything**. The only signal is a total that does not reconcile
with the same command run at a different moment — and totals move for legitimate reasons all
day in a repo with parallel sessions, so the delta reads as normal churn.

## Context / trigger conditions

- You dispatched an agent to "verify", "run the gates", "confirm main is green", or "check
  the suite counts", and its prompt named a worktree path you are also using.
- An agent's reported total disagrees with your own run of the same command, with no merge
  in between to explain it.
- An agent mentions, in passing, that the working tree was modified with files it did not
  write, or that `HEAD` moved mid-run.
- A `git status` in the agent's transcript is non-empty when you expected a clean tree.
- You are about to publish "verified at `<sha>`" using numbers gathered while you had
  unstaged edits.

## Worked example (2026-08-05)

A session merging a run of PRs dispatched a verification agent into its own worktree while it
carried on drafting. The agent later reported:

> `CLAUDE.md` in the worktree showed as modified with 65 lines I did not write, and shortly
> after the worktree's detached HEAD advanced on its own. My first gate run was silently
> measuring main *plus* an uncommitted foreign change.

It caught this **only** because a validator count moved `150 → 152` between two runs it
expected to match — and it recovered by checking the commit out in a throwaway worktree and
re-measuring there. Had the counts happened to be stable across those two moments, the
contaminated numbers would have shipped as the session's verification evidence.

## The fix

**Give a verifying agent a checkout nobody else writes to.** Put it in the agent's prompt, not
in your own head:

```bash
# in the AGENT's prompt — its own tree, pinned to an explicit commit
git worktree add --detach /tmp/verify-<slug> <sha-or-origin/main>
cd /tmp/verify-<slug>
ln -sfn /path/to/repo/.venv .venv        # or whatever the tooling needs
# ... run the gates here ...
git worktree remove --force /tmp/verify-<slug>
```

Then either of these, as the situation allows:

- **Pin the commit.** Pass the SHA you want verified and have the agent assert it:
  `git rev-parse HEAD` must equal it before any suite runs.
- **Or finish first.** Commit and push everything, then dispatch. A verifying agent and an
  author working the same tree is the collision; sequencing removes it.

**Require the agent to prove the tree was clean.** Its report must include `git status --short`
output (empty) and `git rev-parse HEAD` alongside every count. A number without those two is
not evidence about a branch — it is evidence about a moment on somebody's disk.

## Detection after the fact

If you suspect a contaminated run, you do not need to reason about it — re-measure:

```bash
git worktree add --detach /tmp/recheck <sha>
cd /tmp/recheck && <the gate commands>
git worktree remove --force /tmp/recheck
```

If the numbers differ from the agent's, the agent's were of your working tree. Republish the
clean ones and say which report was superseded — a corrected number in a PR body is cheap; a
wrong one quoted onward by a tracker card is not.

## Related

- `dispatched-bash-agent-git-checkout-clobbers-uncommitted-edit` — the destructive cousin.
- `subagent-read-stale-worktree-needs-head-pin` — wrong worktree rather than dirty worktree.
- `concurrent-session-checkout-clobbers-shared-worktree` — the branch moves under you.
- `worktree-outer-ls-mistaken-for-main-state` — reading outside any worktree at all.
