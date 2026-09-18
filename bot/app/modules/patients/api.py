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

import urllib.parse
from datetime import datetime, timedelta

from fastapi import APIRouter, File, Request, UploadFile

from ... import db
from ... import engine as eng
from ... import teeth_svg as tsvg
from ...core.api import api_body, api_guard, api_require
from ...core.auth import PERM_MONEY, can, request_user
from ...core.layout import ALERT_KINDS, STATUS_LABEL, _initials, msg_json
from . import anamneza as panam
from . import card as pcard
from . import odontogram as podo
from . import perio as pperio
from . import visit as pvisit
from .routes import (_PL_BADGE, _PL_CANAL, _PL_PER, _add_alert, _add_bridge,
                     _add_pay, _add_plan, _appoint, _del_bridge, _drop_doc,
                     _erase, _free_slots, _new_patient, _open_doc, _p_age,
                     _peek_html, _perio_absent, _perio_ctx, _perio_del,
                     _pl_canal, _pl_dmy, _pl_money, _pl_new_foot,
                     _pl_stale_cut, _pl_status, _pl_terms, _pl_trend, _plan_del,
                     _plan_status, _save_anamneza, _save_perio, _save_profile,
                     _save_tooth, _save_visit, _sf_letters, _sf_map, _store_doc,
                     _visit_back, _visit_ctx)

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


# ======================= дневник визита (C19) =======================

def _visit_payload(a: dict, rec: dict | None, items: list, back: str) -> dict:
    """Страница «Consultație» данными: визит, запись (или её нет), можно ли
    писать, графы и шаблоны (тексты сервера), позиции плана — выполненные
    на этом визите и открытые для отметки (только активные: отказ в списке
    галочек не показывается, см. visit.py)."""
    status = a.get("status") or ""
    editable = status not in pvisit.NO_FORM_STATUSES
    return {
        "appt": {"id": a["id"], "when": _when(a["starts_at"]), "patient_id": a["patient_id"],
                 "patient": a.get("name") or "", "service": a["service"] or "",
                 "doctor": a["doctor"] or "", "status": status,
                 "status_label": STATUS_LABEL.get(status, status),
                 "comment": a.get("comment") or ""},
        "record": ({**{k: (rec.get(k) or "") for k in db.VISIT_FIELDS},
                    "created": _when(rec["created_at"]),
                    "updated": _when(rec["updated_at"]) if rec.get("updated_at") else "",
                    "author": rec.get("author") or ""} if rec else None),
        "editable": editable,
        "note": "" if editable else pvisit.READONLY_NOTE,
        "fields": pvisit.fields(),
        "templates": pvisit.templates(),
        "plan": {
            "linked": [{"id": it["id"], "text": pvisit.item_text(it)}
                       for it in items if it.get("appointment_id") == a["id"]],
            "open": [{"id": it["id"], "text": pvisit.item_text(it),
                      "in_lucru": it["status"] == "in_lucru"}
                     for it in items if it["status"] in db.PLAN_ACTIVE],
        },
        "back": back,
    }


@router.get("/api/visits/{aid}")
async def api_visit(request: Request, aid: int, back: str = ""):
    """Дневник визита. 404 — визита нет или это заметка без пациента."""
    if (deny := api_guard(request)) is not None:
        return deny
    ctx = await _visit_ctx(aid)
    if ctx is None:
        return msg_json(False, status=404)
    a, rec, items = ctx
    return msg_json(True, data=_visit_payload(a, rec, items, _visit_back(back, a["patient_id"])))


@router.post("/api/visits/{aid}")
async def api_visit_save(request: Request, aid: int):
    """{acuze, examen, diagnostic, tratament, recomandari, done: [id…], back}.
    Отменённому/неявившемуся — 409 bad_vst; пустая запись — 422 bad_visit;
    удача — ok_visit и свежая страница."""
    if (deny := api_guard(request)) is not None:
        return deny
    ctx = await _visit_ctx(aid)
    if ctx is None:
        return msg_json(False, status=404)
    a = ctx[0]
    body = await api_body(request)
    if body is None:
        return msg_json(False, "bad_visit", status=422)
    raw = body.get("done")
    done = [str(x) for x in raw] if isinstance(raw, list) else []
    code = await _save_visit(aid, a, {k: _s(body, k) for k in db.VISIT_FIELDS}, done)
    if code == "bad_vst":
        return msg_json(False, code, status=409)
    if code == "bad_visit":
        return msg_json(False, code, status=422)
    a, rec, items = await _visit_ctx(aid)
    return msg_json(True, code, data=_visit_payload(
        a, rec, items, _visit_back(_s(body, "back"), a["patient_id"])))


