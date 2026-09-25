# DentPilot Cloud — сервер лицензий

Отдельная программа (шаг 1 плана — `docs/dentpilot-2/cloud.md`): клиники,
подписки, выдача подписанного файла лицензии, письмо с ним, платежи
переводом, напоминания по датам, журнал. ⛔ Ни одного
импорта из `bot/`; общее с движком — контракт файла и `tests/fixtures/license/`.

```
cd cloud
python -m venv .venv && .venv/bin/pip install -r requirements.txt
python tests/run_tests.py                       # свой прогон, stdlib-харнес
DP_ADMIN_HASH=$(python -m app.tools hash-password) DP_LICENSE_KEY=../tests/fixtures/license/test-key.json \
  DP_MAIL_OUTBOX=./outbox python -m uvicorn app.main:app --port 8090
```

| Переменная | Что |
|---|---|
| `DP_CLOUD_DB` | путь к базе SQLite (по умолчанию `cloud.db` в текущей папке) |
| `DP_LICENSE_KEY` | приватный ключ выдачи: `.pem` (боевой) или `.json` с числами (тестовый) |
| `DP_LICENSE_KID` | имя ключа для `.pem` (у `.json` лежит внутри) |
| `DP_ADMIN_USER`, `DP_ADMIN_HASH` | администратор; хеш — `python -m app.tools hash-password` |
| `DP_SECRET` | подпись куки сессии; пусто — случайная на процесс (сессии не переживут рестарт) |
| `DP_SECURE_COOKIES` | `1` за TLS (Caddy) |
| `DP_SMTP_HOST/PORT/USER/PASS`, `DP_MAIL_FROM` | почта; без хоста письма ложатся файлами в `DP_MAIL_OUTBOX` |
| `DP_BANK_BENEFICIARY`, `DP_BANK_IBAN`, `DP_BANK_NAME`, `DP_BANK_CODE` | реквизиты в письме о переводе; без них платёж создаётся, письмо не уходит |
| `DP_MAIB_PROJECT_ID`, `DP_MAIB_PROJECT_SECRET`, `DP_MAIB_SIGNATURE_KEY` | проект maib ecommerce (L12): оплата картой по ссылке; пусто — только переводом. `DP_MAIB_BASE_URL` — адрес API, меняют только тесты |

**Ежедневная задача** — напоминания по таблице `cloud.md › «Напоминания»`
(счёт за 14 дней, за 3 дня, в день срока, накануне и в день режима чтения).
Запуск раз в сутки из cron с тем же окружением, что у сервера; второй запуск
в тот же день ничего не шлёт. Та же задача — кнопкой в списке клиник.

```
# 06:05 UTC = 09:05 Кишинёв летом; даты в файлах лицензий — UTC
5 6 * * * cd /srv/cloud && set -a && . /srv/dentpilot/cloud.env && set +a && python -m app.jobs daily >> /var/log/dentpilot-jobs.log 2>&1
# в Docker: docker exec dentpilot-cloud python -m app.jobs daily
python -m app.jobs daily --at 2026-10-17T06:00:00Z     # разбор: что ушло бы в этот день
```

**Оплата картой (L12)** — платёж с ссылкой maib: в карточке «Создать платёж»
с выбором «картой» (или «Ссылка на карту» у ожидающего перевода), письмо несёт
ссылку на hosted-страницу maib и, если есть реквизиты, перевод с тем же
reference — долг один. После оплаты maib зовёт
`POST /v1/maib/callback`; подпись проверяется, и всё равно статус
спрашивается у maib (`pay-info`) — только его `OK` продлевает срок и выдаёт
файл, второй callback ничего не делает. Тот же вопрос задают кнопка
«Проверить» и ежедневная задача — callback не обязан дойти. Статус не OK —
платёж остаётся в ожидании со словами maib в карточке; «Новая ссылка» даёт
новую попытку на тот же reference. Страницы возврата — `/pay/ok`, `/pay/fail`.
⚠️ Имена методов maib — по их документации на 25.09, сверить в песочнице
(`app/maib.py`).

**Автообновление файла (L13)** — в каждый выданный файл едет `renew`: адрес
`DP_BASE_URL/v1/license` и токен клиники (рождается с первой выдачей, дальше
один и тот же). Программа клиники раз в сутки делает `GET /v1/license?seq=N`
с `Authorization: Bearer <токен>`: 200 — файл новее `N` (тот же текст, что
скачивается), 204 — новее нет, 401 — токен не признан. След запроса — в
карточке клиники («программа спрашивала … файл у программы»), выдача файла
программе — строкой `renew` в журнале. Поле пишется только при `DP_BASE_URL`
на https (или loopback для стенда): `python -m app.tools check` говорит, что
есть.

**Прод** — по шагам в [DEPLOY.md](DEPLOY.md): VPS, Docker + Caddy, ключ,
секреты, cron, копии и учение по восстановлению, вариант без Docker и вариант
на ПК с Windows. Служебные команды: `python -m app.tools check` (окружение
готово?), `backup --dir … --keep 30`, `verify-backup ФАЙЛ`, `drill ФАЙЛ`
(учение: сервер на копии в чистой папке).

**Боевой ключ** делается один раз на сервере и никогда не покидает его:

```
python -m app.tools keygen --kid 2026a --out /srv/dentpilot/keys/2026a.pem
```

Команда печатает строку для таблицы `KEYS` в `bot/app/core/rsa_verify.py` —
её и только её кладут в программу. До этого шага лицензия в программе не
применяется вовсе (`license.applies()`).
