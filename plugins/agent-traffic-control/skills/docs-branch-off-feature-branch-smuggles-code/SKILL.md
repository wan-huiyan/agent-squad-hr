---
name: docs-branch-off-feature-branch-smuggles-code
description: |
  Catch the bug class where a "docs follow-up" PR silently ships the
  parent feature's code under a `docs(sN):` title because the docs branch
  was created from the current working branch (a feature branch),
  not from `origin/main`. Use when: (1) you just opened a PR titled
  `docs(...)` or `chore(...)` after wrapping up a feature session,
  (2) `gh pr diff <N> --name-only` shows files OUTSIDE `docs/` (source
  code, Dockerfile, tests, generated artefacts), (3) `git log
  origin/main..HEAD` shows TWO+ commits where you only authored
  one or two docs commits, (4) the surprise commit author/message is
  from your own earlier feature work on the parent branch, (5) the PR
  body claims "docs-only" but the actual diff carries code. Trigger
  surface: end-of-session handoff workflows that `git checkout -b
  docs/sN-handoff` from inside a feature worktree that's still on
  `feat/sN-feature`. Squash-merging such a PR auto-promotes the
  feature code under a "docs" title — bypassing the planned
  merge-and-deploy gate for the feature PR, and silently deploying
  if cloudbuild.yaml auto-fires on main push. Sister to
  `stale-base-pr-silently-reverts-upstream-content` (which is about
  PR-vs-PR overlap on the same files); this skill covers the
  branch-base trap that smuggles ENTIRE commits into the docs PR.
  Sister to `pr-hijack-via-stale-worktree-branch-ref` (which is about
  worktree branch-ref staleness); this skill covers the orthogonal
  "wrong base at branch-creation time" trap. Detection: code-reviewer
  agent or a `gh pr diff --name-only | grep -v '^docs/'` check before
  squash-merge. Recovery: rebase `--onto origin/main feat/sN-feature
  docs/sN-handoff` to drop the smuggled commits, force-push.
author: Claude Code
version: 1.1.2
date: 2026-06-23
disable-model-invocation: true
---

# Docs follow-up branch off a feature branch smuggles feature code

## Problem

You finish a feature session, the work lives on `feat/sN-feature` (PR
already open). You want to write a session handoff + the next-session
prompt as a docs-only PR. You run:

```sh
git checkout -b docs/sN-handoff-and-sN+1-prompt
# ...write docs, commit, push, gh pr create...
```

