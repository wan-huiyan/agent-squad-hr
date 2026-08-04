---
name: workflow-parallel-fanout-omits-sequential-phases
description: |
  A sequential, stateful multi-agent process (adversarial DEBATE rounds, iterative
  reflect-then-rebut, staged consensus where step N reads step N-1's peers) silently
  VANISHES when the task is run under "ultracode" or authored as a Workflow — the run
  collapses to a parallel find→verify→judge with no reviewer-to-reviewer cross-talk.
  Use when: (1) you ran "review / red-team / debate X in ultracode mode" and the
  workflow shows only ~3 stages (review → verify → judge), no
  debate/reflection/blind-final; (2) you invoked a multi-phase SKILL (e.g.
  roundtable:agent-review-panel) but
  the execution was a parallel fan-out with no agents reading each other; (3) a skill
  whose spec MANDATES sequential phases produced a result with those phases absent and
  it is NOT context-compression (that's the sister skill
  multi-agent-skill-silent-phase-compression). Counter-intuitive root cause: the
  Workflow/ultracode engine is a PARALLEL
  fan-out engine (parallel()/pipeline(), agents never see each other) with no primitive
  for sequential cross-talk — so "run it as a workflow" structurally omits debate, and
  invoking a skill under ultracode-bias ≠ running the skill's protocol.
author: Claude Code
version: 1.0.1
date: 2026-08-04
disable-model-invocation: true
---

# Running a sequential multi-agent process as a Workflow silently drops its sequential phases

## Problem

A multi-agent process that depends on **sequential, stateful cross-talk** — adversarial
debate rounds, reflect-then-rebut, blind-final-after-debate, any "step N reads step N−1's
peer outputs and responds" — **silently disappears** when the task is executed under
*ultracode* or hand-authored as a `Workflow`. The result looks like a clean 3-stage
**review → verify → judge** with no reviewer-to-reviewer argument, and reads as complete.
The judge ends up doing alone the reconciliation the debate was supposed to surface.

## Context / Trigger Conditions

- You said "review / red-team / stress-test X **in ultracode**" and the `/workflows`
  view shows ~3 stages at most: independent review → verify → judge. No debate /
  reflection / blind-final.
- You invoked a multi-phase **skill** (e.g. `roundtable:agent-review-panel`, which
  *mandates* Phase 5 Debate / 6 Summarize / 7 Blind-Final) but the actual execution was
  a parallel fan-out — N independent agents, then a judge — with zero agents reading each
  other's output.
- A skill spec lists mandatory sequential phases, yet the run has them absent — **and**
  it's not the context-compression failure (full skill ran, mid-phases squeezed out under
  token pressure → that's the sister skill, see below).

## Root cause

The `Workflow` tool / ultracode is a **parallel fan-out engine**: `parallel()` and
`pipeline()` run agents that **never see each other**. There is **no primitive for
sequential cross-talk** (agents reading peers' outputs and responding across rounds). The
tool's own canonical review recipe is literally **"find → adversarially verify → judge"** —
debate is not in its vocabulary. Three consequences, by frequency (from a week-long audit
of `roundtable:agent-review-panel` usage across dozens of runs, where **nearly every run
had no debate**):

1. **Ultracode biases toward authoring a Workflow instead of invoking the sequential
   skill.** The workflow it writes is find→verify→judge; debate was never in it.
2. **Debate-less sister skills get auto-selected** for small / autonomous-multi-PR work
   (e.g. a "streamlined parallel panel, no debate, no judge" skill) — debate-free *by
   design*.
3. **"Invoking a skill" ≠ "running its protocol"** in an ultracode/workflow-biased
   session: the skill name appears in the transcript, but execution collapses to a
   parallel shape. (Audit: the skill was invoked on the order of a dozen times, ran its
   full protocol only a couple of times, and actually debated just once.)

This is **structurally distinct** from silent phase *compression*: there, the full skill
runs and mid-pipeline phases get dropped under orchestrator context-budget pressure; HERE
the protocol **never ran** — a parallel, debate-less mode ran in its place.

## Solution

**To get the sequential phases back:**

1. **Invoke the skill WITHOUT ultracode/workflow framing.** `/roundtable:agent-review-panel`
   in a non-ultracode turn, or *"run the FULL panel with adversarial debate rounds — do
   not streamline, do not run it as a workflow."* The sequential phases live in the
   **skill's own Agent-tool orchestration**, not the Workflow engine.
2. **If you DO want cross-talk inside a Workflow, author it explicitly.** It's the default
   *absence* of cross-talk, not an impossibility: make round 2 a `pipeline()`/`parallel()`
   stage whose prompts are **fed round 1's peer outputs** so each agent rebuts what the
   others said, then judge. (Proven: one audited run used `phases [Review, Debate,
   Audit+Verify, Judge]` and debated correctly.)
3. **Make absence loud.** Stamp a `[NO-DEBATE]` / `[NO-CROSS-TALK]` banner on the output
   when the sequential phase produced no state — so a flattened run announces itself
   instead of looking complete.

**The discriminator — when does this even matter?** Fan-out with no cross-talk is *correct*
when the sub-tasks are **independent** (classify N transcripts, review N unrelated files,
search N angles) — there's nothing to debate. Sequential debate earns its cost **only when
agents would genuinely change each other's verdicts**: security-vs-performance tradeoffs,
"is this P0 actually real", merge/ship go-no-go. Drop cross-talk freely for independent
work; protect it for adversarial-tradeoff work. (Ironically, an *audit* of this very
problem correctly ran as a no-debate fan-out — independent transcripts.)

## Verification

- After forcing the skill path: the transcript shows agents reading each other's findings
  and revising (Phase 5/6/7 state files, e.g. `state/reviewer_*_phase_5_round1.md`), not
  just N independent reviews → judge.
- The output names a debate/rebuttal step with actual position changes, not a single
  judge integration.

## Notes

- **Sister skill — different root cause, same symptom:**
  [`multi-agent-skill-silent-phase-compression`](../multi-agent-skill-silent-phase-compression/SKILL.md)
  covers the case where the FULL skill *did* run but mid-pipeline phases were silently
  compressed under orchestrator context-budget pressure. If the skill genuinely ran its
  protocol and phases still vanished → that skill. If a parallel/streamlined/workflow mode
  ran *instead of* the protocol → this skill.
- The audit that surfaced this: a multi-agent Workflow over about a week of real usage;
  finding written up (anonymized) in the review-panel tool's own `docs/analysis/`. The
  repo-side fix (loud `[NO-DEBATE]` banner) is tracked as an issue there.
- General principle beyond review panels: **any** skill/process whose value is sequential
  state (iterative refinement, negotiation, multi-round consensus) is at risk of being
  flattened when "run as a workflow." Audit the executed shape, not the invoked name.
