"""Режим восстановления: ключ картотеки не читается — живёт ОДИН экран.

Новый ПК, переустановка Windows, другая учётка — и ключ под DPAPI больше не
расшифровывается. Падать нельзя: у клиники не осталось бы ни одного экрана,
чтобы ввести код с листа восстановления. Поэтому старт (`main.startup`) ставит
режим, база не открывается вовсе, а шлюз в `main.py` ведёт все адреса журнала
сюда.

⛔ Состояние — функцией `active()`, а не именем: `from … import` имени скопировал
бы `False` на момент импорта, и шлюз молча не сработал бы никогда — клиника с
нечитаемым ключом получила бы пятисотые вместо поля для кода. Держит
`test_structure` («переприсваиваемое имя не импортируется по значению»).
"""
from __future__ import annotations

import html
import logging

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from ... import engine as eng
from ... import paths
from ...core import dbkey
from ...core.auth import same_origin_post
from ...core.layout import fonts_css, standalone
from .pages import CONFIG_BROKEN_TMPL, RECOVER_DONE, RECOVER_TMPL

router = APIRouter()
log = logging.getLogger("web")

_active = False


def active() -> bool:
    """Идёт ли программа в режиме восстановления (ставит старт, снимает только
    перезапуск: ключ перезаписан, а база всё ещё не открыта)."""
    return _active


def enter() -> None:
    global _active
    _active = True


def config_broken_page() -> str:
    """Экран «профиль клиники не читается» (`eng.CONFIG_BROKEN`): какой файл
    восстановить. Отдаёт шлюз в `main.py` — база в этом состоянии тоже не
    открыта."""
    return (CONFIG_BROKEN_TMPL
            .replace("__PATH__", html.escape(str(eng.config_path())))
            .replace("__FONTS__", fonts_css()))


@router.get("/admin/recover", response_class=HTMLResponse)
async def recover_page(err: str = "") -> Response:
    if not _active:
        return RedirectResponse("/admin", status_code=303)
    # ⭐ ДВА исхода, а не один. Раньше оба вели сюда с `err=1`, и клиника,
    # набравшая ПРАВИЛЬНЫЙ код с печатного листа, получала «код неверен» —
    # тупик в самый плохой момент, потому что чинить она шла не то. Отказ
    # записи `db.key` (нет прав на папку) не имеет отношения к коду.
    msg = {
        "1": "Codul nu este valid sau nu se potrivește cu această bază de date",
        "2": ("Codul este corect, dar cheia nu a putut fi salvată în dosarul "
              "cu date. Verificați drepturile pe dosar și încercați din nou."),
    }.get(err, "")
    return HTMLResponse(standalone(RECOVER_TMPL).replace(
        "__ERR__", f"<div class='err'>{msg}</div>" if msg else ""))


@router.post("/admin/recover")
async def recover_apply(request: Request, code: str = Form("")) -> Response:
    """Код с бумаги → ключ → ПЕРЕЗАВОРАЧИВАНИЕ под текущую учётку Windows.

    ⭐ Ключ проверяется НА САМОЙ БАЗЕ, а не «похож ли он на код»: иначе опечатка
    сохранилась бы как рабочий ключ, и следующий запуск снова упал бы в
    восстановление — уже без подсказки, что виноват ввод.
    """
    if not _active:
        return RedirectResponse("/admin", status_code=303)
    if not same_origin_post(request):     # третий POST без куки, тот же щит
        return Response(status_code=403)
    key = dbkey.parse_recovery(code)
    path = paths.db_file()
    if key is None or not dbkey.opens_with(path, key):
        return RedirectResponse("/admin/recover?err=1", status_code=303)
    # ⛔ Сюда мы попадаем, только если код ВЕРЕН: он открыл саму базу. Значит
    # неудача записи — это про папку, а не про ввод, и путать их нельзя.
    if not dbkey.store(key):
        log.error("ключ с листа верен, но db.key записать не удалось")
        return RedirectResponse("/admin/recover?err=2", status_code=303)
    log.warning("ключ базы восстановлен с листа — требуется перезапуск")
    return HTMLResponse(standalone(RECOVER_DONE))
