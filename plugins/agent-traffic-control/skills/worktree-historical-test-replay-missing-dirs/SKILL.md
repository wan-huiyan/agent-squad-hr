---
name: worktree-historical-test-replay-missing-dirs
description: |
  Fix `pytest exit 4` ("file or directory not found") when running a test
  command in a git worktree checked out at an OLD commit. Use when:
  (1) you're doing historical replay (incident replay, mutation testing,
  git bisect with tests) and the suite errors out in 1-2 seconds with no
  test execution, (2) the test command works fine at HEAD but fails at
  pre-fix SHAs, (3) `pytest scripts/overnight/tests/ <analytics_pkg>/tests/ --tb=no
  -q` returns "ERROR: file or directory not found: scripts/overnight/tests/"
  at an old SHA, (4) you're building tooling that runs the project's
  canonical test command across multiple historical SHAs.

  The fix is NOT to add the missing dir back — it didn't exist then. The
  fix is to filter the test-dir list at each SHA to only those that exist
  in that commit's tree, then invoke pytest with the filtered list. If
  none survive, classify the SHA as "unrunnable" rather than failing the
  whole replay.
author: Claude Code
version: 1.0.0
date: 2026-04-24
disable-model-invocation: true
---

# Worktree historical test replay — missing dirs

## Problem

You're replaying historical bugs by checking out each pre-fix SHA in a temp
worktree and running the project's canonical test command. At HEAD the
command works (e.g. 159 tests collect). At older SHAs you get:

```
ERROR: file or directory not found: scripts/overnight/tests/

no tests ran in 0.01s
```

Exit code 4, duration 1-2 seconds. Pytest aborted before collection because
one of the test directories you passed didn't exist yet at that commit.

This silently corrupts a historical-replay audit: you can't tell apart
"the suite passed and missed the bug" from "the suite never ran." Both
look like pytest failures from the outside.

## Context / Trigger Conditions

- You're running historical incident replay, mutation testing, git bisect,
  or any other "check out an old SHA and run the suite" workflow
- The project's test layout grew over time (test dirs added, removed,
  reorganized in subsequent commits)
- The test command embeds explicit directory paths:
  `pytest scripts/overnight/tests/ <analytics_pkg>/tests/ ...`
- Pytest exits 4 (`USAGE_ERROR`) in <5 seconds with no test execution
- The SAME test command works at HEAD but fails at pre-fix SHAs older than
  the test layout's current shape

## Solution

Before invoking the test command at each SHA, **filter the test directory
list to only those that exist in the worktree at that SHA**:

```bash
# Inside the worktree at the target SHA:
TEST_DIRS=()
for d in scripts/overnight/tests <analytics_pkg>/tests <analytics_pkg>/cloudrun/<dashboard_app>/tests; do
  [ -d "$d" ] && TEST_DIRS+=("$d")
done

if [ ${#TEST_DIRS[@]} -eq 0 ]; then
  # No test dirs existed at this SHA — classify as 'unrunnable', skip.
  echo "STATUS=unrunnable_no_test_dirs_at_sha"
  exit 0
fi

PYTHONPATH=. pytest "${TEST_DIRS[@]}" --tb=no -q
```

In Python:

```python
test_dirs_at_head = ["scripts/overnight/tests", "<analytics_pkg>/tests"]
existing = [d for d in test_dirs_at_head if (worktree_path / d).is_dir()]
if not existing:
    return {"status": "unrunnable", "reason": "no test dirs existed at this SHA"}
subprocess.run(["pytest", *existing, "--tb=no", "-q"], cwd=worktree_path)
```

Or query git directly without checking out:

```bash
git -C "$REPO" ls-tree -d --name-only "$SHA" -- "$DIR"
# exit 0 if dir exists at that SHA, prints the dir name
# exit 0 with no output if dir doesn't exist
```

## Why this happens

Pytest treats explicit path arguments as "you promised these exist". When
one is missing it aborts with exit 4 (USAGE_ERROR) BEFORE collection — so
not a single test runs, even from the dirs that DO exist. The exit code
is the same as a pytest CLI usage mistake, which makes the failure mode
ambiguous: it looks like "the test command is wrong" rather than "the
test layout was different at that SHA".

Subdirs that didn't exist yet at older SHAs are common in real projects:

- New service added with its own `tests/` dir
- Test reorg moved `tests/` from root into `services/foo/tests/`
- Component spun out from a monolith took its tests with it

## Verification

```bash
# At HEAD — all dirs exist, command works:
$ pytest scripts/overnight/tests/ <analytics_pkg>/tests/ --collect-only -q
159 tests collected

# At an old SHA — one dir missing:
$ git -C $WORKTREE ls-tree -d --name-only HEAD -- scripts/overnight/tests <analytics_pkg>/tests
<analytics_pkg>/tests
# (scripts/overnight/tests is absent)

# After filtering:
$ pytest <analytics_pkg>/tests/ --collect-only -q
58 tests collected   # ran successfully against the dirs that existed
```

The filtered run produces a real pass/fail signal. The unfiltered run
produces an ambiguous "exit 4" that looks like a script bug.

## Notes

- **Always classify the "no test dirs existed at all" case as unrunnable,
  not as a 0% catch rate.** A SHA that pre-dates the test suite isn't
  evidence that the suite missed the bug — there was no suite. This is a
  data-quality note in the report, not a test-quality finding.
- Same pattern applies to file paths in the command, not just dirs:
  `pytest tests/test_specific.py` fails the same way if that file was
  added later. Less common, but check.
- If the project uses `pytest` with no path argument (relying on
  `testpaths` in `pyproject.toml`), this trap is partially avoided —
  pytest will collect whatever exists. But you lose control over which
  dirs run, and `pyproject.toml` itself may not exist at older SHAs, so
  fall back to explicit + filtered paths for replay tooling.
- `git worktree add -f --detach <SHA>` is the right pattern for historical
  replay — `--detach` avoids creating a useless branch you have to clean
  up, `-f` overrides the safety check if the worktree path was reused.
- Always `git worktree remove -f` in a trap on EXIT, even if the test run
  failed, or you accumulate dead worktrees.

## Example

From `test-effectiveness-auditor` v1.0 (a separately published plugin, not one of this repo's skills):

```bash
# Initial naive command — fails on the project's older SHAs because
# scripts/overnight/tests/ was added in a later session:
pytest scripts/overnight/tests/ <analytics_pkg>/tests/ --tb=no -q
# → exit 4 in 2s, status="some_failed", but no tests actually ran

# After filtering test dirs to those existing at pre-fix SHA 72580148dd:
pytest <analytics_pkg>/tests/ --tb=no -q
# → 58 passed in 1.32s — real signal: bug not caught by then-existing tests
```

This was the difference between recording 4 incidents as "all unrunnable
(broken script)" and recording 3 of 4 as "ran cleanly, all gap_testable
(tests missed the bug)" — the latter is the actual finding.

## References

- [pytest exit codes](https://docs.pytest.org/en/stable/reference/exit-codes.html) — exit 4 is "Usage error"
- [git ls-tree](https://git-scm.com/docs/git-ls-tree) — query a tree at any SHA
- [git worktree add](https://git-scm.com/docs/git-worktree#Documentation/git-worktree.txt-add) — `--detach -f` for replay tooling
