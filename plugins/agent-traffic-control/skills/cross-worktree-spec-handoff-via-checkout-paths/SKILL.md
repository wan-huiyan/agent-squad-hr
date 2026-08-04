---
name: cross-worktree-spec-handoff-via-checkout-paths
description: |
  Pass design specs or any shared artefact between two parallel Claude Code sessions in
  different worktrees on different branches, without merging the producing branch to main first.
  Use when: (1) session A produced design docs / a handoff prompt / a mockup file on branch X,
  (2) session B (different cwd/worktree, branch Y off main) reports "the file doesn't exist" or
  "I can't find the design spec you mentioned", (3) you want B unblocked NOW, no PR review
  cycle, (4) both worktrees share one `.git`. Unblock: `git checkout <producing-branch> --
  <paths>` in B's worktree pulls them in as staged additions. Covers the gitignore-exception
  trick for blanket-ignored files (`*.html` mockups). Diagnostic-search variant: user says
  "execute <path/to/file>" but it isn't in your worktree — `git log --all --diff-filter=A --
  <path>` + `git branch --contains <sha>` find which branch holds it; `git show <branch>:<path>`
  reads it without modifying your tree. Clean-PR-extraction variant: land a mergeable SUBSET on
  main from a branch SHARED with a live parallel session or DO-NOT-MERGE content — cut a
  THROWAWAY worktree off origin/main, check safe paths in, never branch-switch the SHARED
  worktree (it yanks the parallel session's files). Cleanup: `gh pr merge --delete-branch` fails
  when main is checked out elsewhere. cwd-relative-pathspec trap: `git log --
  <root-relative-path>` returns EMPTY from a subdir, masking a committed file; use `git log
  --all --name-only | grep`, `git -C <root>`, or absolute-path Read.
author: Claude Code
version: 1.3.1
date: 2026-08-04
---

# Cross-worktree spec handoff via `git checkout <branch> -- <paths>`

## Problem

You ran a brainstorming / design session in Claude Code session A. Output:
design spec doc, a handoff prompt, a vibe mockup HTML. You committed them
on branch `worktree-spec-A` in `.claude/worktrees/spec-A/`.

You then started Claude Code session B in a different worktree, on a fresh
branch `feat/something-B` branched from `main`. Session B is supposed to
consume the design spec — but the spec doc, handoff prompt, and mockup
files **don't exist** in B's working tree, because B's branch was cut from
main before A's commits landed and the commits never made it to main.

Session B reports: "the referenced design spec files don't exist in the
handover. Let me look at what's available." → it's blocked.

The naive fix is "merge A's branch into main, then B pulls main". That
needs a PR review cycle. Slow.

## Context / Trigger Conditions

All of:

- Two (or more) Claude Code sessions are running in parallel, in
  **different worktrees** of the same repo. (`git worktree list` shows
  multiple paths.)
- Session A (the producer) committed artefacts — design docs, plans, spec
  files, mockups, fixtures, prompts — on a branch that is **not** the base
  branch of session B.
- Session B (the consumer) is on a branch branched from `main` (or any
  ancestor that predates A's commits) and cannot see A's files via
  `ls` or Read.
- B reports a "file not found" / "doesn't exist" / "can't see the spec"
  symptom referencing files that you (or session A) know exist on disk
  *somewhere else*.

Smoking-gun signals:
- The missing file's path matches one you (or A) named in a recent message
  ("the spec is at `docs/plans/...`").
- `git log --all --oneline -- <path>` shows the file was committed on a
  branch that isn't an ancestor of B's branch.
- `git worktree list` shows 2+ worktrees; the file exists in one but not
  the other.

Note: this is distinct from
[[multi-worktree-file-url-stale-content]] (browser opens stale file://
URL), [[subagent-bash-cd-wrong-worktree]] (subagent operates in the wrong
cwd), and [[worktree-outer-ls-mistaken-for-main-state]] (parent dir
listing not reflecting worktree state). Those are all "wrong working
directory" issues; this one is "right working directory, file genuinely
isn't there yet because it lives on a different branch."

## Solution

### Variant — handoff prompt missing from current worktree (read-only diagnostic)

Added 2026-05-26 (v1.1.0). The original skill below assumes you already know
which branch holds the missing artefact. If you DON'T — the user told you to
execute a handoff prompt (e.g., `docs/handoffs/session_N_prompt.md`) and it
doesn't exist in your current worktree — start with this diagnostic search
BEFORE jumping to Step 1.

Trigger: user says "execute `docs/handoffs/session_NN_prompt.md`" (or any
specific file path) and `Read` / `ls` reports the file doesn't exist on disk.

```bash
# 1. Find which commits anywhere in the repo first introduced this file
git log --all --oneline --diff-filter=A -- "*session_NN_prompt*" 2>&1 | head -10
# Example output:
#   5307eb9 docs(s69): handoff + S70 prompt — 3 PRs shipped ...
#   79d27d3 docs(s69): handoff + S70 prompt — 3 PRs shipped ...

# 2. Find which branches contain those commits
git branch -a --contains 5307eb9 2>&1 | head -5
# Example output:
#   remotes/origin/release-uk

