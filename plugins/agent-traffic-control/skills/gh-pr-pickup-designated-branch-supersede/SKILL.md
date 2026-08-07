---
name: gh-pr-pickup-designated-branch-supersede
description: |
  Finish somebody else's open draft pull request when your session must push to a different,
  designated branch name — base it on the PR head and supersede.
author: Claude Code
version: 1.0.0
date: 2026-07-06
---
# Picking up an existing PR when the harness designates a different branch

## Problem

A session is asked to "pick up PR #N and finish the tasks", but the
execution harness (Claude Code on the web, GitHub-Action-spawned sessions,
etc.) pre-designates a branch name for all pushes — different from PR #N's
head branch — and forbids pushing anywhere else. Three tempting wrong moves:

1. **Push to the PR's own head branch anyway.** Violates the harness branch
   contract; on some remotes (proxy-scoped credentials) the push is denied
   outright, or worse, silently allowed against the operator's intent.
2. **Start the designated branch from main.** You re-implement or cherry-pick
   the PR's work; the diff review context, commit messages, and the PR's own
   handoff docs (often committed ON the PR branch) are lost.
3. **Rewrite the inherited commits** (rebase --exec amend, squash locally)
   to satisfy a commit-signature/identity linter. The originals are already
   pushed on the open PR; rewriting forks the history and confuses the
   supersede story.

## Fix — the supersede pattern

```sh
# 1. Base the designated branch ON the PR head (keeps its commits + docs)
git fetch origin <pr-head-branch> main
git checkout -B <designated-branch> origin/<pr-head-branch>

# 2. If main moved since the PR forked, merge it now (one conflict pass early)
git merge origin/main -m "Merge main into <topic> continuation"

# 3. ...finish the work, commit...

# 4. PUSH WITH AN EXPLICIT REFSPEC — see trap below
git push -u origin <designated-branch>

# 5. Open the superseding PR; body says "Supersedes #N" + what was added
# 6. Comment on #N pointing to the new PR, then close #N (draft, unmerged)
```

## Trap: `checkout -B` onto a remote ref hijacks your upstream

`git checkout -B <designated> origin/<pr-head-branch>` sets the new branch's
upstream to `origin/<pr-head-branch>`. From then on a bare `git push`
(or pull) targets the ORIGINAL PR's branch — exactly what the harness
forbids — and `git status -sb` quietly shows
`<designated>...origin/<pr-head-branch> [ahead N]`. Always push with the
explicit form `git push -u origin <designated-branch>`; the `-u` repoints
the upstream at your own remote branch on first push.

## Trap: signature linters vs inherited history

Commit-identity/signature hooks ("commits will show as Unverified") list the
inherited PR commits too. Verify with
`git log --format='%h %an %ae | %cn %ce'` first: if author+committer already
match the required identity, the residual complaint is a missing
cryptographic signature you likely cannot produce in the container — and the
inherited commits are already pushed unsigned on the open PR, so rewriting
them buys nothing and breaks the shared history. Amend only YOUR tip commit
if asked; note that an API squash-merge at the end produces a
platform-signed commit on main regardless.

## Closing the original PR

A merged PR is finished history; but an open superseded DRAFT should be
closed, not left dangling — two open PRs for one change is how parallel
sessions double-merge. Sequence: create the new PR first, comment on the old
one ("Superseded by #M, which contains both commits from this branch plus
<what was added>"), then close it. Keep `Refs #issue` (not `Closes`) in the
new PR if the underlying issue is multi-part and stays open.

## Verification

```sh
git status -sb                 # upstream must be origin/<designated-branch>
git log --oneline <pr-head-sha>..HEAD   # your additions sit ON TOP of the PR
gh pr view <M> --json headRefName       # new PR's head = designated branch
gh pr view <N> --json state             # old PR = CLOSED, with pointer comment
```

## Example

2026-07-06, the-causal-impact-repo: PR #481 (branch
`claude/execute-next-session-prompt-xmp68q`, WIP draft "tests pending") was
picked up by a session whose designated branch was
`claude/pr-481-the-causal-xvuiyv`. The designated branch was reset onto the
PR head, main (one docs commit ahead) merged in, the missing tests + review
fixes committed on top, pushed with an explicit `-u origin` refspec, and
PR #482 opened with "Supersedes #481" in the body; #481 got a pointer comment
and was closed. The stop-hook's "unverified commits" warning listed the two
inherited #481 commits — left untouched (already pushed on #481); only the
session's own tip was amended.

## Notes

- If the picked-up PR is already MERGED, this skill does not apply — restart
  the designated branch from the latest default branch instead and treat the
  follow-up as fresh work (never stack on merged history).
- Sister patterns: `gh-pr-create-orchestration-cwd-wrong-head` (explicit
  head selection), `stale-base-pr-silently-reverts-upstream-content` (why
  the early main merge matters), `gh-squash-merge-closes-only-one-issue`
  (issue-keyword hygiene in the superseding PR body).
