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
EXC=(--exclude-dir=.git --exclude-dir=.githooks --exclude=leak_scan.sh --exclude=CONTRIBUTING.md --exclude=.leakterms --exclude=.leakfigs --exclude=.leakdomains)

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
# Fail-closed on absence. `.leakterms` going missing is invisible; this one must not be.
if [ ! -f .leakdomains ]; then
  echo "LEAK GATE: .leakdomains is missing. It is a TRACKED file and its absence means the" >&2
  echo "  industry-vocabulary half of this gate did not run. Restore it (git checkout" >&2
  echo "  -- .leakdomains) rather than deleting the check that noticed." >&2
  exit 1
fi
while IFS= read -r t; do
  [ -z "$t" ] && continue
  case "$t" in \#*) continue;; esac
  out=$(grep -rnIiE "${EXC[@]}" -- "$t" . 2>/dev/null | sed '/^$/d')
  if [ -n "$out" ]; then printf '%s\n' "$out" | head -10; echo "  ^ industry vocabulary: $t"; echo; fail=1; fi
done < .leakdomains

if [ "$fail" -ne 0 ]; then
  echo "LEAK GATE: candidate client/PII identifiers found (above). Sanitize, or exclude a false positive, before publishing." >&2
  exit 1
fi
echo "LEAK GATE: clean"
exit 0
