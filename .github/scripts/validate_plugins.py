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
  9. HOOK/CI PARITY: every gate `.github/workflows/ci.yml` invokes is also invoked by
     `.githooks/pre-push`, in the same relative order, unless it is listed with a
     reason in `.hook-parity-accepted`.
     WHY THIS LIVES HERE and not in a step of its own: a tenth CI step would be a
     tenth thing to keep in the hook -- one more parity obligation of the kind it
     exists to police. This file is CI's FIRST step and is already invoked by the
     hook, so the check rides along with no new coupling. Same reasoning that put
     the `.leakdomains` scan inside `leak_scan.sh` rather than beside it.
     WHY IT IS NEEDED: hand-maintained parity has now failed twice. v1.19.1 found
     the hook running five of six gates; v1.27.0 found it three behind, having
     drifted across three releases while the file's own header asserted parity.
     Both times the assertion was the last thing anyone checked, which is why the
     hook now states no total at all.

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

    check_hook_parity(ROOT)
    return finish()


# --------------------------------------------------------------------------- #
# Check 9: hook / CI parity.
# --------------------------------------------------------------------------- #
CI_REL = os.path.join(".github", "workflows", "ci.yml")
HOOK_REL = os.path.join(".githooks", "pre-push")
PARITY_ACCEPT_REL = ".hook-parity-accepted"

_STEP_RE = re.compile(r"^\s*-\s+name:\s*(.+?)\s*$")
_RUN_BLOCK_RE = re.compile(r"^(\s*)run:\s*[|>][-+]?\s*$")
_RUN_INLINE_RE = re.compile(r"^(\s*)run:\s*(\S.*?)\s*$")
_VAR_ASSIGN_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$")
_VAR_REF_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)")


def strip_shell_comment(line):
    """Drop a trailing `#` comment, ignoring a `#` inside quotes.

    Required, not cosmetic. Both files DOCUMENT the gates they run: the hook's
    header names validate_plugins.py and mutation_check.py in prose, and ci.yml's
    comments name the release-parity gate. A comment-blind scan reads a file's own
    documentation as invocations and reports perfect parity between two banners.
    """
    out, quote = [], None
    for ch in line:
        if quote:
            out.append(ch)
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
            out.append(ch)
        elif ch == "#":
            break
        else:
            out.append(ch)
    return "".join(out).rstrip()


def _expand(s, varmap):
    """Expand $VAR / ${VAR} and reduce the result to a repo-relative path.

    A value that is a command substitution resolves to "" -- which is exactly
    right for ROOT="$(git rev-parse --show-toplevel)", since every key here is
    repo-relative.
    """
    for _ in range(5):
        new = _VAR_REF_RE.sub(lambda m: varmap.get(m.group(1) or m.group(2), ""), s)
        if new == s:
            break
        s = new
    while "//" in s:
        s = s.replace("//", "/")
    return s.lstrip("/")


def _keys_from_command(cmd, varmap):
    """Gate keys invoked by one command line, in order.

    A key is either a repo-relative path to a .py/.sh script, or a `-m <module>`
    invocation plus its first path-like argument.

    KNOWN EDGE, stated rather than papered over: an inline `python -c "..."` has no
    name to key on, so those are COUNTED rather than identified. CI's inline count
    must be <= the hook's. Two different inline gates in CI against one in the hook
    would be caught; swapping one inline gate for a different one would not.
    """
    keys, inline = [], 0
    toks = [t for t in cmd.split() if t]
    i = 0
    while i < len(toks):
        t = toks[i].strip("'\"")
        if t == "-c":
            inline += 1
            i += 1
            continue
        if t == "-m" and i + 1 < len(toks):
            mod = toks[i + 1].strip("'\"")
            target = ""
            for nxt in toks[i + 2:]:
                cand = _expand(nxt.strip("'\""), varmap)
                if cand.startswith("-"):
                    continue
                if "/" in cand:
                    target = cand
                    break
            keys.append(f"-m {mod} {target}".strip())
            i += 2
            continue
        p = _expand(t, varmap)
        if p.endswith(".py") or p.endswith(".sh"):
            keys.append(p)
        i += 1
    return keys, inline


