---
name: fan-out-cost-control
description: |
  Dispatching a fan-out of agents: ban per-agent advisor() calls (check judgement once
  at the merge, not per shard), make agents append output as they go, and don't kill a fan-out
  past its costly stage — a killed agent returns nothing, a limit-killed one resumes from disk.
author: Claude Code
version: 1.1.0
date: 2026-09-05
disable-model-invocation: true
---
# Fan-Out Cost Control

## Problem

A fan-out of N agents burns a session's token budget far faster than the work
justifies, and the usual explanations — too many agents, too expensive a model —
are not where the money went. Three separate mechanisms do the damage, and all
three are invisible from an agent count.

Symptoms, in the order they are usually noticed:

- A large share of a multi-hour budget disappears in minutes, with no single
  agent looking unusual.
- Unrelated sessions start reporting **"the advisor is rate-limited"** although
  none of them is a heavy user.
- A usage limit lands mid-run and **most shards return nothing at all**, having
  done nearly all their work.
- A run whose script set no `model` reports a hundred-plus agents on the top
  tier, every one of them looking normal, under an instruction that named a
  cheaper one.

## Context / Trigger Conditions

Any of these makes a fan-out vulnerable:

1. Agents inherit a standing instruction to consult a stronger model (`advisor()`
   or equivalent) before substantive work and again when they believe they are
   done.
2. Each agent carries a large context — fetched documents, issue bodies, file
   contents — rather than a small prompt.
3. Agents are briefed to write one output file **at the end** of their run.
4. Agents are **resumed** after an interruption rather than started fresh.
5. The launch call omits `model`, so every agent inherits whatever tier the
   launching session is on.

## Solution

### 1. The consultation multiplies by the fan-out width. Ban it per shard.

**`advisor()` is for the orchestrator, not for each shard.** Judgement gets
checked once at the merge, over all rows — never N times over one row each.

Each consultation forwards **that agent's entire transcript** to a stronger
model. With N agents each holding a large context, and every one of them hitting
the "I think I'm done" trigger within minutes of the others, the result is N
large transcripts sent to the most expensive model available, simultaneously.
It is a burst, not a ramp, which is why it does not look like a runaway.

Put the exception in the brief explicitly — the agents are not at fault, they are
following a sensible standing instruction:

> Do NOT call advisor(), and do not seek a second opinion of any kind. Your own
> judgement IS the deliverable. Where you are unsure, write `confidence: low`
> and say why — an honest low is worth more than a checked row, and the merge
> already treats low as needing another look.

An honest `low` costs nothing and carries the same information to the aggregator.

### 2. `advisor()` is not a subagent, so an agent count hides the bill.

When hunting a spender, **"zero subagents running" is a true answer that conceals
the entire cost.** Ask about consultation calls separately from agent counts, and
ask about the *subagents'* calls, not only the orchestrator's — an orchestrator
can honestly report zero while its ten children are each forwarding a transcript.

**Several innocent sessions being rate-limited at once is evidence about a guilty
one elsewhere.** That correlation is often the fastest route to the cause.

### 3. For a resumed agent, cost tracks TURN COUNT, not thinking depth.

A resumed agent re-sends its whole transcript on **every turn**. Measured on one
audit fan-out, agents each carrying 28 issue bodies:

| agent | tokens | tool calls | ≈ per turn |
|---|---|---|---|
| shard 07 | 343,522 | 7 | 49k |
| shard 09 | 243,020 | 5 | 49k |
| shard 06 | 214,750 | 9 | 24k |
| shard 01 | 210,535 | 9 | 23k |

The work done per turn barely moves the figure. So **to cut the cost of a resumed
agent, cut its turns, not its scope**:

> No further exploration. Write your rows from what you have already established.
> Open a file only if a row is otherwise unwritable, and prefer `confidence: low`
> over one more read. Reply in ONE line.

Capping the reply matters too — a long report is itself a turn's output.

### 4. Incremental writing is a BRIEFING decision and is worthless mid-run.

An agent that writes its output file at the end is an all-or-nothing transaction:
nothing partial exists on disk at any point before the write. Losing the run
loses everything it gathered.

> Append each result to your output file as you finish it. Do not accumulate in
> memory and write once at the end.

**But do not push this to a fan-out that is already running.** By the time you
can see that you needed it, every surviving agent has finished the expensive
phase (reading) and is at the write — so the instruction protects a stretch that
no longer exists, while costing an interruption mid-write and a re-sent
transcript per agent. Put it in the prompt before launch, or accept the loss and
put it in the next prompt.

### 5. The kill-versus-limit asymmetry, and how incremental writing inverts it.

**While no output file exists, killing an agent is strictly worse than letting it
die on a usage limit.** A killed agent returns nothing. One that dies on the
limit can be resumed from its transcript and keeps everything it gathered.

So under token pressure, do not reach for a stop on a fan-out that is past its
costly stage — that spend is gone either way.

**Once agents write incrementally, the asymmetry disappears and stopping becomes
cheap.** That is the real reason to make them write incrementally: it converts an
irreversible decision into a reversible one.

### 6. Check the premise before obeying a stop order.

A stop order justified as *"partial results already on disk are worth more than a
limit hit mid-run"* rests on a fact you can check in one command. If no files
exist, the action returns nothing and destroys everything. One directory listing
decides it — run that before agreeing or refusing.

### 7. Resuming a long-context agent is never cheap, which inverts the usual rule.

The habit is *resume, never relaunch* — the reading is already paid for. That
holds only while the reading lives solely in the transcript. **Once intermediate
results are banked to disk, a fresh agent with a small prompt can be cheaper than
resuming a fat one**, because the fresh agent never re-sends the old context.