# 3. Read the file directly without modifying your working tree
git show origin/release-uk:docs/handoffs/session_70_prompt.md | less
# or pipe to sed/grep for a section, or `gh` if it's already on GitHub
```

This is **read-only** — no checkout, no working-tree changes. Useful when
you just need to **read** the prompt to understand what to do; the full
Step 1→4 checkout flow below is for when subagents or downstream tooling
need the file to exist on disk in your worktree.

If `git log --all --diff-filter=A -- <path>` returns empty:
- **You're in a subdir/worktree and the pathspec is repo-root-relative.**
  `git log -- <path>` resolves `<path>` relative to your CWD, so a
  root-level `docs/handoffs/foo.md` queried from inside
  `docs/deliverables/.../sub/` matches nothing and returns EMPTY — even
  though the file is committed on your own branch. (Same trap bites
  `find .`, which only searches from cwd, so it ALSO comes up empty and
  the two together read as "the file was never committed".) Fix with a
  cwd-independent search: `git -C <repo-root> log -- <path>`, or drop the
  pathspec and grep the name list
  `git log --all --name-only --pretty=format: | grep -i <pattern>` (that
  list is repo-root-relative). Asymmetry worth memorizing: `git show
  <ref>:<repo-root-path>` and `git ls-tree` ARE repo-root-relative, so they
  resolve the file when `git log -- path` from the same cwd doesn't — and an
  absolute-path `Read` always works regardless of cwd.
- The file was committed under a different filename (was renamed) — try
  without the path filter: `git log --all --oneline --grep="session_NN"`
- The file was never committed (only exists on someone else's local
  worktree, never pushed) — you can't recover it via git
- The path is wrong — double-check with `git ls-tree -r origin/<branch> --
  | grep -i <keyword>`

After you confirm the branch holding the file, proceed to Step 1 below if
you need it on disk; or just `git show <branch>:<path>` repeatedly if
read-only access is sufficient.

### Variant — extract a clean main-bound PR from a shared / parallel-active branch

Added 2026-06-30 (v1.2.0). **Different goal** from the rest of this skill: not
"unblock a consumer session", but "land a *mergeable subset* of my work onto
`main`" when my commits sit on a branch I can't cleanly PR — because it's
**shared with an active parallel session** and/or tangled with DO-NOT-MERGE
content. The instinct to `git checkout -b new-branch origin/main` in the
current worktree is a **trap**: that branch-switch yanks every file out from
under the parallel session working in the same worktree.

Trigger: (1) your doc/code work is committed on branch X; (2) X is shared with
another live session (its `git status` shows their uncommitted WIP; `git log`
shows their unpushed commits) OR X is a DO-NOT-MERGE branch; (3) you want only
a clean, reviewed subset on main.

```bash
# 1. NEVER `git checkout` a new branch in the shared worktree. Spin a throwaway
#    worktree off origin/main instead (isolated; parallel session untouched):
git fetch origin
git worktree add /path/to/throwaway -b docs/clean-subset origin/main

# 2. From the throwaway worktree, pull ONLY the safe subset from branch X:
cd /path/to/throwaway
git checkout X -- docs/reviews/foo.md docs/handoffs/bar.md docs/deliverables/baz/
git status --short | grep -iE 'gated|other-session-dir' && echo LEAK   # sanity: no gated/parallel content

# 3. Commit, push the throwaway branch, PR --base main, review, merge.
git commit -m "..."; git push -u origin docs/clean-subset
gh pr create --base main ...

# 4. Cleanup AFTER merge. `gh pr merge --delete-branch` FAILS its local step
#    when main is checked out in another worktree ("'main' is already used by
#    worktree at ...") — but THE MERGE STILL SUCCEEDED. Finish cleanup manually:
gh api -X DELETE repos/<owner>/<repo>/git/refs/heads/docs/clean-subset   # remote ref
cd /any/other/worktree
git worktree remove /path/to/throwaway --force
git branch -D docs/clean-subset
```

Why a throwaway worktree (not `git show <branch>:<path>` or editing in place):
you need the files **on disk, staged, on a branch off main** to open a PR; and
you must not disturb the shared worktree. The throwaway isolates both. Leave
the shared branch's push to the parallel session (pushing it would also push
their unpushed commits). See also [[parallel-session-coedit-via-source-mtime-and-idempotent-rebuild]].

### Step 1 — confirm the diagnosis

From inside session B's worktree:

```bash
# Is the file on disk here?
ls path/to/the/file 2>/dev/null && echo "present" || echo "missing"

# What branches contain commits touching this path?
git log --all --oneline -- path/to/the/file | head -5

# Does B's current branch include any of those commits?
git merge-base --is-ancestor <commit-from-log> HEAD && echo "in B" || echo "not in B"
```

If "missing" + commits exist on a branch + that branch is not an ancestor
of B → confirmed.

### Step 2 — pull the files into B's working tree

From inside B's worktree (cwd is B's checkout):

```bash
git checkout <producing-branch> -- \
  path/to/file-1 \
  path/to/file-2 \
  path/to/directory/  # trailing slash works for whole dirs
