[CmdletBinding()]
param(
    [string]$RuntimeRoot,
    [switch]$KeepGeneratedConfigs,
    [switch]$KeepCodexConfig,
    [string]$ConfirmCustomRuntime = ""
)

$ErrorActionPreference = "Stop"
$userHome = [Environment]::GetFolderPath("UserProfile")
$defaultRuntime = Join-Path $userHome ".intent-translator\mcp"
if (-not $RuntimeRoot) { $RuntimeRoot = $defaultRuntime }
$runtimeFull = [IO.Path]::GetFullPath($RuntimeRoot)
$dataRoot = [IO.Path]::GetFullPath((Join-Path $userHome ".intent-translator"))
if ($runtimeFull -ne [IO.Path]::GetFullPath($defaultRuntime)) {
    if ((Split-Path -Leaf $runtimeFull) -ne "mcp" -or $ConfirmCustomRuntime -ne "REMOVE-MCP-RUNTIME") {
        throw "Custom runtime removal requires a path ending in 'mcp' and -ConfirmCustomRuntime REMOVE-MCP-RUNTIME"
    }
}

if (-not $KeepCodexConfig) {
    $codexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $userHome ".codex" }
    $codexConfig = Join-Path $codexHome "config.toml"
    if (Test-Path -LiteralPath $codexConfig) {
        $lines = @(Get-Content -LiteralPath $codexConfig -Encoding utf8)
        $result = [System.Collections.Generic.List[string]]::new()
        $skipping = $false
        $found = $false
        foreach ($line in $lines) {
            if ($line -match '^\[mcp_servers\.intent-translator(?:\.env)?\]$') {
                $skipping = $true
                $found = $true
                continue
            }
            if ($skipping -and $line -match '^\[') { $skipping = $false }
            if (-not $skipping) { $result.Add($line) }
        }
        if ($found) {
            $backup = "$codexConfig.bak-intent-translator-$(Get-Date -Format 'yyyyMMddTHHmmss')"
            Copy-Item -LiteralPath $codexConfig -Destination $backup
            Set-Content -LiteralPath $codexConfig -Value $result -Encoding utf8
            Write-Host "Removed Codex MCP entry; backup: $backup"
        }
    }
}

if (Test-Path -LiteralPath $runtimeFull) {
    Remove-Item -LiteralPath $runtimeFull -Recurse -Force
    Write-Host "Removed MCP runtime: $runtimeFull"
}

$configDir = Join-Path $dataRoot "mcp-configs"
if (-not $KeepGeneratedConfigs -and (Test-Path -LiteralPath $configDir)) {
    Remove-Item -LiteralPath $configDir -Recurse -Force
    Write-Host "Removed generated MCP snippets: $configDir"
}

Write-Host "Profile and memory were preserved. Restart or reload the agent host."
