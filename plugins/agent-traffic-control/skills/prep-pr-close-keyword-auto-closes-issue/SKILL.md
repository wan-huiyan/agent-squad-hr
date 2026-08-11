---
name: prep-pr-close-keyword-auto-closes-issue
description: |
  Diagnose and prevent the trap where a scaffolding/prep/planning/handoff PR
  (one that ships a paste-ready prompt, an ADR, an implementation plan, or
  any docs-only artefact describing FUTURE work) contains a close-keyword
  like `closes #N` / `fixes #N` / `resolves #N` in its TITLE or BODY, which
  GitHub auto-applies at merge time — closing issue #N BEFORE the actual
  implementation work has been done. Use when: (1) `gh issue view <N>` reports
  the issue CLOSED but you know the work hasn't run, (2) you're about to open
  a PR shipping a "next-session prompt" / "implementation plan" / "ADR
  proposal" / "scaffolding" and the title or body references an issue,
  (3) `gh api repos/<O>/<R>/issues/<N>/timeline` shows the closing commit is
  a docs-only PR (only `docs/handoffs/`, `docs/plans/`, `docs/decisions/`,
  or `docs/specs/` paths changed), (4) a fresh session is asked to execute
  an issue that already shows as CLOSED. Different from
  `gh-squash-merge-closes-only-one-issue` (THERE: one of many issues closed
  on merge; HERE: an issue closed correctly per its keyword but at the wrong
  TIME — during prep, not during implementation). Includes a paste-ready
  diagnostic snippet, a reopen-comment template, an audit recipe for scanning
  closed issues for false-positives across a repo, and a prevention
  convention (use bare `#N` references in non-implementation PRs). v1.2.0 adds
  the NEGATED-KEYWORD variant: writing `Does not close #N` / `not resolving #N`
  / `partial — closes #N later` in a commit or PR body STILL auto-closes #N
  (GitHub's parser ignores the negation), and this fires for CODE PRs too (not
  just docs/prep) — and squash-merge reads the COMMIT body, which can differ
  from the PR description. Use when an issue closed despite a "does not close"
  hedge, or a partial-implementation PR closed a multi-part issue.
author: Claude Code
version: 1.2.0
date: 2026-05-29
disable-model-invocation: true
---

# Prep PR close-keyword auto-closes issue prematurely

## Problem

You wrote a docs-only PR shipping a paste-ready prompt / implementation plan /
ADR proposal / scaffolding for future work on issue #N. The PR title looked
like:

> `docs(s171): next-session prompt — backfill historical sf_converted (closes #672)`

or the PR body opened with:

> Paste-ready S171 prompt for the historical `sf_converted` backfill that
> pre-empts Q3 2026 calibration retrain. Closes-ready for issue #672 (P1).

The PR squash-merged cleanly. Hours or days later, someone (you or the next
session) starts executing the prompt. They run `gh issue view 672` and find:

```json
{"closed":true,"closedAt":"2026-05-11T11:27:12Z","stateReason":"COMPLETED"}
```

But the work hasn't run yet. The issue closed because GitHub's keyword parser
treated `closes #672` in the prompt PR's title/body as a close-keyword and
fired at merge time — even though the merged diff was a docs-only handoff
file, not the implementation.

