---
name: worktree-does-not-isolate-shared-installed-artefacts
description: |
  A git worktree isolates the SOURCE TREE and nothing else. Anything installed
  or cached under a key that is not the worktree path — a simulator keyed by
  bundle id, DerivedData keyed by project path, a plugin cache keyed by version
  string, a venv keyed by package name — is shared by every worktree on the
  machine, so a build/test/run in one worktree can silently exercise ANOTHER
  worktree's artefact. Use when: (1) a test result contradicts one you already
  trust, or reports values from a build you reverted; (2) suites you never
  touched fail, or a "clean worktree" baseline disagrees with a full run;
  (3) two runs that should differ produce identical output, or a fix appears to
  have no effect; (4) several sessions/worktrees build the same app on one
  machine. Fix: check PROVENANCE (bytes and compiled-in source paths), not
  version labels; uninstall/pin the shared artefact rather than trusting a
  rebuild; and verify a staleness fix the way you verified the staleness.
author: Claude Code
version: 1.0.0
date: 2026-08-05
disable-model-invocation: true
---

# A worktree does not isolate anything installed outside it

## Problem

Worktrees make source isolation cheap, which makes it easy to believe the whole
build is isolated. It is not. The worktree is one input; every other input is
keyed by something else and is therefore **shared by every worktree on the
machine**:

| keyed by | shared artefact |
|---|---|
| package name | venv / editable install (see `verify-pytest-imports-worktree-not-primary-checkout`) |
| bundle id | an installed app on a simulator/emulator/device |
| project path *or* a hash of it | build caches (Xcode DerivedData, gradle, cargo target dirs) |
| version string | a plugin/tool cache directory |
| port | a dev server another worktree started |

So a run in worktree A can exercise worktree B's artefact, and **nothing in the
output says so**. There is no crash and no blank — just a confident, complete,
internally consistent answer about the wrong code.

## Context / Trigger Conditions

- Several sessions or worktrees on one machine building the same app.
- A test result **contradicts one you already trust** — especially if it reports
  values matching a build you reverted earlier.
- Suites your diff never touched fail, or fail *differently* between two runs.
- A "clean worktree" baseline disagrees with a full run. **The baseline is not
  automatically clean** — it shares every artefact in the table above.
- A fix appears to have no effect, or a reverted bug still appears.

## Why it happens

Each of these caches is keyed on identity the worktree does not participate in.
A simulator holds **one app per bundle id**, so whichever worktree installed
last wins and the next `xcodebuild test` may reuse it. A tool cache directory
named for a version is refreshed on the *version*, so republishing the same
version leaves stale content behind a correct-looking label.

**The three worst properties, in order:**

1. **The failure is confident.** It produces detailed, plausible, wrong results
   rather than an error.
2. **Detection by counting does not work** where the artefact is an install
   rather than a bundle — the cases *do* run.
3. **The remedy is where the bug gets created.** Copying, syncing and caching
   are exactly what you reach for to fix staleness, so a sync can reintroduce
   it — including into the directory you were repairing.

## Solution

**1. Check provenance, not labels.** A version number, a directory name and a
filename are labels; a label matching is not evidence the contents match.

```bash
md5 -q "$BUILT/App" ; md5 -q "$INSTALLED/App"        # bytes, not names
diff -q <(git show HEAD:path/to/file) cache/path/to/file
```

Best of all, use identity the toolchain compiled in. Test frameworks print the
**source path recorded at compile time**; if it names another worktree, the run
is void:

```bash
grep -oE "/[^:]*/Tests/[A-Za-z]+\.(swift|py|ts)" run.log | sed 's|/Tests/.*||' | sort -u
```

**2. Prevent rather than detect**, where the artefact is an install:

```bash
xcrun simctl uninstall "$UDID" com.example.app        # before every run
```

**3. Pin the shared cache to this worktree** where the tool allows it
(`-derivedDataPath`, `PYTHONPATH`, `CARGO_TARGET_DIR`, `GRADLE_USER_HOME`).

**4. When two results contradict each other, stop reasoning and look.** Install
the built artefact somewhere fresh and observe it directly. This is minutes and
it terminates the argument.

## Verification

- The provenance check names **only this worktree**.
- Re-run after the fix and confirm the contradicting result flips.
- **Verify a staleness fix the way you verified the staleness** — print what
  each artefact *declares* against what it *contains*, on one line, before
  saying it is fixed.

## Example

One machine, ten worktrees, one iOS app, 2026-08-05. The same shape three times:

1. **Stale test bundle.** `xcodebuild test` printed `** TEST SUCCEEDED **`
   having executed **zero** cases — an `-only-testing:` filter naming a method
   the built bundle predated matches nothing, and matching nothing is not an
   error.
2. **Stale install.** A simulator kept serving an app `xcodebuild` believed it
   had replaced, through a `clean` and a `simctl erase`: seven failing suites
   plus a layout guard reporting the **exact values of a build reverted an hour
   earlier**. The same build, installed by hand on a second simulator and
   photographed, was correct. Then a *clean-worktree baseline* ran test bundles
   built by two **other** worktrees and was silently void — caught only because
   the failure messages carried their compiled-in source paths.
3. **Stale tool cache — self-inflicted.** A cache directory named `1.14.1` held
   content 44 lines short of the published 1.14.1, so a skill step written the
   day before was not running. **While syncing it, the session copied 1.14.2's
   content into the `1.14.1` directory** — recreating "same version string,
   different content", the defect it had just spent twenty minutes diagnosing.

The run that got polluted was the one that bypassed the wrapper doing the
uninstall. Use your own tooling, especially when you are in a hurry.

## Notes

- Scope check before blaming the shared artefact: if only *your* suites fail,
  suspect your change first. This pattern's signature is failures in areas the
  diff never touched, or two runs that should differ agreeing.
- `simctl erase` does **not** guarantee a fresh install on the next run; it was
  observed not to.

## References

- `verify-pytest-imports-worktree-not-primary-checkout` — the same
  failure in Python; this skill is its generalisation.
- `prove-test-failures-pre-existing-via-clean-worktree` — the right method for
  "mine or pre-existing?", and the one whose baseline this pattern can void.
- `concurrent-session-checkout-clobbers-shared-worktree`, `using-git-worktrees`.
