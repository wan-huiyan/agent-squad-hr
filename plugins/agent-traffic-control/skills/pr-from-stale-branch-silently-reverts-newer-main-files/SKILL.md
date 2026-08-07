---
name: pr-from-stale-branch-silently-reverts-newer-main-files
description: |
  Trap: opening/merging a PR from a branch that was created a while ago can
  SILENTLY DELETE (revert) files that landed on main AFTER your branch point —
  with NO merge conflict to warn you. Use when: (1) about to `gh pr create` or
  squash-merge from a long-lived / earlier-branched branch; (2) `git diff
  origin/main..HEAD --stat` shows DELETIONS of files you never touched; (3) a PR
  diff is unexpectedly large or removes another session's/teammate's work; (4)
  the repo has many parallel branches + a squash-merge flow (each squash makes
  older branches progressively staler). The fix is to merge origin/main INTO the
  branch first, then re-verify the diff shows only your additions. Distinct from
  merge-CONFLICT skills — this is the no-conflict, clean-merge silent-regression
  case. See also: pr-conflict-from-mid-flight-merges,
  large-redesign-parallel-branch-collision-audit, merge-conflict-generated-files.
  ALSO covers the variant where the branch is NOT behind main: its parent IS
  current main and `git merge origin/main` says "Already up to date", because
  only the POINTER moved while the TREE stayed old. Every behindness check
  passes and the diff still deletes what landed in between. Use when a PR
  deletes files you never touched AND the branch looks perfectly rebased.
  Auditing as a VICTIM: source every content needle from the merged diff
  (`git show <squash-sha> -- <file>`), never from memory, and check the state AT
  the suspect commit rather than at origin/main.
author: Claude Code
version: 1.2.0
date: 2026-06-17
disable-model-invocation: true
---

# A PR from a stale branch can silently revert newer main files (no conflict)

