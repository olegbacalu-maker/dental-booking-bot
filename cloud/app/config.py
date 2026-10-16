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
# Сервер обновлений (03.10, updates.py): выпуск по тегу и атом-фид всех выпусков —
# для канала beta; меняют только тесты. RELEASES_DOWNLOAD — единственный префикс
# ссылок на файлы, который сервер отдаёт программам (и который программа примет).
RELEASES_TAG_API = env("DP_RELEASES_TAG_API",
                       "https://api.github.com/repos/olegbacalu-maker/dental-booking-bot/releases/tags/{tag}")
RELEASES_ATOM = env("DP_RELEASES_ATOM", "https://github.com/olegbacalu-maker/dental-booking-bot/releases.atom")
RELEASES_DOWNLOAD = "https://github.com/olegbacalu-maker/dental-booking-bot/releases/download/"
UPDATE_CACHE_S = int(env("DP_UPDATE_CACHE_S", "300"))   # как часто сервер обновлений спрашивает GitHub
# SMS-пакет (S3, docs/dentpilot-2/sms.md › «Сервер»): провод к sms.md знает один
# smsmd.py. Токен — с четырьмя правами (messages:send, messages:read, account:read,
# senders:read), живёт только здесь, на VPS; пусто = SMS выключены целиком
# (программе — 503 sms_unconfigured). Адрес API меняют только тесты (стенд в
# процессе теста). Секрет — часть адреса уведомлений о доставке, который Олег
# вписывает в кабинете sms.md (Settings → API): /v1/smsmd/dlr/<секрет>; пусто =
# уведомлений нет, статусы собирает только опрос.
SMSMD_TOKEN = env("DP_SMSMD_TOKEN")
SMSMD_BASE_URL = env("DP_SMSMD_BASE_URL", "https://api.sms.md/v3")
SMSMD_DLR_SECRET = env("DP_SMSMD_DLR_SECRET")
# тихие часы «с-до» по Кишинёву, страховка поверх программы; одинаковые числа = выключены (только стенд)
SMS_QUIET = env("DP_SMS_QUIET", "21-8")
# Выключатель показа (S7): токен в cloud.env нужен раньше, чем пакет увидят все — сперва
# SMS себе, потом пилотная клиника, через 30 дней уведомления — все. Пусто = предложен
# только клиникам с `sms_accounts.pilot` (Олег ставит в карточке); 1 = всем.
SMS_OFFERED = env("DP_SMS_OFFERED") == "1"
SUPPORT_PHONE = "+373 60 508 048"
# Прайс — тот же, что на сайте (dentpilot.md › #preturi, с 24.09.2026): месяц
# 499 MDL, год — 11 месячных (5 489 MDL, «o lună gratuită»). Сроки и счёт
# года — payments.MONTHS / payments.BILLED. Меняется цена — меняются сайт и
# это число вместе; у заведённой подписки своя цена в subscriptions.price.
PRICE_MONTH = 499


def _packs(raw: str) -> dict[int, int]:
    """«сегментов:лей,…» → {сегментов: лей}. Кривая пара пропускается, а не роняет старт."""
    out: dict[int, int] = {}
    for part in raw.replace(";", ",").split(","):
        units, _, price = part.strip().partition(":")
        if units.strip().isdigit() and price.strip().isdigit() and int(units) > 0 and int(price) > 0:
            out[int(units)] = int(price)
    return dict(sorted(out.items()))


# SMS-пакет — решения S0 Олега 16.10 (sms.md › «Решения S0»), каждое константой;
# правка решения = правка здесь и на сайте вместе, как у PRICE_MONTH.
# ⛔ ЦЕН В РЕПОЗИТОРИИ НЕТ — он публичный. Пополнения и цена имени живут в cloud.env:
# DP_SMS_PACKS=«штук:лей» через запятую (решение: 100/200/300/400/500, дешевле с
# объёмом), DP_SMS_NAME_PRICE — лей за год своего имени. Пусто = не продаётся
# (sms_no_packs / sms_no_name), программа говорит об этом словами.
SMS_PACKS = _packs(env("DP_SMS_PACKS"))
SMS_NAME_PRICE = int(env("DP_SMS_NAME_PRICE", "0") or "0")
SMS_NAME_DAYS = 365        # своё имя оплачивается ГОДОМ (Олег 16.10), отсчёт — с одобрения sms.md
SMS_PACK_DAYS = 0          # остаток бессрочный (Олег 16.10): 0 = не сгорает
SMS_TRIAL = True           # пробный период: SMS есть…
SMS_TRIAL_UNITS = 30       # …30 штук бесплатно, один раз (Олег 16.10)
SMS_READONLY = False       # S0 не решён: в режиме чтения по оплаченному остатку — нет (423 sms_plan)
SMS_COMMON_OK = True       # пока имя клиники не одобрено (или год не оплачен) — от общего имени (Олег 16.10)
SMS_COMMON = "DentPilot"   # общее имя отправителя на нашем аккаунте sms.md
SMS_DAILY_CAP = 300        # потолок сегментов в сутки у новой клиники; Олег меняет в карточке
SMS_LOW = 50               # «Au rămas N SMS» — письмо клинике, когда остаток опустился до порога
# Себестоимость сегмента у sms.md (их ответ 16.10, с НДС) — только для сверки
# «продано и не потрачено» против их баланса в админке; это не наша цена.
SMSMD_SEGMENT_COST = "0.30"
