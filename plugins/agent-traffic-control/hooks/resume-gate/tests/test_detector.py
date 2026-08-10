import json
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import resume_gate as rg

FIX = pathlib.Path(__file__).parent / "fixtures"

def test_signature_a_fires_on_the_incident():
    entries = rg.load(FIX / "incident.jsonl")
    hits = rg.signature_a(entries, rg.agent_calls(entries))
    assert hits == ["Fix three disclosure defects"]

def test_signature_a_silent_on_clean_session():
    entries = rg.load(FIX / "clean.jsonl")
    assert rg.signature_a(entries, rg.agent_calls(entries)) == []

def test_signature_a_silent_on_a_session_that_merely_discusses_it():
    """The fixture carries 4 needle rows - a user message, an assistant
    message, a Read tool_result, and one Agent tool_result that quotes it
    mid-body. Exactly 1 satisfies qualifying rule 1, and 0 survive rule 2's
    prefix anchor. Rule 1 alone would fire on that Agent tool_result, which
    is a review subagent reporting on this very detector."""
    entries = rg.load(FIX / "discussion.jsonl")
    assert rg.signature_a(entries, rg.agent_calls(entries)) == []


def test_signature_a_ignores_a_prefix_anchored_result_from_a_non_agent_tool(tmp_path):
    """Qualifying rule 1: the hit must sit in a tool_result resolving to an
    Agent/Task call. A non-Agent tool (here a Read) whose result happens to
    carry both the harness prefix and the needle is not unreviewed subagent
    work - and without the `not in agents` guard the lookup that follows
    raises KeyError, which in PreToolUse becomes exit 2 and blocks the
    call."""
    rows = [
        {
            "type": "assistant",
            "message": {"content": [
                {"type": "tool_use", "id": "toolu_read_1", "name": "Read",
                 "input": {"file_path": "/tmp/notes.md"}},
            ]},
        },
        {
            "type": "user",
            "message": {"content": [
                {"type": "tool_result", "tool_use_id": "toolu_read_1",
                 "content": rg.PREFIX + ". " + rg.NEEDLE + " is quoted in this file."},
            ]},
        },
    ]
    path = tmp_path / "non_agent_result.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    entries = rg.load(path)
    assert rg.signature_a(entries, rg.agent_calls(entries)) == []

def test_load_survives_malformed_rows():
    entries = rg.load(FIX / "malformed.jsonl")
    assert len(entries) == 5
    assert entries[1][1] is None
    assert rg.signature_a(entries, rg.agent_calls(entries)) == []

def test_signature_b_finds_the_unconsumed_async_report():
    """Exact list, not membership. A membership assertion here is what hid
    the extra hit: the incident fixture also contains a failed
    run_in_background Bash notification, which used to surface as an
    unactionable "(async task toolu_...)"."""
    entries = rg.load(FIX / "incident.jsonl")
    hits = rg.signature_b(entries, rg.agent_calls(entries))
    assert hits == ["Review the readability commit"]


def test_signature_b_ignores_backgrounded_bash_commands():
    """Task-notifications are not emitted only for subagents - a Bash call
    run with run_in_background produces one too. The incident fixture holds
    a failed background command whose notification has no Agent tool_use
    behind it; a failed shell command is not unreviewed subagent work, and
    it must not arm the gate."""
    entries = rg.load(FIX / "incident.jsonl")
    agents = rg.agent_calls(entries)
    hits = rg.signature_b(entries, agents)
    assert all(hit in agents.values() for hit in hits), hits
    assert not any(hit.startswith("(async task") for hit in hits), hits

def test_signature_b_ignores_queued_user_messages():
    """queue-operation rows are also used for queued user input."""
    entries = rg.load(FIX / "malformed.jsonl")
    assert rg.signature_b(entries, rg.agent_calls(entries)) == []


