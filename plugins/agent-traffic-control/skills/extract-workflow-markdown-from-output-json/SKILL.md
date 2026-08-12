---
name: extract-workflow-markdown-from-output-json
description: |
  Use when a Workflow (or background Agent) synthesis step returns a LARGE markdown
  deliverable inside a structured-output (schema) field — e.g. a `next_prompt_markdown`,
  a full report, a generated doc — and you need to persist it to a file. The completion
  notification TRUNCATES the result and shows the field JSON-escaped (literal `\n`, `\"`),
  so hand-retranscribing it into a Write call is both lossy (you only saw part of it) and
  error-prone (escapes leak as literal text). Trigger: you're about to retype an agent's
  big returned markdown blob from a `<task-notification>` or truncated tool result into a
  file. Symptoms it prevents: a saved doc containing literal `\n`/`\"`, or silently missing
  the tail past the truncation cap.
author: Claude Code
version: 1.0.0
date: 2026-06-06
disable-model-invocation: true
---

# Persist a Workflow's large markdown field by parsing its output JSON — never retype it

## Problem
A Workflow's synthesis `agent(..., {schema})` returns a big markdown deliverable in a schema
field (e.g. `next_prompt_markdown`, `report`, `plan`). You want it on disk. The instinct is to
copy it out of the completion `<task-notification>` (or the truncated tool result) into a Write
call. Two failures follow:
1. **Truncation loss** — the notification/tool result is capped (often a few hundred lines / ~25-35k
   tokens) with `... (truncated N chars, full result in <path>)`. Retyping from it silently drops
   everything past the cap.
2. **Escape leakage** — inside the JSON the field is escaped: newlines are literal `\n`, quotes are
   `\"`. Hand-copying (or reflowing) it often ships those escapes as literal text in the saved file,
   so the markdown renders as one line with visible `\n`.

## Context / Trigger conditions
- A `Workflow` / background `Agent` finished; its result contains a long markdown/string field you
  want to save as a `.md` (a next-session prompt, a synthesized report, generated copy).
- The `<task-notification>` says `full result in /private/tmp/.../tasks/<task-id>.output`.
- You're tempted to Write the content by retyping it from what you can see.

## Solution
The full, unescaped result is always persisted to the output file named in the notification
(`.../tasks/<task-id>.output`, a JSON envelope `{summary, agentCount, logs, result}`). Parse it and
write the field — let `json.load` do the unescaping; never retype.

```bash
OUT="/private/tmp/.../tasks/<task-id>.output"   # path from the <task-notification>
python3 - "$OUT" <<'PY'
import json, sys
r = json.load(open(sys.argv[1]))["result"]
# navigate to the field (e.g. result.synthesis.next_prompt_markdown)
doc = r["synthesis"]["next_prompt_markdown"]
open("docs/handoffs/the_doc.md", "w").write("<your header>\n\n" + doc + "\n")
PY
```

- Prepend your own header in the same script (provenance line, run id) rather than editing after.
- If you also want a human-readable provenance/evidence doc from the other structured fields
  (e.g. each investigator's `current_state`/`files_to_touch`), build it in the SAME python pass —
  you already have the parsed object.
- This also works for a foreground `Agent` whose final text you saved, and for resuming from a
  killed run via the `agent-*.jsonl` transcripts.

## Verification
- `grep -c '\\n' the_doc.md` → must be 0 (no literal backslash-n leaked).
- `head` the file: the markdown header/structure renders as real newlines, not one wrapped line.
- Byte size is plausibly the FULL field (compare to the `truncated N chars` hint — if your file is
  ~the truncation cap, you retyped the truncated view by mistake).
- `python3 -m json.tool "$OUT" >/dev/null` confirms the envelope is valid JSON before extracting.

## Example (real run)
A 4-investigator + synthesis Workflow returned a large `next_prompt_markdown` (~28KB, a full
paste-ready next-session prompt) plus four per-issue findings objects. The notification truncated at
~35k tokens (roughly line 100 of 170). Instead of retyping the prompt, I `json.load`-ed the
`tasks/<task-id>.output` envelope, wrote `result.synthesis.next_prompt_markdown` to the handoff doc
(with a prepended provenance header) AND built a second evidence doc from `result.findings` in the
same pass. Verified `grep -c '\n'` = 0 and the header rendered. Hand-retranscription would have
dropped a large fraction (~40%) of the prompt and risked literal-`\n` leakage.

## Notes
- The output file lives under `/private/tmp/.../<session>/tasks/<task-id>.output` — ephemeral; extract
  before it's cleaned up, and copy it into `docs/` (e.g. `docs/reviews/` or `docs/analysis/`) if you
  want durable provenance.
- See also: `flatten-workflow-parallel-arrays-before-collecting`,
  `workflow-standalone-schema-agent-crash-and-args-string` (other Workflow-mechanics traps),
  `claude-code-transcript-token-dedup-by-message-id` (reading agent transcripts directly).
