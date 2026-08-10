#!/usr/bin/env python3
"""Generate the four test fixtures deterministically. Committed output is authoritative.

These used to be sliced copies of REAL transcripts. That was right while the tool
lived in a private repo — the fixtures were real, so they could not lie about the
shape of the thing being detected — and wrong the moment it was published: the
slices carried session content, filenames and identifiers from live client work,
and no amount of find-and-replace makes a real transcript publishable.

So the fixtures are now built, not captured. Each one reproduces a measured
property of the real transcript it replaces, and every row exists because some
test inspects it:

  incident.jsonl   Signature A fires once (a sync subagent's tool_result BEGINS
                   with the harness prefix and carries the needle at a small
                   offset in a short result), Signature B fires once (an
                   unmatched enqueue whose status is not `completed` and whose
                   tool-use-id resolves to an Agent call). Plus the three things
                   that must NOT fire: an unmatched enqueue whose status IS
                   `completed`, a non-completed notification from a backgrounded
                   Bash command with no Agent behind it, and a notification with
                   no tool-use-id tag at all.
  clean.jsonl      No needle anywhere, and three unmatched `completed` enqueues.
                   That last part is the point of this fixture, not decoration:
                   the first version of Signature B was a bare enqueue/remove
                   imbalance, and an imbalance is the NORMAL state of a session
                   that ends while a background agent is still running. Measured
                   across every transcript on the development machine, 57 of 79
                   sessions with any task-notification had one, this control
                   included. A clean fixture with balanced queues would let that
                   rule back in unnoticed.
  discussion.jsonl A session that merely TALKS about the detector: the needle
                   appears in an assistant message, in a user message, and — the
                   case the whole design turns on — mid-body inside an Agent
                   tool_result, which satisfies qualifying rule 1 completely and
                   must still not fire. In the measured original, true positives
                   carried the needle at offset ~124 of a ~500-character result
                   and discussion carried it at offset ~2,000 of a ~14,700
                   character one; the fixtures keep those two orders of magnitude
                   apart, because that separation is what the prefix anchor
                   exploits.
  malformed.jsonl  An unparseable line, an empty object, a message whose content
                   is a bare string, and a queue-operation carrying a queued USER
                   MESSAGE rather than a task-notification.

Two properties of the output are load-bearing:

  1. The literal needle never appears in plain form on disk. `escape_needle` is
     the only place that transformation is written down — do not restate it in
     prose elsewhere, which is how an earlier draft of the plan leaked the very
     string it was explaining how to hide.
  2. Generation is deterministic — no clock, no randomness, no filesystem reads.
     `tests/test_fixtures.py::test_fixtures_match_the_generator` regenerates into
     a temporary directory and compares byte for byte, so a hand-edited fixture
     is a test failure rather than a silent divergence.

Run `python3 make_fixtures.py` to rewrite the committed fixtures in place.
"""
import json
import pathlib
import sys

FIX = pathlib.Path(__file__).parent / "fixtures"

# Assembled from two halves, never written whole. See the module docstring.
NEEDLE = "PARTIAL output recovered from the " + "agent"
PREFIX = "Agent terminated early due to an API error"

SESSION_ID = "00000000-0000-4000-8000-000000000000"
CWD = "/home/example/workspace/demo-repo"
BRANCH = "feature/example-branch"
VERSION = "2.0.0"


def escape_needle(line):
    """Hide the literal needle on disk; json.loads still yields it."""
    return line.replace(NEEDLE, "PARTIAL output recovered from the \\u0061gent")


# --------------------------------------------------------------------------
# Row builders. Field sets mirror the real transcript rows the detector reads;
# every value is synthetic.
# --------------------------------------------------------------------------

def _uuid(n):
    return "00000000-0000-4000-8000-%012d" % n


