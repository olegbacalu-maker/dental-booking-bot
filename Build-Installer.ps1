# Build-Installer.ps1 - sobiraet artefakty reliza:
#   dist\DentPilot.exe                  - sama programma (ee kachaet self-update)
#   dist\DentPilot-Setup-<ver>.exe      - master ustanovki dlya novyh klinik (USB)
#   dist\DentPilot-Setup-<ver>.zip      - on zhe dlya GitHub Release
#
# ZACHEM zip: v relize dolzhen byt ROVNO ODIN fail .exe i eto DentPilot.exe.
# Uzhe ustanovlennye kliniki vybirayut asset iz spiska, i vtoroi .exe ryadom
# oni mogut skachat vmesto programmy i zateret eyu sebya. Zip nevidim dlya nih.
#
#   .\Build-Installer.ps1            # reliznaya sborka (trebuet chistoe derevo)
#   .\Build-Installer.ps1 -SkipApp   # upakovat uzhe sobrannyi dist\DentPilot.exe
#
# Versiya artefakta beretsya NE iz engine.py, a iz samogo exe (/health):
# imenno tak nevozmozhno vypustit "Setup-1.10.0.exe" s binarnikom 1.9.1.
# -SetupDir: kuda polozhit gotovyi master ustanovki dlya klinik. Pustaya
# stroka otklyuchaet kopirovanie. dist ostaetsya vyhodom sborki i
# perezapisyvaetsya kazhdym bildom, poetomu "chto otdavat klinike" zhivet
# otdelno i ne teryaetsya.
param([switch]$SkipApp, [string]$SetupDir = "D:\DentProject\releases")
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Fail($msg) { Write-Host ""; Write-Host "STOP: $msg" -ForegroundColor Red; exit 1 }

# --- versiya v ishodnike (dlya sverki s tem, chto realno vnutri exe) ---
$engine = Get-Content "bot\app\engine.py" -Raw
if ($engine -notmatch 'APP_VERSION\s*=\s*"([^"]+)"') { Fail "APP_VERSION ne naiden v bot\app\engine.py" }
$srcVersion = $Matches[1]
if ($srcVersion -notmatch '^\d+\.\d+\.\d+$') {
    Fail "APP_VERSION = '$srcVersion' - nuzhny rovno tri chisla (X.Y.Z), inache sravnenie versii u klinik lomaetsya"
}

# --- 1. sborka exe ---
if ($SkipApp) {
    if (-not (Test-Path "dist\DentPilot.exe")) { Fail "net dist\DentPilot.exe - zapustite bez -SkipApp" }
    Write-Host "!! -SkipApp: upakovyvayu uzhe lezhashchii exe. Eto NE reliznaya sborka." -ForegroundColor Yellow
    Get-ChildItem "dist" -Filter "DentPilot-Setup-*" -EA SilentlyContinue | Remove-Item -Force
} else {
    # gryaznoe derevo => teg ne vosproizvedet binarnik, a nedodelannaya rabota
    # iz drugogo okna uedet vsem klinikam v odin klik
    $dirty = git status --porcelain
    if ($dirty) {
        Write-Host "Nekommitnutye izmeneniya:" -ForegroundColor Yellow
        $dirty | ForEach-Object { Write-Host "   $_" }
        Fail "reliznaya sborka tolko iz chistogo dereva (zakommitte ili -SkipApp dlya chernovoi sborki)"
    }
    # Chistoe derevo != zapushennoe. Teg na GitHub vesitsya na origin/main, i
    # esli lokalnye kommity ne uehali - teg lyazhet na STARYI kod, a binarnik
    # budet sobran iz novogo. Imenno tot razryv, ot kotorogo zashchishchaet
    # proverka vyshe, tolko na odin shag dalshe.
    # Windows PowerShell prevrashchaet LYUBOI stderr native-komandy v oshibku, a
    # pri $ErrorActionPreference=Stop - v terminiruyushchuyu. Poetomu "net seti"
    # i "net upstream" ubivali sborku vmesto predupreghdenii nizhe: obe vetki
    # byli nedostizhimy, i sobrat s vetki bez upstream bylo nelzya voobshche.
    # try/catch vozvrashchaet im zadumannoe povedenie, ne oslablyaya Fail nizhe.
    try { git fetch --quiet origin 2>$null } catch { $global:LASTEXITCODE = 1 }
    if ($LASTEXITCODE -ne 0) {
        Write-Host "!! git fetch ne udalsya (net seti?) - sravnivayu s tem, chto est lokalno" -ForegroundColor Yellow
    }
    $upstream = $null
    try { $upstream = git rev-parse --abbrev-ref --symbolic-full-name "@{u}" 2>$null } catch { }
    if (-not $upstream) {
        Write-Host "!! u vetki net upstream - proverit, zapushen li kommit, nechem" -ForegroundColor Yellow
    } else {
        $ahead = (git rev-list --count "@{u}..HEAD" 2>$null)
        if ([int]$ahead -gt 0) {
            git log --oneline "@{u}..HEAD" | ForEach-Object { Write-Host "   $_" }
            Fail "$ahead kommit(ov) ne zapushcheny v $upstream - teg lyazhet na chuzhoi kod. Snachala: git push"
        }
        $behind = (git rev-list --count "HEAD..@{u}" 2>$null)
        if ([int]$behind -gt 0) {
            Write-Host "!! $upstream operezhaet vas na $behind kommit(ov) - sobiraete NE poslednii kod" -ForegroundColor Yellow
        }
    }
    Write-Host "Sborka DentPilot.exe (APP_VERSION $srcVersion) ..."
    Get-ChildItem "dist" -Filter "*.exe" -EA SilentlyContinue | Remove-Item -Force
    Get-ChildItem "dist" -Filter "*.zip" -EA SilentlyContinue | Remove-Item -Force
    & "$PSScriptRoot\Build-Desktop.ps1"
    if ($LASTEXITCODE -ne 0) { Fail "PyInstaller upal" }
    if (-not (Test-Path "dist\DentPilot.exe")) { Fail "PyInstaller ne sozdal dist\DentPilot.exe" }
}

