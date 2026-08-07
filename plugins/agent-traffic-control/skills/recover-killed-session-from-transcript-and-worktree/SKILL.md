---
name: recover-killed-session-from-transcript-and-worktree
description: |
  Use to recover the work, plan, and failure-cause of a PRIOR Claude Code session that died /
  crashed / was killed mid-task (e.g. a hung tool call, an API 529 storm, the user force-quit), so
  the current session can continue it without redoing work or repeating the fatal mistake. Trigger
  when: (1) the user says something like "we had a session yesterday on worktree X that got killed —
  the transcript might help", "resume the crashed session", "continue what the last run was doing";
  (2) you find an isolated git worktree with uncommitted WIP + a leftover plan file (tasks/session_N_todo.md)
  but no corresponding merged PRs; (3) a feature branch has uncommitted changes and you need to know
  the intent behind them. Covers: locating the dead session's worktree + leftover artifacts, finding
  and identifying its transcript JSONL, and mining it for the plan, the cause of death (to avoid
  repeating it), and any USER DECISIONS made in that session (so you don't re-ask). Also covers the
  trap that the dead session's "verified" / "done" claims are often PARTIAL (it was killed
  mid-verification), so re-verify completely before trusting them.
author: Claude Code
version: 1.0.0
date: 2026-06-06
---

# Recover a killed Claude Code session from its transcript + worktree

## Problem
A prior session was doing real work (building a feature, fixing a batch of issues) and got killed
mid-task — a hung tool call, an API 529 after a long run, the user quit. It left uncommitted WIP and
a half-finished plan, but no handoff. Starting fresh wastes the work AND risks repeating whatever
killed it. The session's full intent + state lives in its **transcript JSONL** + its **worktree
artifacts** — recover from there.

## Context / Trigger Conditions
- User: "the session yesterday on worktree X got killed, the transcript might help" / "resume it".
- An isolated git worktree with uncommitted WIP + a leftover `tasks/session_N_todo.md` (or similar
  plan file) + maybe a baseline screenshot, but no matching merged PRs.
- A branch with uncommitted changes whose intent you need.

## Solution

### 1. Find the worktree + leftover artifacts (cheap, do first)
```bash
git -C <repo> worktree list                 # find the named worktree + its branch/HEAD
ls <worktree>/tasks/ <worktree>/             # leftover plan (session_N_todo.md), baseline pngs
git -C <code-repo> status -sb                # uncommitted WIP from the killed run
git -C <code-repo> reflog -20                # what it did right before dying
```
A leftover `tasks/session_N_todo.md` is gold — it's usually the killed session's (often advisor-vetted)
plan with specific implementation notes. Read it FIRST; it may make transcript-mining optional.

### 2. Locate + identify the transcript
Transcripts live at `~/.claude/projects/<encoded-cwd>/*.jsonl`, where `<encoded-cwd>` is the session's
working dir with `/`→`-` (a worktree at `.../worktrees/token-app` → `...-worktrees-token-app`).
```bash
DIR=~/.claude/projects/<encoded-worktree-path>
ls -lt "$DIR"/*.jsonl                        # newest = most likely the killed session
for f in "$DIR"/*.jsonl; do printf "%6s  %s\n" "$(wc -l < "$f")" "$(basename "$f")"; done
```
The killed session is usually the **most-recently-modified** file; it's often abnormally SHORT (died
early) or ends abruptly. Confirm by reading its tail (below).

### 3. Mine it for the three things that matter
Each JSONL line is a JSON object; `user` content is a string, `assistant` content an array of
text/tool_use blocks. Extract with `jq` (don't read whole multi-MB files into context):
```bash
# user messages (decisions, instructions) — content is a STRING for type=="user"
jq -rc 'select(.type=="user" and (.message.content|type=="string")) | .message.content' "$f" \
  | grep -viE 'system-reminder|tool_result'
# the last things that happened before death (cause)
jq -rc 'select(.type=="assistant") | .message.content[]? |
  if .type=="text" then "TEXT:"+(.text[0:200]) elif .type=="tool_use" then "TOOL:"+.name else .type end' "$f" | tail -15
```
Recover:
- **The plan** — what it was building (cross-check the leftover `tasks/*.md`).
- **The cause of death** — the last tool call + any error. (Real example: the tail showed
  `browser_take_screenshot` hung on "waiting for element to be stable" then API 529 — the screenshot
  trap, see `playwright-screenshot-hangs-on-infinite-animation`. Knowing this, you AVOID the same call.)
- **User decisions made in that session** — scope choices, approvals, preferences. Quote them; do NOT
  re-ask the user things they already decided in the dead run.

For large transcripts, dispatch a subagent to mine them (protects your context) — but **transcript
mining can overload** (a fan-out subagent 529'd here); if it fails, fall back to `jq` yourself.

### 4. Re-verify the dead session's "done" claims — they're often PARTIAL
A killed session's "fixed and verified" notes were frequently written mid-verification (it died before
finishing). Real example: the dead run claimed "#50 fixed and verified numerically" but had only
checked ONE symptom (the right-edge); the fix was actually incomplete (label still wrapped, value still
clipped) — caught only by re-measuring fully. **Re-verify inherited fixes end-to-end before trusting them.**

## Verification
- The recovered plan matches the leftover artifacts + reflog.
- You can state the cause of death and have a concrete way to avoid it.
- You've listed the user decisions from the dead session and are not re-asking them.
- Inherited "done" items are re-verified, not assumed.

## Notes
- The dead session's worktree branch + uncommitted WIP may be reconcilable onto current main
  (stash → checkout main → branch → pop) if its base has moved since.
- See also: `playwright-screenshot-hangs-on-infinite-animation` (a common session-killer),
  `claude-code-projects-jsonl-worktree-fanout` + `claude-code-session-shipped-and-agent-labels-from-transcript`
  (transcript-location + extraction mechanics), `handoff-prompt-stale-user-hint-newer-state` (the
  related "newer state landed since the prompt" case).

## Reference-only siblings in this toolkit

These carry `disable-model-invocation: true`. They never appear in the skill
listing and the Skill tool refuses them, so the only way in is to open the file
with Read when one of these matches what you are looking at.

- [`session-handoff-detect-prior-orphan-pr`](../session-handoff-detect-prior-orphan-pr/SKILL.md) — a previous handoff run already left a branch, PR or worktree behind — find it before opening a duplicate
- [`session-handoff-number-collision-with-unmerged-sibling`](../session-handoff-number-collision-with-unmerged-sibling/SKILL.md) — two sessions picked the same handoff number because each only sees what merged on its own branch
- [`parallel-session-superseded-validated-fix-verify-live-prod-state-first`](../parallel-session-superseded-validated-fix-verify-live-prod-state-first/SKILL.md) — a parallel session already shipped a different fix to the same live artefact while you were building yours
