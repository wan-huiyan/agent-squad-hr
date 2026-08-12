#!/usr/bin/env python3
"""Structural validation for a Claude Code plugin marketplace repo.

Checks (stdlib only, no external deps):
  1. .claude-plugin/marketplace.json parses and has name / owner / plugins[].
  2. Every marketplace plugin `source` dir exists and is registered exactly once.
  3. Every plugin dir on disk is registered in marketplace.json (no orphans).
  4. Every plugin has a .claude-plugin/plugin.json that parses, with name == dir basename,
     and that name matches the marketplace entry.
  5. Every plugin exposes a skill: either plugins/<name>/SKILL.md, or a nested
     plugins/<name>/skills/<skill>/SKILL.md set (multi-skill plugin).
  6. Every SKILL.md frontmatter `name:` is a valid skill name -- at most 64 characters,
     lowercase letters / digits / single hyphens, no leading, trailing or doubled hyphen
     -- and equals its containing directory name.
     WHERE THE 64 COMES FROM: the Agent Skills specification
     (https://agentskills.io/specification), "Max 64 characters. Lowercase letters,
     numbers, and hyphens only.", which the Skills API restates. Claude Code's own skill
     docs do NOT state a cap, so this is a PORTABILITY gate, not a local style rule -- an
     over-long name loads here and fails a spec validator elsewhere. Five skills shipped
     at 65-72 characters, four of them in v1.7.0, and nothing here noticed until v1.25.0.
  7. If a VERSION file exists: it is non-empty; and for a single-plugin repo it must
     equal that plugin's plugin.json version (drift guard).
  8. Every marketplace entry's `version` equals that plugin's plugin.json version.
     Without this, a release can bump VERSION + plugin.json and leave the marketplace
     entry consumers actually read on the previous version, and CI passes anyway.
     81ebb0f (v1.5.0) shipped exactly that way -- VERSION and plugin.json at 1.5.0,
     marketplace.json still 1.4.0 -- and was silently corrected by f1254dd (v1.6.0).
     The same drift recurred in afbee80 and was caught in review, not by CI.

Exit 0 = all good; exit 1 = one or more failures (printed).
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
errors = []
warnings = []


def err(m): errors.append(m)
def warn(m): warnings.append(m)


def frontmatter_name(skill_md):
    """Return the `name:` value from a SKILL.md YAML frontmatter block, or None."""
    try:
        with open(skill_md, encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        err(f"cannot read {skill_md}: {e}")
        return None
    if not text.startswith("---"):
        err(f"{skill_md}: missing YAML frontmatter")
        return None
    end = text.find("\n---", 3)
    block = text[3:end] if end != -1 else text
    m = re.search(r"^name:\s*(.+?)\s*$", block, re.MULTILINE)
    if not m:
        err(f"{skill_md}: no `name:` in frontmatter")
        return None
    return m.group(1).strip().strip('"').strip("'")


def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        err(f"invalid JSON {path}: {e}")
        return None


def main():
    mkt_path = os.path.join(ROOT, ".claude-plugin", "marketplace.json")
    if not os.path.isfile(mkt_path):
        err(".claude-plugin/marketplace.json not found")
        return finish()
    mkt = load_json(mkt_path)
    if mkt is None:
        return finish()
    for key in ("name", "owner", "plugins"):
        if key not in mkt:
            err(f"marketplace.json missing top-level `{key}`")
    plugins = mkt.get("plugins", [])
    registered = {}
    mkt_versions = {}
    for p in plugins:
        name, source = p.get("name"), p.get("source", "")
        if not name or not source:
            err(f"marketplace plugin entry missing name/source: {p}")
            continue
        if name in registered:
            err(f"plugin `{name}` registered more than once in marketplace.json")
        registered[name] = source.lstrip("./")
        mkt_versions[name] = p.get("version")

    plugins_dir = os.path.join(ROOT, "plugins")
    on_disk = set()
    if os.path.isdir(plugins_dir):
        on_disk = {d for d in os.listdir(plugins_dir)
                   if os.path.isdir(os.path.join(plugins_dir, d))}

    # orphan dirs not in marketplace
    for d in sorted(on_disk - {os.path.basename(s) for s in registered.values()}):
        err(f"plugins/{d} exists on disk but is not registered in marketplace.json")

    for name, rel in registered.items():
        pdir = os.path.join(ROOT, rel)
        if not os.path.isdir(pdir):
            err(f"marketplace source `{rel}` (plugin {name}) does not exist")
            continue
        pj = os.path.join(pdir, ".claude-plugin", "plugin.json")
        if not os.path.isfile(pj):
            err(f"{rel}: missing .claude-plugin/plugin.json")
        else:
            pjd = load_json(pj)
            if pjd is not None:
                if pjd.get("name") != os.path.basename(rel):
                    err(f"{pj}: name `{pjd.get('name')}` != dir `{os.path.basename(rel)}`")
                if pjd.get("name") != name:
                    err(f"{pj}: name `{pjd.get('name')}` != marketplace entry `{name}`")
                if not pjd.get("version"):
                    warn(f"{pj}: no version field")
                # Marketplace <-> plugin.json version drift guard. The marketplace
                # entry is what consumers read, so it must not lag plugin.json.
                mv = mkt_versions.get(name)
                if not mv:
                    warn(f"marketplace.json entry `{name}`: no version field")
                elif pjd.get("version") and mv != pjd["version"]:
                    err(f"marketplace.json `{name}` version ({mv}) != "
                        f"{rel}/.claude-plugin/plugin.json version ({pjd['version']})")
        # skill presence: flat SKILL.md or nested skills/*/SKILL.md
        flat = os.path.join(pdir, "SKILL.md")
        skills_dir = os.path.join(pdir, "skills")
        if os.path.isfile(flat):
            check_skill(flat)
        elif os.path.isdir(skills_dir):
            subs = [d for d in os.listdir(skills_dir)
                    if os.path.isdir(os.path.join(skills_dir, d))]
            if not subs:
                err(f"{rel}/skills/ has no skill subdirectories")
            for d in subs:
                sm = os.path.join(skills_dir, d, "SKILL.md")
                if not os.path.isfile(sm):
                    err(f"{rel}/skills/{d}/ missing SKILL.md")
                else:
                    check_skill(sm)
        else:
            err(f"{rel}: no SKILL.md and no skills/ directory")

    # VERSION drift guard
    vpath = os.path.join(ROOT, "VERSION")
    if os.path.isfile(vpath):
        with open(vpath, encoding="utf-8") as f:
            version = f.read().strip()
        if not version:
            err("VERSION file is empty")
        elif len(registered) == 1:
            only = next(iter(registered.values()))
            pjd = load_json(os.path.join(ROOT, only, ".claude-plugin", "plugin.json"))
            if pjd and pjd.get("version") and pjd["version"] != version:
                err(f"VERSION ({version}) != single plugin version ({pjd['version']})")
    return finish()


NAME_MAX = 64
NAME_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def check_skill(skill_md):
    n = frontmatter_name(skill_md)
    if n is not None:
        # An over-long name is invisible to every other gate here: the skill is still
        # on disk, still matches its directory, still has one README row, still routes.
        # Nothing noticed for five of them between v1.7.0 and v1.24.0.
        if len(n) > NAME_MAX:
            err(f"{skill_md}: frontmatter name `{n}` exceeds {NAME_MAX} characters ({len(n)})")
        if not NAME_RE.fullmatch(n):
            err(f"{skill_md}: frontmatter name `{n}` must use lowercase letters, "
                "digits, and single hyphens only")
        dirname = os.path.basename(os.path.dirname(skill_md))
        if n != dirname:
            err(f"{skill_md}: frontmatter name `{n}` != dir `{dirname}`")


def finish():
    for w in warnings:
        print(f"::warning::{w}")
    if errors:
        for e in errors:
            print(f"::error::{e}")
        print(f"\nFAILED: {len(errors)} error(s), {len(warnings)} warning(s)")
        return 1
    print(f"OK: marketplace + plugins valid ({len(warnings)} warning(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
