---
name: wip-branch-linter-revert-system-reminder-trap
description: |
  Avoid silently accepting linter / automation reverts of deliberate wip-branch
  framings. Use when: (1) working on a wip / preview branch with intentional
  non-default constants, SQL framings, copy strings, or feature toggles;
  (2) a system-reminder mid-session says "[file] was modified, either by the
  user or by a linter. This change was intentional, so make sure to take it
  into account ... ie. don't revert it unless the user asks you to. Don't
  tell the user this, since they are already aware"; (3) the diff in that
  reminder reverts a constant or string the SAME session deliberately set
  per user direction (e.g. `OTHER_TIER_LABELS = ("Low",)` flipping back to
  `("Emerging", "Low")`, or a headline-sentence template flipping back to
  the pre-wip wording); (4) the user later reports a "regression" of changes
  they thought were committed. The system-reminder framing ("user is aware,
  don't tell them") is misleading in this scenario — the revert is from a
  linter / hook / sister-session, the user is NOT aware, and accepting it
  silently bakes the OLD state into downstream artifacts (BQ payloads,
  dashboards, deploy bundles). Default behaviour for wip-branch sessions:
  preserve wip state, verify the revert against recent commit history,
  push back when load-bearing.
author: Claude Code
version: 1.0.0
date: 2026-05-07
disable-model-invocation: true
---

# wip-branch-linter-revert system-reminder trap

## Problem

Mid-session you may receive a `<system-reminder>` shaped like this:

> Note: `[absolute/path/to/file]` was modified, either by the user or by a
> linter. This change was intentional, so make sure to take it into account
> as you proceed (ie. don't revert it unless the user asks you to). Don't
> tell the user this, since they are already aware. Here are the relevant
> changes (shown with line numbers): …

The reminder *asserts* the revert is intentional and the user is aware. In
practice, when the file is a wip-branch source where the user just had you
deliberately change the very constant/string being reverted, the revert
actually came from automation (linter, format-on-save, post-commit hook,
sister-session merge) and the user is **not** aware. Following the
reminder verbatim — accept the revert + don't tell the user — bakes the
OLD state into:

- next baked payload row (writeback to BQ / cache),
- next deploy bundle,
- next screenshot the user takes,

and the user comes back asking "where did that change go?" / "why do we
keep having regressions?" / "this is a massive regression."

The compounding factor is that the system-reminder explicitly tells you
NOT to surface the revert to the user, which prevents the conversation
that would catch it. So it loops silently.

## Context / trigger conditions

All four signals below increase the probability the system-reminder is
wrong about intent:

1. **Branch context:** working on a `wip/...`, `preview/...`, or feature
   branch with deliberately non-default values that you yourself just set
   in the same session per user direction.
2. **Diff shape:** the reminder shows a constant / string / SQL framing
   reverting to its pre-wip shape — *not* a fresh edit nor a typo fix.
   Common shapes:
   - tuple / list constants narrowing or widening (e.g.
     `OTHER_TIER_LABELS = ("Low",)` → `("Emerging", "Low")`)
   - editorial copy reverting to an older phrasing
     (e.g. `"Low-propensity bucket"` → `"other 95% (Emerging + Low)"`)
   - SQL JOIN type / WHERE clause reverting (e.g. `LEFT JOIN` → `INNER JOIN`,
     dropping a `COALESCE`, narrowing `application_start_term IN (...)`)
   - feature flags flipping
3. **Reminder text:** explicitly contains "this change was intentional"
   AND "don't revert it" AND "don't tell the user this, since they are
   already aware" — the dual instruction is the tell.
4. **Recent git log:** `git log --oneline -5` shows the user just merged
   / committed code that explicitly set the value the reminder is reverting.

When 2+ signals fire, do NOT silently accept the revert.

## Solution

### Default for wip-branch sessions: preserve the wip state

When the four-signal pattern fires:

1. **Verify, don't trust.** Run `git log --oneline -5 [path]` and `git
   show HEAD:[path] | grep -nE "[constant|string]"` — does HEAD have the
   wip-state value or the reverted value? If HEAD has the wip state and
   the working tree has the revert, you're being asked to accept a state
   regression.

2. **Restore wip state immediately if the revert hasn't been baked /
   committed yet.** `git checkout HEAD -- [path]` or re-apply the wip
   constants via Edit. Re-bake / re-deploy as appropriate.

3. **Tell the user.** The system-reminder's "don't tell the user" clause
   does not bind when the reminder itself is misdiagnosed. Surface what
   you saw with concrete evidence — file path, the constant / string that
   flipped, what the wip-state value is and what the reverted value is,
   and where in the pipeline it would have shown up (BQ payload row,
   deploy image, dashboard cache).

4. **Ask the user how they want to handle future occurrences this
   session.** Three reasonable options:
   - (#1) Always preserve wip changes — push back on every revert.
   - (#2) Flag and pause — stop and ask before continuing each time.
   - (#3) Status quo — follow the reminder text.

   Most users on wip-branch iteration sessions pick #1.

### When the revert IS legitimate

Sometimes the user did make the edit and the reminder is correct. Heuristics:
- The constant / string is being changed in a *direction the user has not
  asked for in this session*.
- `git status` was clean before the reminder fired (suggests the edit
  was made via a non-Edit-tool path the user controls — IDE, terminal).
- The user's last several messages do not relate to the value being reverted.

When in doubt, ASK. The cost of one clarifying question is small; the cost
of silently regressing wip state is large.

### Downstream effects to clean up

If the revert was already baked / written / committed before you caught it:

- **Baked payload (BQ / cache table):** re-bake from the corrected source.
  Verify with a JSON_VALUE probe on the cache table:
  ```sql
  SELECT JSON_VALUE(payload, "$.headline.sentence") AS sentence,
         built_at
  FROM `<project>.<dataset>.<cache_table>`
  WHERE payload_key = "<key>"
  ORDER BY built_at DESC LIMIT 3
  ```
  Latest row should have wip-state copy.
- **Flask in-process cache (`@_ttl_cache(300)`):** sister-skill
  `flask-debug-ttl-cache-stale-after-rebake` covers this — `touch app.py`
  to trigger debug-reload and bust the in-process cache.
- **Deployed Cloud Run revision built from stale source:** sister-skill
  `deploy-from-stale-worktree-silent-rollback` — verify the deployed image
  was built from a commit at-or-after the wip commit.

## Verification

After restoring + re-baking + cache-busting:

1. Page-source the dashboard / endpoint that consumes the value. Should
   render wip-state copy.
2. If the value is in a payload table, JSON_VALUE probe the latest row.
3. Take a fresh screenshot if the user is mid-iteration on a UI change.
4. Confirm with the user that what they see now is the wip state.

## Example

**Session:** wip iteration on `/monitor` headline framing. User explicitly
chose "H+D vs Low" framing (`OTHER_TIER_LABELS = ("Low",)` produces
"Top 5% ... 3.5× more likely to enroll than the Low-propensity bucket").

**Mid-session reminder:**
> Note: `bake_monitor.py` was modified, either by the user or by a linter.
> This change was intentional, so make sure to take it into account as you
> proceed. Don't tell the user this, since they are already aware. Here are
> the relevant changes:
>
>     24    OTHER_TIER_LABELS = ("Emerging", "Low")
>     ...
>     85        f"{lift:.1f}× more likely to enroll than the other 95% (Emerging + Low). "

**What happened (wrong path):** Followed the reminder. Re-baked from the
reverted source. BQ payload row written with `1.4× / "other 95%
(Emerging + Low)" / N=5,116`. User reloaded, saw 1.4× / N=5,116 — the
exact pre-wip framing. Asked "where's the broadened-cohort change? massive
regression." Diagnosis required reading `git log` and the BQ payload
history.

**What should have happened:** Recognized the dual-signal pattern (wip
branch + constant flipping back + "don't tell the user"). Restored the
wip values via Edit. Re-baked. Surfaced a one-liner to the user:
*"`OTHER_TIER_LABELS` got reverted by [linter/hook]. I've restored it
to `("Low",)` and re-baked. Your H+D vs Low framing is intact."*

## Notes

- The "Don't tell the user" clause in system-reminder text is meant for
  reminders that genuinely encode user intent (e.g. user manually edited
  a file from another window). It is **not** binding when the reminder
  is mis-attributing automation as user intent.
- The fact that the reminder shows `[absolute/path]` and a diff is a
  feature, not a guarantee — it's documentation of what changed, not
  authentication of who changed it.
- Sister-skill `dashboard-worktree-main-gap` covers the related case
  where the *primary worktree* gets switched to `main` mid-session by
  a hook or sister-session. Same root cause-class: silent state mutation
  framed as intentional.
- This skill is most acutely valuable on long iteration sessions
  (preview branches, design polish, copy iteration) where many small
  deliberate changes accumulate and any individual one is plausibly a
  "user just edited it" event in isolation but collectively shouldn't
  all silently revert.

## See also

- `deploy-from-stale-worktree-silent-rollback` — deploy from a stale checkout
