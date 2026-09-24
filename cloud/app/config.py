"""Настройки сервера — только из окружения (docs/dentpilot-2/cloud.md › «Сервер»).

⛔ Ни один секрет не лежит в коде и не читается из файла в дереве: приватный
ключ — путь в DP_LICENSE_KEY, хеш пароля администратора — DP_ADMIN_HASH,
подпись куки — DP_SECRET. Пустая переменная означает «нет», а не умолчание,
и старт об этом говорит в логе, а не молчит.
"""
import os
import pathlib


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


DB_PATH = pathlib.Path(env("DP_CLOUD_DB", "cloud.db"))
LICENSE_KEY = env("DP_LICENSE_KEY")          # .pem (боевой) или .json с числами (тесты)
LICENSE_KID = env("DP_LICENSE_KID")          # kid для .pem; у .json берётся из файла
ADMIN_USER = env("DP_ADMIN_USER", "admin")
ADMIN_HASH = env("DP_ADMIN_HASH")            # pbkdf2-sha256$iters$salt$hex — python -m app.tools hash-password
SECRET = env("DP_SECRET")                    # подпись куки; пусто — случайный на процесс
SECURE_COOKIES = env("DP_SECURE_COOKIES") == "1"
BASE_URL = env("DP_BASE_URL", "https://cloud.dentpilot.md")
SMTP_HOST = env("DP_SMTP_HOST")
SMTP_PORT = int(env("DP_SMTP_PORT", "587") or "587")
SMTP_USER = env("DP_SMTP_USER")
SMTP_PASS = env("DP_SMTP_PASS")
MAIL_FROM = env("DP_MAIL_FROM", SMTP_USER or "dentpilotpro@gmail.com")
MAIL_OUTBOX = env("DP_MAIL_OUTBOX")          # папка сухого прогона: письма ложатся файлами
SUPPORT_EMAIL = "dentpilotpro@gmail.com"
SUPPORT_PHONE = "+373 60 508 048"
