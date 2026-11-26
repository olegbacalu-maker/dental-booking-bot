"""Календарь врача в его Google: подключение из карточки врача, уход, блок для экрана.

Дверь к Google врачей — core/gdoc.py (файл связи, токены, замок врача, уход); сверку журнала с
календарём делает свой цикл через крючки двери (`gdoc.sync_*`). Здесь — вход врача в браузере
Windows, создание или подхват его календаря, «Deconectează» и все слова блока.

- Подключает директор или регистратура (`PERM_DOCTORS`), только с ПК программы; врач входит своим
  Google сам. Право — дата `gcal_doctor` в файле лицензии, на входе и на возврате, до сети.
- Отзыва у Google нет: он проектный и оборвал бы связь клиники и календари других врачей аккаунта.
- Календарь сначала ищется по прежнему id (файл связи, затем картотека): новый ПК или переустановка
  подхватывают прежний календарь, а не заводят второй с тем же именем.
- Токены, код входа и verifier не попадают ни в лог, ни в базу.
"""
from __future__ import annotations

import asyncio
import html
import logging
import os
import time
from datetime import datetime, timezone
from urllib.parse import parse_qs

from ... import db
from ... import engine as eng
from ...core import gauth, gdoc, gwrite
from ...core import license as lic
from ...core import license_state as lst
from ...core.auth import PERM_DOCTORS, PERM_SETTINGS, all_users, can, client_is_local, request_user
from ...core.layout import msg_text, msg_view

log = logging.getLogger("gdoc")

BACK_PATH = "/google/back/medic"
LOGIN_TTL = 600.0                         # секунд живёт начатый вход
LOGINS_MAX = 8
CHECK_WAIT = 20.0                         # «Sincronizează acum» ждёт прохода врача не дольше
# Второе «Deconectează» в это окно после неудачного удаления календаря закрывает связь в программе.
LEAVE_AGAIN = 600.0
PRIVACY = {"href": "https://dentpilot.md/privacy.html#google", "label": "dentpilot.md/privacy.html#google"}
PREMIUM = {"href": "/admin/license", "label": "Setări › Licența"}
CAL_TEXT = ("Programările medicului din DentPilot. Se modifică doar în DentPilot: ce schimbați aici "
            "nu ajunge în program.")

S_OFF, S_WAITING, S_ON, S_RECONNECT = "off", "waiting", "on", "reconnect"
S_FOREIGN, S_PREMIUM, S_READONLY, S_PAUSED = "foreign", "premium", "readonly", "paused"

# Срок доезда приёма до календаря врача — то же число, что у цикла сверки и в документах; одно число
# держит сторож «срок доезда до календаря врача — одно число».
SYNC_MINUTES = 5
SOON = f"în cel mult {SYNC_MINUTES} minute"

# Слова блока карточки врача (`GdocWords` клиента): ключи — ровно эти, экран своих слов не пишет.
WORDS = {
    "title": "Google Calendar",
    "lead": f"Programările medicului ajung singure în calendarul lui din Google, {SOON}.",
    "hint": "Se deschide browserul: medicul alege contul lui Google și permite accesul.",
    "details": "Detalii:",
    "connect": "Conectează Google", "connect_here": "Conectează aici", "reconnect": "Conectează din nou",
    "check": "Sincronizează acum", "disconnect": "Deconectează",
    "disconnect_ask": "",                 # готовой строкой с именем календаря — `_disconnect_ask`
    "waiting_title": "Așteptăm răspunsul Google…",
    "waiting_detail": "În browser medicul alege contul lui Google și permite accesul. Dacă pagina s-a "
                      "închis, deschideți-o din nou.",
    "reopen": "Deschide din nou pagina", "cancel": "Renunță",
    "connected": "Conectat:", "calendar_label": "Calendarul",
    "last": "Ultima actualizare:", "all_in": "totul e la zi.", "last_ok": "Ultima reușită:",
    "pending": "",                        # готовой строкой с числом — `_pending_text`
    "level_lead": "Ce vede medicul:", "level_link": "Se schimbă în lista Medici",
    # путь к Premium: фраза, а ссылкой — только сам путь (`PREMIUM`)
    "premium_lead": "O porniți plătind varianta Premium în",
}
# Слова блока «Calendarele medicilor în Google» над списком врачей (`GdocListWords` клиента).
LIST_WORDS = {
    "title": "Calendarele medicilor în Google",
    "lead": "Fiecare medic conectat își vede programările în telefon. Ce ajunge acolo alege directorul.",
    "count": "",                          # готовой строкой с числами — `_count_text`
    "label": "Ce vede medicul în Google", "phone": "În telefon:", "change": "Schimbă",
    "only_dir": "Schimbă doar directorul.",
    "remote": "Se schimbă doar de pe calculatorul pe care rulează programul.",
    "premium": "Calendarele medicilor în Google fac parte din DentPilot Premium:",
    "premium_more": "fiecare medic își vede programările în telefon, implicit doar ora.",
    "default": "implicit",
    "rewrite": f"La schimbare calendarele se rescriu singure, {SOON}.",
    "dlg_title": "Ce vede medicul în Google",
    "dlg_ack": "Am înțeles: aceste date ale pacienților vor fi în Google, în telefonul fiecărui medic conectat.",
    "dlg_ok": "Alege", "dlg_cancel": "Renunță",
}
CHIP = {S_ON: "Google conectat", S_OFF: "Google neconectat", S_WAITING: "Google: așteptăm",
        S_RECONNECT: "Google: de refăcut", S_FOREIGN: "Google: alt calculator",
        S_READONLY: "Google oprit", S_PAUSED: "Google oprit"}
