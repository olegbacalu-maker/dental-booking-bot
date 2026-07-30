# Backup-Db.ps1 - dump bazy dental v backups\ (hranim poslednie 14).
# Restore: .\Restore-Db.ps1 -File backups\dental_YYYYMMDD_HHMMSS.sql
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

docker info *> $null
if ($LASTEXITCODE -ne 0) { Write-Host "Docker not running - backup skipped."; exit 0 }

$dir = Join-Path $PSScriptRoot "backups"
if (-not (Test-Path $dir)) { New-Item -ItemType Directory $dir | Out-Null }
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$dest = Join-Path $dir "dental_$stamp.sql"

docker exec dental_sandbox_db pg_dump -U dental -d dental --clean --if-exists -f /tmp/bk.sql
if ($LASTEXITCODE -ne 0) { Write-Host "pg_dump FAILED"; exit 1 }
docker cp dental_sandbox_db:/tmp/bk.sql $dest | Out-Null
docker exec dental_sandbox_db rm /tmp/bk.sql

$size = [math]::Round((Get-Item $dest).Length / 1KB, 1)
Write-Host "Backup OK: $dest ($size KB)"

# retention: 14 poslednih
Get-ChildItem $dir -Filter "dental_*.sql" | Sort-Object Name -Descending |
    Select-Object -Skip 14 | Remove-Item -Force
