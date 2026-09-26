<#
.SYNOPSIS
  Start PostgreSQL (docker), migrate, load db_Exynos2600_SM-S947B + derived project DB folders (authoring sync, measurement import), start API and UI.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\dev_up.ps1
  powershell -ExecutionPolicy Bypass -File scripts\dev_up.ps1 -SkipLoad -Streamlit
#>
param(
    # derived authoring project -> its DB folder (compiled 00~02 + measurements -> 03_evidence), loaded after 2600
    [hashtable]$AuthoringProjects = @{ "sm-s957b" = "db_Exynos2700_SM-S957B" },
    [switch]$SkipLoad,
    [switch]$NoUi,
    [switch]$Streamlit
)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)          # implementation/
New-Item -ItemType Directory -Force output\etl | Out-Null

function Step($msg) { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }
function Run($exe, [string[]]$argv) {
    & $exe @argv
    if ($LASTEXITCODE -ne 0) { throw "$exe $($argv -join ' ') failed (exit $LASTEXITCODE)" }
}

Step "PostgreSQL (docker compose)"
Run docker @("compose", "up", "-d", "postgres")
$cid = (docker compose ps -q postgres).Trim()
for ($i = 0; $i -lt 60; $i++) {
    $health = (docker inspect --format "{{.State.Health.Status}}" $cid).Trim()
    if ($health -eq "healthy") { break }
    Start-Sleep -Seconds 2
}
if ($health -ne "healthy") { throw "postgres not healthy: $health" }
Write-Host "postgres: $health (127.0.0.1:15432)"

Step "Alembic migration"
Run uv @("run", "alembic", "upgrade", "head")

if (-not $SkipLoad) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    Step "Rename legacy ids in the runtime DB (authoring/id-renames.yaml; no-op when nothing matches)"
    Run uv @("run", "python", "-m", "scenario_db.etl.rename_ids", "--map", "authoring\id-renames.yaml",
             "--apply", "--backup", "output\etl\rename-backup-$stamp.json")

    Step "Retire out-of-scope rows (authoring/retired.yaml, current ids; no-op when nothing matches)"
    Run uv @("run", "python", "-m", "scenario_db.etl.retire", "--spec", "authoring\retired.yaml",
             "--apply", "--backup", "output\etl\retire-backup-$stamp.json")

    Step "ETL: db_Exynos2600_SM-S947B"
    Run uv @("run", "python", "-m", "scenario_db.etl.loader", "db_Exynos2600_SM-S947B",
             "--strict", "--report-json", "output\etl\etl-exynos2600.json")
    foreach ($p in $AuthoringProjects.Keys) {
        $db = $AuthoringProjects[$p]
        Step "Authoring sync -> $db ($p)"
        Run uv @("run", "python", "-m", "scenario_db.authoring", "sync", $p, "--fixture", $db, "--to", "fixture", "--prune")
        if (Test-Path "$db\measurements") {
            Step "Measurement import -> $db\03_evidence"
            Run uv @("run", "python", "scripts\import_measurements.py", $db, "--strict")
        }
        Run uv @("run", "python", "-m", "scenario_db.etl.loader", $db,
                 "--strict", "--report-json", "output\etl\etl-$p.json")
    }
}

Step "API http://127.0.0.1:18000/docs"
Start-Process powershell -ArgumentList @("-NoExit", "-Command",
    "Set-Location '$PWD'; uv run --group sim uvicorn scenario_db.api.app:app --host 127.0.0.1 --port 18000")

if (-not $NoUi) {
    Step "React UI http://localhost:3000"
    Start-Process powershell -ArgumentList @("-NoExit", "-Command", "Set-Location '$PWD\ui'; npm run dev")
}
if ($Streamlit) {
    Step "Streamlit http://127.0.0.1:18502"
    Start-Process powershell -ArgumentList @("-NoExit", "-Command",
        "Set-Location '$PWD'; uv run --group dashboard --group sim streamlit run dashboard/Home.py --server.port 18502 --server.address 127.0.0.1")
}
Write-Host "`nDone. ETL reports: output\etl\*.json" -ForegroundColor Green
