"""Вход в журнал, первая установка PIN, выход и сигнализация auth.json.

⚠️ Это одно из трёх мест, где законно зовётся оракул входа (`verify_pin`,
`note_fail`, …): он привязан к папке, В КОТОРОЙ ИДЁТ ПРОГРАММА, и пишет в неё.
Белый список в `test_structure` (`_LOGIN_OK`) называет файлы поимённо —
чтобы будущий экран миграции не спрятался под «любой модуль с формой входа».
Сам оракул — `try_login` ниже, ОДИН на форму и на JSON-дверь смены человека
(`api.py`, B4.4): второй, со своими ветками, разошёлся бы с первым в том, кого
пускать и что считать неудачей.
"""
from __future__ import annotations

import asyncio
import hmac
import html
import logging
import urllib.parse
from datetime import datetime

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from ... import db
from ... import engine as eng
from ...core.auth import (ADMIN_KEY, _as_user, auth_blocked, auth_file_fp,
                          client_is_local, client_peer, fail_count, FAIL_DELAY,
                          find_user, lock_left, LOCK_STEP_COUNTS, NET_STEP_COUNTS,
                          note_fail, note_ok, peer_label, PEER_LOCAL, PERM_SETTINGS,
                          pin_len_ok, pin_range_text, _pin_rec, remember_auth_file,
                          require, revoke_cookie, same_origin_post, _secret,
                          _set_auth_cookie, set_tamper_alert, _setup_allowed,
                          verify_pin, _write_pin)
from ...core.layout import msg_text, standalone
from .pages import LOGIN_TMPL, PASS_INPUT, PIN_INPUT, SETUP_LOCAL_TMPL, SETUP_TMPL

router = APIRouter()

# Исходы входа — одни на форму (`?err=`) и на JSON (коды MSG_BANNER).
LOGIN_OK, LOGIN_BAD, LOGIN_LOCK, LOGIN_BROKEN = "ok", "bad", "lock", "broken"


async def try_login(password: str, uid: str = "",
                    peer: str = "") -> tuple[str, dict | None, int]:
    """Оракул входа: (исход, запись вошедшего, срок блокировки в секундах).

    Один на форму входа и на `POST /api/auth/login`. Здесь всё, что решает,
    пускать ли человека, и всё, что вход оставляет после себя: счётчик
    неудач, пауза, строка в ленте, отпечаток auth.json, `last_login`.
    `peer` — устройство (`auth.client_peer`): счётчик неудач и блокировка с
    17.10 свои у каждого адреса, общий по сети — заслон от смены адресов.
    ⚠️ Origin вызывающий сверяет САМ до вызова (`same_origin_post`): форма
    отвечает на чужой POST пустым 403, JSON — конвертом; оракулу об этом знать
    незачем. ⚠️ Куку тоже выдаёт вызывающий — ПОСЛЕ этого вызова: `verify_pin`
    мог переписать файл v1→v2 и сменить ключ подписи (см. `verify_pin`).
    """
    if auth_blocked():
        # проверять ввод не по чему — «PIN greșit» тут враньё, а счётчик
        # неудач наказал бы человека за наш же битый файл. Вложенность та же,
        # что в _guard: при заполненном ADMIN_KEY проверять ЕСТЬ по чему, и
        # безусловный отказ запер бы исправный вход
        return LOGIN_BROKEN, None, 0
    if (left := lock_left(peer)) > 0:
        return LOGIN_LOCK, None, left
    pw = password.strip()
    who = None
    if _pin_rec():
        # логин необязателен: пароль у каждого свой (pin_free это стережёт), и
        # заставлять регистратуру набирать ещё и id — трение на ровном месте.
        # Указан явно — сверяем только с ним: так на телефоне у врача вход
        # предсказуем, даже если однажды пароли всё-таки совпадут.
        # ⚠️ .lower() — как в users/save: учётки заводятся ТОЛЬКО в нижнем
        # регистре, а поле ID на телефоне получает автозаглавную букву. Без
        # него врач с верным паролем видит «PIN greșit» и накручивает счётчик
        # блокировки собственным телефоном.
        who = verify_pin(pw, uid=uid.strip().lower()[:32])
        ok = who is not None
    else:
        ok = bool(ADMIN_KEY) and hmac.compare_digest(pw, ADMIN_KEY)
    if ok:
        note_ok(peer)
        if who is not None:
            # verify_pin мог молча переписать файл (миграция v1→v2, доливка
            # sid) — обновляем отпечаток, иначе следующий старт увидит «взлом»
            await remember_auth_file()
            # Журнал входов (08-13): «кто входил вчера вечером» — вопрос, на
            # который раньше отвечать было нечем: вход не оставлял следа
            # нигде. Облачная ветка (ADMIN_KEY) не пишет: там нет людей, и
            # строка «cineva a intrat» ничего бы не говорила.
            await db.log_clinic_event("login", "A intrat în registru",
                                      actor=_as_user(who)["name"])
            await db.set_meta(f"last_login:{who.get('id', 'clinic')}",
                              datetime.now(eng.TZ).isoformat())
        return LOGIN_OK, who, 0
    lock = note_fail(peer)
    # Всплеск подбора — строкой в ленту, на СТУПЕНЯХ лестницы, а не на
    # каждой неудаче (иначе спам). Удачный вход обнулит счётчик, но строка
    # останется: серия «кто-то тыкал PIN у стойки» перестаёт быть тихой.
    # С 17.10 строка называет УСТРОЙСТВО: телефон из Wi-Fi и стойка — разные
    # истории. Общий счётчик пишет свою строку только когда в нём больше
    # промахов, чем у этого устройства, — значит, адресов несколько.
    n_dev, n_all = (fail_count(peer) if peer else 0), fail_count()
    if lock and peer and n_dev in LOCK_STEP_COUNTS:
        await db.log_clinic_event(
            "login_fail",
            f"{n_dev} încercări greșite la intrare de la {peer_label(peer)} "
            f"— blocat {_wait_text(lock)}",
            actor="necunoscut")
    net_steps = NET_STEP_COUNTS if peer else LOCK_STEP_COUNTS
    if (lock and peer != PEER_LOCAL and n_all in net_steps
            and (not peer or n_all > n_dev)):
        where = " din rețea, de pe mai multe dispozitive" if peer else ""
        await db.log_clinic_event(
            "login_fail",
            f"{n_all} încercări greșite la intrare{where} — blocat {_wait_text(lock)}",
            actor="necunoscut")
    # asyncio.sleep, а не time.sleep: у настольного издания один процесс на всю
    # клинику, и блокирующая пауза заморозила бы журнал остальным
    await asyncio.sleep(FAIL_DELAY)
    return LOGIN_BAD, None, lock


