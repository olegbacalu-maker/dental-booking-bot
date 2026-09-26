# Запуск сервера лицензий на ПК с Windows (шаг 1 без VPS: клиника с сервером не связывается,
# файл идёт по почте). Читает cloud.env из этой папки в окружение процесса и запускает нужное.
#   .\run-windows.ps1                 # сервер: http://127.0.0.1:8090/admin
#   .\run-windows.ps1 -Job daily      # ежедневная задача (Планировщик заданий: раз в сутки)
#   .\run-windows.ps1 -Backup         # копия базы в .\backups (Планировщик: раз в сутки)
#   .\run-windows.ps1 -Check          # окружение готово?
# Требуется: Python 3.13+, venv в ..\.venv (python -m venv .venv; .venv\Scripts\pip install -r requirements.txt).
param([string]$Job = "", [switch]$Backup, [switch]$Check)
$root = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $PSScriptRoot "cloud.env"
if (-not (Test-Path $envFile)) { Write-Error "нет $envFile — скопируйте cloud.env.example и заполните"; exit 1 }
Get-Content $envFile | ForEach-Object {
    $line = $_.Trim()
    if ($line -eq "" -or $line.StartsWith("#")) { return }
    $kv = $line -split "=", 2
    [Environment]::SetEnvironmentVariable($kv[0].Trim(), $kv[1].Trim(), "Process")
}
# UTF-8 режим Python: без него вывод в файл или трубу (Планировщик заданий,
# перенаправление) идёт в cp1251, и первая румынская буква (ă, ț) роняет
# задачу — в консоли этого не видно. Проверено прогоном cloud/tests на ПК 25.09.
$env:PYTHONUTF8 = "1"
$py = Join-Path $root ".venv\Scripts\python.exe"
Set-Location $root
if ($Check)        { & $py -m app.tools check; exit $LASTEXITCODE }
if ($Backup)       { & $py -m app.tools backup --dir (Join-Path $root "backups") --keep 30; exit $LASTEXITCODE }
if ($Job -ne "")   { & $py -m app.jobs $Job; exit $LASTEXITCODE }
& $py -m uvicorn app.main:app --host 127.0.0.1 --port 8090
