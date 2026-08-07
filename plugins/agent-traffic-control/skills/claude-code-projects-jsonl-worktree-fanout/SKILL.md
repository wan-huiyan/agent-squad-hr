---
name: claude-code-projects-jsonl-worktree-fanout
description: |
  Find a prior session's transcript that `~/.claude/projects/<project>/` does not hold: each git
  worktree gets its own separately namespaced project directory.
author: Claude Code
version: 1.0.0
date: 2026-05-28
---
# Claude Code projects/ JSONL transcripts fan out across worktrees

## Problem

The user asks: *"find that session ~2 weeks ago where we discussed X"*. You grep `~/.claude/projects/-Users-<user>-Documents-foo-project/*.jsonl` for keywords, get partial or zero hits, and report "couldn't find it" — but the session **does** exist, just under a different directory because it ran inside a git worktree.

Claude Code maps **each git worktree to its own project directory** under `~/.claude/projects/`. The canonical project at `/Users/<user>/Documents/foo-project/` becomes:

```
~/.claude/projects/-Users-<user>-Documents-foo-project/
```

But a worktree created via `git worktree add .claude/worktrees/<wt-name>` becomes a separate sibling:

```
~/.claude/projects/-Users-<user>-Documents-foo-project--claude-worktrees-<wt-name>/
```

Each worktree dir holds its own JSONL transcripts for sessions started from that working directory. A project that's seen heavy worktree use (typical for `superpowers:using-git-worktrees` workflow) can have **dozens** of sibling dirs.

## Context / Trigger Conditions

- User asks about a prior session, conversation, or work in a project
- Project uses `superpowers:using-git-worktrees` or has `.claude/worktrees/` populated
- Your initial grep of `~/.claude/projects/<project-name>/*.jsonl` returned fewer hits than expected, or none
- You want to enumerate every session that ever ran against the project (e.g. for a knowledge audit)
- Symptom: `~/.claude/projects/` contains a `<project-name>` dir AND multiple `<project-name>--claude-worktrees-<wt>` siblings

## Solution

### Quick lookup (one-liner)

Glob the **wildcard suffix** to cover canonical + all worktrees:

```bash
ls ~/.claude/projects/ | grep -iE "<project-keyword>" | wc -l  # confirm fan-out
```

Then search across all of them at once:

```bash
find ~/.claude/projects/ -name "*.jsonl" -newermt "<earliest-date>" 2>/dev/null \
  | grep -iE "<project-keyword>" \
  | grep -v subagents \
  | while read f; do
      c=$(grep -ic -E "<your-search-keywords>" "$f" 2>/dev/null)
      [ "$c" -gt 0 ] && echo "$c | $(stat -f "%Sm" -t "%Y-%m-%d %H:%M" "$f") | $f"
    done | sort -rn | head -10
```

Key points:
- The `grep -iE "<project-keyword>"` filters to the project family (canonical + all worktrees)
- `grep -v subagents` excludes subagent JSONLs (under `<session-id>/subagents/agent-*.jsonl`) — those are dispatched-agent runs, not user-facing sessions
- `find -newermt` narrows by date; loosen the window if needed

### Confirming the canonical directory mapping

For a working directory at `/Users/<user>/Documents/foo-project/`, the canonical project dir is:

```
~/.claude/projects/-Users-<user>-Documents-foo-project/
```

Note: slashes in the path become dashes; the leading dash is part of the encoding. For a worktree at `/Users/<user>/Documents/foo-project/.claude/worktrees/<wt-name>/`:

```
~/.claude/projects/-Users-<user>-Documents-foo-project--claude-worktrees-<wt-name>/
```

The `--` collapsing the slash-dot-slash boundary is the giveaway that you're looking at a worktree namespace, not the canonical one.

### Reading user prompts efficiently

JSONL lines mix user messages, assistant messages, tool calls, and system reminders. To extract just **real user prompts** (skip injected skill text, tool results, system reminders):

