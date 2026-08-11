---
name: parallel-pr-template-fork-duplicates-moved-section
description: |
  Diagnose silent semantic duplication after two parallel PRs ship. Use when:
  (1) one PR (the **mover**) relocates a section/component/block from template
  X to template Y (X loses it, Y gains it), (2) a sibling PR (the **forker**),
  authored against pre-mover main, creates / promotes / copies template Z from
  the OLD version of X (when X still contained the section), (3) both PRs
  squash-merge without textual conflict because they touch different files,
  (4) after both deploy, the section appears on BOTH the mover's destination
  Y AND on the forker's route Z. Symptom is user-visible: "I see this radar /
  card / nav block in two places, why?" Root cause is structural — git's
  textual 3-way merge can't see that file Z ⊆ pre-mover-X. Fix: hand-delete
  the section from one location (usually the forker's), update tests if any
  asserted on the duplicate render. Prevention: when the mover merges first,
  rebase the forker BEFORE squash and audit any moved sections; or add a
  cross-route uniqueness test (`grep -c "<section-id>"` across primary
  routes ≤ 1). Sibling to `route-orphan-fetch-after-template-carveout`
  (covers within-PR template/handler drift; this skill covers across-PR
  template duplication).
author: Claude Code
version: 1.0.0
date: 2026-05-07
disable-model-invocation: true
---

# Parallel-PR Template Fork Duplicates Moved Section

## Problem

Two PRs ship within hours of each other. Neither shows a textual merge
conflict. Both pass tests. Both deploy cleanly. After deploy, a user reports
"this section is appearing in two places now — that's wrong, right?"

The mechanism is structural, not textual:

- **PR #A (mover)**: relocates a `<section>...</section>` from template `X.html`
  to template `Y.html`. `X` loses the block; `Y` gains it.
- **PR #B (forker)**: promotes / copies / forks `X.html` into a new template
  `Z.html` (e.g., the route is moving up in the IA, or the page is being
  split). The fork is literal — `Z.html` was authored as a near-copy of `X.html`
  *as it existed before the mover landed*.
- The two PRs touch *different files* on disk. Squash-merge is "clean" by
  git's textual measure: `X` lost a block (mover), `Y` gained it (mover), `Z`
  was added (forker). No 3-way merge conflict.
- Reality: `Z` was forked from a snapshot of `X` that *still contained* the
  section. So after both ship, the block lives in BOTH `Y` and `Z`.

The user sees the duplication immediately. Code review on each PR in isolation
wouldn't have caught it — each diff was correct against its own base.

## Trigger conditions

ALL of these are typically true:

1. Two PRs merged to main within a short window (hours / a day), authored
   independently.
2. One PR's diff includes lines that look like "move section from X to Y" —
   classic markers: deletion in one template, equivalent insertion in another,
   plus a comment saying "moved per IA brief §N" or similar.
3. The other PR's diff includes "create new template Z" or "rename X → Z"
   where the `+` lines for Z look very similar to (or are a literal copy of)
   the *pre-mover* version of X.
4. Neither PR's branch was rebased onto the other after both were opened.
5. User-visible symptom: rendered HTML on two different routes contains the
   same heading / chart / SVG / id (e.g., `<h2>Feature Snapshot</h2>` or
   `id="feature-radar-chart"` appears on `/route-y` AND `/route-z`).
6. Tests still pass because each route's tests were authored to assert on
   their own template; cross-route uniqueness wasn't part of the contract.

## Diagnostic — confirm the duplication

```sh
# 1. Identify the moved section's stable identifier (id / class / heading text).
SECTION_ID="feature-radar-chart"   # or "<h2>Feature Snapshot</h2>" etc.

# 2. Grep ALL templates for that identifier on main HEAD.
grep -rln "$SECTION_ID" path/to/templates/

# Expected pre-incident: exactly 1 hit (the mover's destination).
# Incident: 2+ hits (mover's destination AND forker's new template).

# 3. Confirm via rendered HTML with the framework's test client (mock mode):
python3 -c "
from app import app
with app.test_client() as c:
    for route in ['/route-y', '/route-z', '/legacy-x']:
        r = c.get(route)
        n = r.data.decode().count('$SECTION_ID')
        print(f'{route}: count={n}')
"
# Want: exactly one route renders count=1; others = 0.
# Incident: two routes render count=1.
```

If grep shows the identifier in two templates AND two routes render it,
you've reproduced the duplication.

### Confirm timing — was this really the parallel-PR pattern?

```sh
# Find the mover and the forker by timeline:
gh pr list --repo OWNER/REPO --state merged --limit 30 \
  --json number,title,mergedAt,files \
  --jq '.[] | "\(.mergedAt)  #\(.number)  \(.title)"' | head -20

# Look for two PRs merged close in time where:
#   - one says "move/relocate X" or "promote X to Y"
#   - the other says "fork/copy X to Z" or "promote X to top-level"
```

The forker is usually the one that copy-pasted from a stale base. The mover
is usually first by merge timestamp (because the forker would have noticed
the conflict if it were the other way around).

## Fix

**Hand-delete the duplicate from one location.** Usually the forker's
template — because the mover's destination is the canonical home of the
section per the new IA.

```diff
- <h2>Feature Snapshot</h2>
- <p>Compare up to six pipeline-stage segments...</p>
- <div id="feature-radar-chart" class="radar-chart"></div>
+ {# Section moved to <Y.html> by PR #A (#mover-issue). The earlier PR #B
+    (#forker-issue) inherited an older snapshot before the move — drop
+    the orphan section here so it lives only on the canonical route. #}
```

If any tests assert on the duplicate render (e.g., a test for `/route-z`
that calls `assert "Feature Snapshot" in html`), update them too.

If a downstream JS bootstrap (e.g., `radar.js` self-bootstraps on
`document.getElementById('feature-radar-chart')`) was relying on the duplicate
for some reason, check that the JS still finds its target on the canonical
route only.

## Verification

```sh
# Re-run the diagnostic. Want exactly one template + one route now.
grep -rln "$SECTION_ID" path/to/templates/   # → 1 file
python3 -c "..."                              # → 1 route renders, others 0

# Run cross-cutting route tests to make sure no regressions:
pytest tests/test_<route_y>.py tests/test_<route_z>.py
```

## Prevention

Three layers, in order of cheapness:

1. **Rebase the forker** onto current main BEFORE squash-merging if any other
   PR touched a related file in the interim. The squash-merge command's
   "Mergeable" indicator is a TEXTUAL check; it does NOT detect
   semantic-section duplication.

2. **Add a cross-route uniqueness invariant test** for any section/component
   that has a single canonical home:

   ```python
   # tests/test_unique_sections.py
   import pytest
   PRIMARY_ROUTES = ["/", "/actions", "/drivers", "/monitor", "/library/explorer", ...]
   UNIQUE_SECTIONS = {
       "Feature Snapshot": "/library/explorer",
       "Pipeline by Score": "/",
       # ...
   }

   @pytest.mark.parametrize("title,canonical", UNIQUE_SECTIONS.items())
   def test_section_appears_on_canonical_route_only(client, title, canonical):
       hits = []
       for route in PRIMARY_ROUTES:
           if title in client.get(route).data.decode():
               hits.append(route)
       assert hits == [canonical], (
           f"{title!r} should appear only on {canonical}, found on: {hits}"
       )
   ```

   This invariant catches the duplication at PR-CI time, regardless of which
   PR gets merged first.

3. **PR-author audit checklist** when promoting / forking a template: search
   the most recent N merges to main for any "move section X to file Y"
   patterns. If any apply to the source template you're forking, port the
   move forward in your PR.

## Worked example (a client analytics dashboard, 2026-05-07)

Architecture:
- `the-dashboard-service` Cloud Run service serves multiple dashboard routes.
- Sidebar IA went through Phase 5 (4 tabs) → Phase 6 (5 tabs: Overview /
  Actions / Drivers / Monitor / Library) over ~24h via 4 PRs.

Two of those PRs collided semantically:

- **PR #296 (mover, merged 2026-05-06 21:01 UTC)**: "Move Feature Snapshot
  radar /library/methods → /library/explorer." Removed `<h2>Feature Snapshot</h2>`
  + radar `<div>` from `library_methods.html`; added them to `library_explorer.html`.
- **PR #303 (forker, merged 2026-05-06 23:48 UTC)**: "Promote Methods page to
  top-level Drivers tab." Created new `drivers.html` as a near-copy of the
  *pre-#296* `library_methods.html` (which still had the radar block).
  Also flipped `/library/methods` to a 302-redirect handler (→ `/drivers`).

GitHub squash-merge of #303 reported "Mergeable" because the textual diff was:
- `+ templates/drivers.html` (new file)
- `- {old library_methods.html content}` / `+ {redirect handler}` (in `app.py`)
- `~ templates/library_methods.html` (other minor changes)

No textual collision with `library_explorer.html` (which #296 had modified).
Result: `/library/explorer` shows the radar (PR #296 ✓), and `/drivers` ALSO
shows the radar (PR #303's literal copy of pre-#296 `library_methods.html`).

User-visible: "this looks nothing like the mockup; I see Feature Snapshot
twice." Tests stayed green because each route had its own test file and
neither asserted cross-route uniqueness.

Diagnostic:
```sh
grep -rln 'feature-radar-chart' <analytics_pkg>/cloudrun/<dashboard_app>/templates/
# → drivers.html       (incident)
# → library_explorer.html
```

Render confirmation:
```python
DASHBOARD_USE_MOCK=true python3 -c "
from app import app
with app.test_client() as c:
    for r in ['/drivers', '/library/explorer']:
        h = c.get(r).data.decode()
        print(r, 'count:', h.count('feature-radar-chart'))
"
# /drivers count: 1
# /library/explorer count: 1
```

Fix: deleted the radar `<div>` block from `drivers.html` (lines 90-103),
replaced with a `{# moved to /library/explorer per IA brief / PR #296 #}`
comment. Drive-by: updated `test_library_methods_does_not_call_get_feature_snapshot`
to expect the post-#303 redirect-shape (302 → /drivers) instead of the stale
200 it had.

Shipped as PR #317 (cat7-7dq), squash-merged + redeployed pulse rev
`00010-bt2`. Post-fix render: `/drivers` count = 0; `/library/explorer`
count = 1.

## Notes

- **Why git can't catch this**: 3-way merge operates on file-level diffs.
  When PR #B forks file X to a new file Z, git's view is "Z is a new file";
  it doesn't know Z's content was copy-pasted from a snapshot of X. So when
  the merge base of PR #A doesn't intersect with Z's lifetime, there's no
  diff to conflict on. Fundamentally a limitation of textual diff vs.
  semantic equivalence.
- **Most fragile during IA reorganizations**: the duplication risk is highest
  when multiple PRs are reshaping the navigation/IA in parallel — each PR
  thinks it owns "the" canonical home for a component, and the timing of
  who-merges-first determines which view wins.
- **Squash-merge intensifies the problem**: a non-squash merge would carry
  forward each constituent commit, and the rebase step before merge would
  surface conflicts. Squash-merge collapses everything into a single textual
  diff at merge time, making the semantic comparison even harder.
- **Code review caveat**: each PR's reviewer is looking at THAT PR's diff
  against THAT PR's base. There's no point in the review process where both
  PRs' diffs are inspected together — that's exactly when semantic
  duplication would be visible.
- **Don't blame the squash-merge feature**: the same pattern can happen with
  rebase-and-merge or merge-commit strategies. The root cause is "fork from
  stale base, sibling PR moves something out of the fork's source." Squash
  just makes detection harder.

## Sister skills

- `pr-conflict-from-mid-flight-merges` — the textual sibling: two PRs touch
  the same lines and git flags `mergeStateStatus: DIRTY`. This skill
  documents the silent (non-textual) failure mode of the same scenario.

## References

- Git's three-way merge limitation:
  https://git-scm.com/docs/git-merge-base#_discussion (merge base behavior
  on disjoint trees, applicable when a fork creates a new file path).
- GitHub squash-merge mechanics:
  https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/incorporating-changes-from-a-pull-request/about-pull-request-merges#squash-and-merge-your-commits
