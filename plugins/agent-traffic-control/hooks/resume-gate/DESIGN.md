# resume-gate — design, and the two designs that were measured and rejected

**Date:** 2026-08-10
**Status:** implemented; installed and verified live before this document was finalised

This is the reasoning behind `resume_gate.py`, kept because two earlier designs were intuitive,
were built far enough to be measured, and were wrong in ways that are not obvious. Without the
record, they get re-proposed.

Every number below was measured on one developer machine with 1,898 stored Claude Code
transcripts across roughly a dozen repositories. They are stated as what was measured over what
population, not as universal constants — reproduce them on your own machine before relying on them.

---

## Problem

Sessions get interrupted, most often by a usage limit. When a session is interrupted, some of the
work it dispatched can end in a state the session itself never assessed — most importantly, a
subagent whose output the harness truncates and labels partial. The parent's transcript still
contains that subagent's text, so a later session resuming the branch can read it as a finished,
reviewed result and ship it.

Nothing in the harness distinguishes **"a subagent finished and the parent reviewed it"** from
**"a subagent was killed mid-run and nobody looked."** That is the entire gap this closes.

## The motivating incident — and the corrected record

The design was originally motivated by a story that turned out to be wrong. It is recorded because
the wrong version is the intuitive one.

**The claim:** a subagent outlived its parent, kept running after the usage limit killed the
session, and wrote to a client-facing deliverable at 13:42 — 39 minutes after the parent went quiet
at 13:03 — so its output was never reviewed.

**What the transcripts actually showed:**

- **The two timestamps were on different clocks.** The machine's local time was one hour ahead of
  UTC. The `13:42` was a local-time file mtime; the `13:03` was a UTC transcript timestamp.
  Converted to one clock, the write happened at **12:42 UTC, 21 minutes _before_ the parent's last
  turn** — not 39 minutes after.
- **The subagent did not outlive its parent.** The parent's transcript contains, verbatim, the
  harness's own partial-output notice. The same limit killed both, and the harness said so. (That
  notice occupies **one row** but appears **twice within it** — once in the `tool_result` block and
  once in a duplicated field outside `message`. Count rows, not occurrences.)
- **That subagent never touched the deliverable.** The writes came from three other subagents, all
  before the limit, all already committed and pushed.

**The residual risk, stated correctly:** one subagent returned partial output, the harness said so
in a fixed string, and a resuming session has no mechanism that makes it notice. That — not clock
skew — is what this design addresses.

The generalisable lesson is worth more than the incident: **a file mtime and a transcript timestamp
are not comparable without converting them to one clock**, and an argument built on the difference
between them will be confidently wrong.

## Non-goals

- **Not an unevadable control.** The gate escalates to a human; it does not make shipping
  impossible. Anything that must be unevadable belongs in CI — see Sequencing.
- **Not a review of the work itself.** It flags that something needs a look; it does not judge it.
- **No new state, no CLI, no evidence protocol.** See the rejected designs.

---

## Design

Three small pieces, all stdlib Python, no persistent state.

### Component 1 — the `SessionStart` detector

Hook event `SessionStart`, matcher `resume`. Receives `session_id`, `transcript_path`, `cwd`,
`source`, `permission_mode`.

It looks for **two** signatures, because subagents die in two different ways and each leaves a
different trace. It emits nothing when neither is present.

#### Signature A — a synchronous subagent, killed mid-run

The harness writes a partial-output notice into the parent's transcript. That notice is the thing
being matched; this document never spells it out, for the reason in rule 3.

Four qualifying rules, all mandatory. Without them the detector is unusable.

**Rule 1 — the hit must sit inside a `tool_result` block whose `tool_use_id` resolves to an
`Agent`/`Task` `tool_use` in the same transcript.** A bare string search matches any session that
merely *discusses* the string — including the session that implements this design, the one that
reviews it, and the one that writes its tests.

