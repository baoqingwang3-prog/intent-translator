[CmdletBinding()]
param(
    [string]$RuntimeRoot,
    [string]$HomeDirectory,
    [string]$ConfigDir,
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
$userHome = if ($HomeDirectory) { [IO.Path]::GetFullPath($HomeDirectory) } else { [Environment]::GetFolderPath("UserProfile") }
if (-not $RuntimeRoot) { $RuntimeRoot = Join-Path $userHome ".intent-translator\mcp" }
if (-not $ConfigDir) { $ConfigDir = Join-Path $userHome ".intent-translator\mcp-configs" }
$version = (Get-Content -LiteralPath (Join-Path $PSScriptRoot "VERSION") -Raw).Trim()
if ($version -notmatch '^\d+\.\d+\.\d+(?:(?:a|b|rc)\d+|-[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)*)?(?:\.post\d+)?(?:\.dev\d+)?(?:\+[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)*)?$') { throw "Invalid VERSION: $version" }
$versionRoot = Join-Path $RuntimeRoot (Join-Path "runtimes" $version)
$venv = Join-Path $versionRoot "venv"
if (
    [Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT -and
    [IO.Path]::GetFullPath($versionRoot).Length -gt 120
) {
    throw "MCP runtime path is too long for some Windows dependencies. Choose a shorter -RuntimeRoot, such as C:\it-mcp."
}
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { $python = Get-Command python3 -ErrorAction SilentlyContinue }
if (-not $python) { throw "Python 3.10+ is required." }

if ((Test-Path -LiteralPath $versionRoot) -and $Replace) {
    $resolvedRuntime = [IO.Path]::GetFullPath($RuntimeRoot)
    $resolvedVersion = [IO.Path]::GetFullPath($versionRoot)
    if (-not $resolvedVersion.StartsWith($resolvedRuntime, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to replace a version outside the runtime root: $resolvedVersion"
    }
    Remove-Item -LiteralPath $versionRoot -Recurse -Force
}
if (-not (Test-Path -LiteralPath (Join-Path $venv "Scripts\python.exe"))) {
    New-Item -ItemType Directory -Path $versionRoot -Force | Out-Null
    & $python.Source -m venv $venv
}

$venvPython = Join-Path $venv "Scripts\python.exe"
$runtimeHealthy = $false
if (-not $Replace -and (Test-Path -LiteralPath $venvPython)) {
    & $venvPython -c "import importlib.util as u, importlib.metadata as m; raise SystemExit(u.find_spec('intent_translator_mcp') is None or m.version('intent-translator-mcp') != '$version')"
    $runtimeHealthy = $LASTEXITCODE -eq 0
}
if ($runtimeHealthy) {
    Write-Host "Reusing healthy MCP runtime $version at $versionRoot"
} else {
    & $venvPython -m pip install --disable-pip-version-check --retries 5 --timeout 60 --upgrade $PSScriptRoot
    if ($LASTEXITCODE -ne 0) { throw "Failed to install MCP package into $versionRoot" }
}

$command = Join-Path $venv "Scripts\intent-translator-mcp.exe"
& $venvPython -m intent_translator_mcp.config --host all --command $command --home $userHome --output-dir $ConfigDir
if ($LASTEXITCODE -ne 0) { throw "Failed to generate MCP host configurations" }

& $venvPython -c "from intent_translator_mcp.server import mcp; print('MCP import smoke test passed')"
if ($LASTEXITCODE -ne 0) { throw "MCP import smoke test failed" }

$state = @{ version = $version; runtime = $versionRoot; command = $command; installed_at = [DateTime]::UtcNow.ToString('o') }
[IO.File]::WriteAllText((Join-Path $RuntimeRoot "current.json"), ($state | ConvertTo-Json), $utf8)

if ($ConfigureCodex) {
    & $venvPython -m intent_translator_mcp.host_registration repair --host codex --home $userHome
    $registrationExit = $LASTEXITCODE
    if ($registrationExit -eq 3) {
        Write-Warning "Codex is running, so its MCP configuration was not changed."
        Write-Host "After closing Codex, run:"
        Write-Host "& '$venvPython' -m intent_translator_mcp.host_registration repair --host codex --home '$userHome'"
    } elseif ($registrationExit -ne 0) {
        throw "Failed to register the MCP runtime with Codex by using the native Codex CLI"
    }
}

Write-Host "Installed MCP runtime $version to $versionRoot"
Write-Host "Generated host configurations in $ConfigDir"
