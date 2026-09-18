"""Модель фиши пациента: расчёты над строками базы, одни на старую страницу
(`routes.admin_patient`) и на JSON API (`api.api_patient_card`, C18).

До 18.09 вся арифметика фиши — сумма активного плана, прогресс без отказов,
долг и сальдо, «следующий» и «последний» визит, пилюли шапки, цифры KPI,
риски анамнеза, чем открывать документ — жила внутри f-строк обработчика на
девятьсот строк и проверялась только через готовую разметку. Здесь она
вынесена ФУНКЦИЯМИ, а не скопирована: старая страница зовёт их и рисует
HTML, API зовёт их и отдаёт JSON, и второго счёта у фиши нет. Что именно
считает каждая — записано на ней; паритет двух экранов держит
`tests/test_patient_card.py`.

Модуль СЧИТАЕТ и не рисует: ни `_ic`, ни `html.escape`, ни `db` внутри —
значки едут именами из `layout._I` (старая страница оборачивает их в `_ic`,
клиент — в `<Icon>`), тексты — сырыми, экранирует тот, кто вставляет в
разметку. Импорт только `routes → card` и `api → card`; обратного нет и
быть не должно.
"""
from __future__ import annotations

from datetime import date, datetime

from ... import db
from ... import engine as eng
from ...core.layout import LIVE_STATUSES, _age
from . import anamneza as panam

# ---------- словари фиши (переехали из routes.py 18.09, там остались псевдонимы) ----------

# Переходы плана НАПРАВЛЕННЫЕ, а не по кругу (просьба Олега 08-07: кнопка
# «следующий статус» гоняла процедуру по кольцу, и финал воскресал в
# «Planificat» одним случайным кликом). Из финала есть ровно один тихий выход —
# «Redeschide» обратно в работу, для исправления ошибки; пути «финал →
# запланировано» не существует. Охрана в маршруте смотрит на пару (откуда,
# куда): устаревшая вкладка не пришлёт запрещённое ребро.
# ОТКАЗ (08-11) — не четвёртая ступень, а боковой выход: ст.13(5) Legea
# 263/2005 требует, чтобы отказ пациента остался В МЕДДОКУМЕНТАЦИИ с указанием
# возможных последствий, а не был вычеркнут. Поэтому отказаться можно и от
# запланированного, и из работы, а вернуться — только в «Planificat»: заново
# начатая после отказа процедура это новое решение пациента, а не продолжение
# старого. ⛔ Из «Finalizat» в «Refuzat» ребра нет: отказаться от сделанного
# нельзя, ошибку исправляет «Redeschide».
PLAN_EDGES = {("planificat", "in_lucru"), ("in_lucru", "finalizat"),
              ("finalizat", "in_lucru"),
              ("planificat", "refuzat"), ("in_lucru", "refuzat"),
              ("refuzat", "planificat")}

# переход, у которого причина ОБЯЗАТЕЛЬНА: «отказался» без «от чего именно
# предупредили» — это не запись по ст.13(5), а пустая отметка
PLAN_NEEDS_MOTIV = ("refuzat",)

PLAN_LABEL = {"planificat": "Planificat", "in_lucru": "În lucru",
              "finalizat": "Finalizat", "refuzat": "Refuzat"}

# Кнопка «следующий шаг» у позиции — ОДНА на статус, и это ребро из
# PLAN_EDGES (Începe / Finalizează / Redeschide / Reia). Отказ — боковой
# выход, он есть только у незакрытых; удалять можно только нетронутое
# (см. patient_plan_del). Старая страница рисует кнопки по этой же таблице.
PLAN_NEXT = {"planificat": "in_lucru", "in_lucru": "finalizat",
             "finalizat": "in_lucru", "refuzat": "planificat"}
PLAN_REFUSABLE = ("planificat", "in_lucru")

# какие статусы показывает каждая вкладка плана — ОДИН словарь на сервер и
# на браузер; пока правило жило выражением «не finalizat», отказ попадал в
# «Active» молча
TAB_STATES = {"act": db.PLAN_ACTIVE, "finalizat": ("finalizat",),
              "refuzat": ("refuzat",)}

DOC_CATEGORIES = {"radiografie": "Radiografie", "acord": "Acord / contract",
                  "trimitere": "Trimitere", "alt": "Alt document"}