class Rows(object):
    """Accumulates rows and hands out deterministic uuids and timestamps."""

    def __init__(self):
        self.rows = []
        self._n = 0

    def _next_uuid(self):
        self._n += 1
        return _uuid(self._n)

    def add(self, row):
        self.rows.append(row)
        return row

    def meta(self):
        """The five session-metadata rows every transcript opens with."""
        for row in (
            {"type": "last-prompt", "leafUuid": _uuid(900), "sessionId": SESSION_ID},
            {"type": "custom-title", "customTitle": "Example session", "sessionId": SESSION_ID},
            {"type": "agent-name", "agentName": "Example Agent", "sessionId": SESSION_ID},
            {"type": "mode", "mode": "default", "sessionId": SESSION_ID},
            {"type": "permission-mode", "permissionMode": "default", "sessionId": SESSION_ID},
        ):
            self.add(row)

    def _envelope(self, kind, timestamp):
        return {
            "type": kind,
            "uuid": self._next_uuid(),
            "parentUuid": _uuid(self._n - 1) if self._n > 1 else None,
            "sessionId": SESSION_ID,
            "session_id": SESSION_ID,
            "timestamp": timestamp,
            "cwd": CWD,
            "gitBranch": BRANCH,
            "version": VERSION,
            "userType": "external",
            "isSidechain": False,
            "entrypoint": "cli",
        }

    def tool_use(self, timestamp, tool, tool_use_id, tool_input):
        row = self._envelope("assistant", timestamp)
        row["requestId"] = "req_%s" % tool_use_id
        row["message"] = {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": tool_use_id, "name": tool, "input": tool_input}
            ],
        }
        return self.add(row)

    def assistant_text(self, timestamp, text):
        row = self._envelope("assistant", timestamp)
        row["requestId"] = "req_text_%d" % self._n
        row["message"] = {"role": "assistant", "content": [{"type": "text", "text": text}]}
        return self.add(row)

    def tool_result(self, timestamp, tool_use_id, content):
        """content: a string, or a list of {"type": "text", "text": ...} parts.

        Both shapes occur in real transcripts and `_result_text` handles each;
        the Signature A hit deliberately uses the list shape, because that is
        how the harness delivers its own partial-output notice.
        """
        row = self._envelope("user", timestamp)
        row["promptId"] = "prompt_%d" % self._n
        row["sourceToolAssistantUUID"] = _uuid(self._n - 1)
        row["message"] = {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": tool_use_id, "content": content}],
        }
        return self.add(row)

    def user_text(self, timestamp, text):
        row = self._envelope("user", timestamp)
        row["promptId"] = "prompt_%d" % self._n
        row["message"] = {"role": "user", "content": text}
        return self.add(row)

    def queue(self, timestamp, operation, content):
        return self.add({
            "type": "queue-operation",
            "operation": operation,
            "timestamp": timestamp,
            "sessionId": SESSION_ID,
            "content": content,
        })


def notification(task_id, tool_use_id, status, summary, result=None):
    """A task-notification exactly as the harness enqueues one.

    tool_use_id=None omits the <tool-use-id> tag entirely — a real shape, and
    the one that makes TOOL_USE_ID_RE find nothing and the row be skipped.
    status=None omits <status>, which the detector must treat as outstanding
    rather than as success.
    """
    lines = ["<task-notification>", "<task-id>%s</task-id>" % task_id]
    if tool_use_id is not None:
        lines.append("<tool-use-id>%s</tool-use-id>" % tool_use_id)
    lines.append("<output-file>/tmp/%s.output</output-file>" % task_id)
    if status is not None:
        lines.append("<status>%s</status>" % status)
    lines.append("<summary>%s</summary>" % summary)
    if result is not None:
        lines.append("<result>%s</result>" % result)
    lines.append("</task-notification>")
    return "\n".join(lines)


def _pad_to(text, target, filler):
    """Extend `text` with whole sentences of `filler` until it reaches `target`.

    Whole sentences rather than a character slice, so a fixture never ends on a
    half word — the fixtures get read by humans debugging a failure.
    """
    out = [text]
    length = len(text)
    i = 0
    while length < target:
        sentence = " " + filler[i % len(filler)]
        out.append(sentence)
        length += len(sentence)
        i += 1
    return "".join(out)


FILLER = [
    "The run had reached the third of its planned checks when it stopped.",
    "Nothing below this line should be treated as a completed result.",
    "The remaining checks were never started.",
    "Re-run the step from the beginning rather than trusting this text.",
    "No files were written after the point where the output ends.",
]