NOTICE = ("Programările pleacă de pe acest calculator direct în Google — serverul DentPilot nu le vede. "
          "Se schimbă doar în DentPilot; în Google e o copie pentru medic.")
REMOTE = "Medicul se conectează doar de pe calculatorul pe care rulează programul."
ASK = ("Deconectați Google Calendar al medicului? Calendarul „{name}” se șterge din contul lui Google; "
       "programările rămân în DentPilot.")
ASK_NO_NAME = ("Deconectați Google Calendar al medicului? Calendarul lui din Google se șterge; programările "
               "rămân în DentPilot.")
# Вторая строка состояния (`why.detail`) — что делать; первая — слово словаря (`why.text`).
DETAIL = {
    "gd_premium": "Fiecare medic își vede programările în telefon — implicit doar ora, fără numele pacientului.",
    "gd_paused": "Programul a scos din calendarul medicului toate programările, și pe cele trecute. Legătura "
                 "rămâne — după plata Premium revin singure.",
    "gd_readonly": "După plata abonamentului se actualizează din nou singur.",
    "gd_dead": "Accesul dat programului a fost retras în contul Google al medicului sau a expirat.",
    "gd_no_scope": "Google nu a dat dreptul de a scrie în calendarul medicului: la conectare lăsați bifată "
                   "permisiunea pentru calendar.",
    "gd_cal_gone": "Calendarul „DentPilot” a fost șters din contul Google al medicului. „Conectează din nou” "
                   "face un calendar nou.",
    "gd_elsewhere": "Cheia de acces se citește doar pe calculatorul și în contul Windows unde a fost făcută "
                    "conectarea. Conectați-l din nou de pe acest calculator.",
    "gd_foreign": "Aici calendarul lui nu se actualizează. Conectați-l din nou de pe acest calculator — "
                  "calendarul rămâne același, iar celălalt calculator se oprește.",
    "gd_archived_wait": "Dacă Google nu răspunde acum, programul încearcă din nou singur.",
    "gd_failed": "Dacă se repetă, scrieți-ne.",
    "gd_back_ok": "Sfat: medicul să iasă din contul său Google în acest browser — calculatorul clinicii "
                  "este folosit și de alții.",
}
# Уровень подробности: длинное слово — в карточке врача, короткое с заглавной — в переключателе.
LEVEL_LONG = {"time": "doar ora, fără numele pacientului", "initials": "inițialele pacientului",
              "name": "numele pacientului și serviciul"}
LEVEL_SHORT = {"time": "Doar ora", "initials": "Inițiale", "name": "Nume și serviciu"}
LEVEL_HINT = {"time": "Fără numele pacientului", "initials": "Inițialele și numărul fișei · cere confirmare",
              "name": "Numele întreg și serviciul · cere confirmare"}