MAX_DOC_MB = 25

# растровые картинки, которые безопасно отдавать inline (для превью в фише).
# ⛔ SVG и HTML сюда НЕ входят: файл с того же origin, показанный inline, — это
# чужой скрипт в нашем журнале.
INLINE_MIME = {"image/png", "image/jpeg", "image/webp", "image/gif"}
# PDF смотрим внутри программы (в WebView2 свой просмотрщик), но множество
# отдельное: миниатюры и <img> остаются только у растра.
PDF_MIME = {"application/pdf"}

# отказ сохранения профиля ПОКАЗЫВАЕТ виноватое поле: форма раскрыта, поле
# красное. Баннер «Date invalide» без этого заставлял искать ошибку перебором
BAD_FIELD = {"bad_card": "name", "bad_bd": "birth_date", "bad_idnp": "idnp"}

# Значки — ИМЕНАМИ из layout._I: старая страница заворачивает их в разметку
# своим помощником, клиент рисует <Icon>. Сами подписи видов (ALERT_KINDS)
# живут в core/layout.
ALERT_ICON = {"allergy": "sos", "medication": "pill", "warning": "alarm", "info": "info"}
ALERT_TONE = {"allergy": "orange", "medication": "orange", "warning": "red"}
DOC_ICON = {"radiografie": "xray", "acord": "note", "trimitere": "mail", "alt": "file"}
PAY_ICON = {"numerar": "cash", "card": "card", "transfer": "bank"}
ACT_ICON = {"appt_new": "cal", "appt_status": "check", "appt_cancel": "ban",
            "tooth": "tooth", "plan_add": "plus", "plan_status": "refresh",
            "plan_del": "minus", "doc_add": "clip", "doc_del": "trash",
            "alert_add": "sos", "profile": "pen", "archive": "box",
            # выдача копии данных — событие, о котором спросят на проверке;
            # в общей ленте оно обязано быть заметным, а не точкой по умолчанию
            "export": "download", "acord": "clipboard", "plan_acord": "clipboard",
            "consult": "med", "fisa043": "print", "anamneza": "note",
            "view": "eye", "doc_view": "eye", "erase": "erase"}

# сколько строк летописи фиша показывает сразу; остальные — за кнопкой
ACT_SHOWN = 10
# сколько визитов рисует история в правой колонке
HIST_SHOWN = 8


# ---------- профиль ----------

def age_of(p: dict) -> int | None:
    """Возраст: по полной дате рождения, иначе по году (пациент из бота)."""
    if p.get("birth_date"):
        try:
            bd = date.fromisoformat(p["birth_date"])
            t = datetime.now(eng.TZ).date()
            return t.year - bd.year - ((t.month, t.day) < (bd.month, bd.day))
        except ValueError:
            pass
    return _age(p.get("birth_year"))


def channel(p: dict) -> str:
    """Откуда пациент: бот, стойка или веб — по префиксу ключа сессии."""
    key = p.get("session_key") or ""
    return ("Telegram" if key.startswith("tg:")
            else "recepție" if key.startswith("manual:") else "web")


def money(n: int) -> str:
    """1200 → «1 200»: тысячи пробелом, как всюду в фише."""
    return f"{n:,}".replace(",", " ")


# ---------- план лечения ----------

def plan_key(it: dict) -> tuple:
    """Порядок осмысленный, а не «как добавляли»: работа сверху,
    запланированное по сроку, законченное свежим вперёд, отказы последними."""
    st = it["status"]
    if st == "in_lucru":
        return (0, 0.0, it["id"])
    if st == "planificat":
        return (1, str(it.get("due_date") or "9999-99-99"), it["id"])
    da = it.get("done_at")
    return (2 if st == "finalizat" else 3,
            -(da.timestamp() if hasattr(da, "timestamp") else 0.0),
            -it["id"])


