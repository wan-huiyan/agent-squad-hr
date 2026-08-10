#!/usr/bin/env python3
"""resume-gate — flag work an interrupted session never reviewed.

Rule: the literal partial-output needle must never appear in this file.
It is assembled at runtime from two halves.
"""
import base64
import binascii
import json
import re
import sys

SKILL = "agent-traffic-control:recover-killed-session-from-transcript-and-worktree"

NEEDLE = "PARTIAL output recovered from the " + "agent"
PREFIX = "Agent terminated early due to an API error"
AGENT_TOOLS = ("Agent", "Task")

TASK_NOTIFICATION = "<task-notification>"
TOOL_USE_ID_RE = re.compile(r"<tool-use-id>([^<]+)</tool-use-id>")
STATUS_RE = re.compile(r"<status>([^<]+)</status>")
COMPLETED = "completed"


def load(path):
    """Return [(raw_line, parsed_or_None)]. Never raises on bad input."""
    entries = []
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                entries.append((line, json.loads(line)))
            except ValueError:
                entries.append((line, None))
    return entries


def _blocks(row):
    content = (row.get("message") or {}).get("content")
    return content if isinstance(content, list) else []


def _result_text(block):
    content = block.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            part.get("text", "") for part in content if isinstance(part, dict)
        )
    return ""


def agent_calls(entries):
    """tool_use_id -> description for every Agent/Task call in the file.

    Scanned over ALL entries, never windowed: the dispatch can precede the
    segment mark even when its result lands inside the window.
    """
    calls = {}
    for _, row in entries:
        if not isinstance(row, dict):
            continue
        for block in _blocks(row):
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use" and block.get("name") in AGENT_TOOLS:
                desc = (block.get("input") or {}).get("description")
                calls[block.get("id")] = desc or "(no description)"
    return calls


def signature_a(entries, agents):
    """Sync subagents the harness killed mid-run.

    Two qualifying rules, both required:
      1. the hit sits in a tool_result resolving to an Agent/Task call
      2. that result's text BEGINS with the harness prefix

    Rule 1 alone is insufficient: a review subagent reporting on this feature
    returns an Agent tool_result that quotes the needle mid-body.
    """
    hits = []
    for _, row in entries:
        if not isinstance(row, dict):
            continue
        for block in _blocks(row):
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            if block.get("tool_use_id") not in agents:
                continue
            text = _result_text(block)
            if NEEDLE not in text:
                continue
            if not text.lstrip().startswith(PREFIX):
                continue
            hits.append(agents[block["tool_use_id"]])
    return hits


def signature_b(entries, agents):
    """Async SUBAGENTS whose report the parent never consumed.

    81 of 181 Agent calls return only "Async agent launched successfully";
    their outcome arrives later as a task-notification, so signature_a can
    never see them. An enqueue with no matching remove is a report that was
    produced but never taken off the queue.

    An unmatched enqueue alone is NOT the hazard: any session that ends
    while a background agent is still running leaves one behind, and that
    is normal (measured: 57 of 79 sessions with task-notifications have at
    least one). The hazard is specifically an unconsumed report whose agent
    did not finish cleanly, so we also gate on the notification's <status>.
    Only "completed" counts as reviewed-and-fine; a missing or unparseable
    status is treated as NOT completed — fail toward reporting, since an
    unreadable status is not evidence the work succeeded.

    (`dequeue` and `popAll` operations never carry task-notification content
    in the measured transcripts, so they need no special-casing here — they
    fall through the content-prefix check like any other non-notification
    queue-operation row.)

    Third qualifying rule: the notification's tool-use-id must resolve to an
    Agent/Task call. Task-notifications are NOT emitted only for subagents —
    a Bash call run with run_in_background produces one too, and on the
    incident transcript a failed background grep ("Background command …
    failed with exit code 2") produced a second, non-completed hit with no
    Agent tool_use behind it. That is a failed shell command, not unreviewed
    subagent work, and reporting it armed the gate over something the session
    had already seen inline. There is deliberately no fallback label for an
    unresolvable id: a bare "(async task toolu_…)" names nothing a human can
    act on, and it was the only thing that made those background hits look
    like findings.
    """
    balance = {}
    status = {}
    for _, row in entries:
        if not isinstance(row, dict) or row.get("type") != "queue-operation":
            continue
        content = row.get("content")
        if not isinstance(content, str) or not content.lstrip().startswith(TASK_NOTIFICATION):
            continue
        match = TOOL_USE_ID_RE.search(content)
        if not match:
            continue
        tool_use_id = match.group(1)
        delta = 1 if row.get("operation") == "enqueue" else -1 if row.get("operation") == "remove" else 0
        balance[tool_use_id] = balance.get(tool_use_id, 0) + delta
        status_match = STATUS_RE.search(content)
        status[tool_use_id] = status_match.group(1) if status_match else None
    return [
        agents[tid]
        for tid, count in balance.items()
        if count > 0 and status.get(tid) != COMPLETED and tid in agents
    ]


