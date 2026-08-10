---
name: synthetic-id-collision-rebase
description: |
  Fix the "I claimed cat7-7bg, they claimed cat7-7bg, theirs merged first" failure
  mode when rebasing a PR after parallel sessions land mid-flight. Use when:
  (1) rebasing a stale PR onto current main produces a conflict in an append-only
  register file (tracker entries, ADR `NNNN-` prefixes, migration filenames, OpenAPI
  operationIds, error codes, lessons.md `## N.` numbering), (2) BOTH your branch
  and a freshly-merged branch added an entry under THE SAME synthetic ID — the
  collision is namespace, not just text, (3) plain "accept both sides" yields two
  rows with identical IDs that violate the file's invariant, (4) multiple Claude
  Code sessions share a working tree and each picked "next free letter" from their
  local view of the file. Prescribes a reroll workflow: scan ALL taken IDs in
  current main, pick truly-next-free, replay only your entry under the new ID,
  regenerate any derived artifacts (site, indexes), force-push. Also covers the
  variant where git splits the conflict boundary mid-argument-list of a multi-line
  Python function call, leaving an orphaned partial call that causes a SyntaxError
  far from the conflict site — requires ast.parse() verification after resolution.
author: Claude Code
version: 1.1.2
date: 2026-05-13
disable-model-invocation: true
---

# Synthetic ID Collision During Multi-Session PR Rebase

## Problem

You opened a PR that adds an entry to an append-only register — `Item("cat7-7bg", ...)` in a roadmap tracker, `0017-foo.md` ADR, `V025__add_index.sql` migration, `## 144. ...` in `lessons.md`, `errcode: "E_QUOTA"` in an error catalog. You picked the ID by reading the file and grabbing the next free slot.

Meanwhile, a parallel session — or a co-author, or your own work in another worktree — also picked the same ID. **Their PR merged first.** Now your PR is `mergeable: CONFLICTING / DIRTY`, and even after reading their version, the conflict isn't really about content alignment — it's that **the synthetic ID itself is taken**. A 3-way merge that "accepts both sides" produces two rows with identical IDs, which violates the file's primary key.

This is a particularly nasty failure because:
1. The conflict resolution `--theirs` keeps their entry under the ID you wanted; your work is silently dropped.
2. The conflict resolution `--ours` overwrites their already-merged entry; your work shows up under their ID, blowing away their data.
3. The naive "merge both" appends two `cat7-7bg` rows; tooling that keys on the ID picks the first, hides the second.

## Context / Trigger Conditions

All four hold:
1. Your PR is conflicting after a mid-flight merge from another branch (often: another Claude Code session sharing the same working tree).
2. The conflicting file is an **append-only register** keyed by a synthetic ID, where the ID is supposed to be unique. Common patterns:
   - Roadmap/backlog trackers: `Item("cat7-7bg", ...)`, `Item("cat7-7bh", ...)`
   - ADRs: filename prefix `NNNN-` (`0016-foo.md`, `0017-bar.md`)
   - DB migration files: `V025__create_users.sql`, `V026__add_index.sql`
   - Sequential lessons: `## 142. ...`, `## 143. ...` in `lessons.md`
   - OpenAPI operationIds, GraphQL error codes, feature flags with sequential names
3. `git diff origin/main...HEAD -- <file>` shows your block adding the same ID their already-merged block adds. (3 dots — from the merge-base, so you see what YOUR branch adds, not everything that differs between the two tips.)
4. The file has a derived/regenerated artifact (HTML site, sphinx index, README badge, openapi.json) that was also touched on both sides — meaning the regenerator runs on whichever wins the merge.

## Solution

**Reroll your ID. Don't try to resolve in-place.**

### Step 1 — Confirm the namespace collision

After `git fetch origin main && git rebase origin/main`, when conflict surfaces:

```bash
# Show your ID + theirs in the conflict block
git diff --name-only --diff-filter=U   # which files conflict
grep -n "<<<<<<<\|=======\|>>>>>>>" <register-file> | head -20
```

If you see your `Item("cat7-7bg", ...)` and their `Item("cat7-7bg", ...)` in the same conflict hunk under the same key, you have a namespace collision, not a content collision.

### Step 2 — Find the truly-next-free ID on current main

