---
name: gh-pr-create-orchestration-cwd-wrong-head
description: |
  Diagnose and prevent `gh pr create` opening a PR against the WRONG head branch
  when invoked from a parallel-orchestration setup with multiple worktrees.
  Use when: (1) you've dispatched subagents to work in sub-worktrees but you're
  finalizing PRs from a separate orchestration worktree, (2) `gh pr create`
  succeeds but `gh pr view --json headRefName` shows your orchestration
  worktree's branch (e.g. `docs/sNNN-handoff`) instead of the feature branch
  the subagent committed to (e.g. `fix/issue-X`), (3) two PRs exist for the
  same logical change because a revived subagent opened a second one on the
  correct branch. Trigger: PR title is correct (heredoc body matches your
  intent) but the PR's `headRefName` doesn't match the feature worktree's
  branch — your CWD when invoking `gh` overrode the head selection.
author: Claude Code
version: 1.0.0
date: 2026-05-08
disable-model-invocation: true
---

# `gh pr create` from orchestration worktree picks wrong head branch

## Problem

In a parallel-execution setup, an orchestrator dispatches sub-agents to feature
worktrees (`<repo>/.claude/worktrees/feature-A/`, `feature-B/`, etc.) and waits
on their completion. When the orchestrator then runs `gh pr create` to open
the PR for one of those features, **it gets opened against whatever branch is
currently checked out in the orchestrator's CWD** — not the feature
branch the subagent committed to.

Result: a PR with the right title and body but the wrong head branch
(typically the orchestrator's `docs/sNNN-handoff` or `main`-tracking branch).
The PR's diff is unrelated to the change description, and the actual feature
work never gets a PR.

## Trigger conditions

You're hitting this skill if **all** of:

1. Your workflow has multiple worktrees: one orchestrator + N feature
   worktrees.
2. You ran `gh pr create` (with title + body via heredoc) from the
   orchestrator's working directory.
3. `gh pr view <N> --json headRefName` returns your orchestrator's branch
   (e.g. `docs/sNNN-handoff`), NOT the feature branch (e.g.
   `fix/issue-XXX`).
4. The PR's diff in `gh pr diff <N>` doesn't match the body text.

Optional secondary signal:

- A revived subagent later opens a SECOND PR on the correct branch (because
  it ran `gh pr create` from the feature worktree where its CWD was). Now you
  have two PRs.

## Root cause

`gh pr create` defaults `--head` to the **current branch in the CWD where you
invoked it**. The orchestrator's CWD is typically a worktree that's checked
out on a different branch than the feature branch — that branch is what gets
pushed/used as head. The subagent's git commits in `<repo>/.claude/worktrees/feature-X/`
have NO effect on the orchestrator's CWD branch.

This is an easy trap because:
- The heredoc-supplied body looks right.
- The branch name doesn't appear in the `gh pr create` invocation, so
  there's nothing to visually trip on.
- The PR opens successfully and reports a URL — looks like success.

## Fix

Two equally good options. Pick whichever fits your workflow.

### Option A — `cd` into the feature worktree before invoking `gh`

```sh
cd /path/to/repo/.claude/worktrees/feature-A
gh pr create --title "..." --body "$(cat <<EOF ... EOF
)"
```

This relies on `gh` reading the CWD's branch automatically.

### Option B — Pass `--head` explicitly (no `cd` needed)

```sh
gh pr create \
  --head fix/issue-XXX \
  --title "..." \
  --body "..."
```

`--head` overrides CWD branch detection entirely. Slightly more verbose but
foolproof in mixed-worktree contexts.

### Recovery if you've already opened the wrong-branch PR

```sh
# Verify which PR is wrong
gh pr view <wrong-N> --json headRefName,title

# Close the wrong one with a clear reason
gh pr close <wrong-N> --comment "Closing — opened against wrong head \
branch from orchestration worktree. PR <correct-N> is canonical."

# Open the correct one (if a sister subagent didn't already)
cd /path/to/feature-worktree
gh pr create --title "..." --body "..."
```

## Verification

After opening the PR:

```sh
# These two should match:
gh pr view <N> --json headRefName --jq .headRefName
git -C /path/to/feature/worktree branch --show-current
```

Then spot-check the diff:

```sh
gh pr diff <N> | head -20
```

The first 20 lines should match the kind of changes described in the PR
body (e.g. if the PR body says "rename X → Y", the diff should show that).

## Example

**S160 incident (2026-05-08):** orchestrator was on branch
`docs/s159-handoff` in worktree `.claude/worktrees/fix-issues/`. After the
pick #5 subagent finished work on branch
`fix/s160-issue490-rename-status-labels` in worktree
`.claude/worktrees/s160-pick-3/`, the orchestrator ran `gh pr create` from
its own CWD. The resulting PR #599 had:
- Correct title: "fix(library): rename two status labels (Closes #490)"
- Correct body: described the rename
- Wrong head: `docs/s159-handoff` (the orchestrator's branch — totally
  unrelated to the rename)

The orchestrator only noticed when checking
`gh pr view 599 --json headRefName`. By then, the revived pick #5 subagent
had opened PR #600 on the correct branch. PR #599 was closed with a "wrong
head branch" comment; PR #600 became canonical.

## Notes

- This pattern is endemic to setups where the orchestrator coordinates
  parallel work across sibling worktrees. It does NOT affect single-worktree
  flows (where the orchestrator's CWD IS the feature branch).
- The `gh` CLI doesn't warn if the CWD branch and the recently-pushed
  feature branch differ — both are valid heads from `gh`'s perspective.
- A defensive pre-check: before `gh pr create`, run
  `git rev-parse --abbrev-ref HEAD` and confirm it matches the branch you
  pushed for THIS feature.
- Sister patterns:
  - `subagent-bash-cd-wrong-worktree` (subagent's `cd` lands in the
    orchestrator's worktree)
  - `credit-stall-mid-orchestration-revive-collision` (revived subagent
    races the orchestrator's recovery actions)

## References

- `gh pr create` docs: https://cli.github.com/manual/gh_pr_create —
  `--head` flag documentation.
- Project incident: S160 (2026-05-08), the-project-repo
  PR #599 closed, PR #600 canonical.
