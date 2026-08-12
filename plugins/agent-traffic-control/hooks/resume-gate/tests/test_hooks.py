import io, json, os, pathlib, subprocess, sys
import pytest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import resume_gate as rg

FIX = pathlib.Path(__file__).parent / "fixtures"

def _payload(name, source="resume"):
    return {"source": source, "transcript_path": str(FIX / f"{name}.jsonl"), "cwd": "/tmp"}

def test_session_start_warns_on_the_incident():
    code, out, err = rg.run_session_start(_payload("incident"))
    assert code == 0
    body = json.loads(out)["hookSpecificOutput"]
    assert body["hookEventName"] == "SessionStart"
    assert "Fix three disclosure defects" in body["additionalContext"]
    assert "Review the readability commit" in body["additionalContext"]
    assert rg.MARK_PREFIX in body["additionalContext"]

def test_session_start_silent_on_clean_session():
    code, out, err = rg.run_session_start(_payload("clean"))
    assert (code, out.strip()) == (0, "")

def test_session_start_silent_on_discussion_transcript():
    code, out, err = rg.run_session_start(_payload("discussion"))
    assert (code, out.strip()) == (0, "")

def test_session_start_ignores_non_resume_sources():
    code, out, err = rg.run_session_start(_payload("incident", source="startup"))
    assert (code, out.strip()) == (0, "")

def test_session_start_emits_a_clearing_mark_when_the_previous_mark_listed_items(tmp_path):
    """Branch 2 of three: nothing outstanding now, but a previous mark still
    lists something. Emit ONLY the clearing mark - no warning text.

    Without this branch encode_mark([]) is never produced in production
    (_context() was its only caller, and it ran only when items existed), so
    one interruption armed the gate permanently."""
    marked = tmp_path / "resolved.jsonl"
    marked.write_text(
        json.dumps({"type": "user", "content": rg.encode_mark(["Fix three disclosure defects"])}) + "\n",
        encoding="utf-8",
    )
    code, out, err = rg.run_session_start(
        {"source": "resume", "transcript_path": str(marked), "cwd": "/tmp"})
    assert code == 0
    ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert ctx == rg.encode_mark([])
    assert "Fix three disclosure defects" not in ctx
    assert "resuming after an interruption" not in ctx

def test_session_start_stays_completely_silent_when_there_is_nothing_to_clear(tmp_path):
    """Branch 3 of three: no outstanding items and no previous mark that
    listed any. Emitting a clearing mark unconditionally here would inject
    hook output into every resume of every session forever."""
    quiet = tmp_path / "quiet.jsonl"
    quiet.write_text(json.dumps({"type": "user", "message": {"content": []}}) + "\n", encoding="utf-8")
    code, out, err = rg.run_session_start(
        {"source": "resume", "transcript_path": str(quiet), "cwd": "/tmp"})
    assert (code, out.strip()) == (0, "")

def test_session_start_does_not_re_emit_a_clearing_mark_after_one_already_cleared(tmp_path):
    """An already-empty previous mark is not "something to clear" - a second
    resume after the gate went quiet must produce no output at all, or every
    resume from then on emits a mark."""
    cleared = tmp_path / "cleared.jsonl"
    cleared.write_text(
        json.dumps({"type": "user", "content": rg.encode_mark([])}) + "\n", encoding="utf-8")
    code, out, err = rg.run_session_start(
        {"source": "resume", "transcript_path": str(cleared), "cwd": "/tmp"})
    assert (code, out.strip()) == (0, "")