def partial_output_notice():
    """The harness's own notice, at the offsets a true positive carries.

    Measured on the transcripts this fixture replaces: the needle sat at offset
    ~124 of a ~500-character result. Discussion of the same string sat at
    ~2,000 of ~14,700. The gap between those two is the entire basis of the
    prefix anchor, so the generator asserts this one stays on the near side of
    it rather than letting a later edit quietly close the gap.
    """
    text = (
        PREFIX
        + " and could not be restarted within this session. "
        + "Everything below is "
        + NEEDLE
        + " before it was stopped, and it is incomplete.\n\n"
        + "Started the first of the three fixes and edited one file."
    )
    text = _pad_to(text, 500, FILLER)
    offset = text.index(NEEDLE)
    assert text.startswith(PREFIX), "Signature A needs the prefix at position 0"
    assert 100 <= offset <= 160, "needle offset drifted to %d" % offset
    assert 460 <= len(text) <= 560, "notice length drifted to %d" % len(text)
    return text


def review_report_quoting_the_needle():
    """A review subagent's report ON the detector — rule 1 passes, rule 2 fails.

    This is not a corner case, it is the implementation workflow: every review
    of this tool returns an Agent tool_result that quotes the string the tool
    matches on. It must never fire.
    """
    head = _pad_to(
        "Review of the resume-gate design, second pass.\n\n"
        "The detector's two qualifying rules hold up. Rule 1 resolves the hit to "
        "an Agent call, and rule 2 anchors on where the string sits rather than "
        "on whether it is present at all.",
        1_900,
        FILLER,
    )
    body = (
        head
        + "\n\nThe string the detector matches is \""
        + NEEDLE
        + "\", and this report quotes it, which is exactly the false positive "
        + "rule 2 exists to prevent.\n\n"
    )
    body = _pad_to(body, 14_700, FILLER)
    offset = body.index(NEEDLE)
    assert not body.startswith(PREFIX), "the discussion fixture must not anchor"
    assert offset >= 1_500, "needle offset too shallow at %d" % offset
    assert len(body) >= 14_000, "report length drifted to %d" % len(body)
    return body


# --------------------------------------------------------------------------
# The four fixtures.
# --------------------------------------------------------------------------

