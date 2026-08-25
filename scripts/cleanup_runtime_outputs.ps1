[CmdletBinding()]
param(
    [switch]$Apply,
    [switch]$IncludePytestTemp
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$repoPrefix = $repoRoot.TrimEnd("\") + "\"

$directoryNames = @(
    "runtime_logs",
    ".codex_run_logs",
    ".runlogs",
    ".runtime",
    "logs"
)

$fileNames = @(
    ".coverage",
    "test-scenariodb.db",
    "fastapi.err.log",
    "fastapi.out.log",
    "streamlit-dashboard.err.log",
    "streamlit-dashboard.out.log"
)

function Assert-RepositoryChild {
    param([Parameter(Mandatory = $true)][string]$Path)

    $fullPath = [System.IO.Path]::GetFullPath($Path)
    if (-not $fullPath.StartsWith($repoPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing target outside repository: $fullPath"
    }
    return $fullPath
}

function Get-TargetSize {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (Test-Path -LiteralPath $Path -PathType Leaf) {
        return (Get-Item -LiteralPath $Path).Length
    }
    $files = Get-ChildItem -LiteralPath $Path -File -Recurse -Force -ErrorAction SilentlyContinue
    return ($files | Measure-Object -Property Length -Sum).Sum
}

$targets = @()
foreach ($name in $directoryNames) {
    $candidate = Assert-RepositoryChild (Join-Path $repoRoot $name)
    if (Test-Path -LiteralPath $candidate -PathType Container) {
        $targets += Get-Item -LiteralPath $candidate -Force
    }
}

foreach ($name in $fileNames) {
    $candidate = Assert-RepositoryChild (Join-Path $repoRoot $name)
    if (Test-Path -LiteralPath $candidate -PathType Leaf) {
        $targets += Get-Item -LiteralPath $candidate -Force
    }
}

if ($IncludePytestTemp) {
    $pytestCacheDirs = Get-ChildItem -LiteralPath $repoRoot -Directory -Force |
        Where-Object { $_.Name -like "pytest-cache-files-*" }
    foreach ($directory in $pytestCacheDirs) {
        [void](Assert-RepositoryChild $directory.FullName)
        $targets += $directory
    }
}

$rows = foreach ($target in $targets | Sort-Object FullName -Unique) {
    [pscustomobject]@{
        Type = if ($target.PSIsContainer) { "directory" } else { "file" }
        Bytes = Get-TargetSize $target.FullName
        Path = $target.FullName
    }
}

if (-not $rows) {
    Write-Output "No disposable runtime outputs found."
    exit 0
}

$rows | Format-Table -AutoSize

if (-not $Apply) {
    Write-Output "Dry-run only. Re-run with -Apply to remove the listed targets."
    exit 0
}

$failures = @()
foreach ($target in $targets | Sort-Object FullName -Unique) {
    $safePath = Assert-RepositoryChild $target.FullName
    try {
        if ($target.PSIsContainer) {
            Remove-Item -LiteralPath $safePath -Recurse -Force
        }
        else {
            Remove-Item -LiteralPath $safePath -Force
        }
        Write-Output "Removed: $safePath"
    }
    catch {
        $failures += [pscustomobject]@{
            Path = $safePath
            Error = $_.Exception.Message
        }
        Write-Warning "Failed to remove: $safePath"
    }
}

if ($failures) {
    $failures | Format-Table -Wrap -AutoSize
    throw "Runtime cleanup completed with $($failures.Count) failed target(s)."
}
