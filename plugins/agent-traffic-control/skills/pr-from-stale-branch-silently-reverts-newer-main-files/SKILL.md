---
name: pr-from-stale-branch-silently-reverts-newer-main-files
description: |
  Trap: merging a PR whose branch carries an OLD TREE silently DELETES
  (reverts) files that landed on main after that tree was built — with NO
  merge conflict to warn you, because a deletion your own commit records is
  not a conflict. Use when: (1) about to `gh pr create` or squash-merge from
  a long-lived / earlier-branched branch, from a worktree committed with
  `git add -A`, or after a `git reset --soft`; (2) `git diff --diff-filter=D
  --name-only origin/main...HEAD` lists files you never touched; (3) a PR
  diff is unexpectedly large or removes another
  session's/teammate's work; (4) the repo has many parallel branches + a
  squash-merge flow. Check DELETIONS, not behindness: the variant that does
  the damage is NOT behind main at all — its parent IS current main,
  `git merge origin/main` says "Already up to date" and every ancestor check
  passes, because only the POINTER moved while the TREE stayed old. Use when
  a PR deletes files you never touched AND the branch looks perfectly
  rebased. Merging main in is worth doing but does NOT prevent this. As a
  VICTIM: source every needle from the merged diff, never from memory, and
  check the state AT the suspect commit, not at origin/main. No-conflict
  silent regression, not a merge-CONFLICT skill. See also:
  git-diff-2dot-vs-3dot-merge-safety (the 2-dot FALSE alarm: the deletions
  are an artifact), pr-conflict-from-mid-flight-merges,
  large-redesign-parallel-branch-collision-audit,
  merge-conflict-generated-files.
author: Claude Code
version: 1.3.0
date: 2026-06-17
disable-model-invocation: true
---

# A PR from a stale branch can silently revert newer main files (no conflict)

## Problem

**Your branch's commit records a DELETION of files that are on main.** Merging it
applies that deletion, and **there is no merge conflict** — a removal your own
side committed is not a conflict, it is a change git carries out. The PR looks
"clean", `mergeable: MERGEABLE`, CI green, and the removals sit in the diff stat
where nobody reads them.

Nobody decides to delete anything. The tree gets that way by accident:

- **`git reset --soft origin/main`** (or `--mixed` then `git add -A`) run from a
  branch whose base was old. The POINTER lands on current main; the index still
  holds the OLD tree; the commit therefore records *"delete everything added
  since"* as part of your change.
- **Committing a stale worktree with `git add -A`.** Same result — the tree you
  stage predates main, so everything main gained is staged as removed.
- **A branch re-created or re-pointed onto a newer base while its working tree
  stayed old.**

### What does NOT cause it: simply being behind main

A branch that merely *lacks* files B/C/D — never had them, never recorded
deleting them — **does not delete them on merge.** GitHub computes the
**merge-base** diff (`git diff origin/main...HEAD`, three dots) and performs a
three-way merge, which preserves B/C/D.

The thing that *looks* like this trap and is not: `git diff origin/main..HEAD`
(**two** dots) compares tip to tip, so every file main gained after your branch
point renders as a deletion your branch appears to be making. That is an
artifact of the wrong command, not a pending revert. Verified: for one PR,
GitHub reported 5 files / 219 insertions / 16 deletions and three-dot matched
exactly, while two-dot reported 4 files / 13 insertions / 22 deletions — a
different file list and deletions that did not exist. Full treatment:
`git-diff-2dot-vs-3dot-merge-safety`.

Three-dot is not the lax option, either — a branch that genuinely deletes another
session's 418-line file still shows `418 deletions` under three-dot. It reports
real removals and drops invented ones.

**So the question is never "am I behind?" It is "does my branch record a
deletion?"** Every behindness check passes on the variant that does the damage.

## Context / Trigger Conditions
- About to `gh pr create` / `gh pr merge --squash`, especially after a
  `git reset --soft`, a rebase, or a `git add -A` in a worktree you had left
  sitting for hours.
