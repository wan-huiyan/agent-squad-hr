---
name: flask-debug-cross-worktree-edit-stale
description: |
  Diagnose "I edited the template / view / CSS but Flask debug-mode keeps
  serving the old version" when running a local dev server (Flask, Django
  runserver, Rails server, etc.) from one git worktree while editing files
  in a sibling worktree of the same repo. Use when: (1) you have multiple
  `git worktree` checkouts of the same repo (typical with
  `.claude/worktrees/<feature>` directories), (2) a dev server is running
  in worktree A serving its working tree, (3) you're making edits in
  worktree B because branch X is checked out at A and you can't `git
  checkout X` in B too, (4) `curl http://127.0.0.1:PORT/page` returns
  byte-identical responses despite your edits, (5) you're tempted to
  blame Jinja bytecode cache, Flask `@_ttl_cache`, or browser caching.
  Root cause is filesystem-level: each git worktree has its own
  independent working tree on disk; Flask is reading worktree A's files,
  not worktree B's. Cache-busting tricks (`touch app.py`, browser hard
  refresh, restart Flask) won't help. Sister skill to
  `flask-debug-ttl-cache-stale-after-rebake` (genuine TTL cache trap) and
  `gh-pr-merge-worktree-checkout-trap` (branch-checked-out-elsewhere
  errors). Different from `deploy-from-stale-worktree-silent-rollback`
  (which covers Cloud Run / Docker production deploys, not localhost).
author: Claude Code
version: 1.0.0
date: 2026-05-08
disable-model-invocation: true
---

# Flask debug edits cross-worktree stale

## Problem

You're running a Flask dev server (`python app.py` with `debug=True`,
or `flask run --debug`) from one git worktree. You're editing template
/ static / view files from a *sibling* worktree of the same repo,
because the branch you want to ship is checked out at the running
worktree and `git checkout <branch>` fails in your editing worktree.

You hit `curl http://127.0.0.1:PORT/the-page` after each edit, and the
response bytes don't change. You hypothesize Jinja bytecode cache,
Flask `@_ttl_cache`, browser caching, CDN, or stale `__pycache__`. You
try `touch app.py` to bust Flask's debug-reload, restart the process,
clear browser cache. Nothing fixes it.

**Root cause:** git worktrees have **independent working trees on
disk**. Each `git worktree` directory has its own copy of every tracked
file. Flask is reading from `<worktree-A>/templates/page.html`. Your
edits live in `<worktree-B>/templates/page.html`. They're physically
different files; the dev server has no way to see B's edits until A's
disk state changes.

## Trigger conditions (high-confidence diagnosis)

Fire this skill when ALL of these are true:

1. `git worktree list` shows ≥2 worktrees of the same repo.
2. A dev server is bound to a known port; `lsof -i :PORT` shows the
   server process.
3. The server's CWD (`lsof -p <PID> | grep cwd`, or check the script
   that launched it) is in worktree A.
4. Your editor is making changes in worktree B (different path, same
   repo).
5. `curl` against the page returns byte-identical responses despite
   confirmed-saved edits in worktree B.
6. The file you're editing is **tracked** (git knows about it) — not
   a new untracked file. (Untracked files exist in only one worktree
   anyway.)

If condition 6 is FALSE (you created a new file), the new file simply
doesn't exist in worktree A's tree. Same root cause, different shape:
either commit + ff-merge into A's branch, or create the file in A.

## Diagnostic recipe

```bash
# 1. Confirm cross-worktree mismatch
diff -q \
  <(grep "your-recent-edit-marker" "<worktree-A>/path/to/file") \
  <(grep "your-recent-edit-marker" "<worktree-B>/path/to/file")
# Files differ → confirmed.
# Files match → look elsewhere (TTL cache, CDN, etc.).

# 2. Confirm Flask is actually reading from A
lsof -p $(lsof -ti :PORT | head -1) | grep "cwd\|<worktree-A>"

# 3. Check git state of A
git -C "<worktree-A>" rev-parse HEAD
git -C "<worktree-A>" status -sb
# What branch is A on? Are there uncommitted changes that would conflict
# with merging your work in?
```

## Solution

Three fixes, in order of safety + ease:

### Fix 1 — ff-merge your branch into A's branch (recommended)

If A has a clean working tree and is checked out on a branch your work
should land on (e.g., the wip branch), commit your edits in B and
fast-forward-merge into A.

```bash
# In worktree B (where you're editing):
git -C "<worktree-B>" add <files>
git -C "<worktree-B>" commit -m "..."

# Then ff-merge into A's branch (run from B is fine; --ff-only refuses
# any non-trivial merge so it's safe):
git -C "<worktree-A>" merge --ff-only <your-branch>
```

Flask debug-reload watches the disk and picks up the changed files on
next request. Done.