# --- 2. dymovoi test: exe voobshche zapuskaetsya, i chto on o sebe govorit? ---
# Eto edinstvennaya proverka, kotoraya lovit zabytyi hidden-import: takoi exe
# molcha zakryvaetsya, a bez testa uehal by vsem klinikam.
Write-Host "Proverka zapuska exe ..."
$port = 8100
while ((Test-NetConnection -ComputerName 127.0.0.1 -Port $port -InformationLevel Quiet -WarningAction SilentlyContinue)) { $port++ }
$lab = Join-Path $env:TEMP ("dp_smoke_" + [System.Diagnostics.Process]::GetCurrentProcess().Id)
if (Test-Path $lab) { Remove-Item $lab -Recurse -Force }
New-Item -ItemType Directory -Force $lab | Out-Null
Copy-Item "dist\DentPilot.exe" $lab
$env:DENTART_BROWSER_MODE = "1"; $env:DENTART_NO_BROWSER = "1"; $env:DENTART_PORT = "$port"
# ADMIN_KEY zadan, chtoby dymovoi test mog otkryt STRANICY, a ne tolko /health:
# bez nego pustaya papka trebuet ekrana ustanovki PIN.
$env:ADMIN_KEY = "smoke1234"
# Klinika s NASTROENNYM botom (grandfather): samozapis (lending i /chat) i
# interfeis bota zamorozheny 08-08 i zhivut tolko za tg_configured. Bez etogo
# dymovoi test proveryal by otsutstvuyushchii kanal, a index.html poteryannyi
# iz sborki ostalsya by nezamechennym. Vetku "bez bota" sterezhet nabor
# "Zamorozka bota" v run_tests.py.
# ⚠️ Peremennaya okruzheniya DENTART_TOKEN_UNREADABLE zdes NE rabotaet:
# launcher zovet dpapi.unlock_env_token, i tot SNIMAET flag, kogda token
# prochitan (pustoi token = uspeshno prochitan). Poetomu daem laboratorii
# CHESTNOE sostoyanie grandfather - token v dental.env, kotoryi ne
# rasshifrovyvaetsya: dpapi sam vystavit flag, a adapter Telegram ne startuet
# (token pri etom pustoi), znachit seti vo vremya sborki net.
Set-Content -Path (Join-Path $lab "dental.env") -Encoding utf8 -Value @(
    "# smoke: token prisutstvuet, no ne rasshifrovyvaetsya -> grandfather",
    "TELEGRAM_TOKEN=dpapi:smoke-nu-rasshifruesh",
    "ADMIN_KEY=smoke1234"
)
$proc = Start-Process (Join-Path $lab "DentPilot.exe") -WorkingDirectory $lab -PassThru -WindowStyle Hidden
$health = $null
foreach ($i in 1..45) {
    try { $health = Invoke-RestMethod "http://127.0.0.1:$port/health" -TimeoutSec 2; break }
    catch { Start-Sleep -Milliseconds 700 }
}
# /health otvechaet BEZ edinogo faila na diske, poetomu poteryannyi --add-data
# (static, clinic.json) on ne lovit. Otkryvaem realnye stranicy.
$smokeOut = ""
$smokeCode = 1
if ($health) {
    $smokeOut = & ".venv-desktop\Scripts\python.exe" "tests\smoke_exe.py" "http://127.0.0.1:$port" "smoke1234" 2>&1 | Out-String
    $smokeCode = $LASTEXITCODE
}
# Ubivaem DEREVO: onefile-sborka PyInstaller raspakovyvaetsya i zapuskaet
# DOCHERNII process. Stop-Process po roditelyu ostavlyal ego zhit - on derzhal
# port i vremennuyu papku, i kazhdaya sborka ostavlyala visyachii DentPilot.exe.
# ⚠️ try/catch obyazatelen (08-12). Dochernii process chasto umiraet SAM vsled
# za roditelem, i togda taskkill pishet v stderr "could not be terminated" - a
# "2>&1" pri $ErrorActionPreference=Stop delaet iz etogo TERMINIRUYUSHCHUYU
# oshibku. Sborka padala na poslednem shage, uzhe posle uspeshnogo dymovogo
# testa: exe sobran, stranicy otkryvayutsya, a operator vidit krasnoe i ne
# ponimaet, chto vsyo horosho. Eto ta zhe grablya, chto opisana v karte pro git.
try { & taskkill /PID $proc.Id /T /F 2>&1 | Out-Null } catch { }
Start-Sleep -Milliseconds 800
Remove-Item $lab -Recurse -Force -EA SilentlyContinue
$env:DENTART_BROWSER_MODE = $null; $env:DENTART_NO_BROWSER = $null; $env:DENTART_PORT = $null
$env:ADMIN_KEY = $null

