---
name: stacked-pr-review-per-base-diff-and-attach
description: |
  Two paired patterns for reviewing a stack of dependent PRs (#A → #B → #C
  where each is based on the prior, not on main). (1) Reviewer agents need
  each PR's diff against ITS OWN base, not all-vs-main — otherwise upstream
  PR's changes show as part of downstream PR's diff and reviewers
  misattribute findings. Use `gh pr diff <N> -R owner/repo > prN-vs-its-base.diff`
  per PR. (2) Review reports for the whole stack should be committed to the
  BASE branch of the stack (the bottom PR's branch), not to the most recent
  one — every PR up the stack inherits them via base-branch advance, and PR
  diffs still show only the actual feature changes because merge-base advances
  too. Use when: dispatching a multi-agent review panel against 2+ stacked
  PRs; deciding where to commit reviewer report .md files; auditing whether
  a stacked-PR review panel saw the right per-PR scope.
author: Claude Code
version: 1.0.0
date: 2026-05-28
---

# Stacked PR review: per-base diffs + base-branch attachment

## Problem

Reviewing a stack of N dependent PRs (where #B is based on #A, #C is based on
#B, etc., rather than each PR being based on main) hits two distinct issues:

1. **Diff capture for reviewer agents.** If you naively run `gh pr diff <N>`
   against every PR in the stack, gh defaults to comparing against the PR's
   declared base — which is correct. But if you pre-filter via `git diff
   main..pr-branch`, you'll include all upstream PRs' changes in the
   "downstream PR's diff," and reviewers will flag findings against code
   that actually shipped 2 PRs ago. The reviewer attributes the finding to
   the wrong PR, and the author of the downstream PR is left confused.

2. **Where to commit the review reports.** Once 3 reviewer agents have
   produced `reviewer_correctness.md`, `reviewer_architecture.md`,
   `reviewer_security.md`, they need to live somewhere reachable by every
   PR in the stack — but committing them to the top-of-stack PR pollutes
   that PR's diff (the reports become "changes" the topmost PR is making).
   The base-of-stack PR is the natural home.

## Context / Trigger Conditions

- A stack of 2+ open PRs exists where the head PR's base is another open PR (not main)
- You're dispatching a multi-agent review panel (e.g., `roundtable:agent-review-panel`) to cover the whole stack
- One of these symptoms:
  - Reviewer flags a "missing feature" in PR #C that was actually added in PR #A
  - Reviewer's diff snapshot shows ~3× as many lines as the PR's actual change
  - You want PR #A's reviewer to see the docs/reviews/ folder but committing it to PR #C's branch means PR #A can't see it
  - The orchestrator wonders "which branch do I commit this report to?"

## Solution

### Pattern 1: per-PR base-aware diff capture

For each PR in the stack, capture its diff against ITS OWN base, not against
main:

```bash
mkdir -p /tmp/stack-review
for pr in 57 58 59; do
  # gh pr diff defaults to PR's declared base (the right thing)
  gh pr diff $pr -R <org>/agentic-ai-workshop \
    > /tmp/stack-review/pr${pr}-vs-its-base.diff
  # Also save the body so reviewers have author intent
  gh pr view $pr -R <org>/agentic-ai-workshop --json body -q .body \
    > /tmp/stack-review/pr${pr}-body.md
done
wc -l /tmp/stack-review/*.diff
```

Each reviewer agent then receives the per-PR diffs + bodies via the prompt:

```
PR #57 vs main:        /tmp/stack-review/pr57-vs-its-base.diff (~600 lines)
PR #58 vs #57 branch:  /tmp/stack-review/pr58-vs-its-base.diff (~230 lines)
PR #59 vs #58 branch:  /tmp/stack-review/pr59-vs-its-base.diff (~330 lines)
```

State explicitly in the prompt: "PR #58 vs `s13-gemini-retry-friendly-error`
(#57's branch)" so the reviewer doesn't misread the base.

### Pattern 2: commit review reports to the BASE branch of the stack

Once reports exist, commit them to the BOTTOM PR's branch (the stack's
shared base), not the topmost. In a 3-PR stack #A ← #B ← #C, commit
`docs/reviews/<topic>/` to #A's branch. Every PR in the stack then sees
those reports because:

- #A's PR diff includes them (the docs are part of #A's diff against main now)
- #B's PR diff does NOT show them (merge-base advances when #A's branch advances; #B's diff still shows only #B's feature changes vs #A's tip)
- #C's PR diff does NOT show them (same reason — #C still diffs against #B's tip)
- A new PR #D stacked on #C inherits the reports too, automatically

The mechanism: `gh pr diff` uses merge-base, not the literal base ref at PR
creation time. When the base branch advances, the merge-base advances too,
and the PR's "diff" shifts accordingly.

```bash
# Example: 3-PR stack #57 → #58 → #59 (each based on prior).
# Bottom of stack is #57's branch, but for "the foundation under all 3", use #59's
# branch only if all 3 will inherit reports — actually #57 is the truer base.
# Pick the branch where the report applies AND where the PR descriptions
# already reference it. For the s13 review session, #59's branch was the
# correct home because the reviews evaluated all 3 PRs and #57/#58 reviewers
# had already begun without seeing them.

git worktree add /tmp/stack-base-worktree s13-firestore-jobstore
cp docs/reviews/<topic>/*.md /tmp/stack-base-worktree/docs/reviews/<topic>/
cd /tmp/stack-base-worktree
git add docs/reviews/
git commit -m "docs: review panel reports for the s13 stack (#issue)"
git push
```

After the push, refresh the PRs to see the diff update:

```bash
gh pr diff 57 | wc -l  # should NOT include the new review .md files
gh pr diff 58 | wc -l  # same
gh pr diff 59 | wc -l  # WILL include the new review .md files (it's PR #59's diff vs main now)
```

(The bottom PR's diff grows by the size of the reports; the upper PRs are
unaffected. This is the intended behavior — reviewers of the bottom PR see
the reports as part of "this PR introduces a foundation including review
docs.")

## Verification

After committing reports to the base branch:

1. `gh pr view <top_pr> --json files -q '.files[].path'` — confirm the report files do NOT appear in the top PR's file list
2. `gh pr view <base_pr> --json files -q '.files[].path'` — confirm they DO appear in the base PR's file list
3. From a worktree on the TOP PR's branch, `ls docs/reviews/<topic>/` — confirm files exist locally (you inherit them because base advanced)

If the reports DO appear in every PR's diff, the PR base refs aren't set up
as a stack — they may all be based on main. Check with:

```bash
gh pr list --state open --json number,headRefName,baseRefName
```

## Example

The 2026-05-28 GA/GTM audit s13-stack review:

```
main
└── #57 s13-gemini-retry-friendly-error  (base: main)
    └── #58 s13-firestore-foundation     (base: s13-gemini-retry-friendly-error)
        └── #59 s13-firestore-jobstore   (base: s13-firestore-foundation)
            ├── #62 s13-tool-cache       (base: s13-firestore-jobstore)
            └── #63 s13-fixup-surgical   (base: s13-firestore-jobstore)
                └── #64 s13-fixup-structural (base: s13-fixup-surgical)
```

Reviewer agents got per-base diffs (`pr57-vs-main.diff`,
`pr58-vs-s13-gemini-retry.diff`, `pr59-vs-s13-firestore-foundation.diff`).
Reports were committed to `s13-firestore-jobstore` (#59's branch). Net
effect:

- PR #59's diff grew by ~3 review .md files (acceptable — review is part of #59's foundation)
- PR #62, #63, #64 inherited the reports via base-branch advance without diff bloat
- New work stacked on top (PR-A → PR-B) also inherited them automatically

## Notes

- This pattern requires that the bottom PR of the stack is open AND its base ref is `main`. If the bottom PR was already merged when reports are written, commit them to main via a separate small docs PR instead.
- If the stack is more than 4 PRs deep, consider splitting the review batch by foundation-vs-feature: review the bottom 2-3 (foundation) separately from the top (feature) so reports can attach to the right granularity.
- Don't commit reports to a top-of-stack PR "to be safe" — the reports will reappear in every subsequent rebase and bloat downstream PR diffs.
- The `roundtable:agent-review-panel` skill writes reports to `docs/reviews/<date>-<topic>/`. Combine that directory naming with the base-branch attachment pattern for clean cross-PR visibility.
- For a 2-PR stack, pattern 2 still works but is borderline overhead — committing the reports as a separate small docs PR off main may be cleaner. The pattern's value scales with stack depth.

## References

- `gh pr diff` documentation: defaults to PR's declared base (the right thing for stacked PRs by construction)
- Git merge-base semantics — what makes pattern 2 work without manual rebases
- [`roundtable:agent-review-panel`](https://github.com/wan-huiyan/agent-review-panel) — Phase 1 "Codebase State Check" already enumerates the worktree+branch state; this skill adds the stacked-PR attachment dimension
- Empirically used 2026-05-28 in the GA/GTM audit project's s13-stack review panel run (3 reviewers + 4 stacked PRs)

## Reference-only siblings in this toolkit

These carry `disable-model-invocation: true`. They never appear in the skill
listing and the Skill tool refuses them, so the only way in is to open the file
with Read when one of these matches what you are looking at.

- [`stacked-pr-base-branch-deletion-auto-closes-dependent`](../stacked-pr-base-branch-deletion-auto-closes-dependent/SKILL.md) — deleting a base PR's branch auto-closed the dependent stacked PR, which cannot be reopened
- [`code-review-subagent-fabricates-specifics-to-inflate-severity`](../code-review-subagent-fabricates-specifics-to-inflate-severity/SKILL.md) — a reviewer agent's HIGH/BLOCKING finding cites specifics that do not exist in the diff
- [`subagent-pre-existing-misattribution`](../subagent-pre-existing-misattribution/SKILL.md) — a reviewer put test failures on the wrong side of the pre-existing / PR-introduced line
- [`prove-test-failures-pre-existing-via-clean-worktree`](../prove-test-failures-pre-existing-via-clean-worktree/SKILL.md) — proving failures predate your change by replaying the suite in a clean worktree
