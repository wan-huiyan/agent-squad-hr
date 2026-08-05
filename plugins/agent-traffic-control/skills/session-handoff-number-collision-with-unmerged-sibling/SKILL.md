---
name: session-handoff-number-collision-with-unmerged-sibling
description: |
  Detect and recover from a session-number collision when running session-handoff
  and a parallel/sibling session has authored a same-numbered handoff doc that
  hasn't merged into main yet. Use when: (1) you're in `session-handoff` Phase 1
  about to write `docs/handoffs/session_NNN_handoff.md`, (2) `ls docs/handoffs/`
  shows the highest number is N-1 (so you pick N), BUT (3) MEMORY.md "Recent
  sessions" or sessions_archive.md already contains a `session_NNN_*.md` entry
  pointing at another worktree's branch whose PR hasn't merged. Symptom: you
  create files that don't collide on disk (the sibling's files live on a
  separate branch) but DO collide logically — both PRs claim "S167", a future
  reader can't tell which is which, and any cross-reference to "session_167_*"
  becomes ambiguous. Defends against the silent-logical-collision class
  (sister to `pr-conflict-site-regen` v1.4.0 Step 2c which covers the
  same shape for tracker IDs). Sister to `feedback_coordination_framing_for_
  parallel_artifact_collisions` (proactive coordination) and `feedback_
  parallel_session_file_ownership` (proactive file-level rules) — both of
  those prevent the collision; this skill recovers from it post-hoc.
  v1.1.0 (S173, 2026-05-11) adds Variant A (MERGED-sibling-PROMPT-only
  collision: sibling's prompt file for the next session is ALREADY on main
  but your `ls`/`grep` filter was too narrow — e.g., you only listed
  `*_handoff.md` files, or used a hand-written range pattern like
  `grep -E "session_(170|171|172)"` instead of the canonical `[0-9]+`
  recipe) and Variant B (single-PR-files-N-and-N+1: one PR ships both an
  executor's own handoff AND the next-session prompt, claiming TWO
  consecutive numbers in a single merge — detection-only refinement, not
  a naming bug).
author: Claude Code
version: 1.1.0
date: 2026-05-11
disable-model-invocation: true
---

# Session-Handoff Number Collision With Unmerged Sibling

## Problem

`session-handoff` Phase 1 Step 2 says "Write handoff doc → `docs/handoffs/session_N_handoff.md`." The implicit assumption is that you can determine N by inspecting `docs/handoffs/` on the current branch. **This assumption breaks when a parallel/sibling session ran concurrently in another worktree and its handoff PR hasn't merged into main yet.**

Concrete sequence:
1. Sibling session ran 2 hours ago in `.claude/worktrees/other/`, drafted `session_167_handoff.md`, opened PR #690 (still under review).
2. Sibling session updated MEMORY.md "Recent sessions" with an S167 entry AND appended to sessions_archive.md.
3. You fork your worktree off `origin/main` — MEMORY.md is local-user-state so you see the sibling's S167 entry, but `docs/handoffs/` on `origin/main` does NOT yet have `session_167_handoff.md` (PR pending).
4. You run `ls docs/handoffs/` → highest is S166b → you pick **S167**.
5. You write `docs/handoffs/session_167_handoff.md` + `session_168_prompt.md`.
6. Both sessions now claim S167. Disk doesn't conflict (different branches). MEMORY.md shows two S167 entries. Future readers can't tell which is canonical.

The collision is silent because:
- `ls` only sees the current branch's files.
- `git log origin/main -- docs/handoffs/session_167_handoff.md` returns empty (PR pending).
- Pre-commit hooks don't check session-number uniqueness.
- The session-handoff skill itself doesn't tell you to cross-check MEMORY.md.

## Context / Trigger Conditions

Activate this check during `session-handoff` Phase 1 Step 2 (before writing the handoff doc), or during Phase 4 Step 22.a (review-agent factual-accuracy pass), whenever **all** of:

