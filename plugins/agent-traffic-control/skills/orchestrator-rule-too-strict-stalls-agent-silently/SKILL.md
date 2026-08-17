---
name: orchestrator-rule-too-strict-stalls-agent-silently
description: |
  A safety rule you wrote into an agent's brief can be so strict that its
  precondition never holds — and the agent then does exactly the right thing,
  which is nothing, for as long as you leave it running. Nothing errors, nothing
  goes red, and the agent's own status reads as work in progress, so the stall is
  invisible from every surface you would normally check. Use when: (1) an agent
  has been running a long time with no product and no failure; (2) you gave an
  agent a guard phrased over the WHOLE repo, org or fleet — "only when nothing
  else is running", "only when the queue is empty", "only when no other session
  holds a lock" — in an environment that is never quiet; (3) you are wondering
  why nothing has merged, shipped or landed and no check is failing; (4) you are
  about to write a precondition into a brief and want it scoped so it can
  actually be satisfied. The fix is to scope every guard to the OBJECT the agent
  is acting on, not to global quiet: for a lander, the branch's own head is
  finished-green, the PR is BEHIND, and no run is in progress ON THAT BRANCH. The
  general form is a question to add to your own routine — ask each stalled agent
  whether one of YOUR rules is what is blocking it.
author: Claude Code
version: 1.0.0
date: 2026-08-17
disable-model-invocation: true
---

# Your own rule is the blocker, and it fails silently

## Problem

You write a guard into an agent's brief to stop it doing something dangerous. The
guard is correct in spirit and its precondition is scoped too wide, so in a busy
environment it never holds.

The agent obeys. It checks the precondition, finds it unmet, waits, checks again. It
is behaving exactly as instructed and it produces nothing.

**Every surface that would normally tell you says the wrong thing:**

| Surface | What it shows | What it means |
|---|---|---|
| the agent's status | running | it is running |
| CI | green / nothing new | nothing was pushed |
| the PR list | open, no new activity | nobody merged anything |
| the agent's own notes | "waiting for the safe window" | the window will never open |

There is no error to find, and a correctly-waiting agent is indistinguishable from a
busy one. This is what makes an over-strict rule more expensive than a wrong one: a
wrong rule usually breaks something and tells you.

**The observed cost:** a landing agent was told that `gh pr update-branch` was safe
only when **nothing was running repo-wide**. In a repo with several lanes pushing all
night, that is never true. The agent waited correctly and shipped nothing **for an
hour**. Nothing went red. It was found by asking, out of band, why nothing had
merged — not by any signal the system produced.

## Context / Trigger Conditions

Any of these:

- An agent has been alive for a long stretch with **no product and no failure** —
  no commits, no pushes, no PR state changes, and nothing red anywhere.
- A brief you wrote contains a precondition quantified over everything: *"when
  nothing else is running"*, *"when the queue is empty"*, *"when no other session is
  active"*, *"once all checks everywhere are done"*.
- You are asking "why has nothing merged?" and every check you run comes back clean.
- You are **writing** a guard right now, and its subject is the environment rather
  than the object the agent is acting on. That is the moment this is cheapest.

**Not for:** an agent burning budget on a polling loop — that one is loud, produces a
stream of no-op notifications, and is
[`subagent-external-wait-orchestrator-takeover`](../subagent-external-wait-orchestrator-takeover/SKILL.md).
The failure here is the opposite: **silence**, and no tokens spent at all.

## Solution

### 1. Scope every guard to the object, not to the environment

The rule is one substitution: replace *"when nothing is running"* with *"when nothing
is running **on this thing**"*. The danger a guard like this exists to prevent is
almost always local — you do not want to disturb **this branch's** in-flight run, and
another lane's run on another branch was never the hazard.

**The concrete case — when is `gh pr update-branch` safe on a PR?** All three, and
all three are about that one branch:

```bash
PR=123
BRANCH=$(gh pr view "$PR" --json headRefName -q .headRefName)

# 1. The branch's CURRENT head is finished and green — not "a run passed once".
gh pr checks "$PR"                       # every check has a conclusion, all pass

# 2. The PR is actually behind its base — otherwise there is nothing to update.
gh pr view "$PR" --json mergeStateStatus -q .mergeStateStatus   # BEHIND

# 3. No run is in progress ON THAT BRANCH. Other branches are irrelevant.
gh run list --branch "$BRANCH" --status in_progress --json databaseId -q 'length'
gh run list --branch "$BRANCH" --status queued      --json databaseId -q 'length'
# both zero → safe to update-branch
```

The repo-wide version of check 3 — `gh run list --status in_progress` with no
`--branch` filter — is the rule that stalls. It is the *same command* minus one flag,
which is exactly why it is easy to write and hard to spot afterwards.

### 2. Before you dispatch, ask whether the precondition can ever be true

For each guard in the brief, answer two questions in writing:

- **How often is this true, in the environment this agent will actually run in?**
  If the honest answer is "rarely" or "I don't know", it is a stall waiting to happen.
