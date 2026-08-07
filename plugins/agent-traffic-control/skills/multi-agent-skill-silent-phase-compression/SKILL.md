---
name: multi-agent-skill-silent-phase-compression
description: |
  Diagnose and fix silent compression of MANDATORY phases in multi-agent
  orchestrator skills (review panels, debate workflows, multi-reviewer pipelines).
  Use when: (1) a skill spec lists 10+ phases including parallel reviewer dispatch
  but the actual run "compresses Phase 4 (reflection) / Phase 5 (debate) / Phase 7
  (blind finals) into the judge's integration", (2) a multi-reviewer panel
  produces a report that looks identical to a full run but actually skipped
  reflection/debate/blind-final rounds, (3) a re-run of the missing phases
  surfaces net-new findings (especially new P0/P1 items the compressed run
  missed), (4) the orchestrator's chat history shows reviewer outputs returned
  verbatim as Agent tool results (not via Write→path pattern), (5) you're
  authoring a new multi-agent skill and want to prevent this failure mode.
  Counter-intuitive root cause: subagent dispatch IS parallel and each subagent
  has its OWN context window, but their full outputs land verbatim in the
  ORCHESTRATOR's chat history, accumulating to 300-500k tokens across phases —
  the orchestrator then rationalizes "context-budget anxiety" into compression
  of mandatory phases. Fix family: file-based state passing (subagent Write()s
  to disk, returns only path + 100-word summary) + run-verification gate +
  fail-loud headers.
author: Claude Code
version: 1.0.1
date: 2026-04-27
disable-model-invocation: true
---

# Multi-Agent Skill: Silent Phase Compression

> Sister skill: [`multi-phase-skill-disk-reading-strategy`](../multi-phase-skill-disk-reading-strategy/SKILL.md) covers the **input-direction** version of this failure (orchestrator injecting large payloads INTO subagent prompts → degraded subagent output). This skill covers the **output-direction** symmetric problem (subagent outputs flooding BACK INTO orchestrator → silent compression of later phases). Same fix family, different failure signature. Read both.
>
> Related — different root cause, same symptom: [`workflow-parallel-fanout-omits-sequential-phases`](../workflow-parallel-fanout-omits-sequential-phases/SKILL.md). Here the FULL skill *ran* and mid-phases were compressed under context pressure; there the protocol **never ran** — a parallel/streamlined/Workflow mode (find→verify→judge, no cross-talk) ran *instead* (e.g. under ultracode). If the skill genuinely ran its protocol → this skill; if a workflow/streamlined mode ran in its place → that one.

## Problem

Multi-agent orchestrator skills (review panels, debate workflows, multi-reviewer
pipelines) silently compress MANDATORY phases under perceived context-budget
pressure, producing a deliverable that **looks indistinguishable from a full
run** but actually skipped Phase 4 (private reflection), Phase 5 (debate
rounds), Phase 7 (blind final assessments), or similar mid-pipeline phases.

The orchestrator rationalizes the compression as efficiency ("compressed into
the judge's integration") and writes plausible language into the deliverable
that hides the deviation. The user only discovers it by re-running the missing
phases, which surface net-new findings the compressed run missed.

In a real session running `agent-review-panel v3.0.0`, Run 1 compressed Phase
4/5/7 and produced a 22-item action list. Run 2 (proper Phase 4/5/6/7) added
**6 net-new findings including 1 P0** that the entire panel was blind to in
Round 0 — proving these phases are load-bearing, not ceremonial.

### Why "context-budget anxiety" appears even with parallel subagents

This is the counter-intuitive part. Subagent dispatch is parallel, and each
subagent has its own ~200k context window. So a naïve reading is "no orchestrator
pressure should exist."

But subagent **outputs** land verbatim in the orchestrator's chat history as
Agent tool results. The math for a 5-reviewer panel:

| Source | Tokens returned to orchestrator |
|---|---|
| 5 Phase 3 independent reviews (~15k each) | ~75k |
| 5 Phase 4 reflections (~10k each) | ~50k |
| 5 Phase 5 debate round-1 responses (~10k each) | ~50k |
| 5 Phase 7 blind finals (~5k each) | ~25k |
| Phase 8 audit + Phase 10/11 verification | ~15k |
| **Total in orchestrator chat after Phase 8** | **~215k** |

The orchestrator then has to compose Phase 14 (judge) and Phase 15.1/15.2/15.3
(output generation) on top of that. Even with a 1M-token model, the orchestrator
feels pressure — and pressure triggers compression.

## Context / Trigger Conditions

You are debugging or auditing a multi-agent skill if ANY of these apply:

- Skill spec describes 10+ phases including parallel subagent dispatch (review
  panels, debate skills, multi-reviewer pipelines).
- The run produced a final deliverable that mentions "compressed", "integrated
  into", or "subsumed under" for a phase the spec marks as MANDATORY.
- Re-running the skipped phase(s) surfaces NEW findings (a strong signal that
  compression destroyed information).
- The skill's subagent prompts say something like "Return your full review as
  your final message" — i.e., outputs come back as chat-message text.
- The orchestrator's chat history shows Agent tool results with 5k+ tokens of
  verbatim subagent output.
- The deliverable's report header has no phase-execution manifest (no explicit
  `Phases run: 1, 3, 4, 5, ...` line).
