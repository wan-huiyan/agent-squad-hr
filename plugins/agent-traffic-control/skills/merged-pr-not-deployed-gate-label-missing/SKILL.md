---
name: merged-pr-not-deployed-gate-label-missing
description: |
  Diagnose "I merged my PR + CI is green but the live service still doesn't show
  my changes." Use when: (1) a code-bearing PR has been squash-merged into main
  with all required status checks passing, (2) the user reports the change is
  still missing from the deployed environment minutes-to-hours later, (3) the
  repo has a `pull_request: types: [closed]` workflow gated on a label
  (typically `auto-deploy`, `deploy`, `ship-it`) and/or a path filter, (4) the
  deploy workflow's run row in `gh run list` shows `conclusion=skipped` for
  your PR's branch — visually identical to `success` in the run summary.
  Distinct from `gha-auto-deploy-never-ran-skipped-mask` (sister skill: same
  "skipped masks failure" symptom class but different cause — that skill is
  about the FIRST time the gate fires and the deploy step then hits a
  permission gap; THIS skill is about the routine case where the gate
  correctly works and the PR simply didn't satisfy it). Trigger phrases:
  "I can't see the changes live", "merged but not deployed", "PR shipped
  but prod didn't update", "the auto-deploy workflow shows skipped", "do I
  need to deploy manually after merge?". ALSO covers the INVERSE trap (v1.2.0):
  an `actions/labeler` auto-applied `auto-deploy` to a config/docs-only PR (e.g.
  `<dashboard_app>/monitoring/*.yaml`, README, ADR) that lives under the
  deployable path glob but never affects the built image — so merging fires an
  UNWANTED redeploy. Trigger: "why does my monitoring/docs PR have the auto-deploy
  label", "remove auto-deploy before merge", "config PR triggered a redeploy".
author: Claude Code
version: 1.2.1
date: 2026-07-01
disable-model-invocation: true
---

# Merged PR Not Deployed — Gate Label / Path Filter Quietly Skipped the Workflow

## Problem

A code change is merged into main and CI is green. The user opens the live service expecting to see the change and it's not there. The natural first instinct is "Cloud Run is caching" or "the bake hasn't re-run yet" or "I'm looking at the wrong revision". The actual cause is much simpler and quieter: **the deploy workflow never ran**, because the PR didn't satisfy the workflow's `if:` gate (typically a required label like `auto-deploy`, or a path filter that excludes the changed files).

The trap is that GHA's `conclusion=skipped` looks visually identical to `conclusion=success` in the workflow run summary on the PR page and in `gh run list` — same green checkmark icon, same "completed" status. Nothing on the PR's "all checks passed" surface tells you the deploy didn't happen.

This is a sister symptom to `gha-auto-deploy-never-ran-skipped-mask` (the FIRST-time-the-gate-fires-and-finds-an-infra-gap pattern), but a distinct cause: here the gate works as designed, the PR simply didn't carry the label.

## Context / Trigger Conditions

All of these are typically true:

- The PR has been merged (`gh pr view <N> --json state` returns `MERGED`).
- All required status checks were green at merge time.
- The repo has a deploy workflow with a top-level conditional gate. Common patterns:

  ```yaml
  on:
    pull_request:
      types: [closed]
      branches: [main]

  jobs:
    gate:
      if: >
        github.event.pull_request.merged == true &&
        contains(github.event.pull_request.labels.*.name, 'auto-deploy')
  ```

  Or path-filter style:

  ```yaml
  on:
    pull_request:
      types: [closed]
      paths:
        - '<analytics_pkg>/cloudrun/<dashboard_app>/**'
  ```

- The user reports "I merged + CI green but I can't see the changes live" minutes-to-hours after merge (long enough that they've already eliminated obvious caching).
- Sibling PRs from the same hour DID auto-deploy successfully — i.e. the workflow itself is healthy.

## Diagnostic

Three commands, in order:

### Step 1 — Was the deploy workflow's run for your PR `skipped`?

```sh
gh run list \
  --workflow=<deploy-workflow-name>.yml \
  --branch <your-merged-branch> \
  --limit 5 \
  --json status,conclusion,createdAt,headSha,event
```

If the row for your branch's merge shows `"conclusion":"skipped"` — confirmed. The workflow was registered for the event but the gate excluded it. Move to Step 2.

If there's no row at all — the workflow's `on:` filter didn't match (e.g. wrong event type, wrong base branch). Inspect the workflow YAML.

If the row shows `failure` — that's a different problem; check `gh-auto-deploy-never-ran-skipped-mask` if this was the first time the gate fired, otherwise treat as a normal CI failure.

### Step 2 — What is the gate?

```sh
# Find the deploy workflow file
ls .github/workflows/ | grep -iE 'deploy|ship|publish'

# Read its top-of-file `on:` and first job's `if:` condition
head -60 .github/workflows/<deploy-workflow-name>.yml
```

Look for one of these patterns:

| Gate type | YAML signature | What "skipped" means |
|---|---|---|
| Label gate | `if: contains(github.event.pull_request.labels.*.name, 'X')` | Your PR didn't carry label `X` at merge time |
| Path filter | `paths: ['some/dir/**']` under `on: pull_request` | Your PR's diff didn't touch any file under that path |
| Branch filter | `branches: [main]` (less likely to skip if you merged into main) | Your PR's base wasn't `main` |
| Combined | Both label and path gates in series | Either gate alone can cause skip |

### Step 3 — Compare against a known-deployed sibling PR

```sh
gh run list \
  --workflow=<deploy-workflow-name>.yml \
  --status success \
  --limit 3 \
  --json createdAt,headBranch,headSha
```

Pick the most recent success. Look at that PR — does it carry the label your PR is missing? Does it touch the path you didn't? Confirms the gate semantics.

## Solution

### A — Manual deploy now (ship today's changes)

Find the project's manual deploy script. In Cloud Run / GCP repos this is typically:

```sh
find . -name 'deploy*.sh' -not -path './node_modules/*' -not -path '*/worktrees/*' \
  | grep -i $(basename $(pwd))
# or
ls **/cloudrun/**/deploy*.sh 2>/dev/null
```

Before running the script, run the **5-line preflight from `deploy-from-stale-worktree-silent-rollback`**:

```sh
git fetch origin --quiet
git status -sb              # MUST show 'main...origin/main' (no ahead/behind, no leading branch name)
git diff --quiet            # MUST exit 0 (no uncommitted changes)
git log -1 --oneline        # CONFIRM you're at the post-merge HEAD (the one with your closes-#N commit)
ls .git/MERGE_HEAD .git/CHERRY_PICK_HEAD 2>/dev/null  # MUST be empty
```

If preflight passes, run the deploy script from the right directory. The script likely does `gcloud builds submit ... <DIR>` which packages local files; running from a stale worktree silently rolls back recent commits (per the sister skill).

### A2 — Variant: deploying from a worktree + Cloud Run **Job** baker (verified 2026-06-28)

Option A's preflight assumes you can stand on the `main` branch. **In a git worktree you usually can't** (`main` is checked out elsewhere → `git checkout main` errors), and the deploy script's own git-state guard *also* refuses to run off-`main`. The clean, verified path:

1. **Deploy the exact merge commit from a detached HEAD** (not a branch):
   ```sh
   git fetch origin --quiet
   git checkout <merge_commit_sha>        # detached; worktree-safe (only BRANCH checkouts collide)
   test "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)"   # MUST pass — you ARE on main's tip
   test -z "$(git status --porcelain)"                              # MUST be clean — you deploy the tree as-is
   ```
   Do this guard *yourself* — the next step disables the script's built-in one.

2. **Run the deploy script in CI mode for an image-only deploy.** Setting `CI=1` (or `GITHUB_ACTIONS=1`) is exactly what the label-gated workflow runs, and on these scripts it has a **dual effect** that is the whole point:
   ```sh
   CI=1 bash ./deploy_baker.sh        # or deploy_scoring_pulse.sh
   ```
   - skips the `[[ -z "${CI:-}" ]]` **git-state guard** (you just did it by hand from detached HEAD), AND
   - skips the **manual-only scheduler-flip + IAM re-assert** block (`if [[ -n "${CI:-}" ]]: SKIP`).

   Running it *without* `CI=1` from a workstation re-asserts the Cloud Scheduler sentinel + IAM bindings — those are already live, and the unguarded `gcloud scheduler jobs update` will `set -e` **abort the script after the image already deployed** if you lack `cloudscheduler.jobs.update`. So for a routine redeploy of already-merged code, **`CI=1` is the correct minimal action**, not a shortcut.

3. **A Cloud Run *Job* (baker) image deploy is staged, not active.** Unlike a *Service* revision (live on deploy), a Job only runs the new image on its next execution. The next chained/cron bake will use it — but to make the change **visible now**, execute the job. Beware the freshness gate:
   ```sh
   gcloud run jobs execute <job> --region <r> --project <p> --wait
   # → "v6 scoring not ready: MAX(scoring_date)=<yesterday> today=<today> — exiting 0"  ← gate no-op'd, NOTHING baked
   gcloud run jobs execute <job> --args="--target-date=max" --region <r> --project <p> --wait   # force-bake freshest data
   ```
   The plain execute **silently no-ops** (exit 0) before today's upstream data lands; `--target-date=max` bakes against the latest available date so the change goes live immediately. Confirm the payload was rebuilt by the NEW image (query the payload table's `built_at` + a value your change controls), not just that the job exited 0.

### B — Add the missing label to the merged PR (audit trail)

Even if you can't re-trigger the workflow (`pull_request: types: [closed]` only fires once), add the label so future audits can see what should have happened:

```sh
gh pr edit <N> --add-label auto-deploy
```

This is purely cosmetic for the PR record. It does NOT trigger a re-run of the closed event.

### C — If the workflow has `workflow_dispatch`, re-fire manually

```sh
grep -n 'workflow_dispatch' .github/workflows/<deploy-workflow-name>.yml
```

If present:

```sh
gh workflow run <deploy-workflow-name>.yml --ref main
```

If not present, options A or B are your only paths.

## Verification

After deploy:

```sh
# Cloud Run: check the latest revision matches the post-merge commit
gcloud run services describe <service> --region <region> \
  --format='value(status.latestReadyRevisionName, status.latestCreatedRevisionName)'

# Or hit the deployed URL and confirm the change is visible
```

For Cloud Run specifically, the new revision's name carries a hash; cross-reference against `gh run view <build-run-id> --json` to confirm the build-source commit matches your merge SHA.

**Attribution discipline — don't blame your deploy for pre-existing alerts.** A first post-deploy run (especially a manual force-bake) often surfaces warnings/red alerts in its logs. Before attributing any of them to your change, **diff against the PRIOR run's logs** — query the same alert signature over the last few runs:

```sh
gcloud logging read 'resource.type="cloud_run_job" AND resource.labels.job_name="<job>" AND textPayload:"MONITOR_ALERT:<NAME>"' \
  --project <p> --limit 15 --freshness 3d --format='value(timestamp,textPayload)'
```

If the identical signature fired on runs *before* your deploy, it is pre-existing — file it separately, don't conflate it with your change. (2026-06-28: a baker redeploy's bake logged a red `MODEL_HEALTH worst=invariants` + a `Failed to query SHAP trend data` warning; both were proven pre-existing by the prior two days' logs — the invariants red was a model-cutover re-baseline tail, the SHAP warning a latent `model_version` column-reference bug in an *untouched* query. Neither was the deploy's fault; both became their own issues.)

