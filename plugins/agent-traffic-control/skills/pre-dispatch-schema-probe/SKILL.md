---
name: pre-dispatch-schema-probe
description: |
  Before firing a multi-hour or multi-agent data dispatch (overnight insight runs, parallel
  subagent fleets, Cloud Run batch jobs, scheduled pipelines), run a fast 5-minute schema probe to
  verify that every dataset path, table name, and column name referenced in the plan/scope doc
  actually exists in the warehouse. Use when: (1) you inherited a scope doc authored by a
  predecessor session and are about to dispatch 2+ long-running agents or jobs based on its table
  references, (2) the plan doc mentions specific BQ paths like `project.dataset.table` or column
  names like `enrolled_2025` and you're copying them verbatim into agent prompts or SQL, (3)
  you're tempted to trust a scope doc that "looks authoritative" (prior-PR approvals,
  multi-session review history), (4) dispatch cost is $50+ or wallclock is in hours. Catches
  predecessor docs that assert dataset/column names confidently but wrongly — fabricated from
  memory or stale from a prior schema. Typical catches: a dataset path that doesn't exist
  (`project.dataset_a` instead of `project.dataset_b.dataset_a`), a label column that is
  plausible but wrong (`enrolled_2025` instead of `enrolled_segment_a`), a column-name prefix
  convention that is assumed but absent (`evt_page_visit_30d` instead of
  `page_visit_8_30d`). Related but distinct from
  `verify-plan-constants-against-data`, which covers enum/category VALUES inside columns; this
  skill covers the STRUCTURE (dataset paths, table names, column names).
author: Claude Code
version: 1.1.1
date: 2026-08-04
---

# Pre-Dispatch Schema Probe

## Problem

Scope docs and plan docs authored by predecessor sessions routinely cite specific BigQuery
paths, table names, and column names as if they were verified facts. Often they're not —
authors write from memory, from stale schema snapshots, or from hypothetical schemas that
never landed. When you mechanically copy those references into 7 parallel agent prompts and
fire them against production data, you burn the entire wallclock window discovering the
errors one at a time, mid-run.

The failure mode is costly because:

1. **Multi-agent dispatches amplify the blast radius.** 1 wrong table path × 7 agents × 10
   min before each tap-out = 70 agent-minutes of wasted compute before anyone notices.
2. **Predecessor scope docs carry authority.** A scope doc that went through multiple
   review rounds, PR approvals, and handoff sessions LOOKS authoritative. No one re-checks
   the dataset paths because "surely someone already did."
3. **Plausible-wrong > obviously-wrong.** `enrolled_2025` looks like exactly the kind
   of column name a training-features table would have. `analytics.predictions_daily.predictions_daily`
   looks like a sensible namespaced path. Both are wrong. Obviously-wrong paths (typos) fail
   loudly; plausible-wrong paths fail slowly inside agents.
4. **Column-name prefixes are assumed.** Predecessor sessions often describe engagement
   columns as "the `evt_*` family" or "the `engagement_*` columns" when the actual warehouse
   naming has no prefix at all (e.g., `page_visit_8_30d`, `login_1d`).
5. **The fix is cheap but the miss is expensive.** A 5-minute `bq ls` + `INFORMATION_SCHEMA.COLUMNS`
   probe costs <$1 and surfaces 100% of path/name errors before firing. Skipping it costs
   a full overnight window.

## Context / Trigger Conditions

Use this skill when ALL of:

- You're about to dispatch ≥2 parallel agents, Cloud Run jobs, scheduled triggers, or
  long-running Python scripts that query a data warehouse.
- The prompts / SQL / Python are being generated from a scope doc, plan doc, or handoff
  document authored in a prior session (not freshly inspected by you).
- The dispatch wallclock is measured in hours (not minutes) — i.e., the cost of mid-run
  failure is not trivial.

ALSO use when ANY of:

- The scope doc cites specific BQ paths (`project.dataset.table`), table names, or
  column names verbatim.
- The scope doc describes column families with a prefix convention ("the `evt_*` columns",
  "engagement features", "SHAP rollups") without quoting actual column names.
- The scope doc's paths involve a project-level namespace that LOOKS correct but you
  haven't personally seen a successful query against it.
