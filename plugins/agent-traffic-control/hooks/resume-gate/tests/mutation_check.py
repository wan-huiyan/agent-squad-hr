#!/usr/bin/env python3
"""Mutation harness — break each guard, confirm the suite notices.

    python3 tests/mutation_check.py          # exit 0 = every mutation killed

Why this is committed rather than run once and quoted. Six tests in this
tool's first build could not fail, and each one hid a real defect: an
`assert isinstance(hits, list)` that passes for `[]`, a positive path
monkeypatched away, three installer tests that asserted strings appeared
without asserting where they sat. Writing real-looking test code is not
writing a test, and the only thing that reliably tells the difference is
breaking the code and watching.

A quoted mutation score is also not reproducible. An earlier revision of this
README claimed "25 mutations, 25 killed" with no list committed; an
independent reviewer then ran a different set and **7 of 13 survived**, each
one a real gap. Every mutation below that reviewer found is now in this list,
so the claim can be re-checked rather than believed.

Each entry deletes or inverts ONE guard and names the property it removes. A
mutation that nothing catches is a test gap, not a passing grade — fix the
test, do not delete the mutation.

Some fixture mutations are expected to be caught by make_fixtures.py's own
assertions rather than by pytest; those report GENERATOR-REFUSED, which is a
kill (the fixture could not be built wrong in the first place).

THIS HARNESS SCORES A MUTANT "KILLED" ON A NON-ZERO PYTEST EXIT CODE, and until
v1.27.0 it did not ask WHY the exit was non-zero. Anything that stops pytest
running therefore read as a kill. Measured on a machine with no pytest module
installed: `python3 tests/mutation_check.py` printed "41 mutations, 41 killed, 0
needing attention" and exited 0, having executed no test at all. A perfect score
from a harness that never ran — the same failure shape as a leak gate that prints
"clean" because its denylist was empty.

So `preflight()` now proves, before any mutant is scored, that pytest is
importable AND that the UNMUTATED suite passes. A green run means the kills are
real; a refusal names the reason. CI installs pytest explicitly and the pre-push
hook resolves an interpreter that has it, so neither path reaches the refusal
silently.
"""
import pathlib
import shutil
import subprocess
import sys
import tempfile

HOOK = pathlib.Path(__file__).resolve().parents[1]

