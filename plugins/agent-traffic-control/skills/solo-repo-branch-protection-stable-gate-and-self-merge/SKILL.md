---
name: solo-repo-branch-protection-stable-gate-and-self-merge
description: |
  Lock main on a repo you maintain alone so nothing red lands and you are not deadlocked — no
  second reviewer needed. Use when something broken reached main by direct push — CI runs after
  the push, too late to block it — or status checks are required and direct pushes still land.
  Three traps: a matrix names check runs `test (20)` and `test (22)`, never the workflow name, so
  require a stable aggregation gate that fails, not skips; `required_status_checks` alone only
  gates merges; and `required_approving_review_count: 0` with `enforce_admins` lets you self
  merge. Not for an undeployed merge.
author: wan-huiyan
version: 1.0.0
date: 2026-06-01
---
# Solo-Repo Branch Protection: Stable Gate + Self-Merge

## Problem

You want main to be unbreakable — no direct pushes, the test check must be green before
anything lands — but you're the only maintainer, so you can't require a second reviewer,
and you don't want a config that deadlocks all merges later. Three traps make the naive
approach wrong.

## Context / Trigger Conditions

- A broken/malformed commit reached `main` because it was pushed directly (CI runs
  *after* the push lands, so a post-push workflow can't block it).
- You set "require status checks to pass" but direct pushes still go through.
- You're a solo owner and worry branch protection means you can never merge your own PRs.

## Solution

### Trap 1 — Matrix check-runs aren't named after the workflow

A workflow `name: Tests` with a job `test` and `strategy.matrix.node-version: [20, 22]`
produces check-runs named **`test (20)`** and **`test (22)`** — not `Tests`. If you
require `Tests` (the workflow name) as a status check, it never exists → no merge ever
satisfies it. If you require `test (20)`/`test (22)` directly, then changing the matrix
(drop 20, add 24) silently orphans the required context and **deadlocks all merges**.

Fix: add a stable **aggregation gate job** and require only it. `if: always()` +
checking `needs.test.result` makes it FAIL (not skip) when any matrix leg fails — a
*skipped* required check would itself deadlock merges.

```yaml
  test-gate:
    if: always()
    needs: test
    runs-on: ubuntu-latest
    steps:
      - name: Verify the test matrix succeeded
        run: |
          if [ "${{ needs.test.result }}" != "success" ]; then
            echo "test matrix did not succeed: ${{ needs.test.result }}"; exit 1
          fi
```
Push this and let it run once, then confirm the check-run name exists:
`gh api repos/<owner>/<repo>/commits/main/check-runs --jq '.check_runs[].name'`.

### Trap 2 — required_status_checks alone does NOT block direct pushes

Required status checks only gate PR *merges*. To block direct pushes to main you must
also require a pull request (`required_pull_request_reviews` must be present/non-null).

### Trap 3 — Solo self-merge

Set `required_approving_review_count: 0` — a PR is required, but zero approvals, so you
can merge your own PR once the check is green. `enforce_admins: true` makes it a real
guarantee (even the owner can't bypass).

### Apply it

```bash
cat > /tmp/protection.json <<'EOF'
{
  "required_status_checks": { "strict": true, "contexts": ["test-gate"] },
  "enforce_admins": true,
  "required_pull_request_reviews": { "required_approving_review_count": 0 },
  "restrictions": null
}
EOF
gh api -X PUT repos/<owner>/<repo>/branches/main/protection --input /tmp/protection.json
```
Needs `repo` scope (`gh auth status`). Pair with a local `.githooks/pre-push` that runs
the suite for fast local failure — protection is the authoritative gate, the hook is the
fast layer.

## Verification

```bash
# config active
gh api repos/<owner>/<repo>/branches/main/protection \
  --jq '{checks:.required_status_checks.contexts, admins:.enforce_admins.enabled, pr:.required_pull_request_reviews.required_approving_review_count}'
# direct push REJECTED (use --no-verify to bypass local hook and test the SERVER)
git commit --allow-empty -m probe && git push --no-verify origin main   # → GH006, "must be made through a pull request"
git reset --hard HEAD~1
# happy path still works: branch → gh pr create → wait test-gate → gh pr merge --squash --delete-branch
```
Expected rejection: `remote: error: GH006: Protected branch update failed ... Changes
must be made through a pull request. ... Required status check "test-gate" is expected.`

## Notes

- **Emergency lift** (don't get locked out if CI itself breaks): `gh api -X DELETE
  repos/<owner>/<repo>/branches/main/protection`, or PUT with `enforce_admins:false` to
  keep an admin bypass. You own the repo, so this state is always recoverable.
- `strict: true` means a branch must be up to date with main before merge (rebase if stale).
- `gh pr create --fill` aborts if run from the wrong cwd / before the branch is detected;
  pass `--repo`/`--base`/`--head` explicitly (see `gh-pr-create-orchestration-cwd-wrong-head`).
- To fan out across many solo repos, script the PUT per repo after confirming each has a
  `test-gate`-style stable check. See also `claude-plugin-repo-ci-release`.

## Reference-only siblings in this toolkit

These carry `disable-model-invocation: true`. They never appear in the skill
listing and the Skill tool refuses them, so the only way in is to open the file
with Read when one of these matches what you are looking at.

- [`workflow-run-deploy-gate-fork-pr-ref-name-escalation`](../workflow-run-deploy-gate-fork-pr-ref-name-escalation/SKILL.md) — a deploy gated on `on: workflow_run` and a branch name can be escalated from a fork PR
- [`merged-pr-not-deployed-gate-label-missing`](../merged-pr-not-deployed-gate-label-missing/SKILL.md) — the PR merged and CI is green but production never got it — a deploy gate label was missing

## Neighbouring skills

These were named in this skill's description until v1.18.0. The description is
resident in context on every turn, so a cross-link there costs budget on every
turn and buys nothing -- a user never types another skill's name. They belong
here, where the model reads them once retrieval has already succeeded.

- [`gh-pr-merge-unstable-state-needs-auto-and-watch-branch-deletes`](../gh-pr-merge-unstable-state-needs-auto-and-watch-branch-deletes/SKILL.md)