**Rule 2 — that `tool_result`'s text must _begin_ with the harness prefix**
`Agent terminated early due to an API error`. Rule 1 alone is **not** sufficient, and the reason is
structural rather than incidental: a review subagent reporting *on this design* returns its report
as an `Agent` `tool_result` that quotes the matched string, satisfying rule 1 completely. That is
not a hypothetical — it is the implementation workflow.

> Measured on the design session's own transcript: **15 rows contain the string, 2 of them inside
> an `Agent` `tool_result`, and 0 survive prefix-anchoring.** On the incident transcript: 1 row,
> 1 in a `tool_result`, 1 anchored. The separator is unambiguous — in true positives the string
> sits at offset ~124 of a ~500-character result; in discussion it sits at offset ~2,005 of a
> ~14,700-character one.

The anchor also generalises beyond usage limits: a second true positive on the same machine was
caused by `API Error: Connection closed mid-response` and anchors identically.

**Rule 3 — the matched string must never appear in this repository in plain form.** Not in the
code, not in this document, not in the test fixtures, not in a commit message. It is assembled at
runtime from two halves, and the fixtures store it escaped. A committed plain copy poisons every
session that reads the file, permanently.

> Evidence this is not paranoia: the design session's own count of rows containing the string went
> **7 → 10 → 15** purely by discussing the problem.

**`"first half" + "second half"` does not satisfy this rule.** CPython folds adjacent string
constants at *compile* time, so that form puts the whole string into the `.pyc` — and a grep over a
checkout that has ever run the tests finds it there. It is only in `__pycache__/`, which is
gitignored, so nothing ever shipped; but the code said "assembled at runtime" and that was not true.
The constant is now built with `str.join`, which the peephole optimiser does not fold.

**The segment mark needs the same rule, and did not have one.** Component 2 reads the newest mark
out of the transcript and *trusts it*. A mark is a fixed literal, so any row that merely quotes one
becomes state the gate acts on — a doc example, a fixture, someone pasting hook output into a chat
while debugging. A committed empty mark would be the worst case: every session that reads that file
disarms its own gate. `test_no_source_file_contains_a_decodable_segment_mark` now enforces this the
way `test_no_fixture_contains_the_literal_needle_on_disk` enforces rule 3. Before that test, the
repo was clean by luck.

**Rule 4 — the scan is bounded to the current resume segment, marked by a sentinel Component 1
emits itself.** There is **no** resume marker in the transcript to key off. Verified: no row type
records one, `sessionId` is constant across all 2,387 rows of the transcript checked, `entrypoint`
is always `cli`, and the four resume gaps in that file begin on inconsistent row types. A
timestamp-gap heuristic is not a fallback — it would reintroduce exactly the timestamp reasoning
the first draft died of.

So Component 1 emits a short sentinel inside its `additionalContext`, which lands in the transcript
as a system reminder. Component 2 scans only rows after the **last** sentinel. Self-marking, no
external state, nothing to expire. **The sentinel must not contain the matched string**, or rule 3
defeats itself.

Without this the warning is permanent: the string never leaves the transcript, so Component 1
re-warns on every future resume and Component 2 prompts on every ship action forever. Measured on
the incident session: **6 ship actions ran 44 hours later**, every one of which would have prompted.

#### Signature B — an asynchronous subagent whose report was never consumed

This is the half that matters most, and a partial-output scan alone cannot see it. **81 of 181
Agent calls return only `Async agent launched successfully`** — the outcome arrives later as a
task-notification, not as that `tool_result`, so no partial-output notice ever reaches the parent
no matter what happens to the subagent.

The motivating incident had **two** subagents killed by the same limit, one of each kind:

| Subagent | Mode | Parent's `tool_result` | Signature A sees it? |
|---|---|---|---|
| the synchronous one | sync | partial-output notice | yes |
| the asynchronous one | **async** | `Async agent launched successfully` | **no** |

