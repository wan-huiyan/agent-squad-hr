---
name: workflow-agent-unreachable-mid-flight-check-output-not-brief
description: |
  An agent's brief is frozen at the moment you dispatch it, and whether you can
  correct it later is decided by WHICH DISPATCH MECHANISM you used, not by how
  urgent the correction is. A subagent spawned directly can be sent a message: it
  reads the correction and keeps everything it has already worked out. An agent
  running inside a workflow has no address — correcting it means stopping the
  workflow, editing its script, and resuming by run id, with completed phases
  replaying from cache. Use when: (1) you are choosing between a workflow and a
  plain subagent for a task whose premise could move under it — a review verdict,
  a rule the user is still deciding, an issue that might be claimed; (2) a rule,
  standard or number changed after dispatch and you need to know who still holds
  the old one; (3) you find yourself routing a correction to a running lane
  through a shared task list, a file on disk or another agent because there is no
  channel to it; (4) an agent's report is fine on its own terms but was written
  against a premise that has since been overturned. Two rules: put a task that may
  need mid-flight correction in a plain subagent rather than a workflow, and for
  anything already dispatched, catch the stale rule ON THE WAY OUT — at output
  review — because inbound amendment reaches nobody who has already started.
author: Claude Code
version: 1.0.0
date: 2026-08-17
disable-model-invocation: true
---

# A workflow agent has no address — check its output, not its brief

## Problem

Two facts that are easy to learn separately and expensive to learn together:

1. **A brief is frozen at dispatch.** Whatever the agent was told is what it
   believes for its whole run. Nothing you learn afterwards reaches it.
2. **Whether you can unfreeze it is a property of the dispatch mechanism**, decided
   before you knew you would need to.

A subagent you spawned directly has an address. You can send it a message; it reads
the correction and carries on with everything it has already worked out — the files
it has read, the design it settled on, the half-written diff.

An agent running as a phase inside a workflow has no address. To change what it was
told you have to **stop the workflow, edit the script, and resume by run id**
(`resumeFromRunId` in the harness this was learned on). Phases that already completed
replay from cache, so the run is not lost — but the agent's own accumulated context
is, and every call signature downstream of your edit re-runs live.

So the moment you pick a dispatch mechanism, you have already decided whether that
task can be corrected. That decision is usually made on the wrong grounds: workflows
get chosen because the task has phases, not because the task's premise is stable.

**The observed cost:** a release lane accumulated **eleven blockers** that needed to
reach a sibling lane running as a workflow. There was no channel to it. Every one had
to be routed through the shared task list and picked up on the lane's next natural
read — slower than a message, and with no confirmation that the lane had read any of
them.

## Context / Trigger Conditions

Reach for this at either of two moments.

**Before dispatch**, when any of these hold:

- The task depends on a rule, standard, threshold or number that a reviewer, a user
  decision or a sibling lane could still change during the run.
- The task depends on state another session can move — an issue that may be claimed,
  a PR that may merge, a branch that may be deleted.
- You expect to want to narrow or widen the task's scope once you see early output.

**After dispatch**, when any of these hold:

- A rule changed and you cannot immediately name every agent still holding the old
  one.
- You are routing a correction to a running lane through a file, a task list or
  another agent — that workaround *is* the symptom.
- An agent returns a report that is internally consistent and answers a question
  nobody is asking any more.

**Not for:** an agent that has already died or stalled. Recovering one of those is
`parallel-impl-agent-dies-mid-stream-verify-working-tree` (its final message may be
the only copy of its product) and `credit-stall-mid-orchestration-revive-collision`
(suspended agents that revive and race your replacements). This skill is about an
agent that is alive, healthy, and wrong.

## Solution

### 1. Pick the channel at dispatch time, from one question

> **If the premise of this task moves in the next hour, do I need this agent to know?**

| Answer | Dispatch as | Because |
|---|---|---|
| Yes | a plain subagent | it has an address; a message corrects it and it keeps its context |
| No | a workflow phase is fine | you get the phase structure and cache replay, and give up the ability to talk to it |

Two things this question is **not**. It is not "is the task complicated" — a long,
mechanical, well-specified task is a fine workflow phase. And it is not "might the
agent fail" — failure is recoverable either way; being *quietly wrong for an hour* is
the thing a workflow phase makes expensive.

### 2. If it is already dispatched, catch it on the way OUT

Inbound amendment is only ever partial. A correction appended to a shared brief
reaches the agents that have not started yet and nobody else — and you usually cannot
tell which is which. So the reliable place to catch a stale rule is the **output
review**, where every agent's product passes through one gate you control.

Keep a short, dated list of rules that changed *during* the run, and check each
returning agent's product against it:

```
CHANGED MID-RUN — check every product that lands after this line
  <time>  <rule> corrected by review: <old value> → <new value>, on <which table/file>
  <time>  the naming rule for the ledger columns is snake_case, not camelCase
```

Then, for each returning product, ask **what the agent must have believed** rather
than what it says. The tell is that the report will not mention the old rule at all —
it will just have applied it.

