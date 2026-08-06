---
name: gh-pr-merge-unstable-state-needs-auto-and-watch-branch-deletes
description: |
  Diagnose and recover from two adjacent `gh pr merge` failure modes that masquerade as merge
  conflicts. Use when: (1) `gh pr merge --squash` (or `--merge`) errors with "To have the pull request
  merged after all the requirements have been met, add the `--auto` flag" AND "Run the following to
  resolve the merge conflicts locally" even though you just pushed a clean resolution; (2)
  `gh pr view <N> --json mergeable,mergeStateStatus` returns `MERGEABLE` + `UNSTABLE` rather than
  `MERGEABLE` + `CLEAN`; (3) you delete the remote branch (`git push origin --delete <branch>`)
  immediately after `gh pr merge` returns a conflict warning thinking the merge succeeded — and
  discover the PR has flipped to `CLOSED` rather than `MERGED`. The actual root cause for (1)/(2) is
  almost always pending CI / branch-protection checks, NOT real merge conflicts; the fix is `--auto`
  flag so `gh` queues the merge for when checks pass. For (3) — recovery requires restoring the remote
  branch (`git push -u origin <branch>` from your local copy, OR — if you have NO local copy —
  from `refs/pull/<N>/head`) and `gh pr reopen <N>` before retrying. (4) `gh pr merge` errors
  `Pull Request is still a draft (mergePullRequest)` — the PR is a draft; run `gh pr ready <N>`
  first. A cleanup step that deletes the head branch keyed on branch-EXISTENCE (not merge-success)
  will delete a draft/unmerged PR's branch and close it — always gate deletes on `mergedAt != null`.
  Sibling to `gh-pr-merge-worktree-checkout-trap` (different failure mode — worktree holding main).
author: Claude Code
version: 1.1.1
date: 2026-06-08
disable-model-invocation: true
---

# `gh pr merge` UNSTABLE state + branch-delete recovery

## Problem

Two adjacent failure modes that read as "merge conflicts" but aren't:

### Failure A: `gh pr merge` rejects with "conflicts" when there are none

You push a clean resolution of merge conflicts, GitHub shows the PR as MERGEABLE, and yet:

```
$ gh pr merge 915 --squash
To have the pull request merged after all the requirements have been met,
add the `--auto` flag.
Run the following to resolve the merge conflicts locally:
  gh pr checkout 915 && git fetch origin main && git merge origin/main
```

The first line is the actual hint; the second is misleading boilerplate. The real cause is
`mergeStateStatus: UNSTABLE` — branch protection or CI checks are pending. `gh` can't merge yet
because the repo's rules aren't satisfied, not because of file-level conflicts.

### Failure B: PR auto-closes if you delete the remote branch right after Failure A

Common pattern: previous PR on the same branch merged cleanly with `gh pr merge <N> --squash`. You
then do `git push origin --delete <branch>` to clean up. Habit kicks in for the next PR — you run
`gh pr merge` (gets Failure A above), notice the "conflicts" warning, run
`git push origin --delete <branch>` anyway thinking the merge already landed remotely...

```
$ gh pr view 915 --json state
{"state":"CLOSED"}   # ← not MERGED — the PR closed because the branch was deleted with the merge un-queued
```

GitHub treats a deleted-branch PR with no merge in progress as abandoned and closes it.

## Context / Trigger conditions

- `gh pr merge --squash` (or `--merge`) returns with the "add the `--auto` flag" / "resolve
  conflicts" stderr
- `gh pr view <N> --json state,mergeable,mergeStateStatus` shows `{state: OPEN, mergeable: MERGEABLE,
  mergeStateStatus: UNSTABLE}` — the `UNSTABLE` is diagnostic; it means "no real conflicts, but checks
  aren't passing yet"
- Or: a PR you just tried to merge is now `state: CLOSED` rather than `state: MERGED`, AND the remote
  branch is missing
- Repo has branch protection rules (required status checks, required reviews) OR CI workflows that
  haven't completed yet
