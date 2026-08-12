---
name: flatten-workflow-parallel-arrays-before-collecting
description: |
  Claude Code Workflow tool gotcha: a pipeline() stage that returns
  parallel([...]) resolves to a BARE ARRAY, but a sibling stage that returns
  {dimension, verified: []} resolves to an OBJECT — so a collector written as
  `per.flatMap(p => Array.isArray(p?.verified) ? p.verified : [])` SILENTLY
  DROPS every item from the array-shaped stages. Use when: (1) a fan-out
  review/verify workflow reports "0 confirmed / 0 refuted" or "0 findings" but
  the agent count / journal shows verify agents actually ran; (2) a
  loop-until-dry or review workflow looks suspiciously CLEAN; (3) you wrote a
  pipeline whose stage-2 conditionally returns parallel(...) for some items and
  an object for others. The "0 findings" is a FALSE all-clear from a
  result-collection bug, not a real result. Fix: handle BOTH shapes in the
  collector.
author: Claude Code
version: 1.0.0
date: 2026-06-04
disable-model-invocation: true
---

# Workflow pipeline(): a stage returning parallel() is a bare array the collector silently drops

## Problem
In the Claude Code **Workflow** tool, `pipeline(items, stage1, stage2, …)` runs each item
through the stages. A common fan-out-then-verify shape makes stage-2 return **different
shapes per item**:

```js
const per = await pipeline(DIMENSIONS,
  d => agent(findPrompt, {schema: FINDINGS}),          // stage 1
  (findings, d) => {
    if (!findings.confirmed.length)
      return { dimension: d.key, verified: [] };        // OBJECT shape (no findings)
    return parallel(findings.confirmed.map(f => () =>   // BARE ARRAY shape (has findings)
      agent(verifyPrompt(f), {schema: VERDICT}).then(v => ({...f, verdict: v}))));
  });
```

`per[i]` is now an **object `{verified: […]}`** for dimensions that found nothing, but a
**bare array `[{…verdict…}, …]`** for dimensions that DID find candidates (because
`parallel()` resolves to an array). A collector written for only the object shape:

```js
const all = per.flatMap(p => Array.isArray(p?.verified) ? p.verified : []);  // BUG
```

evaluates `Array.isArray(undefined)` → false for every array-shaped element → returns `[]`
→ **silently drops all verdicts from exactly the dimensions that found bypasses.** The
workflow returns `confirmed: 0, refuted: 0` — a **false "all clear."** The real tell:
`agentCount` is high and the journal shows `verify`/`v2:` agents both `started` AND
`result`-ed, yet `confirmed_count + refuted_count == 0` (verify agents only spawn for
candidates, so candidates existed).

## Context / Trigger Conditions
- A `Workflow` script using `pipeline()` where a later stage conditionally returns
  `parallel(...)` (adversarial-verify / review / loop-until-dry patterns).
- The workflow result is "0 confirmed / 0 refuted" or "0 findings" — suspiciously clean.
- The completion summary's `agentCount` (or the journal under
  `…/subagents/workflows/wf_*/journal.jsonl`) shows verify agents ran, contradicting "0".

## Solution
Handle BOTH shapes in the collector (this is what the canonical multi-stage example in the
Workflow docs does, and it's easy to drop when simplifying):

```js
const all = per.flatMap(p =>
  Array.isArray(p?.verified) ? p.verified
  : (Array.isArray(p) ? p : []));        // <-- the array-shape branch the bug omits
```

Better still, make stage-2 return ONE consistent shape (always an object, or always an
array) so the collector can't diverge. If a phase()/coverage map reads `p.attacks_run_count`,
that's also `undefined` for the array-shaped items — another symptom.

**Recovery without re-running the agents:** edit the collector line in the persisted script
(`…/workflows/scripts/<name>-<runId>.js`) and **resume** with
`Workflow({scriptPath, resumeFromRunId})` — the find + verify agents are cached and return
instantly; only the fixed synthesis re-runs. The dropped findings reappear.

## Verification
- After the fix/resume, `confirmed_count + refuted_count` matches the number of verify
  agents that ran (journal `result` lines for `v*:` keys).
- A dimension that genuinely found a real bypass now shows up in `confirmed`, not nothing.

## Notes
- This is the **inverse of trusting a clean review** — like a green test that asserts
  nothing, a "0 findings" workflow can mean "found nothing" OR "collected nothing."
  Distrust a clean adversarial round; verify the agents attacked (journal / agentCount)
  before believing it. See [[code-review-subagent-fabricates-specifics-to-inflate-severity]]
  and [[per-item-tryexcept-zero-ok-looks-like-hang]] (a zero/empty that means "broke", not "fine").
- `parallel()` also resolves a thrown thunk to `null`, so always `.filter(Boolean)` the
  flattened array before using verdicts.
- The journal lives at
  `~/.claude/projects/<proj>/<session>/subagents/workflows/wf_<id>/journal.jsonl`
  (`{type:'started'|'result', key, agentId}` lines) — the fastest way to confirm agents ran.
