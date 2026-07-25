[CmdletBinding()]
param(
    [ValidateSet("Auto", "Codex", "Claude", "Cursor", "Gemini", "Copilot", "OpenCode", "Shared", "All")]
    [string]$TargetHost = "Auto",
    [string]$Destination,
    [switch]$Replace,
    [switch]$SkipProfile,
    [switch]$CheckOnly
)

$ErrorActionPreference = "Stop"

function Assert-DirectChildPath {
    param([string]$Root, [string]$Child)
    $rootFull = [IO.Path]::GetFullPath($Root).TrimEnd('\')
    $childFull = [IO.Path]::GetFullPath($Child)
    if ((Split-Path -Parent $childFull).TrimEnd('\') -ne $rootFull) {
        throw "Refusing filesystem operation outside target root: $childFull"
    }
}

$source = Join-Path $PSScriptRoot "skills\intent-translator"
if (-not (Test-Path -LiteralPath (Join-Path $source "SKILL.md"))) {
    throw "Skill source not found: $source"
}
if (-not (Test-Path -LiteralPath (Join-Path $source "VERSION"))) {
    throw "Skill version file not found: $source\VERSION"
}
$sourceVersion = (Get-Content -LiteralPath (Join-Path $source "VERSION") -Raw).Trim()

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
    foreach ($root in $hostRoots.Values) { $targets.Add($root) }
} elseif ($TargetHost -ne "Auto") {
    $targets.Add($hostRoots[$TargetHost])
} else {
    foreach ($name in @("Codex", "Claude", "Cursor", "Gemini", "Copilot", "OpenCode")) {
        $configHome = Split-Path -Parent $hostRoots[$name]
        if (Test-Path -LiteralPath $configHome) { $targets.Add($hostRoots[$name]) }
    }
    if ($targets.Count -eq 0) { $targets.Add($hostRoots["Shared"]) }
}

$uniqueTargets = @($targets | Select-Object -Unique)
foreach ($targetRoot in $uniqueTargets) {
    $destinationPath = Join-Path $targetRoot "intent-translator"
    $installedVersionPath = Join-Path $destinationPath "VERSION"
    $installedVersion = if (Test-Path -LiteralPath $installedVersionPath) {
        (Get-Content -LiteralPath $installedVersionPath -Raw).Trim()
    } elseif (Test-Path -LiteralPath (Join-Path $destinationPath "SKILL.md")) {
        "legacy-unversioned"
    } else {
        "not-installed"
    }
    Write-Host "intent-translator: installed=$installedVersion available=$sourceVersion target=$destinationPath"
    if ($CheckOnly) { continue }
    if ((Test-Path -LiteralPath (Join-Path $destinationPath "SKILL.md")) -and -not $Replace) {
        throw "Skill already exists at $destinationPath. Re-run with -Replace to upgrade it."
    }
}

if ($CheckOnly) { return }

foreach ($targetRoot in $uniqueTargets) {
    New-Item -ItemType Directory -Path $targetRoot -Force | Out-Null
    $destinationPath = Join-Path $targetRoot "intent-translator"
    $operationId = [Guid]::NewGuid().ToString("N")
    $stagePath = Join-Path $targetRoot ".intent-translator.stage.$operationId"
    $rollbackPath = Join-Path $targetRoot ".intent-translator.rollback.$operationId"
    Assert-DirectChildPath -Root $targetRoot -Child $destinationPath
    Assert-DirectChildPath -Root $targetRoot -Child $stagePath
    Assert-DirectChildPath -Root $targetRoot -Child $rollbackPath
    try {
        New-Item -ItemType Directory -Path $stagePath -Force | Out-Null
        $sourceFiles = Get-ChildItem -LiteralPath $source -Recurse -File | Where-Object {
            $_.FullName -notmatch '[\\/]__pycache__[\\/]'
        }
        foreach ($file in $sourceFiles) {
            $relative = $file.FullName.Substring($source.Length + 1)
            $targetFile = Join-Path $stagePath $relative
            $targetDirectory = Split-Path -Parent $targetFile
            New-Item -ItemType Directory -Path $targetDirectory -Force | Out-Null
            Copy-Item -LiteralPath $file.FullName -Destination $targetFile -Force
        }
        if (-not (Test-Path -LiteralPath (Join-Path $stagePath "SKILL.md"))) {
            throw "Staged installation is missing SKILL.md"
        }
        $stagedVersion = (Get-Content -LiteralPath (Join-Path $stagePath "VERSION") -Raw).Trim()
        if ($stagedVersion -ne $sourceVersion) {
            throw "Staged version mismatch: expected $sourceVersion, got $stagedVersion"
        }
        if (Test-Path -LiteralPath $destinationPath) {
            Move-Item -LiteralPath $destinationPath -Destination $rollbackPath
        }
        if ($env:INTENT_TRANSLATOR_TEST_FAIL_AFTER_BACKUP -eq "1") {
            throw "Simulated failure after backup"
        }
        Move-Item -LiteralPath $stagePath -Destination $destinationPath
        if (Test-Path -LiteralPath $rollbackPath) {
            Remove-Item -LiteralPath $rollbackPath -Recurse -Force
        }
        Write-Host "Installed intent-translator $sourceVersion to $destinationPath"
    } catch {
        if ((Test-Path -LiteralPath $destinationPath) -and (Test-Path -LiteralPath $rollbackPath)) {
            Remove-Item -LiteralPath $destinationPath -Recurse -Force
        }
        if (Test-Path -LiteralPath $rollbackPath) {
            Move-Item -LiteralPath $rollbackPath -Destination $destinationPath
        }
        if (Test-Path -LiteralPath $stagePath) {
            Remove-Item -LiteralPath $stagePath -Recurse -Force
        }
        throw "Installation failed and the previous version was restored: $($_.Exception.Message)"
    }
}

if (-not $SkipProfile) {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) { $python = Get-Command python3 -ErrorAction SilentlyContinue }
    if ($python) {
        $profilePath = if ($env:INTENT_TRANSLATOR_PROFILE) {
            $env:INTENT_TRANSLATOR_PROFILE
        } else {
            Join-Path $userHome ".intent-translator\profile.json"
        }
        if (-not (Test-Path -LiteralPath $profilePath)) {
            & $python.Source (Join-Path $source "scripts\init_profile.py") init --profile $profilePath
        } else {
            & $python.Source (Join-Path $source "scripts\init_profile.py") migrate --profile $profilePath
            if ($LASTEXITCODE -ne 0) { throw "Existing local profile migration failed" }
            & $python.Source (Join-Path $source "scripts\init_profile.py") validate --profile $profilePath
        }
    } else {
        Write-Warning "Python 3.10+ was not found; Skill files were installed but the local profile was not initialized."
    }
}

if ($uniqueTargets.Count -gt 0) {
    $onboard = Join-Path (Join-Path $uniqueTargets[0] "intent-translator") "scripts\onboard.py"
    Write-Host "Optional first-time setup: python `"$onboard`" start"
}
