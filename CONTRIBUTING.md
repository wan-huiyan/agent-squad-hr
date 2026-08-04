# Contributing — publishing hygiene

These skills are often distilled from real client engagements. Before anything is pushed, a
**leak gate** checks for client / PII identifiers so engagement-specific details never ship to
this public repo. A second gate keeps every SKILL.md description inside the cap Claude Code
applies to the skill listing.

## What runs automatically

**CI** (`.github/workflows/ci.yml`) runs three checks on every PR and push:

1. `.github/scripts/validate_plugins.py` — marketplace / plugin / SKILL.md structure.
2. `scripts/check_skill_descriptions.py` — the **skill-description cap gate**.
3. `scripts/leak_scan.sh` — the **leak gate**. It enforces low-false-positive generic
   patterns: Salesforce custom fields (`__c` / `__r`), API keys / tokens, and real email
   addresses. A hit fails the check.

### The skill-description cap gate

Claude Code injects every model-invocable skill's `name` + `description` into context on
**every turn**. Each entry is capped at `skillListingMaxDescChars` (1536). Over the cap the
harness keeps `description[:1535]` and appends an ellipsis — it cuts **mid-word**, with no
warning anywhere. A description is trigger text, so every `use when the user says "..."`
phrase past char 1535 is already dead: the skill cannot fire on it.

```bash
python3 scripts/check_skill_descriptions.py . --no-color --triggers   # exit 0 = clean
```

`--triggers` lists the quoted trigger phrases that fall past the cut. When trimming, compress
synonym runs and cut prose/implementation detail — never delete a distinct concept, and keep
any "NOT for ..." negative list, which is what stops false firing. Land ~30–50 chars under the
cap so the next edit does not re-break it. The script is vendored from
[wan-huiyan/context-police](https://github.com/wan-huiyan/context-police); fix it there and
re-vendor rather than forking it here.

## One-time local setup (recommended)

Enable the committed pre-push hook so both gates run **before** anything leaves your machine:

```bash
git config core.hooksPath .githooks
cp .leakterms.example .leakterms      # then add YOUR real client / brand / project names
```

`.leakterms` is gitignored — it holds the names only you know are sensitive (client brands,
dataset / project ids, your username), one `grep -E` regex per line. **Never commit it.** The
generic CI patterns plus your local `.leakterms` together catch the *enumerable* leaks; a first
public publish still deserves a human / LLM semantic read for client-shaped names a fixed
pattern can't enumerate.

## If the leak gate fires

Sanitize the flagged content (replace the identifier with a neutral placeholder), or — for a
genuine false positive — narrow the pattern or add an exclusion in `scripts/leak_scan.sh`.

## If the description gate fires

Trim the flagged description down to size. Do **not** raise `--max-chars`: the cap is read out
of the Claude Code binary, so overriding it only hides the truncation, it does not prevent it.
