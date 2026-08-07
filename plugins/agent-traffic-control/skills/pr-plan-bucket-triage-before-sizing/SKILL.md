---
name: pr-plan-bucket-triage-before-sizing
description: |
  Run a 1-day "Phase 0 bucket triage" with subagent-per-bucket dispatch
  BEFORE writing detailed PR plans, when scoping work on a codebase that
  (a) someone else is actively shipping on, (b) you haven't audited
  recently, or (c) you're relying on assumptions about route existence,
  UI wiring, storage shape, or defect scope. Use when: (1) you're about
  to invoke `superpowers:writing-plans` for 3+ PRs and your LOC estimates
  contain question marks or "TBD by triage" markers; (2) brainstorming
  output references "the colleague's module is a stub" / "the UI doesn't
  exist yet" / "the report download is missing" — assumptions you haven't
  grep'd; (3) the design says "PR-N depends on triage findings"; (4) you
  catch yourself writing "size: 150-600 LOC" ranges; (5) the codebase has
  a roadmap doc claiming features are "Done" but with caveats that haven't
  been re-verified. The skill defines the bucket-triage pattern (6 typical
  buckets: routes/templates, existing surface, module integration, break
  diagnosis, pattern audit, storage convention), the subagent dispatch
  shape for investigation work (vs. implementation), and the findings-doc
  structure that turns assumptions into per-bucket verdicts. Demonstrated
  ROI on its motivating case: caught 4 wrong assumptions in 4 hours that
  would have invalidated 3 detailed PR plans. NOT for: greenfield work
  (no existing code to audit), bug fixes you can reproduce in 5 minutes,
  or solo work on a codebase you've touched this week.
author: Claude Code
version: 1.0.0
date: 2026-05-15
---

# Phase 0 Bucket Triage Before Writing PR Plans

## Problem

`superpowers:writing-plans` produces detailed task-by-task plans with exact
file paths, LOC estimates, and TDD steps. That's the right output when you
**know the codebase state** — but a common failure mode is writing those
plans on assumptions about: which routes already exist, whether a colleague's
in-flight module is a stub or substantial, what storage convention links
results to runs, whether a "known defect" is still real or was quietly fixed.
You burn cycles writing detailed plans, the engineer starts implementing,
and within the first hour they discover the plan was sized against a
codebase that doesn't exist. The fix is **always re-plan with the new
evidence** — meaning the original plan was waste.

The cost of writing plans on speculation is asymmetric:
- Writing 4 detailed plans on speculation: ~2 hours.
- Discovering plan-1 was wrong during implementation, re-planning, re-discussing
  with reviewer: ~4 hours per wrong plan.
- Net cost of speculation: ~14 hours.
- Cost of a 1-day Phase 0 triage: ~6 hours.
- Net savings: ~8 hours, AND the surviving plans are sized in concrete LOC
  (not ranges), AND triage typically uncovers free-bonus findings (stale docs,
  pre-existing bugs, design opportunities the speculation would have missed).

## Context / Trigger Conditions

Use this skill when **all three** are true:

1. **You're sizing PRs against an existing codebase.** (Greenfield work
   doesn't have anything to audit — go straight to writing-plans.)
2. **You don't have certainty about the codebase's current state.** Markers:
   - You haven't touched the relevant files this week
   - Someone else is actively shipping on a branch you'll touch
   - A roadmap doc claims things are "Done" with caveats
   - The brainstorming output uses language like "we assume X exists" /
     "if Y is missing" / "her module is probably a stub" / "TBD by triage"
3. **The PR plans depend on those assumptions.** Markers:
   - LOC estimates are ranges ("150-600 LOC") instead of concrete numbers
   - Plan says "PR-N sizing depends on triage findings"
   - Storage / loader sizing depends on schema you haven't grep'd

If any of these are absent: skip this skill. Go to writing-plans directly.

## Solution

**Phase 0 = a single-day investigation that outputs a findings document
+ a refined PR plan with real numbers. No production code touched.**