Async results are delivered as task-notification rows tracked by `queue-operation` enqueue/remove
pairs. The rule was originally stated as **an enqueued task-notification with no matching
`remove`**, on the theory that any unmatched enqueue is an async subagent whose report the parent
never consumed.

**That theory is measurably wrong, and by a lot.** An unmatched enqueue by itself is not the
hazard — a session that simply ends while a background agent is still running leaves one behind,
and that is normal. Measured across every transcript on the machine with at least one
task-notification: **57 of 79 sessions (72%) have an unmatched enqueue**, including **3 hits on the
clean control transcript**, which breaks the design's own "silent on clean" criterion outright. A
bare-imbalance rule would have gated roughly three out of every four ship actions on that machine,
clean sessions included.

**The corrected rule reads the notification's own `<status>` field.** Report a hit only when the
status is present and is **not** `completed`; a missing or unparseable status counts as
outstanding, because an unreadable status is not evidence the work finished cleanly — fail toward
reporting.

> Tallied by status across all 1,898 transcripts: `completed` 225, `killed` 24, `failed` 9,
> `stopped` 1. Those 34 non-completed cases are the actual hazard; the 225 completed ones are
> exactly the harmless "still running when the session ended" case the bare-imbalance version could
> not tell apart from a killed subagent.

**Third rule: the notification's `tool-use-id` must also resolve to an `Agent`/`Task` call.**
Task-notifications are not emitted only for subagents — a Bash call run with `run_in_background`
produces one too. On the incident transcript that gave Signature B a **second** hit: a failed
background grep, non-completed, with no Agent `tool_use` behind it. It surfaced under a fallback
label — `(async task toolu_…)` — that names nothing a human can act on, and it would have armed the
gate over a shell command the session had already seen inline. **The fallback label is deleted
outright:** if the id does not resolve to an Agent call, there is no subagent to report.

This also makes Signature B conceptually **symmetric with Signature A**: both detect a subagent
that was *terminated early*, rather than one that simply has not reported back yet — A
synchronously via the harness's own notice, B asynchronously via a non-`completed` status. Same
hazard, two delivery mechanisms, not two unrelated checks.

Note the harness **redelivers** pending notifications on resume, so a resuming session does
eventually see the report. What it never sees is any marker saying the work was produced while the
parent was dead — which is precisely the hazard in the Problem section.

For each hit under either signature, the detector reports the associated `Agent` call's
`description`.

#### Supplementary context, same hook

`git status --porcelain` and `git log @{u}..HEAD`, reported as "work that exists but has not been
through review." Uncommitted and unpushed work is the correct proxy — bounded to a handful of
items, scoped to the repo, and immune to mtime entirely.

#### The three emission branches, and why the middle one exists

Output goes back as `hookSpecificOutput.additionalContext`, which reaches the model on resume as a
system reminder. It names each affected subagent, carries the segment mark, and points at the
`recover-killed-session-from-transcript-and-worktree` skill for what to do next.

| Outstanding items | Previous mark | What the hook emits |
|---|---|---|
| non-empty | anything | the warning text, ending in a mark listing those items — **arms** the gate |
| empty | listed items | **only** a mark listing nothing, no warning text — **disarms** the gate |
| empty | absent, or already empty | nothing at all |

**The middle row is the fix for a defect found in final review.** As first built, the mark was
written only as the last line of the warning text, so a mark listing *nothing* was never produced
in production: one interruption armed the gate permanently, and 44 hours and any number of resumes
later it still named the same long-resolved items.

**The third row matters as much as the second.** Emitting a clearing mark unconditionally on every
resume would inject a line of hook output into every resume of every session on the machine, most
of which never had anything outstanding. A session with nothing to say and nothing to retract stays
silent.

### Component 2 — the `PreToolUse` ask-gate

Fires on ship actions when the current session's transcript shows **either** signature. One gate,
both signatures, no second reading.