# (label, relative file, old, new, regenerate fixtures first?)
MUTATIONS = [
    # ---- Signature A ----
    ("A: drop the prefix anchor (rule 2)", "resume_gate.py",
     "            if not text.lstrip().startswith(PREFIX):\n                continue\n", "", False),
    ("A: drop the lstrip before anchoring", "resume_gate.py",
     "text.lstrip().startswith(PREFIX)", "text.startswith(PREFIX)", False),
    ("A: drop the Agent-resolution guard (rule 1)", "resume_gate.py",
     '            if block.get("tool_use_id") not in agents:\n                continue\n', "", False),
    # ---- Signature B ----
    ("B: drop the status gate", "resume_gate.py",
     "if count > 0 and status.get(tid) != COMPLETED and tid in agents",
     "if count > 0 and tid in agents", False),
    ("B: drop the enqueue/remove balance gate", "resume_gate.py",
     "if count > 0 and status.get(tid) != COMPLETED and tid in agents",
     "if count >= 0 and status.get(tid) != COMPLETED and tid in agents", False),
    ("B: drop the Agent-resolution gate, restore the fallback label", "resume_gate.py",
     "        agents[tid]\n        for tid, count in balance.items()\n"
     "        if count > 0 and status.get(tid) != COMPLETED and tid in agents",
     '        agents.get(tid, "(async task %s)" % tid)\n        for tid, count in balance.items()\n'
     "        if count > 0 and status.get(tid) != COMPLETED", False),
    ("B: treat a missing status as completed", "resume_gate.py",
     "status[tool_use_id] = status_match.group(1) if status_match else None",
     "status[tool_use_id] = status_match.group(1) if status_match else COMPLETED", False),
    ("B: accept queue rows that are not task-notifications", "resume_gate.py",
     "if not isinstance(content, str) or not content.lstrip().startswith(TASK_NOTIFICATION):",
     "if not isinstance(content, str) or False:", False),
    ("B: first-write-wins on status instead of last", "resume_gate.py",
     "        status[tool_use_id] = status_match.group(1) if status_match else None",
     "        status.setdefault(tool_use_id, status_match.group(1) if status_match else None)", False),
    # ---- the mark ----
    ("mark: accept a corrupt mark as the segment boundary", "resume_gate.py",
     "    for index, items in reversed(_marks(entries)):\n"
     "        if items is not None:\n            return entries[index + 1:]\n    return entries",
     "    marks = _marks(entries)\n    if not marks:\n        return entries\n"
     "    return entries[marks[-1][0] + 1:]", False),
    ("mark: swallow the decode exception and return []", "resume_gate.py",
     "    except (binascii.Error, UnicodeDecodeError, ValueError):\n        return None",
     "    except (binascii.Error, UnicodeDecodeError, ValueError):\n        return []", False),
    ("mark: drop the declared-count check", "resume_gate.py",
     "    if len(items) != int(match.group(1)):\n        return None", "", False),
    ("mark: first match on a line wins instead of the last", "resume_gate.py",
     "        for match in _MARK_RE.finditer(raw):\n            found.append((index, _decode_mark(match)))",
     "        m = list(_MARK_RE.finditer(raw))\n        if m:\n            found.append((index, _decode_mark(m[0])))", False),
    ("mark: stop sanitising the item separator", "resume_gate.py",
     '    safe = [item.replace(_MARK_ITEM_SEP, " ") for item in items]', "    safe = list(items)", False),
    ("mark: fall back to an earlier mark's items when the newest is corrupt", "resume_gate.py",
     "    marks = _marks(entries)\n    if not marks:\n        return None\n    return marks[-1][1]",
     "    marks = _marks(entries)\n    if not marks:\n        return None\n"
     "    for _, items in reversed(marks):\n        if items is not None:\n            return items\n    return None", False),
    # ---- detector plumbing ----
    ("detect: drop the de-duplication", "resume_gate.py",
     "    for item in signature_a(window, agents) + signature_b(window, agents):\n"
     "        if item not in hits:\n            hits.append(item)",
     "    hits = signature_a(window, agents) + signature_b(window, agents)", False),
    ("detect: never window on the last mark", "resume_gate.py",
     "    window = window_after_last_mark(entries)", "    window = entries", False),
    ("_result_text: read only the first part", "resume_gate.py",
     '        return " ".join(\n            part.get("text", "") for part in content if isinstance(part, dict)\n        )',
     '        return content[0].get("text", "") if content else ""', False),
    ("_blocks: assume message is always a dict", "resume_gate.py",
     '    message = row.get("message")\n    if not isinstance(message, dict):\n        return []\n'
     '    content = message.get("content")',
     '    content = (row.get("message") or {}).get("content")', False),
    ("agent_calls: assume input is always a dict", "resume_gate.py",
     '                desc = tool_input.get("description") if isinstance(tool_input, dict) else None',
     '                desc = (tool_input or {}).get("description")', False),
    # ---- SessionStart branches ----
    ("session-start: never emit the clearing mark", "resume_gate.py",
     "            if not previous:\n", "            if True:\n", False),
    ("session-start: emit a clearing mark unconditionally", "resume_gate.py",
     "            if not previous:\n                # None (no mark, or an undecodable one) or [] (already\n"
     "                # clear): nothing is armed, so there is nothing to disarm.\n                return 0, \"\", \"\"\n",
     "", False),
    ("uncommitted_summary: return nothing", "resume_gate.py",
     "    import subprocess\n    lines = []", "    import subprocess\n    return []\n    lines = []", False),
    # ---- the missing-transcript branch ----
    # Anchored on `items = read_last_mark(entries)`, which appears only in
    # run_pre_tool_use - run_session_start has a near-identical except clause
    # and replace(old, new, 1) would otherwise hit that one instead.
    ("no-transcript: block the call instead of allowing it", "resume_gate.py",
     "        except FileNotFoundError:\n            return 0, json.dumps(_no_transcript_output()), \"\"\n"
     "        items = read_last_mark(entries)",
     "        except FileNotFoundError:\n            raise\n        items = read_last_mark(entries)", False),
    ("no-transcript: allow but say nothing", "resume_gate.py",
     "        except FileNotFoundError:\n            return 0, json.dumps(_no_transcript_output()), \"\"\n"
     "        items = read_last_mark(entries)",
     "        except FileNotFoundError:\n            return 0, \"\", \"\"\n        items = read_last_mark(entries)", False),
    ("no-transcript: drop the remedy from the message", "resume_gate.py",
     '    "no transcript; set CLAUDE_CODE_FORCE_SESSION_PERSISTENCE=1 to restore the guard."',
     '    "no transcript."', False),
    # ---- installer ----
    ("install: put `if` at the matcher-group level", "install.py",
     '        {"matcher": BASH_MATCHER, "hooks": [_command(script_path, "pre-tool-use", condition)]}',
     '        {"matcher": BASH_MATCHER, "if": condition,\n         "hooks": [_command(script_path, "pre-tool-use")]}', False),
    ("install: unanchor the Bash matcher", "install.py",
     'BASH_MATCHER = "^Bash$"', 'BASH_MATCHER = "Bash"', False),
    ("install: drop the git -C ship condition", "install.py",
     '    "Bash(git -C * push:*)",\n', "", False),
    ("install: never refuse an unstable path", "install.py",
     "    resolved = os.path.normpath(os.path.realpath(str(script_path)))",
     "    return None\n    resolved = os.path.normpath(os.path.realpath(str(script_path)))", False),
    ("install: bare prefix match instead of path segments", "install.py",
     "    if resolved == stable or resolved.startswith(stable + os.sep):",
     "    if resolved.startswith(stable):", False),
    ("install: hardcode the home directory", "install.py",
     '    home = os.path.realpath(home if home is not None else os.path.expanduser("~"))',
     '    home = "/home/alice"', False),
    ("install: stop resolving symlinks in the stable-path check", "install.py",
     '    home = os.path.realpath(home if home is not None else os.path.expanduser("~"))',
     '    home = home if home is not None else os.path.expanduser("~")', False),
    ("install: never check the script exists", "install.py",
     "    if os.path.isfile(script_path):\n        return None", "    return None", False),
    ("install: accept a directory as the script", "install.py",
     "    if os.path.isfile(script_path):", "    if os.path.exists(script_path):", False),
    # ---- fixtures ----
    ("fixture: anchor the discussion quote at position 0", "tests/make_fixtures.py",
     '    head = _pad_to(\n        "Review of the resume-gate design, second pass.\\n\\n"',
     '    head = _pad_to(\n        PREFIX + " Review of the resume-gate design, second pass.\\n\\n"', True),
    ("fixture: drop the needle from the discussion report", "tests/make_fixtures.py",
     '\n        + NEEDLE\n        + "\\", and this report quotes it',
     '\n        + "[redacted]"\n        + "\\", and this report quotes it', True),
    ("fixture: stop escaping the needle on disk", "tests/make_fixtures.py",
     '    return line.replace(NEEDLE, "PARTIAL output recovered from the \\\\u0061gent")',
     "    return line", True),
    ("fixture: balance the clean fixture's stray enqueues", "tests/make_fixtures.py",
     '    r.queue("2026-01-03T10:01:11.000Z", "enqueue",',
     '    r.queue("2026-01-03T10:01:11.000Z", "remove",', True),
    ("fixture: leave the consumed failure unconsumed", "tests/make_fixtures.py",
     '    r.queue("2026-01-02T09:02:15.000Z", "remove", consumed_failure)', "    pass", True),
    ("fixture: hand-edit a fixture without regenerating", "FIXTURE_EDIT", "", "", False),
]


