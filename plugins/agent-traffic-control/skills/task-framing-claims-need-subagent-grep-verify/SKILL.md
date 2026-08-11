---
name: task-framing-claims-need-subagent-grep-verify
description: |
  When dispatching a sub-agent (Agent / Task) to WRITE content that
  cross-references existing code paths, explicitly grant + expect grep-driven
  correction of the dispatcher's task-framing claims. Use when:
  (1) your prompt to a sub-agent asserts facts about what an existing
  codebase contains ("X is NOT in v6.1", "Y is already implemented at
  module Z", "feature F handles case G");
  (2) the sub-agent will produce a document, analysis, or design that
  consumers will treat as authoritative;
  (3) the sub-agent has Read/Grep/Glob access to the code being claimed
  about.
  Without an explicit "verify these claims + tag corrections" instruction,
  a sub-agent will either (a) faithfully reproduce the dispatcher's wrong
  claim, or (b) silently substitute its own view without flagging the
  contradiction — both leave the dispatcher with a doc that LOOKS right
  but is stale. Companion to `factcheck-subagent-needs-complete-sources`
  (which covers feeding fact-check agents complete sources) — this skill
  covers the INVERSION: telling write-content agents they can correct
  YOU.
author: Claude Code
version: 1.0.1
date: 2026-08-04
disable-model-invocation: true
---

# Task-framing claims need sub-agent grep-verify

## Problem

You dispatch a sub-agent to write content (analysis doc, design doc,
implementation plan, code review summary) that needs to cross-reference
existing code paths. To give the sub-agent a head start, you assert facts
in the prompt about what's currently in the codebase:

- "Feature X is NOT in v6.1's training pipeline; the v7 implication is to
  add it as a categorical feature"
- "Module Y already implements caching at line ~120"
- "The current handler doesn't support multipart uploads"

If any of those framing claims are wrong, the sub-agent has two failure
modes — both bad:

1. **Faithful reproduction.** The sub-agent treats your prompt as ground
   truth, doesn't grep to verify, and produces a doc with the wrong
   premise baked in. Downstream readers can't tell the doc was based on
   a faulty premise.

2. **Silent substitution.** The sub-agent greps, finds you wrong, and
   quietly substitutes its own (correct) view — but doesn't flag the
   contradiction. You think your prompt was correct because the doc
   reads sensibly; the discrepancy with your mental model never surfaces.

The fix is ~3 lines of prompt: explicitly grant the sub-agent permission
to verify and correct your task-framing claims, and tell it to TAG any
corrections so the contradiction is visible.

## Context / Trigger Conditions

This skill applies when you're about to launch an Agent / Task subagent
to produce written content AND any of these are true:

- Your prompt contains specific factual claims about what an existing
  codebase contains: "X is not in module Y", "function Z handles case W",
  "feature F is already implemented at file:line N"
- Your prompt provides a numbered list of candidate features / changes /
  implications where each item depends on a "what currently exists" claim
- The sub-agent's output is going to be cited later as authoritative
  ("see analysis doc §3" or "per the design plan, X is needed")
- The sub-agent has Read / Grep / Glob access to the code being claimed
  about (i.e., it CAN verify — it just won't unless told to)

If none of these are true (sub-agent is doing pure exploration, or it has
no code access, or output is throwaway scratch work), this skill doesn't
apply.

## Solution

Add an explicit verify-and-tag block to the sub-agent prompt. Three
mandatory elements:

### 1. Grant correction permission explicitly

State that the sub-agent is *expected* to find errors in your framing:

> "The task-framing claims below describe what I believe v6.1 currently
> contains. I haven't grep-confirmed every one. **Verify each against
> the source before relying on it; if you find a contradiction, proceed
> with the corrected version.**"

Without the explicit grant, even capable sub-agents default to deference.

### 2. Specify the grep target

Don't make the sub-agent hunt for which file to verify against. Name the
canonical source(s):

> "Verify against: `<analytics_pkg>/dataform/v10_feature_matrix_<analytics_pkg>.sqlx`
> + `<feature_pkg>/pipeline_stage.py` + `cr_scoring_serve_v6/`.
> Use grep / Read; do not rely on documentation alone."

### 3. Require a visible tag for corrections

Tagging is what surfaces the contradiction back to you:

> "For each finding, tag it `[VERIFIED]` (matches my framing) or
> `[Contradicts task framing]` (you found my claim wrong — proceed with
> your corrected version and explain the discrepancy in 1-2 sentences)
> or `[NEEDS-VERIFICATION]` (you couldn't grep-confirm but the claim is
> plausible). Cite file:line for `[VERIFIED]` items."

The tag is structural feedback. Without it, corrections silently merge
into the doc body and you never learn your framing was wrong.

## Verification

After the sub-agent returns, scan its output for `[Contradicts task
framing]` tags. If any appear:

1. Read the sub-agent's explanation of what your claim got wrong.
2. Either: accept the correction and update any downstream documents
   that referenced the wrong claim; OR push back if you have stronger
   evidence the sub-agent missed something (rare).
3. Update your own mental model. The next time you brief a sub-agent on
   the same topic, your framing should be correct.

If you see no `[Contradicts task framing]` tags and the deliverable feels
suspiciously confident on a topic where you weren't sure: spot-check 2-3
`[VERIFIED]` citations by greping the cited file:line yourself. If those
resolve, trust the rest.

## Example

Bad sub-agent prompt (no correction permission):

```
Write docs/analysis/foo.md covering 8 v7 retrain implications:
1. doc-eligibility / has_required_doc — NOT in v6.1, candidate add
2. segment_type — NOT in v6.1 feature set, candidate add
3. region_status — needs derivation, candidate add
... etc
```

Good sub-agent prompt (S217's actual flow):

```
Write docs/analysis/foo.md covering 8 v7 retrain implications.

The 8 findings below come from a fact-check panel against the canonical
sheet. I have NOT grep-confirmed every claim about what v6.1 currently
contains. Verify each against `<analytics_pkg>/dataform/v10_feature_matrix_
<analytics_pkg>.sqlx` + `<feature_pkg>/pipeline_stage.py` +
`cr_scoring_serve_v6/`. For each finding, tag it [VERIFIED]
or [Contradicts task framing] or [NEEDS-VERIFICATION] with file:line
evidence. If you find me wrong, proceed with the corrected version and
explain the discrepancy in 1-2 sentences.

1. doc-eligibility / has_required_doc — NOT in v6.1, candidate add
2. segment_type — NOT in v6.1 feature set, candidate add
... etc
```

S217 outcome: sub-agent grep-verified all 8 findings. Two came back
`[Contradicts task framing]`:

> Finding 2 (segment_type): "NOT in v6.1" was wrong — `app_record_type`
> IS already a feature in v6.1 at lines 226/769/1039. The v7 implication
> is vocabulary pinning post-2026-04-17 model promotion, NOT adding.

> Finding 5 (region_status): "needs derivation" implied absence — it
> IS already pulled at line 585 into `crm_derived_features`
> and surfaced at line 1267. The v7 question is grain semantics + lead-
> stage proxy quality, not whether to add.

Without the correction-permission grant, both findings would have shipped
as "add this feature to v7" — wrong recommendation, would have shown up
as embarrassing in v7 design review.

## Notes

**Why explicit grant is needed.** Modern sub-agents are trained to be
helpful and to follow dispatcher instructions. When the dispatcher's
framing is factually wrong but plausibly stated, the default is to
faithfully reproduce. The explicit "verify + correct + tag" instruction
overrides the default-deference.

**Why tagging matters more than correcting.** Without tags, a sub-agent
that silently corrects your framing produces a doc that LOOKS like it
agreed with your prompt — but in reality your prompt was wrong AND you
never learned it was wrong. The next session you'll repeat the same wrong
framing. Tags break the cycle.

**Where this is most valuable.** High-leverage analysis docs, design
plans, code-review summaries, anything that downstream consumers will
cite as authoritative. Lower-value where the sub-agent is doing pure
exploration with no claim-to-fact.

**Related failure modes that this skill does NOT cover:**

- `factcheck-subagent-needs-complete-sources` — about giving fact-check
  sub-agents complete sources (not the inversion this skill covers)
- `subagent-pre-existing-misattribution` — about attributing pre-existing
  issues to sub-agent work (different blame-direction)
- `agent-review-panel-stale-cite-verification` — about reviewers verifying
  their cites are not stale (different scope: reviewer self-check, not
  dispatcher claim correction)

**Skill activation heuristic.** Before writing an Agent / Task prompt
that includes "X is not in Y" or "Z is already implemented at W" type
claims, ask: would I bet my next deliverable that this is currently
true in the codebase? If no — add the verify-and-tag block.

## References

- S217 worked example: PR #963 (`the-project-repo`),
  `docs/analysis/2026-05-27-s216-findings-for-v7.md` — sub-agent
  caught 2 of 8 task-framing errors via grep-verify against
  `v10_feature_matrix_<analytics_pkg>.sqlx`.
- Companion skill: `factcheck-subagent-needs-complete-sources` (covers
  feeding fact-check agents complete sources — different direction)
- Project lesson: `~/.claude/projects/.../memory/lessons.md` #129 (the
  S217 origin write-up)