- You're in a multi-PR session where the previous PR merged cleanly, conditioning you to expect the
  same flow

## Root cause

**For Failure A:** `gh pr merge` (without `--auto`) requires the PR to be fully ready to merge RIGHT
NOW. If branch-protection rules or CI checks are pending, `gh` reports it as a generic merge problem
with misleading conflict-resolution advice. The actual diagnostic is the
`mergeStateStatus` field — `UNSTABLE` means "pending checks", `BLOCKED` means "failed checks or
missing reviews", `CLEAN` means "ready to merge", `DIRTY` means "real file conflicts".

**For Failure B:** GitHub's UI treats "branch deleted + no merge in progress" as PR abandonment. The
PR closes; the merge never happens; recovery requires restoring the branch AND reopening the PR.

## Solution

### Diagnose first — three-line state check

Before retrying or panicking:

```bash
gh pr view <N> --json state,mergeable,mergeStateStatus,statusCheckRollup
```

Interpretation:

| `state` | `mergeable` | `mergeStateStatus` | Meaning | Action |
|---|---|---|---|---|
| OPEN | MERGEABLE | CLEAN | Ready to merge | `gh pr merge <N> --squash` |
| OPEN | MERGEABLE | UNSTABLE | Pending CI / checks | `gh pr merge <N> --squash --auto` |
| OPEN | MERGEABLE | BLOCKED | Failed checks or missing required reviews | Fix the failed check or request review |
| OPEN | CONFLICTING | DIRTY | Real file conflicts | Resolve locally, push, retry |
| CLOSED | (any) | (any) | PR closed (often: branch deleted) | Restore branch + reopen (see recovery below) |
| MERGED | (any) | (any) | Already done | Nothing to do |

### Fix Failure A — use `--auto`

```bash
gh pr merge <N> --squash --auto
# Returns silently; merge queues for when checks pass; GitHub auto-deletes remote branch on merge
```

`--auto` tells GitHub to wait for branch-protection requirements and then merge automatically. No
polling required — GitHub handles it. The remote branch is deleted by GitHub at merge time (no need
to do it yourself).

### Fix Failure B — restore branch + reopen PR + retry

```bash
# Your local branch still has the commits — push it back up
git push -u origin <branch-name>

# Reopen the PR (gh closed it when the branch went away)
gh pr reopen <N>

# Verify it's back
gh pr view <N> --json state,mergeable,mergeStateStatus

# Then merge with --auto
gh pr merge <N> --squash --auto
```

**No local copy of the branch?** (Common when the PR was authored in another session/worktree, or
you discarded the local branch.) The commits are still reachable via the PR's pull ref — restore the
branch from there; no `git reflog` or colleague clone needed:

```bash
SHA=$(gh pr view <N> --json headRefOid -q .headRefOid)   # PR keeps the head SHA even after delete
git fetch origin refs/pull/<N>/head                      # the commits live here regardless of the branch
git push origin "$SHA:refs/heads/<branch-name>"          # recreate the branch at the EXACT SHA → PR re-links
gh pr reopen <N>                                         # delete had flipped it to CLOSED
gh pr ready <N>                                          # also un-draft if it was a draft (Failure C)
gh pr merge <N> --squash                                 # the re-push may re-trigger CI → wait for it
```

### Fix Failure C — PR is a draft

`gh pr merge <N> --squash` errors `GraphQL: Pull Request is still a draft (mergePullRequest)`. The PR
is a draft; mark it ready, then merge:

```bash
gh pr ready <N>            # un-draft
gh pr merge <N> --squash
```

The real danger is the *combination*: a "merge then clean up the branch" routine where the cleanup
deletes the remote head ref whenever the branch still exists. On a draft PR the merge is refused but
the branch still exists → the cleanup deletes it → the PR closes. **Gate every branch delete on
merge-success, never on branch-existence:**

```bash
gh pr merge <N> --squash
if [ "$(gh pr view <N> --json mergedAt -q .mergedAt)" != "null" ]; then
  # delete remote ref only now
fi
```