def _run_pytest(cwd):
    return subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-q", "--tb=no", "-p", "no:cacheprovider"],
        cwd=cwd, capture_output=True, text=True)


def preflight():
    """Refuse to score anything until a kill is known to MEAN something.

    Two conditions, because they fail differently and a reader needs to know which:
    pytest must be importable, and the unmutated suite must PASS. If the clean tree
    already fails, every mutant's non-zero exit is inherited rather than caused, and
    the score is noise that reads as a pass.
    """
    probe = subprocess.run([sys.executable, "-c", "import pytest"],
                           capture_output=True, text=True)
    if probe.returncode != 0:
        print("REFUSING TO RUN: no pytest module for %s." % sys.executable)
        print("  This harness scores a mutant KILLED on a non-zero pytest exit code, and")
        print("  a missing pytest also exits non-zero — so it would report every mutation")
        print("  killed while running nothing. Install pytest, or use:")
        print("    uv run --python 3.11 --with pytest python tests/mutation_check.py")
        return False
    work = pathlib.Path(tempfile.mkdtemp(prefix="resume-gate-baseline-"))
    try:
        dst = work / "hook"
        shutil.copytree(HOOK, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        base = _run_pytest(dst)
        if base.returncode != 0:
            print("REFUSING TO RUN: the UNMUTATED suite already fails, so a mutant's")
            print("  non-zero exit would be inherited rather than caused and every")
            print("  mutation would score KILLED for the wrong reason. Fix the suite first.")
            print((base.stdout or "").strip()[-1500:])
            return False
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return True


def main():
    if not preflight():
        return 2
    results = []
    for label, rel, old, new, regen in MUTATIONS:
        work = pathlib.Path(tempfile.mkdtemp(prefix="resume-gate-mut-"))
        dst = work / "hook"
        shutil.copytree(HOOK, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        try:
            if rel == "FIXTURE_EDIT":
                p = dst / "tests" / "fixtures" / "clean.jsonl"
                p.write_text(p.read_text(encoding="utf-8").replace(
                    "Summarise the release notes", "Summarize the release notes"), encoding="utf-8")
            else:
                p = dst / rel
                text = p.read_text(encoding="utf-8")
                if old not in text:
                    results.append((label, "PATCH-DID-NOT-APPLY"))
                    continue
                p.write_text(text.replace(old, new, 1), encoding="utf-8")
                if regen:
                    gen = subprocess.run([sys.executable, "make_fixtures.py"],
                                         cwd=dst / "tests", capture_output=True, text=True)
                    if gen.returncode != 0:
                        results.append((label, "GENERATOR-REFUSED"))
                        continue
            results.append((label, "KILLED" if _run_pytest(dst).returncode else "SURVIVED"))
        finally:
            shutil.rmtree(work, ignore_errors=True)

    width = max(len(lbl) for lbl, _ in results)
    bad = 0
    for label, outcome in results:
        flag = "" if outcome in ("KILLED", "GENERATOR-REFUSED") else "   <-- TEST GAP"
        if flag:
            bad += 1
        print("%-*s  %s%s" % (width, label, outcome, flag))
    print("\n%d mutations, %d killed, %d needing attention" % (len(results), len(results) - bad, bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
