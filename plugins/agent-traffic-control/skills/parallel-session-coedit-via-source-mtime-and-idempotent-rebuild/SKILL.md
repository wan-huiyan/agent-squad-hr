---
name: parallel-session-coedit-via-source-mtime-and-idempotent-rebuild
description: |
  Edit a shared deliverable while another live session or a colleague's agent is editing the same
  file right now — "don't delete each other's work", "only write when the other one is finished".
  When the file is built from many per item sources by an assembler (sections into one HTML,
  slides, reports): source mtime shows which items they are on, disjoint sources cannot clobber,
  and an idempotent rebuild merges everybody's sources. Grepping the assembled build is a false
  negative test, and staging then pausing lets their commit absorb your files. Not for planning
  who edits what next session.
author: Claude Code
version: 1.2.0
date: 2026-07-01
---
# Co-editing a section-assembled deliverable alongside a live parallel session

## Problem

The user says: *"a parallel session is making active edits on the same file, so
please don't delete each other's work — maybe only write on it when the other one
is finished."* The deliverable is large and shared. The naive readings both fail:
**serialize** (do nothing until they finish — wastes the session, ignores the
user's "fan out / go fast") or **dive in blindly** (and clobber their work, which
is exactly what they warned against).

There is a third path that is fast AND safe — but only once you notice the build
model: the artifact is **assembled from per-item source files**, and the assembler
is **idempotent** (reads all sources from disk, regenerates the one output). That
changes the collision math entirely.

## Context / Trigger conditions

- User warns that another live session / agent is editing the same file; "don't
  clobber each other"; possibly "only write when the other is finished."
- The deliverable is generated: a build script (`_assemble.py`, a bundler, a
  static-site generator) inlines per-item source files (`sections/*.html`,
  partials, slides) into ONE output file. The output is a **build artifact**, not
  the source of truth.
- You need to make real edits this session without losing concurrent work.

## Solution

1. **Find the build model FIRST. Never hand-edit the assembled OUTPUT.** Locate the
   assembler and confirm the big file is generated from per-item sources. Edit the
   **source files**; the output is regenerated. (If you edit the 2 MB assembled
   HTML directly, the next rebuild by either session silently overwrites you.)

2. **Map hot/cool per item via SOURCE-FILE mtime** — this is your real-time
   ownership signal, no git needed:
   ```sh
   stat -f '%Sm %N' -t '%H:%M:%S' sections/*.html      # BSD/macOS
   # or: ls --time-style=+%H:%M:%S -l sections/*.html   # GNU
   ```
   Files touched in the last few minutes = the other session's **HOT** set; old
   mtimes = **COOL**. Re-stat right before each edit batch — the other session
   moves between cards/items quickly (a broad pass can touch 6+ files in minutes).