- The dispatch includes INFORMATION_SCHEMA-dependent code (e.g., "select columns where
  name matches pattern X") which silently returns empty if the pattern is wrong.
- Multiple past sessions have "used v10 / table Y / column Z" without any recent session
  having actually ran `DESCRIBE` or `INFORMATION_SCHEMA.COLUMNS` against it.

## Solution — the 5-minute probe

Run ALL of these before firing anything. Budget: ~$1 BQ, ~5 minutes.

### Step 1: `bq ls` the project — verify dataset names

```bash
bq ls --max_results=100 <project>:
```

Look for the dataset(s) the scope doc references. If the scope says
`project.foo_daily.foo_daily` (namespaced), check whether `foo_daily` exists as a dataset
AND whether the same name exists as a table inside some *other* dataset. Common failure:
scope treats the project-level path as the dataset when actually the dataset is something
different (`ml_predictions.predictions_daily` vs fictional `predictions_daily.predictions_daily`).

### Step 2: `bq ls` each dataset — verify table names

```bash
bq ls --max_results=50 <project>:<dataset>
```

Confirm the exact table names. Watch for: version suffixes (`_v2`, `_enriched`, `_daily`
vs. singular), archived-vs-live (`_archive`, `_deprecated`), partition hints in the table
name.

### Step 3: `INFORMATION_SCHEMA.COLUMNS` — verify column names and types

For each table you'll query:

```sql
SELECT column_name, data_type
FROM `<project>.<dataset>.INFORMATION_SCHEMA.COLUMNS`
WHERE table_name = '<table>'
ORDER BY ordinal_position
```

Redirect to a file and grep for the exact names the scope doc uses. If the scope says
"column `enrolled_2025`" — grep for it. If not found, widen: `grep -i enroll` and
see what the actual naming is.

### Step 4: Verify prefix / pattern assumptions with a distinct-count

If the scope describes a column family by prefix ("the `evt_*` family has ~60 columns"),
run:

```sql
SELECT COUNT(*)
FROM `<project>.<dataset>.INFORMATION_SCHEMA.COLUMNS`
WHERE table_name = '<table>'
  AND column_name LIKE 'evt_%'  -- whatever prefix the scope claims
```

If the count is 0 or nowhere near the claimed count, the prefix assumption is wrong. Run
an open-ended list of actual column names to see the real naming convention.

### Step 5: Record findings in a state file

Write `state/phase_0_probe_results.md` (or equivalent) with, per-table:

- ✓ PASS / 🔧 CORRECTED / ❌ BLOCKED
- Exact path used in the probe
- Row/column counts
- Any corrections the scope doc needs
- SQL queries, for reproducibility

This is the artefact future sessions (and reviewers) will trust instead of the scope doc
for these facts.

### Step 5.5 (Phase 0.Z): Label-tag check — STRICT mode

The structural probe (steps 1-4) verifies that paths/tables/columns exist.
A different failure mode survives that probe: scope docs that supply
**human-readable labels** for codes/enums whose values DO exist in the warehouse
but whose meanings have been guessed from memory. Value-coverage probes pass
100% (the codes are real) but the labels are fabricated, and they ship into
client-facing UI strings, dropdown labels, and SQL CASE branches.

This step blocks dispatch when any unverified code-legend table appears in the
scope doc, track prompts, or orchestrator prompt. **No escape hatch** —
multi-hour, $50+ dispatches don't get to skip this; the friction of resolving
the tags is rounding error vs. a wrong-label run.

```bash
# For each track prompt + the orchestrator prompt + the scope doc:
for f in <scope.md> <orchestrator-prompt.md> <track-prompts/*.md>; do
  python3 <path-to>/session-handoff/scripts/label_audit.py \
    --strict --repo-root "$(git rev-parse --show-toplevel)" "$f" || exit 1
done
```

**Strict-mode behavior** (vs. the loose mode used by the `session-handoff` Phase 0 pass):

1. **Domain-noun cue required.** A code-shape table only flags when prose
   nearby contains one of: `status`, `code`, `category`, `enum`, `stage`,
   `bucket`, `tier`, `type`, `class`, `flag`, `kind`, `level` (singular and
   plural variants, case-insensitive). Strict mode trades a small chance of
   false negatives for substantially fewer false positives during multi-track
   dispatch authoring.
2. **No `label-audit-skipped:` frontmatter escape hatch** — strict mode
   ignores it entirely.
3. **Citation re-resolution.** Every `[verified: <repo-rel-path>:<line>]` tag
   is resolved via `git show HEAD:<file>` against the live repo. If the file
   has moved, the line has shifted past EOF, or the path no longer exists at
   HEAD, dispatch is blocked with "stale citation — re-verify and update tag."

**Required tag formats:**

- `[verified: <repo-relative-path>:<line>]` — citation to authoritative source
  (vendor doc, INFORMATION_SCHEMA result, internal data dictionary)
- `[HYPOTHESIS]` — explicit acknowledgment that the label is a guess; the
  receiving session re-probes before relying on it

**Exit codes:** 0 (clean), 1 (blocking — untagged or stale citation). No
"skipped" status in strict mode.

**Why this is separate from the steps above.** Steps 1-4 cover STRUCTURE
(does this column exist?). This step covers SEMANTICS (does this label match
the source-system meaning?). A scope doc can pass the structural probe and
still ship a "Status code legend" where every label is wrong. The worked
example that motivated this gate: a scope doc passed the full structural probe
(every status code in the legend was a real value present in the warehouse) yet
every human-readable label paired with those codes had been guessed from memory
and was wrong — and those labels were headed straight into client-facing UI
strings.

### Step 6: Apply corrections in-place

Either:

- **Edit the scope doc** with the corrected paths/names, note the correction inline
  (`was X, corrected to Y per probe on YYYY-MM-DD`), and regenerate any scaffolding that
  embedded the wrong value.
- **Document corrections in a handoff file** (`session_N_prompt.md`) that the dispatching
  session will read alongside the scope doc.

Either way, do NOT dispatch with the wrong values still in any agent prompt.

## Verification

After probing, you should have:

- A state file listing every dataset/table/column the dispatch references, each marked
  PASS or CORRECTED.
- Scope-doc edits (or an addendum file) with the corrections applied.
- Agent prompts or SQL regenerated against the corrected paths (grep your prompts for the
  old wrong paths and replace).
- Confidence that firing won't tap out on the first bq query.

A good proxy for "done": a lightweight end-to-end smoke query — `SELECT COUNT(*) FROM
<full.corrected.path> WHERE <filter>` against one panel — runs cleanly and returns a
plausible count.

## Example

**Scenario:** a propensity-modeling project. A predecessor session authored a v6 scope doc
claiming:
- Historical scored panels at `analytics.predictions_daily.predictions_daily`
- Label column `enrolled_2025`
- Engagement columns follow an `evt_*` prefix pattern

**Probe:**

```bash
bq ls --max_results=100 analytics:
# → lists 16 datasets; NO dataset called `predictions_daily`
# → DOES have `ml_predictions`

bq ls --max_results=30 analytics:ml_predictions
# → includes `predictions_daily` (partitioned by scoring_date)
# → Correct path is ml_predictions.predictions_daily

bq query --use_legacy_sql=false "SELECT column_name FROM \`analytics.ml_features.INFORMATION_SCHEMA.COLUMNS\` WHERE table_name='v10_training_features' AND column_name LIKE '%enroll%'"
# → Returns enrolled_segment_a, enrolled_segment_b, enrolled_segment_c
# → NOT enrolled_2025 (doesn't exist)

bq query --use_legacy_sql=false "SELECT COUNT(*) FROM \`analytics.ml_features.INFORMATION_SCHEMA.COLUMNS\` WHERE table_name='v10_training_features' AND column_name LIKE 'evt_%'"
# → 0 rows
# → evt_* prefix assumption wrong; actual pattern is {event_type}_{window}d
```

**Result:** 3 corrections surfaced in ~5 min at <$1 BQ. Had 7 parallel agents fired with
the scope-doc paths, all 7 would have tapped out on first bq query.

## Notes

- **This skill is about STRUCTURE; `verify-plan-constants-against-data` is about CONTENT.**
  That skill catches wrong enum VALUES inside a correctly-named column. This one catches
  wrong dataset/table/column NAMES. Run both before dispatch if both layers apply.
- **Cost scales with dispatch size, not probe size.** The probe is the same 5 minutes
  whether you're firing 2 agents or 20. For small 1-agent sessions, the probe is
  often overkill; for 5+ agent sessions, it's essential.
- **Predecessor sessions may have "successfully used" a table name by never actually
  running a query against it.** Code review or handoff confirmation isn't evidence of
  data alignment. Only an actual SELECT query is.
- **Watch for "the dataset used to be called X" drift.** Projects rename datasets during
  refactors; scope docs authored before the rename carry the old name. `bq ls` shows the
  current truth.
- **Archive the probe as a reproducible artefact.** Future sessions re-running the same
  dispatch can re-run the probe in 30 seconds to re-verify; don't re-invent it.

## See also

- `verify-plan-constants-against-data` — for wrong enum VALUES inside columns (complementary)
- `bq-identity-resolution-debug` — for identity-join drift across datasets
- `sf-bq-upsert-verify-before-createddate-gate` — for import-mode drift in CRM→BQ pipelines

## References

- BigQuery `INFORMATION_SCHEMA` reference: https://cloud.google.com/bigquery/docs/information-schema-intro
- `bq ls` command reference: https://cloud.google.com/bigquery/docs/bq-command-line-tool#listing-datasets
