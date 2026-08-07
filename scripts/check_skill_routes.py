#!/usr/bin/env python3
"""Gate the ROUTES into this toolkit: can the model get to a skill at all?

WHY THIS EXISTS
    Only a model-invocable skill is retrieved. A skill carrying
    `disable-model-invocation: true` is reachable in exactly two ways: the user
    types its name, or a skill the model HAS retrieved names it in its body and
    the model opens the file. Nothing else reaches it -- and the Skill tool
    refuses it outright, with a message that also tells the model not to
    reproduce the workflow by other means.

    So a reference-only skill that no LIVE skill names is dead weight. It is on
    disk, it is in the README, and no session will ever open it unless the user
    happens to remember it exists.

    Measured on 2026-08-07, before this gate: of 77 reference-only skills, 57
    were named by no live skill. The real retrieval surface was 41 of 98.

    Links from a DISABLED skill do not count. The model only reads a disabled
    skill's body after it has already been sent there, so a chain that starts
    inside the dark half never starts at all.

WHAT IT CHECKS
    1. reachability -- every reference-only skill is named in the body of at
       least one live skill.
    2. links        -- every `../<name>/SKILL.md` relative link resolves. A link
       to a skill that ships in a DIFFERENT plugin is dead on a plugin install
       (see v1.11.1); name those in backticks instead of linking them.
    3. README rows  -- every skill has exactly one index row, and no row points
       at a directory that does not exist.

    Body text costs nothing in the skill listing, so 1 is free to satisfy.

USAGE
    python3 scripts/check_skill_routes.py [REPO_ROOT] [--list]

    Exit 0 = every skill reachable, every link resolves, every README row present.
    Exit 1 = at least one failure.
"""

from __future__ import annotations

import argparse
import collections
import os
import re
import sys

SKILLS_REL = "plugins/agent-traffic-control/skills"


def split_frontmatter(text: str) -> str:
    if not text.startswith("---"):
        return ""
    first_nl = text.find("\n")
    if first_nl == -1 or text[3:first_nl].strip():
        return ""
    end = re.search(r"^---\s*$", text[first_nl + 1:], re.M)
    if not end:
        return ""
    return text[first_nl + 1: first_nl + 1 + end.start()]


def load(root: str) -> dict:
    sk = os.path.join(root, SKILLS_REL)
    out = {}
    for d in sorted(os.listdir(sk)):
        p = os.path.join(sk, d, "SKILL.md")
        if not os.path.isfile(p):
            continue
        text = open(p, encoding="utf-8").read()
        fm = split_frontmatter(text)
        out[d] = {
            "path": p,
            "body": text[len(fm) + 8:] if fm else text,
            "disabled": re.search(r"^disable-model-invocation:\s*true\s*$",
                                  fm, re.M | re.I) is not None,
        }
    return out


def inbound_from_live(skills: dict) -> dict:
    """Which LIVE skills name each skill in their body.

    Word-boundary matched: a mention of `using-git-worktrees` must not be
    counted as an inbound link to `git-worktree`. Substring matching inflates
    `git-worktree` from 1 live inbound to 4 and hides a real orphan.
    """
    pat = {n: re.compile(r"(?<![A-Za-z0-9-])" + re.escape(n) + r"(?![A-Za-z0-9-])")
           for n in skills}
    inbound = {n: [] for n in skills}
    for src, v in skills.items():
        if v["disabled"]:
            continue
        for tgt in skills:
            if tgt != src and pat[tgt].search(v["body"]):
                inbound[tgt].append(src)
    return inbound


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root", nargs="?", default=".")
    ap.add_argument("--list", action="store_true",
                    help="print every skill with its live-inbound count")
    a = ap.parse_args()

    root = a.root
    sk_dir = os.path.join(root, SKILLS_REL)
    if not os.path.isdir(sk_dir):
        print(f"error: no skills directory at {sk_dir}", file=sys.stderr)
        return 2

    skills = load(root)
    live = [n for n, v in skills.items() if not v["disabled"]]
    ref = [n for n, v in skills.items() if v["disabled"]]
    inbound = inbound_from_live(skills)

    print(f"skill-routes-gate  ·  {len(skills)} skills "
          f"({len(live)} model-invocable, {len(ref)} reference-only)\n")

    failed = False

    # 1. reachability
    orphans = [n for n in ref if not inbound[n]]
    if orphans:
        failed = True
        print(f"  UNREACHABLE ({len(orphans)}) — reference-only and named by no live "
              f"skill, so nothing can route the model to them")
        for n in orphans:
            print(f"    · {n}")
        print("  Fix: add [`name`](../name/SKILL.md) to the body of the live skill that\n"
              "  owns the nearest moment. Body text costs nothing in the listing.\n")
    else:
        print(f"  reachability  OK — all {len(ref)} reference-only skills are named "
              f"by a live skill")

    # 2. relative links resolve
    broken = []
    for d, v in skills.items():
        for m in re.finditer(r"\]\((\.\./[^)]+)\)", open(v["path"], encoding="utf-8").read()):
            tgt = os.path.normpath(os.path.join(sk_dir, d, m.group(1)))
            if not os.path.exists(tgt):
                broken.append((d, m.group(1)))
    if broken:
        failed = True
        print(f"\n  BROKEN LINKS ({len(broken)}) — dead on a plugin install")
        for d, l in broken:
            print(f"    · {d}  →  {l}")
        print("  A skill from another plugin is not at ../<name>/. Name it in backticks.")
    else:
        print(f"  links         OK — every ../<name>/SKILL.md link resolves")

    # 3. README index rows
    readme_path = os.path.join(root, "README.md")
    rows = collections.Counter()
    if os.path.isfile(readme_path):
        rows = collections.Counter(re.findall(
            r"\(plugins/agent-traffic-control/skills/([a-z0-9-]+)/\)",
            open(readme_path, encoding="utf-8").read()))
    missing = [n for n in skills if rows[n] == 0]
    dangling = [n for n in rows if n not in skills]
    duped = sorted(n for n, c in rows.items() if c > 1)
    if missing or dangling or duped:
        failed = True
        print(f"\n  README INDEX")
        for n in missing:
            print(f"    · no row: {n}")
        for n in dangling:
            print(f"    · row points at a directory that does not exist: {n}")
        for n in duped:
            print(f"    · {rows[n]} rows (want exactly 1): {n}")
    else:
        print(f"  readme rows   OK — {len(skills)} skills, exactly one index row each")

    if a.list:
        print("\n  live-inbound counts (0 on a reference-only skill is a failure):")
        for n in sorted(skills, key=lambda x: (skills[x]["disabled"], -len(inbound[x]), x)):
            kind = "ref " if skills[n]["disabled"] else "LIVE"
            print(f"    {kind}  live-inbound {len(inbound[n]):>2}  {n}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
