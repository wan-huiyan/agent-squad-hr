"""Tests for install.build_config() and unstable_install_reason().

Never call install.main() from here - it would write to the real
~/.claude/settings.json on whatever machine runs the tests. Installing is a
decision a human makes deliberately, not a byproduct of pytest, so every
check below runs against a pure function with a fake script path.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import install


def _bash_groups(cfg):
    return [h for h in cfg["PreToolUse"] if h["matcher"] == install.BASH_MATCHER]


def _conditions(handler):
    return [inner.get("if") for inner in handler["hooks"]]


def test_bash_handler_matches_on_tool_name_not_command():
    """The top-level matcher is a regex on the tool name only - it cannot
    see the command. Writing matcher: "Bash(git *)" would silently match
    no tool name and the gate would never fire; this asserts the matcher
    stays the bare tool name."""
    cfg = install.build_config("/x/resume_gate.py", [])
    bash = _bash_groups(cfg)
    assert bash, "expected at least one handler matching the bare tool name Bash"
    for handler in bash:
        assert "Bash(" not in handler["matcher"], (
            "matcher must not carry a command pattern: %r" % handler["matcher"]
        )


def test_bash_matcher_is_anchored_so_it_does_not_also_match_bashoutput():
    """The matcher is an UNANCHORED regex (RegExp.prototype.test), so a bare
    "Bash" also matches BashOutput and any future Bash-prefixed tool. Only
    the exact tool name should be gated."""
    import re

    cfg = install.build_config("/x/resume_gate.py", [])
    bash = _bash_groups(cfg)
    assert bash
    for handler in bash:
        pattern = re.compile(handler["matcher"])
        assert pattern.search("Bash"), handler["matcher"]
        assert not pattern.search("BashOutput"), (
            "matcher %r also matches BashOutput - anchor it" % handler["matcher"]
        )


def test_if_is_a_handler_level_field_not_a_sibling_of_matcher():
    """`if` belongs INSIDE the inner hooks array, next to `type` and
    `command`. At the matcher-group level it is an unrecognised key and is
    dropped silently, leaving a condition-less handler that prompts on every
    Bash call, once per ship condition."""
    cfg = install.build_config("/x/resume_gate.py", ["Artifact"])
    for handler in cfg["PreToolUse"] + cfg["SessionStart"]:
        assert "if" not in handler, (
            "`if` sits at the matcher-group level, where it is ignored: %r" % handler
        )


def test_every_bash_handler_carries_an_if_condition_on_its_inner_handler():
    """A Bash-matched group whose inner handler has no `if` would ask on
    every single Bash call - fails if a group is ever added without one."""
    cfg = install.build_config("/x/resume_gate.py", [])
    bash = _bash_groups(cfg)
    assert bash
    for handler in bash:
        assert handler["hooks"], handler
        for inner in handler["hooks"]:
            assert inner.get("if"), "inner Bash handler %r has no if condition" % inner


def test_ship_conditions_cover_the_documented_merge_fallback():
    cfg = install.build_config("/x/resume_gate.py", [])
    joined = " ".join(
        inner.get("if", "") for h in cfg["PreToolUse"] for inner in h["hooks"]
    )
    for needed in ("git push", "gh pr merge", "gh pr create", "gh pr edit", "gh release create", "gh api"):
        assert needed in joined, "ship set misses %r" % needed


def test_ship_conditions_cover_git_dash_c_push():
    """`Bash(git push:*)` is prefix matching and does not cover
    `git -C <path> push`, which is how work happens in a worktree - and how
    resume_gate.py itself shells out."""
    cfg = install.build_config("/x/resume_gate.py", [])
    conditions = [inner.get("if") for h in cfg["PreToolUse"] for inner in h["hooks"]]
    assert "Bash(git -C * push:*)" in conditions, conditions


def test_ship_conditions_are_bash_scoped_patterns_not_bare_verbs():
    """Each condition must be a Bash(...) pattern - a bare verb string like
    "git push" with no Bash() wrapper would not be a valid hook `if` and
    would silently fail to gate anything."""
    cfg = install.build_config("/x/resume_gate.py", [])
    for handler in _bash_groups(cfg):
        for inner in handler["hooks"]:
            assert inner["if"].startswith("Bash("), inner["if"]


def test_publish_tools_are_injected_not_frozen():
    """build_config must take the publish-tool union as a parameter rather
    than hard-coding it, since a Python installer cannot enumerate the
    harness's live tool list at import time."""
    cfg = install.build_config("/x/resume_gate.py", ["Artifact", "mcp__x__y"])
    matchers = [h["matcher"] for h in cfg["PreToolUse"]]
    assert any("Artifact" in m and "mcp__x__y" in m for m in matchers)