### The 5-step workflow

1. **Setup (~30 min, manual).** Cut a `triage/<short-name>` branch off the
   target branch (NOT main if you're triaging someone else's active work).
   Push the design doc + triage plan onto it so all relative-path links
   work locally. Slack the active developer: "doing 1-day triage, won't
   push anything, will share findings — flag if anything's in flux."

2. **Define investigation buckets (in writing-plans, ~30 min).** The 6
   standard buckets that have worked across multiple sessions:

   | Bucket | What it answers | Typical output |
   |---|---|---|
   | Routes & UI surface state | Which routes/templates exist? Are they wired? | file:line table of all matches |
   | Existing affordances | What user-facing features already exist that overlap with the planned PR? | List of existing routes/buttons + how to extend vs replace |
   | Module integration | Which modules already do the thing the PR plans to add? | Public function signatures + call graph |
   | Break / defect diagnosis | Reproduce reported breaks; classify (front-end / back-end / data); size fix | Single-line root cause + S/M/L size |
   | Pattern audit | Grep client-facing surfaces for jargon / debt / inconsistencies | Counts per file + reusable lint script |
   | Storage / persistence convention | How are results keyed and persisted? Can the PR loader reach what it needs? | Schema + walker script |

   Not every project needs all 6. Pick the buckets whose answers actually
   affect PR sizing. Skip the rest.

3. **Dispatch a subagent per bucket (~3-5 hours total in parallel).** Use
   `general-purpose` subagent, NOT the formal `superpowers:subagent-driven-development`
   loop. Investigation work doesn't fit the TDD + spec-reviewer + code-quality-reviewer
   pattern — there's no "spec" beyond the bucket question, and the "code"
   is markdown findings. Each subagent gets:
   - **Scene-setting:** project name, working directory, branch, why this
     triage exists, prior buckets' verdicts (so each subagent can use earlier
     findings as context).
   - **A specific bucket question:** "How is X wired in this codebase today?"
   - **A required output template:** the exact markdown structure for that
     bucket's section in the findings doc, with placeholders the subagent
     fills in.
   - **A required verdict at the end:** "Pick one of these N classifications
     and justify with file:line citations."
   - **A required commit:** subagent commits the findings before reporting back.
   - **Constraints:** read-only, no Flask launch (creds), no production code
     edits, cite file:line for every claim.

   Skip Flask-launch and cred-requiring steps in subagent dispatch — note
   "skipped, requires user creds" in the findings. The user can manually
   validate those steps later.

4. **Synthesise (~30 min).** Dispatch a final subagent to read all the
   bucket verdicts and produce: TL;DR, revised PR plan (table with sized
   PRs + sequencing), newly-discovered risks, things-the-colleague-should-know.

