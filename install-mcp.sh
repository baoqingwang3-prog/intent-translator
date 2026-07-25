#!/bin/sh
set -eu
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

intent_home="${INTENT_TRANSLATOR_HOME:-$HOME}"
runtime_root="${INTENT_TRANSLATOR_RUNTIME:-$intent_home/.intent-translator/mcp}"
config_dir="${INTENT_TRANSLATOR_CONFIG_DIR:-$intent_home/.intent-translator/mcp-configs}"
python_bin="${PYTHON:-python3}"
repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
version=$(tr -d '\r\n' < "$repo_dir/VERSION")
if ! printf '%s\n' "$version" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+((a|b|rc)[0-9]+|-[A-Za-z0-9]+([.-][A-Za-z0-9]+)*)?(\.post[0-9]+)?(\.dev[0-9]+)?(\+[A-Za-z0-9]+([.-][A-Za-z0-9]+)*)?$'; then
  printf 'Invalid VERSION: %s\n' "$version" >&2
  exit 2
fi
version_root="$runtime_root/runtimes/$version"
venv="$version_root/venv"

"$python_bin" -c 'import sys; raise SystemExit(sys.version_info < (3, 10))'
mkdir -p "$version_root"
if [ ! -x "$venv/bin/python" ]; then
  "$python_bin" -m venv "$venv"
fi
"$venv/bin/python" -m pip install --disable-pip-version-check --retries 5 --timeout 60 --upgrade "$repo_dir"
"$venv/bin/python" -m intent_translator_mcp.config \
  --host all --command "$venv/bin/intent-translator-mcp" --home "$intent_home" --output-dir "$config_dir"
"$venv/bin/python" -c "from intent_translator_mcp.server import mcp; print('MCP import smoke test passed')"
printf '{"version":"%s","runtime":"%s","command":"%s"}\n' "$version" "$version_root" "$venv/bin/intent-translator-mcp" > "$runtime_root/current.json"
printf 'Installed MCP runtime %s to %s\nGenerated host configurations in %s\n' "$version" "$version_root" "$config_dir"
