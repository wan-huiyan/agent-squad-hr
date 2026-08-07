---
name: pre-dispatch-agent-isolation-parameter-not-prompt
description: |
  Telling an agent in its prompt it has "your own isolated worktree" creates nothing — isolation
  is the dispatch call's `isolation: "worktree"` parameter. Before fanning out agents that will
  commit, read the CALL back and make each prove where it landed. Prevention, not cleanup.
author: Claude Code
version: 1.0.0
date: 2026-08-07
---
# Agent isolation is a parameter, not a sentence in the prompt

## Problem

You are about to fan out several agents that will each commit to their own branch. Your
prompt template opens with *"You are running in an isolated git worktree — changes you make
here do NOT affect other agents"*, so you dispatch and move on.

**That sentence creates nothing.** The worktree is created by the dispatch tool's
`isolation: "worktree"` parameter. With the parameter unset, every agent runs in the *same*
checkout — and every one of them reports back as though it were isolated, because you told it
it was.

Nothing errors. Git does not complain that four agents share a working tree; that is a
perfectly ordinary thing for a directory to be. The damage arrives as ordinary-looking
results: a commit on the wrong branch, a branch that changes under a session mid-run, a test
total that is off by one.

**Why this specific mistake keeps happening:** the isolation is a *field* in a tool call, and
a field is very easy to describe in English and forget to set. The prompt is the part you
write by hand and re-read; the parameters are the part you fill in once from a template. So
the belief that the agents are isolated is strongest precisely when it is false.

## Context / Trigger Conditions

Any one of these is enough — this is a cheap check, not a gated procedure:

- You are about to issue **2 or more** Agent / Workflow / Task calls in one batch, and the
  agents will run `git commit`, `git checkout`, `git rebase` or `git push`.
- Your dispatch prompt **asserts** isolation ("your own worktree", "changes here don't affect
  others") — that phrasing is the tell that you are relying on prose.
- You are reusing a prompt template or a plan document that was written for an earlier
  fan-out, where the parameters are not part of the text you copied.
- A single agent is being sent into a directory another session is live in. One agent is
  enough; "parallel" is not a precondition.

**Not for:** read-only agents that never write to the repo (a review pass, a grep audit).
Those have a different hazard — reading the wrong tree — which
`subagent-read-stale-worktree-needs-head-pin` covers.

## Solution

### 1. Read the CALL back, not the prompt

Before you send the batch, look at each invocation's parameters and confirm
`isolation: "worktree"` is actually set on every call whose agent will write. Not the prompt
body — the parameters.

If your dispatch tool has no such parameter, the equivalent is to create the worktree
yourself and pass its **absolute path** in, then have the agent `cd` there as step one:

```bash
git worktree add /abs/path/outside/repo/agent-<n> -b <branch-for-agent-n> origin/main
```

`using-git-worktrees` covers doing that safely. What does **not** work is any wording,
however emphatic, in the prompt.

### 2. Make every agent prove where it is, in its first 30 seconds

Require this as the agent's **first** bash call, and require both values echoed back in its
final report:

```bash
git rev-parse --show-toplevel      # which checkout am I in?
git branch --show-current          # on which branch?
```

Then read the reports as a set:

- **Two agents naming the same toplevel = one shared tree.** That is the entire signal, and
  it is available before either agent has written a line.
- An agent whose branch is not the one you assigned it is already in someone else's work.

This costs one line per agent and turns a silent condition into a visible one.

### 3. Know the tell, in case it is already running

**A number that is TRUE of something, but not of the branch you are measuring.** A total that
moves with no merge in between is a *location* question before it is a *what-changed*
question — run `git rev-parse --show-toplevel` in the agent that reported it before you go
hunting for the diff.

The reason this is the tell rather than an error message: in a shared checkout every number
an agent reports is a real measurement of a real tree. It is just not a measurement of the
tree that agent is supposed to be working on, and nothing about the number says so.

## Verification

Before the batch runs, all of:

- Every writing agent's call carries `isolation: "worktree"` (or an explicit, distinct
  worktree path).
- `git worktree list` after dispatch shows one entry per writing agent, on distinct branches.

After the first reports come back:

- The reported `--show-toplevel` values are **all distinct**, and none of them is the
  orchestrator's own checkout.
- The reported branch names match the assignment, one agent each.

