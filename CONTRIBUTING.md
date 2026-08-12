# Contributing — publishing hygiene

These skills are often distilled from real client engagements. Before anything is pushed, a
**leak gate** checks for client / PII identifiers so engagement-specific details never ship to
this public repo. A second gate keeps every SKILL.md description inside the cap Claude Code
applies to the skill listing.

## What runs automatically

**CI** (`.github/workflows/ci.yml`) runs these checks on every PR and push, in this order:

1. `.github/scripts/validate_plugins.py` — marketplace / plugin / SKILL.md structure, plus the
   **hook/CI parity check** described under *One-time local setup* below.
2. `scripts/check_skill_descriptions.py` — the **skill-description cap gate**.
3. `scripts/leak_scan.sh` — the **leak gate**. It enforces low-false-positive generic
   patterns: Salesforce custom fields (`__c` / `__r`), API keys / tokens, and real email
   addresses — plus the **tracked** industry-vocabulary denylist in `.leakdomains`. A hit
   fails the check, and so does a missing `.leakdomains`. See *The two term files* below.
4. `scripts/check_skill_routes.py` — the **route gate**: can the model get to a skill at all?
   It also asserts that every **"N skills" claim above `## Version history`** in the README
   equals the number of skill directories, and that **no markdown file cites a backticked
   skill name that resolves to nothing**.
5. `scripts/check_skill_tiers.py` — the **tier gate**: does the listing still fit, by policy?
6. `scripts/check_release_parity.py` — a version claimed in `VERSION` or the changelog with no
   GitHub Release. Accepted holes live in `.release-parity-accepted`.
7. A two-line assertion that `--json` reports `within_budget: true`.
8. `plugins/agent-traffic-control/hooks/resume-gate/tests` — the hook's pytest suite.
9. `…/tests/mutation_check.py` — the **mutation check**: it breaks each of that hook's guards
   in turn and fails if the suite does not notice.

**No total is written here on purpose.** A hand-maintained count is right on the day it is
typed and quietly wrong afterwards — this line said "six" for three releases while CI ran
nine, and the README's front page said 98 skills against a tree of 99 for four. Read the list.

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

Four things fail it: an unreachable reference-only skill; a `../<name>/SKILL.md` link that
does not resolve (a skill from *another* plugin is not at that path — name it in backticks,
see v1.11.1); a skill with no README index row, or more than one; and a README front-page
skill count that disagrees with the tree.

**The count check is scoped to the header, above `## Version history`.** Changelog entries
state what was true at the time and must keep their historical figures — there are 45 matches
below that heading and a gate firing on those would be muted within a week. If the heading
cannot be found the check *fails* rather than scanning the whole file.

Two things it refuses to do quietly. **Zero claims found is a failure, not a pass** — either
the front page stopped stating a count or the check stopped finding it, and both need a human.
And it **self-tests the pattern on every run**, because the claim it most needs to catch is the
opening sentence, where a markdown link sits between the number and the noun:

```
A coordination toolkit of 99 [Claude Code](https://claude.com/claude-code) skills
```

A bare `\d+\s+skills` regex does not match that. Measured: the naive form finds 2 of the 3
header claims and the one it drops is line 3 — so a gate built on it would have reported OK
through the whole window in which the front page was wrong.

### Citing a skill that is not in this repo

Check 1 asks whether a reference-only skill is reachable **from** a live skill. The citation
check asks the opposite question — whether a name a skill points **at** exists at all — and
nothing had ever asked it. Measured for #39: **51 names across 77 sites in 41 files**, most of
them in "Sister skill:" and "See also:" lines, which is exactly where a reader goes when the
current skill did not answer their question.

The link check could not catch them either: every one is a **bare backticked name**, not a
`[...](../name/SKILL.md)` link, so a link-shaped gate fires on none of them and could never see
one in frontmatter.

**If you cite a name that is not a skill directory here, add it to `.skill-citations-accepted`
in the same commit**, one `name  # reason` per line. That file is the map: a name in a skill
body that you cannot find is in there, with its status and where to get it if anywhere. Do not
add a name just to turn the gate green — a confident wrong note is worse than an admitted gap,
because the note is what the next person trusts instead of re-checking.

Unlike `.hook-parity-accepted`, this one **fails closed on absence**: a missing, empty or
comments-only file is a failure, not a stricter policy, because its entries are the deliberate
historical citations the README must keep and losing them would produce a wall of false
failures — the fastest way to get a check muted.

Two mechanics worth knowing before editing the sweep:

- **It is fence-aware, and the naive version is wrong in a way that looks right.** A plain
  `` `([^`]+)` `` regex pairs backticks *across* ``` fence boundaries: an odd number of
  backticks inside a fence flips the parity for every line after it. That version found the one
  known dangling name in **2 of its 7** files and printed a clean-looking result for the rest.