def test_signature_b_ignores_a_failed_report_the_parent_already_consumed():
    """The balance gate, not the status gate, has to exclude this one.

    The incident fixture holds a `failed` notification whose enqueue IS
    matched by a remove - an async subagent that failed and whose report the
    parent read and acted on. That is not unreviewed work: the session saw it.
    Every OTHER balanced pair in the fixture is `completed`, so the status gate
    masks them and `count > 0` could be relaxed to `count >= 0` with nothing
    going red. This is the row that makes the balance gate observable.
    """
    entries = rg.load(FIX / "incident.jsonl")
    agents = rg.agent_calls(entries)
    assert "Audit the changelog links" in agents.values(), \
        "fixture lost the consumed-failure Agent call"
    assert "Audit the changelog links" not in rg.signature_b(entries, agents)


def test_signature_b_ignores_a_queued_user_message_quoting_a_notification(tmp_path):
    """A queued USER MESSAGE that quotes notification markup must not count.

    Not contrived: pasting a task-notification into the queue to ask about it
    is exactly what happens while working on this detector. The tags are all
    present and the tool-use-id resolves to a real Agent call, so the
    tool-use-id regex and the status regex both succeed - the ONLY thing
    separating this from a genuine notification is that the content does not
    begin with the task-notification tag.
    """
    entries = _write(tmp_path / "quoted_notification.jsonl", [
        _agent_row("toolu_test_quoted", "Rebuild the search index"),
        _enqueue_row(
            "While you're at it, can you explain this? I got "
            "<tool-use-id>toolu_test_quoted</tool-use-id> with "
            "<status>failed</status> and I don't know what it means."
        ),
    ])
    assert rg.signature_b(entries, rg.agent_calls(entries)) == []

def test_signature_b_silent_on_clean_session():
    """Clean sessions routinely end with completed-but-unread reports; those are not the hazard."""
    entries = rg.load(FIX / "clean.jsonl")
    assert rg.signature_b(entries, rg.agent_calls(entries)) == []

def test_signature_b_ignores_completed_reports():
    entries = rg.load(FIX / "incident.jsonl")
    hits = rg.signature_b(entries, rg.agent_calls(entries))
    assert "Five readability items" not in hits, "completed reports are noise, not hazard"
    assert "Review the readability commit" in hits, "the terminated-early async agent is the hazard"

def _notification(tool_use_id, status=None, summary='Agent "Do the thing" finished'):
    lines = [
        "<task-notification>",
        "<task-id>ztest123</task-id>",
        "<tool-use-id>%s</tool-use-id>" % tool_use_id,
        "<output-file>/tmp/ztest123.output</output-file>",
    ]
    if status is not None:
        lines.append("<status>%s</status>" % status)
    lines += ["<summary>%s</summary>" % summary, "</task-notification>"]
    return "\n".join(lines)


def _enqueue_row(content):
    return {
        "type": "queue-operation",
        "operation": "enqueue",
        "timestamp": "2026-08-10T00:00:00Z",
        "sessionId": "test-session",
        "content": content,
    }


def _agent_row(tool_use_id, description):
    return {
        "type": "assistant",
        "message": {"content": [
            {"type": "tool_use", "id": tool_use_id, "name": "Agent",
             "input": {"description": description}},
        ]},
    }


def _write(path, rows):
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    return rg.load(path)


def test_signature_b_treats_missing_status_as_outstanding(tmp_path):
    """An unreadable status is not evidence of success - fail toward
    reporting. Built around a REAL Agent call so the hit is a name a human
    can act on; a notification with no Agent behind it is a different case,
    covered by test_signature_b_ignores_a_notification_with_no_agent_call."""
    entries = _write(tmp_path / "missing_status.jsonl", [
        _agent_row("toolu_test_missing_status", "Audit the deploy config"),
        _enqueue_row(_notification("toolu_test_missing_status")),
    ])
    hits = rg.signature_b(entries, rg.agent_calls(entries))
    assert hits == ["Audit the deploy config"]


