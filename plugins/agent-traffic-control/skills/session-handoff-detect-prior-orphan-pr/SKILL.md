---
name: session-handoff-detect-prior-orphan-pr
description: |
  Pre-flight detection of a prior incomplete /session-handoff run that already
  created a branch, PR, handoff doc, and/or worktree — so the current invocation
  doesn't open a duplicate PR. Use when (1) you're about to write
  `docs/handoffs/session_N_handoff.md` as part of /session-handoff, (2) you
  just created or considered creating a `docs/sN-handoff` branch and `git`
  reports "branch already exists" or `+` (checked out elsewhere), (3) you find
  a worktree under `.claude/worktrees/` whose name vaguely matches the current
  session number, (4) `git status` in a worktree you don't recognize shows
  "nothing to commit" but the working tree contains a session handoff doc you
  haven't seen written this turn. Root cause: a prior orchestrator (parallel
  session, aborted earlier run, or a /session-handoff that ran partway and
  lost its context) created the branch + handoff doc + push + PR before the
  current orchestrator picked up. Without this check, you'll write a fresh
  handoff doc in the main checkout, commit to a different branch, and open
  a duplicate PR — leaving two competing handoff docs for session N.
author: Claude Code
version: 1.0.0
date: 2026-05-26
disable-model-invocation: true
---

# /session-handoff pre-flight: detect prior orphan branch + PR before writing a new handoff doc

## Problem

You're running /session-handoff at the end of a long, multi-step session. You start drafting `docs/handoffs/session_N_handoff.md` in the main checkout. Everything looks fine — `git status` in the main checkout shows the file as untracked, you write 200 lines, you're ready to commit.

Then you go to create the PR branch and `git worktree add` fails with "branch already exists." Or worse, you don't check and silently create a duplicate PR.

Root cause: a prior orchestrator already did most of /session-handoff for this session. That orchestrator:
1. Created branch `docs/sN-handoff` off main
2. Created a worktree (often mis-labeled like `.claude/worktrees/sN+1-handoff` instead of `.claude/worktrees/sN-handoff`)
3. Wrote `docs/handoffs/session_N_handoff.md` in that worktree
4. Committed and pushed to `origin/docs/sN-handoff`
5. Opened a PR (often a thin one with just the handoff doc, missing the rest of the 7-bucket dispatch)
6. Then lost context, was interrupted, or didn't finish the rest of the workflow

The current orchestrator has no memory of that work — it's a different session instance — and sees only the fresh state. The detection signals are subtle:

- `git branch --list 'docs/sN-handoff'` shows `+ docs/sN-handoff` (the `+` means checked out in another worktree).
- `git worktree list | grep -i sN` reveals a worktree at an unfamiliar path.
- That worktree contains `docs/handoffs/session_N_handoff.md` but `git status` there reports "nothing to commit, working tree clean" — meaning the file is already tracked and committed.
- `gh pr list --head docs/sN-handoff --state open` returns an OPEN PR.

Without this check, you'll:
- Create a duplicate PR (`docs/sN-handoff-2` or similar) for the same session.
- End up with two competing handoff docs both claiming to describe session N.
- Confuse the next session's orchestrator about which doc to read.
- Waste compute writing 200 lines that already exist (often better-written by the prior attempt).

## Context / Trigger conditions

Run this pre-flight check at the start of /session-handoff Phase 1 (before drafting the handoff doc):

- `git worktree list` returns more entries than you remember creating this session.
- `git branch --list 'docs/sN-handoff' 'docs/sN-*'` shows a hit you didn't create.
- `gh pr list --state open --head 'docs/sN-handoff' --json number,title` returns ≥1 result.
- A worktree directory under `.claude/worktrees/` has a name involving the current or adjacent session number.

If any of these are true, the prior orphan exists. Stop and inspect before drafting.

## Solution

### Pre-flight runbook (30 seconds)

```bash
N=15  # current session number
PROJECT_ROOT=/path/to/repo

# 1. Branch check
git branch --list "docs/s${N}-handoff" "docs/s${N}-*"
# A `+` prefix means checked out in another worktree.

# 2. Worktree check
git worktree list | grep -iE "s${N}|handoff"

# 3. Open-PR check
gh pr list --state open --head "docs/s${N}-handoff" --json number,title,body
# Also try variants: docs/s${N}_handoff, docs/sN-handoff-bundle, etc.

# 4. If a worktree exists, inspect its working tree
cd /path/to/that/worktree
git status                        # "nothing to commit" means the docs are committed
ls docs/handoffs/session_${N}_handoff.md
wc -l docs/handoffs/session_${N}_handoff.md   # is there real content?

# 5. If a PR exists, check what's in it
gh pr view <N> --json files,body -q '{files:[.files[].path], body:(.body|.[0:300])}'
```

### Decision matrix

