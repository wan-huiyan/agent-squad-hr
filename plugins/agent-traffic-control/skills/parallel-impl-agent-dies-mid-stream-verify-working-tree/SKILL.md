---
name: parallel-impl-agent-dies-mid-stream-verify-working-tree
description: |
  A dispatched parallel implementation subagent can die mid-stream and leave ZERO durable
  output while the harness still reports the task "completed". Use when: (1) you fanned out
  2+ foreground impl agents (Agent/Task tool) to edit code in one repo, (2) one returns
  `API Error: Response stalled mid-stream` / an empty or truncated final message, possibly
  alongside a background "<task> completed (exit code 0)" notification, (3) you're about to
  integrate or commit their combined work. The "completed" status is a LIE here — the agent
  may have written nothing (target file untouched, no test created, its self-made todos all
  still pending). ALWAYS reconcile each agent's CLAIMED work against the actual working tree
  (`git status`, grep the target file for the expected change) before integrating; the
  healthy sibling's work is usually intact, so just finish the dead agent's task yourself.
  Sister to subagent-reports-complete-but-pr-unmerged (work done, integration skipped) and
  credit-stall-mid-orchestration-revive-collision (stalled then auto-revives and races).
  Pairs with shared-file-redesign-parallel-author-serial-integrate (the no-commit → serial
  path-scoped integrate pattern that makes this degrade gracefully).
  ALSO covers the INVERSE outcome — see "Variant: the agent died but the work SURVIVED" —
  where a long single-owner pipeline agent commits+pushes per stage, so a mid-stream death
  leaves finished stages already on the remote. There, redoing the task from scratch
  duplicates landed work: reconcile against `origin/<branch>` and open PRs BEFORE the
  working tree, re-dispatch only the missing stages, never `resumeFromRunId` (it re-runs
  everything downstream), and after the SAME stage dies 3 times do it in the main loop.
  AND the REVIEWER/ANALYST variant — see "Variant: the dead agent's product was its final
  MESSAGE" — where the right move is neither redo nor re-dispatch: the agent's transcript
  survives, the failure notification carries its partial result, and a SendMessage resume
  ("finalize from what you have; no advisor consults; no re-reading") recovers the complete
  deliverable in one cheap turn.
author: Claude Code
version: 1.3.0
date: 2026-07-23
disable-model-invocation: true
---

# Parallel impl agent dies mid-stream — verify the working tree, not "completed"

## Problem
You dispatch N foreground implementation agents in parallel (disjoint files). One comes
back with `API Error: Response stalled mid-stream` (or an empty/truncated report), and the
harness may even emit a background "<task> completed (exit code 0)" line. If you trust that
and integrate, you ship a hole: the agent wrote NOTHING — its target route is untouched, no
test file exists, the todos it created for itself are all still `pending`.

## Context / Trigger Conditions
- 2+ parallel `Agent`/`Task` impl agents editing code in one repo.
- One returns a stall/timeout/empty final message; `subagent_tokens` ~0; a "completed" status.
- You're about to run a combined `git add`/commit or a whole-repo check across both outputs.

## Solution
1. **Reconcile claimed-vs-actual before integrating.** For each agent: `git status --short`
   and grep its target for the expected change (e.g. `grep -n generateChineseText route.ts`).
   A missing edit + no new test file = the agent died; "completed (exit 0)" was the harness
   reporting the shell wrapper exited, NOT the work landing.
2. **Don't try to revive a dead foreground agent — finish its task yourself.** Unlike a
   credit-stall suspension, a mid-stream API death leaves no resumable state. You have full
   context; do it in the main loop (or redispatch a fresh agent with the same brief).
3. **It degrades gracefully because of the orchestration guardrails:** agents do NOT commit
   and do NOT run whole-repo type-check (avoids git-index races + cross-agent `tsc`
   false-positives on half-written files); the orchestrator does path-scoped
   `git add <exact files>` per unit + the full check at integration. So the survivor's work
   is clean and committable independent of the casualty.

## Variant: the agent died but the work SURVIVED (checkpointed pipelines)

The headline case above is the *shared-file* orchestration, where agents deliberately don't
commit — so a death means zero durable output. The **inverse** case is just as common and the
recovery is completely different: a long, single-owner pipeline agent whose stages each
`git commit && git push` before moving on. When that agent dies mid-stream, the finished stages
are **already on the remote**. Treating it like the headline case — redoing the task from
scratch — duplicates work and can clobber pushed commits.

**So the reconcile step (Solution 1) has to look in the right place.** Working-tree-only checks
lie here in the other direction: the agent's worktree may be gone or reset while its commits sit
safely on `origin`. Check, in this order:

```sh
git fetch origin
git log --oneline origin/<branch>          # which stages actually landed?
gh pr list --head <branch> --state all     # did it get as far as opening a PR?
git status --short                         # only NOW look at the tree
```