def test_signature_b_uses_the_most_recent_status_when_one_id_reports_twice(tmp_path):
    """Last write wins, and it has to be spelled out because both readings
    are defensible until you pick one.

    The same tool-use-id can appear on more than one notification row. The
    status that matters is the CURRENT one: an agent that failed and was
    retried to completion is not outstanding, and one that looked complete
    and was later reported killed is. Reading the first status instead would
    be wrong in both directions, and nothing in the suite noticed the
    difference until this test existed.
    """
    entries = _write(tmp_path / "failed_then_completed.jsonl", [
        _agent_row("toolu_retried", "Retried after a failure"),
        _enqueue_row(_notification("toolu_retried", status="failed",
                                   summary='Agent "Retried after a failure" failed')),
        _enqueue_row(_notification("toolu_retried", status="completed",
                                   summary='Agent "Retried after a failure" completed')),
    ])
    assert rg.signature_b(entries, rg.agent_calls(entries)) == [], \
        "a failure superseded by a completion is not outstanding"

    entries = _write(tmp_path / "completed_then_killed.jsonl", [
        _agent_row("toolu_later_killed", "Killed after reporting"),
        _enqueue_row(_notification("toolu_later_killed", status="completed",
                                   summary='Agent "Killed after reporting" completed')),
        _enqueue_row(_notification("toolu_later_killed", status="killed",
                                   summary='Agent "Killed after reporting" killed')),
    ])
    assert rg.signature_b(entries, rg.agent_calls(entries)) == ["Killed after reporting"], \
        "a completion superseded by a kill IS outstanding"


def test_signature_b_ignores_a_notification_with_no_agent_call(tmp_path):
    """A backgrounded Bash command produces a task-notification too, and a
    failed one is non-completed. With no Agent tool_use to resolve against
    there is no actionable subagent to name, so it must not be reported."""
    entries = _write(tmp_path / "background_bash.jsonl", [
        _enqueue_row(_notification(
            "toolu_background_bash",
            status="failed",
            summary='Background command "Locate the counts" failed with exit code 2',
        )),
    ])
    assert rg.signature_b(entries, rg.agent_calls(entries)) == []

def test_result_text_joins_every_part_not_just_the_first():
    """Agent results arrive as a LIST of parts, and the notice is not always
    alone in part 0. Measured on real transcripts: every Agent/Task result
    had list content, and a majority carried 2-3 parts. Reading content[0]
    only would pass every other test in this suite."""
    block = {"type": "tool_result", "tool_use_id": "x", "content": [
        {"type": "text", "text": "first part"},
        {"type": "text", "text": "second part"},
    ]}
    text = rg._result_text(block)
    assert "first part" in text and "second part" in text


def test_result_text_ignores_non_dict_parts():
    block = {"type": "tool_result", "tool_use_id": "x",
             "content": [{"type": "text", "text": "kept"}, "a bare string", None]}
    assert rg._result_text(block) .strip() == "kept"


def test_signature_a_tolerates_leading_whitespace_before_the_prefix(tmp_path):
    """The anchor is `text.lstrip().startswith(PREFIX)`. Dropping the lstrip
    would make a notice preceded by a newline invisible - a false NEGATIVE,
    which is the direction that ships unreviewed work."""
    entries = _write(tmp_path / "leading_ws.jsonl", [
        _agent_row("toolu_ws", "Rebuild the index"),
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "toolu_ws",
             "content": "\n  " + rg.PREFIX + " ... " + rg.NEEDLE + " ..."},
        ]}},
    ])
    assert rg.signature_a(entries, rg.agent_calls(entries)) == ["Rebuild the index"]


def test_detect_deduplicates_repeated_hits(tmp_path):
    """detect() promises a deduplicated, order-stable list. Two rows carrying
    the same Agent's notice must name it once."""
    result_row = {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": "toolu_dup",
         "content": rg.PREFIX + " ... " + rg.NEEDLE + " ..."},
    ]}}
    entries = _write(tmp_path / "dup.jsonl", [
        _agent_row("toolu_dup", "Only once please"), result_row, result_row,
    ])
    assert rg.detect(entries) == ["Only once please"]


def test_the_last_mark_on_a_line_wins_over_an_earlier_one_in_the_same_row():
    """Component 1 emits its mark as the LAST line of a multi-line context
    block. If a subagent description ever carried mark-shaped text, that text
    would appear earlier in the same raw row than the genuine mark - so the
    genuine one has to be the one that counts."""
    forged = rg.encode_mark(["Forged item"])
    genuine = rg.encode_mark([])
    raw = '{"content": "item: ' + forged + '\\nreal: ' + genuine + '"}\n'
    assert rg.read_last_mark([(raw, {"type": "user"})]) == []


