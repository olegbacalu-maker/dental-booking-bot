# Build-Engine.ps1 - sobiraet DVIZHOK obolochki Tauri papkoi (T5, 18.10.2026).
# Rezultat: dist\DentPilot-Engine\DentPilot-Engine.exe + dist\DentPilot-Engine\_internal\
# Ustanovshchik (T9) kladet etu papku kak engine\ ryadom s DentPilot.exe obolochki.
# Kontrakt chastei: docs\dentpilot-2\tauri-contract.md; pochemu papkoi - sidecar.md.
#
# S 2.0.0 eto edinstvennaya sborka dvizhka: Build-Installer.ps1 zovet ee i kladet
# papku ryadom s obolochkoi. Prezhnyaya sborka odnim failom s oknom pywebview
# (Build-Desktop.ps1) snyata 22.10.2026.
#
# Pochemu tak (proveryeno opytom 18.10, sm. sidecar.md):
#  - papkoi (onedir): u odnogo faila zagruzchik porozhdaet NASTOYASHCHII process-vnuk,
#    kotorogo kill() obolochki ne gasit, i kazhdyi zapusk raspakovyvaet ~60 MB v TEMP;
#  - KONSOLNAYA podsistema: obolochka zapuskaet dvizhok s CREATE_NO_WINDOW (okna net),
#    truby stdin/stdout rabotayut navernyaka, a okonnyi zagruzchik PyInstaller na
#    neperehvachennoi oshibke risuet SVOE okno s trassoi - dvizhok visit na nem, a
#    kontrakt zapreshchaet dvizhku okna. Privilegirovannyi zapusk (UAC) idet s SW_HIDE.
#  - pywebview v dvizhok ne edet: okno i storozha perezapuska risuet obolochka.
#    --exclude-module webview ostaetsya strahovkoi: poka pywebview stoit v obshchem
#    .venv-desktop, PyInstaller mog by ego podobrat.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$venv = ".venv-desktop"
if (-not (Test-Path $venv)) {
    py -3 -m venv $venv
}
# Cherez modul, a ne pip.exe/pyinstaller.exe: obolochki venv ne perezhivayut pereezd papki.
& "$venv\Scripts\python.exe" -m pip install --quiet -r bot\requirements-desktop.txt pyinstaller
if ($LASTEXITCODE -ne 0) { Write-Host "pip exit $LASTEXITCODE"; exit 1 }

if (-not (Test-Path "build")) { New-Item -ItemType Directory "build" | Out-Null }
& "$venv\Scripts\python.exe" scripts\make_icon.py build\icon.ico
if ($LASTEXITCODE -ne 0) { Write-Host "make_icon exit $LASTEXITCODE"; exit 1 }

# React-klient - do PyInstaller. cmd /c i 2>&1: v PS 5.1 lyuboi stderr npm stal by oshibkoi.
if (-not (Test-Path "frontend\node_modules")) {
    cmd /c "cd /d ""$PSScriptRoot\frontend"" && npm ci 2>&1"
    if ($LASTEXITCODE -ne 0) { Write-Host "npm ci exit $LASTEXITCODE"; exit 1 }
}
cmd /c "cd /d ""$PSScriptRoot\frontend"" && npm run build 2>&1"
if ($LASTEXITCODE -ne 0) { Write-Host "npm run build exit $LASTEXITCODE"; exit 1 }
foreach ($f in "bundle.js", "three.js", "three-core.js", "teeth.js") {
    if (-not (Test-Path "bot\app\static\js\$f")) { Write-Host "MISSING static\js\$f"; exit 1 }
}

& "$venv\Scripts\python.exe" "scripts\sync_version.py"
if ($LASTEXITCODE -ne 0) { Write-Host "sync_version exit $LASTEXITCODE"; exit 1 }

# Staruyu papku - DO sborki: upavshii PyInstaller ne dolzhen ostavit proshluyu na meste.
$out = "dist\DentPilot-Engine"
if (Test-Path $out) { Remove-Item $out -Recurse -Force }

& "$venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onedir --console --name DentPilot-Engine `
    --icon "$PSScriptRoot\build\icon.ico" `
    --version-file "$PSScriptRoot\build\version_info.txt" `
    --distpath dist --workpath build\engine --specpath build\engine `
    --add-data "$PSScriptRoot\bot\app\static;app\static" `
    --add-data "$PSScriptRoot\bot\app\clinic.json;app" `
    --add-data "$PSScriptRoot\bot\app\clinic_new.json;app" `
    --hidden-import sqlcipher3 --hidden-import sqlcipher3.dbapi2 `
    --exclude-module webview --exclude-module clr --exclude-module clr_loader `
    --exclude-module pythonnet --exclude-module bottle --exclude-module proxy_tools `
    "$PSScriptRoot\bot\desktop.py"
if ($LASTEXITCODE -ne 0) { Write-Host "PyInstaller exit $LASTEXITCODE"; exit 1 }

$exe = "$out\DentPilot-Engine.exe"
if (-not (Test-Path $exe)) { Write-Host "BUILD FAILED"; exit 1 }
$size = [math]::Round(((Get-ChildItem $out -Recurse -File | Measure-Object Length -Sum).Sum) / 1MB, 1)
Write-Host "Sobrano: $out ($size MB papka). Dalshe - ZAPUSK pod obolochkoi-harnessom."

# Sborka obyazana ZAPUSTIT to, chto sobrala (urok Build-Desktop 21.09): truby DP1,
# stop i zakrytyi stdin, vtoroi ekzemplyar, chuzhoi port, koren programmy nad engine\,
# stranitsy sobrannoi programmy. Laboratoriya - vremennaya papka, port svoi.
& "$venv\Scripts\python.exe" "scripts\engine_check.py" --exe $exe
if ($LASTEXITCODE -ne 0) { Write-Host "SBORKA NE PRINYATA: protokol dvizhka"; exit 1 }

Write-Host "OK: $exe ($size MB) - govorit po kontraktu, ostanavlivaetsya chestno."