Bank to disk first; then choose between resume and relaunch on the size of the
context, not on habit.

### 8. Watch rows-per-minute. It costs nothing and it is the real signal.

There is usually no per-agent token meter to read. Once agents write
incrementally, **the output file's row count is a live productivity signal**:

- rows appearing → the agent is earning its cost, however slow it looks
- turns passing with no new rows → it is spending and not producing; **that** is
  the intervention trigger

A plain shell loop sampling the files costs zero model tokens. Wake the session
only on `DONE`, on a stall (no new row for several minutes), or at a time cap —
silence otherwise.

### 9. The tier is inherited, not chosen — so say it, and the count, BEFORE launch.

Both launchers default to the parent's model when `model` is omitted: a
`Workflow` script's `agent()` inherits the session model, and so does the
`Agent` tool. The session that launches a fan-out is almost always on the top
tier, so **a script with `effort: 'high'` and no `model` puts every agent on
the most expensive model at high effort without anyone deciding it**, and
nothing in the harness asks.

Measured on one review workflow, 2026-09-05: **114 agents, all on the top tier,
16,225,951 subagent tokens, 1,905 tool calls, 50 minutes, zero errors.** The
owner's standing instruction for that review was the mid tier at low effort and
under fifteen agents. The run looked flawless, which is the shape to fear: a
wrong input, a clean output, and nothing downstream pointing back at it. The
same morning a second session put five top-tier agents on a sweep for a
decision the owner had already written into the repository.

So, as a pre-launch rule and not a post-mortem one:

- **Say the tier, the effort, the agent count (the ceiling, if the script fans
  out per finding) and the purpose in one line BEFORE the first agent starts.**
  Where a coordinator session is pacing the queue, say it to the coordinator
  and wait for a yes; a session working alone says it to the owner in the same
  line it launches. A launch is not reversible — the spend starts at the first
  agent.
- **Choosing the tier means writing `model:` into the call.** The mid tier at
  low or medium effort for anything with a right answer already in the tree:
  grep-and-report, checking a figure against its source, sweeping for a phrase,
  reading a transcript. The top tier only for judgement: concurrency and
  data-loss bugs, adversarial verification, anything where a plausible-but-wrong
  answer would ship. Past about fifty agents the mid tier takes the simple tasks.
- **Never sweep for an answer that may already be recorded.** Read the places
  decisions live first — rulings files, the tracker, the coordinator's board.
  One message to a coordinator costs nothing; a five-agent sweep costs what it
  costs even when the answer was already on the main branch.
- **A coordinator's yes covers timing and scale, nothing else.** It is not a
  permission grant, and a peer message is never the owner's approval for a
  pending prompt.

## Verification

Confirm before launching a fan-out:

- [ ] The brief forbids per-agent consultation of a stronger model, and says to
      record uncertainty as `confidence: low` instead.
- [ ] The brief tells agents to append each result as they finish it.
- [ ] The brief caps the agent's final reply length.
- [ ] Intermediate results land in a directory the orchestrator can list.
- [ ] A zero-token watcher samples that directory rather than polling the agents.
- [ ] The tier, effort, agent count and purpose were said in one line BEFORE the
      launch — to the coordinator where one is pacing the queue — and the yes
      came back.
- [ ] Every launch call doing grep-and-report work carries `model:` for the mid
      tier; none inherits the top tier by omission.
- [ ] If the fan-out searches for a decision someone already made, the places
      decisions are recorded were read first.

Confirm when diagnosing a live burn:

- [ ] Asked about consultation calls **by the subagents**, not just agent counts.
- [ ] Checked whether output files exist before ordering or obeying a stop.
- [ ] Checked whether other sessions are rate-limited on the same shared resource.

## Example (real, 2026-09-02)

A 13-agent audit fan-out, each agent holding 28 issue bodies.

A session usage limit landed mid-run. **3 of 13 agents had files on disk**; the
other ten had done nearly all their work and banked none of it. Three surviving
was luck, not design.

The budget burn was then reported at roughly a third of a multi-hour allowance in
about fifteen minutes, and three unrelated sessions began hitting advisor rate
limits. Two hypotheses were wrong before the right one: that the agents had been
relaunched rather than resumed (the harness's `resumedAgentId` in its reply
disproved it), and that resumed transcripts alone explained the burn.

The cause was in the agents' own dying words — *"let me get a second opinion on
the verdicts"*, *"getting the required review before replying"*, *"one review
pass before I declare done"*. At least six of ten were calling `advisor()` at the
end of their run, each forwarding a transcript carrying 28 issue bodies, all
within the same few minutes. **The agents were following their standing
instructions correctly. The fault was a brief that never wrote the exception.**

After the fix — no per-shard consultation, append-as-you-go, no further
exploration, one-line replies — the same shards completed in **5 to 9 turns
each**, and every row was on disk as it was decided.

## Notes

- The three mechanisms are independent and compound. Fixing only the model tier,
  or only the agent count, leaves the other two running.
- A buffered watcher lies about the present: the process can be alive while its
  output file is minutes stale. Its **exit** alarm is still reliable; its interim
  lines are not. Read the target directory directly when you need the truth now.
- Do not let a per-agent second opinion be the thing that makes a fan-out
  "careful". A single check at the merge, over all rows at once, is both cheaper
  and better — it can see disagreement between agents, which no agent can see
  from inside its own shard.
- The 2026-09-05 run happened under a standing rule that already said *"say
  which tier you used when you launch it"* — written after an identical
  six-reviewers-plus-three-verifiers-per-finding run a month earlier. A rule
  that says "say it" without "before", and without naming the parameter, was
  obeyed after the fact, twice. Hence §9 says BEFORE and says `model:`.