This silently misrepresents repo state. Stakeholders asking "what's left?"
get a falsely-clean issue list. Future audits ("we shipped #672 — where's
the postmortem?") chase ghosts.

## Context / Trigger Conditions

Use this skill when ANY of these hold:

1. **Discovery (after the fact)**: `gh issue view <N> --json state,closedAt,stateReason`
   shows CLOSED, but you have direct evidence (a worktree branch, a prompt
   doc, a session handoff) that the implementation hasn't run.

2. **Pre-flight check at execution time**: A fresh session is asked to
   execute the work for issue #N, and the issue already shows CLOSED. The
   prompt itself is what closed it.

3. **Pattern-matching the closing PR**: `gh api repos/<O>/<R>/issues/<N>/timeline --jq '.[] | select(.event=="closed") | .commit_id'`
   resolves to a commit whose PR (`gh pr view <M> --json files,title`)
   touches only `docs/handoffs/`, `docs/plans/`, `docs/decisions/`,
   `docs/specs/`, or `docs/proposals/` paths.

4. **Authoring a non-implementation PR**: You're ABOUT to open a PR shipping
   a prompt, plan, ADR, handoff, or scaffolding doc, and the title or body
   currently contains a close-keyword (`closes`, `fixes`, `resolves` +
   tense variants: `closed`, `closing`, `fixed`, `fixing`, `resolved`,
   `resolving`) followed by an issue reference. STOP — this is the trap.

5. **Repo-wide audit**: You suspect the trap has fired across multiple
   issues over time and want a mechanical scan.

Don't use this skill when:

- The closing PR's diff actually implements the issue's acceptance criteria
  (true-positive close — different problem).
- The issue is closed but should be reopened for an unrelated reason (drift
  from spec, regression discovered later) — different cause class.
- Multiple issues referenced in one PR and only some closed — that's
  `gh-squash-merge-closes-only-one-issue`'s domain.

## Solution

### Step 1 — Confirm the trap fired

Run the timeline diagnostic on the suspect issue:

```bash
gh api repos/<OWNER>/<REPO>/issues/<N>/timeline \
  --jq '.[] | select(.event=="closed") | {created_at, commit_id, source: (.source.issue.number // .source.pull_request.number // null)}'
```

If `commit_id` is non-null, find the PR that produced it:

```bash
gh api repos/<OWNER>/<REPO>/commits/<COMMIT_ID>/pulls --jq '.[] | {number, title, mergedAt}'
```

Then inspect that PR's diff:

```bash
gh pr view <M> --json files,title,body --jq '{title, files: [.files[].path]}'
```

**Verdict criteria**:

| Files touched | Title/body has close-keyword? | Verdict |
|---|---|---|
| Only `docs/handoffs/`, `docs/plans/`, `docs/decisions/`, `docs/specs/`, `docs/proposals/` | YES | **Trap fired — false-positive close** |
| Any production code (`*.py`, `*.sqlx`, `*.html`, `*.css`, `*.ts`, `*.go`, etc.) | YES | True-positive — implementation shipped |
| Anything | NO | Issue was closed manually or by another path — different cause |

### Step 2 — Reopen the issue with a transparent comment

```bash
gh issue reopen <N> --comment "Re-opened: PR #<M> (the <prompt|handoff|plan|ADR-proposal> doc) contained \`closes #<N>\` in its <title|body>, which GitHub interpreted as a close-keyword on merge. However, the PR's diff is <scaffolding/prep/plan/handoff doc> only — it does not satisfy this issue's acceptance criteria. The actual implementation work has not yet been done. Will re-close when the implementation PR lands with real verification numbers."
```

### Step 3 — Re-close on real implementation

When the implementation PR ships, write its title/body so GitHub's parser
re-fires correctly:

```
fix(<area>): <what shipped> (closes #N)
```

Include verification numbers / acceptance-criteria checkboxes in the body so
the close trail has provenance.

### Step 4 — Prevention going forward

When authoring a non-implementation PR, **never** use close-keywords for
issues the PR doesn't actually resolve. Use bare `#N` references instead:

| Don't | Do |
|---|---|
| `docs: prompt for backfill (closes #672)` | `docs: prompt for backfill #672` |
| `Closes #672, #673` | `Tracks #672, #673` or `References #672, #673` |
| `Fixes #500 (next-session work)` | `Plans fix for #500` |

The close-keyword should appear ONLY in the PR that contains the
implementing diff. Save it for last.

> **⚠️ Negation does NOT save you.** GitHub's keyword parser is a flat
> substring scan — it is **not** negation- or context-aware. Writing
> `Does not close #N`, `partial — does not resolve #N`, `not closing #N yet`,
> or `closes #N later` in a commit/PR body **still closes #N** on
> default-branch merge, because the parser sees the literal `close #N` and
> ignores every surrounding word. If you must mention the issue in a hedged
> way, use a NON-keyword verb: `Scopes only part of #N`, `Partial for #N`,
> `Defers the rest of #N`. **Never put any close-keyword (`close/closes/closed/
> fix/fixes/fixed/resolve/resolves/resolved`) adjacent to `#N` in prose you
> don't intend to act on — even negated.** (This is also why the audit recipe's
> "negated reference" row in §"Regex false-match patterns" is a false match for
> *your audit* but a TRUE close for *GitHub* — the issue really did close.)

### Step 5 — Audit recipe (repo-wide scan)

