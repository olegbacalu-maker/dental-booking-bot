"""JSON API списка пациентов (DentPilot 2.0): поиск, страница, предпросмотр,
новая фиша.

Старая страница «Pacienți» (`routes.admin_search`) читает всю картотеку в
память (`_pl_rows`) и остаётся как есть. Здесь отбор, порядок и страница
считаются базой (`db.patients_count` / `db.patients_rows`), а статус строки,
подписи карточек, разбор запроса и правила новой фиши — те же функции
модуля (`_pl_status`, `_pl_trend`, `_pl_terms`, `_new_patient`,
`_peek_html`), чтобы у двух страниц не разошлись ни слова, ни цифры.
Паритет выдачи со старой страницей держит `test_patients_api.suite_parity`.

Правило то же: `core`, `db`, `engine` — да, `main.py` — нет.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Request

from ... import db
from ... import engine as eng
from ...core.api import api_body, api_guard
from ...core.layout import _initials, msg_json
from .routes import (_PL_BADGE, _PL_CANAL, _PL_PER, _new_patient, _p_age,
                     _peek_html, _pl_canal, _pl_dmy, _pl_money, _pl_new_foot,
                     _pl_stale_cut, _pl_status, _pl_terms, _pl_trend)

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