MARK_PREFIX = "[resume-gate] segment-mark v1"
_MARK_ITEM_SEP = "\x1f"

# Anchored on the base64 alphabet itself, not on whitespace. The mark is
# never alone in the transcript — Component 1 emits it as the last line of a
# multi-line additionalContext block, so in the raw JSON row it sits mid-string
# with prose before and after it, and escaped newlines around it. Any
# character outside [A-Za-z0-9+/=] terminates the payload group naturally, so
# quotes, braces, escaped newlines, and ordinary prose all stop it correctly
# with no separate trimming step. The `*` (not `+`) lets an empty payload —
# the encode_mark([]) case — still match and capture "".
_MARK_RE = re.compile(
    re.escape(MARK_PREFIX) + r" outstanding=(\d+) payload=([A-Za-z0-9+/=]*)"
)


def encode_mark(items):
    """Encode outstanding items into a one-line transcript marker.

    Base64 keeps an arbitrary subagent description from breaking the mark
    across lines: the mark must survive as one line and be found by one
    regex, and a description containing a newline would split it.

    It does NOT stop a description leaking the needle into the transcript,
    and no earlier claim that it did was ever true — `_context()` prints
    every item in plain text two lines above the mark, and `_reason()` joins
    them plainly into the PreToolUse reason. If a subagent description ever
    contains the needle, it reaches the transcript either way; encoding the
    mark changes nothing about that.
    """
    payload = base64.b64encode(_MARK_ITEM_SEP.join(items).encode("utf-8")).decode("ascii")
    return "%s outstanding=%d payload=%s" % (MARK_PREFIX, len(items), payload)


def _last_mark_match(entries):
    """(entry_index, match) for the most recent segment mark, or (None, None).

    Shared by read_last_mark and window_after_last_mark so both agree on
    which entry holds "the last mark". They used to scan independently with
    slightly different checks (`raw.find` vs `in`) — that duplication is part
    of why a stale-mark decode bug went unnoticed, since the windowing path
    never decodes and so never surfaced a decode failure.
    """
    last_index = None
    last_match = None
    for index, (raw, _) in enumerate(entries):
        matches = list(_MARK_RE.finditer(raw))
        if matches:
            last_index = index
            last_match = matches[-1]
    return last_index, last_match


def read_last_mark(entries):
    """Items recorded by the most recent mark.

    Three states: None when no mark exists at all; [] when the most recent
    mark lists nothing; the decoded list otherwise. If the most recent mark
    exists but cannot be decoded — corrupted payload, or a declared item
    count that doesn't match what actually decoded — this returns None
    rather than an earlier mark's items. None makes the caller run a full
    detection pass, which is the safe direction: re-derive rather than trust
    stale state. Falling back to an earlier mark is unsafe in both
    directions — it can resurrect already-resolved items, and it can hide
    new ones.
    """
    _, match = _last_mark_match(entries)
    if match is None:
        return None
    declared_count = int(match.group(1))
    token = match.group(2)
    try:
        decoded = base64.b64decode(token).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return None
    items = [part for part in decoded.split(_MARK_ITEM_SEP) if part]
    if len(items) != declared_count:
        # The declared outstanding=N count and the decoded item count
        # disagree — e.g. non-base64 noise sat immediately after "payload="
        # and the capture group matched empty. That's corruption, not a
        # legitimately empty mark (which declares outstanding=0 and decodes
        # to zero items in agreement).
        return None
    return items


def window_after_last_mark(entries):
    index, _ = _last_mark_match(entries)
    if index is None:
        return entries
    return entries[index + 1:]


def detect(entries):
    """All outstanding items in the current segment, deduplicated, order-stable."""
    agents = agent_calls(entries)
    window = window_after_last_mark(entries)
    hits = []
    for item in signature_a(window, agents) + signature_b(window, agents):
        if item not in hits:
            hits.append(item)
    return hits