An earlier version of this section said Component 2 "re-runs the detector" windowed on the last
sentinel. **That is circular and would have broken the gate:** Component 1 writes the sentinel
immediately after warning, so a re-scan windowed to "rows after the last sentinel" finds nothing,
and a scan windowed *before* the sentinel instead fires forever. Neither version works, and both
were only caught while writing the implementing plan, not while writing the design.

**Resolution: Component 1 writes the outstanding list into the mark itself, and Component 2 reads
it.** Component 1's detection pass still runs once, over rows after the previous mark — but instead
of leaving a bare sentinel, it encodes what it found into the mark. Component 2 reads the most
recent mark and uses its contents directly: no second detection pass, no possibility of two
detectors disagreeing, because there is exactly one detector and it runs exactly once per segment.
Component 2 falls back to a `detect()` pass in **two** cases: no mark exists at all (a session that
has never been resumed), and the newest mark exists but **does not decode**.

**That second case is where a fail-open hid**, found in review after the first version was written.
An undecodable mark correctly returned "no trustworthy state" — but the fallback `detect()` still
windowed on *the most recent mark*, corrupt one included, so the re-derivation had only the handful
of rows after it to scan, usually none. Measured on the incident fixture: appending one undecodable
mark took `detect()` from two hits to zero, and the `PreToolUse` decision from `ask` to silence.
Two realistic triggers, both reproduced — a truncated mark, and a subagent description containing
the mark's own item separator, which makes the hook corrupt state it wrote itself.

The fix: `window_after_last_mark` skips marks that do not decode and falls back to the last boundary
it *can* read. That re-scans more rows than strictly necessary, which is the safe direction, and it
cannot resurrect items from before that boundary since they sit outside the window either way.
`read_last_mark` still refuses to fall back to an earlier mark's *items* — that would be unsafe in
both directions, resurrecting resolved items and hiding new ones.

The lesson generalises past this bug: **"returns None so the caller re-derives" is only safe if you
check what the caller actually re-derives over.** Both halves were individually reasonable and the
composition was fail-open.

The mark is base64 so that a subagent description containing a newline cannot break it across
lines; the mark has to survive as one line found by one regex. **It does not, and never did, stop a
description leaking the matched string into the transcript** — an earlier draft claimed that and
was wrong. Component 1 prints every item in plain text two lines above the mark, and Component 2's
ask-reason joins them plainly. The encoding is about newline safety only.

**Accepted gap, stated more honestly than it first was:** a subagent killed in a session that is
never resumed gets no mark until its first ship action triggers the fallback pass — and because
only `SessionStart:resume` ever *writes* a mark, that session then asks on **every** ship action for
the rest of its life, with no way to clear it from inside the session. The parent saw the harness's
partial-output notice inline regardless, so nothing is hidden. But "the mark-based fast path starts
covering a session from its first resume onward", which is how this paragraph originally read,
describes the mechanism and not the experience: the repeating prompt is the part a user feels, and
interrupting and resuming is the only thing that quiets it.

**Components 1 and 2 must share one detector, not two.** After the qualifying rules this is no
longer a string scan — it is a two-pass parse (collect `Agent` `tool_use` ids, then resolve
`tool_result`s against them and prefix-anchor) plus queue-operation accounting, windowed to the
last mark. If Component 2 reimplements a cheaper version, the two will disagree and the gate will
pass work the warning flagged. Write it once, call it twice.

**Cost:** a full JSON parse of an 11 MB transcript measures **~0.24 s** (0.15 s to load, 0.09 s to
detect) — more than the tens of milliseconds a byte scan would cost, and well under the "on the
order of a second" this section claimed before anyone timed it. Ship actions are rare enough for
either number to be fine — the incident session ran 6 in 181 Bash calls — but a cost used to justify
a design should be measured rather than estimated.

One documented caveat, benign here: the transcript file is written asynchronously and may lag the
in-memory conversation, so it may not yet include the current turn's most recent messages. This
design only ever looks for a string written **before** the interruption, many turns back, so the
lag cannot hide it. Any future check that depends on the *current* turn's text must not read the
transcript — it should use `last_assistant_message` on `Stop`/`SubagentStop` instead.

