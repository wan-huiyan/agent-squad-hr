---
name: shared-file-redesign-parallel-author-serial-integrate
listing_tier: rich
description: |
  Writing the next session's prompts for several remaining slices that ALL edit one hot file — a
  template, a central view, one stylesheet block — so the usual "split only if the file sets are
  disjoint" rule would force everything serial. Shared file work is parallel to author and serial
  to integrate. Pulls the longest lead slice out first as a gating spike when a schema, storage or
  probe gated backend change decides a later panel's scope, fans the rest out, then merges by
  ascending risk — or extracts partials in a prep pull request. Not for a session editing that
  file right now.
author: Claude Code
version: 1.1.0
date: 2026-06-04
---
# Shared-file redesign: parallel-author, serial-integrate

## Problem

You're authoring next-session prompts for the remaining slices of a multi-item
redesign (e.g. a `/report` page redesign with 9 items left across 3-4 slices).
The session-handoff skill's parallelization rule is: *"split into parallel prompts
only if the file sets are disjoint; skip splitting when tasks share files."* But
**every remaining slice edits the same hot file** (`report.html`, plus partly
`analysis.py`). By that rule you'd sequence all of them — losing the parallelism
the user explicitly asked for.

Shared-file work is not un-parallelizable. It's **parallel to author, serial to
integrate** — and the integration can be made cheap (narrow collision marking) or
eliminated entirely (partials extraction). The handoff's job is to hand the next
session that structure, not to give up at "these conflict."

## Context / Trigger conditions

- You're in session-handoff Phase 3 (writing `session_N+1*` prompts) for the
  remaining slices of a redesign.
- The slices share a file (template / central view / one `{% block extra_css %}`),
  so the naive disjoint-files check fails.
- The user asked for parallel execution, OR the work is large enough that serial
  would waste a session.
- Often one slice is a backend/schema/storage change (longest-lead, back-compat
  -critical, maybe probe-gated) that a UI slice consumes.

## Solution

Encode this shape in the orchestrator prompt:

**1. Pull the riskiest/longest-lead slice out as a serial PREREQ ("gating spike"),
not a peer.** If one slice is a backend change that (a) reaches into a live
serialization/storage pipeline, (b) needs a schema bump with back-compat, or
(c) is gated on a probe that might fail (does the engine even expose the data the
UI wants?) — it goes FIRST, alone. Reasons:
   - Its probe result decides the dependent UI slice's scope. Resolve that
     uncertainty before committing the UI scope (else you author a prompt for a
     panel that can't be built).
   - It must land → deploy → **bake** (a real run writes the new schema) before
     the UI slice has real data to render against.
   - It's the critical path; starting it first de-risks the whole fan-out.
   See `inherited-scope-doc-names-may-not-exist`, `deploy-gate-success-report-doesnt-prove-the-gated-path`.

**2. Fan out the remaining slices (parallel AUTHORING).** They're independent to
write; each on its own branch off `origin/main`.

**3. Serial-INTEGRATE by ascending risk.** Merge order = lowest-blast-radius
first (pure template) → mixed (template + new routes) → highest (cross-run lookups
/ depends on the baked backend). Each later branch rebases on `origin/main` after
the prior merges — small and mechanical because the collision surface is narrow
(next point).

   **When the per-PR gate dominates wall-clock, AUTHOR the later slice ON the
   merged prior instead of parallel-author-then-rebase.** "Parallel authoring" is
   the prompt's *suggestion*, not load-bearing — what the user actually picks is
   no-prep-PR (Option 1) vs partials-prep-PR (Option 2). If each slice carries a
   heavy human-gated review (formal panel + integrator + CI + merge), that gate —
   not authoring — is the long pole, so the parallelism you'd buy by authoring slice
   N+1 before slice N merges is marginal, and you pay for it with a rebase over the
   shared collision region. Cleaner: land slice N, then author N+1 **on post-N main**
   — it sees N's real merged code at its declared anchor (e.g. the footer card it
   sits above already exists), so there's **zero rebase** and N+1 is built against
   real, not in-flight, neighbors. Reserve true parallel authoring for de-risking
   *research* on N+1 (deps, routes, data shape) that overlaps N's authoring without
   touching the hot file. (Confirmed S94: Slice C built on merged-B main, no footer
   rebase.) See `same-day-hotfix-write-delta-handoff-not-rewrite-shipped-next-prompt`
   for the analogous "build on what shipped" instinct.

**4. Name the narrow collision surface and a discipline for it.** For a shared
template the real collisions are usually just TWO spots, not the whole file:
   - the single `{% block extra_css %}` `<style>` block every slice appends to →
     give each slice a **distinct marker comment** (`/* === Slice B === */`,
     `/* === Slice C === */`) so appends/rebases touch disjoint regions;
   - the bottom-of-document anchor (cards/sections all cluster low) → declare a
     **footer-ownership order** (which slice's section is last, which sits above
     it, which replaces an existing mid-document element). Each slice inserts only
     at its declared anchor.
   See `template-inlined-css-is-one-surface-not-two`,
   `parallel-pr-template-fork-duplicates-moved-section`.

**5. Offer the partials-extraction trade (convert serial → true parallel).** A
small **Slice-0 prep PR** that extracts the page body into Jinja `{% include %}`
partials (`_report_hero.html`, `_report_chart.html`, `_report_config.html`, …)
gives each slice a **different file** → zero overlap → merge in any order, no
rebase dance. Cost: one extra serial PR + its review gate up front. Recommend it
when all slices land this session (it pays for itself); skip it when only one or
two land. **Let the user pick** (AskUserQuestion) — don't decide unilaterally.

**6. Anchor the slice prompts on memory + grep recipes, not line numbers.** Line
numbers in a hot file drift the moment the first slice merges. Point each prompt
at the memory file + a `grep` for the symbol/marker.

