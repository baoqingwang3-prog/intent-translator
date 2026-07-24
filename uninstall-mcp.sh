#!/bin/sh
set -eu

runtime_root="${INTENT_TRANSLATOR_RUNTIME:-$HOME/.intent-translator/mcp}"
default_runtime="$HOME/.intent-translator/mcp"
config_dir="$HOME/.intent-translator/mcp-configs"
keep_configs=0
confirm_custom=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    --keep-configs) keep_configs=1 ;;
    --runtime) shift; runtime_root="${1:-}" ;;
    --confirm-custom) shift; confirm_custom="${1:-}" ;;
    *) printf 'Unknown option: %s\n' "$1" >&2; exit 2 ;;
  esac
  shift
done

if [ "$runtime_root" != "$default_runtime" ]; then
  case "$runtime_root" in */mcp) ;; *) printf 'Custom runtime path must end in /mcp\n' >&2; exit 2 ;; esac
  if [ "$confirm_custom" != "REMOVE-MCP-RUNTIME" ]; then
    printf 'Custom runtime removal requires --confirm-custom REMOVE-MCP-RUNTIME\n' >&2
    exit 2
  fi
fi

if [ -d "$runtime_root" ]; then
  rm -rf -- "$runtime_root"
  printf 'Removed MCP runtime: %s\n' "$runtime_root"
fi
if [ "$keep_configs" -eq 0 ] && [ -d "$config_dir" ]; then
  rm -rf -- "$config_dir"
  printf 'Removed generated MCP snippets: %s\n' "$config_dir"
fi
printf 'Profile and memory were preserved. Remove any host configuration you merged manually, then restart the host.\n'
