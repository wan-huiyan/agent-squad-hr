---
name: stale-base-pr-silently-reverts-upstream-content
description: |
  Detect and recover when a sibling PR's squash-merge silently reverts an
  upstream PR's content changes because the sibling was based on a pre-upstream
  main snapshot and its line-level rewrites overlapped the upstream PR's edits.
  Use when: (1) two PRs are open in parallel against the same file(s) — one
  refreshing numbers/values, the other rewriting copy/language, (2) the
  number-refresh PR merges first, the language-rewrite PR merges second, (3)
  the language-rewrite PR claims "all numbers preserved" in its body — true
  against ITS base, not against post-upstream-merge main, (4) post-merge of
  the second PR, displayed numbers regress to pre-fix values while OTHER files
  in the same upstream PR (untouched by the second PR) still hold the new
  values — creating a train-serve / display-vs-backend mismatch, (5) CI on
  both PRs was green and `mergeable: MERGEABLE` because git's 3-way merge
  resolves textual overlap silently (it does not see "numbers vs language"
  semantics). Detection: grep upstream PR's distinctive strings on post-merge
  main and compare to upstream PR's intended diff. Recovery: targeted re-apply
  of upstream values on top of sibling's voice, preserving both PRs' intent.
  Sister to `parallel-pr-template-fork-duplicates-moved-section` (duplication
  via mover/forker — different files); this skill covers REVERSION via
  textual overlap on the SAME file. Sister to `pr-conflict-from-mid-flight-merges`
  (covers PR-side detection — your PR turns DIRTY before merge); this skill
  covers the post-merge silent-regression case where NEITHER PR's CI flagged
  the overwrite.
author: Claude Code
version: 1.1.0
date: 2026-05-14
disable-model-invocation: true
---

# Stale-Base PR Silently Reverts Upstream Content via Textual Overlap

## Problem

You ship PR A: updates 8 specific lines in `templates/foo.html` with new
numbers (`50% vs 6%`, `n=117`, etc.). PR A merges cleanly. CI green.

In parallel, PR B was opened against `origin/main` BEFORE PR A merged. PR B
rewrites copy in the same file for language polish — touching the same 8
lines, but with the OLD numbers (because that's what PR B's base showed).
PR B's body claims "all numbers preserved."

PR B rebases / `gh pr merge --squash`s after PR A. Git's 3-way merge runs:
- **Base** (common ancestor): old text + OLD numbers
- **Main side** (post-PR-A): old text + **NEW** numbers ← PR A's contribution
- **PR B side**: rewritten text + OLD numbers ← PR B's contribution

For lines where PR B's rewrite spans the same text PR A edited, the 3-way
merge sees PR B as the "winning" branch-side and takes PR B's version
wholesale. **PR A's numbers silently disappear from those lines.** Other
files PR A touched but PR B didn't (`app.py`, `intelligence_findings.js`,
`library_findings.html`) keep PR A's numbers intact.

Result: a **train-serve / display-vs-backend mismatch** that no PR diff,
no CI signal, and no merge conflict flagged. PR B's author was honest — the
numbers WERE preserved against THEIR base. The regression is invisible
until someone audits the post-merge main against PR A's intended diff.

## Context / Trigger Conditions

All of these typically hold:

1. **Two PRs open in parallel** on the same file(s) — one updates values
   (numbers, names, IDs, configuration), the other polishes copy / language /
   structure.
2. **Value-refresh PR (A) merges first.** Often a data-correctness or
   recalibration PR.
3. **Language-polish PR (B) is based on pre-A main.** Detect via:
   ```bash
   gh pr view <B> --json baseRefOid
   # vs.
   gh pr view <A> --json mergeCommit
   ```
   If B's base predates A's merge commit, B has a stale base.
4. **PR B's body claims "X preserved"** — true against its base, but the
   base is stale. Common phrases: "all numbers preserved", "zero logic
   changes", "preserves all findings".
5. **No merge conflict on `gh pr merge`**: git resolves the textual overlap
   silently. Both PRs show `mergeable: MERGEABLE`, CI on both is green.
6. **Post-merge: only files BOTH PRs touched are affected.** Files only PR A
   touched stay correct (no overlap to resolve). This produces the tell-tale
   train-serve mismatch where backend constants match PR A's intent but
   displayed copy in the overlapped template doesn't.

Adjacent symptoms:
- User-reported "the numbers look wrong" but recent backend changes look fine
- `app.py` / config / JS module constants match the new values, but rendered
  HTML displays old values
