#!/usr/bin/env python3
"""Install resume-gate into ~/.claude/settings.json.

Running this file's main() is a decision for a human to make explicitly -
it edits the user's GLOBAL Claude Code config, which applies to every
project on the machine, not just this one. Nothing in the test
suite calls main(); tests exercise build_config() only, with a fake script
path, and never touch the real settings file.

Two mechanisms, do not conflate them (see DESIGN.md, Component 2):
  - The top-level `matcher` is a regex on the TOOL NAME ONLY. It cannot see
    the command a Bash call runs.
  - The `if` field is what evaluates Bash(git push:*)-style patterns against
    the actual command. It is a HANDLER-level field: a sibling of `type` and
    `command`, INSIDE the inner `hooks` array - NOT a sibling of `matcher`.

      {"matcher": "^Bash$",
       "hooks": [{"type": "command", "if": "Bash(git push:*)", "command": ...}]}

    Putting `if` next to `matcher` is silent and total: it is an
    unrecognised key at that level, so it is dropped, and what remains is a
    handler matching bare Bash with no condition - every Bash call prompts,
    once per ship condition, each prompt preceded by a full JSON parse of an
    11 MB transcript.

The matcher is also an UNANCHORED regex, tested with RegExp.prototype.test,
so "Bash" matches BashOutput too. Anchor it: "^Bash$".

A matcher like "Bash(git *)" would match no tool name at all and the gate
would silently never fire.

WHERE this runs from is a correctness property, not a preference. The hook
config stores an ABSOLUTE PATH to resume_gate.py, and if that path later
stops existing, `python3 /gone/resume_gate.py` exits 2 - which for PreToolUse
BLOCKS THE TOOL CALL. Every push and merge in every project on the machine
then fails, and the error names nothing that would let you find the cause.
That has happened once already, from a scratch worktree. Installing straight
out of a plugin cache is the same bug with a longer fuse: the path carries a
version segment, so the next plugin upgrade orphans it. See
unstable_install_reason().
"""
import json
import os
import pathlib
import sys

# Always present on macOS; never resolved via PATH. Hook PATH is not shell
# PATH - observed repeatedly as `hook error: /bin/sh: node: command not
# found` because nvm's node was not on it, and `find` can resolve to a
# different binary inside a hook than in an interactive shell (DESIGN.md,
# Component 3). Resolving the interpreter via `sys.executable`,
# `shutil.which("python3")`, or any Homebrew/pyenv path inherits that same
# problem.
INTERPRETER = "/usr/bin/python3"

# Anchored: the matcher is an unanchored regex, so a bare "Bash" also
# matches BashOutput (and any future Bash-prefixed tool).
BASH_MATCHER = "^Bash$"

# Ship set, minimum required by the design: push, the `git push origin
# <branch>:main` merge fallback (contains "push" but not "merge", so it is
# covered by the git push condition below), PR merge, PR create, the
# label-add that triggers auto-deploy with no push or merge verb at all, the
# REST-API merge path, and release creation.
#
# `Bash(git push:*)` is PREFIX matching, so it does not cover
# `git -C <path> push` - the command starts "git -C", not "git push". Any
# worktree-based workflow uses that form constantly, and resume_gate.py
# itself shells out with `git -C`, so it needs its own condition.
SHIP_CONDITIONS = [
    "Bash(git push:*)",
    "Bash(git -C * push:*)",
    "Bash(gh pr merge:*)",
    "Bash(gh pr create:*)",
    "Bash(gh pr edit:*)",
    "Bash(gh api:*)",
    "Bash(gh release create:*)",
]

# KNOWN DEVIATION from DESIGN.md's Component 2, accepted deliberately: the
# spec asks for this union to be DERIVED at install time from the tools
# actually present, and it is not - it is a maintained constant. A Python
# installer cannot enumerate the harness's live tool list - that
# derivation is honestly out of reach from inside install.py. What must not
# happen is this union being hard-coded INSIDE build_config, where nobody
# reviewing that function could change it. So main() maintains this default
# and prints it for confirmation before use; build_config takes the list as
# a parameter so it stays testable and overridable. Re-run the installer
# after connecting a new MCP server that can publish client-facing output.
DEFAULT_PUBLISH_TOOLS = [
    "Artifact",
    "ShareOnboardingGuide",
    "DesignSync",
    "mcp__claude_ai_Atlassian__createConfluencePage",
    "mcp__claude_ai_Atlassian__updateConfluencePage",
    "mcp__claude_ai_Google_Drive__create_file",
    "mcp__claude_ai_Gmail__create_draft",
]


def _command(script_path, mode, condition=None):
    handler = {"type": "command", "command": "%s %s %s" % (INTERPRETER, script_path, mode)}
    if condition is not None:
        # Handler-level, alongside "type" and "command". See the module
        # docstring for what happens when this lands next to "matcher".
        handler["if"] = condition
    return handler


