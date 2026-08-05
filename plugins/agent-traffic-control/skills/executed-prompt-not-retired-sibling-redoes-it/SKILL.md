---
name: executed-prompt-not-retired-sibling-redoes-it
description: |
  A prompt/brief/runbook file and the index that lists it are SHARED STATE between parallel
  sessions, so finishing the work is only half of finishing: the session that executes a brief
  must retire it on BOTH surfaces, and the session that writes one must register it, or a
  sibling redoes work that already merged or never sees the file at all. Use when: (1) you are
  about to execute a brief from a handoffs/plans/runbooks directory, or an index says "take this
  one" / "next" / "live, unclaimed"; (2) you have just finished executing such a brief and are
  writing the wrap-up; (3) you just authored a new prompt for a future session; (4) an index
  line claims a row count, a "next" pick, or an unclaimed state; (5) a session reports "this was
  already done" or "the prompt would have re-derived a committed result". Symptoms: the top
  recommendation names an issue that is CLOSED or a PR that is MERGED; two or more rows both
  say "next"; the prompt file has no DONE banner though its issue is closed; `ls` of the prompt
  directory returns files with no row in the index. Checks are cheap and exact — `gh issue view
  <N> --json state`, `gh pr list --search "<prompt filename>" --state merged`, and `ls <dir>`
  diffed against the index rows. NOT for a prompt whose PREMISE merely drifted while still being
  unexecuted (that is handoff-prompt-stale-user-hint-newer-state), and NOT for concurrent writes
  to a machine-written index (that is shared-mutable-index-rmw-race-use-marker-blob-per-item).
author: Claude Code
version: 1.0.0
date: 2026-08-05
disable-model-invocation: true
---

# An executed prompt nobody retired: the next session redoes merged work

## Problem

A repo keeps session briefs in `docs/handoffs/` with an index, `next_session_prompt.md`, whose
table says which are live. Sessions run in parallel and pick their work off that table.

Session A executes `2026-08-05-registered-scope-drift.md` in full: the analysis lands, a ruling
is committed, the issue is closed, the PR merges. Session A writes an excellent handoff about
what it found.

**It does not touch the brief it executed, or the row that pointed at it.**

An hour later the index still reads:

> `| 2026-08-05-registered-scope-drift.md | ... | live, unclaimed — **TAKE THIS ONE** |`

and the brief itself still opens *"Nothing here is blocked and nothing needs the owner to
start."* A fresh session, told only "read the index and take the top row", starts re-deriving a
result that merged an hour ago.

The same repo hit the identical shape twice in one day: a second stream's brief said "task 1:
classify the marks", the marks had been classified that morning, and the PR that caught it is
titled *"the prompt would have commissioned a rival tally against the committed one"* — the
danger is not just wasted time, it is a **second, divergent artifact** for a question already
answered.

**And the mirror-image half:** three `workstream-*.md` prompts sat in the directory for a day
with **no row in the index at all**, so a session reading only the index could not see them —
including the one stream that could have run to completion that day.

## Context / Trigger Conditions

Any of:

1. You are about to execute a brief selected from an index, and the index calls it live /
   unclaimed / next / "take this one".
2. You have just finished executing a brief and are writing the wrap-up.
3. You just authored a prompt for a future session.
4. Two or more index rows carry "next" — which is the same as none carrying it.
5. A prose row count sits beside a table other sessions append to.

Environmental smell: parallel sessions, a solo maintainer who self-merges, and a hand-edited
index. Nothing in CI reads prose, so **no gate catches any of this**.

## Solution

### Before you execute — 20 seconds, and it is not optional

The brief's own text cannot tell you whether it has been done, because the session that did it
is exactly the session that would have updated it. **Check the artifacts instead.**

```bash
# 1. Does the brief name an issue, and is that issue closed?
grep -oE '#[0-9]{2,6}' docs/handoffs/<brief>.md | sort -u | head
gh issue view <N> --json state,title --jq '"\(.state) — \(.title)"'

# 2. Has any merged PR named this brief? PR bodies usually say "Executes <path>".
gh pr list --state merged --limit 60 --search "<brief-filename>" \
  --json number,title,mergedAt

# 3. Does an analysis/result artifact already exist for it?
ls docs/analysis/ | grep -i "<topic>"
```

