---
name: credit-stall-mid-orchestration-revive-collision
description: |
  Recover gracefully when an Anthropic credit/billing failure stalls multiple in-flight
  parallel subagents mid-orchestration, then later resolves. Use when: (1) you've
  dispatched 2+ parallel subagents (Task tool with `run_in_background: true`) and a
  credit/billing issue, MCP outage, or other transient harness failure has frozen them,
  (2) the user reports the issue is now resolved and asks you to continue, (3) you're
  about to relaunch "resume" agents to pick up where stalled originals left off.
  Defends against the silent-revive trap: when API access is restored, ORIGINAL stalled
  subagents can auto-resume from where they froze and continue working IN PARALLEL with
  any "resume" agents you dispatch — leading to two agents racing on the same branch /
  PR / files, duplicate review comments, or one agent overwriting the other's work.
  Captures the diagnostic recipe (JSONL mtime + worktree-state inspection, NOT just
  agent status) and the safe resume pattern (state-aware briefs that detect current
  state and pivot to value-add if originals already recovered).
  Sister skill to `subagent-reports-complete-but-pr-unmerged` (different gap: completed
  status vs unmerged PR) and `anthropic-credit-balance-error-vs-app-bug` (different
  layer: diagnosing fake vs real credit errors, not recovering from real ones).
author: Claude Code
version: 1.1.0
date: 2026-05-08
disable-model-invocation: true
---

# Credit-stall mid-orchestration: revive-collision recovery

## Problem

You're orchestrating N parallel subagents (Task tool with `run_in_background: true`),
each working on independent tracks (e.g., one PR per track). Mid-run, an Anthropic
billing/credit failure or other transient harness outage hits — all in-flight subagents
freeze simultaneously. The user fixes billing, reports back, and asks you to continue.

**The trap:** stalled subagents are NOT dead — they're suspended at the harness layer.
When API access is restored, the harness can auto-resume them from the exact tool-call
boundary they froze on. If you naively relaunch "resume" agents to pick up where you
think the originals stopped, you end up with TWO agents racing on:

- The same git branch (one commits + pushes, the other rebases on top of stale state)
- The same PR (duplicate review comments, conflicting label changes)
- The same files (one Edit lands, then the other Edit overwrites)

Symptoms when this happens: PR has two "no issues found" review comments, force-push
storms as both agents rebase, agent A reports "PR already merged" while agent B is
still polling CI for that same PR.

**Severity ladder** (observed in S156, 2026-05-08, all three originals revived ~2hr
post-stall):