def plan_view(plan: list) -> dict:
    """Сводка плана: позиции в порядке показа, счёт по статусам, вкладка по
    умолчанию, суммы и прогресс.

    ⚠️ Отказ не деньги НИ В ОДНОЙ из двух сумм: он не ждёт оплаты (не «plan
    activ») и не выполнен (не «finalizate»). ⚠️ Прогресс считается от того,
    что клиника ещё может сделать: отказ из знаменателя выпадает, иначе план
    из трёх процедур, одну из которых пациент отверг, навсегда застревает на
    66% «выполнено». Законченное по умолчанию спрятано; если активного не
    осталось — открывается первая НЕПУСТАЯ вкладка, а не пустой экран
    (раньше запасной была «Finalizate», и план из одних отказов открывался
    пустым)."""
    cnt = {k: sum(1 for it in plan if it["status"] == k)
           for k in ("planificat", "in_lucru", "finalizat", "refuzat")}
    n_act = cnt["planificat"] + cnt["in_lucru"]
    default_tab = ("act" if n_act or not plan
                   else "finalizat" if cnt["finalizat"] else "refuzat")
    total = sum(it["price_mdl"] for it in plan
                if it["price_mdl"] and it["status"] in db.PLAN_ACTIVE)
    total_done = sum(it["price_mdl"] for it in plan
                     if it["price_mdl"] and it["status"] == "finalizat")
    n_track = len(plan) - cnt["refuzat"]
    return {
        "items": sorted(plan, key=plan_key),
        "cnt": cnt, "n_act": n_act, "default_tab": default_tab,
        "total": total, "total_done": total_done,
        "n_track": n_track,
        "pct_done": round(100 * cnt["finalizat"] / n_track) if n_track else 0,
    }


def due_view(due, status: str, today: date) -> tuple[str, bool]:
    """Срок позиции: («dd.mm.yyyy» | «—», просрочен ли). Просроченное
    незавершённое подсвечивается — иначе дата в таблице ничем не отличается
    от любой другой даты."""
    if not due:
        return "—", False
    try:
        d = date.fromisoformat(str(due)[:10])
    except ValueError:
        return "—", False
    return d.strftime("%d.%m.%Y"), status != "finalizat" and d < today


def done_view(it: dict) -> str:
    """Дата закрытия позиции (финал или отказ) в поясе клиники; пусто у
    открытой и у записи без даты."""
    da = it.get("done_at")
    if it["status"] in db.PLAN_CLOSED and hasattr(da, "astimezone"):
        return da.astimezone(eng.TZ).strftime("%d.%m.%Y")
    return ""


# ---------- визиты ----------

def visits_view(visits: list, now: datetime) -> dict:
    """Следующий (ближайший живой в будущем), последний (прошлый, не
    отменённый), живые (все, кроме отменённых) и число отменённых."""
    future = [v for v in visits if v["status"] in LIVE_STATUSES and v["starts_at"] > now]
    past = [v for v in visits if v["starts_at"] <= now and v["status"] != "cancelled"]
    live = [v for v in visits if v["status"] != "cancelled"]
    return {
        "next": min(future, key=lambda v: v["starts_at"]) if future else None,
        "last": max(past, key=lambda v: v["starts_at"]) if past else None,
        "live": live, "canc": len(visits) - len(live),
    }


def days_ago(lastv: dict | None, now: datetime) -> int | None:
    if not lastv:
        return None
    return (now.date() - lastv["starts_at"].astimezone(eng.TZ).date()).days


def consult_kind(v: dict, rec: dict | None, now: datetime) -> str:
    """Дневник приёма у строки истории: «rec» — заполнен (диагноз и ссылка),
    «invite» — состоявшийся пустой (приглашение заполнить), «» — будущие не
    зовём: писать «лечение» вперёд — ошибка данных."""
    if rec:
        return "rec"
    if (v["status"] in ("done", "arrived", "waiting")
            or (v["status"] == "confirmed" and v["starts_at"] <= now)):
        return "invite"
    return ""


def rec_diag(rec: dict | None) -> str:
    """Чем подписать ссылку на дневник: диагноз, иначе лечение, иначе жалобы."""
    if not rec:
        return ""
    return (rec["diagnostic"] or rec["tratament"] or rec["acuze"] or "").strip()


# ---------- документы ----------

def doc_view(mime: str | None) -> str:
    """Чем открывать файл: свой просмотрщик (растр, PDF) или программа
    Windows; всё чужое — «ext», и клик уводит в скачивание/startfile."""
    m = mime or ""
    return "img" if m in INLINE_MIME else "pdf" if m in PDF_MIME else "ext"