# Окно «am înțeles»: уровень с данными пациента выбирается только после галочки — у тех же уровней,
# у которых есть это предупреждение, `ack` требует и сервер.
LEVEL_WARN = {
    "initials": "Inițialele pacientului și numărul fișei vor pleca în contul Google al fiecărui medic conectat "
                "și se vor vedea în telefonul lui. Google le păstrează în contul medicului. Alegeți asta doar "
                "dacă pacienții sunt informați și medicii își țin telefonul cu parolă.",
    "name": "Numele pacientului și serviciul vor pleca în contul Google al fiecărui medic conectat și se vor "
            "vedea în telefonul lui. Google le păstrează în contul medicului. Alegeți asta doar dacă pacienții "
            "sunt informați și medicii își țin telefonul cu parolă.",
}
LOCK_ROLE = LIST_WORDS["only_dir"]
LOCK_READONLY = "Se schimbă după plata abonamentului."
# Образец события в переключателе: заголовок строит тот же `gwrite.event_body`, что пишет сверка.
SAMPLE = gwrite.Appt(id=1, start=datetime(2027, 1, 4, 9, 0, tzinfo=timezone.utc), minutes=30, room="Cabinet 1",
                     patient="Maria Lungu", file_no="124", service="Tratament carie")
# Серый замок экрана — у состояний «нет права» (как у связи клиники).
_PLUS_STATES = (S_PREMIUM, S_READONLY, S_PAUSED)

_RECONNECT_WHY = {gdoc.DEAD_GRANT: "gd_dead", gdoc.DEAD_SCOPE: "gd_no_scope", gdoc.DEAD_GONE: "gd_cal_gone",
                  "elsewhere": "gd_elsewhere"}
# ошибка последнего прохода сверки (код провода или двери) → слово блока
_SYNC_WHY = {gwrite.RATE_LIMITED: "gc_g_rate", gdoc.A_RATE: "gc_g_rate",
             gwrite.OFFLINE: "gd_offline", gdoc.A_OFFLINE: "gd_offline"}
# у обмена кода своё слово только там, где новый вход не поможет
_BACK_WIRE = {gauth.INVALID_CLIENT: "gc_g_client", gauth.ADMIN_POLICY: "gd_admin"}
_LEAVE = {gdoc.L_DELETED: "gd_off", gdoc.L_LOCAL: "gd_off_local", gdoc.L_NONE: "gd_gone"}

_logins: dict = {}                        # state входа → dk, verifier, адрес возврата, кто начал
_kept: dict = {}                          # dk → когда «Deconectează» не смогло удалить календарь


def actor() -> str:
    return (request_user() or {}).get("name") or gdoc.ACTOR


def _archived(dk: str) -> bool:
    return eng.DOCTOR_META.get(dk, {}).get("status") == "arhivat"


def _gate_code() -> str:
    s = lic.current()
    return "gd_premium" if s is not None and s.state in (lst.ACTIVE, lst.GRACE) else "gd_readonly"


def _when(iso: str) -> dict | None:
    try:
        at = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None
    return {"at": iso, "when": at.astimezone(eng.TZ).strftime("%d.%m.%Y %H:%M")}


def _waiting(dk: str) -> bool:
    now = time.monotonic()
    return any(e["dk"] == dk and not e["done"] and now - e["at"] < LOGIN_TTL for e in _logins.values())


def _sync_error(dk: str) -> tuple[str, str]:
    """(код слова, когда) по ответу сверки; ('', '') — ошибки нет или сверки нет."""
    got = gdoc.sync_stats(dk)
    err = got.get("error") if isinstance(got, dict) else None
    if not isinstance(err, str) or not err:
        return "", ""
    code = err if err.startswith("gd_") and msg_text(err) else _SYNC_WHY.get(err, "gd_failed")
    at = got.get("error_at")
    return code, at if isinstance(at, str) else ""


def _ro(n: int, one: str, many: str) -> str:
    """«1 programare», «5 programări», «37 de programări» — правило «de» то же, что у `roCount` клиента."""
    if n == 1:
        return f"1 {one}"
    r = n % 100
    return f"{n}{' de' if r == 0 or r >= 20 else ''} {many}"


def _pending(dk: str) -> int:
    got = gdoc.sync_stats(dk)
    n = got.get("pending") if isinstance(got, dict) else 0
    return n if isinstance(n, int) and not isinstance(n, bool) and n > 0 else 0


# ---------- модель блока ----------


