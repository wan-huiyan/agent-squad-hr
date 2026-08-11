---
name: worktree-outer-ls-mistaken-for-main-state
description: |
  Prevent citing files as "on main" when they actually live only in a sibling
  worktree's working tree. Use when (1) you're working inside a worktree at
  `<repo>/.claude/worktrees/<X>/` and need to verify whether a file or feature
  is on `origin/main`, (2) you're tempted to run `ls /path/to/outer-repo/...`
  or `find /path/to/outer-repo` to check, (3) you're about to cite that
  filesystem-walk result in a PR description, handoff doc, or commit message
  as if it represented main's state. Trap: in a multi-worktree setup, the
  outer repo's working tree is on whatever branch the user (or another
  session) last checked out — which can be ANY sibling worktree's feature
  branch, never guaranteed to be main. Running `ls` on the outer dir lists
  THAT branch's files, not main's. A handoff doc that says "X is on main" or
  "X was written by session S" based on outer-`ls` evidence will fail a
  reviewer's dead-reference check and ship a fabricated claim. v1.1 adds the GIT-STATUS
  variant: the same frame inversion bites `git diff` / `git status` / `git log` run after a
  `cd` into the base/outer repo — git reports the BASE working tree (a different branch with
  its own uncommitted edits), so your worktree's changes appear to VANISH and you wrongly
  conclude a parallel session reverted your work. Run git from your worktree (or `git -C
  <worktree>`); never `cd` to the base repo to inspect state.
author: Claude Code
version: 1.1.0
date: 2026-06-22
disable-model-invocation: true
---

# Worktree: Outer-`ls` Mistaken for Main-State

## Problem

You're working inside a git worktree at `<repo>/.claude/worktrees/<branch>/`.
You need to verify whether some file (e.g., `docs/handoffs/session_184_X.md`)
exists on `origin/main` — perhaps because:

- You're writing a handoff doc and want to cite "the canonical S184 prompt that's already on main"
- You're filing a PR body and want to confirm the file you're referencing actually exists
- You're cross-checking a claim from MEMORY.md against current main

The natural-feeling check is:

```bash
ls /Users/.../repo/docs/handoffs/ | grep session_184
# → session_184_drivers_breakdown_full_sweep_prompt.md
```

You walk up out of the worktree, list the outer repo's `docs/handoffs/`, see
the file, and cite it as "on main". **That conclusion is wrong** in any repo
with multiple worktrees in use.

## Context / Trigger Conditions

All four must be true to fire this trap:

1. The repo has **2+ active worktrees** (`git worktree list` shows >1 entry)
2. You're cwd-anchored inside one worktree (e.g., `.claude/worktrees/<X>/`)
3. You need to verify a claim about `origin/main`'s state
4. You reach for a **filesystem traversal command** (`ls`, `find`, `cat`, `tree`)
   on the outer repo's path instead of a git plumbing command

The outer working tree's `HEAD` can be on:
- The literal `main` branch (only if no one explicitly switched it)
- A sibling worktree's feature branch (if someone ran `git checkout <feature>` in the outer dir)
- A stale committed-but-not-pushed branch from days ago
- The branch of whichever worktree was created most recently — git sometimes resets the outer
  HEAD as a side effect of `git worktree add`

