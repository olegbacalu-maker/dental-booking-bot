# Build-Desktop.ps1 - sobiraet DentPilot.exe (PyInstaller, onefile, okno bez konsoli).
# Rezultat: dist\DentPilot.exe
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$venv = ".venv-desktop"
if (-not (Test-Path $venv)) {
    py -3 -m venv $venv
}
& "$venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
& "$venv\Scripts\pip.exe" install --quiet -r bot\requirements-desktop.txt pyinstaller

if (-not (Test-Path "build")) { New-Item -ItemType Directory "build" | Out-Null }
& "$venv\Scripts\python.exe" scripts\make_icon.py build\icon.ico

# Staryi exe udalyaem DO sborki: inache upavshii PyInstaller ostavlyaet
# proshluyu versiyu na meste i Test-Path nizhe rapportuet "OK" o chuzhom faile.
Remove-Item "dist\DentPilot.exe" -Force -EA SilentlyContinue

& "$venv\Scripts\pyinstaller.exe" --noconfirm --clean --onefile --noconsole --name DentPilot `
    --icon "$PSScriptRoot\build\icon.ico" `
    --distpath dist --workpath build --specpath build `
    --add-data "$PSScriptRoot\bot\app\static;app\static" `
    --add-data "$PSScriptRoot\bot\app\clinic.json;app" `
    "$PSScriptRoot\bot\desktop.py"
if ($LASTEXITCODE -ne 0) { Write-Host "PyInstaller exit $LASTEXITCODE"; exit 1 }

if (Test-Path "dist\DentPilot.exe") {
    $size = [math]::Round((Get-Item "dist\DentPilot.exe").Length / 1MB, 1)
    Write-Host "OK: dist\DentPilot.exe ($size MB)"
} else {
    Write-Host "BUILD FAILED"; exit 1
}
