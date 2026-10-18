# Build-Installer.ps1 - sobiraet vypusk DentPilot na Tauri (T9, 18.10.2026):
#   dist\DentPilot\                     - papka programmy rovno tak, kak ee kladet master
#                                         (kontrakt chastei, paragraf 1):
#       DentPilot.exe                   obolochka Tauri (shell\, cargo)
#       engine\DentPilot-Engine.exe     dvizhok papkoi (Build-Engine.ps1, PyInstaller onedir)
#   dist\DentPilot-Setup-<ver>.exe      - master ustanovki (USB, pryamaya peredacha klinike)
#   dist\DentPilot-Setup-<ver>.zip      - on zhe dlya GitHub Release: EDINSTVENNYI asset vypuska
#
# Otdelnogo DentPilot.exe v vypuske bolshe net: teper eto obolochka BEZ dvizhka,
# i obnovlyaetsya programma tolko masterom (update.py, rezhim ustanovshchika).
# Kontrakt - docs\dentpilot-2\tauri-contract.md; kak sobirat i chto proveryat -
# RELEASE.md i docs\dentpilot-2\installer.md.
#
#   .\Build-Installer.ps1            # reliznaya sborka: chistoe derevo, vse zapusheno,
#                                    # PODPIS obyazatelna (SimplySign Desktop - voiti zaranee)
#   .\Build-Installer.ps1 -NoSign    # PROBNAYA: bez podpisi, derevo mozhet byt gryaznym;
#                                    # v releases\ ne kladetsya, release.py ee ne primet
#   .\Build-Installer.ps1 -SkipApp   # upakovat uzhe sobrannyi dist\DentPilot (pravka .iss)
#
# Versiya odna: APP_VERSION iz bot\app\engine.py. Ee berut dvizhok (sync_version ->
# svoistva exe, /health), obolochka (shell\build.rs -> svoistva DentPilot.exe,
# dpShell.version) i master (/DAppVersion). Imya artefakta - iz togo, chto
# SOBRANNAYA programma govorit o sebe (/health pod obolochkoi), a ne iz engine.py:
# tak nevozmozhno vypustit "Setup-1.10.0.exe" s binarnikom 1.9.1.
# -SetupDir: kuda polozhit gotovyi master dlya klinik (pustaya stroka - ne klast).
param([switch]$NoSign, [switch]$SkipApp, [string]$SetupDir = "D:\DentProject\releases")
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Fail($msg) { Write-Host ""; Write-Host "STOP: $msg" -ForegroundColor Red; exit 1 }

$prog = "dist\DentPilot"
$shellExe = "$prog\DentPilot.exe"
$engineExe = "$prog\engine\DentPilot-Engine.exe"

# --- versiya v ishodnike (dlya sverki s tem, chto realno vnutri sborki) ---
$engine = Get-Content "bot\app\engine.py" -Raw
if ($engine -notmatch 'APP_VERSION\s*=\s*"([^"]+)"') { Fail "APP_VERSION ne naiden v bot\app\engine.py" }
$srcVersion = $Matches[1]
if ($srcVersion -notmatch '^\d+\.\d+\.\d+$') {
    Fail "APP_VERSION = '$srcVersion' - nuzhny rovno tri chisla (X.Y.Z), inache sravnenie versii u klinik lomaetsya"
}

# --- 0. podpis: reliznaya sborka bez nee NE IDET ---
# Do T9 sborka bez otpechatka shla dalshe s odnoi zheltoi strokoi "BEZ PODPISI" -
# i takoi vypusk mog uehat klinikam. Teper: bez podpisi - tolko yavnoe -NoSign,
# a release.py proveryaet podpis mastera sam i probnuyu sborku ne zal'et.
# Otpechatok zhivet v peremennoi POLZOVATELYA (sertifikat Certum s 29.09.2026).
# !! Process, zapushchennyi DO ee zapisi (staroe okno terminala, prilozhenie
# Claude), ee ne vidit - poetomu pustoe okruzhenie dobiraetsya iz reestra
# polzovatelya, a dochernie processy (Sign-File, Inno) nasleduyut zapolnennoe.
# Podrobno - Sign-File.ps1, docs/dentpilot-2/installer.md.
if (-not $env:DENTPILOT_SIGN_THUMBPRINT) {
    $env:DENTPILOT_SIGN_THUMBPRINT = [Environment]::GetEnvironmentVariable("DENTPILOT_SIGN_THUMBPRINT", "User")
}
$signOn = -not $NoSign
if ($signOn -and -not $env:DENTPILOT_SIGN_THUMBPRINT) {
    Fail "net DENTPILOT_SIGN_THUMBPRINT - reliznaya sborka tolko s podpisyu. Probnaya bez podpisi: -NoSign"
}
if ($NoSign) {
    Write-Host "!! PROBNAYA SBORKA (-NoSign): bez podpisi, NE dlya vypuska - release.py ee ne primet" -ForegroundColor Yellow
}