1. You've picked a session number N based on `ls docs/handoffs/`.
2. There's a project-level MEMORY.md or sessions_archive.md that tracks recent sessions.
3. The repo is in a "dense parallel-PR" state (multiple worktrees, multiple open handoff PRs in recent days, or a `pr-conflict-site-regen`-style skill in the project's skill set).

**Strong signal that the collision is present:**
- Grepping MEMORY.md for `S<N>\b` or `session_<N>_` returns a match that points at a different worktree than yours.
- That match's PR (linked from the MEMORY entry) shows state OPEN or recently MERGED post-your-fork.

**Strong signal that you can skip this check:**
- It's a first session in a brand-new project.
- Only one Claude session has ever run in this repo.
- No `MEMORY.md` exists.

## Solution

### Step 1: Pre-write check (insert into session-handoff Phase 1 between Steps 1 and 2)

Before writing `session_N_handoff.md`, run the **canonical detection recipe** — exactly this, do NOT substitute a narrower hand-written pattern:

```bash
# Find highest session number on origin/main — match ALL session-numbered files
# (handoff AND prompt AND any other session_NNN_*.md), not just *_handoff.md.
# Use git ls-tree against origin/main to catch MERGED siblings whose files are
# on main but not in your branch's working tree.
git fetch origin main --quiet
main_max=$(git ls-tree -r origin/main docs/handoffs/ 2>/dev/null \
  | grep -oE 'session_[0-9]+[a-z]?' \
  | sort -t_ -k2 -V | tail -1)

# Find highest in your current branch's working tree (may differ if your
# branch diverged from main)
ls_max=$(ls docs/handoffs/ 2>/dev/null \
  | grep -oE 'session_[0-9]+[a-z]?' \
  | sort -t_ -k2 -V | tail -1)

# Find highest documented in MEMORY.md (may include unmerged siblings)
mem_max=$(grep -oE 'S1[0-9]{2}[a-z]?\b|session_1[0-9]{2}[a-z]?\b' \
  ~/.claude/projects/<project-slug>/memory/MEMORY.md \
  2>/dev/null | grep -oE '[0-9]+[a-z]?' | sort -V | tail -1)

echo "origin/main: $main_max | working-tree: $ls_max | MEMORY.md: $mem_max"
```

**Take the MAX of the three** — that's the highest session number CLAIMED anywhere. Your next session is `MAX + 1` (or `MAX + 1b` if you're sibling-parallel to that work).

**Why NOT a hand-written range pattern.** A common antipattern is to grep `session_(170|171|172)` for "recent" numbers. This silently misses any file outside the range — e.g., if a sibling session already claimed N+1 via a prompt file, your hand-pattern won't see it. The canonical recipe uses `[0-9]+` to match ALL numbers, then sort+tail finds the max.

**Why match `session_*` not `session_*_handoff.md`.** The session-number namespace is claimed by ANY file with that prefix — handoffs, prompts, parallel-stream prompts, audit prompts. A prompt-only file (e.g., `session_NNN_<topic>_prompt.md`) filed by a previous session for a future executor STILL claims N. Filter only on `_handoff.md` and you miss the entire prompt-claim category. See Variant A below.

If `mem_max > main_max` or `mem_max > ls_max`, a sibling session is unmerged. Investigate which entry points at which worktree.

### Step 2: Pick the right number

Three cases:

| Situation | Pick |
|---|---|
| `mem_max == ls_max == N` | Your session is **N+1** (or **N+1b** if you have an inflight-related scope) |
| `mem_max == N`, `ls_max == N-1` (sibling unmerged) | Sibling owns N. **You are Nb** (sibling-parallel convention) |
| `mem_max == N+k`, `ls_max == N-1` (multiple unmerged ahead) | Find next-free across both — typically **(N+k)b** |
| No `MEMORY.md` / first session | **1** |

The `b` suffix is project convention in many Claude-Code projects (precedents seen: S130/S130b, S138/S138b, S164/S164b/S164c, S95/S95b). Use `c`/`d`/... if `b` is also claimed by a third parallel session.

### Step 3: Mid-Phase-4 recovery (if you already drafted the colliding files)

If you got to Phase 4 (commit/PR) before noticing the collision via the review agent or final-summary scan:

