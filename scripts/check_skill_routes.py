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
    4. README count -- every "N skills" claim ABOVE `## Version history` equals
       the number of skill directories.
    5. citations    -- no markdown file cites a backticked skill-shaped name that
       resolves to nothing, unless it is recorded in `.skill-citations-accepted`.

    Body text costs nothing in the skill listing, so 1 is free to satisfy.

WHY 4 IS HERE AND NOT IN A GATE OF ITS OWN
    This script ALREADY counts the skills on every run and ALREADY parses the
    README's index rows. It knew the right number and never compared it to the
    one the front page publishes -- so the README said 98 skills against a tree
    of 99 from v1.21.0 until v1.25.0 corrected it by hand, across the opening
    sentence, the install instruction and the buckets sentence. The changelog
    disagreed with itself over the same window (v1.21.0 says 99, v1.22.0 says 98,
    v1.23.0 says 99), which is the tell that no check was involved.

    A new CI step would also have been one more thing to keep in
    `.githooks/pre-push` -- the hand-maintained parity v1.27.0 exists to police.

WHY 5 IS HERE
    Check 1 asks whether a reference-only skill is reachable FROM a live skill.
    Check 5 asks the opposite question -- whether a name a skill points AT exists
    at all -- and nothing had ever asked it. Measured: 51 names across 77 sites in
    41 files, mostly in "Sister skill:" and "See also:" lines, which is precisely
    where a reader goes when the current skill did not answer their question.

    Check 2 could not catch them either: every one is a bare backticked name, not
    a `[...](../name/SKILL.md)` link, so a link-shaped gate fires on none of them
    and could never see one in frontmatter.

USAGE
    python3 scripts/check_skill_routes.py [REPO_ROOT] [--list]

    Exit 0 = every skill reachable, every link resolves, every README row present,
             every front-page count correct, every cited skill name resolves.
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


# --------------------------------------------------------------------------- #
# 4. README front-page skill count
# --------------------------------------------------------------------------- #
CHANGELOG_HEADING = re.compile(r"^##\s+Version history\s*$", re.M)

# Tolerates markdown links BETWEEN the number and the noun. The front page's first
# sentence reads "A coordination toolkit of 99 [Claude Code](https://…) skills", and
# a bare `\d+\s+skills` regex does not match it -- the most-read line in the repo and
# the exact claim this check exists for. Measured on the real README: the naive form
# finds 2 of the 3 header claims and the one it drops is line 3.
COUNT_CLAIM = re.compile(r"\b(\d+)\s+(?:\[[^\]]*\]\([^)]*\)\s+)*skills?\b")


def count_claim_self_test() -> bool:
    """Prove the pattern still sees BOTH forms before trusting its silence.

    Zero matches in the header is reported as a failure, which covers a header that
    stopped stating a count. It does NOT cover a pattern edit that quietly stops
    matching the LINKED form while still matching the two bare ones -- that would
    leave the front page's first sentence ungated while every message still read OK.
    A self-test whose fixture cannot distinguish the broken version is not a test,
    so both forms are asserted on every run.
    """
    linked = "A coordination toolkit of 42 [Claude Code](https://x.y/z) skills — plus"
    bare = "one shot, gets all 42 skills"
    return ([m.group(1) for m in COUNT_CLAIM.finditer(linked)] == ["42"]
            and [m.group(1) for m in COUNT_CLAIM.finditer(bare)] == ["42"])


def check_readme_count(root: str, n_skills: int) -> bool:
    """Every "N skills" claim above the changelog must equal the real count.

    Scoped to the header on purpose: changelog entries state what was true at the
    time and must keep their historical figures. There are 45 such matches below the
    heading, and a gate that fired on those is a gate that gets muted.
    """
    path = os.path.join(root, "README.md")
    if not os.path.isfile(path):
        print("\n  README COUNT — README.md not found, so the front-page count "
              "cannot be checked")
        return False
    if not count_claim_self_test():
        print("\n  README COUNT — the pattern SELF-TEST failed: it no longer matches "
              "the\n  linked form `N [text](url) skills`. Its silence on the README "
              "means nothing\n  until that is fixed.")
        return False
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    parts = CHANGELOG_HEADING.split(text, maxsplit=1)
    if len(parts) < 2:
        print("\n  README COUNT — no `## Version history` heading, so the header "
              "cannot be told\n  apart from the changelog. Refusing to scan the whole "
              "file: every historical\n  figure would read as a failure.")
        return False
    claims = [(i, m.group(1))
              for i, line in enumerate(parts[0].split("\n"), start=1)
              for m in COUNT_CLAIM.finditer(line)]
    if not claims:
        print("\n  README COUNT — no `N skills` claim found above the changelog. "
              "Either the front\n  page stopped stating a count or this check stopped "
              "finding it; both need a human.")
        return False
    wrong = [(i, v) for i, v in claims if int(v) != n_skills]
    if wrong:
        print(f"\n  README COUNT ({len(wrong)} of {len(claims)} claim(s) wrong)")
        for i, v in wrong:
            print(f"    · README.md:{i} claims {v} skills; the tree has {n_skills}")
        return False
    print(f"  readme count  OK — {len(claims)} front-page claim(s), all {n_skills}")
    return True