## Prevention

Three layers, pick at least one:

### Prevention 1 — PR template + CODEOWNERS hint

Add to `.github/PULL_REQUEST_TEMPLATE.md`:

```markdown
- [ ] Add `auto-deploy` label if this PR should ship to production on merge.
      Without this label the deploy workflow will skip silently — even with all CI green.
```

### Prevention 2 — Brief subagents about post-merge ops

When dispatching agents to ship code end-to-end, include in the prompt:

```
After CI goes green, BEFORE merging, add the `auto-deploy` label
via `gh pr edit <N> --add-label auto-deploy` so the deploy workflow
fires on merge. Without the label, the workflow will skip and the
change won't ship to prod even though CI is green.
```

This is the failure mode that happens most often when delegating PR creation.

### Prevention 3 — Required-status-check + bot enforcement

If your team can configure branch protection: require a status check that fails when the auto-deploy label is missing on PRs that touch service code paths. A simple GHA `pull_request` job (separate from the deploy workflow) that checks `if !contains(labels, 'auto-deploy') { fail }` on certain paths.

This is heavier-weight; only do if the missed-label trap is recurring.

### Prevention 4 — Auto-label via `actions/labeler` (recommended)

The cleanest fix: add a GHA workflow that automatically applies the `auto-deploy` label to any PR whose diff touches the deployable paths. The human still has an opt-out (remove the label before merge), but the default is now correct with no manual step.

