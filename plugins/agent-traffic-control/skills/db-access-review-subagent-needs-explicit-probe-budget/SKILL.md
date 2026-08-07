---
name: db-access-review-subagent-needs-explicit-probe-budget
description: |
  Dispatching a review or verification agent with live database, gcloud, psql or bash access: give
  it a tool call and time budget, plus the probes NOT to re-run. Also when it gives `API Error:
  The socket connection was closed unexpectedly`, or has run 30 minutes. Not its sources.
author: Claude Code
version: 1.0.0
date: 2026-05-29
---
# A review subagent with live-DB access needs an explicit probe budget

## Problem

You dispatch a `general-purpose` subagent to review a PR or verify findings, and it has live database /
cloud / Bash access. Unprompted, it does the thorough thing: re-derives every claim from scratch,
running expensive exploratory queries (full-window joins, multi-date sweeps, dry-runs). Two failure
modes follow:

1. **It runs very long** (20–40+ min of wall time on heavy probes), far past what the review needs.
2. **It can socket-close mid-run.** The Agent tool returns `API Error: The socket connection was closed
   unexpectedly` with a non-zero `tool_uses` count but **no final assistant message** — so the agent
   did real work (11, 20 tool calls) but its **verdict was never delivered**. The output is lost, and
   it is **not resumable** from the orchestrator unless a `SendMessage`/continue tool is available
   (often it is not). You've burned the tokens and the wall-clock for nothing.

The root cause is that an unbounded reviewer treats "review this change" as "independently re-establish
the entire ground truth," which is exactly the slow, fragile thing — when the orchestrator has usually
ALREADY established that ground truth and just needs a second pair of eyes on the diff.

## Context / Trigger Conditions

- About to dispatch a code-review / verification / research agent with BigQuery / gcloud / psql / Bash.
- An `Agent` result shows `API Error: The socket connection was closed unexpectedly` plus
  `tool_uses: N (>0)`, `subagent_tokens: 0`, and no Strengths/Issues/Assessment in the output.
- A dispatched reviewer has no return after ~20–30 min.
- You (orchestrator) already ran the expensive live probes and confirmed the numbers in the PR body.

## Solution

Bound review/verify subagents explicitly in the dispatch prompt:

1. **Hard budget:** "Target under ~6 minutes, ≤8 tool calls." A reviewer with a budget self-limits to
   the high-value checks.
2. **Forbid the expensive re-derivation:** "Do NOT run BigQuery probes / multi-table joins over date
   ranges. I already verified <the specific claims> — your job is the STATIC diff review + run only the
   fast unit test (`pytest …`)." Hand it the ground truth as given facts to sanity-check cheaply, not
   to reproduce.
3. **Prefer several short bounded agents over one open-ended one** — diversity of lens at low per-agent
   risk; if one socket-closes you still have the others.
4. **On a socket-close:** capture the returned `agentId`. If a `SendMessage`/continue tool exists, try
   resuming for just the verdict (no new probing). If not, **re-dispatch a fresh bounded agent** — do
   not assume the lost agent "basically finished."

## Verification

The bounded re-dispatch returns a full verdict quickly (minutes, not tens of minutes) and does not
socket-close. A pure-docs review can finish in <1 min / ~4 tool calls.

## Example

Two parallel review agents were dispatched with live-BQ access to verify an ML-pipeline PR and told to
"adversarially verify my claims." Both ran **~34 minutes** (11 and 20 tool calls of BQ probing) and both
returned `API Error: The socket connection was closed unexpectedly` with **zero verdict** — output lost,
not resumable (`SendMessage` unavailable). Re-dispatched with "≤8 tool calls, <6 min, do NOT run BQ
probes (I already validated the delta/unmapped-code/serving checks), review the diff statically + run
the fast pytest" → both returned clean structured verdicts in ~12–13 min; a later docs-only review
returned in 28s / 4 tool calls.

## Notes

- Distinct from [[subagent-watchdog-stall-on-ui-template-track]]: that is a UI/template agent killed by
  the **600s no-output watchdog**, fixed by going inline. This is a **DB-access agent that socket-closes
  after a long live-probe run**, fixed by **bounding the probe budget** (the work IS streaming output, so
  the watchdog isn't the trigger — the transport drop is).
- The asymmetry that makes bounding safe: the orchestrator has already done the expensive verification
  (that's why it's confident enough to merge); the reviewer's value is the independent read of the DIFF
  and a cheap sanity-check of the headline numbers, not a full re-derivation.
- Pairs with the project norm "review every non-trivial PR before merge" — bounding makes that norm
  cheap and reliable instead of a coin-flip on whether the agent returns.
- See also: [[code-reviewer-subagent-no-bash-blocked-on-pr-diff]], [[finding-verification-live-bq-triple-probe]],
  [[subagent-external-wait-orchestrator-takeover]].

## Reference-only siblings in this toolkit

These carry `disable-model-invocation: true`. They never appear in the skill
listing and the Skill tool refuses them, so the only way in is to open the file
with Read when one of these matches what you are looking at.

- [`parallel-impl-agent-dies-mid-stream-verify-working-tree`](../parallel-impl-agent-dies-mid-stream-verify-working-tree/SKILL.md) — a dispatched agent died mid-stream leaving no output while the harness reported it completed
- [`opus-ratelimit-fanout-retry-on-sonnet-throttled-waves`](../opus-ratelimit-fanout-retry-on-sonnet-throttled-waves/SKILL.md) — a large fan-out mass-fails with HTTP 429 / "temporarily limiting requests"
- [`parallel-subagent-fanout-rate-limit-recover-from-disk`](../parallel-subagent-fanout-rate-limit-recover-from-disk/SKILL.md) — recovering a rate-limited fan-out from the files the surviving agents already wrote
- [`credit-stall-mid-orchestration-revive-collision`](../credit-stall-mid-orchestration-revive-collision/SKILL.md) — a billing/credit stall froze in-flight subagents and they collide when it resolves
