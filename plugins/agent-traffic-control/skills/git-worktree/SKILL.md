---
name: git-worktree
description: |
  Create, list, switch and clean up git worktrees — a second isolated checkout for parallel work
  or a pull request review. Runs the bundled `skills/git-worktree/scripts/worktree-manager.sh`,
  which also copies `.env` in, gitignores the dir and trusts mise or direnv. Not a bare `git
  worktree add`.
---
# Git Worktree Manager

This skill provides a unified interface for managing Git worktrees across your development workflow. Whether you're reviewing PRs in isolation or working on features in parallel, this skill handles all the complexity.

## What This Skill Does

- **Create worktrees** from main branch with clear branch names
- **List worktrees** with current status
- **Switch between worktrees** for parallel work
- **Clean up completed worktrees** automatically
- **Interactive confirmations** at each step
- **Automatic .gitignore management** for worktree directory
- **Automatic .env file copying** from main repo to new worktrees
- **Automatic dev tool trusting** for mise and direnv configs with review-safe guardrails

## Resolve the manager script first (once per shell)

Every command below runs `"$WTM"`. Resolve it once:

```bash
# Three roots, in order. A plugin install creates NEITHER of the first two:
# CLAUDE_PLUGIN_ROOT is frequently unset in the shell a step actually runs in, and
# ~/.claude/skills/agent-traffic-control/ does not exist — the plugin lives under
# ~/.claude/plugins/cache/<marketplace>/agent-traffic-control/<version>/.
REL="skills/git-worktree/scripts/worktree-manager.sh"
WTM="${CLAUDE_PLUGIN_ROOT:+${CLAUDE_PLUGIN_ROOT}/$REL}"
[ -f "$WTM" ] || WTM="$HOME/.claude/skills/agent-traffic-control/$REL"
# Rank on the VERSION segment, not the whole path: the marketplace name precedes the
# version, so a plain `sort -V` over full paths would let aaa-mkt/2.5.0 lose to
# zzz-mkt/1.0.0. Here the version sits at NF-4 because the script nests two levels
# deeper than a flat plugin layout. Use `find`, not a glob — zsh fails a non-matching
# glob at expansion time, before 2>/dev/null can apply.
[ -f "$WTM" ] || WTM="$(find -L "$HOME/.claude/plugins/cache" -mindepth 7 -maxdepth 7 \
    -path "*/agent-traffic-control/*/$REL" 2>/dev/null \
  | awk -F/ '{print $(NF-4)"\t"$0}' | sort -V -k1,1 | tail -1 | cut -f2-)"

if [ ! -f "$WTM" ]; then
  echo "worktree-manager.sh: not found — tried \$CLAUDE_PLUGIN_ROOT/$REL," \
       "\$HOME/.claude/skills/agent-traffic-control/$REL, and" \
       "\$HOME/.claude/plugins/cache/*/agent-traffic-control/*/$REL"
fi
```

Say **"not found — tried \<paths\>"**, never a bare "not installed": a failed lookup is
not evidence about install state. Without this block the commands below expanded to
`/skills/git-worktree/scripts/worktree-manager.sh` on any plugin-scope machine and died
with a bare `exit 127` naming no root at all.

## CRITICAL: Always Use the Manager Script

**NEVER call `git worktree add` directly.** Always use the `worktree-manager.sh` script.

The script handles critical setup that raw git commands don't:
1. Copies `.env`, `.env.local`, `.env.test`, etc. from main repo
2. Trusts dev tool configs with branch-aware safety rules:
   - mise: auto-trust only when unchanged from a trusted baseline branch
   - direnv: auto-allow only for trusted base branches; review worktrees stay manual
3. Ensures `.worktrees` is in `.gitignore`
4. Creates consistent directory structure

```bash
# ✅ CORRECT - Always use the script
bash "$WTM" create feature-name

# ❌ WRONG - Never do this directly
git worktree add .worktrees/feature-name -b feature-name main
```

## When to Use This Skill

Use this skill in these scenarios:

1. **Code Review (`/ce:review`)**: If NOT already on the target branch (PR branch or requested branch), offer worktree for isolated review
2. **Feature Work (`/ce:work`)**: Always ask if user wants parallel worktree or live branch work
3. **Parallel Development**: When working on multiple features simultaneously
4. **Cleanup**: After completing work in a worktree

## How to Use

### In Claude Code Workflows

The skill is automatically called from `/ce:review` and `/ce:work` commands:

```
# For review: offers worktree if not on PR branch
# For work: always asks - new branch or worktree?
```

### Manual Usage

You can also invoke the skill directly from bash:

```bash
# Create a new worktree (copies .env files automatically)
bash "$WTM" create feature-login

# List all worktrees
bash "$WTM" list

# Switch to a worktree
bash "$WTM" switch feature-login

# Copy .env files to an existing worktree (if they weren't copied)
bash "$WTM" copy-env feature-login

# Clean up completed worktrees
bash "$WTM" cleanup
```

## Commands

### `create <branch-name> [from-branch]`

Creates a new worktree with the given branch name.

**Options:**
- `branch-name` (required): The name for the new branch and worktree
- `from-branch` (optional): Base branch to create from (defaults to `main`)

**Example:**
```bash
bash "$WTM" create feature-login
```

**What happens:**
1. Checks if worktree already exists
2. Updates the base branch from remote
3. Creates new worktree and branch
4. **Copies all .env files from main repo** (.env, .env.local, .env.test, etc.)
5. **Trusts dev tool configs** with branch-aware safety rules:
   - trusted bases (`main`, `develop`, `dev`, `trunk`, `staging`, `release/*`) compare against themselves
   - other branches compare against the default branch
   - direnv auto-allow is skipped on non-trusted bases because `.envrc` can source unchecked files
6. Shows path for cd-ing to the worktree

### `list` or `ls`

Lists all available worktrees with their branches and current status.

**Example:**
```bash
bash "$WTM" list
```

**Output shows:**
- Worktree name
- Branch name
- Which is current (marked with ✓)
- Main repo status

### `switch <name>` or `go <name>`

Switches to an existing worktree and cd's into it.

**Example:**
```bash
bash "$WTM" switch feature-login
```

**Optional:**
- If name not provided, lists available worktrees and prompts for selection

### `cleanup` or `clean`

Interactively cleans up inactive worktrees with confirmation.

**Example:**
```bash
bash "$WTM" cleanup
```

**What happens:**
1. Lists all inactive worktrees
2. Asks for confirmation
3. Removes selected worktrees
4. Cleans up empty directories

## Workflow Examples

### Code Review with Worktree

```bash
# Claude Code recognizes you're not on the PR branch
# Offers: "Use worktree for isolated review? (y/n)"

# You respond: yes
# Script runs (copies .env files automatically):
bash "$WTM" create pr-123-feature-name

# You're now in isolated worktree for review with all env vars
cd .worktrees/pr-123-feature-name

# After review, return to main:
cd ../..
bash "$WTM" cleanup
```

### Parallel Feature Development

```bash
# For first feature (copies .env files):
bash "$WTM" create feature-login

# Later, start second feature (also copies .env files):
bash "$WTM" create feature-notifications

# List what you have:
bash "$WTM" list

# Switch between them as needed:
bash "$WTM" switch feature-login

# Return to main and cleanup when done:
cd .
bash "$WTM" cleanup
```

## Key Design Principles

### KISS (Keep It Simple, Stupid)

- **One manager script** handles all worktree operations
- **Simple commands** with sensible defaults
- **Interactive prompts** prevent accidental operations
- **Clear naming** using branch names directly

### Opinionated Defaults