The new branch was created from the current `HEAD` — which is still
`feat/sN-feature`'s tip. The new docs branch carries the feature
commit AND your docs commits. The PR title is `docs(sN+1):...`. The
diff includes Dockerfile + src/routes/*.py + tests/*.py from the
feature work.

If a reviewer squash-merges the "docs" PR, you've just landed the
feature code under a docs title — bypassing the planned merge order,
potentially auto-deploying if cloudbuild.yaml triggers on main push,
and definitely confusing anyone who reads the git log later.

## Context / Trigger Conditions

There are two variants with different symptoms depending on whether the
feature PR is still open or was already squash-merged to main:

### Variant A — Feature PR still open (silent code smuggling)

You are in this trap when **all** of these hold:

1. **End-of-session handoff workflow.** You're wrapping up a session
   that produced code changes (already on a feature branch with an
   open PR) and you're about to write the handoff doc + next-session
   prompt as a separate PR.

2. **You created the docs branch via `git checkout -b` from inside
   the feature worktree** without specifying an explicit base. Most
   common variant: you're sitting on `feat/sN-feature` and run
   `git checkout -b docs/sN-handoff` — the new branch points at
   `feat/sN-feature`'s tip.

3. **`gh pr diff --name-only` shows non-`docs/` files.** Code,
   Dockerfile, tests, lock files, generated artefacts. The docs PR
   title says it ships docs but the diff contradicts.

4. **`git log origin/main..HEAD` shows more commits than you
   authored this session for docs.** The extra commit(s) are from
   your own feature work, carried over by the implicit base.

5. **PR title prefix is `docs(...)` or `chore(...)`.** This is the
   signal that maximises the trap's damage — reviewers may assume the
   PR can be squash-merged without scrutiny because "it's just docs".

### Variant B — Feature PR already squash-merged (CONFLICTING state)

This variant occurs when the feature PR **has already merged to main
via squash**. The local feature branch tip (`feat/sN-feature`) has a
different SHA than the squash commit that landed on main — so creating
a docs branch from it diverges from main immediately.

Symptoms differ from Variant A:
- GitHub shows the PR as **`CONFLICTING`** (cannot merge cleanly)
- The PR diff lists **many files** (all the feature files + the docs
  files), not just docs
- `git merge-base HEAD origin/main` returns an ancestor SHA well
  before the feature merge
- The code-reviewer agent report says something like "PR lists 18
  files including production code" even though you only committed 2

This variant is actually LESS dangerous than Variant A (the feature
code is already on main, so squash-merging the docs PR wouldn't
re-deploy it — it would just create a conflict), but it still blocks
the docs PR from merging cleanly and requires a fix.

## Diagnostic — pre-merge

Run BEFORE squash-merging any docs-titled PR:

```sh
# 1. Confirm the PR is truly docs-only.
gh pr diff <N> --name-only | grep -v '^docs/' && echo "TRAP: code in docs PR"

# 2. Inspect actual commits relative to main.
git fetch origin main
git log origin/main..HEAD --oneline
# Should be only your docs commits. If you see commits authored on the
# feature branch (their SHAs match `git log feat/sN-feature` output),
# the docs branch was implicitly stacked.

# 3. If you're already on the docs branch in a worktree:
git merge-base HEAD origin/main
# This should equal `git rev-parse origin/main` if the branch is clean.
# If it equals an older commit, the branch is based on something
# older than main — possibly the feature branch's base.
```

## Solution

### Variant A recovery — rebase onto main

The standard fix is `git rebase --onto`:

```sh
# Form: git rebase --onto <new-base> <old-base> <branch>
# In English: "take <branch>, drop everything since <old-base>'s tip,
# and replant the remainder onto <new-base>."
git rebase --onto origin/main feat/sN-feature docs/sN-handoff

# Verify only your docs commits remain.
git log origin/main..HEAD --oneline

# Verify the diff is now docs-only (3 dots: what the branch PROPOSES,
# measured from the merge-base, which is what GitHub's diff shows).
git diff --name-only origin/main...HEAD

# Force-push (use --force-with-lease to refuse if someone pushed
# concurrently — saves you from clobbering review comments etc.).
git push --force-with-lease
```

After force-push, `gh pr diff <N> --name-only` will refresh on the
next call and show only the docs files.

### Variant B recovery — fresh branch + git show (faster when feature already merged)

When the feature is already on main, rebasing is unnecessary. It's
faster to close the conflicting PR and create a clean branch:

```sh
# 1. Close the conflicting docs PR.
gh pr close <N> --comment "Closing — branch based on pre-squash feature tip. Re-opening clean."

# 2. Create a fresh branch off origin/main.
git fetch origin main
git checkout -b docs/sN-handoff-clean origin/main

# 3. Extract only the docs files from the old branch — no code included.
git show docs/sN-handoff:docs/handoffs/session_N_handoff.md \
  > docs/handoffs/session_N_handoff.md
git show docs/sN-handoff:docs/handoffs/session_N+1_prompt.md \
  > docs/handoffs/session_N+1_prompt.md

# 4. Commit and push.
git add docs/handoffs/session_N_handoff.md docs/handoffs/session_N+1_prompt.md
git commit -m "docs(sN): session handoff ..."
git push -u origin docs/sN-handoff-clean

# 5. Open the new PR.
gh pr create --title "docs(sN): ..." --body "..."
```

Verify the new PR diff is docs-only:
```sh
gh pr diff <new-N> --name-only | grep -v '^docs/' && echo "TRAP" || echo "clean"
```

**Optional: refresh the PR body** if it had any "ships X, Y, Z" claims
that the original (stacked) state contradicted. Per the
PR-description-refresh feedback rule.

## Prevention

Two preventive patterns:

### Pattern A: explicit `origin/main` base at branch creation

```sh
# DON'T: implicit base = current HEAD (the feature branch's tip)
git checkout -b docs/sN-handoff

# DO: explicit base
git checkout -b docs/sN-handoff origin/main
```

This is the cheapest prevention and works in any worktree.

### Pattern B: dedicated worktree off main for docs work

```sh
# DON'T: write docs from inside the feature worktree
cd .claude/worktrees/feat-sN
git checkout -b docs/sN-handoff       # implicit feature-branch base — trap

# DO: spin a fresh worktree pinned to origin/main
git worktree add /absolute/path/.claude/worktrees/sN-docs \
  -b docs/sN-handoff origin/main
```

Worktrees enforce branch isolation. The docs worktree starts on
`origin/main`, period. Sister skill: `feedback_worktree_add_absolute_paths`
(use absolute paths for `git worktree add` to defeat Bash cwd
persistence).

### Pattern C: PR-body sanity check before opening the PR

```sh
# Run this as part of any handoff PR workflow:
gh pr diff <N> --name-only | sort | tee /tmp/pr-files.txt
case "$(cat /tmp/pr-files.txt | grep -v '^docs/')" in
  "") echo "PR is docs-only — safe to merge" ;;
  *)  echo "ABORT: non-docs files in PR" && cat /tmp/pr-files.txt ;;
esac
```

This is the cheapest detection at PR creation time. The
`session-handoff` skill's Phase 4 step 22 already runs a
`code-reviewer` agent that includes this check — but if you skip the
agent for time pressure, run the grep manually.

## Verification

After rebase + force-push:

- `gh pr diff <N> --name-only` returns ONLY paths under `docs/` (or
  whatever your taxonomy is for the PR's intended scope).
- `git log origin/main..HEAD --oneline` shows only the commits you
  authored this session for docs.
- The PR's "Files changed" tab on GitHub shows the same — refresh if
  stale.
- Squash-merge proceeds cleanly with the expected title.

## Example — 2026-06-23 the project S211 (Variant B: feature already merged)

End of session S211 (per-record drawer behaviour filter, PR #1360 already
squash-merged to main as `b5871bc0`). Wrote handoff + S212 prompt. Created
the docs branch:

```sh
git checkout -b docs/s211-session-handoff
# HEAD was feat/s211-drivers-drawer-behaviour-filter's tip (pre-squash SHA)
```

`code-reviewer` agent caught it during the auto-merge review pass:

> HIGH — Not "docs-only" and it won't merge as-is. PR lists 18 files
> including production code (app.py, bq_queries.py, behaviour_taxonomy.py,
> JS/CSS/HTML, tests). Branch was cut from `56e189f5` before `b5871bc0`
> merged, so it carries a divergent duplicate of the shipped feature.
> PR state = CONFLICTING/DIRTY.

Recovery using the Variant B (fresh branch) approach:

```sh
gh pr close 1366 --comment "Closing — branch based on pre-squash feature tip."

git fetch origin main
git checkout -b docs/s211-handoff-clean origin/main

git show docs/s211-session-handoff:docs/handoffs/2026-06-23-s211-...-handoff.md \
  > docs/handoffs/2026-06-23-s211-...-handoff.md
git show docs/s211-session-handoff:docs/handoffs/2026-06-24-s212-...-prompt.md \
  > docs/handoffs/2026-06-24-s212-...-prompt.md

git add docs/handoffs/*.md
git commit -m "docs(s211): session handoff ..."
git push -u origin docs/s211-handoff-clean
gh pr create --title "docs(s211): ..."  # → PR #1370, merged cleanly
```

The reviewer also caught an internal-consistency error (§6 said
`docs/s210-session-handoff` instead of `docs/s211-handoff-clean`) — fixed
before the clean PR was merged.

## Example — 2026-05-27 brief-runner Session 20

End of session, sitting in `.claude/worktrees/first-delivery` on branch
`feat/s20-wire-render-route` (PR #90, F10+F11 fix, ~600 LOC across
Dockerfile + src/routes/render.py + tests/test_routes/test_render.py +
docs/analysis/discovery_v2_e2e_smoke.md). Need to write the S21 prompt
as a separate docs PR.

```sh
git checkout -b docs/s20-handoff-and-s21-prompt    # IMPLICIT BASE: feat/s20-wire-render-route
# ...wrote session_21_prompt.md, committed, pushed, opened PR #92
# PR title: "docs(s21): session 21 prompt — deploy+verify, metrics, design sweep, polish"
```

`code-reviewer` agent caught it on the auto-merge review pass:

> HIGH — PR is NOT docs-only. User briefed this as "ships two files"
> but PR #92 actually ships 6 files including a 254-line rewrite of
> `src/routes/render.py`, `Dockerfile`, and 161 lines of test
> changes. Squash-merging would auto-deploy F10+F11 fix without the
> explicit Task 1 live-verification step the S21 prompt mandates as
> non-negotiable.

Fix took 90 seconds:

```sh
git rebase --onto origin/main feat/s20-wire-render-route \
  docs/s20-handoff-and-s21-prompt
# Successfully rebased and updated.

git diff --name-only origin/main...HEAD
# docs/handoffs/session_20_handoff.md
# docs/handoffs/session_21_prompt.md   ← only docs, as intended

git push --force-with-lease
# (forced update) → PR #92's diff refreshes to 2 files
```

Then squash-merged cleanly. The render.py / Dockerfile changes stayed
on PR #90 where they belong, awaiting their own merge gate.

## Notes

- **The trap is asymmetrically dangerous for docs PRs vs feature PRs.**
  A reviewer scrutinising a `feat(...)` PR will see the code diff and
  treat it as the feature. A reviewer scrutinising a `docs(...)` PR
  may auto-approve without reading the diff carefully. Squash-merging
  it auto-deploys if your CI is wired to deploy on main pushes.

- **The trap is invisible to `gh pr view` if you only check title +
  body.** You MUST inspect `gh pr diff --name-only` or
  `git log origin/main..HEAD` to see it.

- **`--force-with-lease` is the right force flag here.** Plain
  `--force` would overwrite any review comments + co-author commits;
  `--force-with-lease` refuses if the remote moved underneath you.

- **Sister trap (different mechanism, similar damage):**
  `pr-hijack-via-stale-worktree-branch-ref` covers the case where a
  worktree's local branch ref drifts from origin and a `git push`
  re-uses the wrong ref. This skill covers the case where the
  branch was CREATED from the wrong base in the first place.

## References

- Sister: `stale-base-pr-silently-reverts-upstream-content` —
  parallel-PR overlap on same files; different mechanism.
- Sister: `pr-hijack-via-stale-worktree-branch-ref` — worktree
  ref drift; different mechanism.
- Sister: `feedback_worktree_add_absolute_paths` — prevention via
  explicit worktree base.
- `session-handoff` skill — a separate plugin, published at
  https://github.com/wan-huiyan/session-handoff — Phase 4 step 22, the
  `code-reviewer` agent pass that catches this trap if you skip the
  manual check.