def ci_gate_keys(text):
    """(step_count, ordered keys, inline count) from ci.yml's `run:` blocks only.

    Only `run:` content is read. ci.yml's comments name gates in prose and would
    otherwise be scanned as invocations.
    """
    steps, keys, inline = 0, [], 0
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        raw = lines[i]
        if _STEP_RE.match(raw):
            steps += 1
        m = _RUN_BLOCK_RE.match(raw)
        if m:
            indent = len(m.group(1))
            i += 1
            while i < len(lines):
                ln = lines[i]
                if ln.strip() and (len(ln) - len(ln.lstrip())) <= indent:
                    break
                cmd = strip_shell_comment(ln)
                if cmd.strip():
                    k, c = _keys_from_command(cmd, {})
                    keys.extend(k)
                    inline += c
                i += 1
            continue
        m = _RUN_INLINE_RE.match(raw)
        if m and not m.group(2).startswith(("|", ">")):
            cmd = strip_shell_comment(m.group(2))
            if cmd.strip():
                k, c = _keys_from_command(cmd, {})
                keys.extend(k)
                inline += c
        i += 1
    return steps, keys, inline


def hook_gate_keys(text):
    """(command count, ordered keys, inline count) from the hook's code, not comments."""
    varmap, cmds = {}, []
    for raw in text.split("\n"):
        line = strip_shell_comment(raw)
        if not line.strip():
            continue
        cmds.append(line)
        m = _VAR_ASSIGN_RE.match(line)
        if m:
            val = m.group(2).strip().strip("'\"")
            varmap[m.group(1)] = "" if ("$(" in val or "`" in val) else val
    keys, inline = [], 0
    for line in cmds:
        k, c = _keys_from_command(line, varmap)
        keys.extend(k)
        inline += c
    return len(cmds), keys, inline


def parity_accepted(root):
    """{key: reason} of gates DELIBERATELY not run by the hook.

    An absent file means no omission is accepted, which is the strict reading --
    so unlike `.leakdomains`, deleting this one makes the gate harsher, never
    quieter, and needs no fail-closed check of its own.
    """
    out = {}
    path = os.path.join(root, PARITY_ACCEPT_REL)
    if not os.path.exists(path):
        return out
    try:
        with open(path, encoding="utf-8") as fh:
            content = fh.read()
    except OSError as e:
        err(f"cannot read {PARITY_ACCEPT_REL}: {e}")
        return out
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, reason = line.partition("#")
        key = key.strip()
        if key:
            out[key] = reason.strip() or "(no reason recorded)"
    return out


def first_order(keys):
    seen, out = set(), []
    for k in keys:
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


_CONTROL_CI = """\
jobs:
  validate:
    steps:
      - name: A gate the hook runs
        run: python3 scripts/kept.py .
      - name: A gate the hook does NOT run
        run: bash scripts/dropped.sh .
"""
_CONTROL_HOOK = """\
#!/usr/bin/env bash
# bash scripts/dropped.sh -- named in a COMMENT, which must not count as running it
ROOT="$(git rev-parse --show-toplevel)"
python3 "$ROOT/scripts/kept.py" "$ROOT"
"""