def build_incident():
    r = Rows()
    r.meta()

    # Five subagents dispatched. Two of them are the ones that matter.
    r.tool_use("2026-01-02T09:00:00.000Z", "Agent", "toolu_incident_spec_axis",
               {"description": "Spec-axis review", "prompt": "Review the change against the spec."})
    r.tool_use("2026-01-02T09:00:02.000Z", "Agent", "toolu_incident_standards_axis",
               {"description": "Standards-axis review", "prompt": "Review the change against the standards."})
    r.tool_use("2026-01-02T09:00:04.000Z", "Task", "toolu_incident_readability_items",
               {"description": "Five readability items", "prompt": "Apply the five readability items."})
    r.tool_use("2026-01-02T09:00:06.000Z", "Agent", "toolu_incident_readability_review",
               {"description": "Review the readability commit", "prompt": "Review the readability commit."})
    r.tool_use("2026-01-02T09:00:08.000Z", "Agent", "toolu_incident_disclosure_fixes",
               {"description": "Fix three disclosure defects", "prompt": "Fix the three disclosure defects."})
    r.tool_use("2026-01-02T09:00:09.000Z", "Agent", "toolu_incident_link_audit",
               {"description": "Audit the changelog links", "prompt": "Audit every changelog link."})
    # A non-Agent call, so agent_calls() has something to exclude.
    r.tool_use("2026-01-02T09:00:10.000Z", "Read", "toolu_incident_read_notes",
               {"file_path": "/home/example/workspace/demo-repo/notes.md"})

    # Timestamps deliberately out of order here: real transcripts are not sorted
    # (177 non-monotonic adjacent pairs were measured in the interrupted one),
    # and the detector must never depend on ordering.
    r.tool_result("2026-01-02T09:00:12.000Z", "toolu_incident_spec_axis",
                  "Async agent launched successfully")
    r.tool_result("2026-01-02T09:00:11.000Z", "toolu_incident_readability_review",
                  "Async agent launched successfully")
    r.tool_result("2026-01-02T09:00:13.000Z", "toolu_incident_read_notes",
                  "     1\tNotes for the demo repo.\n")

    # SIGNATURE A. content is a list of parts, which is how the harness
    # delivers this notice.
    r.tool_result("2026-01-02T09:01:40.000Z", "toolu_incident_disclosure_fixes",
                  [{"type": "text", "text": partial_output_notice()}])

    # A queued user message. Same row type as a notification, no tags at all,
    # and it must be skipped by the content-prefix check.
    queued = "Also please double-check the changelog entry before you push."
    r.queue("2026-01-02T09:02:00.000Z", "enqueue", queued)
    r.queue("2026-01-02T09:02:01.000Z", "remove", queued)

    # Two reports produced AND consumed: enqueue balanced by remove.
    spec_note = notification("task_spec_axis", "toolu_incident_spec_axis", "completed",
                             'Agent "Spec-axis review" completed',
                             result="No blocking findings.")
    r.queue("2026-01-02T09:02:10.000Z", "enqueue", spec_note)
    r.queue("2026-01-02T09:02:11.000Z", "remove", spec_note)
    standards_note = notification("task_standards_axis", "toolu_incident_standards_axis", "completed",
                                  'Agent "Standards-axis review" completed',
                                  result="Two nits, both fixed.")
    r.queue("2026-01-02T09:02:12.000Z", "enqueue", standards_note)
    r.queue("2026-01-02T09:02:13.000Z", "remove", standards_note)

    # A FAILED report the parent already consumed: enqueue balanced by remove.
    # The status gate does not exclude this one - the status really is `failed`
    # - so the enqueue/remove balance is the only thing standing between it and
    # a false positive. Without this row nothing in the suite distinguishes
    # `count > 0` from `count >= 0`, because every other balanced pair here is
    # `completed` and the status gate masks the difference.
    consumed_failure = notification("task_link_audit", "toolu_incident_link_audit", "failed",
                                    'Agent "Audit the changelog links" failed',
                                    result="Two links 404; the session fixed both inline.")
    r.queue("2026-01-02T09:02:14.000Z", "enqueue", consumed_failure)
    r.queue("2026-01-02T09:02:15.000Z", "remove", consumed_failure)

    # UNMATCHED but `completed`: the harmless "still running when the session
    # ended" case. Reporting this is what made the first Signature B fire on
    # 72% of sessions.
    r.queue("2026-01-02T09:02:20.000Z", "enqueue",
            notification("task_readability_items", "toolu_incident_readability_items", "completed",
                         'Agent "Five readability items" completed',
                         result="All five applied."))

    # SIGNATURE B: unmatched, non-completed, and it resolves to an Agent call.
    r.queue("2026-01-02T09:02:30.000Z", "enqueue",
            notification("task_readability_review", "toolu_incident_readability_review", "failed",
                         'Agent "Review the readability commit" failed',
                         result="Stopped before the review finished."))

    # A backgrounded Bash command. Non-completed, unmatched, and there is no
    # Agent tool_use behind its id — a failed shell command the session already
    # saw inline, not unreviewed subagent work.
    r.queue("2026-01-02T09:02:31.000Z", "enqueue",
            notification("task_background_grep", "toolu_incident_background_grep", "failed",
                         'Background command "Count the matching rows" failed with exit code 2'))

    # A notification carrying no tool-use-id tag at all.
    r.queue("2026-01-02T09:02:32.000Z", "enqueue",
            notification("task_orphan", None, "stopped", "A task with no tool-use-id recorded"))

    # dequeue rows carry a null content in real transcripts.
    r.queue("2026-01-02T09:02:40.000Z", "dequeue", None)

    r.assistant_text("2026-01-02T09:03:00.000Z",
                     "Committing what landed so far; the disclosure fixes are only partly done.")
    return r.rows