def test_gate_arms_on_resume_one_and_disarms_on_resume_two(tmp_path):
    """End-to-end, the sequence that matters: incident transcript -> resume 1
    warns and marks -> that context is appended as a transcript row ->
    resume 2 emits a clearing mark -> appended -> the PreToolUse gate now
    allows a push.

    This is the regression test for "arms once, never disarms". Before the
    fix, resume 2 produced no clearing mark and the final push still asked -
    44 hours and any number of resumes later, naming the same resolved
    items."""
    transcript = tmp_path / "sequence.jsonl"
    transcript.write_text((FIX / "incident.jsonl").read_text(encoding="utf-8"), encoding="utf-8")

    def append_context(context):
        with transcript.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"type": "user", "content": context}) + "\n")

    def push():
        return rg.run_pre_tool_use({"transcript_path": str(transcript), "tool_name": "Bash",
                                    "tool_input": {"command": "git push origin HEAD"}})

    # Resume 1: warns, names the items, arms the gate.
    code, out, err = rg.run_session_start(
        {"source": "resume", "transcript_path": str(transcript), "cwd": "/tmp"})
    assert code == 0
    first = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert "Fix three disclosure defects" in first
    append_context(first)

    code, out, err = push()
    assert json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "ask"

    # Resume 2: the items are behind the mark now, so nothing is outstanding
    # and the previous mark listed something -> a clearing mark.
    code, out, err = rg.run_session_start(
        {"source": "resume", "transcript_path": str(transcript), "cwd": "/tmp"})
    assert code == 0, err
    second = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert second == rg.encode_mark([])
    append_context(second)

    assert push() == (0, "", "")

def test_session_start_exits_2_with_one_line_on_error(tmp_path):
    """A MISSING transcript is deliberately no longer the error case - it has
    its own allow-and-say-so branch - so this uses a path that exists and is a
    DIRECTORY. open() raises IsADirectoryError, which is a genuine surprise
    about the harness with no known cause, and must still fail closed.

    Using a missing file here was the old proxy for "any error", and it is
    what made the two behaviours impossible to change independently."""
    code, out, err = rg.run_session_start({"source": "resume", "transcript_path": str(tmp_path)})
    assert code == 2
    assert len(err.strip().splitlines()) == 1
    assert "resume-gate" in err

def test_session_start_allows_and_says_so_when_the_transcript_does_not_exist(tmp_path):
    """A resume cannot really happen without a transcript, but both hooks must
    answer a missing file the same way rather than one calling it a detector
    failure. Allowed, and NOT silent."""
    missing = tmp_path / "never-written.jsonl"
    assert not missing.exists()
    code, out, err = rg.run_session_start(
        {"source": "resume", "transcript_path": str(missing), "cwd": "/tmp"})
    assert (code, err) == (0, "")
    assert json.loads(out) == {"systemMessage": rg.NO_TRANSCRIPT_MESSAGE}

def test_uncommitted_work_is_reported_as_supplementary_context(tmp_path):
    """Spec: `git status --porcelain` + unpushed commits are the review-state proxy."""
    assert rg.uncommitted_summary("/definitely/not/a/repo") == []


def _git(repo, *args):
    return subprocess.run(
        ["/usr/bin/git", "-C", str(repo)] + list(args),
        capture_output=True, text=True, check=True,
    )

def test_uncommitted_summary_reports_a_dirty_file_and_an_unpushed_commit(tmp_path):
    """The real body of uncommitted_summary was entirely unverified: it could
    be replaced with `return []` and every other test still passed. This
    builds an actual repo with an upstream, one dirty file and one unpushed
    commit, and pins both halves of the output - the --porcelain lines and
    the @{u}..HEAD count with its singular wording."""
    if not os.path.exists("/usr/bin/git"):
        pytest.skip("/usr/bin/git is not available on this machine")

    origin = tmp_path / "origin.git"
    subprocess.run(["/usr/bin/git", "init", "--bare", "-q", str(origin)], check=True)
    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "-q")
    _git(work, "symbolic-ref", "HEAD", "refs/heads/main")
    _git(work, "config", "user.email", "resume-gate-test@example.invalid")
    _git(work, "config", "user.name", "resume-gate test")
    (work / "first.txt").write_text("one\n")
    _git(work, "add", "first.txt")
    _git(work, "commit", "-q", "-m", "first")
    _git(work, "remote", "add", "origin", str(origin))
    _git(work, "push", "-q", "-u", "origin", "main")

    # One commit made after the push: unpushed.
    (work / "second.txt").write_text("two\n")
    _git(work, "add", "second.txt")
    _git(work, "commit", "-q", "-m", "second")
    # One tracked file modified but not committed: dirty.
    (work / "first.txt").write_text("one, edited\n")

    lines = rg.uncommitted_summary(str(work))
    assert any(line.strip().endswith("first.txt") and line.startswith(" M") for line in lines), lines
    assert "1 unpushed commit" in lines, lines
    assert "1 unpushed commits" not in lines, lines

