param(
    [string]$RepoRoot = ""
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

$hookPath = Join-Path $RepoRoot ".githooks"
$postCommit = Join-Path $hookPath "post-commit"
$noteScript = Join-Path $RepoRoot "scripts\write_memory_commit_note.ps1"

if (-not (Test-Path $postCommit)) {
    throw "Missing hook template: $postCommit"
}

if (-not (Test-Path $noteScript)) {
    throw "Missing memory note script: $noteScript"
}

& git -C $RepoRoot config core.hooksPath .githooks
if ($LASTEXITCODE -ne 0) {
    throw "Failed to configure core.hooksPath"
}

Write-Output "Configured git core.hooksPath=.githooks for $RepoRoot"
Write-Output "Post-commit memory notes will be written by scripts/write_memory_commit_note.ps1"