#### `ask`, not `deny`

`deny` is advisory — the model sees the reason and may retry — and any self-service clearing path
is one the gated party can walk itself. `ask` puts a human keypress in the loop, which is the only
part of this the model cannot route around.

#### Ship actions are push, merge and deploy — not commit

Local commits are harmless and constant; blocking them is pure friction. The set must include, at
minimum:

- `git push origin <branch>:main` — a common merge fallback when the GitHub API is unavailable.
  Contains "push" but not "merge".
- `git -C <path> push` — **a separate condition.** `Bash(git push:*)` is prefix matching and this
  command starts `git -C`, not `git push`. Not hypothetical: worktree-based work uses it constantly,
  and `resume_gate.py` itself shells out with `git -C`.

  > ⚠️ **`Bash(git -C * push:*)` is UNVERIFIED.** It places a `*` in the *middle* of the pattern,
  > and that syntax is not confirmed against a primary source — only the trailing `:*` form is. If a
  > mid-pattern `*` is not honoured, **this one condition silently never fires**, and there is no
  > error to notice: an `if` pattern that matches nothing looks exactly like one that has not
  > matched yet. The other seven conditions are unaffected, so the exposure is bare
  > `git -C <path> push` and nothing else. `test_ship_conditions_cover_git_dash_c_push` pins that
  > the string is *emitted*; nothing tests that the harness *honours* it, and no Python test could.
- `gh pr edit <n> --add-label auto-deploy` — **triggers a deployment with no push or merge verb at
  all.** The incident session ran exactly this.
- `gh api -X PUT repos/…/pulls/<n>/merge` — merges via the REST API, no `gh pr merge`.
- `gh release create`.

#### Matching — two distinct mechanisms, do not conflate them

The top-level `matcher` is a regex on the **tool name only** and cannot see the command. The **`if`**
field is what evaluates `Bash(git push:*)`-style patterns. Writing `matcher: "Bash(git *)"` matches
no tool name at all and the gate silently never fires.

**`if` is a handler-level field** — a sibling of `type` and `command`, **inside the inner `hooks`
array**, not a sibling of `matcher`:

```json
{"matcher": "^Bash$",
 "hooks": [{"type": "command", "if": "Bash(git push:*)", "command": "…"}]}
```

The first build put `if` next to `matcher`, where it is an unrecognised key and is dropped. What
remains is a group matching bare `Bash` with no condition — so **every** Bash call prompts, once per
ship condition (seven times over), each prompt preceded by a full JSON parse of the transcript.
Silent, and the opposite of the intent.

**The matcher is unanchored**, tested with `RegExp.prototype.test`, so `"Bash"` also matches
`BashOutput`. Use `"^Bash$"`.

Use `if` rather than a hand-rolled regex over the command string. The built-in does per-subcommand
parsing including `$()` and backticks; a hand-rolled regex is strictly weaker and loses to `git -C`,
double spaces, heredocs, `eval`, and — commonly in real transcripts — a `;`/`&&` chain with the ship
verb in the second clause.

**Non-Bash publish paths need a second handler** with a tool-name regex union. MCP tools appear as
`mcp__server__tool`. A Bash-only gate leaves every one of these open, and they are all
client-facing.

**Known deviation, accepted:** `install.py` ships `DEFAULT_PUBLISH_TOOLS` as a maintained constant
rather than a union derived at install time from the tools actually present. A Python installer
cannot enumerate the harness's live tool list, so that derivation is out of reach from where the
installer runs. The mitigation is that `build_config()` takes the list as a parameter (so it stays
testable and overridable), `main()` prints it before writing anything, and the README says to re-run
the installer after connecting a new MCP server. Read this as the requirement's status: **unmet by
design, with a manual step standing in for it** — not satisfied.

### Component 3 — the install script