# --------------------------------------------------------------------------- #
# 5. dangling skill citations
# --------------------------------------------------------------------------- #
CITATION_ACCEPT_REL = ".skill-citations-accepted"
SKILL_SHAPED = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+){2,}$")
PLUGIN_QUALIFIED = re.compile(r"^([a-z0-9-]+):([a-z0-9]+(?:-[a-z0-9]+){2,})$")
FENCE = re.compile(r"^\s*(`{3,}|~{3,})")


def backticked_names(text: str):
    """Yield (lineno, token) for every `...` span, FENCE-AWARE.

    THE TRAP, recorded because the first version of this sweep was wrong in a way
    that looked right. A plain `` `([^`]+)` `` regex pairs backticks ACROSS ``` fence
    boundaries: an odd number of backticks inside a fence flips the parity for every
    line after it. That version found the one known dangling name in 2 of its 7
    files -- a 71% undercount that reported clean-looking output.

    So: fence state is tracked per line, and backticks pair only WITHIN a single
    non-fenced line, so an unbalanced backtick stops at the end of its own line
    instead of leaking into the next.
    """
    in_fence, marker = False, None
    for i, line in enumerate(text.split("\n"), start=1):
        m = FENCE.match(line)
        if m:
            ch = m.group(1)[0]
            if not in_fence:
                in_fence, marker = True, ch
            elif ch == marker:
                in_fence, marker = False, None
            continue
        if in_fence:
            continue
        pos, n = 0, len(line)
        while pos < n:
            if line[pos] != "`":
                pos += 1
                continue
            run = 1
            while pos + run < n and line[pos + run] == "`":
                run += 1
            delim = "`" * run
            close = line.find(delim, pos + run)
            if close == -1:
                break
            yield i, line[pos + run:close]
            pos = close + run


_FENCE_FIXTURE = """\
Body text citing `alpha-beta-gamma` before any fence.

```bash
# `sample-code-inside-fence` is sample code, NOT a citation, and must not be reported
echo "one ` here"
```

And after the fence, `delta-epsilon-zeta` must still be found.
"""


def citation_self_test() -> bool:
    """Prove fence handling is alive, on a fixture built from the two regressions.

    Three assertions, because the first version had only the first two and a
    mutation run proved it worthless: disabling the fence SKIP entirely left it
    passing, since the fixture held no complete backticked name inside the fence for
    the broken version to wrongly report. A self-test whose fixture cannot tell the
    broken version apart is the defect it exists to catch, one level up.

      1/2. both names OUTSIDE the fence are found -- guards cross-line pairing;
      3.   the name INSIDE the fence is NOT found -- guards the fence skip itself.
    """
    found = {t for _, t in backticked_names(_FENCE_FIXTURE)}
    return ("alpha-beta-gamma" in found
            and "delta-epsilon-zeta" in found
            and "sample-code-inside-fence" not in found)


def citations_accepted(root: str):
    """{name: reason} for names that dangle from THIS repo but are legitimate.

    FAILS CLOSED, and unlike `.hook-parity-accepted` its absence is a failure rather
    than a stricter policy: these entries are the deliberate historical citations the
    README must keep, so a missing file would turn them all into failures and produce
    exactly the wall of noise that gets a check muted. Absence is a broken checkout.
    An empty or comments-only file fails the same way, for the same reason -- 'the
    baseline was not there' must never read as 'the tree is dirty'.
    """
    path = os.path.join(root, CITATION_ACCEPT_REL)
    if not os.path.isfile(path):
        print(f"\n  CITATIONS — {CITATION_ACCEPT_REL} not found. It records the "
              f"deliberate\n  historical and external citations this repo keeps; "
              f"without it every one of\n  them reads as a failure. Restore it.")
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            content = fh.read()
    except OSError as e:
        print(f"\n  CITATIONS — cannot read {CITATION_ACCEPT_REL}: {e}")
        return None
    accepted = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, _, reason = line.partition("#")
        name = name.strip()
        if name:
            accepted[name] = reason.strip() or "(no reason recorded)"
    if not accepted:
        print(f"\n  CITATIONS — {CITATION_ACCEPT_REL} loaded 0 names. An empty accept "
              f"file and a\n  missing one fail the same way here, for the same reason.")
        return None
    return accepted


