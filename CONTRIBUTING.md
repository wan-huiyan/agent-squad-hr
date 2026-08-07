# Contributing — publishing hygiene

These skills are often distilled from real client engagements. Before anything is pushed, a
**leak gate** checks for client / PII identifiers so engagement-specific details never ship to
this public repo. A second gate keeps every SKILL.md description inside the cap Claude Code
applies to the skill listing.

## What runs automatically

**CI** (`.github/workflows/ci.yml`) runs six checks on every PR and push:

1. `.github/scripts/validate_plugins.py` — marketplace / plugin / SKILL.md structure.
2. `scripts/check_skill_descriptions.py` — the **skill-description cap gate**.
3. `scripts/leak_scan.sh` — the **leak gate**. It enforces low-false-positive generic
   patterns: Salesforce custom fields (`__c` / `__r`), API keys / tokens, and real email
   addresses. A hit fails the check.
4. `scripts/check_skill_routes.py` — the **route gate**: can the model get to a skill at all?
5. `scripts/check_skill_tiers.py` — the **tier gate**: does the listing still fit, by policy?
6. A two-line assertion that `--json` reports `within_budget: true`.

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

**Write the positive prompts from the skill's BODY, with the frontmatter unopened.** A prompt
written from the description it will later score measures whether the *words* survived, not
whether the *trigger* did — the suite agrees with the description by construction and cannot
report a loss. The mechanical form of that rule: reject any positive that shares a four-word
run with the current description. It fired on 29 of the **231 positive prompts written for
v1.17.0** — the 11 new suites only, 21 positives each — including four in
`gh-issue-claim-coordination` that were verbatim quoted phrases out of its own description;
all 29 were rephrased.

**The two suites that predate v1.17.0 were never put through that rule, and it shows.**
Re-applying it to the committed files: 0 of the 231 positives in the 11 new suites share a
four-word run with the description they were scored against, against 8 of 25 in
`cross-worktree-spec-handoff-via-checkout-paths` and 3 of 20 in `pre-dispatch-schema-probe`
(renamed `inherited-scope-doc-names-may-not-exist` in v1.18.0). Those two also carry 25/15
and 20/10 positives/negatives rather than 21/10. So read any figure covering "all 13 suites"
as covering two different vintages, and re-run the rule before quoting a number from them.

`scripts/eval/baseline-2026-08-07.json` holds the separation of every description **before**
the v1.18.0 rewrite, with the commit it was measured at. Separation is how much better a
description matches the prompts that should fire it than the prompts a neighbouring skill
should answer. Measure against that file, not against a number quoted in a PR body.

### The tier gate, and the policy for adding a skill

Getting the listing under budget once is easy. Staying there is the hard part, because
the failure is silent: descriptions collapse to bare names, every skill still "works",
and the model just stops being able to see what any of them is for. v1.18.0 landed at
**7,542 chars against an 8,000-char hard ceiling**, and the default profile's target is
**7,780**. So the size of every live description is now policy rather than luck.

**What the 238 chars between 7,542 and the target actually buy: one more name-led skill.**
An entry costs `len(name) + 4 + len(description) + 1`, so a name-led entry at its 160-char
ceiling costs `len(name) + 165` — 177 to 237 across this repo's name lengths (12 to 72
chars), and 238 was chosen to cover the longest of them. A `short` entry costs up to 357
and a `rich` one up to 677 — neither fits, and nor does a second name-led. Adding any of
them means **shortening something else in the same pull request**, which is the decision
this gate exists to force. The 220 chars between the target and 8,000 are a warning band,
not spare capacity: over target is a red build you fix at leisure, over 8,000 is the
harness silently dropping descriptions.

**Every live skill declares `listing_tier: rich | short | name-led`.** The class is
decided by whether the skill has a `skillUsage` record in `~/.claude.json`, because that
is what decides whether its description is certain to be read or merely might be:

| class | ceiling | who | why |
|---|---|---|---|
| `rich` | 600 (`git-worktree` 300) | has a usage record | admitted regardless of size, so the description is what actually drives selection — spend characters here |
| `short` | 280 | zero usage, name does not state the moment | invisible today; length only decides whether it can ever fit leftover slack |
| `name-led` | 160 | zero usage, name already states the moment | one sentence expanding the name |

Headcount caps: **8 rich, 8 short, 10 name-led, 24 live in total.** The gate names the
current holders when one is exceeded, because **promoting a skill means naming the one it
displaces, in the same pull request.**

```bash
python3 scripts/check_skill_tiers.py .                        # the CI invocation
python3 scripts/check_skill_tiers.py . --why                  # the slate: size, live-inbound, usage
python3 scripts/check_skill_tiers.py . --bytes-per-token 3    # the tighter budget
python3 scripts/check_skill_tiers.py . --profile strict       # the 6,000-char target
```

**A new skill starts reference-only** (`disable-model-invocation: true`) **and is named
from the body of the live skill that owns its moment**, so it is reachable from day one
without costing the listing anything. Promote it only when it earns a class, and say what
it displaces.

**The strict profile does not pass today, deliberately.** It models a model given only
6,000 chars of listing (rich ≤430, short ≤200, name-led ≤120; target 5,863). The shipped
slate is 7,542, so `--profile strict` exits 1 and prints the exact gap — 19 descriptions
over their tighter ceiling. It is a target for a future pass, not a claim about today, and
it is a command rather than a memory. CI runs the default profile only.

**One check in that gate is not about size at all.** A SKILL.md whose frontmatter has no
closing `---` on its own line is **dropped from the vendored gate's census without any
error**: breaking one file on purpose took the header from
`98 SKILL.md (20 model-invocable)` to `97 SKILL.md (19 model-invocable)` and still exited
0. So the tier gate fails on an unparseable frontmatter, first, before any count that
would be computed over the wrong set. This was found by writing a script that reassembled
files from `'---\n' + fm + '\n---' + text[len(fm)+8:]` and glued the delimiter onto the
body's first line in all 20 — **do not reassemble a file you only need to insert a line
into.**

### Getting under the cap is necessary, not sufficient

A second limit, `skillListingBudgetFraction` (1% of the context window), sizes the whole
listing. When the total is over budget the harness collapses descriptions to bare names, ranked
by usage rather than by length — so a description can be fully under the cap and still reach
the model as a name only. `check_skill_descriptions.py` prints the budget line for a given
`--context`. Claim "no longer truncated"; never claim "guaranteed visible".

**And that budget is GLOBAL, which is why no number this repo can measure will ever settle
the question.** Every model-invocable skill from every installed plugin competes for the same
8,000 chars — on the machine this work was done on, 105 skills wanting ≥91,094 chars, more
than ten times the budget. Admission is ranked by `usageCount × max(0.5^(days/7), 0.1)` out of
`~/.claude.json → skillUsage`, and a skill nobody has ever invoked scores **0**. So
`check_skill_descriptions.py`'s "fits, N chars to spare" is a statement about THIS REPO'S
share, not about visibility: getting the repo's own total down stops it crowding out other
plugins, and that is the whole of what it does. Never write "it fits, so the descriptions are
visible" — write what was actually achieved (nothing truncated, the repo no longer dominates
a shared budget) and what still depends on the machine (whether any one description survives).

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