3. **Edit ONLY cool, disjoint source files.** Two sessions on *different* source
   files never clobber each other — last-writer-wins only bites the **same** file.
   So staying on disjoint items satisfies "don't delete each other's work" without
   serializing. Ask the user to confirm ownership at item granularity ("does the
   other session own items 1–9 and I take 10 + the analysis?").

4. **An idempotent rebuild is NON-destructive — this is the key insight.** The
   assembler reads ALL source files from disk and regenerates the output, so *any*
   session's rebuild **auto-merges everyone's saved source edits**. Your edits
   survive the other session's rebuild, and theirs survive yours — *as long as all
   edits live in the SOURCES, not the output*. You don't even have to rebuild
   yourself: the next rebuild by anyone picks up your saved sources. (Verified: my
   edits to one card survived the other session's rebuild that happened minutes
   later; that rebuild pulled my changes into the output untouched.)

5. **The only two real collision surfaces — avoid both during the active window:**
   (a) both sessions editing the **same** source file; (b) editing the **shared
   assembler/config** (e.g. reordering items in `_assemble.py`, which also
   renumbers everything). If the ask is "position X near Y," prefer a
   **cross-reference note** inside the (disjoint) source files over a physical
   reorder of the shared assembler. Defer structural reorders until the other
   session is done.

6. **Verify your edits survived.** After the other session bumps the mtime of a
   file you edited, RE-READ it to confirm your changes are intact. (The Edit tool
   also errors on stale state, so a blind edit fails safe rather than clobbering.)

7. **Rebuild only when sanctioned** ("rebuild now") — then verify the OUTPUT
   contains every session's content.

## Verification

- Rebuild cleanly: check the assembler's success line, the item/card count, and
  that all referenced assets embedded (no "missing []").
- **Confirm your content landed — strip tags AND normalize whitespace before
  grepping.** A line-based `grep "my exact phrase"` on assembled HTML gives
  **false negatives** when the phrase wraps across a source line break OR an inline
  tag (`<i>`, `<b>`) sits mid-phrase. Use:
  ```sh
  python3 -c "import re,sys; t=re.sub(r'\s+',' ', re.sub(r'<[^>]+>',' ', open(sys.argv[1]).read())); print(sys.argv[2] in t)" OUT.html "my exact phrase"
  ```
- **To decide whether a card/consideration is ALREADY present (or "missing"),
  grep + READ the SOURCE section files — NOT the assembled output.** The
  tag-stripped check above answers "does this phrase appear *anywhere* in the
  build", which is the wrong question for coverage: the build can be **stale**
  vs the sources, AND a tag-stripped scan **over-matches** when the term appears
  in an *unrelated* card (checking if the ruled-out section covered "Distance from
  campus" false-*positived* on card 09's "by distance" FA figure). So the build
  grep fails **both** ways — false-negative raw (tags/wraps), false-positive
  tag-stripped (cross-section collision). Before a handoff/plan declares a card
  missing → "go build it", confirm against `sections/*.html`. See
  `shipped-change-not-visible-deploy-vs-gate-vs-cache` (Step 0) + lessons #181.
- **Confirm the OTHER session's work is still present** in the output (grep a
  marker of their concurrent additions) — proves the rebuild merged, not lost, it.

## Example (the client dossier, 2026-06-30)

Two live sessions co-editing `decision_dossier_ENRICHED.html`, assembled from
`sections/*.html` via `_assemble.py`. `stat` showed the other session sweeping
cards 01–09 (mtimes in the last ~5 min); my targets 07/08b/10 were cool (hours
old). I edited 08b first; the other session's later rebuild (16:12) pulled my 08b
edits into the output cleanly. When they moved onto 09, I held the 09 cross-ref
until the user gave me explicit ownership of all four cards. I used cross-reference
notes (07↔09) instead of physically reordering cards (which would have meant
editing the shared `_assemble.py`). Final rebuild verified all four of my cards
**and** the other session's card-09 enrichment present; two "missing" greps turned
out to be a line-wrap and an inline `<i>` tag (false negatives), confirmed by the
tag-stripped check.

## Variant — end-of-session handoff/commit on the shared branch (session-handoff Phase 4)

When you wrap up (e.g. `/session-handoff`) while the deliverable is still co-edited
live on a **shared branch**, the handoff skill's default *"commit ALL work → open a
PR → auto-merge docs"* is **wrong** and will entangle or ship the other session's
in-progress work. `git status` on the shared worktree shows **both sessions' edits
intermixed** — there is no clean per-session diff. Invert Phase 4:

1. **Do NOT commit the co-owned deliverable.** Your source edits are saved on disk
   and the idempotent rebuild already merges them. Committing now (a) entangles the
   other session's WIP in your commit and (b) ships a half-done, often gated
   (`DO-NOT-MERGE`) artifact. Leaving the deliverable **saved-but-uncommitted** for
   the worktree owner / post-sign-off commit *is* the protocol, not a loose end.
2. **Commit ONLY your own doc artifacts** (handoff doc, next-session prompt),
   **path-staged by exact filename** — never `git add -A`/`-u`, which sweeps the
   other session's files + untracked build scripts
   (`git-add-all-sweeps-untracked-artifacts-into-commit`).
   - **The index is worktree-GLOBAL — don't stage-then-pause.** `git add` writes to
     the one shared index; if the other session runs **its** `git commit` (even a
     plain commit, no `-a`) while your files sit staged, **your staged files ship in
     ITS commit** — you never ran `git commit`. Observed 2026-07-01: path-staged
     cards 08/10 were absorbed into the parallel session's `f9e63216` ("dossier card
     1B…"). Mitigate: run `git add <paths>` and `git commit` **atomically in the same
     step**, and re-check `git diff --cached --name-only` shows **exactly your paths**
     in the instant before committing (abort if a foreign path appears). If you'd
     rather your content edits land in the *other* session's commit anyway (the owner
     is actively rebuilding that file), just leave them **unstaged** and let it fold
     them in. See `lesson_shared_worktree_staging_absorbed_by_parallel_commit` (the client
     project memory).
3. **Never push.** A shared branch usually carries the other session's **unpushed**
   commits (`git log @{u}..HEAD` shows them above origin); pushing publishes their
   work. The other session owns the push.
4. **Don't amend** a commit another session/issue may reference — add a new small
   commit (preserves the SHA your handoff/issue cited).
5. **Memory index near its size cap?** UPDATE an existing memory file (no new
   `MEMORY.md` index line) instead of adding one.
6. **File the follow-up as a labeled issue** so it's tracked independently of the
   unpushed/gated branch (the next session may start from a fresh worktree off it).
7. If docs genuinely must reach `main` now, land them via a **separate worktree off
   `origin/main`** (a "safe-docs PR" excluding the gated deliverable) — never
   branch-switch the shared/active branch.

Net (verified the client dossier 2026-06-30c): 2 path-staged doc commits, unpushed, atop
the other session's commits; every deliverable edit (yours + theirs) left
uncommitted; one labeled follow-up issue; an existing memory file updated in place.

## Notes

- The user's "maybe only write when the other is finished" is a safe *default*, not
  a hard rule — with the source/assembler model you can co-edit disjoint sources
  immediately and let the idempotent rebuild merge. Surface the coordination
  question (who owns what) rather than stalling.
- This is **filesystem coordination, not git** — no branches. Distinct from
  `shared-file-redesign-parallel-author-serial-integrate` (one orchestrator
  authoring handoff prompts / in-session fan-out) and
  `large-redesign-parallel-branch-collision-audit` (git-branch collisions).
- Worktree note: the deliverable may live in a *different* worktree than your cwd;
  edit it by absolute path there, and remember the user's `file://` URL points at
  that worktree's copy.

## See also

- `shared-file-redesign-parallel-author-serial-integrate` — single-orchestrator
  parallel authoring & serial integration (git branches / handoff prompts).
- `large-redesign-parallel-branch-collision-audit` — pre-existing branches that
  collide with a redesign's files.
- `merge-conflict-generated-files` — when the assembled output *is* tracked and
  conflicts in git.
- `session-handoff` — the Variant above inverts its Phase 4 (commit-all + PR +
  auto-merge) for a shared, live-co-edited, gated branch.