| Found | Action |
|---|---|
| Nothing (no branch, no worktree, no PR) | Proceed normally — create branch off origin/main + worktree + doc + PR. |
| Branch exists, worktree exists, docs already committed, PR open | **DO NOT create a new PR.** Use the existing worktree as your working dir. Add any missing bucket outputs (reviews/, analysis/, plan refresh, next-session prompt) as additional commits to the same branch. Update the PR description to reflect expanded scope. |
| Branch exists but no worktree (e.g., user pruned) | Create a fresh worktree for that branch: `git worktree add /path/to/worktree docs/sN-handoff`. Proceed as above. |
| Branch + worktree but no open PR (maybe abandoned without PR) | Decide: complete the existing branch and open the PR, OR start fresh. Default: complete the existing one — preserves the prior work. |
| Multiple competing branches (e.g., `docs/sN-handoff` + `docs/sN-handoff-bundle`) | Close the smaller / less complete one. Pick the one with more content; consolidate. |
| Worktree with an in-progress handoff doc but not committed | The prior orchestrator died mid-write. Read what's there, decide whether to extend or restart, then proceed in that worktree. |

### When inheriting an orphan handoff doc

Often the orphan is *better* than what you'd write fresh — the prior orchestrator may have had more context, included diff stats, captured nuances. Read it before deciding to overwrite.

Specifically check whether the orphan has things the freshly-drafted version typically lacks:
- Formal frontmatter (`label-audit-skipped:` etc.)
- PR-by-PR sections with diff counts
- Test count delta tables (per-PR, not just session totals)
- Compound "files modified" table covering all PRs
- Open review findings table with file:line specificity

If yes, keep the orphan and patch in whatever's missing (often: bucket footprint, mid-session incidents, cross-doc links).

If the orphan is thin or wrong, overwrite it — but commit on the same branch so the PR's history shows the evolution.

## Verification

After applying the runbook, verify:

1. `gh pr list --state open --head "docs/s${N}-handoff"` returns ≤1 result.
2. Only one `docs/handoffs/session_N_handoff.md` exists in the working tree of your active branch.
3. The PR description matches the actual scope of the branch (not the original thin scope, if you expanded).
4. No `docs/handoffs/session_N_handoff.md` is left untracked in any other worktree or in the main checkout.

## Example — Session 15, the-handover-repo

Mid-/session-handoff Phase 1, I wrote `session_15_handoff.md` (~220 lines) in the main checkout. Then `git worktree add origin/main -b docs/s15-handoff` failed with "branch already exists." Investigation:

```
$ git worktree list | grep -i s15
/Users/.../.claude/worktrees/s16-handoff  95e70df [docs/s15-handoff]
                              ^^^ mislabeled dir name — branch is correct
$ cd /Users/.../.claude/worktrees/s16-handoff
$ git status docs/handoffs/session_15_handoff.md
nothing to commit, working tree clean
$ wc -l docs/handoffs/session_15_handoff.md
193 lines
$ gh pr list --head docs/s15-handoff --state all --json number,title,state
{"number":67,"state":"OPEN","title":"docs(s15): session 15 handoff"}
```

The orphan handoff doc was actually richer than my fresh draft (formal frontmatter, PR-by-PR diff stats, test delta table). I deleted my draft, copied my bucket outputs (reviews/, analysis/, plan refresh, next-session prompt) into the existing worktree, committed onto `docs/s15-handoff`, and updated PR #67's description to reflect the expanded scope. No duplicate PR.

## Notes

- The mislabeled worktree directory name (`s16-handoff` checking out `docs/s15-handoff`) is a common artifact of [main-bash-cwd-persists-nested-worktree](../main-bash-cwd-persists-nested-worktree/) — the prior orchestrator was likely in a different cwd when creating the worktree. The branch name is the authoritative identifier; the directory name is just convenience.
- This skill applies to other "long-running orchestration" workflows too: `/ultrareview`, `/agent-review-panel`, `/loop`, and any custom workflow that creates branches + PRs. The detection runbook is the same; substitute the relevant branch / worktree naming convention.
- If the prior orphan is wrong-session (`docs/s14-handoff` when you're in S16), close that PR explicitly with a comment — don't leave dangling open PRs from a previous arc.
- The 30-second pre-flight cost is trivial relative to the cost of recovering from a duplicate-PR situation (resolving competing handoff docs, closing one PR, explaining the mess in commit messages).

## See also

- [`main-bash-cwd-persists-nested-worktree`](../main-bash-cwd-persists-nested-worktree/) — why orphan worktree dir names are often mislabeled.
- [`session-handoff-number-collision-with-unmerged-sibling`](../session-handoff-number-collision-with-unmerged-sibling/) — sibling scenario: two parallel orchestrators both claim session N+1.
- `session-handoff` (ships in the separate `session-handoff` plugin, not here) — the canonical workflow this skill protects.
- [`pr-hijack-via-stale-worktree-branch-ref`](../pr-hijack-via-stale-worktree-branch-ref/) — adjacent worktree-ref staleness pattern.
