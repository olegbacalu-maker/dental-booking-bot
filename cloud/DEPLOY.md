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
её; PEM — скопировать на носитель вне VPS и больше никуда. Строка потерялась —
`docker compose exec cloud python -m app.tools pubkey` печатает её снова по
ключу из `DP_LICENSE_KEY` (только публичную часть).

⚠️ Строка в программе и есть включатель лицензии: пока таблица `KEYS` пуста,
exe лицензию не проверяет вовсе (`license.applies()`). Первая версия с ключом
у новой установки открывает страницу активации, а у клиники, которая уже
работает, — 14 дней льготы с баннером, потом режим чтения, пока программа не
активирована (заявкой со страницы активации, кодом или файлом). ⛔ Ключ не
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

### Кабинет клиники (шаг 3, 01.10): OAuth-клиент Google

Кабинет `/cont` входит через Google (OpenID Connect). Нужны две строки в
`cloud.env` — `DP_GOOGLE_CLIENT_ID` и `DP_GOOGLE_CLIENT_SECRET`; их выдаёт
консоль Google Cloud один раз на проект. Пока они пусты, сервер работает без
кабинета: `/cont` говорит «не настроен», `/auth/google` отвечает 503, всё
остальное как прежде. Паролей клиник на сервере нет: вход держит Google, у
нас — e-mail, имя и идентификатор аккаунта (политика § 5). Scopes только
`openid`, `email`, `profile` — они «non-sensitive», проверку приложения
Google для них не требует, лимита на число пользователей нет.

1. Войти в <https://console.cloud.google.com> ящиком `dentpilotpro@gmail.com`
   (проект живёт под этим аккаунтом; личный ящик — тоже годится, но потом
   переносить). Вверху «Select a project › New project»: имя `DentPilot`,
   без организации → Create, выбрать его.
2. Слева «APIs & Services › OAuth consent screen» — с 2025 это страница
   «Google Auth Platform». Кнопка «Get started»: App name `DentPilot`,
   User support email — `dentpilotpro@gmail.com`; Audience — **External**
   (Internal есть только у Workspace); Contact information — тот же ящик;
   согласиться с политикой → Create.
3. «Branding»: App domain — Home page `https://dentpilot.md`, Privacy
   policy `https://dentpilot.md/privacy.html`, Terms of service
   `https://dentpilot.md/termeni.html`; Authorized domains —
   `dentpilot.md`. Логотип НЕ загружать: с логотипом Google требует
   проверку бренда, без него — нет. Save.
4. «Data Access › Add or remove scopes»: отметить `.../auth/userinfo.email`,
   `.../auth/userinfo.profile` и `openid` (все три в блоке non-sensitive)
   → Update → Save. Больше ничего не добавлять: любой другой scope
   включает проверку приложения.
5. «Audience»: Publishing status → **Publish app** → Confirm. Пока статус
   «Testing», входить могут только ящики из списка Test users, клиника
   получила бы «Access blocked». Проверки Google после публикации для этих
   scopes не будет.
6. «Clients › + Create client»: Application type **Web application**, Name
   `DentPilot Cloud`; Authorized JavaScript origins — можно не заполнять;
   Authorized redirect URIs → `+ Add URI` →
   `https://cloud.dentpilot.md/auth/google/callback` — ровно так: https,
   без слеша в конце, без www. Create. Окно показывает **Client ID**
   (`…apps.googleusercontent.com`) и **Client secret** (`GOCSPX-…`): секрет
   виден один раз — скопировать сразу (или «Download JSON» и хранить его
   там же, где `cloud.env` и ключ выдачи). Потом секрет можно только
   пересоздать (Reset secret), старый перестанет работать.
7. На сервере вписать оба значения в `/srv/dentpilot/src/cloud/deploy/cloud.env`
   (`chmod 600`, не через чат и не в git), затем `docker compose up -d` и
   `docker compose exec cloud python -m app.tools check` — строка
   «кабинет клиники …: вход через Google, redirect URI
   https://cloud.dentpilot.md/auth/google/callback» обязана совпасть с п. 6
   символ в символ: расхождение даёт у Google `redirect_uri_mismatch`.