# ======================= одонтограмма (C21) =======================
# Контракт — docs/dentpilot-2/clinical-chart.md: геометрия и клинические
# правила серверные, React собирает и обслуживает интерактив. Модель —
# odontogram.model; удача действия возвращает свежую модель целиком.

async def _odontogram(pid: int, p: dict) -> dict:
    tmap = await db.teeth_map(pid)
    tooth_acts = await db.tooth_activity(pid)
    punti = await db.bridges(pid)
    m = podo.model(tmap, tooth_acts, punti)
    m["patient"] = {"id": pid, "name": p["name"] or "",
                    "primary_doctor": p.get("primary_doctor") or ""}
    m["doctors"] = list(eng.DOCTORS.values())
    # ⭐ Последний пародонтальный замер по зубам — «зуб 16 один объект»
    # (контракт clinical-chart.md › «Один зуб на оба инструмента»). Осмотр тот
    # же, что печатается в 043/e: `perio_last` пропускает пустые листы.
    exam, prows = await db.perio_last(pid)
    m["perio"] = pperio.tooth_lines(exam, prows)
    return m


async def _odo_reply(pid: int, code: str, *, ok: set, field: str = "",
                     conflict: set = frozenset()):
    if code not in ok:
        return msg_json(False, code, field=field, status=409 if code in conflict else 422)
    p = await db.get_patient(pid)
    if not p:
        return msg_json(False, status=404)
    return msg_json(True, code, data=await _odontogram(pid, p))


@router.get("/api/patients/{pid}/odontogram")
async def api_odontogram(request: Request, pid: int):
    """Одонтограмма данными: зубы с рисунками обоих видов (цели поверхностей
    внутри), история, дуги, мосты, легенда, словари."""
    if (deny := api_guard(request)) is not None:
        return deny
    deny, p = await _owned(pid)
    if deny is not None:
        return deny
    return msg_json(True, data=await _odontogram(pid, p))


@router.post("/api/patients/{pid}/teeth/{tooth}")
async def api_tooth_save(request: Request, pid: int, tooth: int):
    """{state, state0, note, doctor, surfaces, marks}. Намерение — явным
    полем (прайор 08-16): `surfaces` — карта {буква: состояние} или список
    букв (одно состояние на все), отсутствует/null — форма о поверхностях не
    сообщала; `marks` — список или null по той же причине; `state0` — что
    показала форма. Отказ проверки 422 с полем."""
    if (deny := api_guard(request)) is not None:
        return deny
    deny, p = await _owned(pid)
    if deny is not None:
        return deny
    body = await api_body(request)
    if body is None:
        return msg_json(False, "bad_card", field="state", status=422)
    raw = body.get("surfaces")
    sf, sfmap = None, None
    if isinstance(raw, dict):
        sfmap = _sf_map(raw)
    elif isinstance(raw, (list, str)):
        sf = _sf_letters(raw)
    marks = body.get("marks")
    marks = [str(x) for x in marks] if isinstance(marks, list) else None
    st0 = body.get("state0")
    code = await _save_tooth(pid, tooth, _s(body, "state"), _s(body, "note"),
                             _s(body, "doctor"), sf=sf, sfmap=sfmap,
                             state0=str(st0) if isinstance(st0, str) else None, marks=marks)
    return await _odo_reply(pid, code, ok={"ok_card"}, field="state" if code == "bad_card" else "")


@router.post("/api/patients/{pid}/bridges")
async def api_bridge_add(request: Request, pid: int):
    """{teeth: [[47,'stalp'],[46,'corp'],…], material, material_alt, doctor}.
    Порядок и правила дуги — bridge_norm (422 bad_punte); зуб уже в другом
    мосту — 409 dup_punte."""
    if (deny := api_guard(request)) is not None:
        return deny
    deny, p = await _owned(pid)
    if deny is not None:
        return deny
    body = await api_body(request)
    raw = (body or {}).get("teeth")
    teeth = raw if isinstance(raw, list) else []
    code = await _add_bridge(pid, teeth, _s(body, "material"), _s(body, "material_alt"),
                             _s(body, "doctor"))
    return await _odo_reply(pid, code, ok={"ok_punte"}, field="teeth" if code == "bad_punte" else "",
                            conflict={"dup_punte"})


@router.post("/api/patients/{pid}/bridges/{bid}/delete")
async def api_bridge_del(request: Request, pid: int, bid: int):
    if (deny := api_guard(request)) is not None:
        return deny
    deny, p = await _owned(pid)
    if deny is not None:
        return deny
    code = await _del_bridge(pid, bid)
    if code != "ok_punte_del":
        return msg_json(False, status=404)
    return msg_json(True, code, data=await _odontogram(pid, p))