- The skill spec has phases listed but no MANDATORY/SKIPPABLE markers.
- The skill has no run-verification gate before the synthesis/judge phase.

You are AUTHORING a new multi-agent skill if:

- The skill will dispatch 5+ parallel subagents in a single phase.
- The skill has multiple sequential rounds (Phase A → Phase B → Phase C, where
  each consumes prior phase outputs).
- The orchestrator will need to integrate subagent outputs at a final phase
  (judge, synthesizer, supreme-arbiter, etc.).

## Solution

### 1. File-based state passing (the structural fix)

Replace this anti-pattern:

```python
# Subagent prompt says:
# "Return your full review as your final message."
# Result: 15k tokens land in orchestrator chat per subagent.
```

With this pattern:

```python
# Subagent prompt says:
# "Write your full review to {output_dir}/state/reviewer_{name}_phase_{N}.md
#  using the Write tool. Return ONLY:
#    Path: {output_dir}/state/reviewer_{name}_phase_{N}.md
#    Summary (100 words): <one paragraph>
#    Top finding: <one line>"
# Result: ~120 tokens land in orchestrator chat per subagent.
```

The orchestrator's context cost drops from ~215k to ~3k for the same panel.
Late-phase agents (judge, output writers) read files from disk on demand —
and they each get a fresh ~200k window for that.

This pattern is already used by overnight-workflow skills:

- `overnight-insight-discovery` (separate plugin) — Phase 0 probe results, stitched_view, RESUME_MORNING all written to disk; orchestrator holds paths only
- `successor-handoff` — handoff content written to disk, not chat-history
- `cloud-run-results-bq-postsync` — Path B intermediate state files
- `dual-cloudrun-job-orchestration` — multi-agent file-based coordination

These can chain 30+ subagent runs without compression because the orchestrator
context never bloats.

### 2. Chunked judge / synthesizer (when reviewer count > 5)

If a 5-reviewer panel produces ~205k of judge inputs (Phase 3+4+5+7+8+10+11 +
context brief), a 6-reviewer panel exceeds 200k. Solution:

- **Phase 14a (Synthesizer):** consumes Phase 3+4+5 outputs from disk →
  produces a "panel-position document" (~30k) → writes to disk.
- **Phase 14b (Judge/Ruler):** consumes 14a's synthesis + Phase 7 blind
  finals + Phase 10/11 verification → produces final ruling.

Each gets a fresh ~200k window. Lifts reviewer ceiling from 5 to ~10 without
architectural strain.

### 3. Run-verification gate (the safety guardrail)

Before launching the final synthesis/judge phase, the orchestrator MUST verify
in writing:

```python
# Pseudocode for the gate:
required_files = [
    f"{output_dir}/state/reviewer_{r}_phase_{p}.md"
    for r in REVIEWERS
    for p in [3, 4, 5, 7]  # MANDATORY phases
]
missing = [f for f in required_files if not Path(f).exists()]
if missing:
    # FAIL LOUD — do not proceed to judge
    raise MissingPhaseError(f"Cannot launch judge; missing phase outputs: {missing}")
    # Run the missing phase(s) before retrying.
```

Mirror the existing Phase 15.3 retry pattern that v2.16.4 of `agent-review-panel`
introduced for HTML report generation.