def test_publish_tools_differ_between_calls():
    """Calling build_config with two different tool lists must produce two
    different configs - if the union were frozen inside the function, both
    calls would return the same matcher regardless of the argument."""
    cfg_a = install.build_config("/x/resume_gate.py", ["Artifact"])
    cfg_b = install.build_config("/x/resume_gate.py", ["DesignSync"])
    matchers_a = [h["matcher"] for h in cfg_a["PreToolUse"]]
    matchers_b = [h["matcher"] for h in cfg_b["PreToolUse"]]
    assert matchers_a != matchers_b


def test_empty_publish_tools_adds_no_extra_handler():
    """Absent tools in a union are harmless (per DESIGN.md) - an empty list
    must not add a spurious handler with an empty or malformed matcher."""
    cfg = install.build_config("/x/resume_gate.py", [])
    non_bash = [h for h in cfg["PreToolUse"] if h["matcher"] != install.BASH_MATCHER]
    assert non_bash == []


def test_publish_tool_handler_has_no_if_condition():
    """Non-Bash publish tools are gated purely on tool name - there is no
    command to evaluate an `if` against, unlike the Bash handlers."""
    cfg = install.build_config("/x/resume_gate.py", ["Artifact"])
    non_bash = [h for h in cfg["PreToolUse"] if h["matcher"] != install.BASH_MATCHER]
    assert non_bash, "expected a publish-tool handler"
    for handler in non_bash:
        assert "if" not in handler
        for inner in handler["hooks"]:
            assert "if" not in inner


def test_session_start_handler_is_scoped_to_resume():
    cfg = install.build_config("/x/resume_gate.py", [])
    assert cfg["SessionStart"][0]["matcher"] == "resume"


def test_interpreter_is_absolute():
    """Hook PATH is not shell PATH - the installer must resolve the
    interpreter to an absolute path rather than relying on `python3` being
    found on whatever PATH the hook runs under."""
    cfg = install.build_config("/x/resume_gate.py", [])
    command = cfg["SessionStart"][0]["hooks"][0]["command"]
    assert command.startswith("/usr/bin/python3 "), command


def test_every_hook_command_invokes_the_given_script_path():
    """A stub that hard-coded some other script path, or dropped the mode
    argument, would still pass the interpreter-prefix test above - this
    checks the full command line for both entry points."""
    cfg = install.build_config("/x/resume_gate.py", [])
    session_start_cmd = cfg["SessionStart"][0]["hooks"][0]["command"]
    assert session_start_cmd == "/usr/bin/python3 /x/resume_gate.py session-start"
    for handler in cfg["PreToolUse"]:
        pre_cmd = handler["hooks"][0]["command"]
        assert pre_cmd == "/usr/bin/python3 /x/resume_gate.py pre-tool-use"


def test_install_from_the_plugin_cache_is_refused():
    """The path that ships this tool is the most dangerous one to install from.

    A plugin cache path carries a VERSION segment, so the next `/plugin
    update` replaces the directory and the hook's stored absolute path stops
    resolving. For PreToolUse, a hook that exits 2 blocks the tool call - so
    every push and merge in every project on the machine fails, with nothing
    in the error naming the cause. Whoever finds this tool will find it here
    first, which is exactly why the check has to exist rather than being a
    line in the README.
    """
    reason = install.unstable_install_reason(
        "/home/example/.claude/plugins/cache/some-marketplace/agent-traffic-control/"
        "1.16.0/plugins/agent-traffic-control/hooks/resume-gate/resume_gate.py",
        home="/home/example",
    )
    assert reason is not None
    assert install.OVERRIDE_FLAG in reason, "the refusal must name its own override"
    assert "~/.claude/tools" in reason, "the refusal must name where to put it instead"


