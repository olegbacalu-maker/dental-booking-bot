# Restore-Db.ps1 - vosstanavlivaet dump v zhivuyu bazu (dump s --clean sam drophet tablicy).
# Primer: .\Restore-Db.ps1 -File backups\dental_20260730_120000.sql
param([Parameter(Mandatory = $true)][string]$File)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path $File)) { Write-Host "File not found: $File"; exit 1 }
docker cp $File dental_sandbox_db:/tmp/restore.sql
docker exec dental_sandbox_db psql -U dental -d dental -q -f /tmp/restore.sql
docker exec dental_sandbox_db rm /tmp/restore.sql
Write-Host "Restore OK from $File"
