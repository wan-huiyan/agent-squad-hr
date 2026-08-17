---
name: auto-merge-rearms-while-agent-live-kill-then-disarm-verify
description: |
  Disarming auto-merge on a PR whose agent is still running does not hold it —
  the agent re-arms within minutes and the PR merges, because arming is a step in
  the agent's brief and disarming is not an instruction to the agent at all. Use
  when: (1) you want to STOP a pull request from merging that an agent opened and
  armed, for review, for a rethink, or because it is landing into a queue you are
  trying to drain; (2) a PR you disarmed merged anyway; (3) you are telling agents
  which PRs are on hold and want the hold to be enforced rather than announced;
  (4) you are about to run `gh pr merge --disable-auto` and have not decided what
  to do about the agent. The order is KILL THE AGENT FIRST, THEN DISARM, THEN
  VERIFY the disarm by reading `autoMergeRequest` back — a disarm you did not read
  back is not a hold. The stronger form needs no ordering at all: convert the PR
  to a draft with `gh pr ready --undo`. A draft cannot merge whatever any agent
  does to it, so the hold survives an agent you missed, an agent that restarts,
  and an agent you did not know about.
author: Claude Code
version: 1.0.0
date: 2026-08-17
disable-model-invocation: true
---

# Auto-merge re-arms while its agent is live — kill, disarm, verify

## Problem

You want a pull request held. It has auto-merge armed, so you disarm it:

```bash
gh pr merge 123 --disable-auto
```

Minutes later it is merged.

The reason is not a race in GitHub. It is that **arming auto-merge is a step in the
agent's brief**, and your disarm was not addressed to the agent at all. The agent is
still alive, still working through its list, and one of its later steps — a retry, a
re-check, a "make sure the PR is armed before you finish" line — arms it again. From
the agent's point of view nothing unusual happened: it found the PR unarmed and armed
it, which is what it was told to do.

**This happened twice in one run.** Same PR, same disarm, same result. The second time
is the informative one: repeating the action that failed, faster, does not help, because
the mechanism is not timing.

The general shape is worth naming, because it recurs beyond auto-merge: **changing a
resource's state does not change the intent of a process that keeps re-asserting it.**
Any agent-set state — a label, an assignee, a branch protection exemption, a queued
merge — comes back if the agent that set it is still running.

## Context / Trigger Conditions

- You want a PR **not** to merge, and an agent opened it or is still working on it.
- A PR you disarmed is now `MERGED`, or `autoMergeRequest` is non-null again after you
  cleared it.
- You are publishing a hold — a "do not touch these PRs" list, a freeze, a review
  gate — that is enforced only by agents reading it and choosing to comply.
- You are about to disarm auto-merge and have not checked whether the PR's agent is
  still alive.

**Not for:** a PR that will not merge and you want it to. That is
[`gh-pr-merge-unstable-state-needs-auto-and-watch-branch-deletes`](../gh-pr-merge-unstable-state-needs-auto-and-watch-branch-deletes/SKILL.md)
— the opposite problem, with the opposite fix (`--auto`, not `--disable-auto`).

## Solution

### The strong form — convert it to a draft

A draft pull request **cannot be merged**. Not by `gh pr merge`, not by auto-merge, not
by an agent that re-arms it — GitHub refuses with `Pull Request is still a draft
(mergePullRequest)`. That refusal is a property of the PR, so it holds against an agent
you did not kill, an agent that restarted, and an agent you did not know existed:

```bash
gh pr ready 123 --undo                            # convert to draft — this IS the hold
gh pr view 123 --json isDraft,autoMergeRequest    # expect isDraft: true
```

Prefer this whenever the hold matters more than the PR's appearance. It is also the one
form that does not depend on you having correctly enumerated the agents.

**One trap comes with it, and it is already documented:** a cleanup routine that deletes
a head branch whenever the branch still *exists* — rather than when the PR actually
merged — will delete a held draft's branch and **close the PR**. Gate every branch
delete on `mergedAt != null`. Full treatment in
[`gh-pr-merge-unstable-state-needs-auto-and-watch-branch-deletes`](../gh-pr-merge-unstable-state-needs-auto-and-watch-branch-deletes/SKILL.md)
§*Fix Failure C*.

### The ordered form — kill, disarm, verify

If the PR must stay ready-for-review, the order is not optional:

