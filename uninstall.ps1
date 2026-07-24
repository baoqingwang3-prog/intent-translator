[CmdletBinding()]
param(
    [ValidateSet("Auto", "Codex", "Claude", "Cursor", "Gemini", "Copilot", "OpenCode", "Shared", "All")]
    [string]$TargetHost = "Auto",
    [string]$Destination,
    [string]$DataRoot,
    [switch]$PurgeData,
    [string]$ConfirmPurge = ""
)

$ErrorActionPreference = "Stop"
$userHome = [Environment]::GetFolderPath("UserProfile")
$localAppData = if ($env:LOCALAPPDATA) { $env:LOCALAPPDATA } else { Join-Path $userHome "AppData\Local" }
$hostRoots = [ordered]@{
    Codex = Join-Path $(if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $userHome ".codex" }) "skills"
    Claude = Join-Path $(if ($env:CLAUDE_CONFIG_DIR) { $env:CLAUDE_CONFIG_DIR } else { Join-Path $userHome ".claude" }) "skills"
    Cursor = Join-Path $userHome ".cursor\skills"
    Gemini = Join-Path $userHome ".gemini\skills"
    Copilot = Join-Path $userHome ".copilot\skills"
    OpenCode = Join-Path $localAppData "opencode\skills"
    Shared = Join-Path $userHome ".agents\skills"
}

$targets = [System.Collections.Generic.List[string]]::new()
if ($Destination) { $targets.Add($Destination) }
elseif ($TargetHost -eq "All") { foreach ($root in $hostRoots.Values) { $targets.Add($root) } }
elseif ($TargetHost -ne "Auto") { $targets.Add($hostRoots[$TargetHost]) }
else { foreach ($root in $hostRoots.Values) { if (Test-Path -LiteralPath (Join-Path $root "intent-translator")) { $targets.Add($root) } } }

foreach ($targetRoot in @($targets | Select-Object -Unique)) {
    $rootFull = [IO.Path]::GetFullPath($targetRoot).TrimEnd('\')
    $destinationPath = [IO.Path]::GetFullPath((Join-Path $targetRoot "intent-translator"))
    if ((Split-Path -Parent $destinationPath).TrimEnd('\') -ne $rootFull -or (Split-Path -Leaf $destinationPath) -ne "intent-translator") {
        throw "Refusing to remove unexpected path: $destinationPath"
    }
    if (Test-Path -LiteralPath $destinationPath) {
        Remove-Item -LiteralPath $destinationPath -Recurse -Force
        Write-Host "Removed Skill: $destinationPath"
    }
}

if ($PurgeData) {
    if ($ConfirmPurge -ne "DELETE-LOCAL-DATA") {
        throw "Purging profile and memory requires -ConfirmPurge DELETE-LOCAL-DATA"
    }
    $dataPath = [IO.Path]::GetFullPath($(if ($DataRoot) { $DataRoot } else { Join-Path $userHome ".intent-translator" }))
    if ((Split-Path -Leaf $dataPath) -ne ".intent-translator") {
        throw "Refusing to remove unexpected data path: $dataPath"
    }
    if (Test-Path -LiteralPath $dataPath) {
        Remove-Item -LiteralPath $dataPath -Recurse -Force
        Write-Host "Removed local profile and memory: $dataPath"
    }
} else {
    Write-Host "Local profile and memory were preserved."
}