## Example (real — DoodleRun, 2026-08-07)

Four parallel implementation agents were launched with *"You are in your OWN isolated git
worktree"* in their prompts and the `isolation` parameter unset. All four shared one checkout.
What that produced, none of it an error:

- **One agent's first commit landed on a DIFFERENT agent's branch.** It noticed, restored that
  branch without touching the other agent's uncommitted work, and rebuilt its own work
  elsewhere — a chunk of its run spent on repair nobody asked for.
- **The orchestrating session's own branch was switched out from under it mid-run.**
- **An agent measuring its own branch read `pytest docs` as 446 collected tests; on the branch
  it was 445.** The extra test was real — another agent had committed it into the shared tree
  minutes earlier. Nothing errored, nothing conflicted, and 446 looked exactly like a number.

Every one of those was recoverable, and each was recovered. The cost was the time, plus the
period in which a wrong count was being reasoned about as a right one.

## Notes

- **The prompt sentence is worth keeping** — it tells the agent what to assume and where to
  commit. It is just not the mechanism. Keep the sentence; set the parameter.
- **This is not the same check as "did the agent do its work in the right directory".** That
  is a per-agent cwd question (`subagent-bash-cd-wrong-worktree`). This is a
  *did-a-worktree-ever-exist* question, and it is answered once, before dispatch.
- **A shared checkout is not always wrong** — a single-writer fan-out where only the
  orchestrator commits is fine. The failure is the *belief* in isolation, not the sharing.

## References — what this looks like once it has already happened

These three are recovery skills. Each fires on a symptom, which is to say each fires after
the damage exists; that is why this one is filed separately.

- [`concurrent-session-checkout-clobbers-shared-worktree`](https://github.com/wan-huiyan/agent-traffic-control/blob/main/plugins/agent-traffic-control/skills/concurrent-session-checkout-clobbers-shared-worktree/SKILL.md)
  — a second session's `git checkout` flips the branch under your working tree and clobbers
  uncommitted work. Detection and recovery, from the victim's side.
- [`subagent-bash-cd-wrong-worktree`](https://github.com/wan-huiyan/agent-traffic-control/blob/main/plugins/agent-traffic-control/skills/subagent-bash-cd-wrong-worktree/SKILL.md)
  — the commit-on-a-sibling-branch case seen from the other end: the reported SHA is real and
  `git branch --contains <sha>` finds it on a branch that is not yours.
- [`verifying-subagent-in-your-live-worktree-measures-your-uncommitted-work`](https://github.com/wan-huiyan/agent-traffic-control/blob/main/plugins/agent-traffic-control/skills/verifying-subagent-in-your-live-worktree-measures-your-uncommitted-work/SKILL.md)
  — the same reconciliation failure with a different cause: an agent in a dirty tree reports
  the branch plus your uncommitted edits, as one number.

Adjacent, and about the destructive-git side rather than the isolation side:
[`dispatched-bash-agent-git-checkout-clobbers-uncommitted-edit`](https://github.com/wan-huiyan/agent-traffic-control/blob/main/plugins/agent-traffic-control/skills/dispatched-bash-agent-git-checkout-clobbers-uncommitted-edit/SKILL.md)
— it already names "give it its own worktree" as a remedy; this skill is the pre-flight that
checks you actually did.

## Reference-only siblings in this toolkit

These carry `disable-model-invocation: true`. They never appear in the skill
listing and the Skill tool refuses them, so the only way in is to open the file
with Read when one of these matches what you are looking at.

- [`subagent-driven-branch-ref-froze-stranded-commits`](../subagent-driven-branch-ref-froze-stranded-commits/SKILL.md) — "PR merged but half my work is missing" after one-subagent-per-task development
- [`subagent-reports-complete-but-pr-unmerged`](../subagent-reports-complete-but-pr-unmerged/SKILL.md) — a subagent reported the task complete and the PR is still open
- [`multi-agent-skill-silent-phase-compression`](../multi-agent-skill-silent-phase-compression/SKILL.md) — mandatory phases of a multi-agent skill silently vanished under context pressure
- [`multi-phase-skill-disk-reading-strategy`](../multi-phase-skill-disk-reading-strategy/SKILL.md) — late phases of a multi-phase skill fail silently because payloads went through the prompt, not disk