Two files needed:

**`.github/labeler.yml`**:
```yaml
auto-deploy:
  - changed-files:
    - any-glob-to-any-file: ['<analytics_pkg>/cloudrun/<dashboard_app>/**']
```

**`.github/workflows/auto_label.yml`**:
```yaml
name: Auto-label PRs
on:
  pull_request:
    types: [opened, synchronize, reopened]
permissions:
  contents: read
  pull-requests: write
jobs:
  label:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/labeler@v6
        with:
          repo-token: ${{ secrets.GITHUB_TOKEN }}
          configuration-path: .github/labeler.yml
          sync-labels: false  # never remove labels a human added manually
```

Key points:
- `actions/labeler@v6` is current as of 2026-05 (v5 is from 2023, v6.1.0 is latest)
- `sync-labels: false` prevents the action from removing labels humans added for other reasons
- Fires on `synchronize` too, so if a PR gains/loses the deployable files after opening, the label stays in sync
- Use `any-glob-to-any-file` (not `all-globs-to-any-file`) — label if ANY changed file matches ANY glob
- Adjust the glob to match whichever paths your deploy workflow's path filter watches

### Inverse trap — the auto-labeler OVER-labels a config/docs-only PR under the deployable path (verified 2026-07-01)

Prevention 4 introduces the opposite failure mode. The labeler globs the *whole* deployable tree (`<dashboard_app>/**`), but that tree contains files that **do not affect the built image** — e.g. `<dashboard_app>/monitoring/*.yaml` (Cloud Monitoring IaC applied out-of-band via `gcloud`), READMEs, ADRs. A PR that only touches those still gets `auto-deploy` auto-applied, and because the deploy workflow's path filter *also* matches `<dashboard_app>/**` (the `!`-exclusions only cover baker files), **merging fires a full dashboard redeploy for a change the image never sees** — redeploying whatever else is on `main`, an unintended out-of-band ship.

