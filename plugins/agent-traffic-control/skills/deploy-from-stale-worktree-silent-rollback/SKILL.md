---
name: deploy-from-stale-worktree-silent-rollback
description: |
  Diagnose "I deployed a new Cloud Run / Docker image but a bunch of recently
  merged fixes regressed in production." Use when: (1) the deploy script does
  `gcloud builds submit ... "${SCRIPT_DIR}"` or `docker build <dir>` (build
  context = local filesystem, NOT a git ref), (2) the user has many git
  worktrees / multiple checkouts of the same repo, (3) the user reports
  "redeployed but the fix from PR #X isn't live" or "lots of fixes regressed
  after my deploy", (4) the deployed revision created at time T was authored
  by the user themselves (not CI). Root cause: deploy was run from a worktree
  whose HEAD predates the merged PRs; the build packaged stale local files,
  silently rolling back N commits worth of merged fixes. Provides the
  authoritative diagnostic (download Cloud Build source tarball + byte-diff
  against git history to identify the source commit) and the fix (rebuild from
  current main checkout, or instant traffic-switch rollback to the last
  known-good revision). v1.1 adds a pre-deploy preflight (5 lines from the
  deploy directory: fetch + `git status -sb` first-line interpretation table +
  ahead/behind count + uncommitted check) that catches the trap BEFORE the
  build runs, plus an explicit Variant note for when the *main repo root* is
  parked on a feature branch (operators using .claude/worktrees treat the
  main dir as scratch space for small commits — the deploy script reads it,
  ships the feature branch instead of main, silent rollback). Sister skill to
  `baked-payload-stale-after-merge` (same "fix not visible after redeploy"
  symptom, but root cause is the separately-deployed baker; this skill is
  when the SERVING image itself is stale-from-build).
author: Claude Code
version: 1.2.0
date: 2026-05-07
disable-model-invocation: true
---

# Deploy from a stale worktree silently rolls back merged fixes

## Problem

The user merged a PR (or many PRs), redeployed the serving service, and
reports the fix isn't live — sometimes "a lot of fixes regressed". The
deployed image is brand new (recent timestamp, latest revision) and the
deploy succeeded green. The diff between code and what's deployed is
*not* a baking issue, *not* a browser cache issue — the **image itself
contains old code**.

This happens when the deploy script's build context is the local
filesystem (`gcloud builds submit ... "${LOCAL_DIR}"`,
`docker build <dir>`, `gcloud run deploy --source <dir>`, `kaniko
--context dir://...`) and the user runs it from a stale checkout. With
many git worktrees, it is easy to be sitting in `worktrees/foo/` 21
commits behind `main` and not notice — the deploy ships whatever is on
disk.

## Trigger conditions

All of these are typical:

1. The repo has a deploy script that uses one of:
   - `gcloud builds submit --tag=... "${SCRIPT_DIR}"` (no commit SHA tag)
   - `docker build -t ... <local-dir>` then push
   - `gcloud run deploy --source <local-dir>`
2. The user has multiple checkouts of the same repo (worktrees,
   sibling clones, IDE-managed copies). `git worktree list` shows
   ≥3 worktrees.
3. The user reports a regression after a self-initiated deploy
   (`serving.knative.dev/creator` on the new revision is the user's
   email, not a CI service account).
4. The "regressed" PRs were all merged BEFORE the deploy timestamp —
   they exist on `origin/main` but not necessarily in the local cwd.
5. There is no commit SHA visible on the deployed image (only `:latest`
   or no tag at all). This is a strong tell that the build context was
   local FS, not a git ref.

## Pre-deploy preflight (catch the trap BEFORE it fires)

Run this preflight from the deploy script's directory before you invoke
the build. It costs ~1s and catches every variant of this trap without
needing to inspect Cloud Build tarballs after the fact.

```sh
cd <main-repo-root>           # the dir whose path the deploy script feeds to gcloud builds submit
git fetch origin main
git status -sb                # FIRST line — if not "## main", switch before pulling
git rev-list --count HEAD..origin/main   # must be 0 to deploy
git status --porcelain        # must be empty (uncommitted = will deploy)
git log --oneline -1          # v1.2.0 — actually verify HEAD advanced (don't trust git pull's "Updating X..Y" line)
grep -F "<sentinel-string-from-latest-commit>" <expected-file>   # v1.2.0 — file-level proof the working tree matches the commit
```

