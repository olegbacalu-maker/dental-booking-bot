# Build-Desktop.ps1 - sobiraet DentArt.exe (PyInstaller, onefile).
# Rezultat: dist\DentArt.exe
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$venv = ".venv-desktop"
if (-not (Test-Path $venv)) {
    py -3 -m venv $venv
}
& "$venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
& "$venv\Scripts\pip.exe" install --quiet -r bot\requirements-desktop.txt pyinstaller

& "$venv\Scripts\pyinstaller.exe" --noconfirm --clean --onefile --name DentArt `
    --distpath dist --workpath build --specpath build `
    --add-data "$PSScriptRoot\bot\app\static;app\static" `
    --add-data "$PSScriptRoot\bot\app\clinic.json;app" `
    "$PSScriptRoot\bot\desktop.py"

if (Test-Path "dist\DentArt.exe") {
    $size = [math]::Round((Get-Item "dist\DentArt.exe").Length / 1MB, 1)
    Write-Host "OK: dist\DentArt.exe ($size MB)"
} else {
    Write-Host "BUILD FAILED"; exit 1
}