- **It walks for markdown rather than listing files.** An enumerated list was one file short on
  the day it was written — the hook ships its own `README.md` and `DESIGN.md` inside the plugin,
  read by the same audience and able to carry the same dead pointer.

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
[wan-huiyan/context-police](https://github.com/wan-huiyan/context-police); fix it there and
re-vendor rather than forking it here.

**Read the version out of the file, not out of this page.** The file's own header states it:
upstream commit `c413fd4`, upstream version 2.3.0 (a plugin/marketplace version, not a git
tag — upstream's newest tag is v2.0.0), re-vendored 2026-08-05. This paragraph said "currently
v2.2.1" until v1.19.1, which was two re-vendorings stale: v2.3.0 changed what the gate scores
(wrap corruption over every skill, disabled included) and added a NO HEADROOM tier, so the
stale number was not a cosmetic slip.

> **The digest in that header is currently UNVERIFIABLE, and that is a gap rather than a
> finding.** The header says the file is byte-identical to upstream apart from the note
> between its `--8<--` markers, "so a parity test can strip it and hash the rest", and pins
> `sha256 f72dcfa…`. **There is no such parity test in this repo**, and the stripping
> convention is not written down — whether the docstring's own opening line, the marker lines
> themselves, or the surrounding blank lines are included changes the hash. Stripping the
> marker block and hashing the remainder gives `5a592be…`, which is evidence about a guessed
> convention and **not** evidence that the file is a stale fork. Do not cite it as either.
> What is owed is the parity test, written against upstream so the convention is defined by
> something executable. Note also the header's own warning: a feature-presence grep is not a
> substitute — a test asserting `find_wrap_corruption` and `compare_descriptions` were present
> stayed green on a copy that genuinely was a stale fork, because the drift was inside a
> function whose name never changed.

The same script also fails on **line-wrap corruption**: `description: >` and `description: |`
join their lines, so a line that ends in a hyphen silently becomes `token- efficient` in the
text the harness injects. The usual cause is re-wrapping with `textwrap.wrap()`, which breaks
on hyphens by default — pass `break_on_hyphens=False`. The character count is unchanged, so no
length check can see it.

> **The exit code only covers MODEL-INVOCABLE skills — and 77 of this repo's 98 are not.**
> (That is the gate's own header line, `98 SKILL.md (21 model-invocable, 77 disabled)`. Re-read
> it from a run rather than from here — it moves with every skill added, and it moved three
> times in four days: 21/77, then 20/78 when v1.18.0 demoted `using-git-worktrees`, then back
> to 21/77 when v1.20.0 promoted `git-diff-2dot-vs-3dot-merge-safety`.)
>
> **A live consequence, found the hard way:** a disabled skill is invisible to this gate, so
> its description is never checked. `subagent-pre-existing-misattribution` currently sits at
> **1,548 chars against the 1,536 cap** and CI reports `over: False`, because the gate builds
> its lists as `live = [s for s in skills if not s.disabled]`. Harmless while disabled — and it
> truncates mid-word the moment anyone promotes it. Disabling a skill disables the checks on it.
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

## Releasing: move all three manifests in one commit

`VERSION`, `.claude-plugin/marketplace.json` and
`plugins/agent-traffic-control/.claude-plugin/plugin.json` all carry the version number, and
**they must move together in the same commit.** `validate_plugins.py` cross-checks the
marketplace entry against `plugin.json` precisely because that drift has reddened `main`
before: v1.5.0 shipped with a stale marketplace entry, and the same drift recurred on the
v1.8.1 branch until review caught it.

Two ways this goes wrong, both seen:

- **Bumping two of the three.** A version number is copied into three files; there is no
  single source. Grep the old number across the tree before you commit and expect zero hits.
- **Truncating a manifest while editing it.** `open(p, 'w').write(open(p).read().replace(…))`
  evaluates the outer `open(p, 'w')` first, which truncates the file, so the inner read
  returns `''` and you write an empty manifest. That happened during v1.19.0 and left both
  JSON files at zero bytes; `validate_plugins.py` caught it with
  `invalid JSON … Expecting value: line 1 column 1`. Read the file fully, close it, then
  write.

## One-time local setup (recommended)

Enable the committed pre-push hook so the gates run **before** anything leaves your machine.
It runs the same checks as CI, in CI's order — a hook that runs fewer gates than CI is a hook
that tells you a push is clean when it is not.

**That claim has been false twice, and both times the sentence was the last thing anyone
checked.** In v1.19.1 the hook ran five of six (no `within_budget` assertion) and ran the leak
gate last where CI runs it third. By v1.26.3 it was three gates behind — release parity, the
resume-gate suite and the mutation check, all added between v1.22.0 and v1.23.0 and never added
here — having drifted across three releases while both files asserted parity in prose.

**Parity is now checked** by `check_hook_parity()` in `validate_plugins.py`, which is CI's
first step and the hook's first line, so it runs before everything it guards. It compares the
gates `ci.yml` invokes against the gates the hook invokes and fails on anything CI runs that
the hook does not, in the wrong order or not at all. If an omission is deliberate, record it
with its reason in **`.hook-parity-accepted`** — one `key  # reason` per line, same format as
`.release-parity-accepted`. An absent file accepts nothing, so deleting it makes the check
stricter rather than quieter.

Three mechanics worth knowing before you edit either file:

- **It reads code, not comments.** Both files document the gates they run, and a comment-blind
  scan would read each file's own banner as invocations and report perfect parity between two
  pieces of prose.
- **It self-tests on every run.** The zero-parse guards catch a parser that reads *nothing*;
  they cannot catch one that reads something and mis-keys it. So each run first asserts the
  parser still detects a planted omission in a synthetic pair — the only part of this that
  demonstrates the check is capable of failing.
- **Two gates need `pytest`, and one of them lies without it.** `mutation_check.py` scores a
  mutant KILLED on a non-zero pytest exit, and a missing pytest module also exits non-zero, so
  under a pytest-less interpreter it used to print *"41 mutations, 41 killed, 0 needing
  attention"* and exit 0 having run nothing. It now refuses instead. The hook resolves an
  interpreter that has pytest — or provisions one with `uv run --with pytest` — and says
  loudly when it can do neither, rather than skipping in silence.

```bash
git config core.hooksPath .githooks
cp .leakterms.example .leakterms      # then add YOUR real client / brand / project names
```

To run the two pytest gates by hand without installing anything permanently:

```bash
uv run --python 3.11 --with pytest python -m pytest \
    plugins/agent-traffic-control/hooks/resume-gate/tests -q
uv run --python 3.11 --with pytest python \
    plugins/agent-traffic-control/hooks/resume-gate/tests/mutation_check.py
```

### The two term files, and why one is committed and the other must not be

| | `.leakterms` | `.leakdomains` |
|---|---|---|
| tracked? | **no** — gitignored | **yes** — committed |
| holds | *your* client brands, dataset / project ids, your username | industry vocabulary, spanning many sectors |
| CI sees it? | **no** | **yes** |
| missing file | silently skipped | **hard failure** |

`.leakterms` is gitignored — it holds the names only you know are sensitive, one `grep -E` regex
per line. **Never commit it.** The cost of that is real and was measured: because CI has no copy,
the gate there degrades to the three generic patterns and prints `LEAK GATE: clean`. It printed
exactly that before *and* after v1.24.0 removed 129 occurrences of engagement residue, and was
right both times — it was answering a narrower question than the one being asked of it.

`.leakdomains` exists to close that half. It is **committed on purpose**, so CI reads it too, and
the gate **fails if the file is absent** — "the denylist wasn't there" must never read as "clean"
a second time. It lives inside `leak_scan.sh` rather than as a new CI step, so it needs no
matching edit in `.githooks/pre-push` and cannot drift out of parity at all. That reasoning is
why the parity check above lives inside `validate_plugins.py` too: a gate of its own would have
been one more thing to keep in the hook, which is the drift it exists to catch.

**It spans education, health, finance, legal, HR, retail and cross-sector privacy statutes, and
you must not trim it to the sectors you happen to work in.** A denylist naming one sector *is*
the disclosure: committing that sector's nouns and nothing else to a public repo reassembles, in
one searchable file, the set a scrub just removed — and points at the engagement more precisely
than the prose did. A list spanning six sectors points at none of them, and the next engagement will be in some
other sector anyway.

**Both files together are the *necessary* half, not the sufficient one.** They are known-term
greps. They cannot catch an open-vocabulary coined name — a dashboard nav label, a git worktree
name, a campaign token in a filename — and that class produced most of what v1.24.0 removed. A
first public publish still deserves a human / LLM semantic read.

## If the leak gate fires

Sanitize the flagged content (replace the identifier with a neutral placeholder), or — for a
genuine false positive — narrow the pattern or add an exclusion in `scripts/leak_scan.sh`.

If it fires on **industry vocabulary**, the fix is almost never to delete the term from
`.leakdomains`. Rewrite the worked example so it is about the coordination failure rather than the
sector it was learned in. A term that genuinely cannot stay zero-hit — because it collides with
this repo's own engineering vocabulary — does not belong in `.leakdomains` at all; six such terms
are listed with their reasons in the file itself.

## If the description gate fires

**OVER CAP** — trim the flagged description down to size. Do **not** raise `--max-chars`: the
cap is read out of the Claude Code binary, so overriding it only hides the truncation, it does
not prevent it.

**BROKEN BY LINE-WRAP** — repair the split token and re-wrap the block without breaking on
hyphens. Do not "fix" it by shortening the line; the corruption is the hyphen at the line end,
not the length.
