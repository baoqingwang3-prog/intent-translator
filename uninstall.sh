#!/usr/bin/env sh
set -eu

target_host="auto"
destination=""
purge_data="false"
confirm_purge=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    --host) target_host="$2"; shift 2 ;;
    --destination) destination="$2"; shift 2 ;;
    --purge-data) purge_data="true"; shift ;;
    --confirm-purge) confirm_purge="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

root_for_host() {
  case "$1" in
    codex) printf '%s\n' "${CODEX_HOME:-$HOME/.codex}/skills" ;;
    claude) printf '%s\n' "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills" ;;
    cursor) printf '%s\n' "$HOME/.cursor/skills" ;;
    gemini) printf '%s\n' "$HOME/.gemini/skills" ;;
    copilot) printf '%s\n' "$HOME/.copilot/skills" ;;
    opencode) printf '%s\n' "${XDG_CONFIG_HOME:-$HOME/.config}/opencode/skills" ;;
    shared) printf '%s\n' "$HOME/.agents/skills" ;;
  esac
}

case "$target_host" in
  auto|codex|claude|cursor|gemini|copilot|opencode|shared|all) ;;
  *) echo "Unsupported host: $target_host" >&2; exit 2 ;;
esac

if [ -n "$destination" ]; then
  targets="$destination"
elif [ "$target_host" = "all" ] || [ "$target_host" = "auto" ]; then
  targets="$(root_for_host codex)
$(root_for_host claude)
$(root_for_host cursor)
$(root_for_host gemini)
$(root_for_host copilot)
$(root_for_host opencode)
$(root_for_host shared)"
else
  targets=$(root_for_host "$target_host")
fi

printf '%s\n' "$targets" | while IFS= read -r target_root; do
  [ -n "$target_root" ] || continue
  destination_path="$target_root/intent-translator"
  case "$destination_path" in
    */intent-translator) ;;
    *) echo "Refusing to remove unexpected path: $destination_path" >&2; exit 3 ;;
  esac
  if [ -d "$destination_path" ]; then
    rm -rf -- "$destination_path"
    echo "Removed Skill: $destination_path"
  fi
done

if [ "$purge_data" = "true" ]; then
  [ "$confirm_purge" = "DELETE-LOCAL-DATA" ] || {
    echo "Purging profile and memory requires --confirm-purge DELETE-LOCAL-DATA" >&2
    exit 4
  }
  data_path="$HOME/.intent-translator"
  case "$data_path" in
    */.intent-translator) rm -rf -- "$data_path" ;;
    *) echo "Refusing to remove unexpected data path: $data_path" >&2; exit 5 ;;
  esac
  echo "Removed local profile and memory: $data_path"
else
  echo "Local profile and memory were preserved."
fi