- Backend test fixtures (numbers in `_COLD_OPEN`/`_CONSTANTS` dicts) match A;
  template snapshot tests / display tests use B's rewritten copy with old
  numbers
- The cohort-size discrepancy is small enough not to look like a bug at a
  glance (e.g. `50%` → `48%`, `n=117` → `n=408`)

## Variant: Complete-File Stale-Base Revert

A more severe form where PR A does a **wholesale file rewrite** (hundreds of
lines added/removed, entirely new structure) and PR B's stale version of the
same file is the old design. The merge doesn't revert N specific lines — it
restores the entire pre-PR-A file to the live template.

**Additional trigger conditions for this variant:**

- PR A was a full template rewrite (e.g. 900+ net lines, new HTML structure,
  new CSS class names, new section layout) — not just value updates.
- PR B's description focuses on OTHER files (tab strip, index grid, CSS
  constants) and only mentions the shared file incidentally ("fixed CSS
  grid" / "extracted inline styles") — no mention of structural changes.
- PR B's git stat for the shared file shows a large `++++--` pattern
  (`1155 +++++---------------`) but the net effect restores the old design.

**Detection signals (different from partial-overlap variant):**

- User reports "I don't see PR A's changes in the live dashboard" — the
  symptom is a COMPLETE absence of the new design, not a subtle value mismatch.
  Initial suspicion is usually deploy lag or browser cache (check those first);
  if the revision is confirmed serving the post-B-merge image, look for revert.
- `git diff <PR-A-merge>..origin/main -- <file>` shows the net effect is
  removing ALL of PR A's additions and restoring pre-PR-A content:
  ```bash
  git diff 09ea9b7d..bf5fb3e6 -- templates/library_roadmap.html | grep "^-" | wc -l
  # Returns ~911 lines removed (PR A's entire new design)
  ```
- The rendered page has the old layout, old section structure, and old CSS
  class names — not just stale numbers within new copy.

**Recovery for complete-file revert (different from partial-overlap):**

When PR B's version of the file IS the pre-PR-A file, targeted line edits
will not work — there are too many missing lines. Instead:

```bash
git worktree add .claude/worktrees/recover-A-after-B -b fix/recover-A-after-B origin/main
# Restore PR A's entire file state
git checkout <PR-A-merge-commit> -- path/to/template.html
# Then apply PR B's LEGITIMATE changes to that file (the minor CSS fixes etc.)
# Read PR B's diff for the specific file to identify what, if anything, was
# a genuine improvement vs. stale-base artifact
git diff <pre-B-base>..<PR-B-merge> -- path/to/template.html | grep "^+" | head -30
```

Note: the existing Step 3 says "Do NOT `git checkout <PR-A-merge> -- file`"
— that rule applies to partial-overlap reverts where PR B had legitimate
structural changes. For complete-file reverts where PR B's file = pre-PR-A
content, restoring PR A's file wholesale is the right approach; then layer
PR B's genuine improvements on top.

## Solution

### Step 1 — Confirm the regression

Run a **content audit** on post-merge `origin/main`:

```bash
# Grep upstream PR (A)'s distinctive strings on the affected file
git fetch origin main --quiet
git show origin/main:path/to/affected.html | grep -nE 'newVal1|newVal2|newVal3'
# Compare to PR A's intended state (the merge commit just after A merged)
git show <PR-A-merge-commit>:path/to/affected.html | grep -nE 'newVal1|newVal2|newVal3'
```

If the merge-commit version had N matches and post-B-merge main has M < N,
the regression is real. The missing matches are the reverted lines.

Also confirm "other files survived":

```bash
# Files PR A touched but PR B didn't should still match A's intent
git diff <PR-A-merge-commit>..origin/main -- path/to/other-file.py
# Empty diff = clean survival
```

### Step 2 — Inventory the lost edits

For each affected file, list the lines where PR A's values are missing:

```bash
git diff <pre-A-base>..<PR-A-merge-commit> -- path/to/affected.html
```

This shows the PR A diff. Cross-reference each `-/+` pair against current
post-B-merge main to find the regressed ones.

Build a table:

| # | Line | Post-B-merge (regressed) | PR A's intended | Notes |
|---|------|---|---|---|
| 1 | #237 | "based on 448 records" | "+ n=448 + 6,483-control" | Lost reproduction context |
| 2 | #354 | `48% vs 5%` | `50% vs 6%` | Lost number refresh |
| ... | ... | ... | ... | ... |

### Step 3 — Recover by targeted re-apply, NOT revert

**Do NOT** `git revert <PR-B-merge>` — that nukes the language polish too,
losing legitimate work. **Do NOT** `git checkout <PR-A-merge> -- file` —
that overwrites PR B's polish.

Instead: open a fresh worktree off latest main, then make targeted edits
that restore PR A's values WITHIN PR B's rewritten text:

```bash
git worktree add .claude/worktrees/recover-A-after-B -b fix/recover-A-after-B origin/main
cd .claude/worktrees/recover-A-after-B
# Apply N targeted Edit operations, one per regressed line
# Keep PR B's voice/structure intact; only swap the values back
```

For each regressed line:
- Find the new (post-B-merge) text via Read
- Construct an Edit that swaps the OLD value to A's NEW value, keeping the
  surrounding sentence/structure verbatim
- Add a brief context sentence if PR A had carried additional explanation
  text (e.g., "reproduces against post-S171b-backfill data per ADR-0033")

### Step 4 — Test for pre-existing failures vs new

Run the file's owning tests:

```bash
pytest path/to/tests/ -q
```

If failures appear: check if they're pre-existing on `origin/main` by
stashing and re-running on clean main:

```bash
git stash
pytest path/to/tests/ -q
git stash pop
```

If the same tests fail on clean main, they're pre-existing (PR B's polish
broke them, not your recovery). Note in PR body but don't try to fix as
part of recovery.