def test_uncommitted_summary_pluralises_and_caps_the_porcelain_lines(tmp_path):
    """Two unpushed commits must read "2 unpushed commits", and the dirty
    list is capped at 20 entries - both are wording/limit rules nothing else
    exercises."""
    if not os.path.exists("/usr/bin/git"):
        pytest.skip("/usr/bin/git is not available on this machine")

    origin = tmp_path / "origin2.git"
    subprocess.run(["/usr/bin/git", "init", "--bare", "-q", str(origin)], check=True)
    work = tmp_path / "work2"
    work.mkdir()
    _git(work, "init", "-q")
    _git(work, "symbolic-ref", "HEAD", "refs/heads/main")
    _git(work, "config", "user.email", "resume-gate-test@example.invalid")
    _git(work, "config", "user.name", "resume-gate test")
    (work / "base.txt").write_text("base\n")
    _git(work, "add", "base.txt")
    _git(work, "commit", "-q", "-m", "base")
    _git(work, "remote", "add", "origin", str(origin))
    _git(work, "push", "-q", "-u", "origin", "main")

    for n in range(2):
        (work / ("c%d.txt" % n)).write_text("c\n")
        _git(work, "add", "c%d.txt" % n)
        _git(work, "commit", "-q", "-m", "commit %d" % n)
    for n in range(25):
        (work / ("dirty%02d.txt" % n)).write_text("dirty\n")

    lines = rg.uncommitted_summary(str(work))
    assert "2 unpushed commits" in lines, lines
    porcelain = [line for line in lines if line.startswith("??")]
    assert len(porcelain) == 20, len(porcelain)

def test_session_start_includes_uncommitted_work_when_present(monkeypatch):
    monkeypatch.setattr(rg, "uncommitted_summary", lambda cwd: [" M docs/thing.html", "1 unpushed commit"])
    code, out, err = rg.run_session_start(_payload("incident"))
    ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert "docs/thing.html" in ctx and "1 unpushed commit" in ctx


def _pre(name, tool="Bash", command="git push origin HEAD"):
    return {
        "transcript_path": str(FIX / f"{name}.jsonl"),
        "tool_name": tool,
        "tool_input": {"command": command},
    }

def test_pre_tool_use_asks_when_a_mark_lists_outstanding_items(tmp_path):
    src = (FIX / "incident.jsonl").read_text(encoding="utf-8")
    marked = tmp_path / "marked.jsonl"
    marked.write_text(
        src + json.dumps({"type": "user", "content": rg.encode_mark(["Fix three disclosure defects"])}) + "\n",
        encoding="utf-8",
    )
    code, out, err = rg.run_pre_tool_use({"transcript_path": str(marked), "tool_name": "Bash",
                                          "tool_input": {"command": "git push origin HEAD"}})
    assert code == 0
    body = json.loads(out)["hookSpecificOutput"]
    assert body["permissionDecision"] == "ask"
    assert "Fix three disclosure defects" in body["permissionDecisionReason"]

def test_pre_tool_use_allows_when_the_mark_is_empty(tmp_path):
    marked = tmp_path / "empty.jsonl"
    marked.write_text(json.dumps({"type": "user", "content": rg.encode_mark([])}) + "\n", encoding="utf-8")
    code, out, err = rg.run_pre_tool_use({"transcript_path": str(marked), "tool_name": "Bash",
                                          "tool_input": {"command": "git push origin HEAD"}})
    assert (code, out.strip()) == (0, "")