The branch line of `git status -sb` (the very first line of output)
is the authoritative tell. Three cases:

| `git status -sb` first line                                    | What it means                                  | Action                                                                             |
|----------------------------------------------------------------|------------------------------------------------|------------------------------------------------------------------------------------|
| `## main...origin/main`                                        | Clean, up-to-date                              | Proceed                                                                            |
| `## main...origin/main [behind N]`                             | On main but stale                              | `git pull --ff-only origin main`                                                   |
| `## main...origin/main [ahead N]` or `[ahead N, behind M]`     | Local main has unmerged commits                | Stop. Rebase or push first, never deploy local-only commits silently               |
| **`## <any-other-branch>`**                                    | **Main repo root parked on a feature branch**  | `git checkout main && git pull --ff-only` (see Variant below for the fuller story) |

If you don't recognise the first-line format, **stop and read it** —
this is the one sentence whose misread costs you a silent rollback.

### Variant — `git pull` printed "Updating X..Y" but HEAD silently didn't advance (v1.2.0)

`git status -sb` can show `## main...origin/main` (clean, up-to-date)
**after a pull that didn't actually update anything**, leaving the
working tree stranded at the old commit. The pull's stdout claim
("Updating 9774935..f90b952") is not authoritative — it represents
the operation that *was attempted*, not the result.

**Root cause:** a stale `.git/worktrees/<name>/index.lock` from an
interrupted async post-commit hook blocks the index update. Git silently
skips the working-tree write but still prints the "Updating ..." line
based on the fetched ref. `git status` then shows clean — because
the index DID get reset, just to the old tree.

**Symptoms — all three together:**

1. `git pull --ff-only origin main` reports `Updating <old>..<new>` and exits 0.
2. `git log --oneline -1` shows `<old>`, not `<new>`. **This is the canonical tell.**
3. A file you know is in `<new>` is missing from disk or has the pre-`<new>` content.

**Prevention — add two lines to the preflight:**

```sh
# (after `git pull --ff-only origin main`)
git log --oneline -1                                           # must show the SHA you expected
grep -F "<sentinel-from-latest-commit>" <expected-file>        # must succeed (exits 0)
```

For the second check, pick any unique short string from the most
recent merge — a function name, a comment, a hex value. If the
working tree is at the right commit the grep succeeds; if it's
stranded the grep returns non-zero and you stop before the build runs.

**Fix when caught:** `find .git/worktrees -name index.lock -delete`,
then re-pull. The lock file is always empty (`0` bytes) — verify
with `ls -la` that no process holds it before deleting.

**Cross-reference:** the `worktree-index-corrupt-async-post-commit-hook`
skill covers the lock-file mechanism itself (and the
`fatal: unable to read <sha>` errors when the corruption is worse).
This skill's variant is specifically the *silent* case where neither
git nor the deploy script signals anything wrong.

**Worked example (brief-runner s18b, 2026-05-27):** PR #84 merged
a favicon at `f90b952`. The deploy worktree (long-lived `main`
checkout used by `gcloud builds submit`) had a stale
`index.lock`. `git pull` printed `Updating 9774935..f90b952` but
`git log --oneline -1` still showed `9774935`. The build tarball
captured the pre-favicon state, deployed at revision `00005-fvw`,
and `/static/favicon.svg` returned 404. After diagnosis: removed
the lock, re-pulled (HEAD actually advanced this time), redeployed
at `00006-pkv`. **Adopted: `grep -F <sentinel> <expected-file>`
sanity check before every subsequent `gcloud builds submit`** —
caught the trap proactively on the next deploy cycle. The `grep`
adds maybe 50ms and saves a ~4-minute Cloud Build cycle plus the
user-facing "the change didn't ship" round-trip.

## Diagnostic — confirm before redeploying

Three steps. Each one rules out alternatives.

### Step 1: identify the deployed image and its build

```sh
# What revision is serving traffic?
gcloud run services describe <SERVICE> --region=<REGION> --project=<PROJECT> \
  --format="value(status.latestReadyRevisionName,spec.template.spec.containers[0].image)"

# Recent revisions (look for who deployed and when)
gcloud run revisions list --service=<SERVICE> --region=<REGION> --project=<PROJECT> \
  --limit=5 --format="table(metadata.name,metadata.creationTimestamp,metadata.annotations['serving.knative.dev/creator'],spec.containers[0].image.basename())"

# Recent builds (find the build that produced the deployed digest)
gcloud builds list --project=<PROJECT> --limit=5 \
  --format="table(id,createTime,status,images[0])"
```

