---
name: subagent-reports-complete-but-pr-unmerged
description: |
  Catch the systematic gap between sub-agent "completed" status and the
  actual end state of a PR-merge orchestration task. Use when: (1) you've
  dispatched multiple parallel sub-agents (general-purpose or specialist)
  to open + review + merge PRs, (2) the parent receives `<task-notification>`
  with `status: completed` but the sub-agent's last action was waiting on
  CI, addressing a review finding, or pushing a rebased branch, (3) you're
  tempted to mark the parent task done based on the completion notification
  alone, (4) the parent has a TaskList tracking PR closure and you'd
  silently leave PRs OPEN. Root cause: sub-agents naturally terminate when
  they've kicked off the last asynchronous step (CI watcher, push command,
  reviewer dispatch), even if their brief required them to wait for that
  step's terminal state and then perform a follow-up (label, merge,
  delete-branch). The completion notification reflects sub-agent CONTEXT
  exhaustion, not orchestration COMPLETION. Observed 4/4 in one session.
  Fix: parent always runs a "verify PR state" check on each sub-agent
  completion — query `gh pr view <num>` for state/mergedAt/checks, finish
  the missing step (poll CI, add label, squash-merge, delete-branch) before
  marking the parent task done. Brief sub-agents to be more disciplined
  but DON'T trust them; treat sub-agent "completed" as "handed off to
  parent for finalization." Sister skills: `superpowers:subagent-driven-development`
  (workflow), `subagent-pre-existing-misattribution`,
  `subagent-bash-cd-wrong-worktree`.
author: Claude Code
version: 1.0.0
date: 2026-05-08
disable-model-invocation: true
---

# Sub-Agent Reports "Completed" While PR Is Still OPEN

## Problem

You dispatch 3-5 parallel sub-agents to open + review + merge PRs that close GitHub issues. Each agent's brief explicitly says "wait for green CI, add `auto-deploy` label, squash-merge, delete branch, verify issue auto-closes." The agents work, push PRs, then return `<task-notification status: completed>`.

Several of those PRs are still OPEN. CI was still in-progress when the agent terminated. Or a reviewer found a P1 and the agent fixed it but stopped before re-running CI. Or the agent post-rebased and pushed but didn't merge. The parent, reading "completed," marks its TaskList task done. Hours later you realize 3 of 5 PRs never landed.

This is **systematic**, not occasional. In one session (`scan-bugs-parallel`, 2026-05-08, this repo) **4 of 4** sub-agents stopped before final merge:

- Wave1-G PR #527: agent posted P1 review, then stopped. Parent had to dispatch a continuation agent to fix + merge.
- Wave1-E PR #528: agent's final summary "Now I'll continue with the rest of the workflow (CI, auto-deploy label, merge)" — but the message ended there. PR was OPEN with green CI. Parent merged.
- Wave2 PR #540: agent merged successfully on its own (the exception). But it had to mid-flight rebase, which exposed the timing fragility.
- Wave2 PR #544: agent stopped after pushing the post-rebase branch but before CI completed. Parent merged.

## Trigger Conditions

Apply this skill when:

- You've used `Agent` tool with `run_in_background: true` to launch sub-agents whose briefs include "open PR + review + merge" as a single unit of work.
- A `<task-notification status: completed>` arrives, and:
  - The summary mentions "waiting for CI" / "pytest still pending" / "watching merge".
  - The summary mentions "code review posted" without "merged".
  - The summary mentions "rebased" / "pushed" without "merge SHA".
- You have a TaskList row keyed to GitHub issue closure that you're about to mark `completed` purely on the basis of the sub-agent notification.
- You see a session-level total like "PRs merged: N" — and you got that count from sub-agent reports rather than `gh pr list --state merged`.

## Solution

### Step 1 — never trust completion alone; always verify

When a sub-agent reports completed for a PR-merge task, immediately:

```bash
gh pr view <num> --repo <owner>/<repo> \
    --json state,mergedAt,statusCheckRollup,labels,mergeable
```

Read it before updating any task or summarizing to the user.

### Step 2 — recognize the four common stopping points

| Stopping point | Sub-agent symptom | Parent recovery |
|---|---|---|
| CI in progress | Agent says "waiting for pytest" | `gh pr checks <num> --watch --interval 20`, then label + merge |
| Reviewer posted P0/P1 | Agent posted finding then stopped | Dispatch continuation agent OR fix inline; re-CI; re-review; merge |
| Post-rebase push, no merge | Agent's last step was force-push | Verify mergeable, watch CI, label, merge |
| Branch deletion failed | Agent merged but `--delete-branch` hit `gh-pr-merge-worktree-checkout-trap` | `gh api -X DELETE repos/.../git/refs/heads/<branch>` |