```python
import json
with open(fn) as f:
    for line in f:
        try: d = json.loads(line)
        except: continue
        if d.get("type") != "user": continue
        c = d.get("message",{}).get("content")
        if isinstance(c, list):
            txt = " ".join(b.get("text","") for b in c if isinstance(b,dict) and b.get("type")=="text")
        elif isinstance(c, str): txt = c
        else: continue
        # Filter out injected content
        if "Base directory" in txt or "tool_use_id" in txt[:50] or txt.strip().startswith("<"):
            continue
        if not txt.strip(): continue
        print(f"--- {d.get('timestamp','')[:16]} ---")
        print(txt[:400])
```

Filters explained:
- `"Base directory"` — skill content injected by the `Skill` tool
- `"tool_use_id"` — tool-result wrappers that show up as `type: user` messages
- `txt.strip().startswith("<")` — system reminders and command-name wrappers

## Verification

The pattern is correct when:

```bash
# Should return >1 if the project uses worktrees
ls ~/.claude/projects/ | grep -iE "<project-keyword>" | wc -l
```

Returns more than 1, AND your search across all matching dirs surfaces hits that grepping the canonical dir alone missed.

## Example

Today's session: user asked *"locate a previous session (about 2 wks ago) where I ask you to help me summarize what we did and our learnings"* in the `the-causal-impact-repo` project.

Initial grep of `~/.claude/projects/-Users-<user>-Documents-the-causal-impact-repo/*.jsonl` found 7 files, none matching the description. **Looked like the session was deleted.**

Then I expanded to:

```bash
find ~/.claude/projects/ -name "*.jsonl" -newermt "2026-05-13" ! -newermt "2026-05-16" 2>/dev/null \
  | grep -iE "causal-impact" \
  | grep -v subagents
```

→ 7 matching JSONLs across **5 different project directories** (1 canonical + 4 worktree-namespaced). The target session was in `-Users-<user>-Documents-the-causal-impact-repo--claude-worktrees-eloquent-franklin-fe932f/cff8244f-2194-4448-933c-9a93d417b770.jsonl` — never would have been found by searching the canonical dir alone.

Final keyword grep across all 7 surfaced the right one in seconds (opening prompt: *"can you please review the complete commit history or those 2 repos, and help me summarise what we did..."*).

## Notes

- The fan-out can be substantial: as of this session, `~/.claude/projects/` had 38 directories matching `causal-impact` (1 canonical + 37 worktrees). Similar fanout for other heavily-worktreed projects (`the project` had 3+).
- **Subagent JSONLs are separate.** Within each session dir there's a `<session-id>/subagents/agent-*.jsonl` tree. These hold subagent dispatches, not user conversations — exclude them when looking for "things the user said".
- The fan-out happens automatically when a session is started with `cwd` inside a worktree path — no opt-in needed.
- After a worktree is deleted, its project directory under `~/.claude/projects/` is **not** automatically cleaned up. So historical JSONLs persist even after `git worktree remove`. This is great for archaeology, but means stale worktree dirs accumulate.
- Don't try to be clever with `~/.claude/projects/<exact-canonical>/*.jsonl` patterns — always include the wildcard suffix to cover worktree dirs.

## References

- Claude Code project state docs (CC stores per-cwd session histories under `~/.claude/projects/`)
- The `superpowers:using-git-worktrees` skill describes the worktree workflow that produces this fan-out
- Sibling pattern: `claude-code-session-jsonl-whitespace-text-block` and `claude-code-session-jsonl-orphan-advisor-tool-result` operate on the same JSONL files; this skill is the discovery layer for finding them in the first place

## Neighbouring skills

These were named in this skill's description until v1.18.0. The description is
resident in context on every turn, so a cross-link there costs budget on every
turn and buys nothing -- a user never types another skill's name. They belong
here, where the model reads them once retrieval has already succeeded.

- [`git-worktree`](../git-worktree/SKILL.md)
