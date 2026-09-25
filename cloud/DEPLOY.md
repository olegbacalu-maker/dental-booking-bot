# Развёртывание DentPilot Cloud

Сервер лицензий — одна программа (`cloud/`), одна база SQLite, один
администратор. Живёт на VPS за Caddy по адресу `cloud.dentpilot.md` (L10 плана,
[docs/dentpilot-2/cloud.md](../docs/dentpilot-2/cloud.md)). Всё, что здесь
описано, лежит в `deploy/`; секреты — только в `deploy/cloud.env`, которого в
репозитории нет.

**Три вещи восстанавливают сервис целиком** на любой чистой машине: файл
`cloud.env`, приватный ключ `2026a.pem` и последняя копия базы. Их хранить в
двух местах вне VPS. Потеря ключа означает новый ключ и пересборку программы
у всех клиник; потеря базы — потерю истории выдач и платежей.

## Что нужно

- VPS: 1 vCPU, 1 ГБ, Ubuntu 24.04, публичный IPv4. Десятки клиник для него — ничто.
- Домен: A-запись `cloud.dentpilot.md` → IP VPS **до** первого запуска: Caddy
  получает сертификат при первом обращении и без DNS его не получит.
- Ящик с паролем приложения (Gmail: «Пароли приложений» при включённой
  двухэтапной защите) и реквизиты банка для писем о переводе.

## 1. Машина

```
ssh root@VPS
apt update && apt install -y git ufw
curl -fsSL https://get.docker.com | sh              # docker + compose plugin
ufw allow 22 && ufw allow 80 && ufw allow 443 && ufw enable
mkdir -p /srv/dentpilot/data /srv/dentpilot/keys /var/log/dentpilot
git clone https://github.com/olegbacalu-maker/dental-booking-bot.git /srv/dentpilot/src
cd /srv/dentpilot/src/cloud/deploy
docker compose build
```

## 2. Ключ выдачи — один раз и навсегда

```
docker run --rm -v /srv/dentpilot/keys:/srv/keys dentpilot-cloud \
    python -m app.tools keygen --kid 2026a --out /srv/keys/2026a.pem
```

Команда пишет PEM с правами 0600 и печатает **одну строку** для таблицы
`KEYS` в `bot/app/core/rsa_verify.py`. Строку — в программу и пересобрать
её; PEM — скопировать на носитель вне VPS и больше никуда. ⛔ Ключ не
кладут в репозиторий, в образ, в письмо и в чат.

## 3. Секреты

```
cp cloud.env.example cloud.env && chmod 600 cloud.env
docker run --rm -it dentpilot-cloud python -m app.tools hash-password   # → DP_ADMIN_HASH
openssl rand -hex 32                                                     # → DP_SECRET
```

Заполнить в `cloud.env`: хеш, секрет, `DP_SMTP_PASS`, `DP_BANK_*`.
Комментарии в этом файле — только отдельными строками (см. шапку примера).

## 4. Первый запуск и проверка

```
docker compose up -d
docker compose exec cloud python -m app.tools check     # каждая строка ok или ⚠; ✗ — не запускаемся
curl -s https://cloud.dentpilot.md/health               # {"ok": true, ...}
```

Открыть `https://cloud.dentpilot.md/admin`, войти, завести первую клинику,
выдать пробный файл и отправить письмом на свой адрес. Письмо с вложением
`license.json`, которое принимает программа, — и есть проверка сквозняком.

Автообновление (L13) проверяется той же клиникой: активировать файл в
программе, выдать ей второй файл в админке — и в течение суток (или сразу
кнопкой «Verifică acum» на странице Licență) в карточке появится «файл у
программы», а в журнале — строка `renew`. Программа ходит на
`https://cloud.dentpilot.md/v1/license` — Caddy проксирует его вместе со всем
остальным, отдельной настройки нет.

## 5. Раз в сутки: напоминания и копия