1. **Best case (Track A original)**: revives mid-implementation, notices the merged
   PR via subsequent harness signals, sends a status update, terminates. Resume agent
   had pivoted to value-add (PR #571) under a state-aware brief. **No debris.**
2. **Middle case (Track C original)**: revives, runs `git diff origin/main HEAD --
   <files>`, finds zero diff on feature files, recommends "do not file PR / delete
   branch", terminates. **No PR debris**, just a status-report task-notification.
3. **Worst case (Track D original)**: revives, FILES a full duplicate PR against the
   already-merged branch (recreating the deleted remote branch via push), THEN runs
   its diff check, detects the collision, posts a "close as superseded" comment to
   its own duplicate PR, terminates. **Debris: 1 open PR + recreated remote branch
   → orchestrator must close + delete.**

The original agent's behavior on revive is non-uniform because it depends on which
tool-call boundary the harness froze it at. If frozen pre-implementation, it does
the safe thing. If frozen post-push-pre-PR, it files a duplicate PR before any
sanity check fires.

## Context / Trigger Conditions

ALL of the following:

1. You dispatched 2+ parallel subagents in the same session
2. A `<task-notification>` storm of `completed` events stopped or stayed silent for
   significantly longer than each agent's typical heartbeat — OR the user reports
   billing / credit / connection errors mid-session
3. The user has confirmed the underlying issue is resolved ("credit issue is fixed",
   "I added more credits", "API access restored")
4. You're about to do ONE of:
   - Send a follow-up message to a stalled agent
   - Launch a "resume" agent for a stalled task
   - Take over the work in the main thread

The probability of revive-collision rises with the number of parallel agents and the
duration of the stall. Single-agent sessions usually don't hit this — the harness
either resumes the one agent or doesn't.

## Solution

### Step 1 — Diagnose the actual stall state per agent (BEFORE relaunching)

Don't trust "no completion notification" alone. Check three signals per stalled agent:

**A. JSONL transcript mtime** — proves whether the agent is making any moves at all:

```bash
# The output_file in the task-notification is a symlink. Use -L to follow.
stat -f "%Sm  %z bytes  %N" -L /private/tmp/claude-PID/...task-id.output
```

If mtime hasn't advanced in >5 min AND the file size hasn't grown, the agent is stalled
at the harness layer (no API responses landing). If mtime is fresh (<2 min ago), the
agent is alive and you should NOT launch a resume — wait for it.

**B. Worktree state** — proves what the agent had finished before stalling:

```bash
cd <worktree-path>
git log --oneline origin/main..HEAD     # any commits made?
git status -sb                          # any uncommitted modifications?
git ls-remote origin <branch-name>      # was the branch pushed?
```

This tells you the **last visible side effect** the agent achieved. Possibilities:

| Worktree state                                 | Agent had reached            | Resume strategy                  |
|------------------------------------------------|------------------------------|----------------------------------|
| Clean, no commits, no remote branch            | Just started reading         | Restart from scratch             |
| Modified files, no commits                     | Mid-implementation           | Resume with WIP-state brief      |
| Committed locally, not pushed                  | Code done, no PR yet         | Resume with "push + open PR"     |
| Committed + pushed, no PR                      | Pushed but no PR             | Resume with "open PR + merge"    |
| PR opened, OPEN state                          | PR opened, in CI/review      | Don't relaunch — verify yourself |
| PR MERGED                                      | All done                     | Don't relaunch — declare victory |

**C. PR state via gh CLI** — proves the externally-visible end state:

```bash
gh pr list --repo <repo> --state all --search "head:<branch>" \
  --json number,state,mergedAt,mergeCommit
```

A MERGED state trumps everything else: the original agent finished. Never launch a
resume on a MERGED branch — at best you'll do redundant work; at worst you'll add a
fixup commit to a deleted branch.

### Step 2 — Write state-aware resume briefs

If you decide to relaunch, the resume brief MUST:

1. **State the verified current state explicitly** ("Branch has 1 commit; pushed; no
   PR opened yet" — not "agent stalled mid-run")
2. **Tell the agent to verify state on entry** before doing anything
3. **Authorize pivoting to value-add work** if the original has already finished
   ("If you discover PR is already merged, do not redo the work; instead, look for
   complementary cleanup such as test re-enablement, tracker finalization, or
   follow-up issue filing")
4. **Explicitly say: do NOT force-push if the branch already has a PR** — let the
   original agent (which may revive) own the branch

### Step 3 — Anticipate revive collision; design for it

When you launch a resume agent, ALSO assume the original will revive in parallel.
Concretely:

- **Don't launch the resume on the same branch** if the original might still hold it.
  Cut a fresh branch named `resume/<original-branch>` if the work needs to be done
  out-of-band.
- **If the original revives mid-stream and reports completion**, the resume agent
  should detect this (via `gh pr view` or `git log origin/main`) and gracefully
  pivot — that's why Step 2's pivot authorization matters.
- **Watch for two-review-comment patterns** on the PR after merge — that's
  diagnostic evidence the collision happened. Not actually broken, just noisy.
- **Watch for duplicate PRs filed against already-merged branches** — original
  agent revives at a post-push-pre-PR tool-call boundary, recreates the deleted
  remote branch via `git push`, files a fresh duplicate PR, THEN runs its diff
  check and self-reports "close as superseded". Orchestrator must:
  ```bash
  gh pr close <duplicate#> --comment "Closing as superseded — PR #<canonical> shipped this. <link to credit-stall skill>."
  gh api -X DELETE repos/<owner>/<repo>/git/refs/heads/<branch-name>
  ```
- **You cannot reliably kill originals in flight.** The harness doesn't expose a
  clean "TaskStop a stalled agent" path that survives revival. Accept that
  originals will run to completion or budget exhaustion, and design resume briefs
  + post-merge cleanup to absorb the noise.

### Step 4 — When in doubt, take over in the main thread

If only 1-2 tracks remain and the work is simple (e.g., merge an already-green PR,
verify a deploy), do it in the main orchestrator thread. Don't burn a fresh subagent
budget waiting on `gh pr checks --watch` polling.

## Verification

After dispatching resume briefs:

```bash
# Confirm only one agent is making progress on each branch
for branch in feat/track-A feat/track-B feat/track-C; do
  echo "=== $branch ==="
  gh pr list --repo <repo> --state all --search "head:$branch" \
    --json number,state,headRefName,updatedAt --jq '.[] | {number, state, updatedAt}'
done

# Check for force-push storms (revive collision symptom)
gh pr view <PR#> --repo <repo> --json commits --jq '.commits | length'
# >5 force-pushes in a few minutes = collision smell
```

After all PRs merge, check for the dual-review-comment fingerprint:

```bash
gh pr view <PR#> --repo <repo> --comments | grep -c "No issues found"
# 2 = revive collision happened on review pass
```

Also check for late-filed duplicate PRs ~1-3hr after the canonical PR merged:

```bash
gh pr list --repo <repo> --state open \
  --json number,title,headRefName,createdAt --jq '.[] | select(.title | contains("<keyword from canonical PR>"))'
# Any open PR with the same title pattern as a recently-merged canonical = duplicate
```

## Example

S156 4-track orchestration on the project repo (2026-05-08):

1. Dispatched 3 parallel subagents (A, B, D) at 16:30; D agent merged ~16:50.
2. Credit-balance issue hit at ~17:01 — agents A and C froze. JSONL mtimes stopped
   advancing (verified via `stat -f "%Sm" -L`). User flagged the issue.
3. User confirmed credit fix at ~17:10. Diagnosed each worktree:
   - A had 6 modified files, 0 commits, behind 6 → mid-implementation
   - C had clean tree, 0 commits → just started
   - D had 1 commit, pushed, no PR → "open PR + merge" state
4. Dispatched 3 state-aware resume briefs.
5. **A's original agent revived at ~17:00 and merged PR #566 at 16:40 UTC** (before
   resume agent picked up the worktree). A's resume agent, via the state-aware brief,
   detected this on entry (`git log origin/main` showed merge), pivoted to value-add
   work: re-enabled `test_monitor_template.py` (closes #473), filed tracker
   finalization PR #571, manually closed #473.
6. C and D resume agents proceeded normally — their originals had not revived (C
   had done nothing pre-stall; D's original was paused at "open PR" step which the
   resume completed).
7. Final state: all 4 tracks shipped, 5 PRs merged, no work duplicated, no force-push
   storms. The dual-agent collision on Track A produced no harm because the resume
   brief authorized pivoting.

## Notes

- The harness behavior is "resume from last tool-call boundary, not restart". This
  is generally an asset (you don't lose progress) but creates the collision risk.
- This pattern is NOT specific to credit issues — same dynamic applies to any
  transient harness outage (MCP server unreachable, network blip, hook failure).
  Generalize trigger condition to "any cause of subagent stall that later resolves".
- The `<task-notification>` system can deliver a flood of `completed` events from a
  zombie agent doing zero-tool-use polling cycles after its main work is done. Don't
  interpret these as forward progress — check JSONL mtime + git state.
- If the orchestrator's own context is at risk of compaction, prefer "take over in
  main thread" (Step 4) over launching more subagents.
- Worktree dirty state with `UU` (both-modified, unmerged) markers is a normal step
  in `merge-conflict-generated-files` flow (Steps 3–4 resolve the generator source
  and discard the stale outputs; Step 5 regenerates and stages them) — don't
  mistake it for a stall, the agent is mid-rebase.

## References

- Sister skill: `subagent-reports-complete-but-pr-unmerged` (parent receives
  `status: completed` but PR isn't merged — different gap, complementary recovery)
- Sister skill: `anthropic-credit-balance-error-vs-app-bug` (diagnose fake-vs-real
  credit errors at write-time; this skill picks up after the credit issue is real
  and resolved)
- Related skill: `using-git-worktrees` (the substrate that makes parallel tracks
  isolatable in the first place)
- Related skill: `superpowers:dispatching-parallel-agents` (when to choose parallel dispatch in
  the first place — informs how many tracks to risk a stall on)