# ======================= пародонтограмма (C23) =======================
# Единица здесь — датированный ОСМОТР, а не текущее состояние зуба: карта
# пародонта имеет смысл только в сравнении во времени. Поэтому адрес несёт
# `?exam=`, а удача действия возвращает выбранный осмотр целиком со сводкой:
# BOP%, среднюю глубину и CAL СОХРАНЁННОГО осмотра считает сервер
# (perio.summary), и эти числа уходят в печать и в §4 формы 043/e.
# ⚠️ У клиента есть свой счёт тех же формул (`summarize`), но только для
# ЧЕРНОВИКА: врач видит BOP% пока диктует, а не после записи. Владелец правила
# остаётся один — записанные числа всегда приезжают отсюда.


def _tok(value) -> str:
    """Одно значение в проволочный вид формы. Всё нечисловое и отрицательное
    становится «x» — не-числом, которое разбор (`_perio_mm`) читает как «не
    измеряли». ⛔ Не «0» и не обрезка по краю диапазона: 99 мм — это опечатка
    ввода, и записать её пятнадцатью значит выдумать глубокий карман."""
    if isinstance(value, bool):
        return "x"
    if isinstance(value, int):
        return str(value) if value >= 0 else "x"
    if isinstance(value, str):
        t = value.strip()
        return t if t.isdecimal() else "x"
    return "x"


def _perio_rows(raw) -> list:
    """{"16": {pd, rec, bop, mob, furc}} → строки зубов ТЕМ ЖЕ разбором, что у
    старой формы (`tsvg.parse_perio`).

    ⛔ Второго парсера у API нет намеренно: диапазоны, длина шести точек и
    отбрасывание чужих номеров живут в `teeth_svg`, и разойтись им негде.
    ⚠️ Упаковка (`pack_perio`) для этого не годится: она ЗАЖИМАЕТ значение в
    диапазон, а разбор — отбрасывает. Через API пришло бы «15 мм» там, где та
    же опечатка в форме даёт «не измеряли».
    """
    if not isinstance(raw, dict):
        return []
    parts, sent = [], []
    for num, row in raw.items():
        if not str(num).strip().isdecimal() or not isinstance(row, dict):
            continue
        if not PERIO_ROW_KEYS <= row.keys():
            # ⛔ Строка зуба — ЕДИНИЦА, и присылается целиком. Недостающее поле
            # молча стало бы нулями, то есть стёрло бы рецессию, кровоточивость
            # или подвижность у зуба, которого никто не трогал (прайор 08-16:
            # «поля нет» ≠ «стереть»). Здесь нельзя ответить «не сообщали»: в
            # базе строка перезаписывается целиком, половины у неё не бывает.
            raise ValueError(f"tooth {num}: строка зуба неполная")
        bop = row.get("bop")
        if isinstance(bop, list):
            bop = "".join("1" if x else "0" for x in bop)
        # разделители проволочного вида внутри значения сломали бы строку
        # раньше разбора — гасим их нулём, остальное решает _perio_flags
        bop = "".join("0" if ch in ";/:," else ch for ch in str(bop or ""))[:6]

        def mm(key: str) -> str:
            src = row.get(key)
            return ",".join(_tok(x) for x in (src if isinstance(src, list) else [])[:6])

        sent.append(int(str(num).strip()))
        parts.append(f"{int(str(num).strip())}:{mm('pd')}/{mm('rec')}/{bop}"
                     f"/{_tok(row.get('mob'))}/{_tok(row.get('furc'))}")
    rows = tsvg.parse_perio(";".join(parts))
    got = {r["tooth"]: r for r in rows}
    for n in sent:
        if n not in pperio.PERIO_TEETH:
            continue          # молочные и чужие номера на лист не попадают
        r = got.get(n)
        if r is None or not (any(r["pd"]) or any(r["rec"]) or "1" in r["bop"]
                             or r["mob"] or r["furc"]):
            # ⛔ Строка прислана, а показаний из неё не вышло ни одного (дробные
            # миллиметры, слова, null) — это ОТКАЗ, а не удаление зуба. «Стереть»
            # выражается иначе: зуб НЕ присылают, но называют в `shown`. Иначе
            # `3.5` в шести точках молча снесло бы измеренный зуб с ответом 200.
            raise ValueError(f"tooth {n}: ни одного показания")
    return rows


PERIO_ROW_KEYS = frozenset({"pd", "rec", "bop", "mob", "furc"})


