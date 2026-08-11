---
name: parallel-pr-scope-overlap-tiebreaker-delta-check
description: |
  Before applying a handoff prompt's tiebreaker default ("merge the first-mover",
  "the clean-against-main one", "the one with reviewer APPROVE") to pick a
  winner between two parallel PRs that implemented the SAME scope, run `gh pr
  diff` on BOTH and audit for substantive deltas. Use when: (1) a session
  prompt or handoff doc surfaces a parallel-PR collision and recommends a
  tiebreaker, (2) two PRs targeting the same issue / same fix area are open
  simultaneously authored by different sessions, (3) the prompt's recommended
  winner is the older / cleaner / single-reviewer one — exactly the conditions
  under which "first-mover" rules can ship the inferior implementation, (4)
  you're tempted to skip the delta-check because the diffs "are probably
  substantively equivalent" or the prompt already analyzed them. Symptom of
  having skipped this check: weeks later a follow-up PR re-implements a
  correctness improvement that was already in the loser's diff. Sister to
  `synthetic-id-collision-rebase` (same-id register collisions; mechanism
  is namespace, not scope), `parallel-pr-template-fork-duplicates-moved-section`
  (semantic duplication via mover/forker — different files, same block ends
  up in two places), and project memory
  `feedback_coordination_framing_for_parallel_artifact_collisions.md` (what to
  do AFTER picking a winner — neutral close framing). Defends against the
  trap that prompt-writer's tiebreaker rules optimize for merge mechanics
  (first-mover, clean-against-main, mergeable=CLEAN), not for correctness;
  the better implementation can lose on those axes and still be the right
  choice.
author: Claude Code
version: 1.1.0
date: 2026-06-22
disable-model-invocation: true
---

# Pre-Tiebreaker Delta Check on Scope-Overlapping Parallel PRs

## Problem

Two parallel sessions independently opened PRs targeting the same issue
(same fix scope, same files, same goal). A session-handoff prompt later
asks a third session to pick a winner. The prompt's recommended tiebreaker
is some combination of:

- "Merge the first-mover" (older PR by createdAt)
- "Merge the one that's clean against main" (mergeable: CLEAN, no rebase needed)
- "Merge the one with reviewer APPROVE" (assumed implies higher quality)
- "Merge the one with wider scope" (e.g., bundles verification + handoff doc)

These rules are about **merge mechanics**, not implementation quality.
They can — and do — ship the inferior PR while the better implementation
gets closed.

## Trigger Conditions

ALL of the following must hold:

1. Two parallel PRs are open simultaneously, targeting overlapping scope
   (same issue number cited as `Closes #N`; same files touched; same fix
   intent).
