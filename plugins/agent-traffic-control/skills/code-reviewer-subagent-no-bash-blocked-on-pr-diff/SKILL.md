---
name: code-reviewer-subagent-no-bash-blocked-on-pr-diff
description: |
  Code-review subagents are frequently provisioned WITHOUT a Bash tool, so they
  cannot run `gh pr diff`, `git diff`, or `git checkout` — and when you prompt
  them to "review PR #N, fetch the diff with gh pr diff" they return a BLOCKED
  report (no review performed), not findings. Use when: (1) dispatching
  feature-dev:code-reviewer / voltagent-* / Explore agents to review GitHub PRs
  or branches; (2) a review agent returns "I have no shell/gh/git tool" or "the
  PR sources are not in the working tree" or reviews `main` (which predates the
  PR) instead of the PR; (3) one reviewer in a parallel panel comes back BLOCKED
  while siblings succeeded. Fix: pre-generate per-base diffs to files + point the
  agent at materialized worktree paths, don't tell it to run gh/git.
author: Claude Code
version: 1.0.1
date: 2026-05-29
disable-model-invocation: true
---

# Code-reviewer subagents have no Bash — blocked when told to `gh pr diff`

## Problem

You dispatch a review-panel subagent (e.g. `feature-dev:code-reviewer`) to review
open GitHub PRs, with a prompt like "use `gh pr diff <N>` to get each PR's diff,
then review." The agent returns a **BLOCKED report** — no findings — explaining it
has no shell/`gh`/`git` tool and the PR source isn't in the working tree. Meanwhile
a sibling reviewer in the same panel may succeed (if it happened to find a
materialized worktree on disk). The blocked run is wasted compute and, worse, can
masquerade as "clean" if you don't read it carefully.

## Context / Trigger Conditions

- Dispatching `feature-dev:code-reviewer`, `voltagent-qa-sec:*`, `Explore`, or
  similar review/search agents against a **GitHub PR or a branch not checked out
  in the main working tree**.
- The agent's report says any of: "No shell / `gh` / `git` tool is exposed",
  "The PR sources are not in the working tree", "WebFetch returns 404 (private
  repo)", or it reviewed files on the **current branch (often `main`, which
  predates the PR)** instead of the PR's changes.
- In a parallel panel, **asymmetric outcomes** — some reviewers found the code,
  one came back blocked — because the successful ones discovered an existing
  worktree path and the blocked one looked in the main checkout.

## Root cause

These agents' toolsets exclude `Bash`. For example `feature-dev:code-reviewer` has
`Glob, Grep, LS, Read, NotebookRead, WebFetch, TodoWrite, WebSearch, KillShell,
BashOutput` — note **`KillShell`/`BashOutput` are present but `Bash` itself is
not**, so it can read a background shell's output but cannot *start* a command.
No `Bash` → no `gh pr diff`, no `git checkout <pr-branch>`, no `git diff`. `Read`
hits the filesystem directly, so the agent can only see whatever branch is
currently checked out in the working tree it lands in (the main repo checkout,
which predates the PR). Private repos also defeat the `WebFetch` fallback (404).

## Solution

Do the git/`gh` work in the orchestrator (which *does* have Bash) and hand the
agent **materialized source + pre-generated diffs**, never "run gh":

1. **Materialize each PR branch as a worktree** (or reuse existing ones):
   ```bash
   git worktree add /tmp/pr-<N> <pr-branch>
   ```
2. **Pre-generate each PR's scoped diff against its own base** to a file:
   ```bash
   git diff <base-branch>...<pr-branch> -- app/ tests/ > /tmp/diffs/pr<N>.diff
   ```
   (For a stacked PR, diff against its *own* base, not main, so the diff is scoped
   to that PR's changes only.)

   **Three dots, not two.** The agent cannot cross-check this against GitHub, so the
   file you hand it IS its ground truth — and GitHub's Files-changed tab is the
   merge-base diff. A 2-dot diff renders everything the base gained after the branch
   point as deletions the PR is not making, and a reviewer with no Bash will report
   those invented deletions as findings you then have to disprove.
3. **Prompt the agent with explicit paths**, and tell it up front it has no Bash:
   > "You do NOT have a Bash/git/gh tool — only Read/Grep/Glob. The code is
   > materialized at `/tmp/pr-<N>/`; the scoped diff is at `/tmp/diffs/pr<N>.diff`.
   > Read the diff first, then read surrounding source in the worktree. Do NOT
   > look in the main repo checkout — it predates this work."
4. **For anything the agent would want to run empirically** (a probe, the test
   suite), have it return a "WANTS EMPIRICAL CONFIRMATION" list with the exact
   command, and run those yourself in the orchestrator afterward.

## Verification

The agent returns actual findings citing real `file:line` from the worktree, not a
BLOCKED report or a review of unrelated `main` code. In a panel, all reviewers
produce symmetric, source-grounded output.

## Example

Session reviewing a stacked PR tail (#62/#63/#64): the "Correctness Hawk"
(`feature-dev:code-reviewer`) came back BLOCKED — it looked in the `main` checkout
(which predated the stack) and had no Bash to `git checkout` the branches. Two
sibling reviewers happened to find pre-existing `/private/tmp/s13-*` worktrees and
reviewed fine. Re-dispatching the Hawk with the three per-base diffs pre-written to
`/tmp/s13-diffs/` plus the worktree paths — and a "you have no Bash" preamble — it
then found a P0 in the async transaction logic. Net: one wasted agent run that a
correct first dispatch would have avoided.

## Notes

- **Read blocked reports carefully — BLOCKED ≠ CLEAN.** An agent that couldn't see
  the code is not a clean bill of health; don't let a panel's "no findings" be a
  silent blocked run.
- Some agents are even more restricted (no Write either) — see
  `voltagent-reviewer-no-write-tool` (have the orchestrator persist their inline
  output to files).
- For the per-base-diff scoping of stacked PRs and attaching reviews back to the
  right PR, see `stacked-pr-review-per-base-diff-and-attach`.
- The general-purpose / `claude` agent and `Agent` default DO have Bash; this gap
  is specific to the read-only review/search specialist agents. If you need the
  reviewer to run commands, either pick a Bash-capable agent type or pre-stage
  everything.

## See also

- `overnight-review-panel-blocked-reviewer-reads-as-clean` — the **overnight specialization**
  of this skill (published in `wan-huiyan/overnight-workflows`): in an unattended run a BLOCKED
  reviewer reads as CLEAN with no human to notice, so the bug ships by morning. This skill is the
  general tool-gap mechanism; that one adds the autonomy consequence + morning-synthesis rule.
- `stacked-pr-review-per-base-diff-and-attach` — scoping stacked-PR diffs per base
- `subagent-bash-cd-wrong-worktree` — Bash-capable agents landing in the wrong worktree
