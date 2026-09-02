---
name: gh-issue-claim-coordination
listing_tier: short
description: |
  Before writing code for a GitHub issue when another session might take the same one, claim it
  with BOTH an assignee and a `wip` label so a sibling sees it and skips. Trigger on "pick up
  issue #N", "work through the open issues", "is anyone on this?". Not for filing or reviewing.
---
# GitHub issue claim coordination (assignee + label)

When multiple Claude Code sessions (or human + agent) work the same repo in parallel, two sessions can independently pick up the same issue, do parallel implementations, and collide at PR time — burning hours of duplicated work and forcing one branch to be rebased or abandoned.

**Default agent behaviour is silent.** An agent dispatched to "work on the bug-tagged issues" does not automatically check whether another session is already on issue #N. There's no built-in coordination unless this skill (or equivalent) runs at pickup.

This skill installs a 60-second protocol — preflight check, atomic claim, stale-claim sweep, release on completion — using two GitHub-native primitives so the claim is visible everywhere (issue list UI, `gh issue list`, dashboards, sibling sessions).

## Why both `assignee` AND a `wip` label?

They cost ~0 to set together and cover different failure modes:

- **`assignees`** is GitHub's canonical "who's on this" primitive. `gh issue list --assignee ""` cleanly enumerates unclaimed work; agents tend to surface assignees in their own context without prompting.
- **A `wip` label** is far more visible in the GitHub issue list UI (a coloured chip next to the title) and lets you find every active claim with one query: `gh issue list --label wip`. It also survives the case where someone reassigns the issue without thinking about coordination.

Belt and suspenders. If the assignee gets dropped on a bulk edit, the label still flags it; if the label gets dropped, the assignee still says it.

## Pickup protocol

### Step 0: Ensure the `wip` label exists (idempotent — runs every time)

Don't carry "did I do the setup yet?" state. The label create is cheap and noisy on success only the first time; on subsequent runs it just exits non-zero with "already exists", which `|| true` swallows. Bake it into every pickup so a fresh repo or a teammate's repo just works.

```bash
gh label create wip \
  --description "Claimed by an active session — do not start parallel work" \
  --color FBCA04 \
  || true
```

