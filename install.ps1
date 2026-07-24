[CmdletBinding()]
param(
    [ValidateSet("Auto", "Codex", "Claude", "Cursor", "Gemini", "Copilot", "OpenCode", "Shared", "All")]
    [string]$TargetHost = "Auto",
    [string]$Destination,
    [switch]$Replace,
    [switch]$SkipProfile
)

$ErrorActionPreference = "Stop"
$source = Join-Path $PSScriptRoot "skills\intent-translator"
if (-not (Test-Path -LiteralPath (Join-Path $source "SKILL.md"))) {
    throw "Skill source not found: $source"
}

$userHome = [Environment]::GetFolderPath("UserProfile")
$codexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $userHome ".codex" }
$claudeHome = if ($env:CLAUDE_CONFIG_DIR) { $env:CLAUDE_CONFIG_DIR } else { Join-Path $userHome ".claude" }
$cursorHome = Join-Path $userHome ".cursor"
$geminiHome = Join-Path $userHome ".gemini"
$copilotHome = Join-Path $userHome ".copilot"
$localAppData = if ($env:LOCALAPPDATA) { $env:LOCALAPPDATA } else { Join-Path $userHome "AppData\Local" }
$openCodeHome = Join-Path $localAppData "opencode"
$sharedHome = Join-Path $userHome ".agents"

$hostRoots = [ordered]@{
    Codex = Join-Path $codexHome "skills"
    Claude = Join-Path $claudeHome "skills"
    Cursor = Join-Path $cursorHome "skills"
    Gemini = Join-Path $geminiHome "skills"
    Copilot = Join-Path $copilotHome "skills"
    OpenCode = Join-Path $openCodeHome "skills"
    Shared = Join-Path $sharedHome "skills"
}

$targets = [System.Collections.Generic.List[string]]::new()
if ($Destination) {
    $targets.Add($Destination)
} elseif ($TargetHost -eq "All") {
    foreach ($root in $hostRoots.Values) {
        $targets.Add($root)
    }
} elseif ($TargetHost -ne "Auto") {
    $targets.Add($hostRoots[$TargetHost])
} else {
    foreach ($name in @("Codex", "Claude", "Cursor", "Gemini", "Copilot", "OpenCode")) {
        $configHome = Split-Path -Parent $hostRoots[$name]
        if (Test-Path -LiteralPath $configHome) {
            $targets.Add($hostRoots[$name])
        }
    }
    if ($targets.Count -eq 0) {
        $targets.Add($hostRoots["Shared"])
    }
}

$uniqueTargets = @($targets | Select-Object -Unique)
foreach ($targetRoot in $uniqueTargets) {
    $destinationPath = Join-Path $targetRoot "intent-translator"
    if ((Test-Path -LiteralPath (Join-Path $destinationPath "SKILL.md")) -and -not $Replace) {
        throw "Skill already exists at $destinationPath. Re-run with -Replace to overwrite it."
    }
}

foreach ($targetRoot in $uniqueTargets) {
    $destinationPath = Join-Path $targetRoot "intent-translator"
    New-Item -ItemType Directory -Path $destinationPath -Force | Out-Null
    $sourceFiles = Get-ChildItem -LiteralPath $source -Recurse -File | Where-Object {
        $_.FullName -notmatch '[\\/]__pycache__[\\/]'
    }
    foreach ($file in $sourceFiles) {
        $relative = $file.FullName.Substring($source.Length + 1)
        $targetFile = Join-Path $destinationPath $relative
        $targetDirectory = Split-Path -Parent $targetFile
        New-Item -ItemType Directory -Path $targetDirectory -Force | Out-Null
        Copy-Item -LiteralPath $file.FullName -Destination $targetFile -Force
    }
    Write-Host "Installed intent-translator to $destinationPath"
}

if (-not $SkipProfile) {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) {
        $python = Get-Command python3 -ErrorAction SilentlyContinue
    }
    if ($python) {
        $profilePath = if ($env:INTENT_TRANSLATOR_PROFILE) {
            $env:INTENT_TRANSLATOR_PROFILE
        } else {
            Join-Path $userHome ".intent-translator\profile.json"
        }
        if (-not (Test-Path -LiteralPath $profilePath)) {
            & $python.Source (Join-Path $source "scripts\init_profile.py") init --profile $profilePath
        } else {
            & $python.Source (Join-Path $source "scripts\init_profile.py") validate --profile $profilePath
        }
    } else {
        Write-Warning "Python 3.10+ was not found; Skill files were installed but the local profile was not initialized."
    }
}