5. **Decision gate (~15 min, manual).** Plan reviewer (you) reads the
   findings doc. Outcome is one of: (a) proceed to writing-plans for PR-A
   with real numbers, (b) reshape the PR sequence (e.g. a 1-char fix or
   schema migration becomes PR-0 because it's blocking), (c) revise the
   brainstorming if the triage uncovered a fundamental wrong assumption.

### Findings doc structure

Single file at `docs/triage/<date>-<topic>.md`:

```markdown
# <Topic> — triage findings

**Date / Branch / Author / Companion design**

## TL;DR
_(filled by synthesis subagent — 6-8 scannable bullets)_

## Bucket 1 — <name>
_(filled by Bucket-1 subagent with citations + verdict)_

... (Bucket N)

## Revised PR plan
_(table: PR | Title | Size LOC | Depends on | Sequencing — with concrete numbers, not ranges)_

## Newly discovered risks
_(table: Risk | Severity | Mitigation)_

## Things colleague should know
_(findings + coordination asks)_
```

### Subagent dispatch template

Every bucket subagent should get this shape:

```text
You're executing <Bucket N> of a triage plan. Investigation work, not
implementation. No production code touched.

Scene-setting:
- Repo: <name>
- CWD: <absolute path>
- Branch: <triage branch> off <target branch>. Don't switch.
- Why this triage: <one-paragraph context>
- Prior buckets done: <one-line verdict per bucket so far>

Task: <bucket-specific instructions, with explicit Step 1..N>

Step N: SKIP if cred-required, record as "skipped — requires user creds"
Step N+1: Write findings to <findings doc> using this exact template: <...>
Step N+2: Commit with message "triage(bucket-N): <one-line>"

Constraints:
- Read-only inspection
- Cite file:line for every claim
- Stay in scope — Bucket N only
- Do NOT modify any file outside the findings doc + any agreed scripts/triage/* helpers

Output format:
- Status: DONE | DONE_WITH_CONCERNS | NEEDS_CONTEXT | BLOCKED
- Summary: 3-5 bullets (same as Verdict)
- Files changed: path + commit SHA
- Concerns/observations
```

## Verification

After the triage, verify against these checks:

1. **Every PR in the revised plan has a concrete LOC number**, not a range.
   If you still see "150-400 LOC" anywhere, that bucket failed to produce
   evidence — re-dispatch.

2. **At least one "design correction"** appears in the findings.
   In every session this pattern has been used, triage caught
   ≥1 wrong assumption. If your triage produced zero corrections, you
   probably didn't need it — but more likely your buckets weren't
   pointed at the load-bearing assumptions.

3. **Coordination asks for the active developer are concrete.**
   "Are signatures of `X` stable for next 2 weeks?" beats "Can I do this?"

4. **The findings doc references file:line for every claim.**
   Assertions without citations are speculation in disguise.

## Example

### Motivating case (2026-05-15)

User wanted to scope ~4 PRs of webapp work on a branch a colleague was
actively shipping for a client engagement. Brainstorm produced a design
doc with:
- PR-A: "Dual-mode report bundler, 800-1100 LOC"
- PR-B: "Fix SCA UI, TBD-by-triage LOC"
- PR-C: "Post-non-sig feedback loop, 400-600 LOC"
- PR-D: "Jargon audit, 200-400 LOC"

The skill triggered on: "TBD by triage" + LOC ranges + "we assume her
robustness module is a stub."

Phase 0 ran with 6 buckets in ~4 hours. Result:

| Original assumption | Triage finding | Plan delta |
|---|---|---|
| "SCA UI has 224/448-spec defect" | Defect was fixed in `webapp/ci/prep.py:122`; caveat is stale | PR-B collapses 400→150 LOC |
| "No download route exists" | Route exists at `/runs/<id>/report` but serves non-self-contained HTML | PR-A scope shifts from "build" to "make self-contained" |
| "Colleague's robustness module is a stub" | Module is substantial; UI is ALREADY wired at `/sensitivity`, `/backtest`, `/permutation` | PR-A robustness section drops 200→80 LOC |
| "Calendar editor broken on colleague's branch" | 1-character HTML typo at `calendar.html:124`, introduced by user 2 months ago, pre-existing on main | New PR-cal (<1 LOC) added; **provenance correction prevented blaming the colleague** |
| Storage abstraction needs 200-300 LOC | SQLite covers 3/4 result types cleanly; SCA needs a 30-LOC `config_hash` schema add | New PR-0 (30 LOC) unblocks clean PR-A |

Net effect: 4 wrong assumptions caught + 2 new small PRs added + every
final PR has a concrete LOC number. Plan went from 4 PRs with ranges to
7 PRs with sized work, AND a sized parallel "Phase 0.5 UX triage" branch
emerged from the same evidence-first pattern.

## Notes

- **Subagent-driven-development's reviewer loop doesn't help here.** The
  formal spec-compliance and code-quality reviewers are overkill for
  investigation work. The "spec" is the findings template and the "code"
  is markdown — a quick controller-level read after each bucket subagent
  reports is enough.

- **Skip Flask / browser / cred-required steps in subagent dispatches.**
  Have the subagent record them as "skipped — requires user creds," and
  validate manually later (or in a follow-up session). Saves time and
  avoids BLOCKED status.

- **Cherry-pick the design + triage-plan docs onto the triage branch.**
  Otherwise relative-path links in the triage plan break locally. This
  is annoying enough to call out: `git cherry-pick <design-commit> <plan-commit>`
  after cutting the triage branch.

- **Reusable scripts are a free bonus.** Buckets that audit patterns
  (jargon density) or walk storage often produce a small bash/python
  script that's worth committing under `scripts/triage/` — PR-D or PR-A
  can reuse it as a CI lint.

- **Don't skip the synthesis subagent.** Reading 6 bucket verdicts and
  weaving them into a coherent revised PR plan is real work; the same
  controller that dispatched the buckets has the context loss to make
  this tedious. Fresh synthesis subagent reads the doc cold and produces
  a tighter narrative.

- **When NOT to use this:** solo work on a codebase you touched this
  week; greenfield projects; bug fixes you can reproduce in 5 minutes;
  hot-path incident response (no time for 1-day investigation — just
  reproduce + fix). The pattern shines when scope is medium-to-large AND
  you'd otherwise be sizing on assumptions.

## See also

- `superpowers:writing-plans` — what you do AFTER this skill runs, with
  real numbers in hand.
- `superpowers:subagent-driven-development` — the formal implementation
  loop. This skill is its read-only sibling for investigation.
- `superpowers:brainstorming` — what produced the speculative design
  this skill audits.
- `successor-handoff` — when the synthesis output becomes the next
  session's kickoff context.

## References

- The motivating session: `docs/plans/2026-05-15-sbx-uk-robustness-and-report-design.md`
  (design), `docs/plans/2026-05-15-sbx-uk-webapp-triage-plan.md` (triage
  plan), `docs/triage/2026-05-15-sbx-uk-webapp-state.md` (findings) in
  the `<org>/the-causal-impact-repo` repo, branch `triage/sbx-uk-webapp-state`.

## Reference-only siblings in this toolkit

These carry `disable-model-invocation: true`. They never appear in the skill
listing and the Skill tool refuses them, so the only way in is to open the file
with Read when one of these matches what you are looking at.

- [`workflow-parallel-fanout-omits-sequential-phases`](../workflow-parallel-fanout-omits-sequential-phases/SKILL.md) — a sequential debate/consensus process silently vanished into a parallel fan-out
- [`workflow-deterministic-compute-as-script-not-stall-prone-agent`](../workflow-deterministic-compute-as-script-not-stall-prone-agent/SKILL.md) — heavy deterministic compute stalls mid-stream in an agent turn — move it into a script
- [`workflow-large-markdown-deliverable-extract-from-output-json-not-retype`](../workflow-large-markdown-deliverable-extract-from-output-json-not-retype/SKILL.md) — a large markdown deliverable came back inside a structured-output field; extract it, do not retype it
- [`workflow-pipeline-parallel-stage-returns-bare-array-dropped-by-collector`](../workflow-pipeline-parallel-stage-returns-bare-array-dropped-by-collector/SKILL.md) — a pipeline stage returned a bare array and the collector dropped it
- [`workflow-schema-agent-retry-cap-oversized-payload`](../workflow-schema-agent-retry-cap-oversized-payload/SKILL.md) — a schema agent that did all its work returns null — "StructuredOutput retry cap" on an oversized payload
- [`workflow-schema-agents-empty-loop-under-ratelimit`](../workflow-schema-agents-empty-loop-under-ratelimit/SKILL.md) — a workflow returns fewer results than it dispatched because agents empty-looped under a rate limit
- [`workflow-standalone-schema-agent-crash-and-args-string`](../workflow-standalone-schema-agent-crash-and-args-string/SKILL.md) — two crashes that discard every completed agent's work in a dynamic workflow