def _perio_covers(raw) -> set:
    """Зубы, О КОТОРЫХ запись СООБЩАЕТ: те, что тронули на этом экране. Поля
    нет — «не сообщали», и тогда не стирается ничего (прайор 08-16): клиент,
    тронувший один зуб, не должен обнулять остальную карту — а место,
    открывшее осмотр раньше, сносить чужой зуб (18.09).
    ⚠️ Номер принимается и строкой: внутри `teeth` строковые числа берутся
    везде (и ключ зуба, и значения), и только здесь строгость молча съедала бы
    намерение стереть — отказа при этом человек не увидел бы."""
    if not isinstance(raw, list):
        return set()
    out = set()
    for x in raw:
        if isinstance(x, bool):
            continue
        if isinstance(x, int):
            out.add(x)
        elif isinstance(x, str) and x.strip().isdecimal() and len(x.strip()) <= 3:
            out.add(int(x.strip()))
    return out & set(pperio.PERIO_TEETH)


def _perio_field(body: dict | None, key: str) -> str | None:
    """None — поля не было («не сообщали»), строка — значение."""
    v = (body or {}).get(key)
    return v if isinstance(v, str) else None


async def _perio_model(pid: int, p: dict, want: str) -> dict:
    exams, cur = await _perio_ctx(pid, want)
    rows = await db.perio_rows(cur["id"]) if cur else []
    tmap = await db.teeth_map(pid)
    return pperio.model(p, exams, cur, rows, tmap, _perio_absent(tmap),
                        list(eng.DOCTORS.values()))


@router.get("/api/patients/{pid}/perio")
async def api_perio(request: Request, pid: int, exam: str = ""):
    """Осмотры пациента и измерения выбранного (по умолчанию — свежего):
    шесть точек на зуб, CAL, сводка, пороги, рисунки зубов и справочники.
    ⛔ GET ничего не создаёт: пустая карта приезжает с `exam: null`."""
    if (deny := api_guard(request)) is not None:
        return deny
    deny, p = await _owned(pid)
    if deny is not None:
        return deny
    return msg_json(True, data=await _perio_model(pid, p, exam))


@router.post("/api/patients/{pid}/perio/exams")
async def api_perio_new(request: Request, pid: int):
    """Новый (пустой) осмотр. Летопись пишется при сохранении измерений."""
    if (deny := api_guard(request)) is not None:
        return deny
    deny, p = await _owned(pid)
    if deny is not None:
        return deny
    eid = await db.perio_new(pid)
    return msg_json(True, "ok_perio_new", data=await _perio_model(pid, p, str(eid)))


@router.post("/api/patients/{pid}/perio/{eid}")
async def api_perio_save(request: Request, pid: int, eid: int):
    """{teeth: {"16": {pd, rec, bop, mob, furc}}, shown: [16, …], doctor, note}.

    Намерение — явными полями: `covers` называет зубы, О КОТОРЫХ запись
    сообщает (стираются только они и только неприсланные), `doctor`/`note` без
    поля не трогаются, `rev` — отпечаток осмотра при загрузке: разошёлся —
    ответ тот же 200, но словами «осмотр правили и в другом месте»
    (ok_perio_merged). ⛔ Строка зуба —
    единица и присылается ЦЕЛИКОМ (все пять полей), иначе 422: половина строки
    обнулила бы остальные измерения того же зуба. ⛔ Строка, из которой не
    вышло ни одного показания, — тоже 422: «стереть» выражается тем, что зуб
    НЕ прислан, хотя назван в `covers`. Чужой осмотр — 404 bad_perio; удача —
    свежая карта со сводкой."""
    if (deny := api_guard(request)) is not None:
        return deny
    deny, p = await _owned(pid)
    if deny is not None:
        return deny
    body = await api_body(request)
    if body is None:
        return msg_json(False, "bad_perio", field="teeth", status=422)
    try:
        rows = _perio_rows(body.get("teeth"))
    except ValueError:
        return msg_json(False, "bad_perio", field="teeth", status=422)
    code = await _save_perio(pid, str(eid), rows,
                             _perio_covers(body.get("covers")),
                             _perio_field(body, "doctor"),
                             _perio_field(body, "note"),
                             _perio_field(body, "rev") or "")
    if not code.startswith("ok"):
        return msg_json(False, code, status=404)
    return msg_json(True, code, data=await _perio_model(pid, p, str(eid)))


@router.post("/api/patients/{pid}/perio/{eid}/delete")
async def api_perio_del(request: Request, pid: int, eid: int):
    """Снять ПУСТОЙ осмотр (двойной клик по «Examen nou»). С измерениями —
    409: медицинскую запись правят, а не заставляют исчезнуть."""
    if (deny := api_guard(request)) is not None:
        return deny
    deny, p = await _owned(pid)
    if deny is not None:
        return deny
    code = await _perio_del(pid, eid)
    if code == "bad_perio":
        return msg_json(False, code, status=404)
    if code != "ok_perio_del":
        return msg_json(False, code, status=409)
    return msg_json(True, code, data=await _perio_model(pid, p, ""))
