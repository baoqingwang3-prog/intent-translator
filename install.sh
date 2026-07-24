#!/usr/bin/env sh
set -eu

target_host="auto"
destination=""
replace="false"
skip_profile="false"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --host)
      target_host="$2"
      shift 2
      ;;
    --destination)
      destination="$2"
      shift 2
      ;;
    --replace)
      replace="true"
      shift
      ;;
    --skip-profile)
      skip_profile="true"
      shift
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

case "$target_host" in
  auto|codex|claude|cursor|gemini|copilot|opencode|shared|all) ;;
  *)
    echo "--host must be auto, codex, claude, cursor, gemini, copilot, opencode, shared, or all" >&2
    exit 2
    ;;
esac

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
source_dir="$script_dir/skills/intent-translator"
if [ ! -f "$source_dir/SKILL.md" ]; then
  echo "Skill source not found: $source_dir" >&2
  exit 1
fi

codex_home="${CODEX_HOME:-$HOME/.codex}"
claude_home="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
cursor_home="$HOME/.cursor"
gemini_home="$HOME/.gemini"
copilot_home="$HOME/.copilot"
opencode_home="${XDG_CONFIG_HOME:-$HOME/.config}/opencode"
shared_home="$HOME/.agents"

root_for_host() {
  case "$1" in
    codex) printf '%s\n' "$codex_home/skills" ;;
    claude) printf '%s\n' "$claude_home/skills" ;;
    cursor) printf '%s\n' "$cursor_home/skills" ;;
    gemini) printf '%s\n' "$gemini_home/skills" ;;
    copilot) printf '%s\n' "$copilot_home/skills" ;;
    opencode) printf '%s\n' "$opencode_home/skills" ;;
    shared) printf '%s\n' "$shared_home/skills" ;;
  esac
}

targets=""
if [ -n "$destination" ]; then
  targets="$destination"
elif [ "$target_host" = "all" ]; then
  targets="$(root_for_host codex)
$(root_for_host claude)
$(root_for_host cursor)
$(root_for_host gemini)
$(root_for_host copilot)
$(root_for_host opencode)
$(root_for_host shared)"
elif [ "$target_host" != "auto" ]; then
  targets=$(root_for_host "$target_host")
else
  for pair in "codex:$codex_home" "claude:$claude_home" "cursor:$cursor_home" "gemini:$gemini_home" "copilot:$copilot_home" "opencode:$opencode_home"; do
    name=${pair%%:*}
    config_home=${pair#*:}
    if [ -d "$config_home" ]; then
      root=$(root_for_host "$name")
      if [ -n "$targets" ]; then
        targets="$targets
$root"
      else
        targets="$root"
      fi
    fi
  done
  if [ -z "$targets" ]; then
    targets=$(root_for_host shared)
  fi
fi

printf '%s\n' "$targets" | while IFS= read -r target_root; do
  [ -n "$target_root" ] || continue
  destination_path="$target_root/intent-translator"
  if [ -f "$destination_path/SKILL.md" ] && [ "$replace" != "true" ]; then
    echo "Skill already exists at $destination_path. Re-run with --replace to overwrite it." >&2
    exit 3
  fi
  mkdir -p "$destination_path"
  (
    cd "$source_dir"
    find . -type f ! -path '*/__pycache__/*' -print
  ) | while IFS= read -r relative; do
    target_file="$destination_path/${relative#./}"
    mkdir -p "$(dirname "$target_file")"
    cp "$source_dir/${relative#./}" "$target_file"
  done
  echo "Installed intent-translator to $destination_path"
done

if [ "$skip_profile" = "false" ]; then
  python_command=""
  if command -v python3 >/dev/null 2>&1; then
    python_command="python3"
  elif command -v python >/dev/null 2>&1; then
    python_command="python"
  fi

  if [ -n "$python_command" ]; then
    profile_path="${INTENT_TRANSLATOR_PROFILE:-$HOME/.intent-translator/profile.json}"
    if [ -f "$profile_path" ]; then
      "$python_command" "$source_dir/scripts/init_profile.py" validate --profile "$profile_path"
    else
      "$python_command" "$source_dir/scripts/init_profile.py" init --profile "$profile_path"
    fi
  else
    echo "Warning: Python 3.10+ was not found; profile initialization was skipped." >&2
  fi
fi