def _wait_text(lock: int) -> str:
    return f"{lock // 60} min." if lock >= 60 else f"{lock} s"


@router.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page(next: str = "/admin", err: str = "", s: str = ""):
    # ⚠️ auth_blocked, а не _auth_broken: то же условие, что в _guard. При
    # заполненном ADMIN_KEY вход по ключу исправен, и разговор про битый файл
    # увёл бы человека чинить то, что его беде не мешает.
    broken = auth_blocked()
    if not _secret() and not broken:
        return RedirectResponse("/admin", status_code=303)
    pin_mode = _pin_rec() is not None
    if broken:
        # битый auth.json: состояние ошибки, а не «PIN не установлен» — setup
        # закрыт (_setup_allowed), и человеку важно знать, ЧТО делать. Файл
        # не трогаем: учётки восстановимы только из копии. Слова — из
        # MSG_BANNER: те же, что получает JSON-дверь (`api.py`).
        err_html = f"<div class='err'>{html.escape(msg_text('auth_broken'))}</div>"
    elif err == "lock":
        # `s` — срок из редиректа сразу после неудачи; lock_left() свежее, но
        # к моменту перезагрузки страницы уже мог утечь до нуля
        left = lock_left() or (int(s) if s.isdigit() else 0)
        wait = f"{left} sec." if left < 60 else f"{(left + 59) // 60} min."
        # вторая фраза — выход, а не упрёк: после смены пароля коллегой человек
        # попадает сюда с ВЕРНЫМ по его памяти PIN-ом и не знает, что делать
        err_html = ("<div class='err'>Prea multe încercări greșite. "
                    f"Încercați peste {wait}<br><small>Ați uitat PIN-ul? "
                    "Un director îl poate schimba din Setări › Securitate "
                    "și utilizatori.</small></div>")
    elif err:
        err_html = (f"<div class='err'>{html.escape(msg_text('login_bad'))}</div>"
                    if pin_mode else "<div class='err'>Parolă greșită</div>")
    else:
        err_html = ""
    nxt = next if next.startswith("/admin") else "/admin"
    return (standalone(LOGIN_TMPL)
            .replace("__ERR__", err_html).replace("__NEXT__", html.escape(nxt))
            .replace("__INPUT__", PIN_INPUT if pin_mode else PASS_INPUT))


@router.post("/admin/login")
async def admin_login(request: Request, password: str = Form(...),
                      uid: str = Form(""),
                      next_url: str = Form("/admin", alias="next")):
    # чужой сайт в браузере клиники не должен ни пробовать PIN-ы, ни
    # накручивать счётчик подбора до блокировки (см. same_origin_post)
    if not same_origin_post(request):
        return Response(status_code=403)
    target = next_url if next_url.startswith("/admin") else "/admin"
    nxt = urllib.parse.quote(target, safe="")
    outcome, who, lock = await try_login(password, uid, client_peer(request))
    if outcome == LOGIN_BROKEN:
        return RedirectResponse(f"/admin/login?err=broken&next={nxt}",
                                status_code=303)
    if outcome == LOGIN_OK:
        # кука ставится ПОСЛЕ try_login: миграция v1→v2 меняет ключ подписи,
        # а запись пользователя — свой sid
        return _set_auth_cookie(RedirectResponse(target, status_code=303), who)
    # `s` — срок блокировки: и у запертого входа, и у неудачи, которая его
    # заперла; страница входа подставит его в «Încercați peste …»
    q = f"err=lock&s={lock}" if lock else "err=1"
    return RedirectResponse(f"/admin/login?{q}&next={nxt}", status_code=303)