8. Проверка сквозняком: открыть `https://cloud.dentpilot.md/cont`, нажать
   «Continuați cu Google», выбрать свой ящик — должна открыться
   регистрация; зарегистрировать тестовую клинику, в админке её «Скрыть» и
   «Отвязать» запись. Ошибка «Access blocked: … has not completed the Google
   verification process» означает, что п. 5 не сделан; «invalid_client» —
   опечатка в id или секрете.

⚠️ Секрет клиента и `cloud.env` — те же правила, что у ключа выдачи: копия
вне сервера, в репозиторий и образ не попадает. Смена домена кабинета =
новая строка redirect URI в п. 6 и `DP_BASE_URL` — иначе вход ломается
молча для всех клиник.

## 4. Первый запуск и проверка

```
docker compose up -d
docker compose exec cloud python -m app.tools check     # каждая строка ok или ⚠; ✗ — не запускаемся
curl -s https://cloud.dentpilot.md/health               # {"ok": true, ...}
```

Открыть `https://cloud.dentpilot.md/admin`, войти, завести первую клинику,
выдать пробный файл и отправить письмом на свой адрес. Письмо с вложением
`license.json`, которое принимает программа, — и есть проверка сквозняком.

Кабинет (шаг 3): открыть `https://cloud.dentpilot.md/cont`, войти своим
Google-ящиком, зарегистрировать тестовую клинику — в кабинете должен
появиться тот же `license.json`, что в её карточке в админке, а кнопка
«Descarcă DentPilot» (`/descarca`) — вести на zip последнего выпуска с
GitHub. Потом в карточке «Скрыть» заявку и «Отвязать» запись.

Автообновление (L13) проверяется той же клиникой: активировать файл в
программе, выдать ей второй файл в админке — и в течение суток (или сразу
кнопкой «Verifică acum» на странице Licență) в карточке появится «файл у
программы», а в журнале — строка `renew`. Программа ходит на
`https://cloud.dentpilot.md/v1/license` — Caddy проксирует его вместе со всем
остальным, отдельной настройки нет.

## 5. Раз в сутки: напоминания и копия

`crontab -e` под тем пользователем, что запускает Docker; строки — в
`cron.example`: в 05:35 копия базы, в 06:05 ежедневная задача с письмами.
Копию с машины **забирает ПК Олега** (решение 02.10, как у Cahul):
`deploy/pull-backups.ps1` в Планировщике заданий Windows («DentPilot Cloud
backup pull», 09:45 ежедневно) копирует новые `cloud-*.db`, `cloud.env` и
ключ выдачи в `D:\DentProject\backups\cloud\`, проверяет последнюю копию
`verify-backup` ключом и ставит на сервере отметку `/srv/dentpilot/data/last-pull`;
`app.tools check` предупреждает, когда отметке больше трёх дней — выключенный
ПК виден заранее. Вариант «сервер сам увозит» (`backup.sh` с `BACKUP_SCP`
или `BACKUP_RCLONE`, строка 05:50 в `cron.example`) остаётся для машины без
ПК; на боевом сервере эта строка снята. Ту же задачу можно запустить кнопкой
в списке клиник или рукой; второй запуск в тот же день ничего не шлёт:

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

⚠️ **Изменился `Caddyfile` — пересоздать контейнер Caddy**, `up -d` его не
трогает, а `caddy reload` перечитывает СТАРЫЙ файл: `Caddyfile` подключён
в контейнер одиночным файлом, и `git pull` кладёт на его место новый inode,
который контейнер не видит (01.10: политика Referrer осталась прежней после
reload). Правильно: `docker compose up -d --force-recreate caddy` —
сертификаты живут в томе, простой секунды. Проверить:
`curl -sI https://cloud.dentpilot.md/health | grep -i referrer-policy`.

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
