# Start-Demo.ps1 - podnimaet demo dlya pokaza v klinike:
# 1) docker compose up, 2) publichnyi tunnel Cloudflare, 3) stranica s QR-kodom.
# Ostanovka tunnelya: Stop-Process -Id <PID> (PID pechataetsya nizhe). Docker NE ubivat'!
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Docker ne zapushchen. Zapusk: wscript D:\Docker\start-docker.vbs - zhdi ikonku kita, potom povtori." -ForegroundColor Yellow
    exit 1
}

docker compose up -d
foreach ($i in 1..20) {
    try { $null = Invoke-RestMethod http://localhost:8088/health -TimeoutSec 2; break }
    catch { Start-Sleep -Seconds 1 }
}

# esli tunnel uzhe krutitsya s proshlogo raza - gasim ego (eto NASH process, ne Docker!)
$old = Get-Process cloudflared -ErrorAction SilentlyContinue
if ($old) {
    $old | Stop-Process -Force -ErrorAction SilentlyContinue
    Write-Host "Staryi tunnel ostanovlen (novyi URL budet nizhe)." -ForegroundColor Yellow
    Start-Sleep -Seconds 1
}
# staryie logi ubiraem molcha, tekushchii log - unikalnyi na kazhdyi zapusk
Get-ChildItem (Join-Path $env:TEMP "cloudflared_demo*.log") -ErrorAction SilentlyContinue |
    ForEach-Object { try { Remove-Item $_.FullName -Force -ErrorAction Stop } catch {} }
$log = Join-Path $env:TEMP ("cloudflared_demo_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))
$cloudflared = "C:\Program Files (x86)\cloudflared\cloudflared.exe"
$p = Start-Process -FilePath $cloudflared -ArgumentList "tunnel", "--url", "http://localhost:8088" `
     -RedirectStandardError $log -PassThru -WindowStyle Hidden

$url = $null
foreach ($i in 1..30) {
    Start-Sleep -Seconds 1
    if (Test-Path $log) {
        $m = Select-String -Path $log -Pattern "https://[a-z0-9-]+\.trycloudflare\.com" | Select-Object -First 1
        if ($m) { $url = $m.Matches[0].Value; break }
    }
}

if ($url) {
    Write-Host ""
    Write-Host "PUBLIC URL:  $url" -ForegroundColor Green
    Write-Host "QR-stranica: http://localhost:8088/demo?url=$url"
    Write-Host "Admin:       http://localhost:8088/admin"
    Write-Host "Tunnel PID:  $($p.Id)   (stop: Stop-Process -Id $($p.Id))"
    Start-Process "http://localhost:8088/demo?url=$url"
} else {
    Write-Host "Tunnel URL ne poyavilsya za 30 s. Log: $log" -ForegroundColor Red
}
