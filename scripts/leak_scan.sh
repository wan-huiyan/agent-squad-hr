#!/usr/bin/env bash
# Public-safe leak gate. Flags likely client/PII identifiers by GENERIC PATTERN so
# nothing client-specific has to be committed here. Maintainer-specific names/brands
# go in a gitignored `.leakterms` (one grep -E regex per line), read at runtime.
#
# TWO TERM FILES, AND THE DIFFERENCE IS THE WHOLE POINT:
#   .leakterms    gitignored. YOUR client names, brands, project ids, username. Never
#                 committed -- so a CI checkout does not have it, and this gate silently
#                 degrades to the three generic patterns below. That is by design for
#                 secret-ish names, and it is also how v1.24.0's 129 occurrences of
#                 engagement residue passed a green gate before AND after removal.
#   .leakdomains  TRACKED. Industry vocabulary, spanning many sectors so the file names
#                 no single one. Committed precisely so CI reads it too. Missing file =
#                 hard failure, because "the denylist wasn't there" must never read as
#                 "clean" a second time.
#
# Usage: leak_scan.sh [repo_root]   ->   exit 0 = clean, 1 = candidate leak(s).
set -u
ROOT="${1:-.}"
cd "$ROOT" || exit 2
fail=0
# CONTRIBUTING.md was excluded here until v1.26.0, from when it only described the gate.
# It now carries the sector policy, which makes it the likeliest future home for an
# illustrative example using real industry vocabulary -- i.e. the one file most worth
# scanning was the one file exempt. It is clean today, so the exclusion simply goes.
# NOTE: --exclude matches on BASENAME, so each entry below exempts that filename in
# EVERY directory, not just the repo root.
EXC=(--exclude-dir=.git --exclude-dir=.githooks --exclude=leak_scan.sh --exclude=.leakterms --exclude=.leakfigs --exclude=.leakdomains)

scan() { # $1 regex  $2 label  [$3 grep -vE false-positive filter]
  local out
  out=$(grep -rnIE "${EXC[@]}" -- "$1" . 2>/dev/null)
  [ -n "${3:-}" ] && out=$(printf '%s\n' "$out" | grep -vE "$3")
  out=$(printf '%s\n' "$out" | sed '/^$/d')
  if [ -n "$out" ]; then printf '%s\n' "$out" | head -20; echo "  ^ $2"; echo; fail=1; fi
}

# --- reliable generic patterns (low false-positive; safe to enforce in CI) ---
scan '[A-Za-z0-9_]+__[cr]\b'                                   'Salesforce custom field (__c/__r)'
scan 'sk-[A-Za-z0-9]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}' 'API key / token'
scan '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'         'email address' 'noreply@|@example\.|example\.(com|org)|user@company|@your-|@company\.'
# NOTE: cloud paths (gs://…) and /Users|/home home paths are NOT enforced by default —
# these skill repos use placeholder paths (gs://your-project, /Users/me, /Users/jesse)
# heavily, so a generic pattern false-positives. Put a REAL bucket/username/project id
# in .leakterms (gitignored) to catch the specific ones instead.

if [ -f .leakterms ]; then
  while IFS= read -r t; do
    [ -z "$t" ] && continue
    case "$t" in \#*) continue;; esac
    out=$(grep -rnIiE "${EXC[@]}" -- "$t" . 2>/dev/null | sed '/^$/d')
    if [ -n "$out" ]; then printf '%s\n' "$out" | head -10; echo "  ^ custom term: $t"; echo; fail=1; fi
  done < .leakterms
fi

# --- tracked industry-vocabulary denylist (see .leakdomains for what it can't do) ---
# FAIL CLOSED. The invariant is not "the file exists" -- it is "the denylist RAN".
# Absence was the obvious way to break that; review found five more, each of which
# printed `LEAK GATE: clean` with planted vocabulary sitting in the tree:
#   empty file · comments only · a malformed regex (grep exits 2, stderr swallowed,
#   no output reads as no hits) · an unreadable file · a stripped final newline,
#   which silently drops the LAST pattern because `read` returns false on EOF.
# So: count what actually loaded, and check grep's exit code per pattern.
if [ ! -f .leakdomains ]; then
  echo "LEAK GATE: .leakdomains is missing. It is a TRACKED file and its absence means the" >&2
  echo "  industry-vocabulary half of this gate did not run. Restore it (git checkout" >&2
  echo "  -- .leakdomains) rather than deleting the check that noticed." >&2
  exit 1
fi
if [ ! -r .leakdomains ]; then
  echo "LEAK GATE: .leakdomains is not readable, so the industry-vocabulary half did not run." >&2
  exit 1
fi
npat=0
# `|| [ -n "$t" ]` re-enters the loop for a final line with no trailing newline.
while IFS= read -r t || [ -n "$t" ]; do
  t="${t%$'\r'}"                      # tolerate CRLF; a stray CR breaks \b anchoring
  [ -z "$t" ] && continue
  case "$t" in \#*) continue;; esac
  npat=$((npat + 1))
  out=$(grep -rnIiE "${EXC[@]}" -- "$t" . 2>/dev/null); rc=$?
  # grep: 0 = matched, 1 = no match, >=2 = the PATTERN ITSELF is unusable.
  if [ "$rc" -ge 2 ]; then
    echo "LEAK GATE: unusable pattern in .leakdomains, so it matched nothing: $t" >&2
    fail=1
    continue
  fi
  out=$(printf '%s\n' "$out" | sed '/^$/d')
  if [ -n "$out" ]; then printf '%s\n' "$out" | head -10; echo "  ^ industry vocabulary: $t"; echo; fail=1; fi
done < .leakdomains
if [ "$npat" -lt 1 ]; then
  echo "LEAK GATE: .leakdomains loaded 0 patterns (empty, or comments only), so the" >&2
  echo "  industry-vocabulary half of this gate did not run. That is the same silence" >&2
  echo "  this file exists to prevent -- restore the patterns rather than the file alone." >&2
  exit 1
fi

if [ "$fail" -ne 0 ]; then
  echo "LEAK GATE: candidate client/PII identifiers found (above). Sanitize, or exclude a false positive, before publishing." >&2
  exit 1
fi
echo "LEAK GATE: clean"
exit 0
