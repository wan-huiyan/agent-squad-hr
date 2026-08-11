#!/usr/bin/env python3
"""Gate the OUTCOME of releasing, not the status of the release job.

WHY THIS EXISTS

    Every other check in this repo looks forward: is the tree consistent NOW,
    will the next commit be valid. Nothing looked backwards at whether a release
    that should have been cut ever was — and for three months, one had not been.

    v1.13.0 is missing from the release list. The mechanism was a path filter on
    the release workflow (`paths: ['VERSION']`):

        43f4d62  "v1.13.0: ..."  manifests -> 1.13.0, VERSION untouched  -> no trigger
        6a49203  "v1.14.0: ..."  VERSION 1.12.0 -> 1.14.0                -> steps over it

    `1.13.0` never existed in VERSION on main, so no later push could cut it.

    The drift guard caught the mismatch at the time — validate_plugins.py went
    red on 43f4d62 (conclusion: failure, 2026-08-07T10:56:43Z) — and the remedy
    bumped to 1.14.0. That satisfied the guard and left the missing release
    permanently unreachable.

    **A guard tells you a state is wrong. It does not tell you what that wrong
    state already cost.** Fixing forward can satisfy the guard while leaving the
    damage in place, and the guard goes green, which reads as resolved.

    The release job cannot substitute for this check. Both branches of its
    create step exit 0, so its `conclusion: success` is byte-identical whether it
    cut a release or skipped one. It has a real failure path (empty VERSION), so
    a passing run looks like evidence the job works — but it cannot fail on the
    case that matters, because that case never reaches it. A passing instance of
    a check that only fails by not running is not evidence the check works.

WHAT IT CHECKS

    Every version this repo has ever CLAIMED to ship has a matching `vX.Y.Z`
    release. "Claimed to ship" is the union of two sources, and the union is
    load-bearing:

        VERSION history          — every value VERSION held on main
        README `## Version history` — every changelog entry

    **Neither source alone detects v1.13.0**, the hole this gate was written for.
    Measured on this repo:

        VERSION values with no release ................ 3   1.3.0  1.4.0  1.5.0
        README versions VERSION never held ............ 4   1.0.0  1.1.0  1.2.0  1.13.0
        union, with no release ........................ 7

    v1.13.0 shipped in the manifests and the README while VERSION stayed at
    1.12.0, so a VERSION-only check cannot see it — the value never existed there.
    A first draft of this gate checked VERSION only and reported v1.3.0/1.4.0/1.5.0
    while missing the case it was built for: a guard that cannot fail on the case
    that prompted it. Hence the union.

    Holes already known are listed in `.release-parity-accepted`, one
    `version  # reason` per line, so an accepted hole is RECORDED rather than
    silently tolerated, and a NEW hole is a hard failure. Baselining matters:
    a gate that ships red with seven historical findings gets muted inside a
    week, which is how a gate dies without anyone deciding to kill it.

USAGE

    python3 scripts/check_release_parity.py .            # needs gh + network
    python3 scripts/check_release_parity.py . --offline   # skip, exit 0, say so

    Exit 0 clean or all-holes-accepted; 1 on a new hole; 0 with a notice when the
    release list cannot be read (never fail CI on a network blip — that would be
    a gate whose own failure mode is invisible, which is the thing it exists for).
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

ACCEPT_FILE = ".release-parity-accepted"
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def run(args: list[str], cwd: str) -> tuple[int, str]:
    try:
        p = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=60)
        return p.returncode, p.stdout
    except (OSError, subprocess.SubprocessError):
        return 127, ""


def version_history(root: str) -> list[str]:
    """Every distinct value VERSION has held on main, oldest first."""
    code, out = run(
        ["git", "log", "--reverse", "--format=%H", "--follow", "--", "VERSION"], root
    )
    if code != 0:
        return []
    seen: list[str] = []
    for sha in out.split():
        c, blob = run(["git", "show", f"{sha}:VERSION"], root)
        if c != 0:
            continue
        v = blob.strip()
        if SEMVER.match(v) and v not in seen:
            seen.append(v)
    return seen


CHANGELOG_ENTRY = re.compile(r"^\s*[-*]\s+\*\*v?(\d+\.\d+\.\d+)\*\*")


def changelog_versions(root: str) -> list[str]:
    """Every version named in the README's `## Version history` section.

    Required because a version can ship in the manifests and the README while
    VERSION lags — which is exactly what happened with 1.13.0.
    """
    path = os.path.join(root, "README.md")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    parts = re.split(r"^##\s+Version history", text, maxsplit=1, flags=re.M | re.I)
    if len(parts) < 2:
        return []
    out: list[str] = []
    for line in parts[1].splitlines():
        m = CHANGELOG_ENTRY.match(line)
        if m and m.group(1) not in out:
            out.append(m.group(1))
    return out


def semver_key(v: str) -> tuple[int, ...]:
    return tuple(int(p) for p in v.split("."))


def released_tags(root: str) -> set[str] | None:
    """Tag names that have a GitHub Release. None if it cannot be determined."""
    code, out = run(
        ["gh", "release", "list", "--limit", "500", "--json", "tagName",
         "--jq", ".[].tagName"], root
    )
    if code != 0:
        return None
    return {line.strip() for line in out.splitlines() if line.strip()}


def accepted(root: str) -> dict[str, str]:
    path = os.path.join(root, ACCEPT_FILE)
    out: dict[str, str] = {}
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            ver, _, reason = line.partition("#")
            ver = ver.strip()
            if ver:
                out[ver] = reason.strip() or "(no reason recorded)"
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", nargs="?", default=".")
    ap.add_argument("--offline", action="store_true",
                    help="skip the release-list lookup and exit 0")
    args = ap.parse_args()
    root = os.path.abspath(args.root)

    vhist = version_history(root)
    chlog = changelog_versions(root)
    history = sorted(set(vhist) | set(chlog), key=semver_key)
    if not history:
        print("release-parity  ·  could not read VERSION history or changelog "
              "— NOTICE, not a failure")
        return 0

    only_changelog = sorted(set(chlog) - set(vhist), key=semver_key)
    print(f"release-parity  ·  {len(history)} claimed versions "
          f"({history[0]} … {history[-1]})")
    print(f"  sources: {len(vhist)} from VERSION history, {len(chlog)} from the "
          f"README changelog")
    if only_changelog:
        print(f"  shipped in the changelog but never in VERSION: "
              f"{', '.join('v' + v for v in only_changelog)}")
        print("  ^ a VERSION-only check cannot see these at all")

    if args.offline:
        print("  --offline: release list not checked. Run without it in CI.")
        return 0

    tags = released_tags(root)
    if tags is None:
        print("  could not read `gh release list` (no gh, no auth, or no network).")
        print("  NOTICE, not a failure — but this check did not run. Re-run in CI.")
        return 0

    # The version in VERSION right now is the PENDING release: on a PR branch its
    # release cannot exist yet, and on main the release job cuts it seconds after
    # the push. Including it would fail this gate on every version-bump PR, which
    # is how a gate gets muted — the exact death this check exists to prevent.
    # Found by running the gate on its own introducing PR.
    pending = ""
    vf = os.path.join(root, "VERSION")
    if os.path.exists(vf):
        with open(vf, encoding="utf-8") as fh:
            pending = fh.read().strip()

    ok = accepted(root)
    missing = [v for v in history if f"v{v}" not in tags and v != pending]
    new = [v for v in missing if v not in ok]
    known = [v for v in missing if v in ok]

    if pending and f"v{pending}" not in tags:
        print(f"  pending: v{pending} is the version this commit ships; its release "
              f"is cut on merge, so it is not counted here")

    for v in known:
        print(f"  accepted hole: v{v} — {ok[v]}")

    if not new:
        print(f"  every released version has a tag "
              f"({len(history) - len(known)} of {len(history)}; {len(known)} accepted)")
        return 0

    print()
    print(f"  FAILURES ({len(new)})")
    for v in new:
        where = []
        if v in vhist:
            where.append("VERSION held it on main")
        if v in chlog:
            where.append("the README changelog claims it")
        print(f"    · no release v{v} — {' and '.join(where)}")
        if v not in vhist:
            print("        VERSION never held this value, so no push can trigger a "
                  "release for it;")
            print("        it must be created by hand against the right commit.")
    print()
    print("  A release was skipped. The release job's `success` does not detect this —")
    print("  both branches of its create step exit 0. Either cut it:")
    print(f"      gh release create v{new[-1]} --title v{new[-1]} --generate-notes")
    print(f"  or, if it is genuinely unreachable, record it in {ACCEPT_FILE}")
    print("  with the reason. Do not step over it with the next bump.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