def _state(dk: str, link: dict | None, s) -> tuple[str, str]:
    """(состояние, код слова) без сети. Без права связь и ключ хранятся: после оплаты сверка вернёт
    события сама. Архив своего состояния не имеет — до прохода сверки видно то, что в файле."""
    connected = link is not None
    if s.state not in (lst.ACTIVE, lst.GRACE):
        return S_READONLY, "gd_readonly"
    if lic.feature_until(gdoc.SYNC_GATE) is None:
        return (S_PAUSED, "gd_paused") if connected else (S_PREMIUM, "gd_premium")
    if _waiting(dk) and not (connected and link["state"] == gdoc.S_ON):
        return S_WAITING, ""
    if not connected:
        return S_OFF, ""
    if link["state"] == gdoc.S_FOREIGN:
        state, code = S_FOREIGN, "gd_foreign"
    elif link["state"] == gdoc.S_RECONNECT:
        state, code = S_RECONNECT, _RECONNECT_WHY.get(link["why"], "gd_dead")
    else:
        state, code = S_ON, _sync_error(dk)[0]
    return state, ("gd_archived_wait" if _archived(dk) else code)


def _why(dk: str, state: str, code: str) -> dict | None:
    if not code:
        return None
    err, err_at = _sync_error(dk)
    if state == S_ON and code == err:
        # неудачный проход: заголовок общий, причина — словом её кода, когда — рядом со штампом удачной
        tail = DETAIL.get(code, "")
        reason = {**msg_view(code), "text": msg_text("gd_sync_failed"),
                  "detail": msg_text(code) + "." + (" " + tail if tail else "")}
        if at := _when(err_at):
            reason.update(at)
        return reason
    reason = {**msg_view(code), "detail": DETAIL.get(code, "")}
    if state in _PLUS_STATES:
        reason["tone"] = "plus"
    return reason


def _pending_text(n: int) -> str:
    return f"încă {_ro(n, 'programare', 'programări')} în drum." if n > 0 else ""


def _disconnect_ask(link: dict | None) -> str:
    name = str(((link or {}).get("calendar") or {}).get("name") or "")
    return ASK.format(name=name) if name else ASK_NO_NAME


def _shown() -> object | None:
    """Состояние лицензии, если блок вообще есть: нет в демо, на сервере, у сборки без клиента."""
    if gdoc.client() is None:
        return None
    s = lic.current()
    return None if s is None or s.wall else s


async def view(request, dk: str) -> dict | None:
    """Блок карточки врача (`GdocView`); None — блока нет. Кнопки — по `can`, слова — по `why`,
    `words` и `notice`."""
    s = _shown()
    if s is None or dk not in eng.DOCTORS:
        return None
    link = gdoc.linked().get(dk)
    state, code = _state(dk, link, s)
    level = await gdoc.level()
    local = client_is_local(request)
    pending = _pending(dk) if state == S_ON else 0
    return {
        "state": state,
        "account": str((link or {}).get("account") or ""),
        "calendar": dict(link["calendar"]) if link and link.get("calendar") else None,
        "last": _when(str((link or {}).get("last_ok") or "")),
        "pending": pending,
        "why": _why(dk, state, code),
        "level": {"code": level, "label": LEVEL_LONG[level]},
        "notice": NOTICE, "privacy": dict(PRIVACY),
        "premium": dict(PREMIUM) if state in (S_PREMIUM, S_PAUSED) else None,
        "waiting": _waiting(dk), "remote": None if local else REMOTE,
        "can": {"connect": local and not _archived(dk) and state in (S_OFF, S_WAITING, S_RECONNECT, S_FOREIGN),
                "check": state == S_ON,
                "disconnect": local and link is not None},
        "words": {**WORDS, "pending": _pending_text(pending), "disconnect_ask": _disconnect_ask(link)},
    }


def _sample(level: str) -> str:
    tag = gwrite.clinic_tag("sample")
    body = gwrite.event_body(level, SAMPLE, tag=tag, event_id=gwrite.event_id(tag, 1, SAMPLE.id, 0), note="")
    return body["summary"]


async def level_view(request) -> dict:
    """Выбор подробности события (`LevelView`): один на клинику, менять — директор с ПК программы;
    почему нельзя — одним словом `lock`."""
    code = await gdoc.level()
    s = lic.current()
    if not can(request_user(), PERM_SETTINGS):
        lock = LOCK_ROLE
    elif not client_is_local(request):
        lock = LIST_WORDS["remote"]
    elif s is not None and s.state not in (lst.ACTIVE, lst.GRACE):
        lock = LOCK_READONLY
    else:
        lock = ""
    return {"code": code,
            "choices": [{"code": c, "label": LEVEL_SHORT[c], "hint": LEVEL_HINT[c], "sample": _sample(c),
                         "warn": LEVEL_WARN.get(c, "")} for c in gwrite.LEVELS],
            "can_set": not lock, "lock": lock}


