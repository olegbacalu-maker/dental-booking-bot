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
SITE_URL = "https://dentpilot.md"           # сайт: условия и политика, на которые ссылается форма
# Реквизиты для перевода — в письме клинике. Пусто = письмо с реквизитами не
# отправляется (платёж при этом создаётся), пока Олег не заполнит окружение.
BANK = {"beneficiary": env("DP_BANK_BENEFICIARY"), "iban": env("DP_BANK_IBAN"),
        "bank": env("DP_BANK_NAME"), "code": env("DP_BANK_CODE")}
# Оплата картой через maib (L12): проект из кабинета maibmerchants. Все три
# пусты = карт нет, платежи только переводом; адрес меняют только тесты.
MAIB_BASE_URL = env("DP_MAIB_BASE_URL", "https://api.maibmerchants.md/v1")
MAIB_PROJECT_ID = env("DP_MAIB_PROJECT_ID")
MAIB_PROJECT_SECRET = env("DP_MAIB_PROJECT_SECRET")
MAIB_SIGNATURE_KEY = env("DP_MAIB_SIGNATURE_KEY")   # подпись callback
# Форма пробного периода (L14): approve — заявка ждёт админа, auto — файл сразу.
# Уведомление о заявке — на этот ящик; пусто = SUPPORT_EMAIL.
TRIAL_MODE = env("DP_TRIAL_MODE", "approve")
TRIAL_NOTIFY = env("DP_TRIAL_NOTIFY") or SUPPORT_EMAIL
# Декларация поставщика по закону 195 — PDF, подписанный Олегом (текст —
# docs/site/declaratie-195.html). Едет вложением в каждое письмо с файлом
# лицензии; пусто или не PDF — письма уходят без неё, и `tools check` это говорит.
DECLARATION = env("DP_DECLARATION")
# Кабинет клиники (шаг 3, 01.10): вход через Google — OAuth-клиент «Web
# application» из консоли Google Cloud, redirect URI = DP_BASE_URL/auth/google/callback
# (DEPLOY.md § 3). Оба пусты = кабинет закрыт: /cont говорит об этом словами.
GOOGLE_CLIENT_ID = env("DP_GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = env("DP_GOOGLE_CLIENT_SECRET")
# адреса Google OpenID Connect; меняют только тесты (стенд Google в процессе теста)
GOOGLE_AUTH_URL = env("DP_GOOGLE_AUTH_URL", "https://accounts.google.com/o/oauth2/v2/auth")
GOOGLE_TOKEN_URL = env("DP_GOOGLE_TOKEN_URL", "https://oauth2.googleapis.com/token")
# Скачивание с сайта (L15): /descarca спрашивает у API GitHub последний выпуск и
# ведёт на его установщик. Репозиторий — тот же, что REPO в bot/app/repo.py
# (импорта из bot/ здесь нет — равенство держит cloud/tests). Адрес API меняют
# только тесты; страница выпусков — запасной адрес, когда API молчит.
RELEASES_API = env("DP_RELEASES_API",
                   "https://api.github.com/repos/olegbacalu-maker/dental-booking-bot/releases/latest")
RELEASES_PAGE = "https://github.com/olegbacalu-maker/dental-booking-bot/releases/latest"
SUPPORT_PHONE = "+373 60 508 048"
# Прайс — тот же, что на сайте (dentpilot.md › #preturi, с 24.09.2026): месяц
# 499 MDL, год — 11 месячных (5 489 MDL, «o lună gratuită»). Сроки и счёт
# года — payments.MONTHS / payments.BILLED. Меняется цена — меняются сайт и
# это число вместе; у заведённой подписки своя цена в subscriptions.price.
PRICE_MONTH = 499
