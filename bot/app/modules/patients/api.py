"""JSON API пациентов (DentPilot 2.0): список, предпросмотр, новая фиша —
и сама фиша (C18) с её действиями.

Старая страница «Pacienți» (`routes.admin_search`) читает всю картотеку в
память (`_pl_rows`) и остаётся как есть. Здесь отбор, порядок и страница
считаются базой (`db.patients_count` / `db.patients_rows`), а статус строки,
подписи карточек, разбор запроса и правила новой фиши — те же функции
модуля (`_pl_status`, `_pl_trend`, `_pl_terms`, `_new_patient`,
`_peek_html`), чтобы у двух страниц не разошлись ни слова, ни цифры.
Паритет выдачи со старой страницей держит `test_patients_api.suite_parity`.

Фиша (`GET /api/patients/{pid}` и `POST …/{pid}/…`) — те же пятнадцать
выборок, что у старой страницы, и те же расчёты из `card.py`; правила
действий — функции `routes._save_profile`, `_appoint`, `_add_alert`,
`_save_anamneza`, `_add_plan`, `_plan_status`, `_plan_del`, `_add_pay`,
`_store_doc`, `_drop_doc`, `_open_doc`, `_erase`, одни на форму и на API.
Удача действия возвращает СВЕЖУЮ фишу целиком: почти каждое действие
двигает сразу несколько секций (план → KPI, сальдо, летопись), и клиент
подменяет всё, а не гадает, что изменилось. Паритет с разметкой держит
`test_patient_card.suite_api`.

Правило то же: `core`, `db`, `engine` — да, `main.py` — нет.
"""
from __future__ import annotations

import html
import urllib.parse
from datetime import datetime, timedelta

from fastapi import APIRouter, File, Request, UploadFile

from ... import db
from ... import engine as eng
from ...core.api import api_body, api_guard, api_require
from ...core.auth import PERM_MONEY, can, request_user
from ...core.layout import ALERT_KINDS, STATUS_LABEL, _initials, msg_json
from . import anamneza as panam
from . import card as pcard
from . import odontogram as podo
from .routes import (_PL_BADGE, _PL_CANAL, _PL_PER, _add_alert, _add_pay,
                     _add_plan, _appoint, _drop_doc, _erase, _free_slots,
                     _new_patient, _open_doc, _p_age, _peek_html, _pl_canal,
                     _pl_dmy, _pl_money, _pl_new_foot, _pl_stale_cut,
                     _pl_status, _pl_terms, _pl_trend, _plan_del, _plan_status,
                     _save_anamneza, _save_profile, _store_doc)

router = APIRouter()

_SORTS = ("last", "name", "new", "debt")


def _months(now: datetime) -> tuple[datetime, datetime, datetime]:
    """Начало прошлого, этого и следующего месяца — окно карточек над списком."""
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    prev_start = (month_start - timedelta(days=1)).replace(day=1)
    next_start = (month_start + timedelta(days=32)).replace(day=1)
    return prev_start, month_start, next_start


def _row(p: dict, now: datetime) -> dict:
    """Строка списка для клиента: даты уже в поясе клиники и в том виде, в
    каком их читает стойка; врач и статус выведены так же, как в `_pl_rows`."""
    row = dict(p)
    row["doctor"] = p["primary_doctor"] or p["last_doctor"] or ""
    nxt = p["next_at"]
    return {
        "id": p["id"],
        "name": p["name"] or "",
        "initials": _initials(p["name"] or "?"),
        "phone": p["phone"] or "",
        "email": p["email"] or "",
        "channel": _pl_canal(p),
        "birth": _pl_dmy(p["birth_date"]) if p["birth_date"] else "",
        "age": _p_age(p),
        "doctor": row["doctor"],
        "doctor_own": bool(p["primary_doctor"]),
        "last": _pl_dmy(p["last_at"]) if p["last_at"] else "",
        "next": nxt.astimezone(eng.TZ).strftime("%d.%m %H:%M") if nxt else "",
        "n_visits": p["n_visits"],
        "debt": p["debt"],
        "status": _pl_status(row, now),
        "archived": bool(p["archived"]),
    }