### Step 5 — Open recovery PR

Title: `fix(<area>): restore <PR-A> values reverted by #<PR-B> stale-base merge`

Body should include:
- Inventory table from Step 2 (regressed line → restored value)
- One-paragraph explanation of WHY it happened (stale base, textual overlap,
  3-way merge silently took B's side)
- The lesson section (see Step 6) so future readers can recognize it
- Test plan referencing the stash/re-run verification

### Step 6 — File-level prevention going forward

After landing the recovery PR, consider:

- A **content-audit check** in CI that grep-verifies anchor strings from
  recently-merged PRs against current main on a sample of templates
- An add-on to the codebase's PR template asking "did you rebase
  against latest main before pushing?" for copy/template PRs
- Adding `value-anchor`-style HTML attributes (`data-rate-a2="50"`)
  that can be unit-tested for value consistency vs the backend constants

## Verification

After Step 5 merges:

```bash
git fetch origin main --quiet
git show origin/main:path/to/affected.html | grep -cE 'newVal1|newVal2|newVal3'
# Should equal the count from <PR-A-merge-commit>
```

And the backend / display consistency check:

```bash
# For each (constant_name, value) pair in backend
grep -E "constant.*newValN" backend/file.py templates/affected.html
# Both files should contain the same value
```

## Example — the project /actions Phase D D.4 + #759 polish (S180+, 2026-05-12)

**Setup**: PR #751 refreshed A2 (`48% → 50%`, `5% → 6%`) and A3
(`4.9% → 6.0%`, `48.3% → 50.5%`, `n=408 → n=117`) post-S171b-backfill
numbers in `templates/actions.html`, `app.py`, `intelligence_findings.js`,
`library_findings.html`. Merged at 11:20:09Z.

PR #759 ("simplify copy for stakeholder readability") was based on
pre-#751 main. Its body claimed "All numbers preserved." Merged at
12:24:15Z, 64 minutes after #751.

**Detection (~3 min post-#759-merge)** via user-prompted content audit:

```bash
git show origin/main:templates/actions.html | grep -E '50%|6.0%|n=117|8× the rate|6,483-record'
# Returned: nothing for the A2/A3 lines, only A1 line had the new context — that's the regression signal
```

**Files affected**:
- `templates/actions.html`: 8 reverted lines (regressed)
- `app.py`, `intelligence_findings.js`, `library_findings.html`: untouched
  by #759, kept PR #751's values (clean survival)

**Result**: train-serve mismatch — backend constants in `app.py`
`_ACTIONS_COLD_OPEN_HISTORICAL` and JS chart data showed `A2=50%/6%,
A3=117/6%/50%`, but template copy showed `A2=48%/5%, A3=4.9%/48.3%`.

**Recovery**: 8 targeted Edit operations on `templates/actions.html` that
preserved #759's plain-English voice (`"roughly 8× the rate"`,
`"about the same as"`, conversational tone) while restoring the
post-fix numbers. Shipped as PR #760, MERGED at 11:34:25Z (~10 min after
detection). Tracker entry `cat7-7jf`.