If this fails with a permissions error (rare; happens on repos where your account can't manage labels), fall back to assignee-only claim and tell the user.

### Step 1: Preflight (single command, returns JSON)

Before writing any code for an issue:

```bash
ISSUE=123  # the issue you're about to start

gh issue view "$ISSUE" \
  --json number,state,assignees,labels,updatedAt \
  --jq '{number, state, assignees: [.assignees[].login], labels: [.labels[].name], updatedAt}'
```

Read the result against this decision table:

| State + assignees + labels                                         | Action                                                                                                                                              |
| ------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| `OPEN`, `assignees: []`, no `wip` label                            | **Free — claim it.** Proceed to claim step.                                                                                                         |
| `OPEN`, assigned to you, has `wip` label                           | **Yours — resume.** No re-claim needed.                                                                                                             |
| `OPEN`, assigned to someone else, OR `wip` label set by another    | **STOP.** Surface to user with assignee + `updatedAt`. Do not start parallel work.                                                                  |
| `OPEN`, has `wip` but `updatedAt` > stale window with no linked PR | Likely abandoned — see [Stale-claim sweep](#stale-claim-sweep) before claiming.                                                                     |
| `CLOSED`                                                           | Issue is done. Confirm scope with user before reopening; the merged PR's diff may already cover what you were going to build.                       |

### Step 2: Claim (after preflight clears)

```bash
gh issue edit "$ISSUE" --add-assignee @me --add-label wip
```

These are independent edits — both should succeed (Step 0 already ensured the `wip` label exists). If only one succeeds because of a transient blip, retry the missing one before starting work. A half-claim is worse than no claim because it confuses future preflights.

### Step 2 (alternative): Surface a collision

When the preflight shows another session has the claim, **do not proceed**. Tell the user something like:

> Issue #123 is currently claimed by `@other-session` (`wip` label, last touched 2h ago at 2026-05-08T09:14Z). Want me to (a) wait, (b) work on a different issue, or (c) override the claim because you know that session is dead?

The user owns the override decision. They might know the other session crashed; they might not. Surfacing the timestamp + claimant lets them choose; do not unilaterally override.

## Stale-claim sweep

Sessions crash, get cancelled, get forgotten. Without a sweep, a stale `wip` label can lock an issue forever.

**Default rule:** a claim is stale if `updatedAt` is more than **24 hours** old AND no PR is linked. Adjust the window to your workflow (shorter for fast-moving repos, longer if multi-day issues are normal).

Find candidates:

```bash
gh issue list --label wip --state open \
  --json number,title,assignees,updatedAt,url \
  --jq '.[] | select((now - (.updatedAt | fromdateiso8601)) > 86400)'
```

(`86400` = 24 hours in seconds. Change to `43200` for 12h, `14400` for 4h, etc.)

When you find a stale claim, **ask the user before clearing it** — the assignee may have paused intentionally (waiting on an external dep, debugging out of band, etc.). If cleared, drop both:

```bash
gh issue edit "$ISSUE" --remove-assignee <stale-assignee> --remove-label wip
```

## The reverse claim: hands-off lists must cite ownership, never infer it

The protocol above records who *is* working on something. The mirror image — telling
your agents what **not** to touch — has no protocol, and it fails in the opposite
direction: instead of two sessions colliding, **nobody works on it at all**.

**What happened (real):** a pull request was put on every agent's hands-off list for
**three days**, on the assumption that it belonged to another session. It did not. It
was the user's own, opened the day before she left. The instruction not to touch it is
the entire reason nobody did.

That failure is silent in a way a collision is not. A collision produces two branches
and an argument. An over-broad hands-off list produces nothing, and a PR sitting
untouched looks exactly like a PR nobody has got to yet.

**The rule: an exclusion needs evidence of ownership, from the same primitives a claim
uses.** Ownership is recorded, so read it — do not infer it from a branch name, a
timing coincidence, or a style that looks like another session's:

```bash
# Who actually owns this? Author, assignees, and whether anything claims it.
gh pr view "$PR" --json author,assignees,createdAt,headRefName,isDraft \
  --jq '{author: .author.login, assignees: [.assignees[].login], createdAt, headRefName, isDraft}'

# And the issue it is attached to, if any — the wip label is the claim.
gh issue view "$ISSUE" --json assignees,labels,updatedAt
```

If none of those names an owner, **the honest entry is "owner unknown", not "belongs to
another session"** — and an unknown owner is a question for the user, not a reason to
freeze the item indefinitely.

**Three rules that make a hands-off list safe to publish:**

- **Every entry carries its reason and its evidence.** `#123 — hold, assigned to
  @other-session, wip label set 14:02` is checkable. `#123 — someone else's` is not, and
  it is the form that survives for three days.
- **Every entry carries an expiry.** A hands-off list is a claim like any other, so give
  it the same sweep as above: an exclusion older than the stale-claim window gets
  re-checked against `gh pr view`, not renewed by default.
- **A hold you actually need enforced is a state, not a sentence.** If the point is that
  a PR must not merge, the list is the wrong tool —
  [`auto-merge-rearms-while-agent-live-kill-then-disarm-verify`](../auto-merge-rearms-while-agent-live-kill-then-disarm-verify/SKILL.md)
  covers why a disarm does not hold while its agent is live, and why a draft does.

## Release on completion

GitHub auto-handles the happy path: a merged PR with a closing keyword (`Closes #123` / `Fixes #123` / `Resolves #123`) closes the issue and the assignee becomes irrelevant. The `wip` label, however, is **not** auto-removed by PR merge — and a CLOSED issue still showing `wip` clutters `gh issue list --label wip` and confuses future stale-claim sweeps.

After PR merge, drop the `wip` label:

```bash
gh issue edit "$ISSUE" --remove-label wip
```

The assignee can stay (it's useful history of who shipped the fix). Only the label needs cleaning.

### Partial-scope guardrail

If your PR only addresses **part** of an issue (`Addresses Part 1.3 of #500` rather than `Closes #500`), keep the issue claimed:

- Do **not** remove the `wip` label after merging the partial PR.
- Do **not** remove yourself as assignee.
- The claim continues until **all** in-scope parts ship.

GitHub's closing-keyword parser is permissive enough to auto-close the parent issue on partial PRs if the wording drifts (e.g. `Closes Part 1 of #500` will close #500 wholesale). The defensive PR-body phrasing ("Addresses Part X of #N", no closing keyword anywhere near `#N`) is independent guidance — see the project memory file `feedback_pr_partial_close_phrasing.md` if you have one.

## When NOT to use this skill

- **Single-session work** with zero parallel risk. The 60-second protocol is overhead with no benefit.
- **Filing new issues.** Claim happens at pickup, not creation.
- **Just reading or commenting** on an issue. The claim signals "I'm about to write code for this," not "I'm thinking about this."
- **Repos where your account can't be assigned** (rare; surfaces as a `gh issue edit` error). Fall back to label-only with a comment recording your session ID.

## Quick reference

```bash
# Pickup (Step 0: ensure label exists — idempotent, runs every time)
ISSUE=123
gh label create wip --color FBCA04 \
  --description "Claimed by an active session — do not start parallel work" || true

gh issue view "$ISSUE" --json number,state,assignees,labels,updatedAt \
  --jq '{number, state, assignees: [.assignees[].login], labels: [.labels[].name], updatedAt}'
# (read decision table; if free:)
gh issue edit "$ISSUE" --add-assignee @me --add-label wip

# Stale sweep (24h window)
gh issue list --label wip --state open \
  --json number,title,assignees,updatedAt,url \
  --jq '.[] | select((now - (.updatedAt | fromdateiso8601)) > 86400)'

# Release after merge (only the label; assignee can stay)
gh issue edit "$ISSUE" --remove-label wip
```

## Sister skills / memory entries

- **`feedback_track_partial_batch_filings.md`** — different problem (knowing what YOU filed when a sandbox cancels mid-batch). This skill prevents the upstream collision; that one cleans up after a different failure mode.
- **`feedback_coordination_framing_for_parallel_artifact_collisions.md`** — what to do AFTER two parallel artifacts have already collided. This skill prevents the collision; that one frames the recovery.
- **`feedback_pr_partial_close_phrasing.md`** — keeps GitHub's closing-keyword parser from auto-closing on partial PRs. Pairs with the partial-scope guardrail above.
- **`merge-conflict-generated-files`** — resolves rebase conflicts when parallel PRs collide on generated output files; its "tracker + site regen" worked example is this exact shape. Downstream of a missed claim; if this skill runs, that one fires less often.

## Reference-only siblings in this toolkit

These carry `disable-model-invocation: true`. They never appear in the skill
listing and the Skill tool refuses them, so the only way in is to open the file
with Read when one of these matches what you are looking at.

- [`prep-pr-close-keyword-auto-closes-issue`](../prep-pr-close-keyword-auto-closes-issue/SKILL.md) — a prep/planning PR's `Closes #N` closed the issue before the work was done
- [`executed-prompt-not-retired-sibling-redoes-it`](../executed-prompt-not-retired-sibling-redoes-it/SKILL.md) — an executed brief was not retired on both the file and its index, so a sibling session redid the work
- [`wip-branch-linter-revert-system-reminder-trap`](../wip-branch-linter-revert-system-reminder-trap/SKILL.md) — a linter or automation quietly reverted a deliberate wip-branch framing
