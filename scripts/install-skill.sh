#!/usr/bin/env bash
# Install the `kube` skill for Claude Code by symlinking it out of this repo,
# so that `git pull` updates the skill, the runbook and the CLI together.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
src="$repo_root/skills/kube"
dest="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}/kube"

if [ ! -f "$src/SKILL.md" ]; then
  echo "error: $src/SKILL.md not found" >&2
  exit 1
fi

mkdir -p "$(dirname "$dest")"

if [ -L "$dest" ]; then
  current="$(readlink "$dest")"
  if [ "$current" = "$src" ]; then
    echo "already installed: $dest -> $src"
    exit 0
  fi
  echo "replacing existing symlink: $dest -> $current"
  rm "$dest"
elif [ -e "$dest" ]; then
  echo "error: $dest already exists and is not a symlink." >&2
  echo "Move it aside first, then re-run this script." >&2
  exit 1
fi

ln -s "$src" "$dest"
echo "installed: $dest -> $src"
echo
echo "Start a new Claude Code session and run /kube to check that it loads."