### 3. Grep the artefact, not the brief — and know when you cannot

A changed rule is easy to sweep for when it survives as text. It is very hard when it
gets *compiled into a structure*: a schema field, a column type, a cron expression, a
retry count, an enum. The value is right there and no text search for the old wording
finds it, because the old wording never made it into the artefact.

**Measured this run:** a reviewer corrected a set of data-retention periods mid-run.
The authoring agent's brief still quoted the superseded wording, and it was on its way
to writing those periods into a schema — where a grep for the old phrasing would have
returned nothing and the wrong values would have looked like a deliberate design
choice. It was caught at output review, not by any inbound amendment.

So the output check has to be **value-level**, not text-level:

```bash
# not this — the old wording is not in the artefact
grep -rn "retain for 30 days" schema/

# this — the VALUES the rule produces, read back from what shipped
grep -rn "retention_days\|ttl\|expires_after" schema/ | sort -u
```

## Verification

Before dispatch:

- For every agent in the batch you can say, in one word, whether it is addressable.
- Any task whose premise is still moving is a subagent, not a workflow phase.

After a mid-run rule change:

- The changed-rules list has a line, with a timestamp.
- Every product that landed after that timestamp has been checked against it at
  **value** level, and you can name the file and value you checked, not just "looked
  fine".
- For any workflow phase already running under the old rule, you have decided
  explicitly between letting it finish and correcting the output, or stopping and
  resuming by run id — and written down which.

## Example (real, this run)

**The unreachable lane.** A release lane finished a review pass and produced eleven
blocking findings that belonged to a sibling lane. The sibling was a workflow. There
was no way to message it. Every finding went onto the shared task list instead and
waited to be read — which worked, and cost a round trip per finding plus the
uncertainty of not knowing whether any had been picked up. Had that lane been an
ordinary subagent, it would have been one message, and the lane would have kept its
context while acting on it.

**The frozen brief.** In the same run a reviewer corrected the data-retention periods.
An authoring agent had been dispatched before that correction and its brief still
quoted the old wording verbatim. Nothing about the agent was wrong — it was doing
exactly what it had been told, competently, and its report would have read as clean.
The correction was caught by reviewing its output against the changed-rules list. Had
it landed, the superseded periods would have been sitting inside a schema definition,
where no search for the old wording could find them.

## Notes

- **Cache replay is the workflow's real advantage, and it is what makes editing the
  script expensive.** Same script plus same arguments replays from cache; the first
  edited call and everything after it runs live. So a one-line edit near the top of a
  long workflow re-runs almost all of it.
- **"Amend the brief on disk" is the right fix for a different problem** — a long
  multi-phase run whose plan needs to evolve for agents that have *not started yet*.
  Its full treatment, including why editing the orchestration script is the wrong
  channel and why an addendum must name the facts it supersedes, is in
  `overnight-multi-issue-implementation` (published in
  [wan-huiyan/overnight-workflows](https://github.com/wan-huiyan/overnight-workflows),
  not in this plugin) under *"Amend a running orchestration through a file on disk,
  not the script"*. This skill is the half that section leaves open: the choice made
  at dispatch time, and what to do about the agents an addendum can never reach.
- **The same root at a different moment.**
  [`handoff-prompt-stale-user-hint-newer-state`](../handoff-prompt-stale-user-hint-newer-state/SKILL.md)
  is the case where the premise moved *before* you start and the user tells you so —
  pause and ask how scope should shift. Here the premise moves *after* dispatch and
  nobody tells the agent at all.
- **A message to a live subagent is not free either.** It costs the agent a turn and
  it can arrive mid-tool-call. It is still far cheaper than a stop-edit-resume cycle,
  and it is the only option that preserves what the agent already worked out.
- **Write the addressability into the dispatch record.** One column — "can I message
  this?" — next to each running agent turns a question you will have to re-derive
  under pressure into one you can read.

## References

- [`parallel-impl-agent-dies-mid-stream-verify-working-tree`](../parallel-impl-agent-dies-mid-stream-verify-working-tree/SKILL.md)
  — recovering an agent that died rather than one that is alive and wrong; covers the
  case where the dead agent's product was its final message
- [`credit-stall-mid-orchestration-revive-collision`](../credit-stall-mid-orchestration-revive-collision/SKILL.md)
  — stalled agents are suspended, not dead, and revive to race the replacements you
  launched
- [`handoff-prompt-stale-user-hint-newer-state`](../handoff-prompt-stale-user-hint-newer-state/SKILL.md)
  — the pre-execution version of the same root cause
- [`inherited-scope-doc-names-may-not-exist`](../inherited-scope-doc-names-may-not-exist/SKILL.md)
  — verify the names a prior session's scope doc cites before a long dispatch, for the
  same reason: a brief is believed for the whole run
- `overnight-multi-issue-implementation` — published in
  [wan-huiyan/overnight-workflows](https://github.com/wan-huiyan/overnight-workflows),
  not part of this plugin; its *"Amend a running orchestration through a file on disk"*
  section is the inbound-amendment half
