# Contributing — publishing hygiene

These skills are often distilled from real client engagements. Before anything is pushed, a
**leak gate** checks for client / PII identifiers so engagement-specific details never ship to
this public repo. A second gate keeps every SKILL.md description inside the cap Claude Code
applies to the skill listing.

## What runs automatically

**CI** (`.github/workflows/ci.yml`) runs four checks on every PR and push:

1. `.github/scripts/validate_plugins.py` — marketplace / plugin / SKILL.md structure.
2. `scripts/check_skill_descriptions.py` — the **skill-description cap gate**.
3. `scripts/leak_scan.sh` — the **leak gate**. It enforces low-false-positive generic
   patterns: Salesforce custom fields (`__c` / `__r`), API keys / tokens, and real email
   addresses. A hit fails the check.
4. `scripts/check_skill_routes.py` — the **route gate**: can the model get to a skill at all?

### The route gate

Most of this repo is reference-only (`disable-model-invocation: true`). Those skills never
enter the listing and the Skill tool refuses them outright, so there are exactly two ways in:
the user types the name, or a skill the model **has** retrieved names it in its body and the
model opens the file. A reference-only skill that no *live* skill names is unreachable — on
disk, in the README, and never opened.

Measured on 2026-08-07, before this gate existed: **57 of 77 reference-only skills were named
by no live skill**, so the real retrieval surface was 41 of 98 rather than 98 of 98.

```bash
python3 scripts/check_skill_routes.py .            # exit 0 = every skill reachable
python3 scripts/check_skill_routes.py . --list     # per-skill live-inbound counts
```

Three things fail it: an unreachable reference-only skill; a `../<name>/SKILL.md` link that
does not resolve (a skill from *another* plugin is not at that path — name it in backticks,
see v1.11.1); and a skill with no README index row, or more than one.

**Links from a disabled skill do not count.** The model only reads a disabled skill's body
after it has already been sent there, so a chain that starts inside the dark half never starts.
Matching is word-boundary: a mention of `using-git-worktrees` is not an inbound link to
`git-worktree`. Substring matching inflates that one from 1 live inbound to 4 and hides a real
orphan.

Body text costs nothing in the skill listing, so satisfying this is free.

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
[wan-huiyan/context-police](https://github.com/wan-huiyan/context-police) (currently v2.2.1 —
a plugin version, not a git tag); fix it there and re-vendor rather than forking it here.

The same script also fails on **line-wrap corruption**: `description: >` and `description: |`
join their lines, so a line that ends in a hyphen silently becomes `token- efficient` in the
text the harness injects. The usual cause is re-wrapping with `textwrap.wrap()`, which breaks
on hyphens by default — pass `break_on_hyphens=False`. The character count is unchanged, so no
length check can see it.

> **The exit code only covers MODEL-INVOCABLE skills — and 77 of this repo's 98 are not.**
> (That is the gate's own header line, `98 SKILL.md (21 model-invocable, 77 disabled)`. Re-read
> it from a run rather than from here — it moves with every skill added.)
> The text report's exit code is `1 if (over or corrupt) else 0`, where both lists are built
> from `live = [s for s in skills if not s.disabled]`. A hyphen break inside a
> `model-invocation: false` skill is **printed by neither and fails nothing**. Verified by
> injecting one into a disabled skill: text report exit 0 and no `BROKEN BY LINE-WRAP` line,
> while `--json` exits 1 and names it. That is exactly why the four real corruptions fixed in
> v1.8.1 had to be found through `--json` rather than CI — all four were in manual-only skills.
> **So run the `--json` form too** whenever you touch a description, disabled or not:
>
> ```bash
> python3 scripts/check_skill_descriptions.py . --json > /dev/null; echo "exit=$?"
> ```

### Before/after a trim, run both checks — they see different things

```bash
# 1. Trigger-surface diff: what a reviewer must read. Exit 1 on DROPPED or NARROWED.
python3 scripts/check_skill_descriptions.py --no-color \
    --compare main:plugins/agent-traffic-control/skills/<skill>/SKILL.md \
              plugins/agent-traffic-control/skills/<skill>/SKILL.md

# 2. Coverage against a committed eval suite of natural-language prompts.
python3 scripts/score_trigger_coverage.py \
    --old  main:plugins/agent-traffic-control/skills/<skill>/SKILL.md \
    --new  plugins/agent-traffic-control/skills/<skill>/SKILL.md \
    --eval scripts/eval/<skill>.eval-suite.json
```

`--compare` catches what coverage scoring structurally cannot: **NARROWED**, where a
precondition is added to a trigger so it fires for fewer users. The word set is identical, so
every bag-of-words metric scores it the same. Read the `NARROWED` and `REWORDED` rows yourself;
do not clear them with a number.

`score_trigger_coverage.py` baselines against `old_description[:1535]` — what the model
actually saw — not the full oversized source. **If a PR quotes coverage figures, the eval suite
must be committed under `scripts/eval/`.** An unreproducible table is worse than no table.

### Getting under the cap is necessary, not sufficient

A second limit, `skillListingBudgetFraction` (1% of the context window), sizes the whole
listing. When the total is over budget the harness collapses descriptions to bare names, ranked
by usage rather than by length — so a description can be fully under the cap and still reach
the model as a name only. `check_skill_descriptions.py` prints the budget line for a given
`--context`. Claim "no longer truncated"; never claim "guaranteed visible".

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

**OVER CAP** — trim the flagged description down to size. Do **not** raise `--max-chars`: the
cap is read out of the Claude Code binary, so overriding it only hides the truncation, it does
not prevent it.

**BROKEN BY LINE-WRAP** — repair the split token and re-wrap the block without breaking on
hyphens. Do not "fix" it by shortening the line; the corruption is the hyphen at the line end,
not the length.