To find historical false-positives, run a mechanical scan on merged PRs in
a window:

```bash
mkdir -p /tmp/audit
gh pr list --state merged --limit 500 \
  --search 'merged:>2026-02-15 (closes OR fixes OR resolves)' \
  --json number,title,body,mergedAt,files \
  > /tmp/audit/merged_with_keywords.json

# Extract (pr, issue) pairs via close-keyword regex
jq -r '.[] | "\(.number)\t\(.title)\t\(.body // "")\t\(.mergedAt)"' \
  /tmp/audit/merged_with_keywords.json \
  | python3 -c '
import sys, re
PAT = re.compile(r"\b(close[sd]?|closing|fix(?:e[sd]|ing)?|resolve[sd]?|resolving)\b[\s:]*#(\d+)", re.IGNORECASE)
for line in sys.stdin:
    parts = line.rstrip("\n").split("\t", 3)
    if len(parts) < 4: continue
    pr, title, body, merged = parts
    issues = {int(m.group(2)) for blob in (title, body) for m in PAT.finditer(blob)}
    for iss in sorted(issues):
        print(f"{pr}\t{iss}\t{merged}\t{title[:80]}")
' > /tmp/audit/pr_closes_issue.tsv

# Filter to prep-style PRs (docs-only paths OR prep-keyword title)
jq -r '.[] |
  select(
    (.title | test("(?i)(prompt|handoff|plan|spec|proposal|next-session|prep|scaffolding|kickoff)"))
    or
    ((.files // []) | map(.path) | all(startswith("docs/")))
  )
  | "\(.number)\t\(.title)"
' /tmp/audit/merged_with_keywords.json > /tmp/audit/suspect_prs.tsv

# Cross-reference: PRs that both look prep-style AND closed an issue
join -t$'\t' -1 1 -2 1 \
  <(sort -k1 /tmp/audit/suspect_prs.tsv) \
  <(sort -k1 /tmp/audit/pr_closes_issue.tsv | cut -f1,2)
```

Each row in the join output is a candidate false-positive: investigate per
Step 1's verdict criteria, then reopen per Step 2 if confirmed.

## Verification

After Step 2 reopen:

```bash
gh issue view <N> --json state --jq .state
# Should print: OPEN
```

After Step 3 re-close (real implementation merged):

```bash
gh issue view <N> --json state,closedAt,stateReason --jq .
# Should print: state=CLOSED, closedAt = recent timestamp, stateReason=COMPLETED
# AND the closing PR's diff should touch implementation paths, not just docs
```

