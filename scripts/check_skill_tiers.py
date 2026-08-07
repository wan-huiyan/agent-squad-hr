#!/usr/bin/env python3
"""Hold the skill listing inside its budget, by policy rather than by luck.

WHY THIS EXISTS
    `check_skill_descriptions.py` (vendored, do not edit) measures the listing and
    tells you when it is over. It does not stop the next skill from putting it over.
    v1.18.0 cut the listing from 23,174 chars to 7,544 against an 8,000-char budget,
    which leaves room for roughly two more skills. Without a gate that is a state the
    repo drifts out of silently -- and the failure is invisible: descriptions get
    collapsed to bare names, everything still "works", and the model just stops being
    able to see what a skill is for.

    So every live skill declares a SIZE CLASS, each class has a headcount cap and a
    length ceiling, and promoting a skill means naming the one it displaces.

THE CLASSES, and why size is decided this way
    The listing budget is global -- roughly a hundred model-invocable skills from
    every installed plugin compete for it -- and the harness fills it by usage rank
    first, then array position. So:

      rich      a skill with a `skillUsage` record is admitted regardless of size and
                its description is certain to be READ. Spend characters there.
      short     zero usage, and the name does not say when to reach for it. The
                description is invisible today; its length only decides whether it can
                ever fit leftover slack. Keep it small, make it a classifier.
      name-led  zero usage, but the name already states the moment. One sentence.

    Measured on 2026-08-07, on this machine's installed copy: of 20 entries, exactly 7
    carried a description, and those 7 were exactly the 7 with a usage record.

WHAT IT CHECKS  (exit 1 on any)
    1. every live skill declares `listing_tier: rich|short|name-led`, and no
       reference-only skill declares one.
    2. headcount caps per class, and on the total.
    3. per-class description ceilings.
    4. the listing total, recomputed with the vendored gate's own formula.
    5. every reference-only skill is reachable from a LIVE skill's body.
    6. no cross-link or provenance boilerplate inside a description.
    7. every SKILL.md has a frontmatter that PARSES -- a closing `---` on its own
       line. This one is not a style rule. `_split_frontmatter` returns None without
       it, `parse_skill` returns None, and the vendored gate then drops the skill from
       its own census: a missing delimiter took the header from
       `98 SKILL.md (20 model-invocable)` to `97 SKILL.md (19 model-invocable)` and
       still exited 0. Nothing reports it. Verified by breaking one file on purpose.

USAGE
    python3 scripts/check_skill_tiers.py [ROOT]
    python3 scripts/check_skill_tiers.py . --context 200000 --bytes-per-token 4
    python3 scripts/check_skill_tiers.py . --profile strict     # the 6,000-char target
    python3 scripts/check_skill_tiers.py . --why                # print the slate
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
# Reachability is DELEGATED, not re-derived. Two gates that each decide locally what
# "reachable" means promptly disagree -- the same defect the funnel hit when two
# harnesses each classified failure_kind for themselves.
from check_skill_routes import load as load_skills, inbound_from_live  # noqa: E402

TIERS = ("rich", "short", "name-led")

# Headcount caps. These are deliberately above today's slate (7/6/7 of 20) so a
# genuine addition is possible, and deliberately not far above, so it is a decision.
CAPS = {"rich": 8, "short": 8, "name-led": 10}
TOTAL_CAP = 24

PROFILES = {
    # the shipped slate: 8,000-char budget, an opus-class model at 200k context
    "default": {"rich": 600, "short": 280, "name-led": 160,
                "overrides": {"git-worktree": 300}, "target": 7643},
    # the tighter target for a model that only gets 6,000 chars of listing. NOT the
    # shipped slate -- v1.18.0 lands at 7,544 and does not meet this. Kept so the gap
    # is a command rather than a memory.
    "strict": {"rich": 430, "short": 200, "name-led": 120,
               "overrides": {"git-worktree": 300}, "target": 5863},
}

# Boilerplate that belongs in the BODY. A description is resident in context on every
# turn, so a cross-link there costs budget every turn and buys nothing: a user never
# types another skill's name.
BANNED = ("Covers:", "Sister to", "See also", "Related but distinct",
          "Core insight", "Demonstrated ROI")

MAX_DESC_CHARS = 1536      # skillListingMaxDescChars
ENTRY_OVERHEAD = 4         # name + 4 with a description
HARD_CEILING = 8000        # never ship a listing above this


def scalar(fm: str, key: str) -> str:
    """Read one YAML scalar: plain, quoted, folded (>) or block (|).

    Mirrors check_skill_descriptions.py::_scalar so both gates read the identical
    string out of the same file.
    """
    m = re.search(r"^%s:[ \t]*(.*)$" % re.escape(key), fm, re.M)
    if not m:
        return ""
    head = m.group(1).strip()
    if head[:1] in ("|", ">"):
        lines = fm[m.end():].splitlines()
        body = []
        for line in (lines[1:] if lines and not lines[0].strip() else lines):
            if line.strip() and not line[:1].isspace():
                break
            body.append(line.strip())
        return re.sub(r"\s+", " ", " ".join(p for p in body if p)).strip()
    if not head:
        return ""
    if len(head) >= 2 and head[0] == head[-1] and head[0] in ("'", '"'):
        head = head[1:-1]
    tail = []
    for line in fm[m.end():].splitlines()[1:]:
        if not line.strip() or not line[:1].isspace():
            break
        tail.append(line.strip())
    if tail:
        head = head + " " + " ".join(tail)
    return re.sub(r"\s+", " ", head).strip()


def frontmatter(text: str) -> str:
    if not text.startswith("---"):
        return ""
    nl = text.find("\n")
    if nl == -1 or text[3:nl].strip():
        return ""
    end = re.search(r"^---\s*$", text[nl + 1:], re.M)
    return text[nl + 1: nl + 1 + end.start()] if end else ""


def usage_records() -> dict:
    """`skillUsage` out of ~/.claude.json, keyed `<plugin>:<skill>`.

    Absent or unreadable is UNKNOWN, never zero -- a missing file must not silently
    reclassify every skill as unused. --why prints a dash for it.
    """
    p = os.path.expanduser("~/.claude.json")
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh).get("skillUsage") or {}
    except Exception:
        return {}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root", nargs="?", default=".")
    ap.add_argument("--context", type=int, default=200_000,
                    help="context window the budget is sized against (default 200,000)")
    ap.add_argument("--bytes-per-token", type=int, default=4,
                    help="chars per token used to size the budget (default 4). Pass 3 to "
                         "check the tighter budget a different tokenizer implies.")
    ap.add_argument("--profile", choices=sorted(PROFILES), default="default")
    ap.add_argument("--why", action="store_true",
                    help="print the slate: size, live-inbound count, usage record")
    a = ap.parse_args()

    root = a.root
    if not os.path.isdir(os.path.join(root, "plugins/agent-traffic-control/skills")):
        print(f"error: no skills directory under {root}", file=sys.stderr)
        return 2

    prof = PROFILES[a.profile]
    skills = load_skills(root)
    inbound = inbound_from_live(skills)
    usage = usage_records()

    info = {}
    unparseable = []
    for name, v in skills.items():
        raw = open(v["path"], encoding="utf-8").read()
        fm = frontmatter(raw)
        if not fm:
            unparseable.append(name)
        desc = scalar(fm, "description")
        when = scalar(fm, "whenToUse") or scalar(fm, "when_to_use")
        full = f"{desc} - {when}" if when else desc
        info[name] = {"tier": scalar(fm, "listing_tier"), "desc": full,
                      "chars": len(full), "disabled": v["disabled"]}

    live = sorted(n for n in info if not info[n]["disabled"])
    ref = sorted(n for n in info if info[n]["disabled"])
    fails = []

    print(f"skill-tier-gate  ·  profile {a.profile}  ·  {len(skills)} skills "
          f"({len(live)} live, {len(ref)} reference-only)\n")

    # 7 -- frontmatter parses at all. Checked FIRST: without it every count below,
    # including the vendored gate's own census, is quietly computed over fewer skills.
    if unparseable:
        fails.append(f"{len(unparseable)} SKILL.md with no parseable frontmatter "
                     f"(a closing `---` must be on its own line): "
                     f"{', '.join(sorted(unparseable))}. The vendored cap gate DROPS "
                     f"these from its census and still exits 0 — it is not a warning "
                     f"you will see anywhere else.")

    # 1 -- every live skill declares a class; no reference-only skill does
    for n in live:
        t = info[n]["tier"]
        if t not in TIERS:
            fails.append(f"{n}: live skill has no `listing_tier: rich|short|name-led`"
                         + (f" (found {t!r})" if t else ""))
    for n in ref:
        if info[n]["tier"]:
            fails.append(f"{n}: `listing_tier` present alongside "
                         f"`disable-model-invocation: true` — a reference-only skill "
                         f"never enters the listing, so it has no class")

    # 2 -- headcounts
    holders = {t: sorted(n for n in live if info[n]["tier"] == t) for t in TIERS}
    for t in TIERS:
        if len(holders[t]) > CAPS[t]:
            fails.append(f"class {t} holds {len(holders[t])}, cap {CAPS[t]}. Current "
                         f"holders: {', '.join(holders[t])}. Adding one means REMOVING "
                         f"one — name it in the same pull request.")
    if len(live) > TOTAL_CAP:
        fails.append(f"{len(live)} live skills, cap {TOTAL_CAP}. Current: "
                     f"{', '.join(live)}. Adding one means removing one — name it in "
                     f"the same pull request.")

    # 3 -- per-class ceilings
    for n in live:
        t = info[n]["tier"]
        if t not in TIERS:
            continue
        ceil = prof["overrides"].get(n, prof[t])
        if info[n]["chars"] > ceil:
            fails.append(f"{n}: description {info[n]['chars']} chars, {t} ceiling "
                         f"{ceil} on the {a.profile} profile")

    # 4 -- the listing total, by the vendored gate's own formula
    total = sum(len(n) + ENTRY_OVERHEAD + min(info[n]["chars"], MAX_DESC_CHARS)
                for n in live) + max(0, len(live) - 1)
    budget = int(a.context * a.bytes_per_token * 0.01)
    print(f"  listing {total:,} chars  ·  budget {budget:,} "
          f"({a.context:,} ctx × {a.bytes_per_token} chars/token × 1%)  ·  "
          f"{a.profile} target {prof['target']:,}")
    if total > HARD_CEILING:
        fails.append(f"listing {total:,} chars is above the hard ceiling "
                     f"{HARD_CEILING:,} — the harness will collapse descriptions to "
                     f"bare names at 200k context on any tokenizer")
    elif total > prof["target"]:
        fails.append(f"listing {total:,} chars is over the {a.profile} target "
                     f"{prof['target']:,}. Under the hard ceiling, but the margin that "
                     f"absorbs the next skill is gone.")
    if total > budget:
        print(f"  WARNING: over budget by {total - budget:,} chars at "
              f"{a.bytes_per_token} chars/token. A model given only {budget:,} chars of "
              f"listing has that much collapsed to bare names; run `--profile strict` "
              f"for the ceilings that would fit {budget:,}.")
    else:
        print(f"  fits, {budget - total:,} chars to spare")

    # 5 -- reachability (delegated)
    orphans = [n for n in ref if not inbound[n]]
    if orphans:
        fails.append(f"{len(orphans)} reference-only skill(s) named by no LIVE skill, so "
                     f"nothing can route the model to them: {', '.join(orphans)}")

    # 6 -- boilerplate in a description
    for n in live:
        for b in BANNED:
            if b in info[n]["desc"]:
                fails.append(f"{n}: description contains {b!r}. A cross-link or a "
                             f"provenance claim is resident in context on every turn "
                             f"and buys nothing — a user never types another skill's "
                             f"name. Move it into the body.")

    if a.why:
        print(f"\n  {'tier':9}{'chars':>6}{'ceil':>6}{'live-in':>9}{'usage':>7}  skill")
        for t in TIERS:
            for n in holders.get(t, []):
                ceil = prof["overrides"].get(n, prof[t])
                u = usage.get(f"agent-traffic-control:{n}")
                ustr = str(u["usageCount"]) if u else ("-" if not usage else "0")
                print(f"  {t:9}{info[n]['chars']:>6}{ceil:>6}"
                      f"{len(inbound[n]):>9}{ustr:>7}  {n}")
        print(f"\n  reference-only, by inbound live routes (0 is a failure):")
        for n in sorted(ref, key=lambda x: (len(inbound[x]), x)):
            print(f"  {'ref':9}{info[n]['chars']:>6}{'':>6}{len(inbound[n]):>9}"
                  f"{'':>7}  {n}")
        if not usage:
            print("\n  usage column is '-': ~/.claude.json holds no skillUsage that "
                  "could be read. UNKNOWN, not zero.")

    if fails:
        print(f"\n  FAILURES ({len(fails)})")
        for f in fails:
            print(f"    · {f}")
        return 1
    print("\n  tier policy OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