def parity_self_test():
    """Prove the parser can still SEE an omission, on a pair engineered to have one.

    The zero-parse guards below catch a parser that reads nothing. They do not catch
    a parser that reads something and mis-keys it -- a normalisation that maps every
    path to "" would satisfy them and report perfect parity forever. So the gate runs
    a positive control on every invocation: two synthetic files, one omission, one
    decoy in a comment. Costs microseconds; it is the only thing here that
    demonstrates this check is capable of failing at all.
    """
    steps, ci_keys, _ = ci_gate_keys(_CONTROL_CI)
    _, hook_keys, _ = hook_gate_keys(_CONTROL_HOOK)
    missing = [k for k in first_order(ci_keys) if k not in set(hook_keys)]
    if steps != 2 or missing != ["scripts/dropped.sh"] or "scripts/kept.py" not in hook_keys:
        err("hook parity: the SELF-TEST failed — this check can no longer detect an "
            f"omission it is built to detect (steps={steps}, ci={ci_keys}, "
            f"hook={hook_keys}, missing={missing}). Its verdict on the real files "
            "is not trustworthy; fix the parser, do not skip this.")
        return False
    return True


def check_hook_parity(root):
    if not parity_self_test():
        return
    ci_path = os.path.join(root, CI_REL)
    hook_path = os.path.join(root, HOOK_REL)
    if not os.path.isfile(ci_path):
        err(f"{CI_REL} not found — cannot check hook/CI parity")
        return
    if not os.path.isfile(hook_path):
        err(f"{HOOK_REL} not found — cannot check hook/CI parity")
        return
    try:
        ci_text = open(ci_path, encoding="utf-8").read()
        hook_text = open(hook_path, encoding="utf-8").read()
    except OSError as e:
        err(f"cannot read a parity input: {e}")
        return

    ci_steps, ci_keys, ci_inline = ci_gate_keys(ci_text)
    hook_cmds, hook_keys, hook_inline = hook_gate_keys(hook_text)

    # FAIL CLOSED ON A DEAD INPUT. Every one of these is a way for the check not to
    # run while printing nothing -- a reformatted `run:` style, a renamed workflow,
    # a hook rewritten into a function. Lesson from the leak gate: enumerate the ways
    # the CHECK can fail to execute, not just the ways its subject can fail.
    if ci_steps == 0:
        err(f"hook parity: parsed 0 steps from {CI_REL} — the parser is not reading it")
        return
    if not ci_keys:
        err(f"hook parity: parsed 0 gate invocations from {CI_REL}'s run: blocks")
        return
    if hook_cmds == 0:
        err(f"hook parity: parsed 0 commands from {HOOK_REL}")
        return
    if not hook_keys:
        err(f"hook parity: parsed 0 gate invocations from {HOOK_REL}")
        return

    ok = parity_accepted(root)
    ci_ordered = first_order(ci_keys)
    hook_set = set(hook_keys)
    missing = [k for k in ci_ordered if k not in hook_set]
    new = [k for k in missing if k not in ok]

    for k in missing:
        if k in ok:
            print(f"::notice::hook parity: accepted omission `{k}` — {ok[k]}")
    for k in new:
        err(f"{HOOK_REL} does not run `{k}`, which {CI_REL} does. Add it to the hook, "
            f"or add `{k}  # <reason>` to {PARITY_ACCEPT_REL} if the omission is "
            f"deliberate.")
    if ci_inline > hook_inline:
        err(f"{CI_REL} runs {ci_inline} inline `python -c` gate(s) against the hook's "
            f"{hook_inline}. Inline commands have no name to key on, so this count is "
            f"the only check on them.")

    # ORDER. Half of the v1.19.1 defect was position, not presence: the hook ran the
    # leak gate last where CI runs it third, so a push could clear the cheap gates
    # locally in a different sequence from the one that would judge it. Only keys
    # present in BOTH are compared, so an accepted omission cannot break this.
    shared = [k for k in ci_ordered if k in hook_set]
    hook_ordered = [k for k in first_order(hook_keys) if k in set(shared)]
    if shared != hook_ordered:
        err(f"{HOOK_REL} runs the shared gates in a different order from {CI_REL}.\n"
            f"      CI:   {' -> '.join(shared)}\n"
            f"      hook: {' -> '.join(hook_ordered)}")

    if not new and shared == hook_ordered:
        print(f"OK: hook/CI parity — {len(shared)} shared gate(s), "
              f"{len(missing)} accepted omission(s), same order")


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