@router.get("/api/patients")
async def api_patients(request: Request, q: str = "", med: str = "", st: str = "",
                       ch: str = "", dat: str = "", sort: str = "last",
                       page: int = 1, per: int = 20):
    """Страница списка. Неизвестные st/ch/dat/sort/per откатываются к «все» и
    «по умолчанию», как на старой странице; page за пределом — последняя."""
    if (deny := api_guard(request)) is not None:
        return deny
    now = datetime.now(eng.TZ)
    q = q.strip()[:60]
    sort = sort if sort in _SORTS else "last"
    st = st if st in _PL_BADGE else ""
    ch = ch if ch in _PL_CANAL else ""
    dat = dat if dat in ("da", "avans") else ""
    per = per if per in _PL_PER else 20
    f = {"q": q, "terms": _pl_terms(q), "med": med, "st": st, "ch": ch, "dat": dat,
         # архивные скрыты, пока их не спросили явно — поиском или фильтром
         "show_archived": bool(q) or st == "arhivat",
         "stale_cut": _pl_stale_cut(now), "now": now}
    page = max(1, page)
    rows = await db.patients_rows(f, sort, per, (page - 1) * per)
    # счёт едет в строках; пустая страница за пределом — считаем и схлопываем
    total = rows[0]["total"] if rows else (await db.patients_count(f) if page > 1 else 0)
    pages = max(1, -(-total // per))
    if page > pages:
        page = pages
        rows = await db.patients_rows(f, sort, per, (page - 1) * per)
    n_arh = await db.patients_archived()
    # архивные спрятаны намеренно, но список обязан признаться, сколько прячет
    hidden = n_arh if not (q or st == "arhivat") else 0
    return msg_json(True, data={
        "rows": [_row(p, now) for p in rows],
        "total": total, "page": page, "pages": pages, "per": per, "sort": sort,
        "hidden_arh": hidden, "n_arh": n_arh,
    })


@router.get("/api/patients/summary")
async def api_patients_summary(request: Request):
    """То, что на экране не меняется от буквы в поиске: карточки над списком,
    варианты фильтров и подписи статусов. Один раз на открытие экрана."""
    if (deny := api_guard(request)) is not None:
        return deny
    now = datetime.now(eng.TZ)
    prev_start, month_start, next_start = _months(now)
    c = await db.patients_counts(month_start, prev_start)
    appts = [r for r in await db.day_appointments(prev_start, next_start)
             if r["source"] != "note" and r["status"] != "cancelled"]
    n_appt = sum(1 for r in appts if r["starts_at"] >= month_start)
    n_appt_prev = len(appts) - n_appt
    doctors = sorted(set(eng.DOCTORS.values()) | set(await db.patients_doctors()))
    # Telegram в фильтре — ПО ДАННЫМ, не по tg_configured(): см. старую страницу
    has_tg = await db.patients_have_tg()
    return msg_json(True, data={
        "tiles": [
            {"icon": "users", "tone": "g", "value": _pl_money(c["n_total"]),
             "foot": _pl_new_foot(c["n_new"]), "href": ""},
            {"icon": "med", "tone": "b", "value": str(c["n_new"]),
             "foot": _pl_trend(c["n_new"], c["n_new_prev"]), "href": ""},
            {"icon": "cal", "tone": "v", "value": str(n_appt),
             "foot": _pl_trend(n_appt, n_appt_prev), "href": "/admin/stats"},
        ],
        "doctors": doctors,
        "channels": [{"id": k, "label": v} for k, v in _PL_CANAL.items()
                     if k != "tg" or has_tg],
        "statuses": [{"id": k, "label": v[0], "cls": v[1]} for k, v in _PL_BADGE.items()],
        "per": list(_PL_PER),
        "clinic_doctors": list(eng.DOCTORS.values()),
    })


@router.get("/api/patients/{pid}/peek")
async def api_patient_peek(request: Request, pid: int):
    """Предпросмотр фиши куском разметки сервера (см. `_peek_html`)."""
    if (deny := api_guard(request)) is not None:
        return deny
    frag = await _peek_html(pid)
    if frag is None:
        return msg_json(False, status=404)
    return msg_json(True, data={"html": frag})


@router.post("/api/patients")
async def api_patient_new(request: Request):
    """Новая фиша из диалога списка. Ответ несёт адрес фиши — новой или той,
    что уже есть с этим телефоном (dup_pat), как редирект формы."""
    if (deny := api_guard(request)) is not None:
        return deny
    body = await api_body(request)
    if body is None:
        return msg_json(False, "bad_pat", field="name", status=422)

    def s(key: str) -> str:
        v = body.get(key, "")
        return v if isinstance(v, str) else ""

    code, pid = await _new_patient(s("name"), s("phone"), s("birth_date"),
                                   s("email"), s("primary_doctor"))
    if code == "bad_pat":
        return msg_json(False, code, field="name", status=422)
    return msg_json(True, code, data={"id": pid, "url": f"/admin/patient/{pid}?msg={code}"})


# ======================= фиша пациента (C18) =======================

# HTTP-код по коду ответа действия: отказ проверки — 422 (с именем поля);
# спор с состоянием (запрещённое ребро плана, удаление начатой позиции,
# выключенный врач, прошедший час, занятый слот) — 409. Коды и тексты — те
# же, что у форм (MSG_BANNER); тихий успех — пустой код.
_CONFLICT = {"bad_pdel", "bad_off", "past", "dup", "conflict"}
_OK = {"", "ok", "ok_card", "ok_tel_dup", "ok_arh", "ok_unarh", "ok_anam", "ok_pay",
       "pay_del", "ok_doc", "ok_anon", "ok_del", "ok_refuz"}


def _reply(code: str, data=None, field: str = "", *, conflict: bool = False):
    ok = code in _OK
    status = 200 if ok else 409 if (conflict or code in _CONFLICT) else 422
    return msg_json(ok, code, data=data, field=field, status=status)


def _views(request: Request) -> bool:
    """?views=1 — журнал доступа НА ЭКРАНЕ: лента дополняется просмотрами.
    Действия фиши несут тот же параметр, чтобы свежая фиша в ответе была в
    том же режиме, что открытая."""
    return request.query_params.get("views") == "1"


def _when(v) -> str:
    return v.astimezone(eng.TZ).strftime("%d.%m.%Y %H:%M") if hasattr(v, "astimezone") else ""


def _visit_row(v: dict, base: str, nextv: dict | None, recs: dict, now: datetime) -> dict:
    """Строка истории визитов: как её читает стойка, дневник — по правилу
    card.consult_kind, ссылка на дневник с возвратом в фишу."""
    rec = recs.get(v["id"])
    ck = pcard.consult_kind(v, rec, now)
    return {
        "id": v["id"], "when": _when(v["starts_at"]),
        "status": v["status"], "status_label": STATUS_LABEL.get(v["status"], v["status"]),
        "service": v["service"] or "", "doctor": v["doctor"] or "",
        "is_next": nextv is not None and v["id"] == nextv["id"],
        "consult": ck, "diag": pcard.rec_diag(rec)[:60] if ck == "rec" else "",
        "url": f"/admin/visit/{v['id']}?back={urllib.parse.quote(base)}",
    }


def _plan_item(it: dict, today) -> dict:
    due, overdue = pcard.due_view(it.get("due_date"), it["status"], today)
    st = it["status"]
    return {
        "id": it["id"], "tooth": it["tooth"], "procedure": it["procedure"] or "",
        "doctor": it["doctor"] or "", "status": st,
        "label": pcard.PLAN_LABEL.get(st, st), "price": it["price_mdl"],
        "due": "" if due == "—" else due, "overdue": overdue,
        "done": pcard.done_view(it),
        "motiv": (it.get("refuz_motiv") or "") if st == "refuzat" else "",
        # кнопки — по той же таблице, что рисует старая страница
        "next": pcard.PLAN_NEXT.get(st, ""),
        "refusable": st in pcard.PLAN_REFUSABLE,
        "deletable": st == "planificat",
    }


def _options() -> dict:
    """Справочники форм фиши — одни на клинику, едут с каждой фишей: виды
    предупреждений, вопросы анамнеза, категории документов, способы оплаты,
    номера зубов, врачи."""
    return {
        "alert_kinds": [{"id": k, "label": v} for k, v in ALERT_KINDS.items()],
        "anamneza_flags": [{"id": k, "label": v} for k, v in panam.FLAGS["ro"].items()],
        "anamneza_texts": [{"id": k, "label": lab, "placeholder": ph}
                           for k, lab, ph in panam.TEXTS],
        "doc_categories": [{"id": k, "label": v} for k, v in pcard.DOC_CATEGORIES.items()],
        "max_doc_mb": pcard.MAX_DOC_MB,
        "pay_methods": [{"id": m, "icon": pcard.PAY_ICON[m]} for m in db.PAY_METHODS],
        "plan_labels": dict(pcard.PLAN_LABEL),
        "tab_states": {k: list(v) for k, v in pcard.TAB_STATES.items()},
        "teeth": podo.FDI_UPPER + podo.FDI_LOWER,
        "milk": podo.FDI_MILK_UPPER + podo.FDI_MILK_LOWER,
        "doctors": list(eng.DOCTORS.values()),
    }


async def _card(pid: int, p: dict, *, views: bool, log_view: bool) -> dict:
    """Фиша целиком — те же выборки и те же расчёты (card.py), что у старой
    страницы. `log_view` — записать открытие в журнал доступа (закон 195):
    открытие экрана — да, обновление после действия — нет."""
    if log_view:
        await db.log_event(pid, "view", "Fișa deschisă")
    alerts = await db.patient_alerts(pid)
    tmap = await db.teeth_map(pid)
    plan = await db.plan_items(pid)
    pays = await db.payments(pid)
    fin = await db.patient_finance(pid)
    docs = await db.documents(pid)
    visits = await db.patient_appointments(pid, 1000)
    recs = await db.visit_records_map(pid)
    anam = await db.anamneza(pid)
    acts = await db.patient_activity(pid, 60, include_views=views)
    erasure = await db.erasure_kind(pid)
    now = datetime.now(eng.TZ)
    base = f"/admin/patient/{pid}"

    pv = pcard.plan_view(plan)
    vv = pcard.visits_view(visits, now)
    nextv, lastv = vv["next"], vv["last"]
    debt = pcard.debt_of(fin)
    av = pcard.anamneza_view(anam)
    sv = pcard.sold_view(fin)
    ap = pcard.appoint_view(p)
    created = p["created_at"].astimezone(eng.TZ)
    return {
        "id": pid, "name": p["name"] or "", "initials": _initials(p["name"] or "?"),
        "archived": bool(p.get("archived")), "erasure": erasure,
        "profile": {
            **{f: p.get(f) or "" for f in db.PATIENT_FIELDS},
            "lang": p.get("lang") or "ro",
            # дата рождения человеку — dd.mm.yyyy, у пациента из бота только год
            "birth": (_pl_dmy(p["birth_date"]) if p.get("birth_date")
                      else str(p.get("birth_year") or "")),
            "gender_label": {"m": "M", "f": "F"}.get(p.get("gender") or "", p.get("gender") or ""),
            "age": _p_age(p), "channel": pcard.channel(p),
            "created": created.strftime("%d.%m.%Y"), "year": created.strftime("%Y"),
        },
        "hero": {
            "pills": pcard.pills(p, alerts, debt, tmap),
            "last": ({"date": lastv["starts_at"].astimezone(eng.TZ).strftime("%d.%m.%Y"),
                      "service": lastv["service"] or ""} if lastv else None),
            "next": ({"date": nextv["starts_at"].astimezone(eng.TZ).strftime("%d.%m.%Y"),
                      "time": nextv["starts_at"].astimezone(eng.TZ).strftime("%H:%M"),
                      "service": nextv["service"] or "", "doctor": nextv["doctor"] or ""}
                     if nextv else None),
            "days_ago": pcard.days_ago(lastv, now),
        },
        "kpi": {"visits": len(vv["live"]), "active": pv["n_act"],
                "done": pv["cnt"]["finalizat"], "canc": vv["canc"]},
        "alerts": [{"id": a["id"], "kind": a["kind"],
                    "label": ALERT_KINDS.get(a["kind"], ""),
                    "icon": pcard.ALERT_ICON.get(a["kind"], "info"), "text": a["text"]}
                   for a in alerts],
        "anamneza": {
            "filled": av["filled"], "state": av["state"], "n_risk": av["n_risk"],
            "flags": [k for k in panam.FLAGS["ro"] if k in av["flags"]],
            "texts": {k: ((anam.get(k) if anam else "") or "") for k, *_ in panam.TEXTS},
            "marked": av["marked"],
            "free": [{"label": lab, "text": txt} for lab, txt in av["free"]],
            "when": av["when"].astimezone(eng.TZ).strftime("%d.%m.%Y") if av["when"] else "",
            "author": av["author"],
        },
        "plan": {
            "items": [_plan_item(it, now.date()) for it in pv["items"]],
            "counts": pv["cnt"], "n_act": pv["n_act"], "default_tab": pv["default_tab"],
            "total": pv["total"], "total_done": pv["total_done"],
            "n_track": pv["n_track"], "pct_done": pv["pct_done"],
        },
        "finance": {
            "charged": fin["charged"], "paid": fin["paid"], "debt": debt,
            "sold": {"kind": sv[0], "amount": sv[1]} if sv else None,
            "payments": [{"id": pl["id"], "when": _when(pl["at"]), "method": pl["method"],
                          "icon": pcard.PAY_ICON.get(pl["method"], "cash"),
                          "amount": abs(pl["amount_mdl"]), "neg": pl["amount_mdl"] < 0,
                          "note": pl["note"] or "", "taken_by": pl["taken_by"] or ""}
                         for pl in pays],
            "can_delete": can(request_user(), PERM_MONEY),
        },
        "documents": [{"id": d["id"], "filename": d["filename"],
                       "when": d["uploaded_at"].astimezone(eng.TZ).strftime("%d.%m.%Y"),
                       "size": pcard.doc_size(d["size"]), "mime": d["mime"] or "",
                       "category": d["category"],
                       "icon": pcard.DOC_ICON.get(d["category"], "file"),
                       "view": pcard.doc_view(d["mime"])} for d in docs],
        "visits": {
            "history": [_visit_row(v, base, nextv, recs, now) for v in visits[:pcard.HIST_SHOWN]],
            "live": [_visit_row(v, base, nextv, recs, now) for v in vv["live"]],
            "n_total": len(visits),
        },
        "activity": {
            "items": [{"id": a["id"], "kind": a["kind"],
                       "icon": pcard.ACT_ICON.get(a["kind"], ""), "text": a["text"],
                       "when": (a["at"].astimezone(eng.TZ).strftime("%d.%m.%Y")
                                if hasattr(a["at"], "astimezone") else ""),
                       "hhmm": (a["at"].astimezone(eng.TZ).strftime("%H:%M")
                                if hasattr(a["at"], "astimezone") else ""),
                       "who": pcard.who(a["actor"])} for a in acts],
            "shown": pcard.ACT_SHOWN, "views": views,
        },
        "appoint": {
            "services": [{"id": k, "label": v["ro"]} for k, v in eng.SERVICES.items()],
            "doctors": ap["svc_docs"], "names": dict(eng.ACTIVE_DOCTORS),
            "primary": ap["prim"], "today": now.date().isoformat(),
        },
        "options": _options(),
    }


async def _card_reply(request: Request, pid: int, code: str, field: str = "", *,
                      conflict: bool = False):
    """Ответ действия: отказ — кодом без данных, удача — свежая фиша."""
    if code not in _OK:
        return _reply(code, field=field, conflict=conflict)
    p = await db.get_patient(pid)
    if not p:
        return msg_json(False, status=404)
    return _reply(code, data=await _card(pid, p, views=_views(request), log_view=False))


async def _owned(pid: int):
    """(отказ | None, пациент | None): фиша существует. Вход каждый маршрут
    проверяет САМ (`api_guard` в теле) — так требует сторож раскладки, и так
    охрана видна там, где решается доступ, а не за помощником."""
    p = await db.get_patient(pid)
    if not p:
        return msg_json(False, status=404), None
    return None, p


def _s(body: dict | None, key: str) -> str:
    v = (body or {}).get(key)
    return "" if v is None else str(v)


@router.get("/api/patients/{pid}")
async def api_patient_card(request: Request, pid: int):
    """Фиша целиком. Пишет открытие в журнал доступа, как старая страница."""
    if (deny := api_guard(request)) is not None:
        return deny
    deny, p = await _owned(pid)
    if deny is not None:
        return deny
    return msg_json(True, data=await _card(pid, p, views=_views(request), log_view=True))


@router.get("/api/patients/{pid}/teeth")
async def api_patient_teeth(request: Request, pid: int):
    """Компактная одонтограмма фиши — тем же куском разметки, что рисует
    старая страница (`odontogram.card`: обе дуги, оба вида, диалог зуба,
    мосты). ⚠️ Точка интеграции до C21: клиент вставляет кусок и исполняет
    его скрипты; форма зуба по-прежнему уходит POST-ом на старый маршрут и
    возвращает страницу с ?msg=. Данные зубов React получит на своём этапе."""
    if (deny := api_guard(request)) is not None:
        return deny
    deny, p = await _owned(pid)
    if deny is not None:
        return deny
    tmap = await db.teeth_map(pid)
    tooth_acts = await db.tooth_activity(pid)
    punti = await db.bridges(pid)
    e = html.escape
    doc_opts = "".join(f"<option value='{e(n)}'"
                       f"{' selected' if p.get('primary_doctor') == n else ''}>{e(n)}</option>"
                       for n in eng.DOCTORS.values())
    return msg_json(True, data={
        "html": podo.card(tmap, tooth_acts, doc_opts, f"/admin/patient/{pid}", punti)})


@router.get("/api/patients/{pid}/activity")
async def api_patient_activity(request: Request, pid: int):
    """Лента отдельно — для переключения «accesările» без повторного
    открытия фиши (второй строки «Fișa deschisă» в журнале быть не должно)."""
    if (deny := api_guard(request)) is not None:
        return deny
    deny, p = await _owned(pid)
    if deny is not None:
        return deny
    card = await _card(pid, p, views=_views(request), log_view=False)
    return msg_json(True, data=card["activity"])


@router.post("/api/patients/{pid}/profile")
async def api_patient_profile(request: Request, pid: int):
    if (deny := api_guard(request)) is not None:
        return deny
    deny, p = await _owned(pid)
    if deny is not None:
        return deny
    body = await api_body(request)
    if body is None:
        return _reply("bad_card", field="name")
    code = await _save_profile(pid, p, lambda f: _s(body, f))
    return await _card_reply(request, pid, code, pcard.BAD_FIELD.get(code, ""))


@router.post("/api/patients/{pid}/archive")
async def api_patient_archive(request: Request, pid: int):
    """{on: true|false} — архив = скрыть из списков; история и файлы остаются."""
    if (deny := api_guard(request)) is not None:
        return deny
    deny, p = await _owned(pid)
    if deny is not None:
        return deny
    body = await api_body(request)
    on = bool((body or {}).get("on", True))
    await db.set_archived(pid, on)
    return await _card_reply(request, pid, "ok_arh" if on else "ok_unarh")


@router.post("/api/patients/{pid}/erase")
async def api_patient_erase(request: Request, pid: int):
    """{confirm: 'STERG'}. ok_del — фиши больше нет, ответ несёт адрес списка;
    ok_anon — личность стёрта, фиша осталась под номером."""
    if (deny := api_guard(request)) is not None:
        return deny
    deny, p = await _owned(pid)
    if deny is not None:
        return deny
    body = await api_body(request)
    code = await _erase(pid, _s(body, "confirm"))
    if code == "ok_del":
        return _reply(code, data={"url": "/admin/search?msg=ok_del"})
    return await _card_reply(request, pid, code, "confirm" if code == "bad_erase" else "")


@router.post("/api/patients/{pid}/alerts")
async def api_patient_alert_add(request: Request, pid: int):
    if (deny := api_guard(request)) is not None:
        return deny
    deny, p = await _owned(pid)
    if deny is not None:
        return deny
    body = await api_body(request)
    code = await _add_alert(pid, _s(body, "kind"), _s(body, "text"))
    return await _card_reply(request, pid, code, "text" if code == "bad_card" else "")


@router.post("/api/patients/{pid}/alerts/{aid}/delete")
async def api_patient_alert_del(request: Request, pid: int, aid: int):
    if (deny := api_guard(request)) is not None:
        return deny
    deny, p = await _owned(pid)
    if deny is not None:
        return deny
    await db.delete_alert(aid, pid)
    return await _card_reply(request, pid, "")


@router.post("/api/patients/{pid}/anamneza")
async def api_patient_anamneza(request: Request, pid: int):
    """{flags: [...], boli, medicamente, alergii, anestezie}."""
    if (deny := api_guard(request)) is not None:
        return deny
    deny, p = await _owned(pid)
    if deny is not None:
        return deny
    body = await api_body(request)
    raw = (body or {}).get("flags")
    checked = {str(x) for x in raw} if isinstance(raw, list) else set()
    code = await _save_anamneza(pid, checked, {k: _s(body, k) for k, *_ in panam.TEXTS})
    return await _card_reply(request, pid, code)


@router.post("/api/patients/{pid}/plan")
async def api_patient_plan_add(request: Request, pid: int):
    """{tooth, procedure, doctor, price, due_date} — строками, как из формы."""
    if (deny := api_guard(request)) is not None:
        return deny
    deny, p = await _owned(pid)
    if deny is not None:
        return deny
    body = await api_body(request)
    code = await _add_plan(pid, _s(body, "tooth"), _s(body, "procedure"),
                           _s(body, "doctor"), _s(body, "price"), _s(body, "due_date"))
    return await _card_reply(request, pid, code, "procedure" if code == "bad_card" else "")


@router.post("/api/patients/{pid}/plan/{item_id}/status")
async def api_patient_plan_status(request: Request, pid: int, item_id: int):
    """{to, motiv}. Запрещённое ребро — 409 bad_card; отказ без причины —
    422 bad_refuz с полем motiv."""
    if (deny := api_guard(request)) is not None:
        return deny
    deny, p = await _owned(pid)
    if deny is not None:
        return deny
    body = await api_body(request)
    code = await _plan_status(pid, item_id, _s(body, "to"), _s(body, "motiv"))
    return await _card_reply(request, pid, code, "motiv" if code == "bad_refuz" else "",
                             conflict=code == "bad_card")


@router.post("/api/patients/{pid}/plan/{item_id}/delete")
async def api_patient_plan_del(request: Request, pid: int, item_id: int):
    if (deny := api_guard(request)) is not None:
        return deny
    deny, p = await _owned(pid)
    if deny is not None:
        return deny
    return await _card_reply(request, pid, await _plan_del(pid, item_id))


@router.post("/api/patients/{pid}/payments")
async def api_patient_pay(request: Request, pid: int):
    """{amount, method, note}: сумма строкой, минус — возврат."""
    if (deny := api_guard(request)) is not None:
        return deny
    deny, p = await _owned(pid)
    if deny is not None:
        return deny
    body = await api_body(request)
    code = await _add_pay(pid, _s(body, "amount"), _s(body, "method") or "numerar",
                          _s(body, "note"))
    return await _card_reply(request, pid, code, "amount" if code == "bad_pay" else "")


@router.post("/api/patients/{pid}/payments/{pay_id}/delete")
async def api_patient_pay_del(request: Request, pid: int, pay_id: int):
    """Только директор (PERM_MONEY), как у формы: 403 no_access остальным."""
    if (deny := api_require(request, PERM_MONEY)) is not None:
        return deny
    if not (await db.get_patient(pid)):
        return msg_json(False, status=404)
    await db.delete_payment(pay_id, pid)
    return await _card_reply(request, pid, "pay_del")


@router.post("/api/patients/{pid}/documents")
async def api_patient_doc_upload(request: Request, pid: int, file: UploadFile = File(...)):
    """multipart: file + category. Тот же _store_doc, что у формы."""
    if (deny := api_guard(request)) is not None:
        return deny
    deny, p = await _owned(pid)
    if deny is not None:
        return deny
    form = await request.form()
    code = await _store_doc(pid, file, str(form.get("category") or "alt"))
    return await _card_reply(request, pid, code, "file" if code == "bad_doc" else "")


@router.post("/api/patients/{pid}/documents/{doc_id}/delete")
async def api_patient_doc_del(request: Request, pid: int, doc_id: int):
    if (deny := api_guard(request)) is not None:
        return deny
    deny, p = await _owned(pid)
    if deny is not None:
        return deny
    await _drop_doc(pid, doc_id)
    return await _card_reply(request, pid, "")


@router.post("/api/documents/{doc_id}/open")
async def api_doc_open(request: Request, doc_id: int):
    """Открыть файл программой этого компьютера. Ответ всегда 200: запрос
    состоялся, а `opened: false` с причиной велит клиенту скачать файл —
    так же, как старый скрипт откатывался на ссылку."""
    if (deny := api_guard(request)) is not None:
        return deny
    err = await _open_doc(request, doc_id)
    return msg_json(True, data={"opened": not err, "reason": err})


@router.get("/api/patients/{pid}/slots")
async def api_patient_slots(request: Request, pid: int, date: str = "",
                            doctor: str = "", service: str = ""):
    """Свободные старты у врача на дату — тот же eng.free_starts, что у бота."""
    if (deny := api_guard(request)) is not None:
        return deny
    deny, p = await _owned(pid)
    if deny is not None:
        return deny
    return msg_json(True, data={"slots": await _free_slots(date, doctor, service)})


@router.post("/api/patients/{pid}/appoint")
async def api_patient_appoint(request: Request, pid: int):
    """{date, time, doctor, service}. Кривые данные и не влезающий в часы
    клиники визит — 422; выключенный врач, прошедший час, дубль у пациента и
    занятый у врача слот — 409. Коды те же, что у формы."""
    if (deny := api_guard(request)) is not None:
        return deny
    deny, p = await _owned(pid)
    if deny is not None:
        return deny
    body = await api_body(request)
    code = await _appoint(pid, _s(body, "date"), _s(body, "time"),
                          _s(body, "doctor"), _s(body, "service"))
    return await _card_reply(request, pid, code, "time" if code in ("bad", "outside") else "")
