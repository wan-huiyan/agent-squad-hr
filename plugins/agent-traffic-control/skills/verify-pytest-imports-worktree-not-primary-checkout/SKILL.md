---
name: verify-pytest-imports-worktree-not-primary-checkout
description: |
  When you run pytest (or any `python -c "import <pkg>"`) from a git WORKTREE
  but the venv has an editable install (`pip install -e .`) made from the
  PRIMARY checkout, `import <pkg>` silently resolves to the PRIMARY checkout's
  source, NOT the worktree code you think you're testing. Use when: (1) you
  edited code in a worktree, ran the suite, it passed/failed — but you're
  unsure it exercised the worktree's edits, (2) tests pass on changes that
  "shouldn't" pass (or fail on changes you reverted), (3) a `src/`-layout
  project with absolute `import src.*` / `import <pkg>.*` imports, one shared
  `.venv`, and multiple worktrees. Fix: prepend the worktree root to
  `PYTHONPATH` and VERIFY resolution with `print(<pkg>.__file__)`.
author: Claude Code
version: 1.0.0
date: 2026-05-29
disable-model-invocation: true
---

# Pytest editable-install resolves to primary checkout, not the worktree

## Problem

You have one virtualenv with an **editable install** (`pip install -e .`) created
from the **primary** repo checkout. You then create a git **worktree** to do
isolated feature work, edit code there, and run the test suite from the worktree
directory. The suite runs against the **primary checkout's** source, not your
worktree edits — silently. Green tests "prove" nothing about your branch; a fix
you only made in the worktree looks like it had no effect, or a bug you only
reverted in the worktree still appears.

## Context / Trigger Conditions

- A `src/`-layout project whose code uses **absolute** imports (`import src.app`,
  `from mypkg.x import y`) — so the package is resolved via `sys.path`, not via
  the cwd.
- ONE shared venv with `pip install -e .` (or `pip install -e ".[dev]"`) run from
  the **primary** checkout. The editable install drops a `__editable__.<pkg>.pth`
  / finder into site-packages that **hardcodes the primary checkout's path**.
- You run `pytest` / `python -m pytest` / `python -c "import <pkg>"` from a
  **git worktree** directory (e.g. `.../.claude/worktrees/feature-x`).
- Symptom: tests pass on a change you believe is incomplete, OR fail on code you
  already fixed in the worktree, OR you simply can't be sure which tree ran.

## Why it happens

`sys.path` precedence at import time is roughly: the script/cwd entry, then
`PYTHONPATH` entries, then site-packages (where the editable `.pth` lives).
pytest does **not** reliably put the worktree's project root first (it only adds
`rootdir`/cwd under specific `pythonpath`/`conftest`/`rootdir` conditions, and a
`src/` layout usually means `src`'s parent isn't auto-added). So `import <pkg>`
falls through to the editable install's hardcoded **primary** path. Nothing
errors — it's just the wrong tree.

## Solution

Prepend the **worktree root** to `PYTHONPATH` so it wins over the editable
`.pth`, and **verify resolution** before trusting any result:

```bash
WT=/abs/path/to/worktree            # the worktree you edited
VENV=/abs/path/to/primary/.venv     # the shared venv with the editable install

# 1. VERIFY which tree import resolves to — do this FIRST, every time:
PYTHONPATH="$WT" "$VENV/bin/python" -c \
  "import src.app, pathlib; print('src from:', pathlib.Path(src.app.__file__))"
#   want: src from: /abs/path/to/worktree/src/app.py   (NOT the primary checkout)

# 2. Run the suite with the same override:
cd "$WT" && PYTHONPATH="$WT" "$VENV/bin/python" -m pytest tests/ -q
```

Alternatives (heavier): create a fresh venv inside the worktree and
`pip install -e .` there; or use `tox`/`uv run` with per-tree environments. The
`PYTHONPATH` prepend is the fastest and needs no install.

## Verification

The `print(<pkg>.__file__)` line resolves to a path **under the worktree**, not
the primary checkout. A quick negative control: run the same one-liner WITHOUT
`PYTHONPATH` — it should print the primary path, confirming the trap is real and
the override is doing the work.

## Example

brief-runner S26: fixing a template/CSS bug in worktree
`.claude/worktrees/s26-configure-fix`, the venv lived at the primary checkout
(`/Users/.../the-handover-repo/.venv`) with `pip install -e .`. Before running the
wizard tests I checked:

```
$ PYTHONPATH="$PWD" /…/the-handover-repo/.venv/bin/python -c \
    "import src.app, pathlib; print('src from:', pathlib.Path(src.app.__file__))"
src from: /Users/.../the-handover-repo/.claude/worktrees/s26-configure-fix/src/app.py   ✓
```

Confirmed the worktree's `src` won; the 17-test wizard suite then genuinely
exercised the worktree edits. Without the check, a green run would have been
meaningless.

## Notes

- This is distinct from cwd/edit-staleness worktree traps
  (`flask-debug-cross-worktree-edit-stale`, `multi-worktree-file-url-stale-content`,
  `main-bash-cwd-persists-nested-worktree`): here the *files* are fine in the
  worktree, but the Python *import machinery* points elsewhere because of the
  editable install's hardcoded path. Same family ("am I really running the tree I
  think I am?"), different mechanism.
- The Bash tool's cwd is reset between calls in some harnesses, so don't rely on a
  prior `cd` — pass `PYTHONPATH` (and an absolute venv python) on the same command
  line every time.
- If the project ever switches to a flat layout or a non-editable install, the
  trap changes shape — re-verify with `__file__` rather than assuming.
- Same reasoning applies to `ruff`/`mypy`/coverage that import the package: verify
  the resolved path, not just that the tool ran.

## References
- PEP 660 (editable installs via build backends) — explains the hardcoded-path
  finder/`.pth` that site-packages installs.
- pytest `pythonpath` / import-mode docs — why `src/` roots aren't auto-added.