If the build was from `gcloud builds submit`, the source tarball is in GCS:

```sh
gcloud builds describe <BUILD_ID> --project=<PROJECT> \
  --format="value(source.storageSource.bucket,source.storageSource.object)"
```

### Step 2: download the build source tarball + inspect

```sh
gcloud storage cp gs://<bucket>/<object> /tmp/build_source.tgz \
  --project=<PROJECT>
mkdir -p /tmp/build && tar -xzf /tmp/build_source.tgz -C /tmp/build

# Inspect the file the user reports as broken (e.g. a template, a Python module)
grep -n "<unique-string-from-the-fix>" /tmp/build/<path/to/file>
```

If the fix is missing from the tarball, **the image was built from stale
code**. Confirm by comparing against git: find which commit's version
of the file matches the deployed one byte-for-byte:

```sh
git log --all --oneline --format="%H" -- <path/to/file> | while read sha; do
  if git show "$sha:<path/to/file>" 2>/dev/null | diff -q - /tmp/build/<path/to/file> >/dev/null 2>&1; then
    echo "MATCH: $sha"
    git log -1 --format="  %cI %s" "$sha"
  fi
done | head -5
```

The matching commit tells you what state the local FS was in when the
deploy ran. Now find the worktree.

### Step 3: identify the stale worktree

```sh
# Find worktrees whose copy of the file matches the deployed (stale) version
for wt in <repo-root> <repo-root>/.claude/worktrees/*/ <other-checkouts>/; do
  f="$wt/<path/to/file>"
  [[ -f "$f" ]] || continue
  if diff -q "$f" /tmp/build/<path/to/file> >/dev/null 2>&1; then
    mtime=$(stat -f "%Sm" "$f")
    echo "MATCH  $mtime  $wt"
  fi
done
```

The worktree with mtime closest to (but before) the build timestamp is
the one the user deployed from. Confirm by checking how far behind it is:

```sh
cd <suspect-worktree>
git rev-list --count HEAD..origin/main      # commits missing
git merge-base --is-ancestor <fix-commit> HEAD && echo "fix present" || echo "FIX MISSING"
```

## Fix

### Immediate (instant, reversible) — traffic-switch to last known-good revision

```sh
gcloud run services update-traffic <SERVICE> \
  --region=<REGION> --project=<PROJECT> \
  --to-revisions=<KNOWN_GOOD_REVISION>=100
```

This restores prior state in ~30 seconds with no rebuild. Use when the
user wants the regression unwound NOW; defer the proper rebuild.

### Proper — rebuild from current main checkout

```sh
cd <repo-root>                              # NOT a feature worktree
git checkout main && git pull --ff-only origin main
git status --porcelain                      # confirm no uncommitted changes
git rev-list --count HEAD..origin/main     # confirm zero behind
bash <path-to-deploy-script> --force
```

Then verify with the diagnostic (Step 2) — the new build's tarball
should contain the fix.

## Prevention — guard the deploy script

Add this near the top of the deploy script:

```sh
# Refuse to deploy from anything other than a current main checkout.
GIT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
GIT_BEHIND=$(git rev-list --count HEAD..origin/main 2>/dev/null || echo "?")
GIT_DIRTY=$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')

if [[ "${GIT_BRANCH}" != "main" ]]; then
  echo "ERROR: not on main (currently on '${GIT_BRANCH}'). Refusing to deploy."
  echo "  cd to the main checkout, or pass --i-know-what-im-doing to override."
  [[ "${1:-}" == "--i-know-what-im-doing" ]] || exit 1
fi
if [[ "${GIT_BEHIND}" != "0" ]]; then
  echo "ERROR: ${GIT_BEHIND} commits behind origin/main. Run 'git pull' first."
  [[ "${1:-}" == "--i-know-what-im-doing" ]] || exit 1
fi
if [[ "${GIT_DIRTY}" != "0" ]]; then
  echo "WARNING: working tree has uncommitted changes — they will be deployed."
fi
```

Equivalent for Dockerfile / Cloud Build YAML projects: bake the
`git rev-parse HEAD` into a build arg + image label, then assert at
deploy time that the label matches `git rev-parse origin/main`.