def test_install_from_a_worktree_is_refused():
    """The original failure: installed from a scratch worktree, verified live,
    then the worktree was removed and every push on the machine broke."""
    assert install.unstable_install_reason(
        "/home/example/code/project/.claude/worktrees/scratch/tools/resume_gate.py",
        home="/home/example",
    ) is not None


def test_install_from_tmp_is_refused():
    assert install.unstable_install_reason(
        "/tmp/resume-gate/resume_gate.py", home="/home/example") is not None


def test_a_missing_script_is_refused_and_the_refusal_is_not_overridable(tmp_path):
    """Installing a path that does not exist is the same disaster as
    installing one that later stops existing, arriving sooner: a PreToolUse
    hook whose script is missing exits 2, and exit 2 blocks the tool call.

    The remedy the installer prints is a two-file `cp`; copying only
    install.py is an easy miss. Unlike the stable-path check, this one has no
    override - where a file lives is a judgement call, whether it exists is
    not.
    """
    missing = tmp_path / "resume-gate" / "resume_gate.py"
    reason = install.missing_script_reason(str(missing))
    assert reason is not None
    assert "resume_gate.py install.py" in reason, "must show copying BOTH files"
    assert install.OVERRIDE_FLAG not in reason, "a missing script is not overridable"


def test_an_existing_script_passes_the_existence_check(tmp_path):
    """The check is worthless if it also refuses a real file."""
    present = tmp_path / "resume_gate.py"
    present.write_text("# stub\n", encoding="utf-8")
    assert install.missing_script_reason(str(present)) is None


def test_a_directory_is_not_mistaken_for_the_script(tmp_path):
    """os.path.exists() would accept a directory named resume_gate.py."""
    d = tmp_path / "resume_gate.py"
    d.mkdir()
    assert install.missing_script_reason(str(d)) is not None


def test_a_symlinked_home_does_not_refuse_the_correct_directory(tmp_path):
    """main() resolves symlinks when deriving the script path, so the check
    must resolve them too - otherwise, on any system where the home directory
    sits behind a symlink (ostree-based distributions ship exactly this), a
    user standing in the recommended directory is refused and told to copy
    the files into the directory they are already in."""
    real_home = tmp_path / "var" / "home" / "example"
    (real_home / ".claude" / "tools" / "resume-gate").mkdir(parents=True)
    script = real_home / ".claude" / "tools" / "resume-gate" / "resume_gate.py"
    script.write_text("# stub\n", encoding="utf-8")

    linked_home = tmp_path / "home-example"
    linked_home.symlink_to(real_home)

    assert install.unstable_install_reason(
        str(linked_home / ".claude" / "tools" / "resume-gate" / "resume_gate.py"),
        home=str(linked_home),
    ) is None


def test_install_from_the_stable_tools_directory_is_allowed():
    """The whole check is worthless if it also refuses the recommended path."""
    assert install.unstable_install_reason(
        "/home/example/.claude/tools/resume-gate/resume_gate.py",
        home="/home/example",
    ) is None


def test_a_sibling_directory_with_the_same_prefix_is_not_mistaken_for_the_stable_root():
    """`startswith` on a bare string would accept ~/.claude/tools-old/ and
    ~/.claude/toolsomething/. The check must compare path SEGMENTS."""
    for impostor in ("/home/example/.claude/tools-backup/resume_gate.py",
                     "/home/example/.claude/toolsmith/resume_gate.py"):
        assert install.unstable_install_reason(impostor, home="/home/example") is not None, impostor


def test_the_stable_root_is_resolved_against_the_given_home_not_a_fixed_string():
    """Two different homes must produce two different verdicts for the same
    path - otherwise the check is reading a baked-in path and would pass or
    fail identically for every user."""
    path = "/home/alice/.claude/tools/resume-gate/resume_gate.py"
    assert install.unstable_install_reason(path, home="/home/alice") is None
    assert install.unstable_install_reason(path, home="/home/bob") is not None


def test_script_path_is_not_hardcoded():
    """build_config must use its script_path argument, not a baked-in path -
    calling it with a different path must change the emitted command."""
    cfg = install.build_config("/somewhere/else/resume_gate.py", [])
    command = cfg["SessionStart"][0]["hooks"][0]["command"]
    assert "/somewhere/else/resume_gate.py" in command
    assert "/x/resume_gate.py" not in command
