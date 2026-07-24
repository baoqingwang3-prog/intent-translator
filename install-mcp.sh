#!/bin/sh
set -eu
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

runtime_root="${INTENT_TRANSLATOR_RUNTIME:-$HOME/.intent-translator/mcp}"
python_bin="${PYTHON:-python3}"
venv="$runtime_root/venv"
repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

"$python_bin" -c 'import sys; raise SystemExit(sys.version_info < (3, 10))'
mkdir -p "$runtime_root"
if [ ! -x "$venv/bin/python" ]; then
  "$python_bin" -m venv "$venv"
fi
"$venv/bin/python" -m pip install --disable-pip-version-check --upgrade "$repo_dir"
skill_dir="$HOME/.agents/skills/intent-translator"
config_dir="$HOME/.intent-translator/mcp-configs"
"$venv/bin/python" -m intent_translator_mcp.config \
  --host all --command "$venv/bin/intent-translator-mcp" --skill-dir "$skill_dir" --output-dir "$config_dir"
printf 'Installed MCP runtime to %s\nGenerated host configurations in %s\n' "$runtime_root" "$config_dir"
