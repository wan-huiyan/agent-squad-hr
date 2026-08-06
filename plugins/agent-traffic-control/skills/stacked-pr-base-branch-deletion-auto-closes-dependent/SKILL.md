---
name: stacked-pr-base-branch-deletion-auto-closes-dependent
description: |
  Recover from the trap where deleting a base PR's branch auto-closes any open
  dependent stacked PR, and the closed PR cannot be reopened or retargeted. Use
  when: (1) you set up a stacked PR pair (PR2's `base` field = PR1's branch
  instead of `main`), (2) you merged PR1 via squash, (3) PR1's remote branch
  got deleted — via ANY route: `gh pr merge <N> --squash --delete-branch`,
  `gh api -X DELETE refs/heads/<branch>`, or `gh pr merge` followed by separate
  branch cleanup — (4) the dependent PR2 is now reported as `state: CLOSED`
  even though you never closed it, (5) `gh pr reopen N` fails with
  `Could not open the pull request`, (6) `gh pr edit N --base main` fails with
  `Cannot change the base branch of a closed pull request`. The only recovery
  for the stacked-PR case is to open a fresh PR from the same head branch with
  base=main. **v1.2.0 (2026-05-19) adds the recoverable single-PR variant**:
  if the deleted branch was the HEAD of a single, in-flight, NEVER-MERGED PR
  (e.g. user deleted the branch after a failed merge attempt that returned
  `GraphQL: Pull Request is not mergeable` because `mergeable: UNKNOWN`),
  the PR closes with `mergedAt: null, mergeCommit: null` and is RECOVERABLE
  via `git push origin <branch>` + `gh pr reopen <N>` — no fresh PR needed.
  Root-cause prevention: never `gh api -X DELETE` a branch until
  `gh pr view <N> --json state` reports exactly `MERGED`. Sister skill to
  `gh-pr-merge-worktree-checkout-trap` (one upstream cause).
author: Claude Code
version: 1.2.1
date: 2026-05-19
disable-model-invocation: true
---

# Stacked PR: Base-Branch Deletion Auto-Closes the Dependent PR

## Problem

You have a stacked PR pair:

- **PR1** — `base: main`, `head: feature-pr1`
- **PR2** — `base: feature-pr1`, `head: feature-pr2` (stacked on PR1)

You squash-merge PR1. The merge succeeds. You then run:

```bash
gh api -X DELETE repos/<owner>/<repo>/git/refs/heads/feature-pr1
```

…to clean up the orphaned remote branch (because `gh pr merge --delete-branch`
failed locally with the worktree-checkout-trap and you used the API as a
workaround). Within seconds, PR2 silently transitions to `state: CLOSED`:

```bash
$ gh pr view <PR2> --json state,closed,mergedAt,baseRefName
{"baseRefName":"feature-pr1","closed":true,"mergedAt":null,"state":"CLOSED"}
```

You never closed PR2. The PR's `head` branch still exists with all the work.
But:

```bash
$ gh pr reopen <PR2>
API call failed: GraphQL: Could not open the pull request. (reopenPullRequest)

$ gh pr edit <PR2> --base main
GraphQL: Cannot change the base branch of a closed pull request. (updatePullRequest)
```

GitHub refuses to reopen the PR (its base branch no longer exists), and
refuses to retarget a closed PR. The PR is effectively a dead reference —
all comments, reviews, and history land on a record that nothing can resurrect.

## Why this happens

When a PR's base branch is deleted, GitHub's behavior is asymmetric:

- **If the base branch is deleted via the GitHub UI's "delete branch" button
  on a merged PR**, GitHub usually auto-retargets dependent open PRs to the
  default branch (typically `main`).
- **If the base branch is deleted via the Git Refs API directly**
  (`DELETE /repos/.../git/refs/heads/<branch>`), GitHub does NOT auto-retarget.
  Instead, it auto-closes any open PR whose `base` field referenced the now-
  missing branch.

The closed PR cannot be reopened because GitHub validates that the base ref
exists at reopen time. It cannot be retargeted because the reopen happens
before the retarget — both are blocked by the missing-base validation.

## Context / Trigger Conditions