if (-not $health) { Fail "sobrannyi exe ne otvechaet na /health - on ne zapuskaetsya (proverte hidden-imports)" }
$version = "$($health.version)"
Write-Host "   exe zhivet i predstavlyaetsya kak $version"
if ($smokeOut) { Write-Host $smokeOut.TrimEnd() }
if ($smokeCode -ne 0) { Fail "stranicy sobrannoi programmy ne otkryvayutsya - sm. vyshe (poteryan --add-data? sbit put k static?)" }

if (-not $SkipApp -and $version -ne $srcVersion) {
    Fail "exe soobshchaet $version, a v engine.py $srcVersion - sborka vzyala staryi binarnik"
}
if ($SkipApp -and $version -ne $srcVersion) {
    Write-Host "!! exe = $version, engine.py = $srcVersion. Artefakty budut nazvany po EXE ($version)." -ForegroundColor Yellow
}

# --- 3. ikonka ---
if (-not (Test-Path "build\icon.ico")) {
    if (-not (Test-Path "build")) { New-Item -ItemType Directory "build" | Out-Null }
    & ".venv-desktop\Scripts\python.exe" scripts\make_icon.py build\icon.ico
}

# --- 4. kompilyator Inno Setup ---
$iscc = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { Fail "ISCC.exe ne naiden. winget install --id JRSoftware.InnoSetup" }

& $iscc "/DAppVersion=$version" "installer\DentPilot.iss" | Out-Null
if ($LASTEXITCODE -ne 0) { Fail "ISCC upal" }

$setup = "dist\DentPilot-Setup-$version.exe"
if (-not (Test-Path $setup)) { Fail "ISCC ne sozdal $setup" }

# --- 5. zip dlya reliza ---
$zip = "dist\DentPilot-Setup-$version.zip"
Remove-Item $zip -Force -EA SilentlyContinue
Compress-Archive -Path $setup -DestinationPath $zip -CompressionLevel Fastest

# --- 6. kopiya mastera v papku vydachi klinikam ---
# Staraya versiya ryadom s novoi - eto vopros "kakoi iz nih otdavat", poetomu
# na verhnem urovne ostaetsya ROVNO ODIN fail, a proshlye uezzhayut v arhiv.
# Ne udalyaem: sborka ne dolzhna tihо unichtozhat to, chto uzhe komu-to otdano.
$copied = ""
if ($SetupDir) {
    try {
        if (-not (Test-Path $SetupDir)) { New-Item -ItemType Directory $SetupDir -Force | Out-Null }
        $name = Split-Path $setup -Leaf
        $old = Get-ChildItem $SetupDir -Filter "DentPilot-Setup-*.exe" -EA SilentlyContinue |
               Where-Object { $_.Name -ne $name }
        if ($old) {
            $arh = Join-Path $SetupDir "arhiva"
            if (-not (Test-Path $arh)) { New-Item -ItemType Directory $arh | Out-Null }
            $old | ForEach-Object { Move-Item $_.FullName (Join-Path $arh $_.Name) -Force }
            Write-Host ("   proshlye versii ubrany v arhiva\: " + (($old | ForEach-Object { $_.Name }) -join ", "))
        }
        Copy-Item $setup $SetupDir -Force
        $copied = Join-Path $SetupDir $name
    } catch {
        Write-Host ("!! kopiya v $SetupDir ne polozhena: " + $_.Exception.Message) -ForegroundColor Yellow
    }
}

$mb = { param($p) [math]::Round((Get-Item $p).Length / 1MB, 1) }
Write-Host ""
Write-Host "OK, versiya $version" -ForegroundColor Green
Write-Host ("  dist\DentPilot.exe                 {0} MB  -> asset reliza (ego kachaet self-update)" -f (& $mb "dist\DentPilot.exe"))
Write-Host ("  DentPilot-Setup-$version.exe" + (" " * [Math]::Max(1, 18 - $version.Length)) + "{0} MB  -> USB / pryamaya peredacha klinike" -f (& $mb $setup))
Write-Host ("  DentPilot-Setup-$version.zip" + (" " * [Math]::Max(1, 18 - $version.Length)) + "{0} MB  -> asset reliza (zip, chtoby ne stalo dvuh .exe)" -f (& $mb $zip))
if ($copied) { Write-Host ("  $copied" + (" " * 4) + "-> otdat klinike (odin fail, bez dist)") -ForegroundColor Cyan }