## Problem
Your branch was cut from main at commit X. Since then, other PRs added files
B, C, D to main. Your branch never had B/C/D. When you open a PR (or merge),
git computes the diff as `origin/main..HEAD` — and because your branch *lacks*
B/C/D, the diff shows them as **DELETIONS**. Merging the PR removes B/C/D from
main, reverting work you never touched. **There is no merge conflict** (your
branch simply doesn't mention those files), so nothing warns you — the PR looks
"clean" and the deletions hide in the diff stat.

## Context / Trigger Conditions
- About to `gh pr create` / `gh pr merge --squash` from a branch that's been
  around for more than a session or two, or in a repo with many parallel branches.
- `git diff --stat origin/main..HEAD` lists files being **removed** that you have
  no memory of touching (e.g. someone else's analysis/handoff/docs from a sibling
  session that merged while you worked).
- The PR's deletion count is suspiciously high for the work you did.
- Squash-merge workflows make this WORSE over time: each squash rewrites main's
  history, so a branch that "was only a bit behind" reverts more with each sibling merge.

## Solution
1. **Before** creating/merging the PR, always sanity-check the full diff stat:
   ```sh
   git fetch origin main
   git diff --stat origin/main..HEAD
   ```
   Scan for `---` / deletion lines on files outside your scope.
2. If you see spurious deletions, **merge origin/main into your branch first**
   (do NOT just merge the PR):
   ```sh
   git merge origin/main --no-edit      # clean if your changes are file-disjoint
   ```
   This re-adds B/C/D to your branch so they're no longer "deleted" in the diff.
3. **Re-verify**: `git diff --stat origin/main..HEAD` should now show ONLY your
   own additions/edits. Then push + PR.
4. If the merge DOES conflict, you've crossed into merge-conflict territory →
   hand off to `pr-conflict-from-mid-flight-merges` /
   `merge-conflict-generated-files` (generated-file union playbooks).

## The harder variant: the branch is NOT behind main, and every check says so

Everything above assumes the branch is *behind* main, so "am I behind?" catches
it and "merge main in" fixes it. **Both fail on the variant that does the most
damage**, because only the branch POINTER was moved onto current main while the
working TREE stayed old:

- `git log --oneline -2` shows your commit sitting directly on top of the newest
  main commit. Perfectly linear. Looks freshly rebased.
- `git merge-base --is-ancestor origin/main HEAD` → **true**. You are not behind.
- `git merge origin/main` → **"Already up to date."** The documented fix is a
  no-op.
- No conflict, `mergeable: MERGEABLE`, CI green.

And the diff still deletes every file that landed between the old tree and the
new parent. How it happens: `git reset --soft origin/main` (or `--mixed` then
`git add -A`) run from a branch whose base was old — the index still holds the
OLD tree, so committing records "delete everything added since" as part of your
change. A stale worktree committed with `git add -A` does the same.

**The check that survives this** — deletions, not behindness:

```sh
git fetch origin main
git diff --diff-filter=D --name-only origin/main...HEAD    # MUST be only files you meant to delete
```

**And the tell that identifies it as a stale tree**, when the deletion list is
long enough to argue about — compare the diff size against several candidate
bases. If your branch differs from an OLD commit by FEWER files than from its
own parent, the tree predates the parent:

```sh
for base in <parent> <a few older main shas>; do
  printf "%s  %s files\n" "$base" "$(git diff --name-only $base HEAD | wc -l)"
done
```

**The fix is NOT to merge main in** (it is already an ancestor). Restore the
paths, or rebuild the work on a fresh checkout of current main:

```sh
git checkout origin/main -- <each deleted path>     # surgical
# or: branch from origin/main and re-apply only your own edits
```

## If one of these has already merged: splice, never revert

`git revert` on the offending squash commit re-deletes everything that has
merged *since* — the same failure, aimed the other way. Recover each lost object
individually from the last commit where it was intact and re-insert it into
*current* main:

```sh
git checkout <last-good-sha> -- <path>                    # files
git show <last-good-sha>:<ledger> | ...                   # hand-edited ledgers: splice ONE object
```

**Check the hand-maintained ledger separately from the files.** A tracker entry
can be gone while its files are fine, and vice versa — and a text field can be
rolled back to its earlier wording while the record still exists, which no
id-presence check catches. Diff the field, not just the key.

### Checking as a victim: scope the check to what you TOUCHED, not what you MADE

The natural check — and the one a broadcast asks for — enumerates *the things I
created*. **The revert's scope is *the things I touched*, which is larger**, and
the gap between them is where a clean-looking check goes wrong. Three ways it
did, all in one session, each after an earlier check had reported clean:

- **In-place edits to records you did not create.** Amending someone else's
  standing ruling, appending a "DONE" paragraph to a pre-existing task, editing
  a caveat block — none of those produce a new id, so an id/status/PR-number
  sweep passes while the prose underneath has reverted. One standing ruling was
  left publishing a superseded range with no marker on it, and the sweep that
  was supposed to have verified it had looked only at `status` and `prs`.
- **A PARTIAL rollback inside one record.** Half of an appended edit survived
  and half reverted, so a single entry said the question was *settled* and, two
  sentences later, quoted the range the settlement replaced. **A half-reverted
  record reads self-consistent** — worse than a clean revert, which at least
  looks obviously old.
- **A moved number is indistinguishable from a reverted one by grep.** A README
  count read 560 where the session had written 546; both a file-existence check
  and a content-needle check flagged it lost, and it was not — sibling sessions
  had added tests. **Re-derive the value; do not compare the string.** The
  needle check is right for prose and wrong for anything computed.

The executable form is a needle per *claim*, not per file — one distinctive
phrase for every paragraph you amended, every ledger field you edited, and every
computed figure re-derived rather than matched:

```sh
REF=${REF:-origin/main}                       # override to check a BRANCH pre-merge
f() { git show "$REF:$2" | grep -qF -- "$3" && echo "OK   $1" || echo "LOST $1"; }
f "ruling: the amendment"  path/to/ledger.js  "AMENDED 2026-08-07 BY"
f "caveat: pinned, not open" path/to/ledger.js "PINNED 2026-08-07 at"
# ...and for anything computed, re-measure instead of grepping:
test "$(pytest docs -q --co 2>&1 | tail -1 | awk '{print $1}')" = "$(grep -oE '[0-9]+ collected' README.md | head -1 | cut -d' ' -f1)"
```

Keep the `REF` override: the same script is the pre-merge gate for *your* PR and
the post-merge audit for someone else's, and only the second one is usually
written.

#### Where the needle comes from — and what it costs to guess one

**Take every needle out of the merged artifact, never out of recall.** Paste the
line you took it from next to the check:

```sh
git show <squash-sha> -- path/to/file.py | grep '^+' | grep -i finalist
# → +    finalist_km = ...           ← THIS line is the needle
```

The audit of PR #853 (DoodleRun, 2026-08-07, tracked under #863) grepped for
`route_km_finalist` — a
symbol name recalled from the session that had written it. The real symbol was
**`finalist_km`**. The grep found nothing, and for a minute the session believed
an entire merged PR had been deleted.

**The failure is two-sided, and only one side is intuitive:**

| A guessed needle that… | …manufactures |
|---|---|
| MISSES | a phantom deletion — alarming, but self-correcting: somebody goes and looks |
| happens to MATCH | a **false all-clear** — and nobody re-checks a clean audit |

The matching case is the worse one and produces no symptom whatsoever. That is
why the provenance rule is absolute rather than a nicety: a needle you cannot
point at a line for is not evidence in *either* direction.

#### Check the state AT the suspect commit, not at `origin/main`

Current state cannot distinguish **"never hit"** from **"hit, and restored by
someone else"**. If a sibling session already noticed the revert and pushed a
recovery PR, `origin/main` holds your content again — and an audit run against
main reads that as proof you were never affected, which is exactly backwards when
the question is what a particular merge did.

```sh
REF=<suspect-squash-sha> ./audit.sh   # "did THAT merge drop it?"  ← the real question
REF=origin/main          ./audit.sh   # "is it there right now?"   ← a different one
```

This is what the `REF` override above is for, and it is worth running both ways:
the first says whether you were a victim, the second says whether anything is
still outstanding.

**Then tell the other sessions.** Losses are per-session and nobody else can see
yours; a broadcast with a copy-pasteable `git cat-file -e origin/main:<path>`
loop is the only thing that finds the ones whose owners have already wrapped.

## Verification
Post-merge-of-main, `git diff --stat origin/main..HEAD` lists only files you
intended to change (no foreign deletions). The PR's "files changed" on GitHub
matches your mental model of the work.

## Example (this repo, S258, 2026-06-17)
Branch `docs/s258-prompt-update` was cut before S257b's anomaly-alignment docs
merged to main. The first `git diff --stat origin/main..HEAD` showed 5 unrelated
files being **deleted** (−384/−93/−65/−40/−19 lines: the anomaly HTML, a content
snapshot, two S257b handoffs, a legend edit) alongside the intended S258 additions
— a clean merge would have reverted all of S257b's work. `git merge origin/main
--no-edit` was conflict-free (docs were disjoint) and the diff then showed only the
7 S258 files. PR opened safely.

## Example 2 — the variant, and it cost four sessions (DoodleRun, 2026-08-07)

PR #853 (`claude/floor500-rulings`, squash `6c79ff26`) shipped three ticked
owner rulings **and deleted 11 files plus 15 hand-maintained ledger entries**
belonging to four other sessions — 59 files, 5,081 deletions.

**Its parent was the newest commit on main.** `git log` showed it directly on
top; nothing was behind. The tree, however, was ~8 hours old: the branch tip
differed from its own parent by **59** files but from an 8-hour-old commit by
only **39**. Everything merged in that window was recorded as a deletion.

**Nothing gated it.** The PR was **created at 09:30:12Z and merged at
09:30:23Z — eleven seconds** — so no reviewer and no CI run ever saw the diff.

**It was found 3½ hours later, by accident**, during an unrelated wrap-up check
that happened to re-read the ledger. Two follow-up PRs restored some casualties;
one session's four files and six ledger entries were still missing hours after
that, because that session had already finished and nobody was coming back.

**The two habits that would have caught it**, in order of cost: run
`git diff --diff-filter=D` before merging, and — in a solo repo where no human
reviews — re-verify your own merged work still exists on main *after* the last
sibling merge, not at the moment you write the ledger entry.

## Notes
- The tell is **deletions in the diff stat**, not a conflict marker — conflict-only
  habits (rely on git to yell) miss this entirely.
- Same root cause as `large-redesign-parallel-branch-collision-audit` (branches
  drift from main), but that skill is a *pre-plan* collision audit across many
  branches; this is the *at-PR-time* per-branch check + the merge-main-in fix.
- `gh pr merge --delete-branch` may then fail with "main is already used by
  worktree at ..." when you run from a worktree — the merge still succeeded;
  delete the remote ref with `gh api -X DELETE repos/<owner>/<repo>/git/refs/heads/<branch>`.