You cannot tell which from a casual `ls`. Concrete failure mode observed in S184b
(2026-05-12, PR #778): handoff doc cited `session_184_drivers_breakdown_full_sweep_prompt.md`
as "on main, unconsumed" based on outer-`ls`. The reviewer ran `git ls-tree origin/main`
and proved the file did not exist on main — it lived only in a sibling worktree's working
tree. Three textual mentions had to be rewritten before the PR could merge.

## Solution

### Step 1: Stop reaching for `ls` on the outer repo path

When the question is "does X exist on main?", `ls` is the wrong tool. The outer working
tree is just another working tree — its state is no more canonical than yours.

### Step 2: Use git plumbing against the explicit ref

```bash
# Does docs/handoffs/session_184_X.md exist on origin/main?
git ls-tree --name-only origin/main docs/handoffs/ | grep session_184

# What's the content of that file on main?
git show origin/main:docs/handoffs/session_184_X.md

# All files in a directory on main:
git ls-tree --name-only origin/main docs/handoffs/

# Listing across all refs (when you don't care WHICH branch, just whether it exists anywhere):
git log --all --oneline -- docs/handoffs/session_184_X.md
```

Always `git fetch origin main --quiet` before this audit so the local `origin/main` ref is
current — otherwise you're checking against a stale snapshot.

### Step 3: Don't conflate "exists somewhere" with "on main"

`git log --all` is great for "is this file anywhere git has ever seen?" but a hit doesn't
mean main has it. If the answer to "where does it live?" matters, follow up with:

```bash
git branch -a --contains $(git log --all --format='%H' -- docs/handoffs/session_184_X.md | head -1)
# Lists every ref that has the commit that introduced the file.
```

If `origin/main` is not in that list, the file is NOT on main — even if your outer-repo `ls`
showed it.

### Step 4: Pre-PR sanity check on any handoff/PR citing files "on main"

Before pushing a handoff doc or PR body that asserts "<file> is on main" / "<file> was written
by session S" / "<file> exists in repo":

```bash
# Extract every cited path
grep -oE 'docs/[a-zA-Z0-9_/-]+\.(md|py|sqlx|html|json)' your_doc.md \
  | sort -u \
  | while read path; do
      git ls-tree --name-only origin/main "$path" >/dev/null 2>&1 \
        && echo "✓ on main: $path" \
        || echo "✗ MISSING on main: $path"
    done
```

Anything `✗ MISSING` either needs a real annotation ("this file lives on a non-main branch
in worktree Y; recover with `git show <branch>:<path>`") or removal.

## Verification

```bash
# Before fixing
ls /path/to/outer-repo/docs/handoffs/ | grep session_184
# Shows session_184_drivers_breakdown_full_sweep_prompt.md

# Truth
git ls-tree --name-only origin/main docs/handoffs/ | grep session_184
# Returns nothing — file is NOT on main

# Where it actually lives
git log --all --oneline -- 'docs/handoffs/session_184_*' 2>/dev/null | head -3
# If no commits printed: file is in some worktree's working tree but never committed.
# Otherwise: lists the branch(es) that committed it.
```

## Example

In S184b (2026-05-12), while writing `session_184b_campaign_pre_launch_zeros_handoff.md`,
I needed to characterize the relationship to the canonical S184 session. I ran:

```bash
ls /Users/<user>/Documents/the-project-repo/docs/handoffs/ | grep 184
# → session_184_drivers_breakdown_full_sweep_prompt.md
```

…and wrote in the handoff: "canonical S184 drivers-breakdown sweep prompt at
`session_184_drivers_breakdown_full_sweep_prompt.md` on main, unconsumed."

PR #778 code-review caught it:

> Sibling reference is broken: `docs/handoffs/session_184_drivers_breakdown_full_sweep_prompt.md`
> exists neither on main nor in the worktree. The handoff cites it 3 times as "on main,
> unconsumed" / "written by S183" — that file does NOT exist anywhere reachable.

Verification with `git ls-tree`:

```bash
git ls-tree --name-only origin/main docs/handoffs/ | grep -i "184\|drivers" | head
# session_107a_topdrivers_handoff.md
# session_110_topdrivers_triple_fix_handoff.md
# (no session_184_*)
```

The file existed only in a sibling worktree's working tree (the outer-repo path's `HEAD`
had been switched to that sibling's branch at some point). Fix: rewrite the 3 mentions to
describe S184 as "an unrelated parallel drivers-breakdown stream running in a sibling
worktree, no artifact on main yet" — drop the specific filename, drop the "on main" claim.

Recovery commit: `fc4d523f` on `docs/s184b-summer-wow-handoff`; merged via PR #778.

## Notes

- **The skill applies to subagents too.** If you dispatch a subagent and ask "find files on
  main matching X", the subagent will instinctively `ls` the outer repo unless you brief it
  to use `git ls-tree origin/main`. Spell it out in the agent prompt.
- **`gh ls-tree` doesn't exist** — but `gh api repos/<owner>/<repo>/contents/<path>?ref=main`
  works as a remote-only fallback when you can't trust the local `origin/main` ref freshness.
  Heavier than `git ls-tree`; only use when offline-from-local-git.
- **CI catches some but not all instances.** GitHub Actions running from `actions/checkout@v4`
  fetches `merge_commit_sha`, not main — file-existence asserts in CI that use plain `[ -f ]`
  in the workflow may not catch this class. Verification belongs in handoff-doc review (per
  `session-handoff` v1.6 Phase 4 step 22 dead-reference check), not in CI.
- **Why git's `worktree add` can switch outer HEAD**: when you `git worktree add ../other
  some-branch`, the outer working tree keeps its current branch UNLESS the user ran a
  `git checkout` in the outer dir at some point. The instability comes from human action,
  not git itself — but the human action is invisible to a session that joined later.

## Variant — `git diff/status/log` run from the BASE repo shows ITS working tree, not yours (v1.1)

The same frame inversion bites with **git status commands**, not just `ls` — and it's scarier
because your own uncommitted work appears to **vanish**. From inside a worktree, if you
`cd /path/to/base-repo && git diff` (or `git status` / `git log`), git reports the **base
repo's** working tree — which is parked on some *other* branch with *its own* uncommitted edits.
Your worktree's staged changes aren't there; an unrelated file you never touched IS there. The
instinctive read is "a parallel session reverted my work / detached my HEAD."

**Worked case (the project drawer, 2026-06-22).** Mid-fix I ran `cd /…/the-project-repo && git diff --stat`
to review my change. It showed only an unrelated `docs/deliverables/...s207...html` edit and
NONE of my `bq_queries.py`/test changes → momentary "did my work get reverted?!" panic. Cause:
the `cd` jumped to the **base** checkout (a different branch with its own dirty file); my changes
were intact in the **worktree** the whole time. Running `git status -sb` *from the worktree* (no
`cd`) showed both my modified files correctly.

**The discipline:**
1. **Run git from your worktree — never `cd` to the base/outer repo to inspect state.** Each
   worktree has its own index + HEAD; git always reports *the working tree of the cwd*.
2. **A "my changes disappeared" result after a `cd` is almost always wrong-cwd, not data loss.**
   Before concluding a parallel session reverted you, check `git rev-parse --show-toplevel` and
   `git branch --show-current` — confirm you're in the worktree, not the base repo.
3. **Prefer `git -C <worktree-path> …`** over `cd` when you must target a specific tree, so the
   cwd never silently changes which working tree git reads. (In this harness the Bash cwd also
   resets between calls, compounding the confusion — see `main-bash-cwd-persists-nested-worktree`.)

## See Also

- `subagent-bash-cd-wrong-worktree` v1.0.0 — sister: `cd` doesn't persist between Bash calls in
  subagents; commits land on the outer working tree's branch instead of the worktree's branch.
  Different mechanism (cd state) but same root cause (multi-worktree disorientation).
- `session-handoff-number-collision-with-unmerged-sibling` v1.1.0 — picking the wrong session
  NUMBER because a sibling's same-numbered handoff isn't on main yet. Same family (parallel-
  worktree state confusion); different trigger (which-N-do-I-use vs does-file-X-exist).
- `worktree-historical-test-replay-missing-dirs` — replaying historical tests in a worktree
  misses dirs that are only on newer commits. Same "outer-vs-current" frame inversion.
- `flask-debug-cross-worktree-edit-stale` — Flask reloader picks up edits from another worktree
  via shared module imports. Sibling problem at the runtime layer.
- `using-git-worktrees` — broader worktree workflow guidance, doesn't focus on the
  filesystem-walk trap.