def _count_text(links: dict) -> str:
    live = [dk for dk in eng.DOCTORS if not _archived(dk)]
    on = sum(1 for dk in live if (links.get(dk) or {}).get("state") == gdoc.S_ON)
    return f"Conectați: {on} din {_ro(len(live), 'medic', 'medici')}"


async def overview(request) -> dict | None:
    """Плашки списка врачей и выбор подробности; None — блока нет."""
    s = _shown()
    if s is None:
        return None
    links = gdoc.linked()
    doctors = {}
    for dk in eng.DOCTORS:
        link = links.get(dk)
        state, code = _state(dk, link, s)
        doctors[dk] = {"state": state, "account": str((link or {}).get("account") or ""),
                       "why": _why(dk, state, code)}
    # без права (абонемент оплачен) блок списка — одна строка с путём к лицензии, плашек у врачей нет
    paid = s.state in (lst.ACTIVE, lst.GRACE)
    no_right = paid and lic.feature_until(gdoc.SYNC_GATE) is None
    return {"doctors": doctors, "level": await level_view(request),
            "premium": dict(PREMIUM) if no_right else None,
            "words": {**LIST_WORDS, "count": _count_text(links), "chip": dict(CHIP)}}


# ---------- вход ----------


def _port(request) -> int:
    """Порт, на котором слушает движок: адрес возврата обязан вести в этот же процесс."""
    server = request.scope.get("server")
    if isinstance(server, (tuple, list)) and len(server) == 2 and isinstance(server[1], int):
        return server[1]
    try:
        return int(os.environ.get("DENTART_PORT", "") or 8088)
    except ValueError:
        return 8088


def _prune() -> None:
    now = time.monotonic()
    for k in [k for k, e in _logins.items() if now - e["at"] >= LOGIN_TTL]:
        del _logins[k]
    while len(_logins) >= LOGINS_MAX:
        del _logins[min(_logins, key=lambda k: _logins[k]["at"])]


def _drop_pending(dk: str) -> None:
    """Незавершённые входы врача умирают; завершённые остаются до срока — повтор адреса отвечает
    «deja conectat»."""
    for k in [k for k, e in _logins.items() if e["dk"] == dk and not e["done"]]:
        del _logins[k]


def cancel(dk: str) -> str:
    """«Renunță» у ожидания: начатый вход врача больше не завершится, даже если браузер вернётся."""
    _drop_pending(dk)
    return "gd_cancel"


async def start(request, dk: str) -> tuple[str, str]:
    """«Conectează»: (код, адрес экрана Google). Адрес открывает браузер Windows — встроенное окно
    для входа Google запрещает правилами. Живая связь не перезаписывается: календарь прежнего
    аккаунта остался бы у Google без хозяина."""
    client = gdoc.client()
    if client is None:
        return "gd_none", ""
    if lic.feature_until(gdoc.SYNC_GATE) is None:
        return _gate_code(), ""
    if _archived(dk):
        return "gd_archived", ""
    link = gdoc.linked().get(dk)
    if link is not None and link["state"] == gdoc.S_ON:
        return "gd_on", ""
    me = request_user() or {}
    verifier, challenge = gauth.pkce()
    state = gauth.new_state()
    redirect = gauth.loopback(_port(request), BACK_PATH)
    _prune()
    # «Deschide din nou pagina» — новый вход; у врача живым остаётся только последний
    _drop_pending(dk)
    _logins[state] = {"dk": dk, "verifier": verifier, "redirect": redirect, "at": time.monotonic(),
                      "done": False, "user": {"id": str(me.get("id") or ""), "role": str(me.get("role") or ""),
                                              "name": str(me.get("name") or "")}}
    hint = str(eng.DOCTOR_META.get(dk, {}).get("email") or "").strip() or str((link or {}).get("account") or "")
    url = gauth.consent_url(client, redirect, state, challenge, scopes=gauth.DOCTOR_SCOPES, login_hint=hint,
                            prompt="consent", auth_url=gdoc.ends().auth)
    return "gd_url", url