def uncommitted_summary(cwd):
    """Work that exists but has not been through review.

    Uncommitted changes and unpushed commits are the correct proxy: bounded
    to a handful of items, scoped to the repo, immune to mtime entirely.
    Absolute git path - hook PATH is not shell PATH. Never raises.
    """
    import subprocess
    lines = []
    try:
        dirty = subprocess.run(
            ["/usr/bin/git", "-C", cwd, "status", "--porcelain"],
            capture_output=True, text=True, timeout=10,
        )
        if dirty.returncode == 0:
            lines += [l for l in dirty.stdout.splitlines() if l.strip()][:20]
        ahead = subprocess.run(
            ["/usr/bin/git", "-C", cwd, "log", "--oneline", "@{u}..HEAD"],
            capture_output=True, text=True, timeout=10,
        )
        if ahead.returncode == 0 and ahead.stdout.strip():
            count = len(ahead.stdout.strip().splitlines())
            lines.append("%d unpushed commit%s" % (count, "" if count == 1 else "s"))
    except Exception:
        return []
    return lines


def _context(items, pending=()):
    lines = [
        "This session is resuming after an interruption. "
        "The following subagent work was produced but never assessed by the session that started it:",
        "",
    ]
    lines += ["  - %s" % item for item in items]
    if pending:
        lines += ["", "Work that exists but has not been through review:"]
        lines += ["  %s" % entry for entry in pending]
    lines += [
        "",
        "Re-verify each end to end before treating it as done, and before pushing, "
        "merging or deploying anything on this branch. A partial or unconsumed "
        "subagent report is not a finished result.",
        "See the %s skill." % SKILL,
        "",
        encode_mark(items),
    ]
    return "\n".join(lines)


def run_session_start(payload):
    """Return (exit_code, stdout, stderr).

    Three outcomes, and the middle one is what makes the gate ever turn off:

      items non-empty            -> warn, and mark(items). Arms the gate.
      items empty, previous mark
        listed something         -> emit ONLY encode_mark([]), no warning
                                    text. Disarms the gate.
      items empty, nothing to
        clear                    -> emit nothing at all.

    Without the middle branch a clearing mark is never produced in
    production, because _context() is the only caller of encode_mark and it
    only ran when there were items: one interruption armed the gate
    permanently, and every ship action forever after was prompted with the
    same long-resolved item names. That is the exact failure mode DESIGN.md
    rejected an earlier draft of Component 2 for.

    The third branch matters just as much in the other direction. Emitting a
    clearing mark unconditionally on every resume would inject a line of
    hook output into every resume of every session on the machine, most of
    which never had anything outstanding. Silence is the correct output for
    a session with nothing to say and nothing to retract.
    """
    try:
        if payload.get("source") != "resume":
            return 0, "", ""
        entries = load(payload["transcript_path"])
        previous = read_last_mark(entries)
        items = detect(entries)
        if not items:
            if not previous:
                # None (no mark, or an undecodable one) or [] (already
                # clear): nothing is armed, so there is nothing to disarm.
                return 0, "", ""
            out = {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": encode_mark([]),
                }
            }
            return 0, json.dumps(out), ""
        pending = uncommitted_summary(payload.get("cwd") or ".")
        out = {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": _context(items, pending),
            }
        }
        return 0, json.dumps(out), ""
    except Exception as exc:
        return 2, "", "resume-gate: detector failed (%s) - sessions are unguarded\n" % type(exc).__name__


def _reason(items):
    return (
        "This session resumed after an interruption and has unreviewed subagent work "
        "outstanding: %s. Confirm each has been re-verified end to end before shipping."
        % ", ".join(items)
    )


def run_pre_tool_use(payload):
    """Return (exit_code, stdout, stderr).

    Three-state read of the last mark: None means no mark exists (this
    session was never warned), so fall back to a full detect() pass;
    [] means a mark exists and listed nothing, so allow silently; a
    non-empty list means ask. Ship-action filtering is not this
    function's job - it lives in the hook config's `if:` conditions.

    Fails CLOSED: any internal error exits 2, which for PreToolUse blocks
    the tool call. A broken gate must never wave a push through.
    """
    try:
        entries = load(payload["transcript_path"])
        items = read_last_mark(entries)
        if items is None:
            items = detect(entries)
        if not items:
            return 0, "", ""
        out = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "ask",
                "permissionDecisionReason": _reason(items),
            }
        }
        return 0, json.dumps(out), ""
    except Exception as exc:
        return 2, "", "resume-gate: gate failed (%s) - blocking to stay safe\n" % type(exc).__name__


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.stderr.write("resume-gate: unreadable hook payload - sessions are unguarded\n")
        return 2
    if mode == "session-start":
        code, out, err = run_session_start(payload)
    elif mode == "pre-tool-use":
        code, out, err = run_pre_tool_use(payload)
    else:
        sys.stderr.write("resume-gate: unknown mode %r\n" % mode)
        return 2
    if out:
        sys.stdout.write(out)
    if err:
        sys.stderr.write(err)
    return code


if __name__ == "__main__":
    sys.exit(main())