```bash
# For tracker/Item-style files
grep -oE "cat7-7b[a-z]" docs/generate_roadmap_backlog.py | sort -u
# Pick the next letter alphabetically: if ..bj is taken, you take bk

# For ADR files
ls docs/decisions/ | grep -oE "^[0-9]{4}" | sort -u | tail -3
# Pick max+1

# For migrations
ls db/migrations/ | grep -oE "^V[0-9]+" | sort -V | tail -3

# For lessons.md
grep -E "^## [0-9]+" .claude-memory/lessons.md | tail -3
# Pick max+1
```

**Critical:** scan the file as it exists on current `main`, NOT your local pre-rebase view. Your local thinks `bg` is free; main says `bg` through `bj` are all taken now.

### Step 3 — Abort the rebase, reset clean, replay your entry under the new ID

The cleanest path is to reset to current main and cherry-pick only the substantive part of your change, then re-apply the register entry under the new ID as a separate commit.

```bash
git rebase --abort                                      # back out of the conflict
git reset --hard origin/main                            # clean slate
git cherry-pick <your-substantive-commit-sha>           # the actual feature/doc work
# Now manually add the register entry under the NEW ID, regenerate derived artifacts
# (site/index/openapi.json/etc.), commit as a fresh "tracker reroll" commit.
```

If your branch had multiple commits, cherry-pick each substantive commit, then add ONE final "tracker reroll" commit that puts the register entry under the new ID + regenerates derived artifacts.

### Step 4 — Regenerate derived artifacts against the new state

The site/HTML/openapi/index file regenerator must run against the post-rebase state, not the pre-rebase state. The file SHA pre-regen will mismatch what's on main even if your register entry's content is identical:

```bash
python3 docs/generate_website.py             # tracker → site
# or whatever the project's regen command is
git add docs/generate_roadmap_backlog.py docs/site/
git commit -m "chore(tracker): add <new-id> for <feature> (PR #N reroll)"
```

### Step 5 — Force-push and refresh the PR description

```bash
git push --force-with-lease origin <branch>
gh pr edit <N> --body "$(cat <<'EOF'
... existing summary ...

## Status — rebased <date>
This branch was rebased onto origin/main after PR #<X> shipped <feature> and
took the original <id>. Re-rolled to <new-id>. New 2-commit history:
1. <SHA> — the substantive change (untouched)
2. <SHA> — fresh register entry (<new-id>) + derived-artifact regen
EOF
)"
```

`--force-with-lease` (not `--force`) prevents stomping any push that another session may have made to your branch in the meantime.

### Step 6 — Verify and merge

```bash
gh pr view <N> --json mergeable,mergeStateStatus
# Expect: MERGEABLE / CLEAN
gh pr merge <N> --squash --delete-branch
```

## Verification

- `gh pr view <N>` returns `mergeable: "MERGEABLE"`, `mergeStateStatus: "CLEAN"`
- The merged main contains BOTH your entry (under the new ID) AND the parallel session's entry (under the original ID); neither overwrote the other
- The regenerated artifact (site/index/etc.) reflects both entries; tooling that keys on the synthetic ID returns 1:1 mapping with no duplicates
- `grep -c "<new-id>" <file>` returns 1 (or however many references you intended)

## Example

This session, 2026-04-27:

- Opened PR #118 with `cat7-7bg` for "S108 docs+tests carry-over" at 15:11 UTC
- Parallel session opened a different PR with `cat7-7bg` for "S108 Run 2 + FERPA fix" — merged first at 14:29 UTC
- Subsequent PRs took `cat7-7bh` (Streamlit decommission), `cat7-7bi` (deposit-optional), `cat7-7bj` (S108 handoff) on main
- Rebased PR #118 → conflict on `Item("cat7-7bg", ...)` block + 3 site files
- Reset to origin/main, cherry-picked substantive commit (4 docs/test files), added new commit with `cat7-7bk` + regenerated `docs/site/{index,roadmap}.html`
- Force-pushed → CLEAN → merged