def test_pre_tool_use_falls_back_to_detection_with_no_mark():
    """No mark at all (the None state) with a genuine incident must ask,
    and the reason must name the actual outstanding item — not just any
    truthy decision — so this pins the None branch's positive case."""
    code, out, err = rg.run_pre_tool_use(_pre("incident"))
    body = json.loads(out)["hookSpecificOutput"]
    assert body["permissionDecision"] == "ask"
    assert "Fix three disclosure defects" in body["permissionDecisionReason"]

def test_pre_tool_use_empty_mark_short_circuits_detection_entirely(monkeypatch, tmp_path):
    """Discriminates [] from None directly, not by inference from the output.

    If the code ever falls back to detect() when the mark decodes to an
    empty list (conflating [] with the None "no mark" state), the patched
    detect() below raises and this test fails. Under correct behaviour
    detect() is never called at all when a mark exists.
    """
    def _boom(entries):
        raise AssertionError("detect() must not run when a mark exists")
    monkeypatch.setattr(rg, "detect", _boom)
    marked = tmp_path / "empty_only.jsonl"
    marked.write_text(json.dumps({"type": "user", "content": rg.encode_mark([])}) + "\n", encoding="utf-8")
    code, out, err = rg.run_pre_tool_use({"transcript_path": str(marked), "tool_name": "Bash",
                                          "tool_input": {"command": "git push origin HEAD"}})
    assert (code, out.strip()) == (0, "")

def test_pre_tool_use_empty_mark_wins_over_a_hit_that_appears_after_it(tmp_path):
    """An empty mark must be trusted even when the session dispatches more
    subagent work afterwards - a realistic case (warned once at resume,
    then kept going).

    Builds: the incident fixture's rows (which contain the Agent tool_use
    call and its needle-bearing tool_result), then an empty mark, then a
    duplicate of that same needle-bearing row placed AFTER the mark. Under
    the wrong behaviour - falling back to detect() because [] got treated
    like "no mark" - window_after_last_mark would cover exactly that
    duplicated row and detect() would find the hit and ask. Under correct
    behaviour the empty mark alone decides, and that row is never consulted.

    The row is located by the Signature A call's tool_use id rather than by
    position, so the fixture can grow rows without silently selecting a
    different one. If make_fixtures.py renames that id, this raises
    StopIteration rather than quietly testing nothing.
    """
    src_lines = (FIX / "incident.jsonl").read_text(encoding="utf-8").splitlines()
    needle_row = next(l for l in src_lines
                      if "toolu_incident_disclosure_fixes" in l and '"tool_result"' in l)
    marked = tmp_path / "hit_after_empty_mark.jsonl"
    marked.write_text(
        "\n".join(src_lines) + "\n"
        + json.dumps({"type": "user", "content": rg.encode_mark([])}) + "\n"
        + needle_row + "\n",
        encoding="utf-8",
    )
    code, out, err = rg.run_pre_tool_use({"transcript_path": str(marked), "tool_name": "Bash",
                                          "tool_input": {"command": "git push origin HEAD"}})
    assert (code, out.strip()) == (0, "")

def test_pre_tool_use_allows_a_clean_session():
    code, out, err = rg.run_pre_tool_use(_pre("clean"))
    assert (code, out.strip()) == (0, "")

def test_pre_tool_use_exits_2_when_the_transcript_path_is_unreadable(tmp_path):
    """Fail-closed on a real error. A directory, not a missing file: a missing
    file is now the allow-and-say-so branch below, so reusing it here would
    make this test and that one contradict each other."""
    code, out, err = rg.run_pre_tool_use({"transcript_path": str(tmp_path), "tool_name": "Bash"})
    assert code == 2

