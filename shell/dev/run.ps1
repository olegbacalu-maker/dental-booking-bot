# Оболочка из исходников: сборка cargo и запуск с движком разработки.
#
#   powershell -File shell\dev\run.ps1                 # настоящий лаунчер bot\desktop.py
#                                                      (⚠️ только движок, говорящий DP1, — ветка Т5)
#   powershell -File shell\dev\run.ps1 -Fake demo      # подставной движок (shell\dev\fake_engine.py)
#   powershell -File shell\dev\run.ps1 -Fake bridge    # настоящий сервер программы под подставным DP1
#   powershell -File shell\dev\run.ps1 -Release -NoRun # только сборка release
#
# ⛔ Порт 8088 — живая установка Олега: здесь по умолчанию 8094.
# ⚠️ Профиль окна и shell.json — в -Root (по умолчанию sandbox\tauri-shell-run):
# окно стенда не делит профиль WebView2 с установленной программой.
# ⚠️ Приложение Claude не видит переменных пользователя: Rust берётся с D:
# явными путями, а не из PATH.
param(
    [string]$Fake = "",
    [int]$Port = 8094,
    [switch]$Release,
    [switch]$NoRun,
    [string]$Root = "D:\DentProject\sandbox\tauri-shell-run",
    [string]$Target = ""
)
$ErrorActionPreference = "Stop"
if ($Port -eq 8088) { throw "8088 - instalarea vie; alegeti alt port" }
$app = (Resolve-Path "$PSScriptRoot\..\..").Path
if (-not $Target) { $Target = Join-Path $Root "target" }

$env:RUSTUP_HOME = "D:\Rust\rustup"
$env:CARGO_HOME = "D:\Rust\cargo"
$env:TMP = "D:\Rust\_tmp"; $env:TEMP = "D:\Rust\_tmp"
$env:CARGO_TARGET_DIR = $Target
$cargo = "D:\Rust\cargo\bin\cargo.exe"
$cargoArgs = @("build", "--manifest-path", "$app\shell\Cargo.toml")
if ($Release) { $cargoArgs += "--release" }
& $cargo @cargoArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
if ($NoRun) { exit 0 }

$exe = Join-Path $Target ($(if ($Release) { "release" } else { "debug" }) + "\DentPilot.exe")
New-Item -ItemType Directory -Force "$Root\data" | Out-Null
$env:DENTPILOT_DEV_APP = $app
$env:DENTART_PORT = "$Port"
$env:DENTART_DATA_DIR = "$Root\data"
$env:DENTART_PROFILE_DIR = "$Root\webview"
$env:DENTART_UPDATE_CHECK = "off"
if ($Fake) {
    $env:DENTPILOT_DEV_ENGINE = "$app\shell\dev\fake_engine.py"
    $env:DP_FAKE = $Fake
} else {
    Remove-Item Env:DENTPILOT_DEV_ENGINE -ErrorAction SilentlyContinue
}
Write-Host "DentPilot.exe: $exe  port $Port  data $Root"
& $exe