1. **Rename files**:
   ```bash
   mv docs/handoffs/session_N_handoff.md \
      docs/handoffs/session_Nb_<topic>_handoff.md
   mv docs/handoffs/session_N+1_prompt.md \
      docs/handoffs/session_N+1b_<topic>_prompt.md
   ```
   Add a `<topic>` suffix (e.g., `model_health_consolidation`) to differentiate from the sibling, mirroring precedents like `session_164b_pick_rebases_handoff.md`.

2. **Rename branch**:
   ```bash
   git branch -m docs/sN-handoff docs/sNb-<topic>-handoff
   ```

3. **Find-and-replace inside the renamed files**: every `S<N>` self-reference becomes `S<N>b`; every cross-ref to your own `session_N_*` filename gets the new full name. Keep cross-refs to the sibling unchanged (they're about that other session).

4. **Update sessions_archive.md row** and **MEMORY.md "Recent sessions" entry** to use `Nb`. Leave the sibling's entry alone — your entry goes ABOVE it (most-recent-first convention).

5. **Update tracker entry** if you've already added one — rename the `Item("cat7-NNN", "S<N> ...")` title to `"S<N>b ..."`.

6. **If you already pushed** under the colliding name: force-push from the renamed branch and let GitHub auto-close the old PR ref, OR if the PR is already open under the old name, edit the title in-place and close+reopen under the new branch.

## Variants

### Variant A — MERGED sibling prompt-only collision (S173, 2026-05-11)

**Symptom.** You start a new session. Latest `session_N_handoff.md` you can find is for N=171. You assume the next handoff slot is 172. But on `origin/main`, a previous executor session already filed `session_172_<topic>_prompt.md` (a PROMPT for a future N=172 executor) before your worktree forked. That filename claims the 172 slot. You write your handoff as `session_172_*` and now main has two files claiming 172.

**Root cause.** Your detection filter was too narrow. Either:
- You only listed `*_handoff.md` files (missing the prompt-file claim), OR
- You used a hand-written range pattern like `grep -E "session_(170|171|172)"` instead of the canonical `[0-9]+` recipe, OR
- You only checked your own branch's working tree (where the prompt file doesn't exist because your fork predates the merge).

**Real-world trigger (this variant's origin).** During S173 (a `/actions` page revalidation plan), the executor: (1) checked `git log` for related PRs, (2) listed `docs/handoffs/` filtered by a hand-written range, (3) saw `session_171_672_backfill_prompt.md` + `session_171_handoff.md` + `session_170_*.md` only. Missed `session_172_closed_issue_audit_prompt.md` filed by PR #716 (the S171b backfill executor's handoff PR). Claimed S172. Code-review caught the collision; recovery via Step 3 below renumbered to S173 + S174 (next-prompt also bumped).

**Detection.** Use the canonical recipe in Step 1 above. The `git ls-tree -r origin/main docs/handoffs/` line is the load-bearing one — it catches MERGED-but-not-yet-in-your-working-tree files.

**Fix.** Standard Step 3 recovery (rename files + branch + cross-refs + tracker). Add a sibling-parallel cross-link in the bucket-footprint field of your new handoff naming the existing N-slot occupant.

### Variant B — Single-PR-files-N-and-N+1 (S173, 2026-05-11)

**Symptom.** One PR ships BOTH an executor's own handoff (claiming N) AND a next-session prompt (claiming N+1) — so a single merge into main claims two consecutive session numbers at once. Downstream sessions that only inspect the latest `_handoff.md` filename miss that the prompt half of the PR also claimed N+1.

**Real-world trigger.** PR #716 in the project: title `docs(s171b): execute #672 backfill — 67 partitions × 21,774 rows + ADR-0030 rollout log + S172 audit prompt`. The diff included BOTH `session_171b_*_handoff.md` (claiming S171b) AND `session_172_closed_issue_audit_prompt.md` (queuing the next session, claiming S172). A subsequent session sees `session_171b_*` on main and assumes 172 is next-free — but the same PR already claimed 172 via the prompt.

**Detection.** Same as Variant A — the canonical recipe in Step 1 catches both claimed slots because it greps `[0-9]+` across all `session_*.md` filenames, not just handoff-suffixed ones.

