# Build-Desktop.ps1 - sobiraet DentPilot.exe (PyInstaller, onefile, okno bez konsoli).
# Rezultat: dist\DentPilot.exe
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$venv = ".venv-desktop"
if (-not (Test-Path $venv)) {
    py -3 -m venv $venv
}
# ⚠️ Vyzyvaem CHEREZ MODUL, a ne pip.exe/pyinstaller.exe. Eti obolochki - exe s
# VSHITYM putem k interpretatoru: posle pereezda papki proekta oni molcha
# vozvrashchayut kod 1 s pustym vyvodom (proveryeno pri pereezde v D:\DentProject).
# python.exe zhe nahodit svoi venv po sobstvennomu raspolozheniyu i perezzhaet.
& "$venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
& "$venv\Scripts\python.exe" -m pip install --quiet -r bot\requirements-desktop.txt pyinstaller

if (-not (Test-Path "build")) { New-Item -ItemType Directory "build" | Out-Null }
& "$venv\Scripts\python.exe" scripts\make_icon.py build\icon.ico

# React-klient (frontend\) sobiraetsya DO PyInstaller: bundle.js i bundle.css
# lozhatsya v bot\app\static i edut v exe tem zhe --add-data, chto panel.js.
# Bez etogo shaga sborka s chistogo klona polozhit v exe stranitsu bez bandla,
# i uvidit eto tolko klinika s vklyuchennym flagom React (smoke_exe eto lovit).
# WARNING: npm pishet preduprezhdeniya v stderr, a PowerShell 5.1 pri
# ErrorActionPreference=Stop delaet iz lyubogo stderr terminiruyushchuyu
# oshibku - poetomu cherez cmd /c s 2>&1 VNUTRI cmd, a ne v PowerShell.
if (-not (Test-Path "frontend\node_modules")) {
    cmd /c "cd /d ""$PSScriptRoot\frontend"" && npm ci 2>&1"
    if ($LASTEXITCODE -ne 0) { Write-Host "npm ci exit $LASTEXITCODE"; exit 1 }
}
cmd /c "cd /d ""$PSScriptRoot\frontend"" && npm run build 2>&1"
if ($LASTEXITCODE -ne 0) { Write-Host "npm run build exit $LASTEXITCODE"; exit 1 }
if (-not (Test-Path "bot\app\static\js\bundle.js")) { Write-Host "BUNDLE MISSING"; exit 1 }

# SQLCipher importiruetsya VNUTRI funkcii (db._sqlite_driver): modul nuzhen
# tolko klinike s shifrovaniem. Bez --hidden-import PyInstaller mozhet ego ne
# zametit - exe soberetsya, dymovoi test proidet, a shifrovanie otkazhet u toi
# kliniki, kotoraya ego vklyuchit. Storozhit proverka v tests\test_dbcrypt.py.
# WARNING: kommentarii vnutri komandy s perenosami (`) lomayut razbor - tolko
# zdes, nad komandoi.
#
# Staryi exe udalyaem DO sborki: inache upavshii PyInstaller ostavlyaet
# proshluyu versiyu na meste i Test-Path nizhe rapportuet "OK" o chuzhom faile.
Remove-Item "dist\DentPilot.exe" -Force -EA SilentlyContinue

# Svoistva faila v Windows (izdatel, versiya, opisanie) berutsya iz resursa,
# kotoryi generiruetsya iz APP_VERSION: odin istochnik na programmu, package.json
# i etot resurs. Do 18.09 vse polya byli PUSTYE - exe bez izdatelya i bez versii.
& "$venv\Scripts\python.exe" "scripts\sync_version.py"
if ($LASTEXITCODE -ne 0) { Write-Host "sync_version exit $LASTEXITCODE"; exit 1 }

& "$venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --noconsole --name DentPilot `
    --icon "$PSScriptRoot\build\icon.ico" `
    --version-file "$PSScriptRoot\build\version_info.txt" `
    --distpath dist --workpath build --specpath build `
    --add-data "$PSScriptRoot\bot\app\static;app\static" `
    --add-data "$PSScriptRoot\bot\app\clinic.json;app" `
    --add-data "$PSScriptRoot\bot\app\clinic_new.json;app" `
    --hidden-import sqlcipher3 --hidden-import sqlcipher3.dbapi2 `
    "$PSScriptRoot\bot\desktop.py"
if ($LASTEXITCODE -ne 0) { Write-Host "PyInstaller exit $LASTEXITCODE"; exit 1 }

if (-not (Test-Path "dist\DentPilot.exe")) { Write-Host "BUILD FAILED"; exit 1 }
$size = [math]::Round((Get-Item "dist\DentPilot.exe").Length / 1MB, 1)
Write-Host "Sobrano: dist\DentPilot.exe ($size MB). Dalshe - ZAPUSK, a ne tolko fail."

# ⛔ Do 21.09 sborka konchalas strokoi vyshe, i ona oznachala ROVNO odno: fail
# sushchestvuet i vesit stolko-to. Za odin den etogo trizhdy okazalos malo -
# pravka launchera, vernaya v ishodnikah, v binarnike ne ispolnyalas, i vidno
# eto TOLKO zapuskom: mezhdu pravilom i povedeniem stoyat PyInstaller,
# planirovshchik i failovaya sistema. Build-Installer.ps1 etot shag imel s
# samogo nachala, a sobirayut Build-Desktop - imenno im, kogda proveryayut
# povedenie. Oba stenda izoliruyut sebe $DENTART_DATA_DIR sami (sm. ih
# dokstrings) i zhivut vo vremennoi papke: ustanovku na etoi mashine,
# %ProgramData% i port 8088 ne trogaet ni odin.
Write-Host "Dymovoi test sobrannoi programmy ..."
& "$venv\Scripts\python.exe" "scripts\smoke_build.py" --exe "dist\DentPilot.exe"
if ($LASTEXITCODE -ne 0) { Write-Host "SBORKA NE PRINYATA: dymovoi test"; exit 1 }

# Zhivaya proverka vetki unique: launcher obyazan naiti STARYI koren i ne
# zavodit pustoi zhurnal ryadom s nastoyashchei kartotekoi. Eto ta samaya dyra
# odnoklik-obnovleniya, i prognom iz ishodnikov ona ne lovitsya voobshche:
# harness podnimaet app.main napryamuyu i desktop.py ne ispolnyaet ni strokoi.
Write-Host "Zhivaya proverka vetki unique ..."
& "$venv\Scripts\python.exe" "scripts\check_relocate_live.py" --exe "dist\DentPilot.exe"
if ($LASTEXITCODE -ne 0) { Write-Host "SBORKA NE PRINYATA: vetka unique"; exit 1 }

Write-Host "OK: dist\DentPilot.exe ($size MB) - zapuskaetsya, stranicy otkryvayutsya, vetka unique ispolnena."