```

This is `git checkout <tree-ish> -- <path>`. It:

- Brings the file contents from `<producing-branch>` into B's working tree.
- Stages the additions/modifications (visible in `git status` as "Changes
  to be committed").
- Does **not** switch branches, does **not** create a merge commit, does
  **not** affect any other file in B's tree.
- Works without a fetch when both branches are local (both worktrees share
  `.git`).
- Works for both files and directories. For directories, every file under
  the directory at that commit is pulled in.

### Step 3 — if the file is gitignored, add an exception

If the file you're pulling in is gitignored (common for HTML mockups in a
repo whose `.gitignore` has a blanket `*.html`), the checkout still works
(it brings the bytes into the working tree), but the file shows as
*staged-add despite being ignored* — slightly confusing. To track it
going forward:

```bash
# Find the ignore rule
git check-ignore -v <path>
# .gitignore:N:*.html	docs/plans/.../foo.html

# Add an exception. Don't broaden too far — scope to the design directory.
echo "!docs/plans/**/*.html" >> .gitignore
```

Then commit `.gitignore` together with the checked-out files so future
edits stay tracked.

### Step 4 — commit on B's branch

```bash
git add .gitignore  # if you added an exception
git commit -m "import spec + mockups from worktree-spec-A for design pass"
```

The spec now lives on B's branch too. When B's PR eventually opens, it
includes both the spec it consumed and the design it produced — single
self-contained PR. (If A's branch later also opens a PR with the same
files, GitHub's squash-merge will deduplicate cleanly.)

## Verification

- `ls <path>` from B's worktree now lists the file.
- `git status` shows the files as "Changes to be committed: new file: ..."
  (or "modified" if they existed at older content).
- The consuming Claude Code session (B) can `Read` the files without
  "file not found" errors.

## Example

This session:

```
.claude/worktrees/session13-resume/   ← session A (producer)
  branch: worktree-session13-resume
  HEAD: 303da93 docs(ui): vibe mockups + gitignore exception
  files: docs/plans/2026-05-26-brief-runner-ui-v2-{design,handoff-prompt}.md
         docs/plans/2026-05-26-vibe-mockups/{index,option-a,option-b,option-c}.html

/Users/<user>/Documents/the-handover-repo/   ← session B (consumer)
  branch: feat/brief-runner-ui-mockup-v2 (branched from main = 755e042)
  HEAD: 755e042 — does NOT include any of A's commits

  Symptom: session B's frontend-design pass reported
  "The referenced design spec and visual anchor files don't exist."
```

Unblock from B's worktree:

```bash
cd /Users/<user>/Documents/the-handover-repo
git checkout worktree-session13-resume -- \
  docs/plans/2026-05-26-brief-runner-ui-v2-design.md \
  docs/plans/2026-05-26-brief-runner-ui-v2-handoff-prompt.md \
  docs/plans/2026-05-26-vibe-mockups/ \
  .gitignore
git status   # all five files staged
```

Session B's frontend-design pass now reads the files and proceeds.

## Notes

- **Local-only branches work too.** Because both worktrees share `.git`,
  you don't need to push the producer branch to origin first. (Pushing is
  still a good idea if anyone else needs the work, or if you'll open a PR
  later — but it's not required for the cross-worktree handoff itself.)
- **Don't `git checkout <branch>` (no `--`)** — that switches branches in
  B's worktree and loses B's in-progress work. The `--` is the critical
  delimiter that makes it a path-restoration, not a branch-switch.
- **Order matters for big handoffs**: pull `.gitignore` first (so newly
  imported HTML files aren't surfaced as "ignored" oddities in git
  status), then the spec / mockup files.
- **Subagents spawned by B** also need the files visible in B's cwd — the
  checkout has to happen before they're dispatched. If a subagent already
  failed with "file not found", do the checkout in the parent session and
  redispatch.
- **Alternative when you don't want it on B's branch yet**: use
  `git show <branch>:<path>` to print a file's content without modifying
  the working tree. Useful for one-off "let me see what A's spec says"
  but doesn't help if B's subagents need to `Read` the file (they'd need
  it on disk).
- **Distinct from `claude-design-handoff-bundle`**: that skill is for
  fetching gzipped tar bundles from `claude.ai/design` URLs (a different
  artefact-transfer mechanism, between Claude Design and Claude Code).
  This skill is local: between two Claude Code sessions in different
  worktrees of the same repo.

## References

- `git checkout <tree-ish> -- <paths>`: see
  [git-checkout(1)](https://git-scm.com/docs/git-checkout) — "Checkout
  paths out of the index or out of another commit." Modern git also
  exposes this as `git restore --source=<branch> <paths>`; both work,
  `checkout` is more widely understood.
- Related: [[multi-worktree-file-url-stale-content]],
  [[subagent-bash-cd-wrong-worktree]],
  [[worktree-outer-ls-mistaken-for-main-state]],
  [[brainstorm-html-mockup-with-design-tokens]],
  [[claude-design-handoff-bundle]].