2. A session-handoff prompt explicitly suggests a tiebreaker default
   ("merge #X because it's first-mover", "clean against main", "wider
   scope"), or you're operating from such instructions in auto-mode.
3. The two PRs were authored by different sessions (different worktrees,
   different branches, different timestamps, different commit authors or
   different `co-authored-by` chains).
4. You haven't yet run `gh pr diff <A>` and `gh pr diff <B>` side-by-side
   to compare implementations.

If those conditions hold and you're about to merge based on the prompt's
recommendation alone, **STOP** — run the delta check first.

## Solution

### Step 1 — Refresh both PR snapshots

A prompt authored hours ago may cite stale state (e.g., "PR #X is CLEAN,
PR #Y is CONFLICTING"). Main may have advanced; the relative state often
flips by the time the next session runs.

```sh
gh pr view <A> --json state,mergeable,mergeStateStatus,statusCheckRollup,additions,deletions,createdAt,headRefName
gh pr view <B> --json state,mergeable,mergeStateStatus,statusCheckRollup,additions,deletions,createdAt,headRefName
```

Watch for these signals that a PR may have already merged:

- `state: MERGED` (obvious)
- `statusCheckRollup` includes post-merge workflow names (e.g., `Deploy
  <service>: SUCCESS`, `Auto-deploy ...: SUCCESS`, `Publish ...`,
  `Release ...`) — these workflows fire on `pull_request: closed` and
  cannot appear before merge
- A merge-commit-id in `git log origin/main` matching the PR's title

If one PR has already merged, the "decision" is moot — focus on closing
the other with coordination framing.

### Step 2 — Diff both PRs against the same base

```sh
# Show full diff for each
gh pr diff <A> > /tmp/pr-A.diff
gh pr diff <B> > /tmp/pr-B.diff

# Or if the PRs are large, slice to the load-bearing files
gh pr diff <A> | sed -n '/diff --git.*<load-bearing-path>/,/diff --git/p'
```

For repos where `gh pr diff` returns too much output, save to file and
grep for substantive markers:

```sh
# Look for new function definitions (correctness or feature deltas)
grep -E '^\+.*(def |function |func )' /tmp/pr-A.diff | head -20
grep -E '^\+.*(def |function |func )' /tmp/pr-B.diff | head -20

# Look for new error/warning paths
grep -E '^\+.*(WARNING|ERROR|fail|catch|except)' /tmp/pr-A.diff | head -20
grep -E '^\+.*(WARNING|ERROR|fail|catch|except)' /tmp/pr-B.diff | head -20

# Look for new validation / preflight checks
grep -E '^\+.*(check|validate|verify|guard|preflight)' /tmp/pr-A.diff | head -20
```

### Step 3 — Classify each delta as substantive or cosmetic

For each addition that exists in one PR but not the other, ask:

| Delta type                                          | Substantive? |
|-----------------------------------------------------|--------------|
| New error path, retry, or fallback                  | YES          |
| Different default value with different semantics    | YES          |
| Defensive validation (input range, null check)      | YES          |
| Different ordering of operations affecting outcome  | YES          |
| Pinning a value vs deriving / aliasing it           | YES (often)  |
| Multi-reviewer panel + fixups vs single reviewer    | YES (process)|
| Different override-flag NAMING (same semantics)     | NO (cosmetic)|
| Different function/variable names (same logic)      | NO (cosmetic)|
| Different prose in code comments                    | NO (cosmetic)|
| Whitespace / formatting                             | NO           |
| One has more / better tests for the same code path  | YES (process)|

If the loser PR has ≥1 substantive advantage, override the prompt's
default tiebreaker. The merge-mechanics rules don't optimize for
correctness; you do.

### Step 4 — If you're in auto-mode, surface the override decision to the user

This is a high-blast-radius decision (which PR's CODE ships to production).
Even in auto-mode, ask the user before overriding the prompt's default.
Frame it as: "the prompt recommends merging #X, but #Y has these substantive
improvements: <list>. Should I (a) adopt #Y and ship #X's docs as a
follow-up, (b) cherry-pick #Y's improvements onto #X then merge #X, (c)
just merge #X as-is and accept the gap?" Default to option (a) when #Y has
real correctness fixes — those should land canonically, not as a port.

### Step 5 — Document the override in MEMORY.md, the tracker entry, and the loser's close-comment

The loser's close comment should be neutral coordination framing per
`feedback_coordination_framing_for_parallel_artifact_collisions.md` and
should explain the substantive grounds for picking the winner — not just
"first-mover lost". This carries the lesson forward and gives the parallel
session credit for the better implementation. Cite the specific deltas.

## Verification

After the override decision, verify:

1. The winner's substantive improvements are visible in the merge commit's
   diff (`git show <merge-sha> -- <load-bearing-files>`).
2. The loser's wider-scope work (handoff docs, tracker entries, future-
   session prompts) ships as a small docs-only follow-up PR — don't lose
   it just because the code lost.
3. MEMORY.md is updated with the lesson + a one-line bullet linking the
   handoffs from both sides.
4. The tracker entry's `notes=` field cites the specific deltas that drove
   the override — this is the durable record for the next session that
   reads the tracker.

## Example — S155 / S156b deploy-script collision (2026-05-08)

A handoff prompt asked S156b to pick a winner between PR #542 (first-mover,
clean-against-main, single-reviewer APPROVE, wider scope incl. verification +
handoff + tracker) and PR #553 (parallel, 31 min later, CONFLICTING-against-
main initially, scope: #364 fix only). Prompt's recommendation: merge #542.

Pre-tiebreaker `gh pr diff` revealed three substantive improvements in #553:

1. **Upfront `git fetch origin main --quiet`** with stderr WARN on failure
   in the deploy-script preflight. #542 read the behind-count from cached
   state — an operator who hadn't fetched got a false "0 behind" and
   passed the guard. Real correctness gap.
2. **Build with `--tag="${IMAGE}:${IMAGE_TAG}"` (SHA-tagged primary) and
   deploy from the SHA-tagged image.** `gcloud run revisions describe
   <rev> --format='value(spec.containers.image)'` returns the source
   commit directly. #542 deploys from `:latest` and adds `:<sha>` only as
   a post-build alias, so describe returns `:latest` and operators have to
   resolve the alias separately to answer "what code is in this revision?".
3. **5-agent reviewer panel + 3 in-PR fixups** addressing convergent
   findings (F1 fetch-failure stderr, F2 `--force` scanned across `$@`,
   F4 echo includes SHA tag). #542 had a single-reviewer APPROVE.

Without the delta-check, the handoff would have shipped #542 and silently
lost all three improvements. With it: closed #542 with coordination framing
citing the deltas, shipped #542's docs as PR #560 (small docs-only follow-
up), captured the lesson in `cat7-7fc` tracker entry + MEMORY.md.