def _still_allowed(snap: dict) -> bool:
    """Право нажавшего — из файла учёток по id, как у входа: понижение действует сразу.
    Без файла учёток (вход по ключу сервера) людей нет — право снято при нажатии."""
    people = all_users()
    if not people:
        return can(snap, PERM_DOCTORS)
    return can(next((u for u in people if u["id"] == snap.get("id")), None), PERM_DOCTORS)


def _query_state(query: str) -> str:
    got = parse_qs(query or "", keep_blank_values=True).get("state") or [""]
    return got[0] if len(got) == 1 else ""


async def finish(request) -> tuple[str, int]:
    """Возврат из браузера Windows на 127.0.0.1. Адрес вне /admin и /api: куки программы в
    браузере нет, посредники его не видят, — поэтому всё проверяется здесь: пир соединения,
    state и PKCE своего входа, право нажавшего, гейт, врач ещё в списке."""
    if not client_is_local(request):
        return "gc_g_back_local", 403
    query = request.url.query
    state = _query_state(query)
    entry = _logins.get(state)
    if entry is None or time.monotonic() - entry["at"] >= LOGIN_TTL:
        return "gd_back_state", 400
    dk = entry["dk"]
    if entry["done"]:
        on = (gdoc.linked().get(dk) or {}).get("state") == gdoc.S_ON
        return ("gd_back_again" if on else "gd_back_state"), 200
    back = gauth.back(query, state)
    if back.code == gauth.BAD_STATE:
        return "gd_back_state", 400
    entry["done"] = True                  # код входа одноразовый: повтор адреса — уже не вход
    if back.code == gauth.ACCESS_DENIED:
        return "gd_back_denied", 200
    if back.code != gauth.OK:
        log.warning("gdoc: login back refused: %s %s", back.code, back.reason)
        return "gc_g_back_failed", 400
    client = gdoc.client()
    if client is None:
        return "gd_none", 409
    if lic.feature_until(gdoc.SYNC_GATE) is None:
        return _gate_code(), 409
    if not _still_allowed(entry["user"]):
        return "gd_back_right", 403
    if dk not in eng.DOCTORS or _archived(dk):
        return "gd_back_gone", 409
    where = gdoc.ends()
    r = await asyncio.to_thread(gauth.exchange, client, back.auth_code, entry["verifier"], entry["redirect"],
                                token_url=where.token, agent=gdoc.agent())
    if r.code != gauth.OK:
        log.warning("gdoc: exchange refused: %s %s", r.code, r.reason)
        return _BACK_WIRE.get(r.code, "gc_g_back_failed"), 400
    if gauth.missing(r.grant.scopes or back.scopes, gauth.DOCTOR_SCOPES):
        # без отзыва: он снял бы и связь клиники, и календари других врачей этого аккаунта
        return "gd_back_no_scope", 400
    async with gdoc.lock(dk):
        code = await _bind(dk, r.grant, entry["user"]["name"] or gdoc.ACTOR)
    if code != "gd_back_ok":
        return code, 409 if code == "gd_none" else 400
    _kept.pop(dk, None)
    gdoc.sync_wake(dk)
    return code, 200


def _wire_code(r: gwrite.Reply) -> str:
    log.warning("gdoc: calendar refused: %s %s", r.code, r.reason)
    if r.code == gwrite.NO_SCOPE:
        return "gd_back_no_scope"
    if r.code in (gwrite.RATE_LIMITED, gwrite.OFFLINE):
        return "gd_back_offline"
    return "gc_g_back_failed"