Resolves the interpreter path at install time and writes the hook config into
`~/.claude/settings.json`. It uses `/usr/bin/python3`, which is always present on macOS, rather than
a Homebrew or pyenv path that a later upgrade relocates.

**Hook PATH is not shell PATH.** This is observed, not theoretical: `PostToolUse:Bash hook error:
/bin/sh: node: command not found`, repeatedly, because nvm's node is not on the hook PATH. The same
trap applies to `find` — in an interactive zsh, `find` may be a function re-execing a bundled `bfs`,
while a hook gets BSD `/usr/bin/find`, and the two disagree on timestamp parsing. **This design
shells out to neither.**

**And never install from a worktree, a branch checkout, or a `/tmp` path.** The first install wrote
the hook command as an absolute path to the script inside the scratch worktree it ran from —
structurally correct, tested, verified live, and a time bomb: when that worktree is removed,
`python3 /gone/resume_gate.py` exits 2, and for `PreToolUse` **exit 2 blocks the tool call**. Every
push and merge in every project on the machine would have been blocked by a hook whose script no
longer existed, with nothing in the error naming the cause. Copy the tool to a stable location and
install from there. Back up `~/.claude/settings.json` first — a one-line `cp` restore is what makes
this undoable in seconds.

## Error handling

**Both hooks `exit 2` on internal error**, and never rely on a printed JSON payload they may not
reach:

| Event | Can exit 2 block? | Effect of exit 2 |
|---|---|---|
| `PreToolUse` | Yes | Blocks the tool call |
| `SessionStart` | **No** | Shows stderr to the user only; the session proceeds |

So the two postures need no split, and an earlier draft was wrong to invent one. A `SessionStart`
hook **cannot** brick session startup — exit 2 there is purely a visible error. That makes `exit 2`
right for the detector too: a broken detector becomes something you *see* rather than something
that silently never fires. **A silent detector is the fail-open defect wearing different clothes**,
and it is the failure mode most likely to go unnoticed for months.

Because `SessionStart` exit 2 surfaces **only stderr** — no JSON, no context — that message must be
a single short self-explanatory line. "resume-gate: detector failed, sessions are unguarded" beats
a stack trace nobody can act on.

Exit code 1 is **non-blocking** for both — the action proceeds with a `hook error` notice. Never use
it for policy; the hooks documentation is explicit that a policy-enforcing hook uses `exit 2`.

### The one failure that is not an internal error: no transcript file

**Added 2026-08-12, after this posture blocked every push on a machine for an entire session.**

A session that inherits `CLAUDE_CODE_CHILD_SESSION` — one started by another Claude Code process —
writes **no transcript at all** when it is interactive. `load()` then raises `FileNotFoundError`,
the handler above exits 2, and exit 2 blocks: `git push`, `gh pr merge`, `gh api` and every gated
publish tool failed in every project on that machine, with
`gate failed (FileNotFoundError) - blocking to stay safe` naming the exception and nothing that
would connect it to session persistence.

**Blocking there protects nothing, and that is the whole argument.** This gate fires on a mark; a
mark is only ever written by the `SessionStart` hook; that hook only acts when `source == "resume"`;
and a session whose transcript was never written cannot be resumed at all. The `detect()` fallback
has no rows to scan either. So the gate could not have fired in either direction — refusing the
push does not make unreviewed subagent work reviewable, it only stops the machine.

So a missing transcript **allows the call and emits a `systemMessage` saying the gate did not run**,
naming both the cause and the remedy (`CLAUDE_CODE_FORCE_SESSION_PERSISTENCE=1`). The second half is
not decoration: "prefer blocking to a check that quietly did nothing" is still right about silence,
and `except FileNotFoundError: return 0, "", ""` would reintroduce exactly the fail-open defect this
tool exists to avoid while looking like the same fix. Both halves have their own mutation in
`tests/mutation_check.py`.

**Only a missing file takes that path.** A payload with no `transcript_path` key, a path that is a
directory, a file that cannot be read — all still exit 2. Those are surprises about the harness with
no known cause; this one has a cause and a remedy.