You are in this trap if **all** of these are true:

1. You used a stacked PR setup (PR2 explicitly opened with `--base <PR1-branch>`,
   not `main`).
2. PR1 squash-merged (PR1 is in `state: MERGED`).
3. PR1's remote branch got deleted via **any programmatic route**:
   - `gh pr merge <N> --squash --delete-branch` (the normal merge-and-cleanup)
   - `gh api -X DELETE repos/<owner>/<repo>/git/refs/heads/<branch>` (the
     workaround when `gh pr merge --delete-branch` failed locally with the
     worktree-checkout-trap)
   - Any other CLI/API-driven branch deletion
   Only the GitHub web UI's "Delete branch" button on the merged PR page
   triggers stacked-PR auto-retarget. Every other route auto-closes the
   dependent.
4. PR2 is now `state: CLOSED` with `mergedAt: null` and `closed: true`.
5. `gh pr reopen <PR2>` fails with `Could not open the pull request`.

## Solution

The dead PR cannot be recovered. Open a fresh PR from the same head branch
against `main`:

```bash
# 1. Verify the head branch still exists with your work
git fetch origin
git ls-remote origin refs/heads/feature-pr2
# should print a SHA — your work survives on the remote branch

# 2. (Optional) Verify HEAD diff against main is what you expect
git log origin/main..origin/feature-pr2 --oneline | head

# 3. Open a fresh PR with base=main; reuse the original PR's body
#    (you can copy-paste from the closed PR; comments don't migrate).
gh pr create \
  --base main \
  --head feature-pr2 \
  --title "feat(...): same title as the dead PR" \
  --body "$(cat <<'EOF'
Replaces #<DEAD_PR_NUMBER> (auto-closed when PR1's base branch was deleted
post-merge — GitHub couldn't auto-retarget). Same diff, now based on main
directly.

[... rest of original body ...]

Code-review findings preserved as comments on the closed PR:
https://github.com/<owner>/<repo>/pull/<DEAD_PR_NUMBER>#issuecomment-<ID>
EOF
)"

# 4. Squash-merge the new PR as usual
gh pr merge <NEW_PR> --squash
```

Reviews and comments on the dead PR are NOT auto-migrated. Leave a comment
on the new PR that links to the dead PR's review thread so the audit trail
stays connected.

## Variant: single, non-stacked PR — head-branch deleted mid-merge (RECOVERABLE)

Same mechanism, different scenario, different recovery:

You have a SINGLE PR (not stacked). You try to merge it. GitHub returns
`GraphQL: Pull Request is not mergeable (mergePullRequest)` because the
PR's `mergeable: UNKNOWN, mergeStateStatus: UNKNOWN` — GitHub hadn't
finished computing mergeability for a recent push. You assume the merge
succeeded silently anyway and proactively run `gh api -X DELETE
repos/<owner>/<repo>/git/refs/heads/<branch>` to "clean up". The PR
state flips to `CLOSED` with `mergedAt: null, mergeCommit: null` — the
branch deletion auto-closed the PR before any merge happened.

