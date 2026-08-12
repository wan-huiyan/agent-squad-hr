# resume-gate — a hook, not a skill

Flags subagent work an interrupted Claude Code session never reviewed, and puts a human keypress in
front of push / merge / deploy while any of it is outstanding.

This is the **trigger**. The knowledge of what to do once you have been warned lives in the
[`recover-killed-session-from-transcript-and-worktree`](../../skills/recover-killed-session-from-transcript-and-worktree/)
skill in this same plugin — how to find the dead session's transcript and worktree, mine it for the
plan and the cause of death, and re-verify its "done" claims. That skill fires when a human notices
something is wrong. This hook is what makes the noticing automatic.

Full reasoning, including the two designs that were built, measured and rejected: [DESIGN.md](DESIGN.md).

## The problem

Sessions get interrupted, most often by a usage limit. Some of the work a session dispatched to a
subagent can end in a state the session itself never assessed:

- A **synchronous** subagent gets killed mid-run, and the harness writes its own notice into the
  parent's transcript saying the recovered output is partial.
- An **asynchronous** subagent's outcome never shows up as that notice at all — it arrives later as
  a separate task-notification. If that subagent was killed too, nothing in the parent's transcript
  ever says so.

Either way, a later session that resumes the branch can read that output as a finished, reviewed
result and ship it. Nothing in the harness distinguishes "a subagent finished and the parent
reviewed it" from "a subagent was killed mid-run and nobody looked."

## What it detects

