---
name: gh-squash-merge-closes-only-one-issue
description: |
  GitHub auto-close on squash-merge only catches ONE issue per PR even when
  the PR title/body says "Closes #447, #448, #449, #450". The first issue
  closes; the rest stay OPEN. Use when: (1) you opened a PR with a title
  or body listing multiple "Closes #X, #Y, #Z" references, (2) the PR
  squash-merged successfully (`gh pr view N --json state` = MERGED),
  (3) `gh issue list --state open` shows some of the referenced issues
  are still OPEN. Root cause: GitHub's auto-close keyword parser binds
  one keyword to one issue; "Closes #447, #448" is interpreted as "Closes
  #447" plus an inline reference to #448. Fix: either (a) write one
  keyword per issue ("Closes #447. Closes #448. Closes #449.") in the
  PR body BEFORE merging, or (b) post-merge, run `gh issue close $N
  --comment "Closed by PR #M (squash-merge auto-close caught only one)"`
  for each leftover. Different from `pr-followup-commit-stranded-after-squash`
  (which covers stranded COMMITS, not stranded ISSUES). Saves a "why are
  my issues still open after merging the fix?" detour.
author: Claude Code
version: 1.0.0
date: 2026-05-07
disable-model-invocation: true
---

# GitHub squash-merge auto-closes only one issue per PR

## Problem

You shipped a fix PR that addresses 4 filed issues. PR title:

> `fix(dashboard): wire /actions segment tiles + plug 4 audit P0s (closes #447, #448, #449, #450)`

PR body opens with:

> Closes #447, #448, #449, #450 — the four template/route P0s from the audit.

PR squash-merges cleanly. CI green, branch deleted. You move on.

Later: `gh issue list --state open` shows `#448`, `#449`, `#450` still OPEN. Only `#447` got auto-closed. You spend a confused minute checking whether the fix actually shipped (it did) before realising the issues never closed.

## Context / Trigger Conditions

All of:

1. PR title or body includes a comma-separated `Closes #X, #Y, #Z` (or `Fixes`, `Resolves`) reference.
2. PR was **squash-merged** (regular merge has slightly different parsing but the same gotcha applies).
3. After merge: `gh pr view N --json state` returns `MERGED`, but `gh issue view #Y` returns `OPEN` for the second-and-later issues.
4. The first issue in the comma list IS closed correctly — proves your "Closes" keyword wasn't malformed.

This is **not** about the issues' content / labels / state. The fix did ship. The auto-close parser just bound the keyword to one issue.

## Solution

### Path A — prevent (preferred, before merge)

Write one keyword per issue in the PR body. GitHub closes each:

```markdown
## Summary

Bundles four P0 fixes from the 2026-05-07 audit.

Closes #447.
Closes #448.
Closes #449.
Closes #450.
```

Or comma-list with a keyword per item:

```
Closes #447, closes #448, closes #449, closes #450.
```

GitHub recognises `close`, `closes`, `closed`, `fix`, `fixes`, `fixed`, `resolve`, `resolves`, `resolved` (any case). One keyword binds to the immediately-following issue ref; a bare comma + #N after it is a *reference*, not a close trigger.

### Path B — recover (after merge)

If the PR is already merged with the broken comma-list pattern:

```bash
# Close each leftover issue with a reference comment
for issue in 448 449 450; do
  gh issue close $issue \
    --comment "Closed by PR #457 (squash-merge auto-close caught only one issue per PR)."
done
```

The comment makes the closure traceable — future readers won't wonder why the issue closed without a linked PR. The issue's GitHub timeline will still show the cross-reference from the merged PR's body.

### Loop pattern (multi-PR clean-up)

When you have several PRs each closing several issues, batch the recovery:

```bash
# tuple format issue:pr — adjust to your set
for tuple in "448:457" "449:457" "450:457" "452:458" "454:459" "455:459"; do
  issue=${tuple%:*}
  pr=${tuple#*:}
  gh issue close $issue \
    --comment "Closed by PR #$pr (squash-merge auto-close caught only one issue per PR)."
done
```

## Verification

```bash
gh issue list --state open --search "447 448 449 450 in:number"
# Empty output = all four closed.
```

Or per-issue:

```bash
gh issue view 448 --json state --jq '.state'
# CLOSED
```

## Example

**Audit shipped 9 issues (#447–#455) in 4 PRs.** Each PR's body said "Closes #X, #Y, #Z" comma-style. After all 4 PRs merged:

| PR | "Closes" body | Auto-closed | Stayed open |
|----|---------------|-------------|-------------|
| #457 | #447, #448, #449, #450 | #447 | #448, #449, #450 |
| #458 | #451, #452 | #451 | #452 |
| #459 | #453, #454, #455 | #453 | #454, #455 |

Recovered with the loop above — 6 `gh issue close` calls total, ~5 seconds. Future PRs in the same session used Path A formatting.

## Notes

- **Sibling skill: `pr-followup-commit-stranded-after-squash`** — covers stranded *commits* (you pushed more after the squash collapsed). Different mechanism, same family of "squash quietly drops things."

- **Why the parser does this:** GitHub's "linked issues" feature was originally one-issue-per-PR. The keyword-to-comma extension came later and didn't fully generalise. Treating "Closes #X, #Y" as "Closes #X" + "reference to #Y" preserves backward compatibility with PR descriptions that mention related issues without intending to close them.

- **Title vs body:** the parser reads BOTH the PR title and the body. If your title contains `(closes #447, #448, #449, #450)` and the body re-states it: still only #447 closes. Adding "Closes #448. Closes #449. Closes #450." anywhere in the body is enough; the title can stay parenthetical.

- **Linked issues UI on github.com:** in the PR sidebar, "Development" / "Linked issues" should show all the issues the PR will close. If only one is listed there, the parser only matched one — fix the body BEFORE merging. (This UI signal is the cheapest preventive check.)

- **CLI users won't see the linked-issues UI** when they `gh pr create` from a HEREDOC. Make path A the default formatting in your PR-template scripts.

- **Other auto-close keywords with the same behavior:** `Fixes`, `Resolves`. Same fix patterns apply — one keyword per issue.

- **Opposite-intent sibling — closed correctly but PREMATURELY:** a single `Fixes #N` *does* fire, but you wanted the issue HELD OPEN because the fix's proof is a deferred unattended run (a cron/scheduled job that hasn't fired yet — merge ≠ proven). Use `Refs #N` (non-closing) and close manually after the run, or `gh issue reopen N` if it already auto-closed. See `verify-recurring-writer-before-unattended-window` § Notes.