This is also the right move when the user wants the work merged into
the wip branch anyway — preferable to polluting A with WIP commits.

### Fix 2 — Move Flask to your worktree

Stop the dev server in A; start it in B from your branch directly.
Costs you the convenience of running from the "blessed" worktree but
eliminates the cross-worktree gap entirely.

```bash
# Stop A's server
lsof -ti :PORT | xargs kill -9

# Start in B
cd "<worktree-B>/<dashboard-dir>"
python3.11 app.py    # or flask run --debug --port PORT
```

### Fix 3 — Sync files manually (debugging only)

For a one-off probe (e.g., "does my CSS edit even render?"), copy the
single file across:

```bash
cp "<worktree-B>/static/css/foo.css" "<worktree-A>/static/css/foo.css"
```

**Don't use this as a workflow.** It silently overwrites whatever's in
A and creates divergence-from-git that's easy to forget. Only use to
prove the diagnosis before committing to Fix 1 or Fix 2.

## Verification

After applying Fix 1 or Fix 2:

```bash
curl -s "http://127.0.0.1:PORT/page" | grep "your-recent-edit-marker" | wc -l
# > 0  → fix worked, dev server now serves your edits
# 0    → still stale; check Flask log for reload errors, or escalate
#         to the sister TTL-cache skill
```

## Why cache-bust tricks fail (and which skill to use instead)

| Symptom | Wrong skill | Right diagnosis |
|---|---|---|
| `touch app.py` doesn't help | `flask-debug-ttl-cache-stale-after-rebake` (Flask TTL cache) | This skill — file-level divergence |
| Browser shows old version after server restart | Browser cache | This skill — server is reading A, browser is correctly receiving A's content |
| Restart Flask, still stale | Bytecode cache | This skill — file system, not Python state |
| `git status` in B shows clean tree but page still old | Git confusion | This skill — A's tree is independent of B's |

The fast disambiguation: **does worktree A's working tree have your
edit?** If no, it's this skill. If yes, look elsewhere.

## Example

Real session 2026-05-08 (this is where the skill was extracted):

- Primary worktree (`/Users/.../the-project-repo`) had
  `wip/monitor-noapp-cohort-broaden` checked out, Flask running on
  :8006 from there.
- Sister worktree (`.claude/worktrees/monitor-prettify`) was where
  edits were being made.
- After 5 polish edits to `templates/library_roadmap.html`, curl
  returned byte-identical 27,028 bytes every time.
- Confused for ~3 minutes by hypotheses around Jinja cache, Flask
  TTL, etc.
- Diagnosis: `grep "miscounted in training" <worktree-A>/...html` → 0
  hits. `grep "miscounted in training" <worktree-B>/...html` → 3
  hits. Confirmed disk divergence.
- Fix: committed in B, ff-merged into wip from primary. Next curl saw
  the polish.

Result: page served correctly within ~1 second of the merge (Flask
debug-reload caught the file change).

## Notes

- **This is NOT a Flask bug.** Every dev server with file-watching
  (Django runserver, Rails server with Spring, etc.) has the same
  shape. The skill name says Flask because that's where it was
  observed, but the diagnostic procedure and fixes generalize.
- **macOS / Linux only.** Windows + git worktrees has additional
  subtleties (CRLF translation, junction points) not covered here.
- **The diagnostic is fast.** A single `diff -q` between worktree
  paths confirms the hypothesis in <1 second. Don't hypothesize for
  3 minutes like the original session did — `diff -q` first.
- **Auto-docs hooks may help OR hurt.** If your project has a hook
  that auto-syncs files, it can either propagate your B-side edits to
  A automatically (helpful) or revert them (frustrating). Check
  whether such a hook exists; if so, consider whether to commit
  through it or work around it.

## See also

- `gh-pr-merge-worktree-checkout-trap` — git-side error that prevents
  you from `git checkout`-ing the same branch in two worktrees.
  Forces you into the cross-worktree edit pattern this skill diagnoses.
- `deploy-from-stale-worktree-silent-rollback` — production sibling
  pattern: Cloud Run / Docker build context = local filesystem, so
  deploying from worktree A bakes A's stale state into the image.
  This skill's localhost-Flask analogue.
- `worktree-index-corrupt-async-post-commit-hook` — different worktree
  trap: corrupt index after async post-commit hooks. Use that skill
  when `git status` itself errors with `unable to read <sha>`.

## References

- Git docs on `git-worktree(1)`: each worktree has its own
  `HEAD`, `index`, and working tree but shares the object store.
  https://git-scm.com/docs/git-worktree
- Flask `debug=True` reloads on file-watcher events; the watcher
  scans the **process's CWD tree**, not "the repo".
  https://flask.palletsprojects.com/en/latest/server/