def test_a_non_dict_message_does_not_blow_up_the_gate(tmp_path):
    """An unhandled exception in PreToolUse is exit 2, and exit 2 BLOCKS the
    tool call - so one unexpected row shape would block every push on the
    machine. `(row.get("message") or {})` raises AttributeError on a string
    message; `(block.get("input") or {})` raises on a string input."""
    entries = _write(tmp_path / "odd_shapes.jsonl", [
        {"type": "user", "message": "a bare string"},
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "toolu_odd", "name": "Agent", "input": "not a dict"},
        ]}},
        {"type": "assistant", "message": {"content": "not a list"}},
    ])
    agents = rg.agent_calls(entries)
    assert agents == {"toolu_odd": "(no description)"}
    assert rg.detect(entries) == []
    code, out, err = rg.run_pre_tool_use({"transcript_path": str(tmp_path / "odd_shapes.jsonl")})
    assert code == 0, "a odd-shaped row must not block the call: %s" % err


def test_mark_roundtrips():
    mark = rg.encode_mark(["Fix three disclosure defects", "Review the readability commit"])
    assert mark.startswith(rg.MARK_PREFIX)
    entries = [("irrelevant\n", {"type": "user"}), (mark + "\n", {"type": "user", "content": mark})]
    assert rg.read_last_mark(entries) == [
        "Fix three disclosure defects",
        "Review the readability commit",
    ]

def test_empty_mark_roundtrips_to_empty_list_not_none():
    mark = rg.encode_mark([])
    entries = [(mark + "\n", {"type": "user", "content": mark})]
    assert rg.read_last_mark(entries) == []

def test_read_last_mark_returns_none_when_absent():
    assert rg.read_last_mark(rg.load(FIX / "clean.jsonl")) is None

def test_mark_never_contains_the_needle():
    mark = rg.encode_mark(["a description containing " + rg.NEEDLE + " verbatim"])
    assert rg.NEEDLE not in mark

def test_window_excludes_everything_before_the_last_mark():
    entries = rg.load(FIX / "incident.jsonl")
    assert rg.detect(entries) != []
    marked = entries + [(rg.encode_mark([]) + "\n", {"type": "user"})]
    assert rg.detect(marked) == []

def test_detect_merges_both_signatures_without_duplicates():
    """Exact list, in order: Signature A's hit then Signature B's, and
    nothing else. Membership assertions here would not have noticed the
    third, unactionable entry Signature B used to add."""
    entries = rg.load(FIX / "incident.jsonl")
    hits = rg.detect(entries)
    assert hits == ["Fix three disclosure defects", "Review the readability commit"]

def test_mark_decodes_when_embedded_mid_string_with_escaped_newlines():
    """Component 1 emits the mark as the last line of a multi-line
    additionalContext block, so in the raw JSON row it sits mid-string with
    prose before and after it, and escaped newlines around it - it never
    stands alone the way test_mark_roundtrips assumes."""
    # Deliberately an item whose base64 has no trailing "=" padding: when
    # padding IS present, binascii silently stops decoding at the "=" and
    # discards everything after it, which accidentally hides this defect for
    # padded payloads. An unpadded payload lets trailing junk actually
    # corrupt the decode, which is the failure this test must catch.
    mark = rg.encode_mark(["Ship the resume gate fix"])
    raw = (
        '{"type": "user", "content": "Some earlier prose.\\nMore context.\\n'
        + mark
        + '\\nTrailing prose after the mark."}\n'
    )
    entries = [(raw, {"type": "user", "content": "irrelevant-parsed"})]
    assert rg.read_last_mark(entries) == ["Ship the resume gate fix"]

def test_read_last_mark_does_not_fall_back_to_a_stale_mark_when_the_latest_clears_it():
    """Regression for the silent-stale-answer bug: a later mark, embedded
    mid-string the way it actually appears, that clears the outstanding list
    to [] must win over an earlier mark that still lists an item - the
    earlier mark's items must never be silently resurrected."""
    earlier = rg.encode_mark(["Stale item"])
    later = rg.encode_mark([])
    raw_later = (
        '{"content": "Some prose before.\\nMore prose.\\n'
        + later
        + '\\nTrailing prose."}\n'
    )
    entries = [
        (earlier + "\n", {"type": "user"}),
        (raw_later, {"type": "user"}),
    ]
    assert rg.read_last_mark(entries) == []