def check_citations(root: str, skills: dict) -> bool:
    """No markdown file may cite a backticked skill name that resolves to nothing."""
    if not citation_self_test():
        print("\n  CITATIONS — the sweep's SELF-TEST failed: fence handling is no "
              "longer working,\n  so this check undercounts silently. A clean result "
              "from it means nothing.")
        return False
    accepted = citations_accepted(root)
    if accepted is None:
        return False

    known = set(skills)
    hooks = os.path.join(root, "plugins/agent-traffic-control/hooks")
    if os.path.isdir(hooks):
        known |= {d for d in os.listdir(hooks)
                  if os.path.isdir(os.path.join(hooks, d))}

    # EVERY markdown file, discovered rather than enumerated. An enumerated list was
    # already one file short on the day it was written -- the hook ships its own
    # README.md and DESIGN.md inside the plugin, read by the same audience and able
    # to carry the same dead pointer. A walk also covers the next doc someone adds.
    # Dot-directories are pruned, which excludes .git and generated caches.
    targets = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for fn in sorted(filenames):
            if fn.endswith(".md"):
                targets.append(os.path.join(dirpath, fn))
    targets.sort()
    if not targets:
        print("\n  CITATIONS — the sweep found no markdown files to scan")
        return False

    hits, scanned = {}, 0
    for p in targets:
        try:
            with open(p, encoding="utf-8") as fh:
                text = fh.read()
        except OSError as e:
            print(f"\n  CITATIONS — cannot read {p}: {e}")
            return False
        scanned += 1
        rel = os.path.relpath(p, root)
        for lineno, tok in backticked_names(text):
            tok = tok.strip()
            name = tok if SKILL_SHAPED.match(tok) else None
            if name is None:
                pm = PLUGIN_QUALIFIED.match(tok)
                name = pm.group(2) if pm else None
            if not name or name in known or name in accepted:
                continue
            hits.setdefault(name, []).append((rel, lineno))

    # A walk that suddenly reads far fewer files than there are skills is a broken
    # walk, not a clean tree.
    if scanned < len(skills):
        print(f"\n  CITATIONS — scanned only {scanned} markdown files against "
              f"{len(skills)} skills;\n  the sweep is not reading the tree")
        return False

    if hits:
        n_sites = sum(len(v) for v in hits.values())
        n_files = len({f for v in hits.values() for f, _ in v})
        print(f"\n  DANGLING CITATIONS ({len(hits)} name(s), {n_sites} site(s), "
              f"{n_files} file(s))")
        for name in sorted(hits):
            where = ", ".join(f"{f}:{l}" for f, l in hits[name][:4])
            more = "" if len(hits[name]) <= 4 else f" (+{len(hits[name]) - 4} more)"
            print(f"    · {name} — {where}{more}")
        print("  A backticked skill name that resolves to nothing costs the reader a "
              "search that\n  cannot succeed. Fix the text: retarget to a skill that "
              "genuinely covers it, drop\n  the pointer, or say plainly that nothing "
              "here covers it. If the name is\n  legitimately external or historical, "
              f"add it to {CITATION_ACCEPT_REL} with the reason.")
        return False

    print(f"  citations     OK — {scanned} markdown files, every backticked skill "
          f"name resolves ({len(accepted)} accepted)")
    return True


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

    # 4. README front-page count
    if not check_readme_count(root, len(skills)):
        failed = True

    # 5. dangling skill citations
    if not check_citations(root, skills):
        failed = True

    if a.list:
        print("\n  live-inbound counts (0 on a reference-only skill is a failure):")
        for n in sorted(skills, key=lambda x: (skills[x]["disabled"], -len(inbound[x]), x)):
            kind = "ref " if skills[n]["disabled"] else "LIVE"
            print(f"    {kind}  live-inbound {len(inbound[n]):>2}  {n}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
