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

## 0. Боевой сервер (с 26.09.2026)

Contabo Cloud VPS 4, отдельная машина (не общая с другими проектами: ключ
выдачи не должен быть досягаем чужим CI или чужим `docker`), Ubuntu 24.04,
`79.143.180.16`, A-запись `cloud.dentpilot.md` в Cloudflare. Шаг 1 на нём уже
сделан 26.09 — ниже он записан так, как делался, чтобы повторить на новой
машине. Грабли, которых в первой версии этого файла не было, — все с живого
сервера (своего и соседнего проекта на том же Contabo):

- ⛔ **Вход по паролю образ Contabo включает сам**: `sshd_config.d/50-cloud-init.conf`
  с `PasswordAuthentication yes`, а sshd берёт ПЕРВОЕ значение ключа. Правка
  `sshd_config` поэтому ничего не выключает; выключает файл с именем `00-…`.
  Проверять `sshd -T`, не `sshd -t` (второй только синтаксис).
- ⛔ **Облако Cloudflare у `cloud` — серое (DNS only).** Оранжевое поставило бы
  адреса Cloudflare перед Caddy: сертификат не выпустится, а лимит попыток
  входа и формы `/proba` видел бы всех посетителей одним адресом.
- ⛔ **AAAA-запись для `cloud` не заводить.** Сеть compose — только IPv4, и
  соединение по IPv6 Docker проводит через свой прокси, подменяя адрес
  клиента адресом моста: те же лимиты снова видят всех одним человеком.
- ⚠️ **Порты, опубликованные Docker, обходят ufw.** Наружу публикуется только
  Caddy (80/443); сервер на 8090 — никогда (так и стоит в `docker-compose.yml`).
- ⚠️ **Часовой пояс образа — Europe/Berlin.** Даты сервера и строки
  `cron.example` — UTC, поэтому машина переводится на UTC; `/etc/timezone`
  `timedatectl` не трогает — править отдельно.
- ⚠️ **Скрипт, отданный по `ssh host "bash -s"`, может съесть сам себя**: первая
  команда, читающая stdin (`docker compose exec -T`, `apt` без `< /dev/null`),
  проглатывает остаток, и bash выходит с кодом 0. Команды — аргументом ssh
  или файлом с `< /dev/null`.
- ⚠️ **Docker обновляет только `apt upgrade`** — unattended-upgrades берут
  лишь пакеты безопасности Ubuntu. Раз в месяц-два руками, со снимком до.
- **Копии у провайдера — дополнение, не замена.** Auto Backup Contabo (диск
  целиком, 10 дней) спасает от умершего диска и неудачного обновления, но
  живёт в том же аккаунте; копия базы увозится с машины (шаг 5), ключ — на
  носителе (шаг 2). Перед обновлением сервера — ручной снимок в панели.

## 1. Машина

```
ssh root@VPS                      # ключом: ключ кладётся при заказе или сразу после
# вход только по ключу (см. «Боевой сервер»: 00- читается раньше 50-cloud-init.conf)
printf 'PasswordAuthentication no\nKbdInteractiveAuthentication no\nPermitRootLogin prohibit-password\n' \
    > /etc/ssh/sshd_config.d/00-hardening.conf
sshd -t && systemctl reload ssh && sshd -T | grep -E '^(passwordauthentication|permitrootlogin) '
# ⚠️ новым окном проверить вход по ключу, и только потом закрывать это
timedatectl set-timezone Etc/UTC && echo Etc/UTC > /etc/timezone && systemctl restart cron
apt update && apt install -y git ufw fail2ban < /dev/null
ufw default deny incoming && ufw allow 22/tcp && ufw allow 80/tcp && ufw allow 443/tcp && ufw --force enable
# Docker — из репозитория Docker (docs.docker.com › Install on Ubuntu), не скриптом
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
gpg --show-keys --with-fingerprint /etc/apt/keyrings/docker.asc   # сверить: 9DC8 5822 9FC7 DD38 854A E2D8 8D81 803C 0EBF CD88
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
    > /etc/apt/sources.list.d/docker.list
apt update < /dev/null && apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin < /dev/null
printf '{ "log-driver": "json-file", "log-opts": { "max-size": "10m", "max-file": "3" } }\n' \
    > /etc/docker/daemon.json && systemctl restart docker      # иначе логи контейнеров растут без края
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

Декларация поставщика (закон 195): подписанный PDF — в `/srv/dentpilot/data/declaratie-195.pdf`
(в контейнере `/srv/data/declaratie-195.pdf`, так и стоит в `cloud.env.example`). Как
его сделать и подписать — `docs/site/README.md` › «Договор и декларация». Файл читается
при каждом письме: положить можно в любой момент, без перезапуска; пока его нет,
письма с файлом лицензии уходят без декларации, и `check` об этом предупреждает.

Заявки на пробный (L14 и из программы, `/v1/trial`): `DP_TRIAL_MODE=auto` —
решение Олега 26.09, так стоит в `cloud.env.example`: файл выдаётся сразу, и
программа клиники включается в момент отправки заявки. `approve` — заявка
ждёт кнопки «Выдать» в админке, программа включается сама через минуту после
неё. Режим меняется строкой в `cloud.env` и `docker compose up -d`. Новый
компьютер той же клиники активируется кодом, который сервер шлёт на её e-mail
(`/v1/verify`) — нужна работающая почта (`DP_SMTP_*`): без неё программа
предложит файл из письма. Пробный — месяц
(`TRIAL_DAYS = 30`, как «Prima lună — gratuită» на сайте). Ссылка на
`https://cloud.dentpilot.md/proba` в карточке цены сайта готова в ветке
`draft/cloud-legal` репозитория сайта и публикуется в день запуска
сервера (`docs/site/README.md`); письма о заявках приходят на `DP_TRIAL_NOTIFY`.

Карты (L12): в кабинете maibmerchants завести проект, взять `Project ID`,
`Project Secret` и `Signature Key` → `DP_MAIB_*`; там же указать адреса
возврата и callback — `https://cloud.dentpilot.md/pay/ok`, `/pay/fail`,
`/v1/maib/callback` (сервер шлёт их и в каждом платеже). Пока три значения
пусты, платежи идут только переводом, и это не ошибка. ⚠️ Перед боевым
включением прогнать один платёж в песочнице maib и сверить имена полей с
`app/maib.py`: документация читалась 25.09 по памяти, без доступа к сайту.

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

⚠️ **Восстановление откатывает номера выдач.** Копия — до суток назад, и файлы,
выданные после неё, сервер забывает; следующая выдача получит номер, который
у клиники УЖЕ стоит, и программа такой файл не примет (берёт только номер
выше). После любого восстановления — хоть из копии базы, хоть из Auto Backup
Contabo — сверить выдачи последних суток с отправленными письмами в Gmail и
выдать недостающим клиникам файл заново: номер у сервера пойдёт дальше.

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

`run-windows.ps1` включает UTF-8 режим Python (`PYTHONUTF8=1`): без него вывод
в файл или трубу идёт в cp1251, и первая румынская буква роняет задачу —
в консоли этого не видно (так краснели 11 проверок `cloud/tests` на ПК 25.09).

В Планировщике заданий два задания раз в сутки: `run-windows.ps1 -Job daily`
и `run-windows.ps1 -Backup` (копии в `cloud\backups`, увозить на флешку или в
облачный диск). Папку с ключом и базой — вне OneDrive и прочей синхронизации.
Если компьютер был выключен несколько дней, задача при следующем запуске
шлёт письмо той строки таблицы, чьё окно сегодня, а не все пропущенные.