**Prevention (file-side).** Not a naming bug — the PR-filer is doing the right thing by handing off a numbered prompt. This Variant exists primarily as a detection challenge for downstream sessions, addressed by Step 1's canonical recipe.

## Verification

After renaming:

```bash
# Internal cross-refs should all be b-suffixed inside your files
grep -nE "session_[0-9]+_(handoff|prompt)\.md|S[0-9]+\b" \
  docs/handoffs/session_Nb_*.md | grep -v "Nb"
# Should print only references to OTHER sessions (not your own bare-N)

# Disk should have your b-suffixed files + sibling's bare-N (if merged) or neither (if not)
ls docs/handoffs/session_N* docs/handoffs/session_Nb*

# Branch name reflects b suffix
git branch --show-current
```

## Example

This session (`/session-handoff` invocation on 2026-05-11):

1. Forked off `origin/main`, ran `ls docs/handoffs/` → highest was `session_99_prompt.md` (truncated view); proper sort showed S166b as highest on-disk.
2. Picked S167. Wrote `session_167_handoff.md` + `session_168_prompt.md`.
3. Got to Phase 2 (sessions_archive update). Read MEMORY.md to find the "Recent sessions" section. **Found an S167 entry already there**, pointing at `summarize-work` worktree, cat7-7gr (site-tracker expansion + 71-issue execution plan).
4. Sibling's PR existed but had not yet merged into main (so the on-disk check missed it).
5. Applied this skill:
   - Renamed files to `session_167b_model_health_consolidation_handoff.md` + `session_168b_model_health_exec_prompt.md`.
   - Renamed branch `docs/s167-handoff` → `docs/s167b-model-health-handoff`.
   - Updated all internal cross-refs (5 occurrences across both files).
   - Updated sessions_archive.md row `| 167 |` → `| 167b |`.
   - Added MEMORY.md entry with `S167b` framing, sibling-parallel cross-link to the existing S167 entry.
   - Tracker entry `cat7-7hd` titled "S167b handoff — ..."
6. Result: two coherent parallel handoffs on main eventually — `session_167_handoff.md` (sibling) + `session_167b_model_health_consolidation_handoff.md` (mine). PR #691 merged 2026-05-10T23:25:58Z.

Total recovery cost: ~5 minutes of file/branch renames + cross-ref find-replace. If the collision had landed in main unrenamed, the cost would have been much higher (post-merge file rename + tracker fixup + MEMORY.md disambiguation).

## Notes

- The check belongs in `session-handoff` Phase 1 Step 2 ideally — if you have edit access to your local copy of that skill, add a one-line cross-check step there. This standalone skill exists as a complement for projects/users who can't or shouldn't fork session-handoff.
- The MEMORY.md cross-check is **not** a hot-path operation in single-session projects — skip if your project has zero parallel-session history. Apply only when "dense parallel-PR" is the project mode (heuristic: 3+ worktrees actively under `.claude/worktrees/`, OR a project skill like `pr-conflict-site-regen` exists).
- This pattern is the session-number equivalent of `pr-conflict-site-regen` v1.4.0 Step 2c (silent ID collision detection for tracker IDs). The recovery mechanics are isomorphic: rename + propagate.
- The `b`/`c` suffix convention is not universal — some projects use `_b`, `-2`, `_alt`, etc. Check the project's precedents in `MEMORY.md` "Recent sessions" before picking a convention.
- The sibling's handoff may eventually merge while yours is in flight, OR vice versa — neither needs to know about the other beyond a cross-link in the bucket-footprint or sibling-parallel field of each handoff. Don't tag the older one as "superseded" — both are valid (per `feedback_coordination_framing_for_parallel_artifact_collisions.md`).

## References

- Sister skill: `numbered-append-log-next-id-grep-max-not-tail` (the WITHIN-FILE non-monotonic case — next lesson/changelog/ADR number is the grep-MAX, not the file-order last; no branches involved).
- Sister feedback files (proactive coordination):
  - `feedback_coordination_framing_for_parallel_artifact_collisions.md` — supersession vs coordination framing.
  - `feedback_parallel_session_file_ownership.md` — file-level rules to prevent the collision upstream.
- Skill of record for the workflow this slots into: `session-handoff` v1.6 Phase 1.