Unlike the stacked case above, **this is recoverable** because:
- The PR was never merged (so no irreversible "merged with wrong base" record exists)
- The PR has no dependents (so no closed-PR-with-dependent-PR2 chain)
- GitHub allows `gh pr reopen <N>` on a PR closed by branch deletion
  (it doesn't apply the "cannot reopen merged PRs" rule here because
  the PR isn't merged — just closed)

Recipe:

```bash
# Verify: PR is CLOSED but never merged
gh pr view <N> --json state,mergedAt,mergeCommit
# {"state": "CLOSED", "mergedAt": null, "mergeCommit": null}

# 1. Re-push the local branch (it's still in your worktree)
git push origin <branch>
# remote: ... * [new branch] <branch> -> <branch>

# 2. Reopen the PR — this works because PR was closed-not-merged
gh pr reopen <N>
# ✓ Reopened pull request ...#<N>

# 3. Wait for mergeability to compute
sleep 5
gh pr view <N> --json mergeable,mergeStateStatus
# {"mergeStateStatus": "CLEAN", "mergeable": "MERGEABLE"}

# 4. Now merge normally
gh pr merge <N> --squash --subject "..." --body "..."
```

The PR's full history (commits, comments, reviews, labels) survives the
close-and-reopen cycle intact. No need to create a fresh PR.

**Root-cause prevention for this variant: never call `gh api -X DELETE`
on a branch until `gh pr view <N> --json state` reports `MERGED` (not
`OPEN`, not `CLOSED`, not `UNKNOWN`).** A failed merge attempt that
returns `mergeable: UNKNOWN` is GitHub still computing — wait, retry the
merge, don't take recovery actions yet. Quick check:

```bash
gh pr view <N> --json state --jq .state   # must be exactly "MERGED"
```

Then and only then is the branch safe to delete.

## Prevention (recommended workflow)

Pick ONE of these patterns when working with stacked PRs + worktrees:

### Pattern A — Merge both PRs before any branch cleanup

Don't delete PR1's branch until PR2 is also merged. After PR1 squash-merges,
GitHub automatically marks PR1's branch as "ready to delete" but doesn't
delete it. Leave it alone. Merge PR2 (which still has `base: PR1-branch`).
Once both are merged, clean up:

```bash
gh api -X DELETE repos/<owner>/<repo>/git/refs/heads/feature-pr1
gh api -X DELETE repos/<owner>/<repo>/git/refs/heads/feature-pr2
```

This is the cheapest and safest pattern. PR2 doesn't need to be retargeted —
it merges with `base: feature-pr1`, and GitHub computes the diff correctly
(PR2's head minus PR1's head, which is just PR2's specific commits).

### Pattern B — Retarget PR2 to main BEFORE deleting PR1's branch

If you need to delete PR1's branch immediately after merge (e.g., automation
constraints):

```bash
# 1. Squash-merge PR1
gh pr merge <PR1> --squash

# 2. Retarget PR2 to main (works because PR2 is still OPEN at this point)
gh pr edit <PR2> --base main

# 3. NOW it's safe to delete PR1's branch
gh api -X DELETE repos/<owner>/<repo>/git/refs/heads/feature-pr1
```

The retarget rebases PR2's diff against `main` (which now contains PR1's
squash). PR2 may then need a manual rebase or merge of `main` to resolve
conflicts, but the PR stays open and reviewable throughout.

## Verification

After recovery, verify:

```bash
# Old PR is closed-unmerged (intentional dead state)
gh pr view <DEAD_PR> --json state,mergedAt
# {"state":"CLOSED","mergedAt":null}

# New PR is open against main with the expected diff
gh pr view <NEW_PR> --json state,baseRefName,headRefName
# {"state":"OPEN","baseRefName":"main","headRefName":"feature-pr2"}

# New PR's diff matches what you intended (no PR1 commits leaked back in)
gh pr diff <NEW_PR> | head -50
```

## Notes

- **The harness/CLI does not warn before this happens.** `gh api -X DELETE`
  on a refs/heads/X executes immediately and the auto-close cascade is a
  GitHub-server-side reaction that lands within ~1 second. There is no
  "this will close N dependent PRs, continue?" prompt.
- **The auto-close on dependent PRs is asymmetric with the UI delete-branch
  button.** If you use the GitHub UI's "Delete branch" button on a merged
  PR's page, GitHub generally auto-retargets dependent open PRs to the
  default branch instead of closing them. **Every other deletion route
  triggers the close cascade**, including `gh pr merge <N> --delete-branch`
  (the normal CLI merge-and-cleanup flow) and `gh api -X DELETE refs/heads/<branch>`.
  Earlier versions of this skill suggested `gh pr merge --delete-branch`
  was safe — that's wrong; it routes through the same Git Refs API
  deletion and triggers the cascade. The UI button is the sole exception
  because it goes through a different code path that does the retarget
  before the delete.
- **GitHub does NOT silently reopen** dependent PRs even if you re-create
  the deleted ref afterwards (`gh api -X PUT refs/heads/feature-pr1`). The
  closed state is sticky.