## Verification

- The orchestrator prompt states: the gating-spike-first order, the ascending-risk
  merge order, the named collision points + discipline, and the Option-1/Option-2
  choice as an explicit AskUserQuestion.
- Each slice prompt is self-contained (cold-start), names its own branch, its
  declared anchor/footer position, and its rebase-after dependency.
- Run `large-redesign-parallel-branch-collision-audit` too — it catches
  *pre-existing* long-running branches (client variants) that also touch the hot
  file; note them as out-of-scope so the next session isn't surprised.

## Example (a causal-impact engagement, #190 /report redesign, S93 handoff)

Slice A (hero) shipped. Remaining: B (chart-foot + scorecard anchors + config
recap — template-only), C (downloads — CSV cheap, PDF/PNG new deps), D (covariate
contributions panel + inline SCA). All edit `report.html`; B/C also touch
`analysis.py`. Disjoint-files test → "don't split."

Structured instead as: **94a Slice D-BACKEND first** (covariate-weight +
spike-slab inclusion-prob extraction; probe-gated — does tfci expose inclusion
probs?; reaches into the live #275 result pipeline; `SCHEMA_VERSION` bump with
back-compat; must bake a real v4 run) → **fan out {94b B, 94c C, 94d D-UI}** →
**serial-merge B → C → D-UI** (ascending risk). Collision surface = the one
`extra_css` block (per-slice markers) + the footer (B's config card last, C's
downloads above it, D-UI's inline SCA replaces the SCA CTA mid-document).
Option-2 partials alternative offered. The advisor validated the shape; the
disjoint-files rule alone would have serialized four sessions of work.

## Variant — in-session EXECUTION: decompose-to-placeholders for a prototype port at scale (S12, 16 agents)

When the parallel work is executed in ONE session (not handed to future sessions) — e.g. porting a
Claude Design prototype into ~12 React components — take the "Option-2 partials" idea all the way:
**decompose the one hot surface into N disjoint files UP FRONT** so the fan-out is genuinely disjoint
and no agent ever edits a shared file.

1. **Freeze the foundation as SHARED PRIMITIVES first** (serial, by the orchestrator): not just CSS —
   design tokens, the ported sprite/canvas engine, the shared state/context (e.g. a window/filter
   context + its pure aggregation, unit-tested), the data-derivation helpers, AND the honesty/
   presentational primitives. Get it compiling, browser-smoke the kept-top on REAL data, then COMMIT
   it as the frozen base the fan-out reads.
2. **Create one PLACEHOLDER file per panel with the FINAL, FIXED prop signature** the shell imports,
   and wire the shell to render them. The whole app compiles + renders a skeleton immediately. Each
   fan-out agent then OVERWRITES exactly one placeholder (same export name + props) → zero shared-file
   edits during fan-out → integration becomes "tsc + browser-smoke", not "merge".
3. **Give each fan-out agent BOTH sources of truth**: the prototype span (authoritative for VISUALS —
   recreate markup/classes) AND the existing component (authoritative for BINDINGS + edge-guards +
   honesty), explicitly told to mine the latter — the prototype fabricates and lacks the guards.
4. **Two waves, not one**: a small first wave (the kept-top sections) exercises the frozen foundation
   API for real and surfaces any API gap BEFORE the larger second wave (the tabs) commits to it.
5. **Constrain each agent**: write ONLY your file (prefix any helper with your component name); no
   shared-file edits; NO `git` / `generate` / dev-server / full-build (the orchestrator compiles +
   smokes). Return terse (files + real bindings + honest-degrade decisions) — verification is tsc +
   browser-smoke, not the agent's prose.
6. **Browser-smoke on a FRESH dev server**, not the HMR console you edited against
   (`vite-hmr-transient-console-errors-verify-on-fresh-reload`).

Validated S12: 16 Opus subagents, both Token Torch surfaces pixel-perfect on real data, tsc/tests/
`generate:verify` green, one adversarial review-panel pass. The disjoint-placeholder decomposition is
what kept a 12-component fan-out collision-free.

## Notes

- The session-handoff skill's "skip splitting when tasks share files" is a safe
  *default*, not a law. This skill is the exception path when the user wants
  parallelism and the shared file is a template/view with a narrow collision
  surface.
- "Ascending risk" ≈ ascending blast radius: pure-template < template+new-routes
  < depends-on-backend / cross-run-lookup. Merge the cheap-to-rebase ones first.
- The gating-spike isn't always backend. It's whichever slice (a) others depend
  on, (b) is probe-gated, or (c) has the longest lead / highest back-compat risk.
- Don't fabricate the dependent slice's data to "unblock" it before the backend
  bakes — gate the UI on field presence and let it render "not available" on old
  records (`availability-window-gate-on-renderable-not-just-present`).

## See also

- `parallel-session-coedit-via-source-mtime-and-idempotent-rebuild` — the LIVE
  two-session variant: co-editing an assembled deliverable in real time via
  source-file mtime + a non-destructive (idempotent) rebuild — filesystem
  coordination, no git, no central orchestrator.
- `large-redesign-parallel-branch-collision-audit` — audits PRE-EXISTING branches
  that collide with a redesign's files; complementary (run both).
- `parallel-pr-scope-overlap-tiebreaker-delta-check` — two simultaneous PRs vs one
  redesign + WIP elsewhere.
- `parallel-pr-template-fork-duplicates-moved-section` — the shared-CSS /
  moved-section collision specifics.
- `inherited-scope-doc-names-may-not-exist` — why the backend gating-spike goes first and
  must bake.
- `session-handoff` (Phase 3 step 18) — the disjoint-files default this skill
  extends.