> The two tests that pinned the old behaviour both used `/nope/missing.jsonl` as their stand-in for
> "any error", which is why the two cases could not be changed independently. They now use a
> directory (`IsADirectoryError`) and a payload with the key absent (`KeyError`), so the fail-closed
> posture is still pinned by something that is genuinely an error.

Both scripts are single-file and stdlib-only, so there is no dependency that can go missing.

## Testing

**The fixtures are generated, not captured.** They started as frozen copies of real transcripts,
which was right while this lived in a private repo — real fixtures cannot lie about the shape of the
thing being detected — and disqualifying the moment it was published.

Two rounds of that were instructive:

1. The first attempt committed **whole transcripts: 21.6 MB** of real session content, permanent in
   git history and unreviewable as a diff. Replaced by minimal row slices — keep a row only if it is
   a `queue-operation` row (Signature B balances enqueues against removes, so dropping any row
   silently changes the answer), a row carrying an `Agent`/`Task` `tool_use`, a row carrying a
   `tool_result` owned by one of those calls, or one of the file's first five rows for shape
   coverage. That got each fixture under 1 MB.
2. Slices are still real. `tests/make_fixtures.py` now **builds** the fixtures deterministically —
   no clock, no randomness, no filesystem reads — and `test_fixtures_match_the_generator`
   regenerates into a temp directory and compares byte for byte, so a hand-edited fixture is a test
   failure rather than a silent divergence.

Each synthetic fixture reproduces a measured property of the transcript it replaces:

| Case | Expected |
|---|---|
| Sync subagent killed (Signature A) | one hit, resolved to the `Agent` call's description |
| Async subagent, report unconsumed (Signature B) | the non-`completed` unmatched enqueue is reported |
| Async subagent, report consumed cleanly | no hit — a `completed` status is not the hazard, even though the enqueue is otherwise unmatched |
| Async subagent that **failed** but whose report was consumed | no hit — the enqueue/remove balance excludes it, and this is the only row that makes the balance gate observable |
| Async subagent, status missing or unparseable | one hit — fail toward reporting |
| A backgrounded Bash command's notification | no hit — no `Agent` call behind the id |
| Clean ending | no hits, no context injected |
| **Discussion, not incident** | **no hits** — the string is present, inside an `Agent` `tool_result`, and not prefix-anchored |
| **A review subagent reporting on this design** | **no hits** — passes rule 1, fails rule 2 |
| **Already-warned segment** | no hits — the warning does not repeat forever |
| Malformed / no-timestamp rows | skipped without error |

**The negative cases matter most.** A gate that fires on clean resumes gets muted within a week, and
the first design failed exactly there. Two of them are non-obvious and both are pinned by their own
fixture assertions, because otherwise they pass vacuously: the discussion fixture must genuinely
*contain* the string inside an Agent `tool_result` (otherwise "silent" means "nothing to find"), and
the clean fixture must genuinely contain unmatched `completed` enqueues (otherwise it stops guarding
against the bare-imbalance rule coming back).

Two transcript properties the parser must tolerate, both measured on the real files:

- **Rows are not sorted by timestamp** — 177 non-monotonic adjacent pairs in the interrupted file,
  84 in the clean one.
- **Transcripts are large** — 11.4 MB for one parent, ~35 MB across its 19 subagent files. Stream
  them line by line; never read one wholesale.

---

## Rejected design 1 — file mtimes plus a marker file cleared by an evidence file

The first design used file mtimes to find artifacts written after the parent's last assistant turn,
wrote a marker file keyed on `sha1(cwd)`, denied `git commit`/`push`/`merge`, and cleared on an
evidence file with one line per flagged item. An adversarial review, verified against the real
transcripts, found it unsound. The defects worth remembering:

