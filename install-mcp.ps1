[CmdletBinding()]
param(
    [string]$RuntimeRoot,
    [switch]$Replace,
    [switch]$ConfigureCodex
)

$ErrorActionPreference = "Stop"
$utf8 = [Text.UTF8Encoding]::new($false)
$OutputEncoding = $utf8
[Console]::InputEncoding = $utf8
[Console]::OutputEncoding = $utf8
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$userHome = [Environment]::GetFolderPath("UserProfile")
if (-not $RuntimeRoot) { $RuntimeRoot = Join-Path $userHome ".intent-translator\mcp" }
$venv = Join-Path $RuntimeRoot "venv"
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { $python = Get-Command python3 -ErrorAction SilentlyContinue }
if (-not $python) { throw "Python 3.10+ is required." }

if ((Test-Path -LiteralPath $venv) -and $Replace) {
    $resolvedRuntime = [IO.Path]::GetFullPath($RuntimeRoot)
    $resolvedVenv = [IO.Path]::GetFullPath($venv)
    if (-not $resolvedVenv.StartsWith($resolvedRuntime, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to replace a venv outside the runtime root: $resolvedVenv"
    }
    Remove-Item -LiteralPath $venv -Recurse -Force
}
if (-not (Test-Path -LiteralPath (Join-Path $venv "Scripts\python.exe"))) {
    New-Item -ItemType Directory -Path $RuntimeRoot -Force | Out-Null
    & $python.Source -m venv $venv
}

$venvPython = Join-Path $venv "Scripts\python.exe"
& $venvPython -m pip install --disable-pip-version-check --upgrade $PSScriptRoot

$skillDir = Join-Path $userHome ".codex\skills\intent-translator"
$configDir = Join-Path $userHome ".intent-translator\mcp-configs"
$command = Join-Path $venv "Scripts\intent-translator-mcp.exe"
& $venvPython -m intent_translator_mcp.config --host all --command $command --skill-dir $skillDir --output-dir $configDir

if ($ConfigureCodex) {
    $codexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $userHome ".codex" }
    $codexConfig = Join-Path $codexHome "config.toml"
    $snippet = Get-Content -LiteralPath (Join-Path $configDir "codex-mcp.toml") -Raw
    $existing = if (Test-Path -LiteralPath $codexConfig) { Get-Content -LiteralPath $codexConfig -Raw } else { "" }
    if ($existing -match '(?m)^\[mcp_servers\.intent-translator\]') {
        throw "Codex already has an intent-translator MCP entry. Update it manually from $configDir."
    }
    New-Item -ItemType Directory -Path (Split-Path -Parent $codexConfig) -Force | Out-Null
    Add-Content -LiteralPath $codexConfig -Value ("`n" + $snippet) -Encoding utf8
    Write-Host "Configured Codex MCP in $codexConfig"
}

& $venvPython -c "from intent_translator_mcp.server import mcp; print('MCP import smoke test passed')"
Write-Host "Installed MCP runtime to $RuntimeRoot"
Write-Host "Generated host configurations in $configDir"