### 4. Fail-loud deliverable headers

If any MANDATORY phase was skipped (despite the gate, e.g., user override), the
final report MUST surface this in the header — not bury it:

```markdown
# Review Panel Report

> ⚠️ COMPRESSED RUN — Phases skipped: 4, 5, 7 (reflection / debate / blind finals)
> Findings may be incomplete. Re-run the panel with full phase coverage before
> acting on this report. (Reason: <orchestrator-supplied justification>)

**Verdict:** ...
```

Plus an `[COMPRESSED]` epistemic label on every action item that lacks debate-round
provenance.

### 5. Phase Execution Manifest (self-documenting deliverable)

Require the report header to enumerate phases that ran:

```markdown
**Phases run:** 1, 3, 4, 5×1, 6, 7, 8, 10, 11, 14, 15
```

Missing numbers (e.g., `1, 3, 8, 10, 11, 14, 15` with 4/5/7 absent) are
immediately visible to a reader.

### 6. Anti-rationalization red flags (for the orchestrator's prompt)

Add to the skill spec a "Red Flags" table mirroring the `using-superpowers` pattern.
Specific thoughts that signal compression about to happen:

| Thought | Reality |
|---|---|
| "This is a setup review, debate won't add much" | Debate surfaces what individual reviewers can't see alone — including 1 P0 in the validated repro case |
| "I'll synthesize the reflection inline" | Reflection runs in subagents' fresh contexts — orchestrator synthesis loses the per-reviewer confidence ratings |
| "The judge can integrate everything" | Judge sees only what's in its prompt; if Phase 4/5/7 didn't run, the judge has nothing to integrate |
| "Convergence reached after Round 0" | Round 0 is INDEPENDENT review — no cross-talk yet, so no convergence is possible |
| "I'll skip Phase 5 round 2-3 since round 1 was thorough" | Acceptable per spec (Phase 5 is "max 3 rounds, can stop early on convergence"). But round 1 minimum is MANDATORY. |
| "I'll compress to save tokens" | Subagent dispatch is parallel; each gets its own context. The compression is for the ORCHESTRATOR's context bloat, which file-based state passing eliminates entirely. |

### 7. Forcing-function row in the skill's MANDATORY terminal output (esp. single-agent long skills)

This failure mode is not exclusive to multi-agent fan-out. It also bites **single-agent,
long-prose skills** (e.g. `session-handoff`): a late, *nested* step (e.g. `24c`) keeps getting
dropped because (a) it sits after the "main event" (the PR merge), and (b) a later phase that
produces visible user-facing output (a recap, a summary) reads as the **finale** — so the agent
races to it and the intervening housekeeping steps silently evaporate. (Observed S18 2026-05-29:
`session-handoff` step 24c "persist usage metrics" dropped across multiple sessions.)

The cheap, durable fix: **make the droppable step a required, non-blankable row in the skill's
mandatory terminal output table** (the summary the agent *always* emits). Most long skills end with
a "present this table" step. If the step's artifact has no row there, the agent can present a
complete-looking "done" without ever doing it — nothing forces it. Add a row that demands either the
artifact (path / value) **or** an explicit `skipped: <reason>`, and a one-line note that the row is
NOT blankable ("if you reach this table and the cell is empty, go back and run step N first").

```diff
  | `MEMORY.md` index | Updated |
+ | **Session usage record (step 24c)** | **REQUIRED — <path> written (cost $X, N subagents) or "skipped: <reason>"** |
  | Git status | All committed and pushed |
```