## Verification

After the proper rebuild:

```sh
# 1. New revision exists and serves traffic
gcloud run revisions list --service=<SERVICE> --region=<REGION> \
  --project=<PROJECT> --limit=2

# 2. Pull the new build's source tarball + grep for the fix
NEW_BUILD_ID=$(gcloud builds list --project=<PROJECT> --limit=1 \
  --format="value(id)")
SOURCE=$(gcloud builds describe "$NEW_BUILD_ID" --project=<PROJECT> \
  --format="value(source.storageSource.bucket,source.storageSource.object)")
gcloud storage cp gs://${SOURCE/$'\t'//} /tmp/new_build.tgz --project=<PROJECT>
mkdir -p /tmp/new_build && tar -xzf /tmp/new_build.tgz -C /tmp/new_build
grep -n "<fix-marker>" /tmp/new_build/<path/to/file>   # should now find it
```

## Worked example (a client analytics dashboard, 2026-05-07)

User: "I just deployed a new version of cloud run but a lot of the
fixes got regressed. e.g, Feature Snapshot are still in driver but we
moved it to explore."

PR #317 (commit `c382b28f`) had merged 8 hours earlier removing the
duplicate Feature Snapshot section from `/drivers`. After the user's
deploy, it was back.

**Diagnostic:**

```sh
$ gcloud run services describe the-dashboard-service --region=us-central1 \
    --project=your-project --format="value(status.latestReadyRevisionName)"
the-dashboard-service-00011-w22

$ gcloud builds list --project=your-project --limit=3 \
    --format="table(id,createTime,images[0])"
50826116-...    2026-05-07 10:10 UTC    gcr.io/your-project/the-dashboard-service

$ gcloud builds describe 50826116-... --project=your-project \
    --format="value(source.storageSource.bucket,source.storageSource.object)"
your-project_cloudbuild  source/1778148635.480733-c08dc0a63ec245b98158888fdb0fd39e.tgz

$ gcloud storage cp gs://your-project_cloudbuild/source/1778148635...tgz /tmp/build.tgz
$ tar -xzf /tmp/build.tgz -C /tmp/build
$ grep -n "Feature Snapshot" /tmp/build/templates/drivers.html
92:    Feature Snapshot           # ← THE SECTION HEADER, not a comment
```

The deployed `drivers.html` line 92 was the section header, NOT the
"moved to /library/explorer" Jinja comment that PR #317 had replaced
it with. **The image was built from pre-#317 code.**

Match against git:

```sh
$ git log --all --oneline --format="%H" -- ...drivers.html | while read sha; do
    git show "$sha:<analytics_pkg>/.../drivers.html" 2>/dev/null \
      | diff -q - /tmp/build/templates/drivers.html >/dev/null \
      && echo "MATCH: $sha"
  done | head
MATCH: 53dbf71181...    # PR #303, BEFORE PR #317
```

Worktree search:

```sh
$ for wt in .../.claude/worktrees/*/; do
    [[ -f "$wt/...drivers.html" ]] && \
      diff -q "$wt/...drivers.html" /tmp/build/templates/drivers.html >/dev/null \
      && echo "MATCH $(stat -f %Sm $wt/...drivers.html)  $wt"
  done
MATCH May  7 10:40:47 2026  .../worktrees/monitor_poor/   # ← deploy mtime ~9:40 UTC
```

`monitor_poor/` HEAD = `6149771d` (PR #311 squash, S140b's `/actions`
redesign), **21 commits behind origin/main**, missing PRs #317, #318,
#319, #320 + 17 wave1 fixes (#343–362). The deploy from this worktree
silently rolled back ~21 merged fixes from production.

**Fix applied:** instant traffic switch to `00010-bt2` (S140c's last
good revision), then proper rebuild instructions handed back to user
(harness blocks production deploys; user runs the rebuild themselves).

## Notes

- **The "no commit SHA" tell**: when you see a deployed image tagged
  only `:latest` (or unlabeled) — no `:abc123def` SHA tag — it almost
  always means the deploy script doesn't bake a git ref into the image.
  That's the architectural precondition for this trap. Recommend adding
  `--tag=${IMAGE}:$(git rev-parse --short HEAD)` to the deploy script.