- Worktrees always created from **main** (unless specified)
- Worktrees stored in **.worktrees/** directory
- Branch name becomes worktree name
- **.gitignore** automatically managed

### Safety First

- **Confirms before creating** worktrees
- **Confirms before cleanup** to prevent accidental removal
- **Won't remove current worktree**
- **Clear error messages** for issues

## Integration with Workflows

### `/ce:review`

Instead of always creating a worktree:

```
1. Check current branch
2. If ALREADY on target branch (PR branch or requested branch) → stay there, no worktree needed
3. If DIFFERENT branch than the review target → offer worktree:
   "Use worktree for isolated review? (y/n)"
   - yes → call git-worktree skill
   - no → proceed with PR diff on current branch
```

### `/ce:work`

Always offer choice:

```
1. Ask: "How do you want to work?
   1. New branch on current worktree (live work)
   2. Worktree (parallel work)"

2. If choice 1 → create new branch normally
3. If choice 2 → call git-worktree skill to create from main
```

## Troubleshooting

### "Worktree already exists"

If you see this, the script will ask if you want to switch to it instead.

### "Cannot remove worktree: it is the current worktree"

Switch out of the worktree first (to main repo), then cleanup:

```bash
cd $(git rev-parse --show-toplevel)
bash "$WTM" cleanup
```

### Lost in a worktree?

See where you are:

```bash
bash "$WTM" list
```

### .env files missing in worktree?

If a worktree was created without .env files (e.g., via raw `git worktree add`), copy them:

```bash
bash "$WTM" copy-env feature-name
```

Navigate back to main:

```bash
cd $(git rev-parse --show-toplevel)
```

## Technical Details

### Directory Structure

```
.worktrees/
├── feature-login/          # Worktree 1
│   ├── .git
│   ├── app/
│   └── ...
├── feature-notifications/  # Worktree 2
│   ├── .git
│   ├── app/
│   └── ...
└── ...

.gitignore (updated to include .worktrees)
```

### How It Works

- Uses `git worktree add` for isolated environments
- Each worktree has its own branch
- Changes in one worktree don't affect others
- Share git history with main repo
- Can push from any worktree

### Performance

- Worktrees are lightweight (just file system links)
- No repository duplication
- Shared git objects for efficiency
- Much faster than cloning or stashing/switching

## Reference-only siblings in this toolkit

These carry `disable-model-invocation: true`. They never appear in the skill
listing and the Skill tool refuses them, so the only way in is to open the file
with Read when one of these matches what you are looking at.

- [`main-bash-cwd-persists-nested-worktree`](../main-bash-cwd-persists-nested-worktree/SKILL.md) — a worktree got created at the wrong filesystem path because the main agent's bash cwd persisted
- [`shell-pinned-to-deleted-worktree-cwd-blocks-git`](../shell-pinned-to-deleted-worktree-cwd-blocks-git/SKILL.md) — every shell command now fails `Unable to read current working directory` after a worktree was removed
- [`git-auto-maintenance-recurring-worktree-index-lock`](../git-auto-maintenance-recurring-worktree-index-lock/SKILL.md) — `index.lock: File exists` keeps coming back after you delete it
- [`worktree-index-corrupt-async-post-commit-hook`](../worktree-index-corrupt-async-post-commit-hook/SKILL.md) — `fatal: unable to read <sha>` in worktree B right after committing in worktree A
- [`worktree-does-not-isolate-shared-installed-artefacts`](../worktree-does-not-isolate-shared-installed-artefacts/SKILL.md) — a worktree isolates the source tree and nothing else — venvs, caches and installed packages stay shared
- [`worktree-historical-test-replay-missing-dirs`](../worktree-historical-test-replay-missing-dirs/SKILL.md) — `pytest exit 4` replaying tests in a worktree checked out at an old commit
- [`pytest-editable-install-resolves-to-primary-checkout-not-worktree`](../pytest-editable-install-resolves-to-primary-checkout-not-worktree/SKILL.md) — an editable install makes `import <pkg>` resolve to the primary checkout, not your worktree
- [`flask-debug-cross-worktree-edit-stale`](../flask-debug-cross-worktree-edit-stale/SKILL.md) — the dev server keeps serving the old template after you edited it in another worktree
- [`async-doc-hook-autodocs-worktree-locks-branch-checkout`](../async-doc-hook-autodocs-worktree-locks-branch-checkout/SKILL.md) — `'<branch>' is already used by worktree at .../autodocs-<name>` from a background docs hook
