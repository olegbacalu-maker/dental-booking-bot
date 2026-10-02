# КОДИРОВКА: файл сохранён как UTF-8 С BOM, и так и должно остаться. Windows
# PowerShell 5.1 читает .ps1 без BOM в системной кодировке (cp1251): первая
# кириллическая буква в кавычках — ошибка разбора до первой строки (грабля
# Cahul, M13).
#
# DentPilot Cloud — вывоз копий базы с сервера лицензий на ПК Олега (02.10).
#
# Тот же приём, что у Cahul (pull-backups.ps1): сервер делает копию сам
# (cron 05:35 UTC, app.tools backup), а ПК раз в день её ЗАБИРАЕТ. Пока копия
# лежит только на сервере, это не бэкап: умерший диск Contabo уносит и базу, и
# её историю. Решение Олега 02.10: вывозить на ПК, как у Cahul, — данные там
# не особые (клиники, выдачи, платежи), а DEPLOY.md § 6 требует три вещи вне
# сервера: копия базы, cloud.env и ключ выдачи — все три забираются здесь.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File D:\DentProject\app\cloud\deploy\pull-backups.ps1
#
# Что делает: копирует новые cloud-*.db, сверяет размеры с тем, что говорит
# сервер (обрезанный файл выглядит как копия и восстанавливается в ничто),
# забирает cloud.env и 2026a.pem, проверяет последнюю копию через
# app.tools verify-backup (целостность, схема, подписи выдач ключом), чистит
# старые локальные, и ставит отметку /srv/dentpilot/data/last-pull на
# сервере — `app.tools check` предупреждает, когда отметка старше трёх дней:
# выключенный ПК заметен, а не обнаруживается в день аварии.
# Задача планировщика: «DentPilot Cloud backup pull», 09:45 ежедневно.

param(
    [string]$Destination = "D:\DentProject\backups\cloud",
    [string]$Server      = "root@79.143.180.16",
    [string]$RemoteDir   = "/srv/dentpilot/data/backups",
    [string]$Marker      = "/srv/dentpilot/data/last-pull",
    [string]$CloudDir    = "D:\DentProject\app\cloud",
    [int]$KeepLocal      = 60
)

$ErrorActionPreference = "Stop"
$log = Join-Path $Destination "pull.log"

function Say([string]$text) {
    $line = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $text
    Write-Output $line
    try { Add-Content -Path $log -Value $line -Encoding UTF8 } catch {}
}

if (-not (Test-Path $Destination)) {
    New-Item -ItemType Directory -Path $Destination | Out-Null
}
Say "pull starting"

# ---- копии базы: что есть на сервере ----
$remote = ssh -o BatchMode=yes -o ConnectTimeout=15 $Server "ls -1 $RemoteDir/cloud-*.db 2>/dev/null"
if ($LASTEXITCODE -ne 0) { Say "ОШИБКА: не удалось получить список копий на $Server"; exit 1 }
$names = @($remote -split "`n" | Where-Object { $_ -match '\S' } | ForEach-Object { Split-Path $_.Trim() -Leaf })
if ($names.Count -eq 0) { Say "ОШИБКА: на сервере нет ни одной копии (app.tools backup ещё не бежал?)"; exit 1 }
Say ("на сервере копий: {0}" -f $names.Count)

$copied = 0
foreach ($name in $names) {
    $local = Join-Path $Destination $name
    if (Test-Path $local) { continue }
    scp -o BatchMode=yes -q "${Server}:${RemoteDir}/${name}" $local
    if ($LASTEXITCODE -ne 0) {
        # полукопия хуже отсутствующей: выглядит как бэкап, а восстанавливается в ничто
        if (Test-Path $local) { Remove-Item $local -Force }
        Say "ОШИБКА: копирование $name не удалось"; exit 1
    }
    $copied++
    Say "скопировано $name"
}

# размеры — по словам сервера: обрезанную передачу список файлов не покажет
$remoteSizes = ssh -o BatchMode=yes $Server "stat -c '%n %s' $RemoteDir/cloud-*.db"
foreach ($line in ($remoteSizes -split "`n" | Where-Object { $_ -match '\S' })) {
    $parts = $line.Trim() -split '\s+'
    $name = Split-Path $parts[0] -Leaf
    $expected = [int64]$parts[1]
    $local = Join-Path $Destination $name
    if (-not (Test-Path $local)) { continue }
    $actual = (Get-Item $local).Length
    if ($actual -ne $expected) {
        Remove-Item $local -Force
        Say "ОШИБКА: $name пришёл как $actual байт, сервер говорит $expected — удалён, повтор завтра"; exit 1
    }
}

# ---- cloud.env и ключ выдачи: две другие вещи для восстановления (DEPLOY.md § 6) ----
$keys = Join-Path $Destination "keys"
if (-not (Test-Path $keys)) { New-Item -ItemType Directory -Path $keys | Out-Null }
scp -o BatchMode=yes -q "${Server}:/srv/dentpilot/src/cloud/deploy/cloud.env" (Join-Path $Destination "cloud.env")
if ($LASTEXITCODE -ne 0) { Say "ОШИБКА: cloud.env не скопирован"; exit 1 }
scp -o BatchMode=yes -q "${Server}:/srv/dentpilot/keys/2026a.pem" (Join-Path $keys "2026a.pem")
if ($LASTEXITCODE -ne 0) { Say "ОШИБКА: ключ выдачи не скопирован"; exit 1 }

# ---- проверка последней копии: целостность, схема, подписи выдач ключом ----
$newest = Get-ChildItem (Join-Path $Destination "cloud-*.db") | Sort-Object Name | Select-Object -Last 1
$py = Join-Path $CloudDir ".venv\Scripts\python.exe"
if ((Test-Path $py) -and $newest) {
    $env:PYTHONUTF8 = "1"
    $env:DP_LICENSE_KEY = Join-Path $keys "2026a.pem"
    $env:DP_LICENSE_KID = "2026a"
    Push-Location $CloudDir
    try {
        $out = & $py -m app.tools verify-backup $newest.FullName 2>&1 | Out-String
    } finally { Pop-Location }
    if ($LASTEXITCODE -ne 0) { Say ("ОШИБКА: копия {0} не прошла проверку:`n{1}" -f $newest.Name, $out.Trim()); exit 1 }
    Say ("проверена {0}: {1}" -f $newest.Name, (($out -split "`n" | Where-Object { $_ -match 'клиник|подписи' }) -join '; ').Trim())
} else {
    Say "проверка пропущена: нет $py — копия лежит, но не проверена"
}

# ---- старые локальные: сервер держит 30, ПК — больше ----
$all = Get-ChildItem (Join-Path $Destination "cloud-*.db") | Sort-Object Name
if ($all.Count -gt $KeepLocal) {
    $all | Select-Object -First ($all.Count - $KeepLocal) | ForEach-Object { Remove-Item $_.FullName -Force; Say ("удалена старая {0}" -f $_.Name) }
}

# ---- отметка на сервере: «копии вывезены тогда-то»; check её читает ----
ssh -o BatchMode=yes $Server "date -u +%Y-%m-%dT%H:%M:%SZ > $Marker"
if ($LASTEXITCODE -ne 0) { Say "ОШИБКА: отметка на сервере не поставлена"; exit 1 }
Say ("готово: новых {0}, всего локально {1}" -f $copied, (Get-ChildItem (Join-Path $Destination "cloud-*.db")).Count)
