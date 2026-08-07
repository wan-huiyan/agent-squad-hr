---
name: factcheck-subagent-needs-complete-sources
description: |
  When dispatching a subagent to fact-check or verify a document/report/claims
  against source material, hand it COMPLETE primary sources — never your own
  abridged summary or partial dump. Use when: (1) you are about to launch an
  Agent/Task subagent to "fact-check", "verify", "independently check",
  "stress-test", or "review the claims in" a document against sources;
  (2) you are assembling the source bundle or writing the prompt for that
  agent; (3) a verification subagent returns a verdict like "claim X is
  unsupported / appears in no source / looks fabricated" — before accepting it,
  check whether the gap is in a source YOU abridged. An agent fed a partial
  source reports confident FALSE-POSITIVE "unsupported" verdicts on exactly the
  regions you trimmed out. (4) you are FANNING OUT several verifiers, each
  scoped to a DIFFERENT SUBSET of sources matched to a doc section — a claim
  anchored to a source outside one verifier's slice gets false-flagged by that
  verifier even though every source is complete (see Variant).
author: Claude Code
version: 1.1.0
date: 2026-06-25
---

# Fact-check subagents need complete primary sources

## Problem

You dispatch a subagent to independently fact-check a document against its
sources. To save context or tokens, you pass the agent a summary or partial
dump of one source instead of the full original. The agent then reports a
**false positive**: "Claim X is unsupported — the term appears in no source."
The claim was actually fine; the supporting text was in the part of the source
you abridged away.

The failure is asymmetric and dangerous: a missing source region does not make
the agent say "I can't tell." It makes the agent confidently say "unsupported"
or "fabricated" — because absence-of-evidence reads as evidence-of-absence when
the agent believes it holds the complete source.

## Context / Trigger Conditions

- About to launch an Agent/Task subagent to "fact-check", "verify",
  "independently check", "stress-test", or "review the claims in" a document.
- Assembling the source bundle / writing the prompt for that agent.
- A verification subagent returns "claim X unsupported / appears nowhere /
  fabricated / not in any source" — especially for one specific claim while
  everything else verifies cleanly.

## Solution

**Prevention — when assembling the agent's sources:**

1. Pass the agent the COMPLETE primary source (full file, full document dump,
   full repo clone), not a hand-written summary of it. If a source is large,
   give it the real artifact and let the agent read what it needs — do not
   pre-digest.
2. If you genuinely must abridge, say so explicitly in the prompt: name which
   sources are partial and which sections were cut, and instruct the agent to
   mark any verdict touching those sections UNVERIFIABLE rather than INACCURATE.
3. Prefer pointing the agent at retrievable originals (a cloned repo, a file
   path, a document ID it can fetch itself) over your transcription of them.

**Response — when the agent flags a claim as unsupported:**

4. Before accepting an "unsupported / fabricated" verdict, read the agent's own
   report for hedges — a good agent will say "the dump I was given is partial"
   or "this section was not in my sources." That hedge is the tell.
5. Reconcile the flagged claim against the COMPLETE source yourself. If the
   supporting text is in a region you abridged, the verdict is a false
   positive — keep the original claim; do not "correct" the document.
6. Treat genuine errors and source-gap false positives separately: apply the
   real corrections, reject the false positive, and state plainly why each.

## Verification

After reconciling: every accepted correction traces to the agent finding a real
discrepancy against COMPLETE source text; every rejected flag traces to a
source region the agent never received. No document claim is changed on the
strength of a source the agent only saw partially.

## Example

A planning-review document was fact-checked by a dispatched subagent against
three sources: two cloned repos (complete) and a Google Doc supplied as a
hand-written Markdown dump. The dump reproduced one section verbatim but
abridged another. The agent verified almost everything, but flagged one
claim — "feature X is mentioned in the source" — as "X appears nowhere in any
source, likely fabricated." The agent honestly noted its dump was partial.
Checking the full Google Doc showed the abridged-out section did contain X. The
claim was correct; the false positive came entirely from the abridged dump. Fix
applied: the document claim stood, and the lesson was to attach the real
document next time, not a transcription.

## Variant — partitioned source sets across PARALLEL verifiers (fan-out)

A second, sneakier trigger: every source file is **complete**, but you fan out
N verifiers and give each one a **different subset** of sources (e.g. one
verifier per doc section, each handed only the sources that section draws on).
A claim that is **anchored to a source in a different verifier's slice** then
gets a confident FALSE-POSITIVE "unsupported / no basis in any source" from the
verifier whose slice excludes it — even though nothing was abridged. This is
common when the consolidated/summary doc reconciles numbers across *multiple*
analyses (e.g. a value from anchor-A re-used in a section the verifier only got
anchor-B sources for).

**Tells:** the flag says "appears nowhere" for a number you KNOW you sourced;
the flagged value is one that legitimately came from a *cross-cutting* or
*earlier-round* source (a prior sweep, a sibling night, a different anchor) that
this particular verifier wasn't handed.

**Mitigations (cheapest first):**
1. When the doc reconciles across rounds, give EVERY verifier the full
   provenance set for cross-cutting claims (or a shared "provenance index"),
   even if each verifier's deep-read is scoped to its section.
2. Tag load-bearing numbers in the doc with their source anchor inline, so a
   scoped verifier can see "this is from source X (not in my slice)" and mark it
   UNVERIFIABLE rather than INACCURATE.
3. On receipt: before deleting a flagged number, grep the FULL source set (not
   just that verifier's slice) for it. If it traces to an out-of-slice source,
   the verdict is a scope false-positive — keep the number, and *sharpen its
   provenance* in the doc (cite the anchor) rather than removing it.

The discriminator vs a real error: a real error means the number matches NO
source at any anchor; a scope false-positive means it matches a source the
verifier simply wasn't given.

## Notes

- A well-built verification agent self-flags incomplete sources. Read the
  agent's caveats, not just its verdicts.
- This is the subagent-dispatch analogue of "absence of evidence is not
  evidence of absence" — scoped to: the absence may be in YOUR source bundle,
  not the world.
- See also: `review-panel-pre-dispatch-claim-recheck` (re-derive the
  load-bearing claim before dispatching reviewers);
  `parallel-rewrite-with-claims-inventory-factcheck` (fact-check a rewrite
  against source DATA, not a derived inventory).

## Reference-only siblings in this toolkit

These carry `disable-model-invocation: true`. They never appear in the skill
listing and the Skill tool refuses them, so the only way in is to open the file
with Read when one of these matches what you are looking at.

- [`task-framing-claims-need-subagent-grep-verify`](../task-framing-claims-need-subagent-grep-verify/SKILL.md) — a writing subagent needs permission to grep and correct the framing you handed it
- [`design-subagent-with-plan-schema-executes-and-deploys-live-infra`](../design-subagent-with-plan-schema-executes-and-deploys-live-infra/SKILL.md) — an agent dispatched only to DECIDE went ahead and executed the plan against live infrastructure
- [`cjk-structured-llm-output-truncates-json-needs-2x-tokens`](../cjk-structured-llm-output-truncates-json-needs-2x-tokens/SKILL.md) — long Chinese/Japanese/Korean structured output truncates mid-JSON — budget about twice the tokens