- `git diff --diff-filter=D --name-only origin/main...HEAD` lists files you have
  no memory of touching (e.g. someone else's analysis/handoff/docs from a sibling
  session that merged while you worked).
- The PR's deletion count is suspiciously high for the work you did.
- Many parallel branches + a squash-merge flow, so sibling work lands on main
  continuously while your tree sits still.

## Solution

1. **Before** creating/merging the PR, ask the only question that matters —
   what does this branch DELETE, measured from the merge-base:
   ```sh
   git fetch origin main
   git diff --diff-filter=D --name-only origin/main...HEAD   # MUST be only files you meant to delete
   git diff --stat origin/main...HEAD                        # and only files you meant to touch
   ```
   Three dots, and `origin/main` rather than `main` — a stale *local* `main` ref
   makes even the three-dot diff over-report
   (`worktree-stale-local-main-ref-inflates-pr-diff`).
2. **If the deletion list is empty, you are done.** There is nothing to fix, and
   nothing to rebase — whatever the two-dot stat showed.
3. **If it is not empty**, confirm it is a stale tree before touching anything.
   Every behindness check will pass, so use arithmetic instead: compare the diff
   size against several candidate bases. If your branch differs from an OLD
   commit by FEWER files than from its own parent, the tree predates the parent:
   ```sh
   for base in <parent> <a few older main shas>; do
     printf "%s  %s files\n" "$base" "$(git diff --name-only $base HEAD | wc -l)"
   done
   ```
4. **Fix it by restoring the paths, not by merging main in** — main is usually
   already an ancestor, so the merge is a no-op:
   ```sh
   git checkout origin/main -- <each deleted path>     # surgical
   # or: branch from origin/main and re-apply only your own edits
   ```
   Then re-run step 1. The deletion list must come back empty.
5. If a merge you do run DOES conflict, you've crossed into merge-conflict
   territory → hand off to `pr-conflict-from-mid-flight-merges` /
   `merge-conflict-generated-files` (generated-file union playbooks).

### On the old advice: "always `git merge origin/main` before every PR"

Worth doing, for reasons that are real — it surfaces conflicts on your own time
instead of at merge time, and it lets you run the tests on the tree that will
actually land. **But it does not prevent a revert**, and it was never the
mechanism:

- Against the *stale tree* case it is a **no-op**: main is already an ancestor,
  so `git merge origin/main` prints "Already up to date" and the recorded
  deletions survive it untouched.
- Against the *behind but clean* case there was nothing to prevent: a three-way
  merge already preserved those files. What merging main in changes is the
  **measurement** — it makes a two-dot diff stop showing phantom deletions.
  Making a wrong command give the right answer is not the same as fixing a risk.

Keep it as hygiene. Do not count it as the check. The check is step 1.

## Why every behindness check passes on the stale-tree variant

Worth spelling out, because each of these individually reads as "you are fine":

- `git log --oneline -2` shows your commit sitting directly on top of the newest
  main commit. Perfectly linear. Looks freshly rebased.
- `git merge-base --is-ancestor origin/main HEAD` → **true**. You are not behind.
- `git rev-list --count HEAD..origin/main` → **0**.
- `git merge origin/main` → **"Already up to date."**
- No conflict, `mergeable: MERGEABLE`, CI green.