def doc_size(size: int) -> str:
    kb = (size or 0) // 1024
    return f"{kb} KB" if kb < 1024 else f"{kb / 1024:.1f} MB"


# ---------- анамнез ----------

def anamneza_view(anam: dict | None) -> dict:
    """Что фиша показывает над свёрнутым опросником.

    ⚠️ Свободный текст — ТОЖЕ риск, и чаще всего именно там аллергия и
    реакция на анестезию. Считать риски по одним галочкам значит показать
    «fără riscuri» над записанной пенициллиновой аллергией. `state`:
    none — не собирали, ok — собран без рисков, risk — есть что запомнить."""
    flags = set((anam.get("flags") or "").split(",")) if anam else set()
    marked = [v for k, v in panam.FLAGS["ro"].items() if k in flags]
    free = [(lab, (anam.get(k) or "").strip()) for k, lab, _ph in panam.TEXTS
            if anam and (anam.get(k) or "").strip()]
    n_risk = len(marked) + len(free)
    when = (anam.get("updated_at") or anam.get("created_at")) if anam else None
    return {
        "filled": bool(anam), "flags": flags, "marked": marked, "free": free,
        "n_risk": n_risk,
        "state": "none" if not anam else ("risk" if n_risk else "ok"),
        "when": when, "author": (anam.get("author") or "") if anam else "",
    }


# ---------- шапка, деньги, летопись, запись ----------

def implants(tmap: dict) -> int:
    return sum(1 for t in tmap.values() if t["state"] == "implant")


def debt_of(fin: dict) -> int:
    """Долг = завершённые позиции плана с ценой − платежи; минус — аванс.
    Долг видит и рецепция — ей его и взыскивать; сводные суммы по клинике
    остаются за директором (PERM_MONEY в статистике)."""
    return fin["charged"] - fin["paid"]


def sold_view(fin: dict) -> tuple[str, int] | None:
    """Плашка сальдо: («bad», долг) / («plus», аванс) / («ok», 0) при
    рассчитавшемся с начислениями / None, когда начислений не было."""
    debt = debt_of(fin)
    if debt > 0:
        return "bad", debt
    if debt < 0:
        return "plus", -debt
    if fin["charged"]:
        return "ok", 0
    return None


def pills(p: dict, alerts: list, debt: int, tmap: dict) -> list[dict]:
    """Бейджи шапки «кто перед врачом, одним взглядом» — из УЖЕ имеющихся
    данных: архив/активен, первые три предупреждения, страховка, долг или
    аванс, импланты. Текст сырой — экранирует тот, кто рисует."""
    out = []
    if p.get("archived"):
        out.append({"tone": "grey", "icon": "box", "text": "Arhivat"})
    else:
        out.append({"tone": "green", "icon": "check", "text": "Pacient activ"})
    for a in alerts[:3]:
        out.append({"tone": ALERT_TONE.get(a["kind"], "grey"),
                    "icon": ALERT_ICON.get(a["kind"], "info"),
                    "text": a["text"][:38]})
    if p.get("insurance"):
        out.append({"tone": "green", "icon": "shield", "text": p["insurance"][:28]})
    if debt > 0:
        out.append({"tone": "red", "icon": "money", "text": f"De achitat: {money(debt)} MDL"})
    elif debt < 0:
        out.append({"tone": "green", "icon": "money", "text": f"Avans: {money(-debt)} MDL"})
    n_impl = implants(tmap)
    if n_impl:
        out.append({"tone": "purple", "icon": "set",
                    "text": f"{n_impl} implant{'e' if n_impl > 1 else ''}"})
    return out


def who(actor: str | None) -> str:
    """Подпись события: с ролями это ИМЯ вошедшего; «recepție» осталось у
    событий, записанных до учёток, и у фоновых задач, где человека нет."""
    return "bot" if actor == "bot" else (actor or "recepție")


def appoint_view(p: dict) -> dict:
    """Окно записи для ЭТОГО пациента: услуга решает, кто из врачей её
    выполняет; медик курант из фиши выбран заранее."""
    return {
        "svc_docs": {k: [dk for dk, _n in eng.allowed_doc_items(k)] for k in eng.SERVICES},
        "prim": next((dk for dk, n in eng.ACTIVE_DOCTORS.items()
                      if n == (p.get("primary_doctor") or "")), ""),
    }