- **Sister skill — upstream cause:** `gh-pr-merge-worktree-checkout-trap`
  documents why operators reach for `gh api -X DELETE` in the first place
  (because `gh pr merge --delete-branch` fails locally when another worktree
  has `main` checked out). That skill says "the merge succeeded; verify
  state=MERGED and move on" — this skill extends that advice with: if you
  also need to clean up the branch AND a stacked PR depends on it, follow
  Pattern A or B above instead of using the API delete directly.
- **Sister skill — different problem:** `pr-followup-commit-stranded-after-squash`
  covers commits pushed after PR squash-merge — different failure mode
  (stranded commits vs auto-closed PR).

## Example — 2026-05-08 chatbox session

Two-PR stack:
- PR #456 (chatbox hardening), `base: main`, `head: worktree-chatbox-with-data`
- PR #461 (chatbox knowledge gap), `base: worktree-chatbox-with-data`,
  `head: worktree-chatbox-with-data-pr2`

Sequence that hit the trap:

1. PR #456 squash-merged (commit `36111e42` on main). ✓
2. `gh pr merge 456 --squash --delete-branch` — local-side failed with
   "fatal: 'main' is already used by worktree at '...wow-action'"
   (the worktree-checkout-trap; merge succeeded on GitHub, only local
   cleanup failed).
3. To clean up the orphaned remote PR1 branch, ran:
   `gh api -X DELETE repos/wan-huiyan/.../git/refs/heads/worktree-chatbox-with-data`
4. **Within seconds, PR #461 transitioned to `state: CLOSED`.** No notification.
5. `gh pr reopen 461` → `Could not open the pull request`.
6. `gh pr edit 461 --base main` → `Cannot change the base branch of a closed PR`.
7. **Recovery:** opened PR #465 with `--base main --head worktree-chatbox-with-data-pr2`,
   reused the body, linked the review-comment thread on the dead #461.
   PR #465 squash-merged successfully.

Total recovery time: ~5 minutes. Could have been zero with Pattern A
(don't delete PR1's branch until PR2 is also merged).

## Example — 2026-05-18 iql-sync session (the `gh pr merge --delete-branch` variant)

Two-PR stack:
- PR #8 (121 IQLs crawled), `base: main`, `head: iql-sync/2026-05-18`
- PR #10 (streaming writes + folder split), `base: iql-sync/2026-05-18`,
  `head: iql-sync/streaming-and-folders`

Sequence that hit the trap:

1. PR #8 squash-merged via `gh pr merge 8 --squash --delete-branch`. ✓
   No worktree conflict; the merge AND the branch deletion both succeeded
   cleanly through gh — no API workaround used.
2. **Within seconds, PR #10 transitioned to `state: CLOSED`** with
   `mergeStateStatus: DIRTY`, `mergeable: CONFLICTING`.
3. `gh pr edit 10 --base main` → `Cannot change the base branch of a closed PR`.
4. `gh pr reopen 10` → `Could not open the pull request`.
5. **Recovery:** `git rebase origin/main` on `iql-sync/streaming-and-folders`
   (git auto-skipped the duplicate squashed commit, leaving just the new
   code on top of main), force-push, `gh pr create --base main --head
   iql-sync/streaming-and-folders` → PR #11. Merged successfully.

**Why this case matters:** the earlier `2026-05-08 chatbox` example
established the trap for the `gh api -X DELETE` route only. This case
proves the trap fires for `gh pr merge --delete-branch` too — the
"normal" CLI flow. The skill's trigger conditions were updated in v1.1.0
to reflect this.

Total recovery time: ~3 minutes (no worktree-checkout-trap to untangle
first; just rebase + new PR).

## References

- GitHub Git Refs API delete behavior:
  https://docs.github.com/en/rest/git/refs#delete-a-reference
- GitHub stacked-PR documentation (auto-retarget on UI delete):
  https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/proposing-changes-to-your-work-with-pull-requests/changing-the-base-branch-of-a-pull-request
- Sister skill: `gh-pr-merge-worktree-checkout-trap` — in this same plugin
  ([source](https://github.com/wan-huiyan/agent-traffic-control/blob/main/plugins/agent-traffic-control/skills/gh-pr-merge-worktree-checkout-trap/SKILL.md))