- **Why worktrees worsen this**: a single-clone repo enforces "you are
  on one branch at a time" — `git status` is loud. Worktrees let you
  have 100+ checkouts each on a different (often stale) branch. The
  user's mental model — "I just merged that PR, surely my checkout has
  it" — silently breaks.
- **Variant: main repo root parked on a feature branch** (v1.1, observed
  3× across May 2026). In workflows that use `.claude/worktrees/` (or
  similar isolated-feature-branch tools), the *main* repo dir frequently
  ends up checked out to a feature branch — operators treat it as scratch
  space for the WIP that doesn't merit a fresh worktree (e.g. small
  doc-only commits, exploratory `/monitor` rework). When the deploy
  script targets the main repo dir's path (`SCRIPT_DIR=…/repo`,
  `gcloud builds submit "${SCRIPT_DIR}"`), it ships whatever branch is
  checked out there — NOT origin/main. The trap fires silently because
  the operator's mental model is "the main repo dir is on main." **Fix:**
  always run `git status -sb` from the deploy directory FIRST (see
  Pre-deploy preflight above) — if the first line isn't
  `## main...origin/main`, you have a feature branch. Then
  `git checkout main && git pull --ff-only origin main` before invoking
  the build. Untracked files (often the operator's in-progress docs)
  follow the branch switch fine *unless* origin/main has the same path,
  so verify via `git ls-tree -r origin/main --name-only | grep -F <path>`
  before checkout when the working dir has untracked content. This
  variant is more common than the `.claude/worktrees/<feature>/` case
  because the main repo dir reads as "the canonical one" — operators
  don't think to check its branch.
- **Why `:latest` resolution doesn't save you**: `gcloud run deploy`
  resolves `:latest` to a digest at deploy time. But the IMAGE that
  `:latest` points to was just built from the stale FS by the earlier
  `gcloud builds submit`. The digest is stable, but the bytes are old.
- **Filtering the worktree-search loop**: 100+ worktrees is a lot. If
  performance is an issue, narrow with `find <worktree-root> -name
  drivers.html -newer <known-old-marker> -mtime -1` to scope to recent
  files.
- **For Docker / non-gcloud builds**: the equivalent is to inspect the
  pushed image directly with `crane export <ref> -` (or `docker run
  --entrypoint cat <ref> /path/to/file` if you have docker locally).
  Same diagnostic — read the file FROM the deployed image and byte-diff
  against git history.

## Sister skills

- `worktree-index-corrupt-async-post-commit-hook` — the underlying
  lock-file mechanism the v1.2 "silent pull" variant depends on.
  That skill covers the LOUD case (`fatal: unable to read <sha>`
  errors); this skill's v1.2 variant covers the SILENT case (no
  error, pull's "Updating X..Y" line lies, deploy ships old code).
- `gh-pr-merge-worktree-checkout-trap` — different worktree pitfall
  (gh CLI refusing to delete branch checked out in another worktree).
- `subagent-bash-cd-wrong-worktree` — subagent context, not deploy.
- `worktree-historical-test-replay-missing-dirs` — running historical
  tests against a worktree missing newer dirs.

## Changelog

- **v1.2.0 (2026-05-27):** Added "silent pull" variant — `git pull
  --ff-only` prints `Updating X..Y` and exits 0, but HEAD silently
  doesn't advance (stale `.git/worktrees/<name>/index.lock` from an
  interrupted async post-commit hook blocks the index update). The
  v1.1 preflight (`git status -sb` + ahead/behind counts) does NOT
  catch this because the post-pull state shows clean. Two new
  preflight lines: `git log --oneline -1` (verify the SHA actually
  advanced) + `grep -F <sentinel> <expected-file>` (file-level proof
  the working tree matches the commit). Source: brief-runner s18b
  PR #84 (favicon deployed at `00005-fvw` shipped without the SVG
  because the deploy worktree was silently stranded at the
  pre-favicon commit).
- **v1.1.0:** Added pre-deploy preflight (`git status -sb` first-line
  interpretation table + ahead/behind count + uncommitted check).
- **v1.0.0:** Initial skill.

## References

- gcloud builds submit:
  https://cloud.google.com/sdk/gcloud/reference/builds/submit
- Cloud Run revision rollback via traffic split:
  https://cloud.google.com/run/docs/managing/revisions#rollback
- git worktree:
  https://git-scm.com/docs/git-worktree