A CLOSED issue or a merged PR naming the brief means **stop and re-scope**, not "proceed
carefully". If the work is genuinely done, your job is to retire the brief — that is a real,
valuable half-hour, and it is the fix for the next session too.

### After you execute — retire it on BOTH surfaces

One is not enough. A reader arrives by either path.

**The brief file** gets a banner at the very top, above the original text:

```markdown
> ## ✅ DONE <date>, PR #<N> — do not execute this again
>
> <one-paragraph result, with the numbers that changed>
> Ruling: `<decision-id>`. Read the result instead: <link>.
> The brief below is kept unedited as the record of what was asked for.
```

Keep the body **unedited**. A brief that silently rewrites itself teaches nothing, and the next
reader needs to see what was asked as well as what came back.

**The index row** changes state and says what it produced, so the row is still useful:

```markdown
| `<brief>.md` | … | **RETIRED — DONE <date>, PR #N.** <the one-line outcome>; #<issue> closed |
```

### When you WRITE a prompt — register it in the same commit

A prompt that exists only in the directory is invisible to anyone using the index, which is what
the index is for. Add the row in the commit that adds the file, and give it:

- what it is, in one line a picker can choose from
- **what it is blocked on**, or "ungated"
- its task id and issue number, so the reader can check state without opening it

### Reconcile the index against the directory, not against itself

```bash
# every prompt on disk that has no row in the index
comm -23 \
  <(ls docs/handoffs/*.md | xargs -n1 basename | sort) \
  <(grep -oE '\[`[^`]+\.md`\]' docs/handoffs/next_session_prompt.md \
    | tr -d '[`]' | sort -u)
```

Run this whenever you touch the index. Recount the rows **from the table** and fix the prose
count — a number in prose beside an appendable table rots on someone else's commit.

### Only one row may carry "next"

If two do, the index is not ordering anything. Resolve it explicitly, in the index, with the
reason — and re-resolve it when a row retires, because retiring the top pick silently promotes
whatever was second without anyone deciding that.

## Verification

```bash
# no live row points at a closed issue
grep -oE '#[0-9]{2,6}' docs/handoffs/next_session_prompt.md | sort -u \
  | sed 's/#//' | while read n; do
      s=$(gh issue view "$n" --json state --jq .state 2>/dev/null)
      [ "$s" = "CLOSED" ] && echo "index cites CLOSED #$n — check the row's state"
    done

# exactly one "next"
grep -c 'TAKE THIS ONE\|— \*\*next\*\*' docs/handoffs/next_session_prompt.md   # want 1

# prose count matches the table
grep -c '^| \[' docs/handoffs/next_session_prompt.md
```

## Example

Real sequence, one repo, one day:

| # | What happened |
|---|---|
| 1 | Session A executes a brief; PR merges; issue closed. Brief and index untouched |
| 2 | Session B is told "read the index" — the top row says **TAKE THIS ONE** for A's work |
| 3 | Caught only because a human asked *"will the index cover all of them?"* |
| 4 | Separately, three prompts had no index row for a full day |
| 5 | And an unrelated stream's brief said "task 1: classify the marks" after they were classified — a merged PR is literally titled *"the prompt would have commissioned a rival tally"* |

Fix shipped in one PR: DONE banner on the brief, row retired with its outcome, three missing
rows added, prose count corrected, and the "next" ordering re-resolved because retiring the top
pick had silently promoted the second.

## Notes

- **This is the producing side.** The consuming side — a brief whose premise drifted while it
  was still unexecuted, usually flagged by the user — is
  `handoff-prompt-stale-user-hint-newer-state`. Both can fire on the same file.
- **Not a concurrency race.** Nothing is being clobbered; the update simply never happens,
  because the session that owed it had already declared itself finished. That is why it needs a
  wrap-up checklist item rather than a locking scheme, and why
  `shared-mutable-index-rmw-race-use-marker-blob-per-item` does not apply.
- **A wrap-up ritual will not catch it on its own.** Retiring the brief happens *after* the PR
  merges, which is *after* most wrap-up checklists have run. Treat "the brief is retired and its
  row updated" as owed until the PR is merged, alongside the PR number itself.
- **The cost is asymmetric.** Registering a row costs one line. A sibling re-deriving a
  committed result costs a session and can produce a second artifact that disagrees with the
  first — which then has to be adjudicated by a human who did not want either.