**Lesson**: a PR body claiming "X preserved" is true against ITS BASE.
With stale-base 3-way merges, "preserved" against the base ≠ "preserved"
against post-rebase main. Always content-audit recent number-touching
merges against the current main post-sibling-merge. The cost is one
`git show + grep` invocation; the alternative is a silent regression
that takes longer to detect than to prevent.

## Example — the project /library/roadmap visual rewrite reverted by polish PR (2026-05-14)

**Setup**: PR #848 (`feat(library): visual refresh of /library/roadmap from design bundle`)
was a wholesale rewrite of `templates/library_roadmap.html` (+1155/-258 lines):
new `roadmap-hero` header with engagement-balance aside (98h/10h/20h), Beat 01
"recently shipped" section (9 theme cards), Beat 02 gap illustration with filmstrip/
polaroid layout, phase-chain SVG, and version timeline. Merged at 00:21:47Z.

PR #850 (`style(library): impeccable polish pass — tier index cards, distil tabs 8→5`)
was developed from a base that predated #848. Its description focused on library index
tiers, tab-strip reduction (8→5), and model-health text-size fixes. Roadmap was
mentioned only as a CSS grid-column fix ("fixed `grid-template-columns` to base
`.library-index-grid`"). PR #850's `library_roadmap.html` was the pre-#848 file.
Merged at 00:53:40Z, ~32 minutes after #848.

**Detection**: User reported "I merged PR #848 but don't see its changes in the live
dashboard." Initial check confirmed revision `the-dashboard-service-00148-cql`
(PR #850's image `bf5fb3e`) was serving 100% of traffic — deploy was correct. Browser
cache was the first suspect; but the deploy log also showed PR #850 was the most recent
deploy. Investigation of `git diff 09ea9b7d bf5fb3e6 -- templates/library_roadmap.html`
revealed 911 lines removed — PR A's entire new design gone.

**Distinguishing signal from partial-overlap variant**: the symptom was "entire page
looks completely different / PR A's design absent" rather than "specific numbers look
wrong." The PR #850 stat line (`1155 +++++---------------`) looked like a big edit but
the net was a near-total revert. PR description gave no hint of structural change.

**Recovery**: `git checkout 09ea9b7d -- templates/library_roadmap.html` to restore PR
A's full template, then apply PR B's legitimate CSS grid fix (`grid-template-columns`)
on top. Separate fix PR opened by the original session.

**Lesson**: When a PR with a misleading "polish pass" label touches a file another PR
recently rewrote, immediately diff the net effect — `git diff <A>..HEAD -- <file>` —
before shipping. A `1155 +++++---------------` stat on a file that just got a 1155-line
rewrite in the prior PR is the tell.

## Notes

- The same pattern fires for **non-numerical content**: config keys,
  enum values, route paths, role names, copy-link labels — anywhere PR A
  changes values within text that PR B independently rewrites.
- Detection is harder when **both** PRs change content. If PR B legitimately
  swaps numbers (e.g. updates one metric while polishing another), the
  audit must be field-by-field rather than file-level.
- `gh pr view --json files` won't surface this — both PRs declared the
  same file changed. The detection signal is **content-level**, not
  file-level.
- Tools that DO catch this: snapshot tests on the template render; visual
  regression diffs; explicit lockstep tests like
  `test_registry_brief_lockstep_with_template_strong` (which existed but
  was on the pre-existing-failure list at the time of #759 — illustrative
  of why test discipline matters).
- **Why git's 3-way merge picked B over A for the overlapping lines**:
  when A's edit is `value-only` (one number swap) and B's edit is
  `structure + value`, git's default recursive strategy treats B's edit
  as the broader change and resolves to B. There's no flag to invert this
  reliably; it's a content-aware decision git can't make.
- Cross-link to `pr-conflict-site-regen` v1.8.0+: that skill
  covers tracker / site-regen file conflicts (mechanical, generator-driven).
  This skill is its content-level cousin (human-authored, semantic).

## References

- `pr-conflict-site-regen/SKILL.md` — tracker/site-regen file
  conflict playbook (Step 2a/2c/2d/2e for IDs; this skill is the parallel
  for content)
- `parallel-pr-template-fork-duplicates-moved-section/SKILL.md` —
  duplication via mover/forker (different files, same block); contrast
  with this skill's overlap-and-revert (same file, different intent)
- `pr-conflict-from-mid-flight-merges/SKILL.md` — PR-side detection
  before merge; this skill is the post-merge case where the merge
  didn't surface a conflict