Then **re-dispatch only the missing stages**, with a brief that states what's already committed.

**Do not use workflow resume.** `resumeFromRunId` re-runs everything downstream of the first
changed call, not just the failed stage — for a checkpointed pipeline that means re-doing landed
work. A targeted mini-workflow covering only the gap is correct.

**The 3-strike escalation rule.** If the *same stage* dies three times, stop re-dispatching and do
it in the main loop in small, individually-verified steps. Three failures on one stage is evidence
the stage is too large for one agent context (oversized payload, long tool chains, big file
rewrites), and a fourth dispatch will fail the same way. In S360 this is exactly how the drift
corrections finally landed after three agent deaths on that stage.

**Design implication — pick the guardrail that matches the work.** Neither pattern is universally
right:

| Work shape | Guardrail | Failure mode it buys |
|---|---|---|
| N agents editing SHARED files in parallel | agents do NOT commit; orchestrator integrates path-scoped | death = no output, but no index races or half-written cross-checks |
| ONE agent, long serial pipeline, stall-prone | agent commits + pushes per stage | death = partial-but-durable progress; resume by re-dispatching the gap |

Choose per-stage commits whenever the work is long enough that a mid-stream death is likely and
the agent owns its files exclusively.

## Verification
`git status` + a grep of each target shows exactly the expected edits from the SURVIVING
agents and nothing from the dead one; after you finish the dead one's task, the full suite +
type-check pass before any commit.

## Variant: the dead agent's product was its final MESSAGE (reviewer/critic/analyst) — resume-finalize, don't redo

When the stalled agent is a REVIEWER, CRITIC, or ANALYST — its deliverable is a structured
final message, not file edits — the impl-agent playbook (verify tree, redo the task) wastes
the whole review: there is no working tree to check, and re-dispatching re-pays the full
read-and-reason cost. The recovery is different and nearly free:

1. **Read the failure notification's `<result>` before deciding anything.** A mid-stream
   stall often lands AFTER the analysis is done and BEFORE the write-up — the partial result
   in the notification can already contain real, load-bearing findings (verified 2026-07-23:
   a design-gate reviewer's stall message carried three corrections that shaped the fix).
2. **SendMessage the SAME agent id** — it resumes from its full transcript — with a
   finalize-only prompt: "Your run stalled mid-stream. FINALIZE now from what you already
   have — do NOT consult any advisor, spawn subagents, or re-read files; write the findings
   list directly in the specified format." Closing the expensive paths matters: the stall
   often happened INSIDE one of them (an advisor consult), and an unconstrained resume can
   stall the same way again.
3. **Name the specific partial-result threads you want finalized** ("include your positions
   on X, Y, Z from your interrupted notes") so nothing silently drops between the partial
   and the final.

Verified 2026-07-23 (the routing app rung-8 design gate): one resume turn recovered the complete
structured review — including items only hinted at in the partial — at a fraction of the
original agent's cost, with zero re-reading. Distinct from `resumeFromRunId` (workflow-level,
re-runs downstream — still never that); this is the agent-transcript resume, which is safe.

**Sub-variant — killed by a SESSION/CREDIT LIMIT, resumed after the reset (verified
2026-07-23, the routing app rung-9 fable critique):** the same transcript-resume works when the
kill cause is "You've hit your session limit" (agent terminated on a terminal API error),
even HOURS later after the limit resets, and even when the agent had NOT yet produced its
deliverable — it had only finished its reading (33 tool uses) and died right before its
compute step. The resume prompt then says CONTINUE, not just finalize: "you were cut off
right before writing your recompute script — write it now, run it, report in the mandated
format; do not re-read artifacts you already read, no subagents, no advisor." Result: the
complete adversarial report in 2 tool uses / ~2.5 min, versus re-paying the entire
read-phase on a fresh dispatch. Two extra rules for the limit case: (a) if the world moved
during the outage (e.g. a merge landed on the branch), state the delta in the resume
message and mark which changes are expected-context vs findings; (b) the failure message's
"PARTIAL output recovered" preamble tells you how far it got — calibrate the resume verb
(finalize vs continue) to that.

## Notes
- TRAP, surfaced reactively (`disable-model-invocation`): recall by grepping lessons/skills
  when a parallel agent returns a stall, or via the `/name` invocation.
- The lie is specifically "completed (exit 0)" on the shell *wrapper*, not on the agent's
  work. Same family as subagent-reports-complete-but-pr-unmerged — different gap: there the
  code exists but the PR isn't merged; here the code was never written.

## References
- See also: credit-stall-mid-orchestration-revive-collision,
  subagent-reports-complete-but-pr-unmerged,
  shared-file-redesign-parallel-author-serial-integrate.
