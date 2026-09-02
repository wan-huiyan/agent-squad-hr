---
name: agent-refusal-with-evidence-beats-literal-compliance
description: |
  A dispatched agent that does exactly what you asked can ship a defect you would
  have stopped yourself, because it can see something at the worksite that you
  could not see when you wrote the brief. Use when: (1) you are writing a brief
  that prescribes a specific fix, threshold, wording or value rather than the
  outcome you want; (2) an agent reports that it did not do what you asked and
  you are deciding whether that is insubordination or judgement; (3) an agent
  asserts "this is fine" or "not needed" with no measurement behind it; (4) you
  are reviewing overnight output and want to know which decisions were checked
  and which were assumed. Two halves, and both are needed: give the agent
  explicit permission to satisfy the INTENT of an instruction while refusing its
  letter, and REQUIRE the evidence with the refusal — what it built or measured,
  what that showed, what it did instead. Evidence is the whole difference between
  a refusal you can bank and one you have to re-litigate. Four agents correctly
  declined an instruction in a single run; one built the suggested fix, measured
  that it turned a silent safe refusal into a permanently red pipeline, and
  reverted it unpushed.
author: Claude Code
version: 1.0.0
date: 2026-08-17
disable-model-invocation: true
---

# Let agents refuse the letter of an instruction — and require the evidence

## Problem

You write a brief. Somewhere in it you prescribe not just the outcome but the *method*:
apply this fix, use this threshold, record this value, phrase it this way.

By the time the agent gets to that line it is standing somewhere you were not when you
wrote it. It has run the tests, read the surrounding code, seen the data. And sometimes
what it can see is that **your instruction, carried out exactly, makes things worse**.

A compliant agent does it anyway. That is the default, and it is a bad default: the
agent's report comes back clean, the instruction was followed, and the defect ships
with your name on the decision.

**In a single run, four agents correctly declined what they were asked to do.** Not one
of those was a failure. Every one was a defect caught at the last place it could still
be caught for free.

But refusal on its own is not the good outcome either. *"I didn't do that, it seemed
wrong"* is unbankable: you cannot act on it, you cannot review it, and you have to
re-derive the whole question yourself. What made these four useful was that each one
**showed its work** — it had built the thing, or measured it, and could say what it
found.

So the useful behaviour has two halves, and shipping only the first is worse than
shipping neither:

1. **Permission** to satisfy the intent of an instruction while refusing its letter.
2. **An evidence requirement** attached to that permission.

Half one alone produces an agent that argues. Both halves produce an agent whose
refusals you can bank without re-checking.

## Context / Trigger Conditions

**When writing a brief:**

- It prescribes a specific fix, patch, threshold, constant, wording or file rather than
  the property you want to hold.
- The work runs unattended, so nobody is there to be asked.
- The task involves a value that must be *measured* — a direction, a count, a duration,
  a rate — and you are supplying it from inference rather than measurement.

**When reading a report:**

- An agent says it did not do something you asked. Before treating that as a failure,
  look for the evidence — its presence or absence is the whole verdict.
- An agent asserts a judgement with no measurement: *"this is fine"*, *"not needed"*,
  *"already handled"*, *"the existing behaviour is correct"*. That is the shape to
  push back on, and it is the same shape whether the conclusion is do-it or don't.
- A change was built and then reverted, and you want to know whether that was
  thrashing or a controlled experiment.

**Not for:** an agent that invented evidence to justify a conclusion. Confident,
specific-looking numbers behind a strong claim need the 30-second check — that is
[`code-review-subagent-fabricates-specifics-to-inflate-severity`](../code-review-subagent-fabricates-specifics-to-inflate-severity/SKILL.md).
This skill raises the value of evidence; that one is why you still verify it.

## Solution

### 1. Put the permission in the brief, in the brief's own words

One paragraph, near the top, phrased so that it authorises a *specific* deviation
rather than general discretion:

```
If following an instruction in this brief literally would defeat the outcome it is
meant to achieve, do NOT follow it literally. Achieve the outcome instead, and say
what you did.

Your report must then contain, for that instruction:
  - what I asked for, quoted;
  - what you did instead;
  - the EVIDENCE — what you built, ran or measured, and what it showed;
  - what would have happened had you complied.

A refusal without evidence is not acceptable output. Neither is silent compliance
with an instruction you can see is wrong.
```

The last two lines are the working part. They make evidence the price of the permission,
so the permission cannot be used as cover for guessing.

### 2. Prefer outcome-shaped instructions to method-shaped ones

Most refusals become unnecessary if the brief states the property rather than the patch:

| Method-shaped (invites a bad literal read) | Outcome-shaped |
|---|---|
| "add a `continue` in that branch so it stops failing" | "the pipeline must not fail on this input; if the input is unusable, the run should end cleanly and say why" |
| "record the facing as north-east" | "record the measured facing; if it cannot be measured from the data, record that it is unknown" |
| "set the timeout to 30s" | "the step must not be killed by its own timeout under the observed load; state what you measured" |