## Verification

After applying `--auto`:

1. `gh pr view <N> --json state` should still show `OPEN` immediately after the command
2. Within minutes (or however long your CI takes), GitHub will merge automatically
3. Final state: `gh pr view <N> --json state,mergedAt` shows `{state: MERGED, mergedAt: <timestamp>}`
4. Remote branch is auto-deleted by GitHub
5. You receive no email failure notification (a clean signal)

## Example

Session ending PR #915 (a docs handoff), 2026-05-19:

```
$ gh pr merge 915 --squash
To have the pull request merged after all the requirements have been met, add the `--auto` flag.
Run the following to resolve the merge conflicts locally:
  gh pr checkout 915 && git fetch origin main && git merge origin/main

$ gh pr view 915 --json state,mergeable,mergeStateStatus
{"mergeable":"MERGEABLE","mergeStateStatus":"UNSTABLE","state":"OPEN"}
                                  ^^^^^^^^
                                  not DIRTY → no real conflicts; pending checks

$ gh pr merge 915 --squash --auto
# (silent success — queues for CI)
```

(Earlier in the same session, the same orchestrator hit Failure B on the same PR by running
`git push origin --delete docs/s207-handoff` immediately after `gh pr merge` returned the conflict
warning — the PR flipped to CLOSED. Recovered with `git push -u origin docs/s207-handoff` +
`gh pr reopen 915` + `gh pr merge 915 --squash --auto`.)

PR #398 (a docs deliverable), 2026-06-08 — the Failure-C-plus-delete combo: `gh pr merge 398 --squash`
errored `Pull Request is still a draft (mergePullRequest)`, but the same script's cleanup step
(`if branch exists → gh api -X DELETE …`) ran anyway and deleted the head branch, closing the PR.
The branch was authored in another session (no local copy). Recovered via the pull ref:
`SHA=$(gh pr view 398 --json headRefOid -q .headRefOid)` → `git push origin "$SHA:refs/heads/<branch>"`
→ `gh pr reopen 398` → `gh pr ready 398` → `gh pr merge 398 --squash` (waited for the re-triggered CI).
Fix that prevented a repeat: gate the delete on `mergedAt != null`, not on branch existence.

## Notes

- **Don't reflexively delete the remote branch after `gh pr merge` errors.** The merge may not have
  landed. Check `gh pr view <N> --json state,mergedAt` first; only delete if `mergedAt` is non-null.
- **`--auto` is safe to use even when checks pass immediately.** If the PR is already CLEAN, `--auto`
  merges instantly. No downside to using it as the default.
- **Branch-protection diagnostics:** if `mergeStateStatus` stays `UNSTABLE` for >5min after a push,
  check `gh pr checks <N>` to see which check is hanging. A common cause is a `paths`-filter workflow
  that didn't trigger because the PR touched no matching paths — that check stays "pending" forever
  and blocks merge until the rule is updated.
- **Sibling failure mode:** `gh-pr-merge-worktree-checkout-trap` — when `gh pr merge --delete-branch`
  fails with `fatal: 'main' is already used by worktree at ...`. That's a LOCAL-side failure of the
  post-merge branch checkout; the GitHub merge itself succeeds. Different beast from the failures
  documented here — verify by checking `gh pr view <N> --json mergedAt`.
- **Required-status-check repos:** in repos with branch protection requiring specific status checks,
  `--auto` is essentially mandatory — no human can merge instantly if checks aren't done. Build the
  habit project-wide.

## References

- [gh pr merge — official docs](https://cli.github.com/manual/gh_pr_merge)
- [GitHub mergeStateStatus enum reference](https://docs.github.com/en/graphql/reference/enums#mergestatestatus)
- Sibling skill: `gh-pr-merge-worktree-checkout-trap` — in this same plugin
  ([source](https://github.com/wan-huiyan/agent-traffic-control/blob/main/plugins/agent-traffic-control/skills/gh-pr-merge-worktree-checkout-trap/SKILL.md))