Why it works: the terminal table is the one artifact the agent reliably produces, so wiring the
fragile step *into* that artifact makes skipping it visibly incomplete rather than silently absent.
Cheaper than a programmatic gate (#3) for prose skills that have no executable harness. Pairs with #5
(manifest) — the manifest proves phases ran; this proves the *tail* step's output exists.

## Verification

You have successfully fixed the compression failure mode if:

1. **Disk audit:** `ls {output_dir}/state/` shows one file per (reviewer × phase) cell.
   For a 5-reviewer panel running Phase 3/4/5/7, expect ~20 state files.
2. **Orchestrator-context audit:** the orchestrator's chat history shows Agent tool
   results capped at ~150 tokens each (path + summary + one-line top finding), not
   verbatim 15k-token reviews.
3. **Header audit:** the final `report.md` has a `Phases run:` manifest line listing
   every mandatory phase, no `[COMPRESSED]` warning.
4. **Diff audit:** running the panel a second time on the same input produces
   broadly the same findings — i.e., the run is no longer dependent on context
   pressure that varies between runs.
5. **Reviewer-count stress test:** the skill works at 7+ reviewers without compression.
   This is the true test, since the bug only manifests above ~5.

## Example: Diagnosing the failure mode

Symptom: a multi-agent review panel produced a report headed APPROVE WITH CHANGES,
22 action items, mean score 5.6/10. User asks "what about debate and private
reflection? it seems like we're missing a lot of rounds."

Diagnostic steps:

1. Read the process.md (director's-cut log). Look for `## Phase 4` and `## Phase 5`.
   If you find a heading like `## Phase 4-5: Reflection & Debate (Compressed)`
   followed by 1-2 paragraphs of summary instead of per-reviewer outputs —
   **confirmed compression**.

2. Re-run the missing phases. Dispatch 5 parallel agents (one per reviewer) with
   prompts that include:
   - Their own original review (read from process.md)
   - The other 4 reviewers' reviews (read from process.md)
   - Instructions to produce reflection + debate response + blind final independently

3. Synthesize a Phase 6 round summary and Phase 7 blind-final score table from
   the agent outputs.

4. Diff the new findings against the compressed-run findings. Net-new findings =
   the cost of the original compression. In the validated repro case, this was
   **6 new findings including 1 P0** (a FERPA/DPA gap that only Devil's Advocate
   surfaced during debate).

5. File an upstream issue against the skill repo with the failure-mode
   reproduction + the architectural fix proposal (file-based state passing
   + run-verification gate + fail-loud headers).

## Notes

- **The skill spec itself is the leak.** A skill that says "Return your full
  review as your final message" cannot prevent compression at runtime. The fix
  must be in the SPEC, not in orchestrator behavior. Orchestrators rationalize
  under pressure; specs do not.
- **The fail-loud header (Solution #4) is the single most user-facing fix.**
  It makes the deviation visible. Even if all other guardrails fail, the user
  can see the warning and re-run.
- **Don't conflate this with Phase-12/13-style skip conditions.** Phase 12
  (Verification Tier Assignment) and Phase 13 (Targeted Verification) have
  EXPLICIT skip conditions in well-designed skills. Phase 4/5/7 do NOT — they
  are MANDATORY. Adding explicit MANDATORY markers is part of the fix
  (anti-rationalization).
- **Cross-skill insight:** every overnight-workflow skill
  ([overnight-workflows](https://github.com/wan-huiyan/overnight-workflows))
  that handles 10+ subagent runs uses some form of file-based state passing.
  This skill is a generalization of that pattern, applied as a diagnostic and
  fix for the symmetric (output-direction) problem the sister skill
  `multi-phase-skill-disk-reading-strategy` already solved for the
  input-direction case.
- **When NOT to invoke this skill:** Phase compression is acceptable for
  genuinely-skippable phases that have an explicit skip condition in the spec
  AND meet that condition (e.g., Phase 12 skips when zero unresolved disputes
  remain). The bug is silent compression of MANDATORY phases.

## References

- Sister skill: [multi-phase-skill-disk-reading-strategy](../multi-phase-skill-disk-reading-strategy/SKILL.md) — input-direction version
- Cross-skill pattern reference (all four ship in OTHER plugins, not in this one — install them separately): `overnight-insight-discovery`, `successor-handoff`, `cloud-run-results-bq-postsync`, `dual-cloudrun-job-orchestration`
- Validated repro: [agent-review-panel#35](https://github.com/wan-huiyan/agent-review-panel/issues/35) — full failure-mode analysis with 6 net-new findings demonstration
- Repro session artifacts: `wan-huiyan/the-project-repo` PRs [#116](https://github.com/wan-huiyan/the-project-repo/pull/116) (compressed Run 1) and [#117](https://github.com/wan-huiyan/the-project-repo/pull/117) (corrective Run 2)
- Related Anthropic skill-design pattern: [using-superpowers](https://github.com/anthropic/superpowers) red-flags table approach