You will still prescribe methods sometimes — you often know something the agent does
not. Keep doing it. Just expect the letter to be refused occasionally, and make that
cheap.

### 3. Read a refusal by its evidence, not by its confidence

Three questions, in order:

1. **Did it build or measure the thing?** A refusal that ran the experiment beats a
   refusal that reasoned about it, every time.
2. **Is the counterfactual stated?** "Had I done what you asked, X would have happened"
   — with X specific enough to check.
3. **Is the artefact clean?** An agent that built your suggested fix, measured it, and
   **reverted it unpushed** has left you nothing to undo. That is the mark of a
   controlled experiment rather than a change of mind mid-way.

If all three hold, bank it. If the first is missing, ask for the measurement — do not
argue about the conclusion.

## Verification

For a brief, before dispatch:

- The permission paragraph is present, and it names evidence as the price.
- You have re-read your own prescriptive lines and asked, for each: *am I stating the
  outcome, or guessing at the method?*

For a report, after:

- Every deviation from the brief is stated explicitly, not discovered by diffing.
- Every deviation carries a measurement, and you can name what was measured.
- Any value the brief supplied by inference — a direction, a rate, a duration — was
  either measured or explicitly recorded as unknown, and **not** silently written down
  as fact.
- Anything built as an experiment and rejected is gone from the branch, and the report
  says so.

## Example (real, this run)

**Four agents declined an instruction in one run. All four were right.** Two are worth
writing out because they are different shapes.

**A suggested fix that would have converted a safe failure into a permanent one.** An
agent was told to apply a specific fix to a pipeline. It built the fix, ran it, and
measured what it actually did: the pipeline's existing behaviour was a **silent safe
refusal** — it declined to proceed on bad input and stopped cleanly — and the suggested
fix converted that into a **permanently red pipeline** that would fail on every run
thereafter. The agent reverted the change **unpushed** and reported the measurement.
Nothing had to be undone, because nothing had been pushed; the whole experiment cost
one agent's time and produced a fact.

**A value inferred rather than measured.** An agent was asked to record a facing
direction that had been arrived at by inference, not measurement. It refused to record
it as data. It was right: the value would have entered the record indistinguishable
from measured values, and nothing downstream would ever have flagged it.

What both have in common is not the refusal. It is that each one arrived with the thing
that made it checkable: a run, a measurement, a counterfactual. An agent that had
simply said *"I don't think that's a good idea"* in either case would have produced a
conversation instead of an answer.

## Notes

- **This is not "let agents ignore the brief".** The permission is narrow and
  conditional: deviate only when the letter defeats the intent, and pay for the
  deviation with evidence. An agent that skips a step because it looked unnecessary is
  a different problem — see
  [`multi-agent-skill-silent-phase-compression`](../multi-agent-skill-silent-phase-compression/SKILL.md),
  where mandatory phases get rationalised away under context pressure.
- **The failure this replaces is silent.** A compliant agent that ships your bad
  instruction produces a clean report, so nothing in your review surfaces it. You only
  find out later, from the artefact.
- **Build-measure-revert is the strongest form and it is cheap.** It costs the agent
  the time to build something it will throw away, and it converts an argument into a
  measurement. Say so in the brief: *if you think an instruction is wrong, the best
  answer is to try it and measure it.*
- **"Unpushed" is doing real work in that sentence.** An experiment reverted before any
  push leaves no branch to clean up, no PR to close, and nothing for a sibling session
  to pick up by mistake.
- **Evidence is required, and still not self-certifying.** A specific-sounding number in
  a refusal deserves the same 30-second grep as a specific-sounding number in a BLOCKING
  review finding.

## References

- [`code-review-subagent-fabricates-specifics-to-inflate-severity`](../code-review-subagent-fabricates-specifics-to-inflate-severity/SKILL.md)
  — why evidence still gets verified: a model can invent coherent specifics to justify
  a strong call
- [`task-framing-claims-need-subagent-grep-verify`](../task-framing-claims-need-subagent-grep-verify/SKILL.md)
  — the dispatcher's own claims are the other thing an agent should check rather than
  accept
- [`factcheck-subagent-needs-complete-sources`](../factcheck-subagent-needs-complete-sources/SKILL.md)
  — a verifier given a partial source will confidently declare good work unsupported;
  check "unsupported" verdicts against what you trimmed
- [`orchestrator-rule-too-strict-stalls-agent-silently`](../orchestrator-rule-too-strict-stalls-agent-silently/SKILL.md)
  — the same permission from the other side: ask whether one of your own rules is what
  is blocking an agent
- [`multi-agent-skill-silent-phase-compression`](../multi-agent-skill-silent-phase-compression/SKILL.md)
  — deviation without evidence, which is the failure mode this skill must not become
