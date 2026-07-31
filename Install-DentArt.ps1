# Install-DentArt.ps1 - ustanovka na komp kliniki:
# kopiruet exe v papku, sozdaet yarlyki (Rabochii stol + Avtozapusk Windows).
# Primer: .\Install-DentArt.ps1 -Source E:\DentArt.exe -Dir C:\DentArt
param(
    [string]$Source = ".\DentArt.exe",
    [string]$Dir = "C:\DentArt"
)
$ErrorActionPreference = "Stop"

if (-not (Test-Path $Source)) { Write-Host "Ne naiden $Source"; exit 1 }
New-Item -ItemType Directory -Force $Dir | Out-Null
Copy-Item $Source (Join-Path $Dir "DentArt.exe") -Force

$ws = New-Object -ComObject WScript.Shell
$desktop = [Environment]::GetFolderPath("Desktop")
$startup = [Environment]::GetFolderPath("Startup")

foreach ($place in @($desktop, $startup)) {
    $lnk = $ws.CreateShortcut((Join-Path $place "DentArt.lnk"))
    $lnk.TargetPath = Join-Path $Dir "DentArt.exe"
    $lnk.WorkingDirectory = $Dir
    $lnk.Description = "DentArt - registrul clinicii"
    $lnk.Save()
}

Write-Host ""
Write-Host "DentArt ustanovlen: $Dir" -ForegroundColor Green
Write-Host " - yarlyk na Rabochem stole"
Write-Host " - avtozapusk pri vklyuchenii kompa (papka Startup)"
Write-Host "Zapustite yarlyk: pri pervom starte programma poprosit ustanovit PIN."
