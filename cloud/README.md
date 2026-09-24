# DentPilot Cloud — сервер лицензий

Отдельная программа (шаг 1 плана — `docs/dentpilot-2/cloud.md`): клиники,
подписки, выдача подписанного файла лицензии, письмо с ним. ⛔ Ни одного
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

**Боевой ключ** делается один раз на сервере и никогда не покидает его:

```
python -m app.tools keygen --kid 2026a --out /srv/dentpilot/keys/2026a.pem
```

Команда печатает строку для таблицы `KEYS` в `bot/app/core/rsa_verify.py` —
её и только её кладут в программу. До этого шага лицензия в программе не
применяется вовсе (`license.applies()`).