async def _bind(dk: str, grant: gauth.Grant, actor: str) -> str:
    """Календарь врача и запись связи — под замком врача. Прежний календарь (id из файла связи или
    картотеки) подхватывается с новой меткой: иначе дверь сочла бы его чужим."""
    where, who = gdoc.ends(), gdoc.agent()
    mark = gdoc.new_mark()
    name = gwrite.calendar_summary(eng.CLINIC_NAME, eng.DOCTORS[dk])
    desc = gwrite.calendar_description(mark, CAL_TEXT)
    old = (gdoc.linked().get(dk) or {}).get("calendar") or {}
    prev = old.get("id") or await db.get_meta(gdoc.META_CAL + dk) or ""
    cal, reused = None, False
    if prev:
        got = await asyncio.to_thread(gwrite.calendar_patch, grant.access, prev, summary=name, description=desc,
                                      base=where.api, agent=who)
        if got.code == gwrite.OK:
            cal, reused = got.data, True
        elif got.code not in (gwrite.NOT_FOUND, gwrite.GONE):
            return _wire_code(got)
    if cal is None:
        got = await asyncio.to_thread(gwrite.calendar_insert, grant.access, name, desc, base=where.api, agent=who)
        if got.code != gwrite.OK:
            return _wire_code(got)
        cal = got.data
    stored = await gdoc.store(dk, refresh=grant.refresh, account=cal["dataOwner"], cal_id=cal["id"],
                              cal_name=cal["summary"] or name, mark=mark, actor=actor, reused=reused,
                              access_token=grant.access, expires_in=grant.expires_in)
    if not stored:
        if not reused:
            # пустой календарь без связи никто больше не уберёт
            await asyncio.to_thread(gwrite.calendar_delete, grant.access, cal["id"], base=where.api, agent=who)
        return "gd_none"
    return "gd_back_ok"


def back_page(code: str) -> str:
    """Страница в браузере Windows после возврата из Google — словами сервера."""
    return ("<!doctype html><html lang='ro'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            "<title>DentPilot</title></head><body style='font-family:system-ui,"
            "sans-serif;max-width:560px;margin:12vh auto;padding:0 16px;"
            "line-height:1.6;color:#162033'>"
            f"<p>{html.escape(msg_text(code) or msg_text('gc_g_back_failed'))}</p>"
            + (f"<p>{html.escape(DETAIL[code])}</p>" if code in DETAIL else "")
            + "</body></html>")


# ---------- команды блока ----------


async def check(dk: str) -> str:
    """«Sincronizează acum»: разбудить сверку врача и ждать её прохода до CHECK_WAIT."""
    if gdoc.client() is None:
        return "gd_none"
    if lic.feature_until(gdoc.SYNC_GATE) is None:
        return _gate_code()
    link = gdoc.linked().get(dk)
    if link is None:
        return "gd_gone"
    if link["state"] != gdoc.S_ON:
        return "gd_foreign" if link["state"] == gdoc.S_FOREIGN else _RECONNECT_WHY.get(link["why"], "gd_dead")
    gdoc.sync_wake(dk)
    if await gdoc.sync_run(dk, CHECK_WAIT) is None:
        return "gd_check_late"
    after = gdoc.linked().get(dk)
    if after is None:
        return "gd_gone"
    if after["state"] != gdoc.S_ON:
        return "gd_foreign" if after["state"] == gdoc.S_FOREIGN else _RECONNECT_WHY.get(after["why"], "gd_dead")
    return _sync_error(dk)[0] or "gd_checked"


async def disconnect(dk: str, actor: str) -> str:
    """«Deconectează»: календарь врача удаляется у Google, ключ забывается, доступ не отзывается.
    Гейт не спрашивается: уйти можно всегда. Пока ключ читается здесь, неудачное удаление связь
    держит — иначе календарь с приёмами остался бы у Google навсегда; второе нажатие в течение
    LEAVE_AGAIN закрывает связь в программе."""
    _drop_pending(dk)
    link = gdoc.linked().get(dk)
    again = time.monotonic() - _kept.get(dk, -LEAVE_AGAIN) < LEAVE_AGAIN
    hard = link is not None and link["state"] == gdoc.S_ON and not again
    async with gdoc.lock(dk):
        out = await gdoc.leave(dk, "disconnect", actor, must_delete=hard)
    if out == gdoc.L_KEPT and hard:
        _kept[dk] = time.monotonic()
        return "gd_off_later"
    _kept.pop(dk, None)
    return _LEAVE.get(out, "gd_off_fail")


async def set_level(chosen: str, ack: bool, actor: str) -> str:
    """Подробность события для всей клиники; с данными пациента — только после «am înțeles»."""
    if gdoc.client() is None:
        return "gd_none"
    if chosen not in gwrite.LEVELS:
        return "gd_level_bad"
    if chosen in LEVEL_WARN and not ack:
        return "gd_level_ack"
    out = await gdoc.set_level(chosen, actor)
    if out == gdoc.LV_BAD:
        return "gd_level_bad"
    if out == gdoc.LV_SET:
        gdoc.sync_wake(None)
        return "gd_level_ok"
    return "gd_level_same"