After Step 5 audit on a clean repo: zero rows in the join output (or only
rows that pass Step 1's verdict as true-positive closes).

## Example

**Concrete instance (the client, 2026-05-11, S171b)**:

- Issue #672 (P1): "S166 follow-up — backfill historical sf_converted
  partitions for Q3 2026 calibration retrain"
- PR #712 (merged 2026-05-11T11:27:13Z): title
  `docs(s171): next-session prompt — backfill historical sf_converted (closes #672)`
  — diff was only `docs/handoffs/session_171_672_backfill_prompt.md`
  + `docs/generate_roadmap_backlog.py` + regen of `docs/site/*.html`
- Closing keyword fired on merge → #672 CLOSED at 11:27:12Z
- Discovery: S171b session opened, asked to execute the backfill prompt,
  ran `gh issue view 672` and saw CLOSED
- Diagnosis: ~3 min via `gh api timeline` → found PR #712 was the closer →
  inspected its files → all `docs/` → trap confirmed
- Mitigation: reopened #672 with transparent comment; ran the backfill
  (67 partitions, 21,774 rows, 2.77% post-backfill miss rate); merged
  PR #716 with `Closes #672` in body → #672 re-closed at 11:50:17Z with
  the real verification numbers

Cost of trap if not caught: a fresh session months later asking "is the
backfill done?" would see #672 CLOSED and skip it. The Q3 2026 calibration
retrain would run against 96%-wrong labels for partitions written before
2026-05-10.

## Notes

- **Why GitHub does this**: GitHub's auto-close feature is convenient when
  the PR is the implementation. It has no way to distinguish "this PR ships
  the work for #N" from "this PR ships a PLAN for the work for #N." Both
  are valid uses of `#N`; only the former should use a close-keyword.

- **The trap is silent — it doesn't error or warn.** The PR merges, the
  issue closes, and the close trail looks normal in the issue's timeline.
  Only direct knowledge that the work hasn't been done surfaces the bug.

- **Auto-merge label workflows amplify the risk.** If your repo has a
  "merge on green" automation that triggers off label + CI, a prep PR with
  a close-keyword + auto-merge label will close the issue without any
  human reading the title.

- **Half-measures don't work**: lowercase `closes` and uppercase `Closes`
  both fire. So do `Close`, `closed`, `closing`, `closes:`, and embeddings
  in larger phrases like `"closes-ready for #672"`. GitHub's parser is
  surprisingly permissive. The only safe way to mention an issue
  non-closingly is to drop the keyword entirely.

- **CI lint guardrail (recommended for high-traffic repos)**: add a
  workflow that flags PRs where (a) title or body contains a close-keyword
  + `#N` reference AND (b) the diff only touches `docs/` paths. Either
  block the merge or post a comment requiring human review. Sample rule:

  ```yaml
  # .github/workflows/prep-pr-close-keyword-lint.yml
  on: pull_request
  jobs:
    lint:
      runs-on: ubuntu-latest
      steps:
        - uses: actions/checkout@v5
        - run: |
            CLOSING=$(echo "${{ github.event.pull_request.title }} ${{ github.event.pull_request.body }}" \
              | grep -Eio '\b(close[sd]?|closing|fix(e[sd]|ing)?|resolve[sd]?|resolving)\b[ \t:]*#[0-9]+' || true)
            FILES=$(gh pr view ${{ github.event.pull_request.number }} --json files --jq '[.files[].path] | join(" ")')
            DOCS_ONLY=$(echo "$FILES" | tr ' ' '\n' | grep -v '^docs/' | wc -l)
            if [[ -n "$CLOSING" && "$DOCS_ONLY" -eq 0 ]]; then
              echo "::error::PR has close-keyword '$CLOSING' but diff is docs-only — likely the prep-PR trap. Use bare #N reference instead."
              exit 1
            fi
  ```

- **Reciprocal: an implementation PR WITHOUT a close-keyword leaves the
  issue OPEN.** Less harmful (issue triagers can manually close), but
  worth catching too. The same lint can flag the inverse: implementation
  diff (touches non-docs paths) + references `#N` without a close-keyword.

## Empirical finding (v1.1.0 addendum, 2026-05-11 S172b audit)

Running the audit recipe across an 85-day window on the source repo
(449 merged PRs, 122 with close-keywords, 31 unique closed issues
suspect-bucketed) returned **0 false-positives**. Reframed risk profile:

1. **In ~22 of 26 suspect rows the docs PR auto-close was a SECOND
   fire on an issue already closed by an earlier implementation PR
   (no-op).** GitHub registers the new closing-PR ref in
   `closedByPullRequestsReferences`, but the issue's state didn't change.
   So the audit's high false-positive *signal* count overstates the real
   defect count by ~6×.

2. **The trap materially fires only when the prompt/handoff/plan PR
   is the FIRST PR to land in the issue's life cycle.** That was
   exactly the original #672 case. Everywhere else, the implementation
   PR closes the issue first (intentionally), and the handoff doc is
   redundant attribution.

3. **Practical priority adjustment**: the CI lint guardrail in this
   skill is belt-and-suspenders, not load-bearing. The bare-`#N`
   convention in non-implementation PRs is the load-bearing fix. Repos
   without the lint installed are not in active danger; the trap is
   genuinely rare in practice.

## Empirical finding (v1.2.0 addendum, 2026-05-29 — negated-keyword authoring trap)

A **code** PR (not a prep/docs PR) auto-closed an issue the author explicitly
meant to leave open, via a **negated** close-keyword.

- The PR implemented only a *partial* slice of a multi-part drift issue (#190).
  The author deliberately did NOT use a close keyword in the title (`(#190 partial / #193)`)
  and dropped a covered/deferred breakdown comment on the issue, intending it to
  stay open.
- But the squash-merge **commit body** contained the sentence **`Does not close #190.`**
  On default-branch merge, GitHub parsed the literal `close #190`, ignored
  `Does not`, and closed #190 as COMPLETED — orphaning the deferred items inside
  a closed issue.
- Detection: `gh issue view 190 --json closedAt,stateReason` + the timeline
  (`gh api repos/<O>/<R>/issues/190/timeline`) showed the closing `commit_id`
  was the author's own merge commit. Fix: `gh issue reopen 190` with a comment
  explaining the auto-close and listing the still-open work.

**Takeaways added to this skill:**
1. The trap is **not limited to prep/docs PRs** — any PR (including code) whose
   commit/PR body contains a close-keyword adjacent to `#N` will close `#N`.
2. **Negation/hedging does not protect you** — see the ⚠️ callout in Step 4.
   The "Negated reference" row in the false-match table was corrected: it is a
   false match for *your audit* but a *real close* by GitHub.
3. Squash-merge uses the **commit body**, which may differ from the PR
   description — scan the actual merge-commit message, not just the PR UI body,
   when both authoring and auditing.

### Regex false-match patterns to suppress

The keyword regex
`\b(close[sd]?|closing|fix(?:e[sd]|ing)?|resolve[sd]?|resolving)\b[\s:]*#(\d+)`
will also match these *non-auto-close* shapes — filter them out before
escalating to a real auto-close audit:

| Pattern | Example | Why it's not an auto-close |
|---------|---------|-----------------------------|
| List-item count | `Fix #1 (literal-pin tests), …` | "#1" is a list count, not an issue ref. GitHub's parser does link it, but if `#1` is a merged PR (not an issue), no auto-close occurs. |
| Past-tense narrative in body | `Closed #115 (stale memory hygiene)` | GitHub's `closedByPullRequestsReferences` empirically returns empty for past-tense `Closed` in body context (no `: #N` immediately after a keyword in the title). Manual closure was the real path. |
| Quoted/code-fenced reference | `` `closes #123` `` inside a code-fence | GitHub does **not** parse keywords inside code fences. |
| Negated reference | `does NOT close #N — out of scope` | **FALSE-MATCH FOR YOUR AUDIT, BUT A REAL AUTO-CLOSE BY GITHUB.** The author didn't *intend* to close (so it's noise when auditing intent), but GitHub's parser ignores the negation and **closes #N anyway**. So when *authoring*, treat this as dangerous (see v1.2.0 addendum); when *auditing others'*, flag it as a likely-unintended close that still fired. |

### Verification gate for the audit recipe

When the recipe surfaces a "suspect" (PR, issue) pair, run this gate
before reopening:

```bash
# Is there ANY merged non-docs PR that mentions the issue?
gh pr list --repo "$REPO" --state merged --limit 30 \
  --search "in:title,body $ISSUE_NUM" \
  --json number,title,files \
  | jq '[.[] | select((.files // []) | map(.path) | any(startswith("docs/") | not))] | .[] | .number'
```

If any non-docs PR is returned, the implementation probably shipped via
that PR; mark the audit row TRUE-POSITIVE (correctly closed in spirit)
instead of FALSE-POSITIVE. Reserve the reopen action for pairs where
**only** docs PRs ever touched the issue **and** the issue's deliverable
is not itself a docs artifact (runbook, probe-analysis, ADR).

### Pragmatic audit cadence

Quarterly is sufficient unless the repo has shipped >100 PRs/month or
has had a recent incident. Even on the originating repo at ~200 PRs/month
through April-May 2026, a 90-day audit found 0 material false-positives
once the verification gate was applied. Burning daily/weekly compute on
this audit is not the right priority surface.

## References

- Sister skill `gh-squash-merge-closes-only-one-issue` v1.0.0 — different
  failure mode (multi-issue keyword binding on one PR).
- Sister skill `stacked-pr-base-branch-deletion-auto-closes-dependent`
  v1.0.0 — different auto-close trap (stacked PR base deletion side-effect).
- GitHub docs on linking PRs to issues:
  https://docs.github.com/en/issues/tracking-your-work-with-issues/linking-a-pull-request-to-an-issue
  (notes the keyword list but does not warn about the prep-PR misuse pattern).
- Discovery context: the-project-repo S171b session
  (2026-05-11), issue #672, PR #712 (the closing PR), PR #716 (the actual
  implementation PR). Audit prompt template at
  `docs/handoffs/session_172b_closed_issue_audit_prompt.md` in that repo
  (filename uses `172b` suffix because a sibling S172 session in the same
  repo claimed `session_172_*` for an /actions revalidation plan handoff).