Reproduced in a controlled repo: the ancestor gate exits 0, the behind-count is
0, and the merge still deletes three files. Only
`git diff --diff-filter=D --name-only origin/main...HEAD` reports them.

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
computed figure re-derived rather than matched. **Save it as a file** (called
`needle-audit.sh` throughout this section), because you will run it more than
once with different values of `REF`:

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
REF=<suspect-squash-sha> sh needle-audit.sh   # "did THAT merge drop it?"  ← the real question
REF=origin/main          sh needle-audit.sh   # "is it there right now?"   ← a different one
```

This is what the `REF` override above is for, and it is worth running both ways:
the first says whether you were a victim, the second says whether anything is
still outstanding.

**Then tell the other sessions.** Losses are per-session and nobody else can see
yours; a broadcast with a copy-pasteable `git cat-file -e origin/main:<path>`
loop is the only thing that finds the ones whose owners have already wrapped.

## Verification
`git diff --diff-filter=D --name-only origin/main...HEAD` is **empty** (or lists
only files you meant to delete), and `git diff --stat origin/main...HEAD` lists
only files you intended to change. The PR's "files changed" on GitHub matches
that same list — it is computed the same way.

## Example 1 — RETRACTED: this was the two-dot false alarm, not the trap

*Published in 1.0.0–1.2.0 as a worked case. It was not one. Corrected in 1.3.0;
kept here because the artifact is common and worth recognising.*

Branch `docs/s258-prompt-update` (this repo, S258, 2026-06-17) was cut before
S257b's anomaly-alignment docs merged to main. `git diff --stat
origin/main..HEAD` — **two dots** — showed 5 unrelated files being "deleted"
(−384/−93/−65/−40/−19 lines: the anomaly HTML, a content snapshot, two S257b
handoffs, a legend edit).

**Nothing was ever at risk.** The branch never had those files and never
recorded deleting them; three-dot would have reported no deletions and the
three-way merge would have preserved every one of them. The original entry
concluded *"a clean merge would have reverted all of S257b's work"* — **that
claim was false**, and it is retracted. `git merge origin/main --no-edit` did
run and was conflict-free, but what it fixed was the diff display, not a
pending revert.

The lesson that survives: a two-dot stat full of red on files you never touched
is the *expected* output of the wrong command. Re-run it with three dots before
you rebase, block, or escalate anything.

## Example 2 — REAL, and it cost four sessions (DoodleRun, 2026-08-07)

PR #853 (`claude/floor500-rulings`, squash `6c79ff26`) shipped three ticked
owner rulings **and deleted 11 files plus 15 hand-maintained ledger entries**
belonging to four other sessions — 59 files, 5,081 deletions.

**These deletions were genuine, not a two-dot artifact.** The branch's parent
*was* main's tip, so the merge base was that same commit and the two-dot and
three-dot diffs were identical — the 5,081 deletions are what GitHub merged.

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
- The tell is **deletions under a THREE-dot diff**, not a conflict marker —
  conflict-only habits (rely on git to yell) miss this entirely, and two-dot
  habits raise the alarm on branches where nothing is wrong.
- Same root cause as `large-redesign-parallel-branch-collision-audit` (branches
  drift from main), but that skill is a *pre-plan* collision audit across many
  branches; this is the *at-PR-time* per-branch deletion check.
- `gh pr merge --delete-branch` may then fail with "main is already used by
  worktree at ..." when you run from a worktree — the merge still succeeded;
  delete the remote ref with `gh api -X DELETE repos/<owner>/<repo>/git/refs/heads/<branch>`.

## See also

- **`git-diff-2dot-vs-3dot-merge-safety` — the canonical statement of the
  operator rule this skill depends on.** Read it first when the deletions you
  are looking at came out of a two-dot diff: `A..B` compares tip to tip and
  invents deletions; `A...B` measures from the merge base and is what GitHub
  shows. Versions 1.0.0–1.2.0 of this skill contradicted it without citing it.
- `worktree-stale-local-main-ref-inflates-pr-diff` — the other direction: a
  correct three-dot diff still over-reports when the LOCAL `main` ref is stale,
  because the merge base is taken against an ancient ref (one case: 92 files /
  8,381 insertions for a 6-file commit). Fetch first; name `origin/main`, not
  `main`. Its `merge-base --is-ancestor` check is necessary but not sufficient —
  the stale-tree variant above satisfies it and still deletes files.
- `stale-base-pr-silently-reverts-upstream-content` — the line-level sibling
  (your hunks overwrite a merged upstream edit inside a file both sides touched)
  rather than this whole-file case.
- `pr-conflict-from-mid-flight-merges` / `merge-conflict-generated-files` — where
  to go once git does raise a conflict.
