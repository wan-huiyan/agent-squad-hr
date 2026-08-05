---
name: dispatched-bash-agent-git-checkout-clobbers-uncommitted-edit
description: |
  A verification/review/audit subagent YOU dispatched (Workflow agents, Explore,
  general-purpose, code-reviewer — anything with Bash) runs a file-level
  `git checkout <path>` / `git restore <path>` / `git stash` to compare your work
  against HEAD, and silently REVERTS your uncommitted working-tree edit in the
  shared worktree. The agent then reports that edit as "missing / not persisted /
  blocker", and sibling agents pile onto the phantom. Use when: (1) a review or
  verification agent reports a file/entry/line you KNOW you just wrote is "missing",
  "not in the file", "not persisted", or "only in the diff not the file"; (2) its
  evidence cites "a subsequent git checkout shows…" or "git diff shows it but the
  working tree doesn't"; (3) a harness "file was modified, either by the user or by
  a linter" reminder names a file you edited but didn't touch since; (4) your own
  passing test suite REQUIRES the thing the agent says is missing (the decisive
  tell — if tests that need it passed, it WAS there). Prevention: commit (or stash
  to your own ref) BEFORE dispatching Bash-capable agents onto a shared worktree.
  ALSO covers the SELF-INFLICTED variant: YOU run `git checkout -- <file>` / `git
  restore <file>` to RESTORE a source file after a mutation test (deliberately
  breaking a guard to prove a test reddens, then reverting) — but the file had
  UNCOMMITTED edits you needed to keep, so the checkout silently discards them and
  reintroduces failures. Safe only when the file is clean-vs-HEAD; if it has
  uncommitted edits, back up with `cp` (restore from the copy) or `git stash`.
author: Claude Code
version: 1.1.0
date: 2026-06-08
disable-model-invocation: true
---

# A dispatched Bash agent's `git checkout` reverts your uncommitted worktree edit

## Problem

You dispatch one or more Bash-capable subagents (a `Workflow` fan-out, `Explore`,
`general-purpose`, `code-reviewer`, etc.) to review/verify work in the **same git
worktree** where you have **uncommitted edits**. An agent, investigating "is X
present / persisted?", runs a **file-level** git command to compare against HEAD:

```
git checkout analysis/SQL/foo.toml     # or: git restore <path> / git stash
```

This reverts your uncommitted edit to that file back to HEAD. The agent then reads
the reverted file, finds your change gone, and reports a **false "missing / not
persisted / blocker"** finding. In a multi-agent review, other agents reading the
same now-reverted file repeat the phantom — so a majority can "fail" on something
that was actually correct and committed-in-spirit.

This is distinct from its siblings:
- `concurrent-session-checkout-clobbers-shared-worktree` — an *unknown* session
  flips the *branch* (`git checkout <branch>` / `git switch`). Here the clobberer
  is *an agent you dispatched* running a *file-level* checkout/restore/stash.
- `subagent-read-stale-worktree-needs-head-pin` — read agents return stale data
  from the *wrong worktree* (no mutation). Here a single shared worktree is
  *mutated* underneath you.

## Context / Trigger Conditions

- A review/verification agent's finding says a change you made is "missing", "not
  in the file", "not persisted", "appears in git diff but not the working tree".
- The agent's own evidence mentions running `git checkout`/`git restore`/`git stash`
  or "git diff vs file content mismatch".
- A `git status` you run afterward shows a file you edited is **no longer modified**
  (it silently reverted), often with a harness *"file was modified, either by the
  user or by a linter"* reminder.
- **Decisive tell:** your test suite that *requires* the supposedly-missing change
  **passed** before you dispatched the agents. Passing tests that need X prove X
  was present; the agent's git op reverted it after the fact.

## Solution

1. **Don't trust the "missing" verdict — verify the current file state yourself:**
   `grep -c "<the thing>" <file>` and `git status --short`. If it's gone from a
   file you edited but didn't revert, an agent clobbered it.
2. **Re-apply the reverted edit** (recover from your conversation context — the
   content is never lost, only the working-tree state).
3. **Re-run the suite** to confirm green again, then **commit immediately** (stage
   explicit paths; `git add` any new untracked files the agents flagged).
4. **Triage the rest of the review honestly:** separate the *phantom* findings
   (all rooted in the clobbered file) from any *genuine* ones. Agents that ran
   actual code (e.g. executed the function, not just `git checkout`) are more
   trustworthy than agents whose evidence is a git comparison.