@router.get("/admin/logout")
async def admin_logout(request: Request):
    """Выход. Кука снимается у браузера И отзывается на сервере (17.10): в
    сети клиники канал http, и подсмотренная кука иначе жила бы до смены PIN
    (`auth.revoke_cookie`). Та же пара действий у JSON-двери (`api.py`)."""
    revoke_cookie(request)
    resp = RedirectResponse("/admin/login", status_code=303)
    resp.delete_cookie("admin_auth")
    return resp


@router.get("/admin/setup", response_class=HTMLResponse)
async def admin_setup_page(request: Request, err: str = ""):
    if not _setup_allowed():
        return RedirectResponse("/admin", status_code=303)
    if not client_is_local(request):
        # не редирект на /admin: _guard без PIN вернул бы сюда же, и сетевой
        # клиент кружил бы в 303 — вместо этого внятная страница с причиной
        return HTMLResponse(standalone(SETUP_LOCAL_TMPL), status_code=403)
    # границы — одной функцией, по состоянию сети: «4–6» здесь пережило
    # подъём потолка до 8 (08-13), а с 17.10 минимум ещё и зависит от сети
    # (6 при включённом «Acces din rețea» — флаг переживает переустановку)
    err_html = (f"<div class='err'>PIN-urile nu coincid sau nu au "
                f"{pin_range_text()}</div>" if err else "")
    return (standalone(SETUP_TMPL).replace("__ERR__", err_html)
            .replace("__PIN_RANGE__", pin_range_text()))


@router.post("/admin/setup")
async def admin_setup(request: Request, pin1: str = Form(...),
                      pin2: str = Form(...)):
    if not _setup_allowed():
        return RedirectResponse("/admin", status_code=303)
    if not client_is_local(request):
        return HTMLResponse(standalone(SETUP_LOCAL_TMPL), status_code=403)
    # пока PIN не установлен, эту форму мог бы отправить чужой сайт из
    # браузера НА САМОМ компьютере клиники — loopback его не отличает
    if not same_origin_post(request):
        return Response(status_code=403)
    p1, p2 = pin1.strip(), pin2.strip()
    if p1 != p2 or not pin_len_ok(p1):
        return RedirectResponse("/admin/setup?err=1", status_code=303)
    _write_pin(p1)
    await remember_auth_file()
    return _set_auth_cookie(RedirectResponse("/admin", status_code=303),
                            find_user("clinic"))


async def check_auth_file() -> None:
    """Сигнализация auth.json: файл переписали или удалили ВНЕ программы.

    Зовёт старт (`main.startup`), сразу после открытия базы.

    Это след, а не замок (см. пояснение в core/auth.py): отпечаток файла живёт
    в базе, расхождение при старте попадает в ленту и висит баннером у
    директора, пока тот не подтвердит. Ложная тревога недопустима — поэтому
    каждый маршрут, пишущий файл сам, обязан звать remember_auth_file().
    """
    if (alert := await db.get_meta("auth_alert")):
        set_tamper_alert(alert)      # непогашенное предупреждение живёт и после рестарта
    now_fp = auth_file_fp()
    stored = await db.get_meta("auth_fp")
    if stored is None:
        # первый запуск с этой проверкой: судить прошлое не по чему
        await db.set_meta("auth_fp", now_fp)
        return
    if stored == now_fp:
        return
    when = datetime.now(eng.TZ).strftime("%d.%m.%Y %H:%M")
    what = ("șters" if not now_fp else "modificat")
    text = (f"Fișierul de acces (auth.json) a fost {what} în afara programului "
            f"— sesizat la pornirea din {when}")
    await db.log_clinic_event("auth_tamper", text)
    await db.set_meta("auth_alert", text)
    await db.set_meta("auth_fp", now_fp)   # один сигнал на одно вмешательство
    set_tamper_alert(text)
    logging.getLogger("auth").warning("auth.json tampered: %s", what)


@router.post("/admin/security/ack")
async def security_ack(request: Request):
    """Погасить предупреждение. Только директор: остальные не могут ни оценить
    «это был техник», ни сменить PIN-ы — им баннер и не показывается."""
    if (deny := require(request, PERM_SETTINGS)) is not None:
        return deny
    await db.del_meta("auth_alert")
    set_tamper_alert("")
    return RedirectResponse("/admin", status_code=303)