def test_read_last_mark_returns_none_for_a_corrupted_payload_not_an_earlier_marks_items():
    """An unreadable most-recent mark must return None, not fall back to an
    earlier mark's items - None tells the caller to re-derive by scanning,
    which is the safe direction.

    `%` is outside the regex's base64 alphabet, so the capture group matches
    EMPTY here and b64decode("") succeeds. This case therefore exercises the
    declared-count check, not the decode exception - the two are covered
    separately below, because for a long time this test was the only one and
    its name promised the coverage it did not have.
    """
    earlier = rg.encode_mark(["Stale item"])
    corrupted = rg.MARK_PREFIX + " outstanding=1 payload=%%%not-base64%%%"
    entries = [
        (earlier + "\n", {"type": "user"}),
        (corrupted + "\n", {"type": "user"}),
    ]
    assert rg.read_last_mark(entries) is None


def test_read_last_mark_returns_none_when_the_payload_raises_on_decode():
    """The decode-exception branch, which the test above never reaches.

    Both arms: `A` is in the base64 alphabet but an impossible length, so
    b64decode raises binascii.Error; `//4=` decodes to bytes that are not
    valid UTF-8, so .decode raises UnicodeDecodeError. Before this, deleting
    the whole `except` clause left the suite green.
    """
    for payload in ("A", "//4="):
        mark = rg.MARK_PREFIX + " outstanding=1 payload=" + payload
        assert rg.read_last_mark([(mark + "\n", {"type": "user"})]) is None, payload


def test_a_corrupt_mark_does_not_disarm_the_gate():
    """The fail-open this whole three-state contract exists to prevent.

    read_last_mark returning None is supposed to mean "re-derive by
    scanning". It only means that if the re-derivation actually has rows to
    scan. When window_after_last_mark windowed on the most recent mark
    REGARDLESS of whether it decoded, appending one corrupt mark to a genuine
    incident transcript left detect() with zero rows - so it found nothing,
    and PreToolUse allowed the push it had been warning about minutes
    earlier. Silent, and in the one direction that matters.
    """
    entries = rg.load(FIX / "incident.jsonl")
    assert rg.detect(entries) == ["Fix three disclosure defects",
                                  "Review the readability commit"]

    corrupt = rg.MARK_PREFIX + " outstanding=1 payload=A"
    marked = entries + [(corrupt + "\n", {"type": "user"})]

    assert rg.read_last_mark(marked) is None, "a corrupt mark is not trustworthy state"
    assert rg.window_after_last_mark(marked) == marked, (
        "an undecodable mark must not be used as the segment boundary")
    assert rg.detect(marked) == ["Fix three disclosure defects",
                                 "Review the readability commit"]


def test_a_corrupt_mark_falls_back_to_the_last_readable_boundary_not_the_whole_file():
    """Re-derive from the newest mark that can actually be read.

    Scanning the whole file instead would resurrect items an earlier, valid
    mark had already cleared - the stale-items failure aimed the other way.
    """
    entries = rg.load(FIX / "incident.jsonl")
    cleared = entries + [(rg.encode_mark([]) + "\n", {"type": "user"})]
    corrupt = cleared + [(rg.MARK_PREFIX + " outstanding=2 payload=A\n", {"type": "user"})]

    assert rg.read_last_mark(corrupt) is None
    assert rg.detect(corrupt) == [], (
        "items behind a valid clearing mark must stay behind it")


def test_encode_mark_survives_an_item_containing_the_item_separator():
    """The hook must not be able to corrupt its own mark.

    encode_mark joins on an ASCII unit separator and read_last_mark splits on
    it, so a description containing one produced a mark declaring 1 item and
    decoding to 2 - unreadable. End to end that meant SessionStart emitted a
    full warning, armed the gate, and the very next push was allowed.
    """
    mark = rg.encode_mark(["Fix the \x1f thing", "Second item"])
    assert rg.read_last_mark([(mark + "\n", {"type": "user"})]) == [
        "Fix the   thing", "Second item"]
