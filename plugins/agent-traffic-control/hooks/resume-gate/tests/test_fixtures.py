import json, pathlib, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import make_fixtures

FIX = pathlib.Path(__file__).parent / "fixtures"
REPO = pathlib.Path(__file__).resolve().parents[1]
# str.join, not `+`: adjacent string constants are folded at COMPILE time, so
# `"a" + "b"` would put the whole string into this file's .pyc.
NEEDLE = "".join(["PARTIAL output recovered from the ", "ag", "ent"])
PREFIX = "Agent terminated early due to an API error"

def _rows(name):
    for line in (FIX / f"{name}.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            yield line

def test_fixtures_exist():
    for name in ("incident", "clean", "discussion", "malformed"):
        assert (FIX / f"{name}.jsonl").exists(), f"missing {name}.jsonl"

def test_no_fixture_contains_the_literal_needle_on_disk():
    for path in FIX.glob("*.jsonl"):
        assert NEEDLE not in path.read_text(encoding="utf-8"), f"{path.name} leaks the needle"

def test_incident_fixture_still_decodes_to_the_needle():
    found = False
    for line in _rows("incident"):
        if NEEDLE in json.dumps(json.loads(line)):
            found = True
    assert found, "escaping destroyed the needle instead of hiding it"

def test_discussion_fixture_still_decodes_to_the_needle_inside_an_agent_result():
    """Without this, the whole discussion fixture is vacuous.

    `test_signature_a_silent_on_a_session_that_merely_discusses_it` asserts
    signature_a returns []. If the needle ever vanished from this fixture -
    an escaping change, a regenerated fixture that dropped the row - that
    assertion would still pass, and pass for the wrong reason: it would be
    measuring a transcript with nothing to find rather than one whose find is
    correctly rejected. So pin the precondition the silence is supposed to be
    interesting about: the needle IS here, it IS inside a tool_result owned by
    an Agent call (qualifying rule 1 satisfied), and it does NOT sit at the
    start (qualifying rule 2 is the only thing rejecting it).
    """
    agent_ids = set()
    for line in _rows("discussion"):
        row = json.loads(line)
        for block in (row.get("message") or {}).get("content") or []:
            if isinstance(block, dict) and block.get("type") == "tool_use" \
                    and block.get("name") in ("Agent", "Task"):
                agent_ids.add(block.get("id"))
    assert agent_ids, "the discussion fixture has no Agent call to resolve against"

    quoting_results = []
    for line in _rows("discussion"):
        row = json.loads(line)
        for block in (row.get("message") or {}).get("content") or []:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            if block.get("tool_use_id") not in agent_ids:
                continue
            content = block.get("content")
            text = content if isinstance(content, str) else " ".join(
                p.get("text", "") for p in content if isinstance(p, dict))
            if NEEDLE in text:
                quoting_results.append(text)

    assert len(quoting_results) == 1, (
        "expected exactly one Agent tool_result quoting the needle, got %d"
        % len(quoting_results))
    text = quoting_results[0]
    assert not text.lstrip().startswith(PREFIX), (
        "the discussion fixture's quote is prefix-anchored - it is now a true "
        "positive, not a discussion")
    assert text.index(NEEDLE) > 1000, (
        "the needle sits at offset %d; the fixture is supposed to carry it deep "
        "in a long report, which is the property the anchor exploits"
        % text.index(NEEDLE))

def test_clean_fixture_has_no_needle_even_decoded():
    for line in _rows("clean"):
        assert NEEDLE not in json.dumps(json.loads(line))

def test_clean_fixture_carries_unmatched_completed_enqueues():
    """The clean fixture's whole job, pinned so it cannot quietly evaporate.

    `test_signature_b_silent_on_clean_session` asserts Signature B says nothing
    here. That assertion is only interesting if this fixture actually contains
    the shape the first version of Signature B fired on: task-notifications
    enqueued and never removed. Balance this fixture's queues and every test
    still passes while the fixture has stopped testing the thing it exists for
    - measured across the development machine, 57 of 79 sessions with any
    task-notification carried an unmatched enqueue, so a clean control without
    one is not representative of a clean session.
    """
    balance = {}
    status = {}
    for line in _rows("clean"):
        row = json.loads(line)
        if row.get("type") != "queue-operation":
            continue
        content = row.get("content")
        if not isinstance(content, str) or not content.startswith("<task-notification>"):
            continue
        tool_use_id = content.split("<tool-use-id>")[1].split("</tool-use-id>")[0]
        delta = {"enqueue": 1, "remove": -1}.get(row.get("operation"), 0)
        balance[tool_use_id] = balance.get(tool_use_id, 0) + delta
        status[tool_use_id] = content.split("<status>")[1].split("</status>")[0]

    unmatched = [tid for tid, n in balance.items() if n > 0]
    assert len(unmatched) >= 3, (
        "expected at least 3 unmatched enqueues, got %d - this fixture is the "
        "control that keeps a bare enqueue/remove imbalance rule out"
        % len(unmatched))
    assert all(status[tid] == "completed" for tid in unmatched), (
        "every unmatched enqueue here must be `completed`; a non-completed one "
        "would make the clean fixture a true positive")

def test_fixtures_stay_small():
    """A cap kept from when these were sliced from real transcripts.

    It is no longer load-bearing for size - a generated fixture is a few KB -
    but it still fails fast if anyone reintroduces a captured transcript,
    which is the thing that must not come back.
    """
    for path in FIX.glob("*.jsonl"):
        size = path.stat().st_size
        assert size < 1_000_000, f"{path.name} is {size} bytes - generate it, do not capture it"

def test_fixtures_match_the_generator(tmp_path):
    """The committed fixtures must be byte-identical to what make_fixtures.py
    emits, and emitting them twice must give the same bytes.

    Two failures this catches. A hand-edited fixture: someone tweaks a row to
    make a test pass and the generator no longer describes what is on disk, so
    the next regeneration silently reverts it. And a non-deterministic
    generator: any clock, uuid4 or dict-ordering dependence creeping in would
    make every regeneration a spurious diff, which trains people to ignore the
    diff.
    """
    first = make_fixtures.build_all()
    second = make_fixtures.build_all()
    assert first == second, "make_fixtures.build_all() is not deterministic"

    for name, text in first.items():
        committed = (FIX / f"{name}.jsonl").read_text(encoding="utf-8")
        assert committed == text, (
            f"fixtures/{name}.jsonl differs from make_fixtures.py output - "
            f"regenerate with `python3 tests/make_fixtures.py`")

def _tracked_source_files():
    """Every committed text file under the hook, excluding build artefacts."""
    for path in sorted(REPO.rglob("*")):
        if not path.is_file():
            continue
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        yield path


def test_no_source_file_spells_out_the_needle():
    """Rule 3, enforced over the source and not only the fixtures.

    `test_no_fixture_contains_the_literal_needle_on_disk` covers *.jsonl.
    This covers the code, the docs and the tests - the places the string
    actually got leaked twice while this tool was being built, once by a
    design document quoting it and once by a plan illustrating the escape and
    losing a backslash to markdown rendering.
    """
    for path in _tracked_source_files():
        assert NEEDLE not in path.read_text(encoding="utf-8", errors="replace"), (
            "%s spells out the needle - describe it, never write it" % path.name)


def test_no_source_file_contains_a_decodable_segment_mark():
    """The mark needs the same rule the needle has, and did not have one.

    Component 2 reads the newest mark out of the transcript and trusts it. A
    mark is a fixed literal, so any row that merely QUOTES one - a doc
    example, a test fixture, someone pasting hook output into a chat while
    debugging - becomes state the gate acts on. A committed empty mark is the
    worst case: every session that reads that file disarms its own gate.

    Nothing enforced this before; the repo was clean by luck.
    """
    import re, sys
    sys.path.insert(0, str(REPO))
    import resume_gate as rg

    offenders = []
    for path in _tracked_source_files():
        if path.name == "resume_gate.py":
            continue  # defines the pattern; cannot match its own regex source
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in rg._MARK_RE.finditer(text):
            if rg._decode_mark(match) is not None:
                offenders.append("%s: %s" % (path.name, match.group(0)[:60]))
    assert not offenders, (
        "these files carry a mark the gate would read as real state: %s" % offenders)


def test_generator_never_reads_the_users_transcripts():
    """The previous generator sliced live transcripts out of ~/.claude/projects.

    That is what made the fixtures unpublishable. The replacement must build
    its rows, so nothing in it should reach for a home directory or the
    transcript store at all.
    """
    source = pathlib.Path(make_fixtures.__file__).read_text(encoding="utf-8")
    for forbidden in ("expanduser", "os.environ", "Path.home", ".claude/projects"):
        assert forbidden not in source, (
            f"make_fixtures.py references {forbidden!r} - it must not read the "
            f"machine it runs on")
