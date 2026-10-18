"""Уведомления у часов (Tauri, пункт Т8): что сказать — решает программа,
показывает оболочка.

Контракт — docs/dentpilot-2/tauri-contract.md § 4. Три уведомления (Олег
18.10): вышло обновление, лицензия кончается, SMS осталось мало. Про пациентов
— ничего: программа не знает, что пациент пришёл.

⭐ Сервер НЕ помнит, что показано, — помнит оболочка (`shell.json` по учётке
Windows). Поэтому `id` детерминирован: при неизменных данных он тот же на
каждом опросе и меняется ровно тогда, когда событие надо показать СНОВА —
новая версия, новый срок лицензии или следующий порог, новый эпизод «мало
SMS» (после пополнения).
⛔ Без сессии и без данных пациентов: маршрут отвечает оболочке этого ПК, а
не человеку. Состояние читается из памяти процесса (`update.STATE`,
`license.current()`, счёт SMS) — база не трогается, поэтому ответ есть и в
режиме восстановления, где она не открыта.
⛔ Тексты — румынские, с действием и с ИМЕНЕМ экрана, как его видно в Setări:
клиника читает уведомление и идёт туда глазами.
"""
from __future__ import annotations

import hmac
import os
from datetime import timedelta

from .. import engine as eng
from .. import sidecar
from .. import update as upd
from . import license as lic
from . import sms_loop
from .auth import client_is_local

V = 1                                     # версия контракта (`v` ответа)
LICENSE_DAYS = (7, 1)                     # за сколько дней до конца (Олег 18.10)
OPEN_UPDATE = "/admin/settings/system"
OPEN_LICENSE = "/admin/license"
OPEN_SMS = "/admin/settings/sms"


def _stamp(dt) -> str:
    """Время в ключе: UTC без двоеточий — `id` разбирать не придётся."""
    return lic.st.fmt(dt).replace("-", "").replace(":", "")


def update_item() -> dict | None:
    """Вышла версия новее, и её можно поставить. Версия, объявленная без
    файла (`asset_pending` у собранной программы), — ещё не повод: экран
    Stare sistem в этот момент говорит «reverificăm automat»."""
    if not upd.newer_available() or (upd.asset_pending() and upd.is_desktop()):
        return None
    ver = upd.STATE["latest"].lstrip("vV")
    return {"id": f"update:{ver}", "title": "Versiune nouă DentPilot",
            "body": f"DentPilot {ver} este gata — actualizați în Setări › Stare sistem.",
            "open": OPEN_UPDATE}


def license_step(left: timedelta) -> int:
    """Порог (7 или 1) для оставшегося срока; 0 — ещё рано."""
    return min((d for d in LICENSE_DAYS if left <= timedelta(days=d)), default=0)


def license_item() -> dict | None:
    """Лицензия кончается: за 7 и за 1 день до `valid_until`. Продлилась сама
    (новый файл, срок дальше) — порога нет, и уведомление молчит. После конца
    говорит баннер программы (`layout._license_banner`), не часы."""
    if not lic.applies():
        return None
    s = lic.current()
    if s is None or s.state != lic.st.ACTIVE or s.valid_until is None:
        return None
    step = license_step(s.valid_until - s.now)
    if not step:
        return None
    day = s.valid_until.astimezone(eng.TZ).strftime("%d.%m.%Y")
    if s.claim is not None and s.claim.plan == "trial":
        title, body = ("Perioada de probă se termină",
                       f"Perioada de probă DentPilot expiră la {day} — activați "
                       f"abonamentul în Setări › Licența.")
    else:
        title, body = ("Abonamentul se termină",
                       f"Abonamentul DentPilot expiră la {day} — prelungiți-l în "
                       f"Setări › Licența.")
    return {"id": f"license:{_stamp(s.valid_until)}:{step}", "title": title, "body": body,
            "open": OPEN_LICENSE}


def sms_item() -> dict | None:
    """SMS мало — ТО ЖЕ правило, что у пункта меню и экрана SMS (`sms_loop.low`).
    Ключ эпизода пишет цикл SMS; пока его нет (первая минута после смены
    порога), молчим: без ключа уведомление показалось бы дважды."""
    lo = sms_loop.low()
    if lo is None or not lo["since"]:
        return None
    return {"id": f"sms:{lo['limit']}:{lo['since']}", "title": lo["title"], "body": lo["text"],
            "open": OPEN_SMS}


def items() -> dict:
    """Ответ `GET /shell/notices`."""
    found = (update_item(), license_item(), sms_item())
    return {"v": V, "items": [it for it in found if it is not None]}


# ---------- кто спрашивает ----------

TOKEN_ENV = sidecar.TOKEN_ENV             # 32 hex на каждый запуск оболочки (контракт § 2)
HEADER = "X-DentPilot-Shell"
TOKEN_MIN = 32


def shell_request_ok(request) -> bool:
    """Запрос — от оболочки ЭТОГО ПК: токен запуска задан, пир — loopback, и
    заголовок совпал (постоянное время). Иначе маршрут для всех — 404, как
    будто его нет: без оболочки (окно pywebview, браузер, телефон) его и нет.
    ⚠️ Пир, а не заголовки: X-Forwarded-* пишет кто угодно (`client_is_local`).
    ⚠️ Короткий токен — не токен: значение из чужих рук (dental.env пишет любая
    учётка Windows) не должно открывать дверь словом «1»."""
    want = os.environ.get(TOKEN_ENV, "").strip()
    got = request.headers.get(HEADER, "").strip()
    if len(want) < TOKEN_MIN or not client_is_local(request):
        return False
    return hmac.compare_digest(got.encode("utf-8"), want.encode("utf-8"))
