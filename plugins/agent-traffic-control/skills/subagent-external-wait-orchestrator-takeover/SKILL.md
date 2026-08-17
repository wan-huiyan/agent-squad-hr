---
name: subagent-external-wait-orchestrator-takeover
description: |
  Avoid orchestrator-budget burn when a subagent's main work is done but it's
  still polling an external event (CI completion, auto-deploy GHA workflow,
  Cloud Build, gcloud run revision rollout, long-running test suite, etc.).
  Use when: (1) you've dispatched a subagent with a final-step instruction
  like "verify auto-deploy" / "wait for CI green" / "poll until revision
  active", (2) the subagent has already done its substantive work (PR merged,
  artifact built) and is now in a polling loop, (3) you notice repeated
  `<task-notification>` events from that agent with `tool_uses: 0` and short
  `duration_ms` (a few seconds each) — each cycle says "still waiting" or
  "still in progress" with zero forward progress, (4) each notification
  forces the orchestrator to spend a turn responding (often dozens of these
  before the external event completes). The subagent isn't broken — it's
  doing what you asked — but the polling work belongs to the ORCHESTRATOR,
  not a subagent. Captures the takeover pattern: dispatch the subagent for
  the substantive work only (with explicit "do NOT poll for deploy
  verification, return after merge"), then the orchestrator runs a one-shot
  CronCreate scheduled to fire after the expected external-event duration
  to verify and close out. Sister to `schedule-poll-orchestrator-pattern`
  (different layer: that one is for fully-scheduled multi-track workflows,
  this one is for single-subagent in-session orchestration).
author: Claude Code
version: 1.1.0
date: 2026-05-08
disable-model-invocation: true
---

# Subagent external-wait → orchestrator-takeover

## Problem

You dispatch a subagent with a brief that includes both substantive work AND
a final verification step gated on an external event:

> "1. Implement … 2. Open PR … 3. Merge … 4. **Verify auto-deploy: poll GHA
> workflow + `gcloud run revisions list` until new revision is active.**"

Step 4 is **wait work** — the subagent has nothing to compute, only to wait
and check. The harness keeps the agent task open during this wait, and each
heartbeat / external signal wakes the agent for a tiny no-op cycle:

```
status: completed · tool_uses: 0 · duration_ms: 2000 · result: "Still polling."
status: completed · tool_uses: 0 · duration_ms: 2200 · result: "In progress."
status: completed · tool_uses: 0 · duration_ms: 1800 · result: "Continuing to wait."
... × 10-20 ...
```

Each cycle costs:

- **Subagent**: ~100-300 tokens of additional context per wake (small but accumulates)
- **Orchestrator**: ~one full turn to acknowledge the notification (large — the
  orchestrator's context is bigger and every reply costs)

The orchestrator's response cost dwarfs the subagent's polling cost. Over a
13-minute Cloud Build wait, this can be ~10-20 orchestrator turns of "still
polling, will report when done" — a non-trivial budget tax for zero work.

## Context / Trigger Conditions

ALL of the following:

1. You dispatched a subagent (Task tool with `run_in_background: true`)
2. The subagent's brief includes a "wait + verify" step at the end
3. You're seeing repeated `<task-notification>` events from that agent with:
   - `status: completed`
   - `tool_uses: 0`
   - Short `duration_ms` (1-30s)
   - `result` saying some variant of "still polling / in progress / waiting"

The earlier in the wait you notice this, the more orchestrator budget you save
by taking over.

## Solution

### The instruction that causes this most often is a PROHIBITION the agent reads as a command

The brief in the section above at least *asks* for the polling. The commoner and more
expensive case is a line you wrote to stop an agent doing something, which it reads as
an instruction to stand and watch:

> "Arm auto-merge and **wait**."

What that meant: *do not fire `gh pr update-branch`; let GitHub land it when the checks
pass.* What it was read as: *poll until the pull request merges.*

**Measured in one night: five agents did exactly that.** One returned `meow~` three
times having spent **300,000 tokens**; another spent **355,000**; a third reported
individual CI legs going green, one at a time, as though that were progress. **Their
findings had been written into the pull request body the whole time** — the work was
finished before the waiting started, and every token after that bought nothing.

**Worse than the tokens: a polling agent emits notifications that look like progress.**
A stalled agent is at least quiet. This one produces a steady stream of plausible
status lines, so each notification costs the orchestrator a wake to discover that
nothing happened — and the fleet looks busy while it is idle.

**The fix is two separate instructions, because one sentence cannot carry both.** They
are about different things and merging them is what created the ambiguity:

```
1. REPORT IMMEDIATELY after arming auto-merge. Your findings go in the PR body
   before you arm. Do not wait for checks, do not wait for the merge, do not
   report merge status — that is the orchestrator's job.

2. NEVER fire `gh pr update-branch` while a run is in progress on that branch.
```

Line 1 is what to do; line 2 is what not to do. Write both, and never write a
prohibition whose verb ("wait", "hold off", "leave it alone") could be read as an
activity.

**And check that the wait is even necessary.** In this case the deliverable — the
findings — was already durable in the PR body. An agent waiting to report something it
has already reported is the purest form of this bug.

Two adjacent failures worth telling apart when you write the brief:

- Scope the prohibition in line 2 **per branch**. Written repo-wide — "only when
  nothing is running" — it stalls the agent silently instead, which is harder to
  notice than polling because it produces nothing at all:
  [`orchestrator-rule-too-strict-stalls-agent-silently`](../orchestrator-rule-too-strict-stalls-agent-silently/SKILL.md).
- If the agent polls because nothing is landing at all, the queue may be the problem
  rather than the brief:
  [`merge-queue-thrash-stop-inflow-and-open-prs-as-drafts`](../merge-queue-thrash-stop-inflow-and-open-prs-as-drafts/SKILL.md).

### Preventive (write better briefs from the start)

In any subagent brief that includes external-event verification, replace the
"poll until done" step with EITHER:

**Option 1 — Subagent returns after the artifact is shipped, orchestrator verifies:**

```
9. `gh pr merge --squash --delete-branch <PR#>`
10. **Return immediately** with the merge commit SHA. Do NOT wait for the
    auto-deploy GHA workflow or Cloud Run revision rollout — the
    orchestrator handles that verification.
```

Then the orchestrator schedules a one-shot CronCreate for the expected
duration (e.g., 4 minutes after merge for a typical Cloud Build) to verify:

```python
CronCreate(
  cron="<one-shot expression for now+4min>",
  prompt="Verify auto-deploy for PR #N: gh run view <run-id>; gcloud run revisions list ...",
  recurring=False
)
```

**Option 2 — Subagent uses `gh pr checks --watch` (single blocking call):**

```
8. `gh pr checks <PR#> --watch` — this blocks until CI conclusion (single
   tool call, no polling loop).
9. If green, merge.
```

`gh pr checks --watch` is a single blocking subprocess that doesn't return
until CI completes. The subagent makes ONE tool call and waits inside that
call. The harness sees one long-running tool, not dozens of short ones.

### Reactive (you already see the polling pattern)

If a subagent is already in a zero-tool-use polling loop:

1. **Don't tell the agent to keep waiting** — every "ack, keep going"
   reply costs more than just taking over.
2. **Take over via CronCreate**: schedule a one-shot verification fire-time
   based on remaining expected duration, with a self-contained verification
   prompt.
3. **Let the agent's polling timeout naturally**. Don't kill it (TaskStop
   would also burn a turn) — just stop responding to its notifications.
   The orchestrator's verification cron will do the actual close-out.

### Tactical scripts

For the common Cloud-Run-via-GHA-`pull_request:closed` deploy verification:

```bash
# Verify auto-deploy completed for a merged PR.
# Run this from a one-shot CronCreate ~4 min after merge.
PR_NUMBER=$1
REPO=$2
SERVICE=$3
REGION=${4:-us-central1}

# Find the workflow run by name (NOT by squash SHA — that's a different SHA
# than the synthesized merge ref the workflow ran on)
RUN_ID=$(gh run list --repo "$REPO" \
  --workflow "Auto-deploy pulse on PR merge" \
  --limit 5 --json databaseId,status,createdAt \
  --jq '[.[] | select(.status != "skipped")][0].databaseId')

# Check workflow conclusion
gh run view "$RUN_ID" --repo "$REPO" --json status,conclusion

# Confirm new revision is active
gcloud run revisions list --service "$SERVICE" --region "$REGION" \
  --limit 3 --format='table(name,active,createTime)'
```

## Verification

After applying takeover:

- Subagent's polling notifications stop arriving at the orchestrator (it
  either terminates on a timeout or you've stopped responding)
- Cron-scheduled verification fires once, runs ~5-10 tool calls, declares
  done, exits — orchestrator spends ONE turn instead of N
- Total orchestrator turns spent on the wait: 1 (fire-and-forget cron
  schedule) + 1 (cron fires + orchestrator handles result) = 2

Compare to without takeover: 10-20 turns × N notifications.

## Example

S156 Track C orchestration (2026-05-08):

- Dispatched Track C subagent with brief that included "9. Verify
  auto-deploy: poll GHA workflow + `gcloud run revisions list`"
- Subagent merged PR #570 at 17:12:46 UTC
- Subagent then went into polling loop — by 17:14 had sent 8+ zero-tool-use
  `<task-notification>` events to orchestrator: "Still running.",
  "Continuing to wait.", "Auto-deploy still in progress.", etc.
- Each notification cost ~one orchestrator turn (~hundreds of tokens of
  context plus the response)
- **Recovery**: orchestrator scheduled a one-shot `CronCreate` at +4min
  (`17 18 8 5 *`) with a self-contained verify prompt, then stopped
  responding to subagent notifications. The cron fired once at 18:17,
  did `gh run view 25569007030` + `gcloud run revisions list`, confirmed
  revision `00048-jds` active, posted final summary, exited.
- Net savings: ~10 orchestrator turns avoided

The subagent's ~10 zero-tool-use micro-cycles cost the subagent itself
~1KB of context — negligible. The orchestrator-side cost was the real bug.

## Notes

- The takeover pattern has a sister case for **scheduled multi-track
  workflows** (RemoteTrigger + cron-fired orchestrator): that's covered
  by `schedule-poll-orchestrator-pattern`. This skill is the in-session
  single-subagent variant.
- `gh pr checks --watch` is a much underused alternative to polling loops.
  When the subagent's wait is on CI specifically (not deploy), prefer the
  single-blocking-call form.
- Some external events have webhooks / `WORKFLOW_RUN` notifications you
  could subscribe to instead of polling, but in-session orchestrator
  context can't easily receive those — cron-based fire-time approximation
  is usually the practical answer.
- The Anthropic prompt cache TTL is 5 minutes. If your one-shot cron is
  scheduled for 4 minutes out, the orchestrator's reactivation reads cache;
  past 5 min, it pays a cache miss. Tradeoff: shorter wait = stays cached
  but might fire too early and need re-schedule; longer wait = cache miss
  but more reliable single-fire. For Cloud Build typical 3-5 min, schedule
  at +4min, accept occasional re-schedule.
- This skill applies to ANY external-event wait, not just deploy: long
  pytest suite, Dataform compile, BigQuery long-running query, baker
  invocation polling, model training job completion, etc.

## References

- Sister skill: `schedule-poll-orchestrator-pattern` — its own plugin in the
  `wan-huiyan-overnight-workflows` marketplace, not here (cron-fired multi-track
  variant; complementary, not redundant)
- Sister skill: `subagent-reports-complete-but-pr-unmerged` (related: gap
  between agent status and actual PR state)
- Related skill: `superpowers:dispatching-parallel-agents` (when to choose subagent
  dispatch in the first place)
- gh CLI: [`gh pr checks --watch`](https://cli.github.com/manual/gh_pr_checks)
  blocks until CI conclusion in a single subprocess call
- Anthropic prompt cache: 5-minute TTL on cached system prompt blocks
  (relevant for picking cron fire-time intervals)
