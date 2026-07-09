#!/usr/bin/env bash
set -euo pipefail

# install.sh — link this repo's skill(s) into the AI coding tools on this machine.
#
# A skill is a folder containing SKILL.md. "Installing" links that folder into each
# tool's skills directory (symlink, so edits are live). This repo ships the Cerberus
# skill (cerberus/SKILL.md).
#
# Usage:
#   ./install.sh                    Install globally for detected tools (Claude Code, Codex, OpenCode)
#   ./install.sh --project DIR      Also install into DIR/.cursor/skills (covers Cursor)
#   ./install.sh -y                 Don't prompt before replacing
#   REPO_URL=<git-url> ./install.sh Clone/update into a cache, then link from there
#
# Skills directories:
#   Claude Code  global ~/.claude/skills    project .claude/skills
#   Codex CLI    global ~/.codex/skills     project .codex/skills
#   OpenCode     global ~/.config/opencode/skills
#   Cursor       (no global dir)            project .cursor/skills

PROJECT_DIR=""
ASSUME_YES="${ASSUME_YES:-0}"
GLOBAL_TARGETS=""

while [ $# -gt 0 ]; do
  case "$1" in
    --project)   PROJECT_DIR="${2:-}"; shift 2 ;;
    --project=*) PROJECT_DIR="${1#*=}"; shift ;;
    -y|--yes)    ASSUME_YES=1; shift ;;
    -h|--help)   grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

have() { command -v "$1" >/dev/null 2>&1; }

# --- Resolve source root (live checkout, or persistent clone) ---
if [ -n "${REPO_URL:-}" ]; then
  CACHE_BASE="${XDG_CACHE_HOME:-$HOME/.cache}/ai-skills"
  repo_name="$(basename "${REPO_URL%.git}")"
  CLONE_DIR="$CACHE_BASE/$repo_name"
  mkdir -p "$CACHE_BASE"
  if [ -d "$CLONE_DIR/.git" ]; then
    echo "Updating clone in $CLONE_DIR"
    git -C "$CLONE_DIR" pull --ff-only
  else
    echo "Cloning $REPO_URL into $CLONE_DIR"
    git clone "$REPO_URL" "$CLONE_DIR"
  fi
  SRC_ROOT="$CLONE_DIR"
else
  SRC_ROOT="$(cd "$(dirname "$0")" && pwd)"
fi

# --- Detect installed tools (global targets) ---
if have claude || [ -d "$HOME/.claude" ]; then
  GLOBAL_TARGETS="$GLOBAL_TARGETS $HOME/.claude/skills"
fi
if have codex || [ -d "$HOME/.codex" ]; then
  GLOBAL_TARGETS="$GLOBAL_TARGETS $HOME/.codex/skills"
fi
OPENCODE_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/opencode"
if have opencode || [ -d "$OPENCODE_DIR" ]; then
  GLOBAL_TARGETS="$GLOBAL_TARGETS $OPENCODE_DIR/skills"
fi

# --- Link one skill folder into one target dir ---
link_skill() {
  src="$1"; targets_dir="$2"
  name="$(basename "$src")"
  dest="$targets_dir/$name"
  mkdir -p "$targets_dir"
  if [ -e "$dest" ] || [ -L "$dest" ]; then
    if [ "$ASSUME_YES" != "1" ]; then
      printf 'Replace existing "%s" in %s? [Y/n] ' "$name" "$targets_dir"
      if [ -r /dev/tty ]; then read -r reply </dev/tty; else reply="Y"; fi
      case "${reply:-Y}" in [nN]*) echo "  skipped $dest"; return 0 ;; esac
    fi
    rm -rf "$dest"
  fi
  ln -s "$src" "$dest"
  echo "  linked $dest -> $src"
}

# --- Find every skill (dir containing SKILL.md) and install it ---
find "$SRC_ROOT" -maxdepth 2 -name SKILL.md -not -path '*/.git/*' -print \
  | while IFS= read -r skillmd; do
      skill="$(cd "$(dirname "$skillmd")" && pwd)"
      echo "Installing skill: $(basename "$skill")"
      for t in $GLOBAL_TARGETS; do link_skill "$skill" "$t"; done
      if [ -n "$PROJECT_DIR" ]; then
        link_skill "$skill" "$PROJECT_DIR/.cursor/skills"
        # Optional: uncomment to also install project-scoped for Claude Code / Codex
        # link_skill "$skill" "$PROJECT_DIR/.claude/skills"
        # link_skill "$skill" "$PROJECT_DIR/.codex/skills"
      fi
    done

echo ""

if [ -z "$GLOBAL_TARGETS" ] && [ -z "$PROJECT_DIR" ]; then
  echo "No supported AI tools detected (Claude Code / Codex / OpenCode)."
  echo "Cursor is project-scoped: re-run with --project /path/to/your/project"
elif [ -z "$PROJECT_DIR" ]; then
  echo "Cursor skipped (no global dir). Install per project with: --project /path/to/your/project"
fi
