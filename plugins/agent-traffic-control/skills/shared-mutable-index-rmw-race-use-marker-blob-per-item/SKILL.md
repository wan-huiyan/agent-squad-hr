---
name: shared-mutable-index-rmw-race-use-marker-blob-per-item
description: |
  Designing a shared "who is active / recent items" index that concurrent producers write to: one
  mutable list silently loses entries. Write one marker per item.
author: Claude Code
version: 1.1.0
date: 2026-06-09
---
# Shared mutable index → use a marker blob/row per item (not a read-modify-written list)

## Problem

You are building a feature where **multiple producers concurrently register items into a shared
collection, and a reader periodically prunes dead entries** — e.g. a "see everyone's in-flight
runs / active sessions / recent uploads" list shown on a home/dashboard page, shared across a
team / workspace / user.

The tempting design is **one shared mutable container** that you read-modify-write:

```python
# register (producer)                       # render + prune (reader)
ids = read(index)                           ids = read(index)
ids = [new_id] + dedupe(ids)                live = [i for i in ids if still_alive(i)]
write(index, ids[:CAP])                     write(index, live)   # prune
```

This has a **read-modify-write race**. Interleave two callers:

1. Reader reads `[A]`.
2. Producer reads `[A]`, computes `[X, A]`, writes `[X, A]`.
3. Reader writes its pruned copy `[A]` (computed in step 1, before X existed).

**X is now permanently gone from the index.** It is never re-added — registration fires *once*,
at create time. So the very item the feature promises to surface silently never appears for
anyone. It is **not** self-correcting (a common false assumption). The window is small, but it is
exactly the "two people working at once" moment the feature exists to serve, and a janitor/prune
reader widens it.

## Context / Trigger Conditions

- You're DESIGNING (or reviewing) a shared "active items / recent items / running now / activity
  feed" index with **concurrent writers** and a **pruning reader**.
- The backing store is a single read-modify-written container: a JSON array in one
  GCS/S3/object-store blob, a DB array/JSON column, a shared cookie list, one file.
- Symptom in the wild: an item a colleague just created **never shows up** in the shared list;
  intermittent "missing entries" that no single user can reproduce; a code reviewer flags a race
  on the index write-back.
- Adjacent (the durable-pointer / reconstruction half of these features):
  see also `in-memory-job-registry-orphans-cloud-result-on-restart` and
  `reconstruction-from-durable-store-must-replicate-completion-gate`.

## Solution

**Use one marker blob/row PER ITEM**, not a shared list:

```
<prefix>/<item_id>      # e.g. _active_runs/<workspace>/<run_id>  — empty body
```

- **Register (producer):** write your *own* key. No read → **race-free by construction**. Two
  concurrent registrations write two different keys; neither can clobber the other.
  ```python
  bucket.blob(f"{prefix}/{item_id}").upload_from_string(b"")
  ```
- **Read (reader):** `list_blobs(prefix=...)` → the item_ids are the key basenames.
- **Prune (reader):** delete the *individual* keys you've confirmed dead. Deleting one key never
  races another producer's key.

Then layer on three cheap refinements the list design made awkward:

1. **Age-prune by the id's embedded timestamp, with NO resolve.** If `item_id` is
   `<hash>_<epoch>` (or any id carrying a creation time), drop entries older than a TTL by *name*
   — `delete(key)` without a round-trip to resolve the item's real state. Self-cleans abandoned
   markers cheaply and bounds the working set.
2. **Dedupe at read time by a stable sub-key.** If two ids map to the same logical thing (e.g.
   `<config_hash>_<ts1>` and `<config_hash>_<ts2>` are re-runs of the same config), keep the
   newest per sub-key at read time so a re-run doesn't resurrect a stale card. Delete the older
   markers.