Symptom: you open a monitoring/config/docs PR, and `gh pr view <N> --json labels` shows `auto-deploy` you didn't add.

Fix — remove it before merge:
```sh
gh pr edit <N> --remove-label auto-deploy   # then verify: gh pr view <N> --json labels
```
The labeler runs on `opened`/`synchronize`, so it won't re-add after you remove it unless you push again. Confirm the deploy stayed skipped post-merge:
```sh
gh run list --workflow=<deploy-workflow>.yml --limit 2 --json conclusion,displayTitle   # expect "skipped" for your PR
```
Durable fix (if config-only PRs under the deployable path are common): tighten the deploy workflow's path filter to `!`-exclude `<dashboard_app>/monitoring/**` (and other non-image dirs), the same way baker-only files are already excluded — so even a labeled config PR gates out.

## Notes

- This skill assumes the `pull_request: types: [closed]` event has already fired and is gone. GHA does NOT re-fire that event when you add a label after merge.
- If you find yourself running manual deploys often because the label is missed, treat it as a process signal — Prevention 1 or 3 will pay back fast.
- For repos that ALSO have a daily cron-bake (e.g. `dashboard_payloads_v1` baker), remember that `dashboard.html` template changes ship via the **service revision** (deploy workflow), not the **bake** (cron job). If the deploy is skipped, no amount of bake re-running will surface template / route / JS changes — they're baked into the container image.
- Sister skill `gha-auto-deploy-never-ran-skipped-mask` covers the case where the gate FIRES (you DID add the label) but the deploy fails on a hidden infra issue. Both wear the same `skipped`-in-the-summary disguise but have opposite root causes.
- Related: `deploy-from-stale-worktree-silent-rollback` is the next thing to read before manually running the deploy script — packaging the wrong worktree is the next trap once you bypass the auto-deploy.

## References

- Sister skill: `gha-auto-deploy-never-ran-skipped-mask` — first-time gate fires + permission gap. Not part of this plugin and not published; refer to it by name.
- Sister skill: `deploy-from-stale-worktree-silent-rollback` — manual deploy preflight; in this same plugin ([source](https://github.com/wan-huiyan/agent-traffic-control/blob/main/plugins/agent-traffic-control/skills/deploy-from-stale-worktree-silent-rollback/SKILL.md))
- GHA docs: [Events that trigger workflows — pull_request](https://docs.github.com/en/actions/using-workflows/events-that-trigger-workflows#pull_request)
- GHA docs: [Conditional execution — `if:`](https://docs.github.com/en/actions/using-workflows/workflow-syntax-for-github-actions#jobsjob_idif)