- **What does the agent do when it is not true — wait, skip, or report?** A guard with
  no stated else-branch defaults to waiting, which is the silent option.

Prefer **report** over **wait** in any brief that will run unattended:

```
If the safe window has not opened after 10 minutes, STOP waiting and report:
which condition is unmet, what you measured, and the PR you would have acted on.
Do not keep waiting silently.
```

That single instruction converts the entire failure mode into a message.

### 3. Add the question to your own routine

The general form, and the part worth keeping even if you never touch a landing lane:

> **Ask each agent whether one of YOUR OWN rules is what is blocking it.**

The agent almost always knows. It has the brief in front of it and it can name the
clause. But it will not volunteer it — from inside the agent, obeying an instruction
is not a problem to report, it is the job. So the information only surfaces if you
ask for it by name:

```
Status check: are you blocked? If yes, quote the exact sentence from your brief
that is blocking you, say what you measured, and say what you would do if that
sentence were removed.
```

Ask this of every long-running agent that has produced nothing, before you go looking
for a bug in anything else.

## Verification

While a fleet is running, this is the two-minute sweep:

```bash
# Agents alive a long time with nothing to show for it
#   → for each, ask the blocked-by-my-own-rule question above.

# And check the fleet-level fact that the stall hides:
gh pr list --json number,title,mergeStateStatus,updatedAt \
  --jq '.[] | select(.mergeStateStatus == "BEHIND")'
```

After rescoping a guard:

- The precondition is quantified over a named object (a branch, a PR, a file), and the
  command that checks it carries the filter that makes it so — `--branch`, `--label`,
  a path.
- The brief states what happens when the precondition is not met, and it is not
  "wait indefinitely".
- You have re-read the guard asking "when is this true?", not "is this safe?".

## Example (real, this run)

A landing agent's brief carried this guard, in good faith:

> Only run `gh pr update-branch` when nothing is running in the repo.

It was written to prevent a branch update from cancelling or invalidating an in-flight
CI run. The intent was right. The scope was the whole repo, and the repo had several
lanes pushing continuously, so the condition never held.

The agent checked, waited, checked, waited. **An hour with no merge.** No failure, no
red check, no error message, and a status that read as work in progress the entire
time. The discovery path was a human question — "why hasn't anything merged?" — which
is not a monitoring strategy.

Rewritten per-branch, the same guard admits the same safety and actually opens:
finished-green on the branch's current head, `mergeStateStatus: BEHIND`, and zero
in-progress or queued runs **on that branch**. Other lanes' runs stopped being the
agent's business, because they never were.

## Notes

- **This is not an argument for weaker guards.** The rewritten rule is not more
  permissive about the hazard it was written for; it is the same rule with the right
  subject. A guard that never opens protects nothing, because the work does not stop
  happening — it moves to whoever is not obeying the guard.
- **The pairing worth knowing:** an over-strict rule stalls, and an ambiguous rule
  burns budget. *"Arm auto-merge and wait"* was read as *"poll until merged"* by five
  agents in one night — the loud twin of this failure, covered in
  [`subagent-external-wait-orchestrator-takeover`](../subagent-external-wait-orchestrator-takeover/SKILL.md)
  §*The instruction that causes this most often*.
- **A stall can also be the fleet's fault rather than one brief's.** If several PRs
  are BEHIND and none is landing, the guard may be fine and the inflow may be the
  problem — see
  [`merge-queue-thrash-stop-inflow-and-open-prs-as-drafts`](../merge-queue-thrash-stop-inflow-and-open-prs-as-drafts/SKILL.md).
  Check which one you have before rewriting anything: rescoping a guard that was not
  the blocker just removes a safety net.
- **An agent that refuses a rule and says why is doing you a favour.** The routine
  that surfaces this stall is the same routine that catches a bad instruction early —
  [`agent-refusal-with-evidence-beats-literal-compliance`](../agent-refusal-with-evidence-beats-literal-compliance/SKILL.md).

## References

- [`subagent-external-wait-orchestrator-takeover`](../subagent-external-wait-orchestrator-takeover/SKILL.md)
  — the loud failure: an agent that polls instead of stalling
- [`merge-queue-thrash-stop-inflow-and-open-prs-as-drafts`](../merge-queue-thrash-stop-inflow-and-open-prs-as-drafts/SKILL.md)
  — when nothing lands and no single brief is at fault
- [`agent-refusal-with-evidence-beats-literal-compliance`](../agent-refusal-with-evidence-beats-literal-compliance/SKILL.md)
  — authorising the agent to say your instruction is wrong, with the evidence
- [`subagent-reports-complete-but-pr-unmerged`](../subagent-reports-complete-but-pr-unmerged/SKILL.md)
  — the other gap between an agent's status and what actually landed
- [`gh pr update-branch`](https://cli.github.com/manual/gh_pr_update-branch) and
  [`gh run list`](https://cli.github.com/manual/gh_run_list) — the `--branch` filter is
  the whole difference between the rule that opens and the rule that does not