## Notes

- **Don't trust prompt-cited PR state.** A prompt authored hours ago may
  reference stale `mergeable` / `state` values. Always re-poll
  `gh pr view --json state,mergeable,statusCheckRollup` before deciding.

- **The tiebreaker rules optimize for merge mechanics, not correctness.**
  - "First-mover" optimizes for chronological priority. The earlier author
    sometimes had less time to refine the implementation; the later one
    had more.
  - "Clean against main" optimizes for rebase-cost. Costs nothing at
    `git rebase`; doesn't predict implementation quality.
  - "Single-reviewer APPROVE" is weaker than "multi-reviewer panel + N
    convergent fixups" — independent agreement is stronger evidence per
    `feedback_multi_reviewer_convergence_fix_in_pr.md`.
  - "Wider scope" sometimes means the PR bundles unrelated work that
    should ship separately anyway; it's not a quality signal.

- **`statusCheckRollup` is an early signal that a PR has already merged.**
  If it includes `Deploy <X>: SUCCESS` or `Auto-deploy ...: SUCCESS` or
  similar post-merge workflow names, recheck `state` immediately — those
  workflows fire on `pull_request: closed` and cannot appear pre-merge.
  Save 5 minutes of "deciding" between two PRs when one is already in
  production.

- **The cost of the delta-check is ~5 minutes** (two `gh pr diff` runs +
  classifying each new line as substantive or cosmetic). The cost of
  skipping it is potentially weeks: a follow-up PR has to re-implement
  the lost improvement, and meanwhile production runs on the inferior
  fix. The asymmetric cost says "always do the check".

- **If both PRs are substantively equivalent**, the prompt's default
  tiebreaker is fine. The check exists to FALSIFY equivalence, not to
  always reverse the recommendation.

## See also

- `feedback_coordination_framing_for_parallel_artifact_collisions.md`
  (project memory) — neutral framing for the loser-PR close comment after
  this skill's delta check has picked a winner
- `feedback_multi_reviewer_convergence_fix_in_pr.md` (project memory) —
  multi-reviewer convergent findings are stronger than single-reviewer
  APPROVE; one of the substantive deltas this skill's classifier looks
  for
- `synthetic-id-collision-rebase` — same-ID register collisions in
  append-only files (different mechanism: namespace, not scope)
- `parallel-pr-template-fork-duplicates-moved-section` — semantic
  duplication after parallel PRs ship (different mechanism: structural
  duplication via mover/forker, not scope overlap)

## Variant — the collision is discovered AFTER one fix is already DEPLOYED LIVE (v1.1)
The base skill assumes two OPEN PRs you pick between. Higher-stakes variant: one fix is already
MERGED + DEPLOYED to a shared live pipeline while a parallel session built/committed a DIFFERENT fix
for the same issue. Two extra moves beyond the delta-check:
1. **Establish ground truth from the LIVE DEPLOYED ARTIFACT — not `main`, not your branch.** Grep the
   actually-deployed file (+ its deployed SHA / revision) for each fix's distinctive markers to learn
   *which* fix is live. Don't reason from "my PR merged" — a parallel session's different fix may be
   the live one, or neither may be deployed. (S266b: checked Dataform main `resolvedGitCommitSha` +
   grepped the served `.sqlx` for `IN UNNEST` vs carry-forward markers → confirmed mine live, theirs
   unmerged.) Sister: `version-fix-check-read-source-not-materialized-table`.
2. **Reconcile via ATOMIC SWAP — never blind-deploy the second fix over the live one.** Deploying fix B
   onto a pipeline already running fix A either reverts A (if B's base is stale), stacks a redundant
   second mechanism, or drifts source↔deployed state. If B wins: revert-A + deploy-B as ONE change. If
   A wins (already live + verified): the other session stands down. Pick ONE — never run both.

(S266b 2026-06-22, `the-project-repo`: #1271 full-key-set `status_code` flicker fix was
live + verified when a parallel session asked to deploy a competing carry-forward fix for the same
flicker. Verified the live serving artifact + relayed a stand-down instead of a blind deploy.)

## References

- This skill was extracted from session S156b on 2026-05-08 in the
  `the-project-repo` repo, working through the PR #542
  vs PR #553 collision on issue #364 (deploy script git-state guard).
  See `docs/handoffs/session_156b_finalize_s155_handoff.md` (PR #560
  merge commit `0b8cee93`) for the full session record.
- The asymmetric-cost argument for always running the delta-check is
  rooted in the same intuition as `feedback_review_before_merging_prs.md`
  (always run a code-reviewer pass before merging) — the marginal cost
  is small, the marginal benefit when it catches something is large.