```bash
PR=123

# 1. KILL THE AGENT FIRST. While it lives, everything below is advisory.
#    Identify it, stop it, and confirm it is stopped — a stop you did not confirm
#    is the same mistake one level up.

# 2. THEN disarm.
gh pr merge "$PR" --disable-auto

# 3. THEN verify, by reading the state back. A disarm you did not read back
#    is not a hold; it is a command you ran.
gh pr view "$PR" --json state,isDraft,autoMergeRequest,mergedAt
# expect: {"state":"OPEN","isDraft":false,"autoMergeRequest":null,"mergedAt":null}

# 4. And re-check after a few minutes. Re-arming is the failure; one read
#    immediately after your own command cannot see it.
```

Step 4 is the one people drop. The failure takes minutes, and the verification everyone
runs takes seconds.

### The hold list has to name what enforces it

If you are publishing a list of PRs on hold, write next to each one **what actually
stops it**, not just that it is on hold:

```
#123  held  — DRAFT (enforced by GitHub)
#124  held  — auto-merge disarmed, agent stopped 14:02, re-verified 14:11
#125  held  — announced only; no enforcement. Anything may merge this.
```

The third line is the honest one, and writing it is usually enough to make you go and
fix it.

## Verification

A hold is real when all of these are true, checked in this order:

1. **The agent is stopped**, and you confirmed the stop rather than issuing it.
2. `gh pr view <N> --json autoMergeRequest` returns `null`, **or**
   `isDraft` is `true`.
3. The same read, repeated **at least five minutes later**, still says so.
4. Nothing in your own tooling deletes head branches on existence rather than on
   `mergedAt != null` — that closes the PRs you are trying to protect.

Across a set of held PRs:

```bash
gh pr list --json number,isDraft,autoMergeRequest \
  --jq '.[] | select(.autoMergeRequest != null and .isDraft == false)
       | {number, WARNING: "armed and not a draft"}'
```

## Example (real, this run)

A pull request needed to be held. Auto-merge was armed, so `gh pr merge --disable-auto`
was run on it. **Within minutes it was armed again and it merged.** The PR's agent was
still live and arming was on its list.

The same thing was done a second time, with the same result. **Twice.** The lesson is
in the repetition: the second attempt was not slower or sloppier than the first — the
action simply does not do what it appears to do while the process that set the state is
still running.

What would have held it, with no ordering to get right and no agent enumeration to get
wrong: `gh pr ready --undo`. A draft cannot merge.

## Notes

- **A hold is a state, not a message.** Anything enforced by agents reading an
  instruction is a request. Anything enforced by GitHub refusing the operation is a
  hold. Prefer the second and say which one you have.
- **Kill order generalises.** For any state an agent asserts — a label, an assignee, a
  reviewer request, a queued merge — stop the asserter before you clear the state, or
  expect it back. The verification is the same: read it back, then read it back again
  later.
- **Do not "hold" a PR by deleting its branch.** It closes the PR and loses the review
  thread's context; recovering it means restoring the branch from `refs/pull/<N>/head`
  and reopening. See the sibling skill above.
- **Draft has a second, unrelated payoff** that makes it worth reaching for by default
  rather than only for holds: on a repo whose expensive workflows skip drafts, a draft
  PR's CI is dramatically cheaper. Measured in
  [`merge-queue-thrash-stop-inflow-and-open-prs-as-drafts`](../merge-queue-thrash-stop-inflow-and-open-prs-as-drafts/SKILL.md).
- **If you cannot find the agent, that is an answer.** Use the draft form. An
  enumeration you are unsure of is exactly the condition the ordered form fails under.

## References

- [`gh-pr-merge-unstable-state-needs-auto-and-watch-branch-deletes`](../gh-pr-merge-unstable-state-needs-auto-and-watch-branch-deletes/SKILL.md)
  — the inverse problem, plus the branch-delete-closes-a-draft trap this skill inherits
- [`merge-queue-thrash-stop-inflow-and-open-prs-as-drafts`](../merge-queue-thrash-stop-inflow-and-open-prs-as-drafts/SKILL.md)
  — draft-by-default as a CI-cost and queue-control lever rather than a hold
- [`subagent-reports-complete-but-pr-unmerged`](../subagent-reports-complete-but-pr-unmerged/SKILL.md)
  — the other direction of the same gap between what an agent reports and PR state
- [`gh pr ready`](https://cli.github.com/manual/gh_pr_ready) (`--undo` converts to
  draft) and [`gh pr merge`](https://cli.github.com/manual/gh_pr_merge)
  (`--disable-auto`)