# --- 1. sborka: klient i dvizhok papkoi, potom obolochka ---
if ($SkipApp) {
    if (-not (Test-Path $shellExe) -or -not (Test-Path $engineExe)) { Fail "net $prog - zapustite bez -SkipApp" }
    Write-Host "!! -SkipApp: upakovyvayu uzhe lezhashchuyu papku $prog. Eto NE reliznaya sborka." -ForegroundColor Yellow
    Get-ChildItem "dist" -Filter "DentPilot-Setup-*" -EA SilentlyContinue | Remove-Item -Force
} else {
    # gryaznoe derevo => teg ne vosproizvedet binarnik, a nedodelannaya rabota
    # iz drugogo okna uedet vsem klinikam v odin klik. Probnoi sborke mozhno:
    # v vypusk ona ne popadet (podpisi net - release.py otkazhet).
    $dirty = git status --porcelain
    if ($dirty) {
        Write-Host "Nekommitnutye izmeneniya:" -ForegroundColor Yellow
        $dirty | ForEach-Object { Write-Host "   $_" }
        if ($signOn) { Fail "reliznaya sborka tolko iz chistogo dereva (zakommitte; probnaya - s -NoSign)" }
    }
    # Chistoe derevo != zapushennoe. Teg na GitHub vesitsya na origin/main, i
    # esli lokalnye kommity ne uehali - teg lyazhet na STARYI kod, a binarnik
    # budet sobran iz novogo.
    # Windows PowerShell prevrashchaet LYUBOI stderr native-komandy v oshibku, a
    # pri $ErrorActionPreference=Stop - v terminiruyushchuyu: "net seti" i "net
    # upstream" ubivali sborku vmesto predupreghdenii nizhe. try/catch vozvrashchaet
    # im zadumannoe povedenie, ne oslablyaya Fail nizhe.
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
            if ($signOn) { Fail "$ahead kommit(ov) ne zapushcheny v $upstream - teg lyazhet na chuzhoi kod. Snachala: git push" }
        }
        $behind = (git rev-list --count "HEAD..@{u}" 2>$null)
        if ([int]$behind -gt 0) {
            Write-Host "!! $upstream operezhaet vas na $behind kommit(ov) - sobiraete NE poslednii kod" -ForegroundColor Yellow
        }
    }
    # Starye artefakty - DO sborki: upavshaya sborka ne dolzhna ostavit proshlye
    # na meste (i staryi odnofailovyi dist\DentPilot.exe tozhe uhodit).
    Get-ChildItem "dist" -Filter "*.exe" -EA SilentlyContinue | Remove-Item -Force
    Get-ChildItem "dist" -Filter "*.zip" -EA SilentlyContinue | Remove-Item -Force
    if (Test-Path $prog) { Remove-Item $prog -Recurse -Force }

    # 1a. klient (vite) + dvizhok papkoi; vnutri - sync_version, PyInstaller i
    # stend protokola DP1 na sobrannom dvizhke (engine_check.py --exe)
    Write-Host "Sborka dvizhka (APP_VERSION $srcVersion) ..."
    & "$PSScriptRoot\Build-Engine.ps1"
    if ($LASTEXITCODE -ne 0) { Fail "sborka dvizhka ne prinyata (Build-Engine.ps1, sm. vyshe)" }

    # 1b. obolochka Tauri. Rust stoit na D: (D:\Rust): prilozhenie Claude i staroe
    # okno terminala peremennyh polzovatelya ne vidyat - poetomu cargo i ego papki
    # berutsya yavnymi putyami, esli okruzhenie pustoe. --locked: versii Tauri
    # zakrepleny (kontrakt, paragraf 0), i sborka ne imeet prava obnovit Cargo.lock.
    # cmd /c ... 2>&1 - cargo pishet hod sborki v stderr (sm. grablyu vyshe).
    $cargo = $env:DENTPILOT_CARGO
    if (-not $cargo) {
        $cargo = @("D:\Rust\cargo\bin\cargo.exe", "$env:USERPROFILE\.cargo\bin\cargo.exe") |
                 Where-Object { Test-Path $_ } | Select-Object -First 1
    }
    if (-not $cargo) { Fail "cargo ne naiden (D:\Rust\cargo\bin ili DENTPILOT_CARGO) - docs\dentpilot-2\tauri.md" }
    $rust = Split-Path (Split-Path (Split-Path $cargo))
    if (-not $env:CARGO_HOME) { $env:CARGO_HOME = Split-Path (Split-Path $cargo) }
    if (-not $env:RUSTUP_HOME -and (Test-Path "$rust\rustup")) { $env:RUSTUP_HOME = "$rust\rustup" }
    $env:CARGO_TARGET_DIR = "$PSScriptRoot\shell\target"
    Write-Host "Sborka obolochki (cargo build --release) ..."
    $oldTemp = $env:TEMP; $oldTmp = $env:TMP
    if (Test-Path "$rust\_tmp") { $env:TEMP = "$rust\_tmp"; $env:TMP = "$rust\_tmp" }
    try {
        cmd /c """$cargo"" build --release --locked --manifest-path ""$PSScriptRoot\shell\Cargo.toml"" 2>&1"
    } finally {
        $env:TEMP = $oldTemp; $env:TMP = $oldTmp
    }
    if ($LASTEXITCODE -ne 0) { Fail "sborka obolochki upala (cargo)" }
    $built = "shell\target\release\DentPilot.exe"
    if (-not (Test-Path $built)) { Fail "cargo ne sozdal $built" }

    # 1c. papka programmy - kak u kliniki: DentPilot.exe + engine\
    New-Item -ItemType Directory $prog | Out-Null
    Copy-Item $built $shellExe
    Copy-Item "dist\DentPilot-Engine" "$prog\engine" -Recurse
}

# --- 2. podpis OBOIH exe (Authenticode) ---
# Do dymovogo testa: proveryaetsya rovno tot fail, kotoryi uedet klinike; podpis
# menyaet bayty. Obolochka - eto ee vidit Windows (yarlyk, UAC sterozha, svoistva);
# dvizhok - eto ego vidit brandmauer (set slushaet on) i privilegirovannyi
# zapusk za UAC (privileged.py: "ispolnyaemyi fail - nash sys.executable").
# Master i deinstallyator podpisyvaet Inno toi zhe komandoi (shag 4).
if ($signOn) {
    Write-Host "Podpis obolochki i dvizhka ..."
    & "$PSScriptRoot\Sign-File.ps1" -Path $shellExe
    if ($LASTEXITCODE -ne 0) { Fail "podpis $shellExe ne udalas (SimplySign Desktop: voiti?)" }
    & "$PSScriptRoot\Sign-File.ps1" -Path $engineExe
    if ($LASTEXITCODE -ne 0) { Fail "podpis $engineExe ne udalas (SimplySign Desktop: voiti?)" }
}

# --- 3. dymovoi test: OBOLOCHKA zapuskaet dvizhok, stranicy otkryvayutsya ---
# scripts\shell_check.py: papka programmy kopiruetsya vo vremennuyu "ustanovku",
# obolochka --tray podnimaet dvizhok iz engine\, obkhod stranic (smoke_exe wall,
# potom grace na zhivoi kartoteke), vtoroi zapusk, chestnyi vyhod cherez vopros
# obolochki (kod 0, port svoboden, -wal sbroshen), snyatie obolochki gasit dvizhok.
# Laboratoriya i ee TEMP - v build\smoke (disk repozitoriya, ne perepolnennyi C);
# DENTART_DATA_DIR stend naznachaet sam - inache dvizhok ushel by v %ProgramData%.
# !! Na shage "vyhod" na sekundu poyavlyaetsya okno-vopros obolochki: stend sam
# nazhimaet "Da" po PID svoei obolochki.
Write-Host "Proverka sobrannoi programmy: obolochka + dvizhok ..."
$lab = "$PSScriptRoot\build\smoke"
New-Item -ItemType Directory -Force $lab | Out-Null
$smokeJson = "$lab\itog.json"
Remove-Item $smokeJson -Force -EA SilentlyContinue
$oldTemp = $env:TEMP; $oldTmp = $env:TMP
$env:TEMP = $lab; $env:TMP = $lab
try {
    & ".venv-desktop\Scripts\python.exe" "scripts\shell_check.py" --prog $prog --out $smokeJson
} finally {
    $env:TEMP = $oldTemp; $env:TMP = $oldTmp
}
if ($LASTEXITCODE -ne 0) { Fail "sobrannaya programma ne proshla proverku - sm. RED vyshe (poteryan --add-data? obolochka ne nashla dvizhok?)" }
if (-not (Test-Path $smokeJson)) { Fail "stend ne ostavil itoga $smokeJson" }
$smoke = Get-Content $smokeJson -Raw -Encoding UTF8 | ConvertFrom-Json
$version = "$($smoke.version)"
if (-not $version) { Fail "sobrannaya programma ne nazvala versiyu (/health)" }
Write-Host "   programma zhivet i predstavlyaetsya kak $version (obolochka $($smoke.shell_file), dvizhok $($smoke.engine_file))"
foreach ($v in @($smoke.shell_file, $smoke.engine_file, $smoke.shell_version)) {
    if ("$v" -ne $version) { Fail "versii razoshlis: /health $version, obolochka $($smoke.shell_file), dvizhok $($smoke.engine_file), dpShell $($smoke.shell_version)" }
}
if (-not $SkipApp -and $version -ne $srcVersion) {
    Fail "programma soobshchaet $version, a v engine.py $srcVersion - sborka vzyala staryi binarnik"
}
if ($SkipApp -and $version -ne $srcVersion) {
    Write-Host "!! programma = $version, engine.py = $srcVersion. Artefakty budut nazvany po PROGRAMME ($version)." -ForegroundColor Yellow
}

# --- 4. master ustanovki (Inno Setup) ---
if (-not (Test-Path "build\icon.ico")) {
    if (-not (Test-Path "build")) { New-Item -ItemType Directory "build" | Out-Null }
    & ".venv-desktop\Scripts\python.exe" scripts\make_icon.py build\icon.ico
}
$iscc = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { Fail "ISCC.exe ne naiden. winget install --id JRSoftware.InnoSetup" }

$isccArgs = @("/DAppVersion=$version")
if ($signOn) {
    # Inno podpisyvaet toi zhe komandoi i sam master, i deinstallyator
    # (SignTool/SignedUninstaller pod #ifdef SignTool v .iss). $q - kavychka,
    # $f - put k failu: ih podstavlyaet Inno, poetomu - v ODINARNYH kavychkah,
    # inache PowerShell podstavil by svoi peremennye. Nastoyashchih kavychek
    # vnutri argumenta net: PowerShell 5.1 lomaet ih pri peredache v exe.
    $isccArgs += "/DSignTool"
    $isccArgs += ('/Sdpsign=powershell.exe -NoProfile -ExecutionPolicy Bypass -File $q' + "$PSScriptRoot\Sign-File.ps1" + '$q -Path $f')
}
Write-Host "Upakovka mastera (Inno Setup) ..."
$isccOut = & $iscc @isccArgs "installer\DentPilot.iss"
$isccCode = $LASTEXITCODE
[IO.File]::WriteAllLines("$PSScriptRoot\dist\iscc.log", [string[]]@($isccOut))
if ($isccCode -ne 0) { $isccOut | Select-Object -Last 15 | ForEach-Object { Write-Host "   $_" }; Fail "ISCC upal (dist\iscc.log)" }

$setup = "dist\DentPilot-Setup-$version.exe"
if (-not (Test-Path $setup)) { Fail "ISCC ne sozdal $setup" }

# Sostav mastera - po ego zhe zhurnalu sborki ("Compressing: <fail>"), bez
# zapuska: KAZHDYI fail papki programmy vnutri, i nichego, krome nee i dvuh
# izvestnyh (demo.flag, zagruzchik WebView2). Poteryannyi _internal\ ili lishnii
# staryi exe v dist inache uvidela by tolko klinika.
# !! U faila BEZ ignoreversion ISCC dopisyvaet versiyu: "...Setup.exe   (1.3.251.23)".
$packed = @($isccOut | Where-Object { $_ -match '^\s*Compressing:\s+(.+?)(\s+\([\d.]+\))?\s*$' } |
            ForEach-Object { [IO.Path]::GetFullPath($Matches[1]) })
$progFull = [IO.Path]::GetFullPath("$PSScriptRoot\$prog")
$want = @(Get-ChildItem $prog -Recurse -File | ForEach-Object { $_.FullName })
$missing = @($want | Where-Object { $packed -notcontains $_ })
$extra = @($packed | Where-Object { -not $_.StartsWith($progFull + "\", [StringComparison]::OrdinalIgnoreCase) } |
           Where-Object { @("demo.flag", "MicrosoftEdgeWebView2Setup.exe") -notcontains (Split-Path $_ -Leaf) })
if ($missing.Count -gt 0) { Fail ("v mastere net $($missing.Count) failov programmy, naprimer " + $missing[0]) }
if ($extra.Count -gt 0) { Fail ("v master popalo chuzhoe: " + ($extra -join ", ")) }
Write-Host ("   sostav mastera: {0} failov programmy (DentPilot.exe + engine\) + demo.flag + zagruzchik WebView2" -f $want.Count)

if ($signOn -and (Get-AuthenticodeSignature -LiteralPath $setup).Status -ne "Valid") {
    Fail "master ustanovki ne podpisan: $((Get-AuthenticodeSignature -LiteralPath $setup).Status)"
}

# --- 5. zip dlya reliza: edinstvennyi asset vypuska ---
# Programma obnovlyaetsya masterom iz etogo zip (update.py: rovno odin
# DentPilot-Setup-<versiya>.exe vnutri, podpis nashim sertifikatom).
$zip = "dist\DentPilot-Setup-$version.zip"
Remove-Item $zip -Force -EA SilentlyContinue
Compress-Archive -Path $setup -DestinationPath $zip -CompressionLevel Fastest

# --- 6. kopiya mastera v papku vydachi klinikam (tolko podpisannogo) ---
# Staraya versiya ryadom s novoi - eto vopros "kakoi iz nih otdavat", poetomu
# na verhnem urovne ostaetsya ROVNO ODIN fail, a proshlye uezzhayut v arhiv.
# Ne udalyaem: sborka ne dolzhna tiho unichtozhat to, chto uzhe komu-to otdano.
# Probnaya sborka tuda ne kladetsya: nepodpisannyi master klinike ne otdaetsya.
$copied = ""
if ($SetupDir -and $signOn) {
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
$progMb = [math]::Round(((Get-ChildItem $prog -Recurse -File | Measure-Object Length -Sum).Sum) / 1MB, 1)
Write-Host ""
if ($signOn) { Write-Host "OK, versiya $version" -ForegroundColor Green }
else { Write-Host "OK, versiya $version - PROBNAYA, BEZ PODPISI (ne dlya vypuska)" -ForegroundColor Yellow }
Write-Host ("  dist\DentPilot\                   {0} MB  -> papka programmy (obolochka + engine\)" -f $progMb)
Write-Host ("  DentPilot-Setup-$version.exe" + (" " * [Math]::Max(1, 18 - $version.Length)) + "{0} MB  -> USB / pryamaya peredacha klinike" -f (& $mb $setup))
Write-Host ("  DentPilot-Setup-$version.zip" + (" " * [Math]::Max(1, 18 - $version.Length)) + "{0} MB  -> EDINSTVENNYI asset reliza (release.py)" -f (& $mb $zip))
if ($copied) { Write-Host ("  $copied" + (" " * 4) + "-> otdat klinike (odin fail, bez dist)") -ForegroundColor Cyan }
foreach ($f in @($shellExe, $engineExe, $setup)) {
    $sig = Get-AuthenticodeSignature -LiteralPath $f
    if ($sig.Status -eq "Valid") {
        Write-Host ("  podpis {0}: {1} (metka vremeni: {2})" -f (Split-Path $f -Leaf), $sig.SignerCertificate.Subject, [bool]$sig.TimeStamperCertificate) -ForegroundColor Green
    } else {
        Write-Host ("  podpis {0}: NET ({1})" -f (Split-Path $f -Leaf), $sig.Status) -ForegroundColor Yellow
    }
}