### Step 3 — finish the missing step in the parent

Don't dispatch yet another sub-agent for the trivial finalization. The parent has full GH CLI access; finishing one PR is 3 commands:

```bash
gh pr checks <num> --repo <owner>/<repo> --watch --interval 20 2>&1 | tail -10
gh pr edit <num>  --repo <owner>/<repo> --add-label auto-deploy   # if dashboard PR
gh pr merge <num> --repo <owner>/<repo> --squash --delete-branch
gh issue view <issue-num> --repo <owner>/<repo> --json state --jq '.state'
```

DO dispatch a continuation agent only if the missing step requires substantive work (e.g. addressing a P1 review finding that needs a real code change).

### Step 4 — brief future sub-agents more aggressively (but still verify)

Add this paragraph verbatim to PR-merge sub-agent briefs:

> **Do not declare completion until `gh pr view <num> --json state` returns `"MERGED"`** with a non-null `mergedAt`. If you've kicked off CI watching and your context is filling up, return a status report saying "CI in progress, parent please finalize" — don't return `completed`. If your context is exhausted, the parent will pick up; but DO NOT return success on a PR that's still OPEN.

This reduces but does not eliminate the gap. Always verify in the parent regardless.

### Step 5 — track PR state in the parent's TaskList description, not just status

Instead of:

```
Task #4: Wave 2 — B+C#515 bundle    [in_progress]
```

Use:

```
Task #4: Wave 2 — B+C#515 bundle    [in_progress]
description: Agent dispatched (id ac9dcb9d). Awaiting PR open. Will mark
completed only when `gh pr view <num> --json mergedAt` is non-null.
```

This forces explicit verification before status flip.

## Verification

End-of-session sanity check:

```bash
gh pr list --repo <owner>/<repo> --state merged --search "merged:>=$(date -v-1d -u +%Y-%m-%dT%H:%M:%SZ)" \
    --json number,mergedAt,title --jq '.[] | "\(.mergedAt) #\(.number) \(.title)"'
```

Cross-reference against your TaskList completed rows. Any row marked completed without a corresponding merged PR (or a documented externally-closed reason — e.g. parallel session merged it) is a false positive that needs investigation.

## Example: `scan-bugs-parallel` session (2026-05-08, `the-project-repo`)

Dispatched 4 sub-agents. All 4 returned `completed`. State at notification time:

- PR #527: OPEN, CI green, P1 review unaddressed → parent dispatched continuation agent.
- PR #528: OPEN, CI green, no label, not merged → parent labeled + merged.
- PR #540: MERGED (exception — sub-agent did finish).
- PR #544: OPEN, post-rebase, CI in-progress → parent watched CI + merged.

Without the verify-then-finish discipline, only #540 would have actually closed its issue. The session total would have been 1/4 instead of 4/4.

## Notes

- This is NOT a sub-agent quality issue — even well-briefed agents hit context limits or terminate after their last visible action. Treat it as a structural property of async sub-agent orchestration.
- The `Plan` skill's review checkpoints partially mitigate by forcing explicit handback; PR-merge sub-agents typically don't use Plan because their flow is linear.
- For very simple PRs (1-line copy fix, no review findings), agents are more likely to finish-and-merge cleanly. The failure rate climbs with: longer CI wait, more files, mid-flight rebases, review findings.
- The schliff-style "did the sub-agent ACTUALLY do what its brief said" verification mindset applies. "Completed" = brief executed; verify outcome separately.
- If you're orchestrating 5+ PR-merge sub-agents in one session, build a small parent-side polling loop: every N minutes, `gh pr list` and reconcile against TaskList. Don't rely on completion notifications alone.

## References

- Session log: `the-project-repo` 2026-05-08 (`scan-bugs-parallel`) — closed 8 issues across 6 PRs; 4/4 sub-agents stopped before final merge.
- Sister skill: `superpowers:subagent-driven-development` (workflow primer for sub-agent dispatch).
- Sister skill: `subagent-pre-existing-misattribution` (different gap class — wrong baseline classification, not premature completion).
- Sister skill: `subagent-bash-cd-wrong-worktree` (different gap class — wrong cwd).