1. **The premise was wrong** — see the corrected incident record above.
2. **`find -newermt` fails silently in both directions on darwin.** The ISO form with `Z` that
   transcripts emit gives `find: Can't parse date/time`, rc=1, zero output — a script ignoring the
   return code reads "nothing unreviewed" and never arms. Drop the `Z` and the cutoff slips ~6 hours
   early with no error at all.
3. **The core invariant is empirically false.** "A cleanly-ended session has no files newer than its
   last turn" — on the control machine, `AGENTS.md` in all seven worktrees carried one identical
   mtime. Something sweeps them; the gate would fire on clean sessions.
4. **Scale makes evidence-per-item unusable** — 294 files postdate the cutoff in one worktree,
   6,043 from the repo root. One evidence line per item is not a workflow.
5. **Worktrees nest inside the repo**, so a root-cwd session flags every parallel session's live
   writes. Also, in a worktree `.git` is a *file*, so `-not -path "*/.git/*"` prunes nothing.
6. **The "parent's last turn" cutoff excluded `tool_use` blocks**, so any session ending "committing
   now" followed by a commit flags its own intended final writes.
7. **Only the most recent quiet period is ever visible** — after one resume, the previous gap's
   orphan is invisible forever.
8. **The evidence file is self-clearing by the gated party** — a 31-character sentence opens it.
   That is not a gate; it is a prompt to type a sentence.
9. **`deny` is advisory**, and a reason string explaining how to clear it is an instruction manual.
10. **`sha1(cwd)` is the wrong key** — the unit is a session, not a directory. Two sessions in one
    worktree overwrite each other's markers, and markers outlive the worktrees they describe.
11. **The stated fail-closed posture was false** — see the exit-code table above. It reproduced the
    same fail-open defect class that a separate gate in that codebase already existed to close.

## Rejected design 2 — the bare string scan

Draft 2 replaced all of that with a single unqualified search for the partial-output notice. The
mechanism claims held up and the stateless rescan was sound, but a second review found the same
*class* of failure in new clothes — one false positive and one false negative, both fatal:

- **It fires on any session that merely discusses the string.** Of 1,898 transcripts, four contained
  it; two were genuine incidents and two were the design conversation itself, from quoting it in
  prose and reading it in command output. Worse, draft 2 printed the string plainly in the design
  document, so every session that read that document — implementer, reviewer, test author — would
  poison its own transcript permanently and gate itself, **with no clearing path**, because the
  design had deliberately removed all state. Hence qualifying rules 1, 2 and 3.
- **It misses async subagents entirely** — 81 of 181 Agent calls never return the notice. The
  motivating incident killed two subagents, one sync and one async; draft 2 caught the sync one and
  missed the other. Draft 1's miss was a one-second timing accident; draft 2's is structural. Hence
  Signature B.
- **Nothing ever cleared it.** The string is permanent in a transcript, so the warning would repeat
  on every resume and every ship action thereafter — the exact inverse of draft 1's defect 7. Hence
  the resume-segment scan window.

---

## Sequencing

1. Ship the three components above.
2. Watch for a week. Record how often the detector fires and how often the ask-prompt is a true
   positive.
3. Only if the prompt proves too noisy, revisit heavier machinery — with the defect lists above as
   the acceptance criteria.
4. **If an unevadable control is wanted, build it in CI, not in a hook.** A check that fails when a
   commit touches a client-facing deliverable without an attached review artifact covers every
   session, worktree and cloud run, and no prompt can talk it out of it. No prompt-level mechanism
   can be unevadable; pretending otherwise is the draft-1 mistake.

## Success criteria

- Fires on the interrupted fixture under **both** signatures, naming both killed subagents.
- Silent on the clean fixture.
- **Silent on a transcript that merely discusses the detector**, including one that has read this
  document. This is the criterion draft 2 failed on the day it was written, so it is a test, not an
  aspiration — "zero false positives over a week of use" was unfalsifiable and is dropped.
- Warns **once per interruption**, not once per resume thereafter.
- A resumed session that ships a branch carrying unreviewed subagent output cannot do so without a
  human keypress.