def build_clean():
    r = Rows()
    r.meta()

    r.tool_use("2026-01-03T10:00:00.000Z", "Agent", "toolu_clean_release_notes",
               {"description": "Summarise the release notes", "prompt": "Summarise the release notes."})
    r.tool_use("2026-01-03T10:00:02.000Z", "Agent", "toolu_clean_migration_checklist",
               {"description": "Draft the migration checklist", "prompt": "Draft the migration checklist."})
    r.tool_use("2026-01-03T10:00:04.000Z", "Task", "toolu_clean_changelog_links",
               {"description": "Check the changelog links", "prompt": "Check every changelog link resolves."})

    r.tool_result("2026-01-03T10:00:06.000Z", "toolu_clean_release_notes",
                  "Async agent launched successfully")
    r.tool_result("2026-01-03T10:00:05.000Z", "toolu_clean_migration_checklist",
                  [{"type": "text", "text": "Async agent launched successfully"}])
    r.tool_result("2026-01-03T10:00:07.000Z", "toolu_clean_changelog_links",
                  "Async agent launched successfully")

    # One report produced and consumed.
    notes = notification("task_release_notes", "toolu_clean_release_notes", "completed",
                         'Agent "Summarise the release notes" completed',
                         result="Six bullets, no blockers.")
    r.queue("2026-01-03T10:01:00.000Z", "enqueue", notes)
    r.queue("2026-01-03T10:01:01.000Z", "remove", notes)

    # THREE unmatched `completed` enqueues. This is the shape that broke the
    # bare-imbalance rule: perfectly clean session, three reports still sitting
    # on the queue because the session ended before reading them.
    r.queue("2026-01-03T10:01:10.000Z", "enqueue",
            notification("task_migration_checklist", "toolu_clean_migration_checklist", "completed",
                         'Agent "Draft the migration checklist" completed',
                         result="Checklist drafted."))
    r.queue("2026-01-03T10:01:11.000Z", "enqueue",
            notification("task_changelog_links", "toolu_clean_changelog_links", "completed",
                         'Agent "Check the changelog links" completed',
                         result="All links resolve."))
    r.queue("2026-01-03T10:01:12.000Z", "enqueue",
            notification("task_background_build", "toolu_clean_background_build", "completed",
                         'Background command "Build the docs" completed'))

    queued = "One more thing when you get a moment: bump the version string."
    r.queue("2026-01-03T10:01:20.000Z", "enqueue", queued)
    r.queue("2026-01-03T10:01:21.000Z", "remove", queued)
    r.queue("2026-01-03T10:01:30.000Z", "dequeue", None)

    r.assistant_text("2026-01-03T10:02:00.000Z", "All three finished cleanly. Nothing outstanding.")
    return r.rows


def build_discussion():
    r = Rows()
    r.meta()

    r.user_text("2026-01-04T11:00:00.000Z",
                "How does the detector avoid firing on a session that just talks about "
                "the string? The harness writes \"" + NEEDLE + "\" and we match on it, "
                "so surely quoting it here would trip it.")
    r.assistant_text("2026-01-04T11:00:10.000Z",
                     "It anchors on position. A real notice begins with the harness prefix; "
                     "a quotation of \"" + NEEDLE + "\" sits deep inside a much longer body.")

    r.tool_use("2026-01-04T11:00:20.000Z", "Agent", "toolu_discussion_design_review",
               {"description": "Review the resume-gate design", "prompt": "Review the design doc."})
    r.tool_use("2026-01-04T11:00:22.000Z", "Read", "toolu_discussion_read_spec",
               {"file_path": "/home/example/workspace/demo-repo/design.md"})

    # Rule 1 passes (an Agent tool_result), rule 2 fails (mid-body, not at 0).
    r.tool_result("2026-01-04T11:02:00.000Z", "toolu_discussion_design_review",
                  [{"type": "text", "text": review_report_quoting_the_needle()}])
    # Not an Agent call at all, and it carries the needle too.
    r.tool_result("2026-01-04T11:02:05.000Z", "toolu_discussion_read_spec",
                  "     1\tThe detector matches \"" + NEEDLE + "\" and anchors on the prefix.\n")

    r.queue("2026-01-04T11:03:00.000Z", "enqueue",
            notification("task_design_review", "toolu_discussion_design_review", "completed",
                         'Agent "Review the resume-gate design" completed',
                         result="Two amendments proposed."))
    r.queue("2026-01-04T11:03:10.000Z", "dequeue", None)
    return r.rows


MALFORMED_LINES = [
    json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "no timestamp here"}]}}),
    "this line is not json at all",
    json.dumps({"type": "user", "message": {"content": "tool_result with no tool_use_id"}}),
    json.dumps({"type": "queue-operation", "operation": "enqueue",
                "content": "a queued user message, not a task notification"}),
    json.dumps({}),
]


def render(rows):
    return "".join(escape_needle(json.dumps(row)) + "\n" for row in rows)


def build_all():
    """name -> file text. Pure: no clock, no randomness, no filesystem."""
    return {
        "incident": render(build_incident()),
        "clean": render(build_clean()),
        "discussion": render(build_discussion()),
        "malformed": "".join(line + "\n" for line in MALFORMED_LINES),
    }


def main(out_dir=None):
    out = pathlib.Path(out_dir) if out_dir else FIX
    out.mkdir(parents=True, exist_ok=True)
    for name, text in build_all().items():
        path = out / ("%s.jsonl" % name)
        path.write_text(text, encoding="utf-8")
        print("wrote %s (%d rows, %d bytes)" % (path.name, text.count("\n"), len(text)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else None))
