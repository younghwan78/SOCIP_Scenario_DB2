param(
    [string]$RepoRoot = "",
    [string]$MemoryNotesDir = "",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

if ([string]::IsNullOrWhiteSpace($MemoryNotesDir)) {
    if (-not [string]::IsNullOrWhiteSpace($env:CODEX_MEMORY_NOTES_DIR)) {
        $MemoryNotesDir = $env:CODEX_MEMORY_NOTES_DIR
    } else {
        $MemoryNotesDir = Join-Path $env:USERPROFILE ".codex\memories\extensions\ad_hoc\notes"
    }
}

function Invoke-GitText {
    param([string[]]$Arguments)
    $output = & git -C $RepoRoot @Arguments 2>$null
    if ($LASTEXITCODE -ne 0) {
        return ""
    }
    return ($output -join "`n").Trim()
}

function Convert-ToSlug {
    param([string]$Text)
    $slug = ($Text.ToLowerInvariant() -replace "[^a-z0-9]+", "-").Trim("-")
    if ([string]::IsNullOrWhiteSpace($slug)) {
        return "commit"
    }
    if ($slug.Length -gt 48) {
        return $slug.Substring(0, 48).Trim("-")
    }
    return $slug
}

$fullHash = Invoke-GitText @("rev-parse", "HEAD")
if ([string]::IsNullOrWhiteSpace($fullHash)) {
    throw "Could not resolve HEAD for repository: $RepoRoot"
}

$shortHash = Invoke-GitText @("rev-parse", "--short", "HEAD")
$branch = Invoke-GitText @("branch", "--show-current")
if ([string]::IsNullOrWhiteSpace($branch)) {
    $branch = "(detached)"
}
$subject = Invoke-GitText @("log", "-1", "--pretty=%s")
$body = Invoke-GitText @("log", "-1", "--pretty=%b")
$author = Invoke-GitText @("log", "-1", "--pretty=%an <%ae>")
$commitDate = Invoke-GitText @("log", "-1", "--date=iso-strict", "--pretty=%cd")
$remoteUrl = Invoke-GitText @("remote", "get-url", "origin")
$changedFiles = Invoke-GitText @("diff-tree", "--no-commit-id", "--name-status", "-r", "HEAD")
$stat = Invoke-GitText @("show", "--stat", "--oneline", "--no-renames", "--format=", "HEAD")
$worktreeStatus = Invoke-GitText @("status", "--short")

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$slug = Convert-ToSlug $subject
$notePath = Join-Path $MemoryNotesDir "$timestamp-$shortHash-$slug.md"

$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("# SOC Scenario DB commit note")
$lines.Add("")
$lines.Add("- Workspace: $RepoRoot")
$lines.Add("- Branch: $branch")
$lines.Add("- Commit: $shortHash ($fullHash)")
$lines.Add("- Subject: $subject")
$lines.Add("- Author: $author")
$lines.Add("- Commit date: $commitDate")
if (-not [string]::IsNullOrWhiteSpace($remoteUrl)) {
    $lines.Add("- Remote origin: $remoteUrl")
}
$lines.Add("- Note source: local git post-commit hook")
$lines.Add("- Memory update policy: this creates an ad_hoc note for later memory ingestion; it does not edit MEMORY.md directly.")
$lines.Add("")

if (-not [string]::IsNullOrWhiteSpace($body)) {
    $lines.Add("## Commit Body")
    $lines.Add("")
    $lines.Add($body)
    $lines.Add("")
}

$lines.Add("## Changed Files")
$lines.Add("")
if ([string]::IsNullOrWhiteSpace($changedFiles)) {
    $lines.Add("- No changed file list available.")
} else {
    foreach ($line in ($changedFiles -split "`n")) {
        $lines.Add("- ``$line``")
    }
}
$lines.Add("")

$lines.Add("## Stat")
$lines.Add("")
if ([string]::IsNullOrWhiteSpace($stat)) {
    $lines.Add("No stat available.")
} else {
    $lines.Add('```text')
    $lines.Add($stat)
    $lines.Add('```')
}
$lines.Add("")

$lines.Add("## Worktree Status After Commit")
$lines.Add("")
if ([string]::IsNullOrWhiteSpace($worktreeStatus)) {
    $lines.Add("Clean.")
} else {
    $lines.Add('```text')
    $lines.Add($worktreeStatus)
    $lines.Add('```')
}
$lines.Add("")

$noteText = ($lines -join "`r`n")

if ($DryRun) {
    Write-Output $noteText
    exit 0
}

New-Item -ItemType Directory -Force -Path $MemoryNotesDir | Out-Null
Set-Content -Path $notePath -Value $noteText -Encoding UTF8
Write-Output $notePath