3. **Cap resolve/display, not just storage.** Sort newest-first; resolve+render at most N (e.g.
   8); leave the rest (age-prune still bounds them). Bounds the per-load cost of resolving each
   marker. NB: the cap is on *cards rendered*, not *markers resolved* — a burst of young-but-dead
   markers can still cost one resolve each on the first load after the burst (then they're pruned).

**Why not "JSON list + optimistic-concurrency CAS retry" (generation precondition)?** It works,
but it *guards* the race with retry loops instead of *removing* it, and it keeps the all-or-nothing
write. Prefer marker-per-item unless you genuinely need ordering or atomic multi-item updates.
Bonus: object stores that already keep `results_<id>.json` / `events/<id>.json` per item are
telling you the idiom — marker-per-item matches the grain of the store.

**If you DO use CAS (the legitimate ordered/atomic-update exception — e.g. an upload *manifest*
that is a single ordered list with cross-item dedup + cascade-delete semantics), the footguns
that make a "passing" CAS silently a no-op or a data-loss:**
- **The precondition must read a REAL generation, or it's a silent no-op.** On GCS,
  `blob.upload_from_string(data, if_generation_match=gen)` raises `google.api_core.exceptions.PreconditionFailed`
  (412) on a lost race — but only if `gen` is real. Non-obvious: after `blob.download_as_text()`,
  `blob.generation` IS populated (from the `X-goog-generation` response header — verified
  google-cloud-storage 3.10.1, `blob.py` `_extract_headers_from_download`), so you can read+capture
  it in one round-trip. If it ever comes back `None` (a non-modelling test fake, or a future lib
  release that stops populating it on download) the code path that does `if gen is not None` falls
  through to an *unconditional* write → the race protection is gone and tests stay green. **More
  robust: read via `bucket.get_blob(key)` (explicit metadata GET → generation always an int; returns
  `None` only on `NotFound`; raises on a real read error → fail-closed)** instead of relying on the
  download side-effect. Pin the client major (`google-cloud-storage>=2,<4`) so the contract can't
  silently change.
- **First write = create-only.** Read an absent index → use `if_generation_match=0` so two concurrent
  first-writers can't both blindly create-and-clobber.
- **Cascade-deletes (reaping displaced blobs) run ONLY after the winning save, from the FINAL
  reconciled displaced set.** A retry recomputes `(new, displaced)` from the reloaded state, so a
  blob the concurrent winner now references is never deleted. Reaping inside the retry loop, or from
  a stale pre-retry `displaced`, deletes a live blob — a worse bug than the race you fixed.
- **A swallow-the-read-error path that then writes is a data-loss trap.** `except Exception: return [], None`
  on the *read* → the caller writes the index rebuilt from just the new entry → clobbers everything.
  Re-raise on a genuine read error (the route's outer handler turns it into a retry), or use
  `get_blob` which fails closed. (the-causal-impact-repo #359 F9 / #457.)

## Verification

- **Race test (the one the list design can't pass):** simulate "reader reads → producer registers
  → reader writes-back-pruned" and assert the producer's item survives. With marker-per-item this
  is trivially true (independent keys); with a shared list it fails.
- Register two items "concurrently" and assert **both** markers exist (no clobber).
- Prune a dead item and assert only its marker was deleted (others intact).
- Stale-by-name marker is deleted **without** a resolve call (trip-wire the resolve fn / client).

## Example

`the-causal-impact-repo` #323 (PR #336, 2026-06-05): a `/home` "Pick up where you left off" feature
showing a workspace's in-flight analysis runs. First built as `_workspace_runs/<slug>.json` (a
shared JSON list, read-modify-written at dispatch and pruned on `/home`). A review panel (two
independent reviewers) flagged the RMW race: a colleague's just-dispatched run could be
permanently dropped — defeating the "see each other's runs" promise. Reworked to a marker blob per
run, `_workspace_runs/<slug>/<run_id>`: race-free, plus age-prune-by-name, config-hash dedupe, and
an 8-card cap. It also matched the codebase, which already stored `results_<method>.json` /
`tests/<type>.json` per item.

## Notes

- This is the *index/enumeration* half. The *resolution* half (rebuilding each item's real state
  from a durable store when an in-memory cache was wiped by a restart) is a separate concern —
  see `reconstruction-from-durable-store-must-replicate-completion-gate` (replicate the in-memory
  completion gate so a partial item isn't shown as done) and
  `in-memory-job-registry-orphans-cloud-result-on-restart`.
- Security note for shared indexes: a durable, enumerable index of ids (+ any attached identity
  like a submitter email) can *erode an unguessability-based access control* — if item URLs were
  "protected" only by hard-to-guess ids, an enumerable index hands an attacker the list. Scope the
  index read to verified members of the sharing boundary (team/workspace), or accept it explicitly
  for the threat model.
- Marker bodies can stay empty (the key *is* the data). If you need a tiny bit of metadata, a few
  bytes in the body is fine — but resist re-creating a shared mutable structure inside it.