### Prevention (the real fix — sequencing)

- **Commit (or `git stash` to your own ref) BEFORE dispatching any Bash-capable
  review/verification agents onto a shared worktree.** Committed work cannot be
  clobbered by a file-level checkout. This is the cheap, reliable fix.
- Or **isolate**: give the agents a separate worktree/copy (`Agent`/`Workflow`
  `isolation: "worktree"`), or restrict them to read-only tools (no Bash) so they
  cannot run git mutations.
- If you must review uncommitted work in place, explicitly instruct the agents:
  "do NOT run `git checkout`/`git restore`/`git stash`/`git reset` — read the
  working-tree files as-is."

## Variant: self-inflicted — `git checkout` to restore a mutation test (v1.1.0)

No subagent involved. To prove a test genuinely binds, you **mutation-test**: break a
guard in a source file, run the test, confirm it reddens, then **restore** the file:

```
# break the guard, run the test (expect RED), then:
git checkout -- bake_monitor.py     # "restore" — but this reverts to HEAD, not to
                                     # your pre-mutation working-tree state
```

`git checkout -- <file>` restores the file to **HEAD (the last commit)**, NOT to
whatever uncommitted state it had before you mutated it. If you'd made **uncommitted
edits** to that file *after* the last commit (e.g. a fix you applied earlier in the
session but hadn't committed yet), the checkout silently discards ALL of them — and
your suite goes red again on the now-missing edits, looking like a fresh bug.

The trap is **state-dependent and intermittent**: the first few mutation tests in a
session are often safe because the file is still clean-vs-HEAD (nothing uncommitted
to lose), so `git checkout` is a perfect no-op restore. The moment you make an
uncommitted edit to that same file and *then* run another `git checkout`-based
mutation test, it clobbers the new edit. "It worked the last three times" gives false
confidence.

**Prevention — pick by what you're protecting:**
- **`cp` backup** (simplest, always correct): `cp file /tmp/bak && <mutate> && <test> && cp /tmp/bak file`. Restores the *exact* pre-mutation bytes regardless of commit state.
- **Commit first**, then `git checkout` is safe (it restores to your just-committed state).
- A throwaway in-memory/`sed`-on-a-copy mutation never touches the real file.

**Decisive tell** (same as the dispatched-agent case): a suite that *passed* moments
ago now fails on edits you know you made → `grep -c` the file → the edits are gone →
your last `git checkout`/`git restore`/`git stash` ate them. Recover by re-applying
from conversation context (the content is never lost), re-run, then commit.

## Verification

- After re-applying: `grep -c` shows your change back in the file; `git status`
  lists it as modified again; the suite is green; you've committed it.
- The clobber can't recur once committed: re-dispatching the same agents leaves
  the committed file untouched.

## Example

S28 of brief-runner: a 4-agent `Workflow` adversarially reviewed an
uncommitted PR in the shared worktree. One `Explore` agent ran
`git checkout analysis/SQL/media_mix.registry.toml` to compare a new `[[template]]`
entry against HEAD — reverting the uncommitted edit. Two of four agents then
returned `verdict: fail, "registry entry missing — git checkout shows only 2
templates"`. But the full test suite (which includes a test asserting the entry
loads and is selected) had passed at 379/11 minutes earlier — proof the entry was
there. Recovery: re-applied the registry edit, re-ran (26 → 379 green), committed,
then re-triaged: the two "fail" verdicts were phantoms; only the edge-case auditor's
findings (which ran real Python) were genuine.

## Notes

- The mechanism is `git checkout <path>` reverting a *single file*, not a branch
  switch — so `git reflog` (the concurrent-session skill's tell) shows nothing
  unusual. Diagnose via current file content vs. your passing tests instead.
- Background `run_in_background` agents can't write, but Bash-capable *foreground*
  review agents (incl. Workflow `agent()` calls) can run git mutations.
- Generalizes the prevention half of
  `concurrent-session-checkout-clobbers-shared-worktree`: when YOU are the one
  spawning the clobberer, you control the fix — commit first.

## References / See also
- `concurrent-session-checkout-clobbers-shared-worktree` — branch-switch variant by an unknown session.
- `subagent-read-stale-worktree-needs-head-pin` — read-only stale-worktree variant (no mutation).