def test_pre_tool_use_exits_2_when_the_payload_has_no_transcript_path():
    """The KeyError path. A payload shaped differently from what the harness
    documents is a surprise with no known cause, so it still blocks - only a
    path that names nothing is treated as "there is nothing to check"."""
    code, out, err = rg.run_pre_tool_use({"tool_name": "Bash"})
    assert code == 2
    assert "resume-gate" in err

def test_pre_tool_use_allows_and_says_so_when_the_transcript_does_not_exist(tmp_path):
    """Regression for 2026-08-12.

    An interactive session that inherits CLAUDE_CODE_CHILD_SESSION writes no
    transcript at all. `load()` then raised FileNotFoundError, the outer
    handler exited 2, and exit 2 BLOCKS - so git push, gh pr merge, gh api and
    every gated publish tool failed in every project on the machine, with an
    error naming the exception and nothing that would connect it to session
    persistence.

    Blocking protected nothing: with no transcript there is no mark to read
    and no rows for detect() to scan, so the gate could not have fired either
    way. It must allow.

    But it must not go quiet about it - a check that silently did nothing is
    the fail-open defect this tool exists to avoid. Pinning the exact payload
    (rather than just `code == 0`) is what makes both halves fail separately:
    restore the block and the code assertion fails; drop the message and the
    payload assertion fails."""
    missing = tmp_path / "never-written.jsonl"
    assert not missing.exists()
    code, out, err = rg.run_pre_tool_use({"transcript_path": str(missing), "tool_name": "Bash",
                                          "tool_input": {"command": "git push origin HEAD"}})
    assert (code, err) == (0, "")
    assert json.loads(out) == {"systemMessage": rg.NO_TRANSCRIPT_MESSAGE}

def test_the_no_transcript_message_names_the_cause_and_the_remedy():
    """The whole point of the message is that the next person does not have to
    rediscover the connection between a blocked push and session persistence.
    A message reading only "no transcript" would satisfy the tests above."""
    assert "CLAUDE_CODE_CHILD_SESSION" in rg.NO_TRANSCRIPT_MESSAGE
    assert "CLAUDE_CODE_FORCE_SESSION_PERSISTENCE=1" in rg.NO_TRANSCRIPT_MESSAGE


def test_main_unknown_mode_exits_2_with_stderr_message(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["resume_gate.py", "bogus-mode"])
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"a": 1})))
    code = rg.main()
    assert code == 2
    captured = capsys.readouterr()
    assert "bogus-mode" in captured.err
    assert len(captured.err.strip().splitlines()) == 1

def test_main_unreadable_json_exits_2_with_one_line_on_stderr(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["resume_gate.py", "session-start"])
    monkeypatch.setattr(sys, "stdin", io.StringIO("not valid json"))
    code = rg.main()
    assert code == 2
    captured = capsys.readouterr()
    assert len(captured.err.strip().splitlines()) == 1
    assert "resume-gate" in captured.err

def test_main_routes_session_start_mode_to_run_session_start(monkeypatch, capsys):
    monkeypatch.setattr(rg, "run_session_start", lambda payload: (0, "SESSION-START-SENTINEL", ""))
    monkeypatch.setattr(sys, "argv", ["resume_gate.py", "session-start"])
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"source": "resume"})))
    code = rg.main()
    assert code == 0
    assert capsys.readouterr().out == "SESSION-START-SENTINEL"

def test_main_routes_pre_tool_use_mode_to_run_pre_tool_use(monkeypatch, capsys):
    monkeypatch.setattr(rg, "run_pre_tool_use", lambda payload: (0, "PRE-TOOL-USE-SENTINEL", ""))
    monkeypatch.setattr(sys, "argv", ["resume_gate.py", "pre-tool-use"])
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"tool_name": "Bash"})))
    code = rg.main()
    assert code == 0
    assert capsys.readouterr().out == "PRE-TOOL-USE-SENTINEL"