End state: main has `cat7-7bg` (parallel session's work), `cat7-7bh`/`bi`/`bj` (subsequent sessions), `cat7-7bk` (mine). All entries preserved, all distinct IDs, regenerated site reflects all of them.

## Variant: Mid-Argument-List Conflict Split (Python multi-line calls)

When the conflicting file is a Python source file with multi-line function calls (e.g., a tracker list of `Item("cat7-7ks", "label", ...)` entries), git's conflict boundary can split inside a single call's argument list rather than between calls.

**What happens:**

Both branches append `Item("cat7-7ks", ...)` near the same location. git's `=======` separator falls between the two new entries, but the *next* existing item's first line (`Item("cat7-7kr", "S196 — ..."`) appears in **both** the HEAD section and the incoming section (git included it as shared context on each side). A naive "take both sides" regex resolution outputs:

```
Item("cat7-7kt", ...)   # your renumbered entry — correct
Item("cat7-7kr",        # orphaned first line — NO arguments, NO closing paren
Item("cat7-7kt", ...)   # duplicate — wrong
Item("cat7-7kr", "S196 — ...", ...)  # the real full entry — correct
```

The `SyntaxError` this produces manifests at the **list-close bracket** (`]`) many lines later, not at the broken line — because Python sees an unclosed `(` started by the orphan.

**Detection:**

```bash
python3 -c "
import ast, sys
with open('docs/generate_roadmap_backlog.py') as f:
    src = f.read()
try:
    ast.parse(src)
    print('OK')
except SyntaxError as e:
    print(f'SyntaxError at line {e.lineno}: {e.msg}')
"
```

Always run `ast.parse()` after resolving conflicts in Python files — the SyntaxError line number points at the list-close, not the orphan. The orphan is the first `Item("cat7-7kr",` line immediately followed by the next `Item(` without any argument lines between them.

**Fix:**

Scan for the orphaned line pattern and delete it:

```bash
# Find: Item("cat7-7kr", immediately followed by Item("cat7-7kt", (no args in between)
grep -n 'Item("cat7-7kr"' docs/generate_roadmap_backlog.py
# Visually confirm the next non-blank line is Item("cat7-7kt", not an argument
# Then delete the orphan line, re-run ast.parse(), regenerate site
```

**Key insight:** git includes the first line of the *shared context after the conflict block* in both conflict sides. Any "take both sides" strategy without per-line argument-count validation will duplicate that shared line.

**Prevention (pre-rebase):** If your new `Item(...)` and the incoming `Item(...)` land adjacent in the file, rename your ID in a separate commit before rebasing (changes the exact insertion point, so git's conflict boundary shifts away from the argument-list interior). The `pr-conflict-site-regen` skill's Step 2a/2e covers the renumber; the cleanest path is to abort early and pre-rename.

## Notes

- **Root cause is shared working tree.** Multi-session work without `claude --worktree <name>` (Claude Code) or equivalent worktree isolation creates this exact failure mode. The recovery here is the symptomatic fix; the structural fix is per-session worktrees.
- **The collision is invisible until merge time.** Both sessions' local view of the file shows their ID as "next free." Only when one merges first does the other's ID become unavailable. There's no useful pre-merge linter for this — the truth lives on origin/main.
- **Append-only registers are vulnerable; replace-style files are not.** A YAML config edit doesn't have this issue because the same key on both sides naturally 3-way-merges. Sequential ID assignment is what creates the namespace.
- **For ADR-style files (one ADR per filename), the collision is at the filesystem level**: `0017-feature-A.md` from your branch + `0017-feature-B.md` from theirs both want to exist as the 17th ADR. Resolution is the same: rename yours to `0018-feature-A.md`.
- **For lessons.md sequential numbering**: if you're at `## 144` and they shipped `## 144` first, you become `## 145`. The reroll edit is in one place but you may need to update cross-references (`L-S108-144` → `L-S108-145`) elsewhere.
- **See also:** `pr-conflict-from-mid-flight-merges` skill covers the broader recipe for any mid-flight-merge conflict; this skill specializes the namespace-collision case where the file conflict isn't really about content.

## References

- Companion skill: `pr-conflict-from-mid-flight-merges` — in this same plugin ([source](https://github.com/wan-huiyan/agent-traffic-control/blob/main/plugins/agent-traffic-control/skills/pr-conflict-from-mid-flight-merges/SKILL.md))
- Parallel-session-isolation root-cause fix: Claude Code's built-in `claude --worktree <name>` flag (avoids shared-working-tree race conditions entirely)