Two independent signatures, both checked by the same detector (`resume_gate.py`'s `detect()`):

- **Signature A** — a synchronous subagent's `tool_result` **begins** with the harness's
  partial-output prefix. Beginning with it, not merely containing it: a review subagent reporting on
  this very tool returns a report that quotes the string mid-body, and that satisfies "contains"
  completely. Measured, that separation is stark — true positives carry the string at offset ~124 of
  a ~500-character result, discussion at offset ~2,005 of a ~14,700-character one.

- **Signature B** — an async subagent's task-notification has an unmatched `enqueue` (no `remove`)
  **and** a `<status>` that is not `completed` **and** a `tool-use-id` that resolves to an
  `Agent`/`Task` call. A missing or unparseable status also counts as outstanding — an unreadable
  status is not evidence the work finished cleanly, so the rule fails toward reporting.

  All three conditions earn their place:

  - **Not a bare enqueue/`remove` imbalance.** That was tried and measured: 57 of 79 sessions with
    any task-notifications (72%, including 3 hits on a clean control) have an unmatched enqueue just
    because a background agent was still running when the session ended. Normal, not a hazard.
  - **Not every non-completed notification.** A Bash call run with `run_in_background` produces a
    task-notification too, and a failed one is non-completed. There is deliberately **no fallback
    label** for an id with no Agent behind it — `(async task toolu_…)` names nothing a human can act
    on, and it armed the gate over shell commands the session had already seen inline.

  Gating on status is what makes the two signatures symmetric: both flag a subagent that was
  *terminated early*, one synchronously and one asynchronously — rather than one flagging
  "terminated" and the other flagging "hasn't reported back yet".

On resume, the `SessionStart` hook runs the detector over the current segment (everything since the
last mark it left in the transcript) and, if either signature fires, injects a warning naming each
affected subagent plus a summary of uncommitted/unpushed work. It also writes a new mark encoding
what it found, so a later `PreToolUse` check reads that mark instead of re-running the detector.

**The hook writes a mark in two cases, and the second one is what turns the gate back off:**

| Outstanding items | Previous mark | What the hook emits |
|---|---|---|
| non-empty | anything | the warning text, ending in a mark listing those items — arms the gate |
| empty | listed items | **only** a mark listing nothing, with no warning text — disarms the gate |
| empty | absent, or already empty | nothing at all |

The middle row is easy to leave out and its absence is invisible: the warning text was originally
the only thing that ever wrote a mark, so a mark listing *nothing* was never produced in real use.
One interruption then armed the gate permanently — every ship action forever after prompted, naming
items resolved days earlier. The third row is equally deliberate in the other direction: writing a
clearing mark on every resume would inject hook output into every resume of every session on the
machine, nearly all of which never had anything outstanding.

## What it gates

Push, merge, and deploy — **not commit**. Local commits are cheap and constant; blocking them is
pure friction. The `PreToolUse` hook fires only on:

- `git push` (including the `git push origin <branch>:main` merge fallback — it contains "push" but
  not "merge", so a naive command-name check would miss it)
- `git -C <path> push` — a **separate** condition, because `Bash(git push:*)` is prefix matching and
  this command starts `git -C`, not `git push`. Not hypothetical if you work out of worktrees, and
  `resume_gate.py` itself shells out this way.

  > ⚠️ **This one is unverified.** `Bash(git -C * push:*)` puts a `*` in the *middle* of the
  > pattern, and that syntax is not confirmed against a primary source — only the trailing `:*` form
  > is. If a mid-pattern `*` is not honoured, **this condition silently never fires**, with no error
  > either way. The other seven are unaffected, so the exposure is bare `git -C <path> push`. The
  > test named `test_ship_conditions_cover_git_dash_c_push` pins that the string is *emitted*; it
  > cannot show the harness honours it.
- `gh pr merge`, `gh pr create`
- `gh pr edit` (covers `--add-label auto-deploy`, which triggers a deployment with no push or merge
  verb in the command at all)
- `gh api` (covers a PR merge done via the REST API, e.g. `gh api -X PUT .../pulls/<n>/merge`)
- `gh release create`
- any tool in the installed publish-tool set — see `DEFAULT_PUBLISH_TOOLS` in `install.py`

When a session has outstanding work under either signature, these calls get
`permissionDecision: "ask"` — a human keypress, not an auto-deny the model could route around by
retrying. **The gate is escapable on purpose.** An earlier design cleared itself on an evidence file
written by the party being gated, which *looked* unevadable and was not. That is worse than an
honest prompt. Anything that must be unevadable belongs in CI.

## If a session has no transcript, the gate allows and says so

A session started by another Claude Code process inherits `CLAUDE_CODE_CHILD_SESSION`, and an
interactive session carrying that marker writes **no transcript file at all**. This gate reads the
transcript, so there is nothing for it to read.

It allows the call and prints a one-line `systemMessage` naming the cause and the remedy
(`CLAUDE_CODE_FORCE_SESSION_PERSISTENCE=1` in `~/.claude/settings.json`). It does **not** block.
Until 2026-08-12 it did: `FileNotFoundError` reached the fail-closed handler, and exit 2 blocked
every `git push`, `gh pr merge`, `gh api` and gated publish call in every project on that machine
for as long as the session lasted, with `gate failed (FileNotFoundError) - blocking to stay safe`
naming the exception and nothing that would connect it to session persistence.

Blocking there protected nothing, which is the whole argument: with no transcript there is no mark
to read and no rows for the detector to scan, so the gate could not have fired in either direction.
See *The one failure that is not an internal error* in `DESIGN.md`. Every other read failure still
exits 2 — including a missing `transcript_path` key and a path that is a directory.

## Install

```bash
python3 install.py
```

This writes hook entries into `~/.claude/settings.json`, your **global** Claude Code config — it
takes effect in every project on the machine, so run it deliberately rather than as a side effect of
something else.

**Back up your settings first**, and **never install from a plugin cache, a worktree, a branch
checkout, or `/tmp`.** Copy the two `.py` files to a stable location and install from there:

```bash
cp ~/.claude/settings.json ~/.claude/settings.json.pre-resume-gate.bak
mkdir -p ~/.claude/tools/resume-gate
cp resume_gate.py install.py ~/.claude/tools/resume-gate/
cd ~/.claude/tools/resume-gate && python3 install.py
```

To uninstall: `cp ~/.claude/settings.json.pre-resume-gate.bak ~/.claude/settings.json`, or remove
every hook entry whose `command` invokes `resume_gate.py` (under both `SessionStart` and
`PreToolUse`). There is no uninstall script — the edit is small, and writing a second tool whose
only job is to touch the same file is not worth it.

The installer resolves the interpreter to the absolute path `/usr/bin/python3` rather than relying
on `python3` being found on `PATH`, because **the PATH a hook runs under is not an interactive
shell's PATH** — observed repeatedly as `hook error: /bin/sh: node: command not found` when nvm's
node was not on it.

`install.py` prints the publish-tool set it is about to gate before writing anything, and re-running
it is idempotent — it replaces its own previously-written handlers rather than duplicating them.
**Re-run it after connecting a new MCP server** that can publish client-facing output. The installer
cannot discover the harness's live tool list, so `DEFAULT_PUBLISH_TOOLS` is a maintained list, not a
derived one, and it gates only whatever it knew about the last time you ran it. This is a knowing
deviation from the design, recorded as such rather than quietly.

## Three traps a maintainer must not walk into

### 1. Never write the matched string into this repository in plain form

Not in code, not in a fixture, not in this README, not in a commit message. Describe it; never spell
it out.

This is not cosmetic. Signature A's whole job is noticing that exact string, so a session that has
read a plain copy earns a false positive on itself — permanently, because the string never leaves
the transcript. Measured while building this: the design session's own count of rows containing the
string went **7 → 10 → 15 purely by discussing the problem**.

An earlier draft of the design demonstrated the escaping technique by writing out the escaped form
as a literal example. Markdown rendering ate a backslash, and the document *defining* the
no-plain-copy rule shipped the string in plain form, in the very sentence explaining why not to.

**So the escaping technique lives in exactly one place:** `tests/make_fixtures.py`'s
`escape_needle()`. It substitutes a JSON unicode escape for one character, so `json.loads`
reproduces the original faithfully while the bytes on disk never spell it and `grep` cannot find it
there. Point at that function; do not re-illustrate it.

**Building the constant with `+` does not count as assembling it at runtime.** CPython folds
adjacent string constants at *compile* time, so `"first half" + "second half"` puts the whole string
into the `.pyc`, where `grep` finds it in any checkout that has ever run the tests. It is confined
to gitignored `__pycache__/`, so nothing ships — but the docstring claiming "assembled at runtime"
was false until the constant moved to `str.join`, which the peephole optimiser leaves alone.

Two guards, both in `tests/test_fixtures.py`:
`test_no_fixture_contains_the_literal_needle_on_disk` covers every `*.jsonl`, and
`test_no_source_file_spells_out_the_needle` covers the code, tests and docs — the places it actually
leaked. Let those cover anything you add rather than writing a parallel check.

**The segment mark needs the same discipline as the needle.** Component 2 reads the newest mark out
of the transcript and trusts it, and a mark is a fixed literal — so any file that quotes one becomes
state the gate acts on. A committed *empty* mark is the bad case: every session that reads that file
disarms its own gate. `test_no_source_file_contains_a_decodable_segment_mark` enforces this. Before
it existed the repo was clean by luck, not by rule.

### 2. Do not "clean up" the unpadded base64 in the mark round-trip test

`tests/test_detector.py::test_mark_decodes_when_embedded_mid_string_with_escaped_newlines`
deliberately uses a mark whose base64 payload has **no trailing `=` padding**.

When padding *is* present, `binascii` stops decoding at the `=` and silently discards everything
after it — so a padded payload makes trailing junk invisible and the test passes against broken
code. Picking an item whose encoding happens to come out padded deletes the only case that
exercises the bug. This is not hypothetical: a regression test with a `==`-padded payload is exactly
what let the embedded-mid-string decode bug through the first time.

### 3. Never install from a path that can disappear

The first install pointed the hook at the script inside the scratch worktree it ran from.
Structurally correct, tested, installed cleanly, verified live — and a time bomb. When that worktree
went away, `python3 /gone/resume_gate.py` exited 2, and **for `PreToolUse`, exit 2 blocks the tool
call**. Every push and merge in every project on the machine would have been blocked by a hook whose
script no longer existed, with nothing in the error naming the cause.

The general rule: **anything registered globally must not point into a worktree, a branch checkout,
a plugin cache directory, or `/tmp`.**

## Running the tests

```bash
cd plugins/agent-traffic-control/hooks/resume-gate
python3 -m pytest tests/ -q          # or: uv run --python 3.11 --with pytest python -m pytest tests/ -q
python3 tests/mutation_check.py      # 38 mutations; exit 0 = every one killed
```

94 tests, stdlib plus pytest only.

`tests/test_install.py` exercises the installer's **pure functions only** — `build_config()`,
`unstable_install_reason()` and `missing_script_reason()`, all given fake paths. Nothing in the
suite calls `install.main()`; that would write to the real `~/.claude/settings.json` on whatever
machine runs the tests, which is exactly the side effect the Install section says to make
deliberately rather than as a byproduct of `pytest`.

### The mutation harness is committed, and that is the point

`tests/mutation_check.py` holds all 38 mutations with the guard each one deletes. Run it; do not
take a score on trust.

An earlier revision of this file claimed "25 mutations, 25 killed" with no list committed. An
independent reviewer then ran a *different* set and **7 of 13 survived** — each a real gap, including
one where nothing distinguished `count > 0` from `count >= 0` and one where the test named for a
corrupt payload never reached the decode-exception branch it was named after. A quoted score is not
reproducible and a list that only its author has seen is not a check.

**If you touch a test, mutate the code it covers and confirm it fails.** Six tests in this tool's
first build could not fail, and each one hid a real defect — an `assert isinstance(hits, list)` that
passes for `[]`, a positive path monkeypatched away, three installer tests that asserted strings
appeared without asserting where they sat. Writing real-looking test code is not writing a test.
When a mutation survives, fix the test; do not delete the mutation.

### The fixtures are generated, not captured

`tests/fixtures/*.jsonl` are built by `tests/make_fixtures.py`, deterministically — no clock, no
randomness, no reads of `~/.claude/projects`. Regenerate with:

```bash
python3 tests/make_fixtures.py
```

`test_fixtures_match_the_generator` regenerates into a temp directory and compares byte for byte, so
a hand-edited fixture is a test failure rather than a silent divergence that the next regeneration
reverts.

Two fixture properties are pinned by their own assertions because otherwise the tests that depend on
them pass **vacuously**:

- the discussion fixture must genuinely contain the matched string inside an `Agent` `tool_result`
  and not prefix-anchored — otherwise "Signature A is silent here" only means "there was nothing to
  find";
- the clean fixture must genuinely contain unmatched `completed` enqueues — otherwise it stops being
  the control that keeps a bare enqueue/`remove` imbalance rule out.

Both are enforced by assertions in `tests/test_fixtures.py`, and `mutation_check.py` breaks each one
to prove the assertion notices.
