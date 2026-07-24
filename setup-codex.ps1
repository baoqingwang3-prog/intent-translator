[CmdletBinding()]
param(
    [string[]]$StudyGoal = @(),
    [string]$ObsidianVaultName = "",
    [string]$ObsidianVaultPath = "",
    [string]$ManagedNote = "AI/intent-translator-study-index.md",
    [switch]$EnableShadow,
    [switch]$SkipPointerSync,
    [switch]$CheckOnly
)

$ErrorActionPreference = "Stop"
$utf8 = [Text.UTF8Encoding]::new($false)
$OutputEncoding = $utf8
[Console]::InputEncoding = $utf8
[Console]::OutputEncoding = $utf8
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

$userHome = [Environment]::GetFolderPath("UserProfile")
$codexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $userHome ".codex" }
$profilePath = if ($env:INTENT_TRANSLATOR_PROFILE) { $env:INTENT_TRANSLATOR_PROFILE } else { Join-Path $userHome ".intent-translator\profile.json" }
$rulesPath = Join-Path $PSScriptRoot "templates\codex-student-rules.md"
$agentsPath = Join-Path $codexHome "AGENTS.md"
$startMarker = "<!-- intent-translator:codex-rules:start -->"
$endMarker = "<!-- intent-translator:codex-rules:end -->"

if (-not (Test-Path -LiteralPath $rulesPath)) { throw "Managed Codex rule template not found: $rulesPath" }

if ($CheckOnly) {
    & (Join-Path $PSScriptRoot "install.ps1") -TargetHost Codex -CheckOnly
    if (Test-Path -LiteralPath $profilePath) {
        $python = Get-Command python -ErrorAction SilentlyContinue
        if (-not $python) { $python = Get-Command python3 -ErrorAction SilentlyContinue }
        if ($python) { & $python.Source (Join-Path $PSScriptRoot "skills\intent-translator\scripts\init_profile.py") validate --profile $profilePath }
    }
    $rulesInstalled = (Test-Path -LiteralPath $agentsPath) -and ((Get-Content -LiteralPath $agentsPath -Raw -Encoding utf8).Contains($startMarker))
    Write-Host "Codex rules: $(if ($rulesInstalled) { 'installed' } else { 'not installed' })"
    return
}

& (Join-Path $PSScriptRoot "install.ps1") -TargetHost Codex -Replace
& (Join-Path $PSScriptRoot "install-mcp.ps1") -ConfigureCodex

$profileScript = Join-Path $PSScriptRoot "skills\intent-translator\scripts\init_profile.py"
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { $python = Get-Command python3 -ErrorAction SilentlyContinue }
if (-not $python) { throw "Python 3.10+ is required to configure the local profile." }
if (-not (Test-Path -LiteralPath $profilePath)) {
    & $python.Source $profileScript init --profile $profilePath --language auto
}

$universityArgs = @($profileScript, "apply-pack", "--profile", $profilePath, "--pack", "university-student", "--managed-note", $ManagedNote)
if ($ObsidianVaultName.Trim()) { $universityArgs += @("--vault-name", $ObsidianVaultName.Trim()) }
if ($ObsidianVaultPath.Trim()) { $universityArgs += @("--vault-path", $ObsidianVaultPath.Trim()) }
& $python.Source @universityArgs
if ($LASTEXITCODE -ne 0) { throw "Failed to apply university-student profile pack." }

$profileArgs = @($profileScript, "apply-pack", "--profile", $profilePath, "--pack", "student-exam-prep", "--managed-note", $ManagedNote)
if ($EnableShadow) { $profileArgs += @("--enable-shadow", "--shadow-preview-chars", "48") }
foreach ($goal in $StudyGoal) {
    if ($goal.Trim()) { $profileArgs += @("--goal", $goal.Trim()) }
}
if ($ObsidianVaultName.Trim()) { $profileArgs += @("--vault-name", $ObsidianVaultName.Trim()) }
if ($ObsidianVaultPath.Trim()) { $profileArgs += @("--vault-path", $ObsidianVaultPath.Trim()) }
& $python.Source @profileArgs
if ($LASTEXITCODE -ne 0) { throw "Failed to apply student-exam-prep profile pack." }

$rules = (Get-Content -LiteralPath $rulesPath -Raw -Encoding utf8).Trim()
$managedBlock = "$startMarker`n$rules`n$endMarker"
$existing = if (Test-Path -LiteralPath $agentsPath) { Get-Content -LiteralPath $agentsPath -Raw -Encoding utf8 } else { "" }
$start = $existing.IndexOf($startMarker, [StringComparison]::Ordinal)
$finish = $existing.IndexOf($endMarker, [StringComparison]::Ordinal)
if ($start -ge 0 -and $finish -ge $start) {
    $finish += $endMarker.Length
    $updated = ($existing.Substring(0, $start).TrimEnd() + "`n`n" + $managedBlock + "`n" + $existing.Substring($finish).TrimStart()).Trim() + "`n"
} else {
    $updated = (($existing.TrimEnd() + "`n`n" + $managedBlock).Trim() + "`n")
}
New-Item -ItemType Directory -Path $codexHome -Force | Out-Null
if ($updated -ne $existing) {
    if (Test-Path -LiteralPath $agentsPath) {
        Copy-Item -LiteralPath $agentsPath -Destination "$agentsPath.bak-intent-translator-$(Get-Date -Format 'yyyyMMddTHHmmss')"
    }
    [IO.File]::WriteAllText($agentsPath, $updated, $utf8)
    Write-Host "Updated managed Codex rules in $agentsPath"
}

$statePath = Join-Path $userHome ".intent-translator\mcp\current.json"
if (-not (Test-Path -LiteralPath $statePath)) { throw "MCP installation state not found: $statePath" }
$state = Get-Content -LiteralPath $statePath -Raw -Encoding utf8 | ConvertFrom-Json
$venvScripts = Split-Path -Parent $state.command
$doctor = Join-Path $venvScripts "intent-translator-doctor.exe"
$study = Join-Path $venvScripts "intent-translator-study.exe"
& $doctor
if ($LASTEXITCODE -ne 0) { throw "intent-translator doctor reported a failure." }
if (-not $SkipPointerSync -and ($ObsidianVaultName.Trim() -or $ObsidianVaultPath.Trim())) {
    & $study pointer-sync --profile $profilePath
    if ($LASTEXITCODE -ne 0) { throw "Study pointer index sync failed." }
}

Write-Host "Codex setup complete. Restart Codex once so the updated MCP tool list is reloaded."