`crontab -e` под тем пользователем, что запускает Docker; строки — в
`cron.example`: в 05:35 копия базы, в 05:50 копия увозится с машины
(`backup.sh`, настроить `BACKUP_SCP` или `BACKUP_RCLONE` в crontab), в 06:05
ежедневная задача с письмами. Ту же задачу можно запустить кнопкой в списке
клиник или рукой; второй запуск в тот же день ничего не шлёт:

```
docker compose exec cloud python -m app.jobs daily
docker compose exec cloud python -m app.jobs daily --at 2026-10-17T06:00:00Z   # разбор: что ушло бы в этот день
```

## 6. Копии и учение по восстановлению

```
docker compose exec cloud python -m app.tools backup --dir /srv/data/backups --keep 30
docker compose exec cloud python -m app.tools verify-backup /srv/data/backups/cloud-20260924-053500.db
docker compose exec cloud python -m app.tools drill         /srv/data/backups/cloud-20260924-053500.db
```

`backup` снимает согласованную копию живой базы (сервер останавливать не
нужно) и проверяет её; `verify-backup` — целостность, версия схемы, счётчики
и подпись каждого выданного файла ключом; `drill` разворачивает копию в
чистой временной папке и поднимает на ней сервер: «учение: OK» значит, что
из этой копии сервис восстанавливается.

**Учение на чистой машине** — до первого клиента, потом раз в квартал: новая
машина по шагам 1 и 3 (ключ и `cloud.env` — с носителя, не новые), копия базы
в `/srv/dentpilot/data/backups/`, `drill` по ней, затем настоящее
восстановление:

```
docker compose down
cp /srv/dentpilot/data/backups/cloud-….db /srv/dentpilot/data/cloud.db
docker compose up -d && docker compose exec cloud python -m app.tools check
```

В админке должны быть те же клиники и те же файлы выдач. То же учение делает
`cloud/tests/test_deploy.py` на каждом прогоне CI: копия живой базы, проверка,
сервер на копии, файл лицензии из копии байт в байт.

## 7. Обновление сервера

```
cd /srv/dentpilot/src && git pull
cd cloud/deploy && docker compose up -d --build
docker compose exec cloud python -m app.tools check
```

Миграции базы идут при старте (`db.py`, `SCHEMA_VERSION`). Перед обновлением
— копия (шаг 6): откат = старый образ плюс старая копия.

## 8. Без Docker

Тот же сервер под systemd: `python3 -m venv /srv/cloud/.venv`, установить
`requirements.txt`, код в `/srv/cloud`, секреты в `/srv/dentpilot/cloud.env`,
юнит `dentpilot-cloud.service` в `/etc/systemd/system/`, Caddy из пакета
(`apt install caddy`) с `Caddyfile`, где upstream `127.0.0.1:8090`. Строки
cron для этого варианта — внизу `cron.example`.

## 9. На ПК с Windows

Для шага 1 сервер может стоять на твоём компьютере: клиника с сервером не
связывается, файл идёт по почте. Что не работает без публичного адреса:
приём карт (L12), автообновление файла из программы (L13), форма пробного
периода (L14).

```
cd cloud
py -3.13 -m venv .venv && .venv\Scripts\pip install -r requirements.txt
copy deploy\cloud.env.example deploy\cloud.env       # заполнить: пути Windows, DP_SECURE_COOKIES=0, DP_BASE_URL=http://127.0.0.1:8090
.venv\Scripts\python -m app.tools keygen --kid 2026a --out C:\dentpilot\keys\2026a.pem
.\deploy\run-windows.ps1 -Check
.\deploy\run-windows.ps1                              # админка: http://127.0.0.1:8090/admin
```

В Планировщике заданий два задания раз в сутки: `run-windows.ps1 -Job daily`
и `run-windows.ps1 -Backup` (копии в `cloud\backups`, увозить на флешку или в
облачный диск). Папку с ключом и базой — вне OneDrive и прочей синхронизации.
Если компьютер был выключен несколько дней, задача при следующем запуске
шлёт письмо той строки таблицы, чьё окно сегодня, а не все пропущенные.