def build_config(script_path, publish_tools):
    """Build the {"SessionStart": [...], "PreToolUse": [...]} hooks block.

    script_path: absolute path to resume_gate.py on disk.
    publish_tools: tool names (Bash excluded) to gate as publish paths, e.g.
        ["Artifact", "mcp__claude_ai_Atlassian__createConfluencePage"].
        Pass [] to omit the non-Bash handler entirely.
    """
    pre_tool_use = [
        {"matcher": BASH_MATCHER, "hooks": [_command(script_path, "pre-tool-use", condition)]}
        for condition in SHIP_CONDITIONS
    ]
    if publish_tools:
        pre_tool_use.append({
            "matcher": "^(%s)$" % "|".join(publish_tools),
            "hooks": [_command(script_path, "pre-tool-use")],
        })
    return {
        "SessionStart": [
            {"matcher": "resume", "hooks": [_command(script_path, "session-start")]}
        ],
        "PreToolUse": pre_tool_use,
    }


# The one location this installer treats as stable. A whitelist, not a
# blacklist of bad paths: the failure it prevents is severe (every push on the
# machine blocked by a hook whose script no longer exists) and the set of
# disappearing paths is not enumerable - a plugin cache, a git worktree, a
# branch checkout that will be switched, /tmp, a mounted volume, a directory
# you will rename next month. Naming the one place that survives is honest;
# listing the places that do not is a guess.
STABLE_INSTALL_ROOT = "~/.claude/tools"

OVERRIDE_FLAG = "--allow-unstable-path"


def unstable_install_reason(script_path, home=None):
    """Why installing from `script_path` is unsafe, or None if it is fine.

    Pure and testable: main() calls it, the tests call it directly, and
    nothing in the test suite has to run main() to exercise the check.
    """
    home = home if home is not None else os.path.expanduser("~")
    stable = os.path.join(home, "tools" if home.endswith(".claude") else ".claude/tools")
    stable = os.path.normpath(stable)
    resolved = os.path.normpath(str(script_path))
    if resolved == stable or resolved.startswith(stable + os.sep):
        return None
    return (
        "resume-gate would be installed from %s, which is not under %s.\n"
        "The hook config stores this absolute path. If it ever stops existing - a\n"
        "plugin upgrade replacing a versioned cache directory, a worktree removed, a\n"
        "branch switched - the hook exits 2, and for PreToolUse exit 2 BLOCKS the tool\n"
        "call. Every push and merge in every project on this machine would fail, with\n"
        "nothing in the error naming the cause.\n"
        "\n"
        "Copy it somewhere stable and install from there:\n"
        "\n"
        "  cp ~/.claude/settings.json ~/.claude/settings.json.pre-resume-gate.bak\n"
        "  mkdir -p %s/resume-gate\n"
        "  cp resume_gate.py install.py %s/resume-gate/\n"
        "  cd %s/resume-gate && python3 install.py\n"
        "\n"
        "If you have a stable location of your own, re-run with %s."
        % (resolved, stable, STABLE_INSTALL_ROOT, STABLE_INSTALL_ROOT,
           STABLE_INSTALL_ROOT, OVERRIDE_FLAG)
    )


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    script = str(pathlib.Path(__file__).resolve().parent / "resume_gate.py")
    settings_path = pathlib.Path(os.path.expanduser("~/.claude/settings.json"))

    reason = unstable_install_reason(script)
    if reason and OVERRIDE_FLAG not in argv:
        sys.stderr.write(reason + "\n")
        return 1
    if reason:
        print("resume-gate: %s given; installing from an unstable path anyway."
              % OVERRIDE_FLAG)

    publish_tools = list(DEFAULT_PUBLISH_TOOLS)
    print("resume-gate: gating these publish tools (edit DEFAULT_PUBLISH_TOOLS in")
    print("install.py and re-run to change, e.g. after connecting a new MCP server):")
    for tool in publish_tools:
        print("  - %s" % tool)

    current = json.loads(settings_path.read_text(encoding="utf-8")) if settings_path.exists() else {}
    hooks = current.setdefault("hooks", {})
    new_config = build_config(script, publish_tools)
    for event, handlers in new_config.items():
        # Drop any handlers this installer previously wrote (identified by
        # invoking resume_gate.py), then add the current set back. This
        # makes re-running the installer idempotent instead of duplicating
        # handlers on every run.
        existing = hooks.get(event, [])
        hooks[event] = [h for h in existing if "resume_gate.py" not in json.dumps(h)]
        hooks[event].extend(handlers)

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
    print("resume-gate: installed into %s" % settings_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
