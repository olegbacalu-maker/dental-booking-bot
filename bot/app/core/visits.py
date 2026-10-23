"""Как выглядит ВИЗИТ на экране — общее для нескольких разделов.

Кнопки исхода по состоянию, строки «Lista zilei», карточки визитов дня, цвет
и фото врача, разбор даты из адреса — данными для JSON API (разметки старых
страниц здесь больше нет: снята 13.10 вместе со старым журналом). Всё это
нужно и журналу дня, и карточке врача, и статистике: положить его внутрь
одного модуля значило бы, что соседний модуль импортирует соседа — а это
ровно та паутина, ради ухода от которой всё и затевалось.

Граница простая: здесь то, что описывает визит как таковой. Каркас страницы —
в layout.py, доступ — в auth.py, пути к данным — в storage.py.
"""
from __future__ import annotations

import pathlib
import urllib.parse
from datetime import date, datetime

from .. import db
from .. import engine as eng
from .auth import request_user, schedule_scope
from .layout import _age, status_view
from .storage import _data_dir


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return datetime.now(eng.TZ).date()


def of_doctor(r: dict, dk: str) -> bool:
    """Строка дня принадлежит врачу `dk`: по `doctor_id`, а у легаси-строки
    без него — по снимку имени. ⛔ Одно правило на всех, кто режет день по
    врачу (сетка врача, его страница, экран кресла, журнал врача по праву,
    списки стойки): третья копия условия однажды забыла бы легаси-ветку, и
    старая запись пропала бы с одного экрана, оставаясь на другом. Жила в
    `schedule/routes` до 22.10 — переехала сюда, когда понадобилась и
    `desk.py`, который `routes` импортирует сам."""
    return (r.get("doctor_id") == dk
            or (not r.get("doctor_id") and r["doctor"] == eng.DOCTORS.get(dk)))


def my_scope() -> str | None:
    """Чей журнал видит вошедший (22.10, права врача) — `auth.schedule_scope`
    по живому справочнику врачей: None — всех, ключ — только этого врача,
    "" — ничей (учётка врача без привязки). Один вызов на журнал, окно записи
    фиши и кресло: второй вычислитель разошёлся бы с первым молча."""
    return schedule_scope(request_user(), eng.DOCTORS)


def mine(r: dict, scope: str | None) -> bool:
    """Строка дня — из журнала вошедшего: все при полном праве, свои у
    врача (`of_doctor`, с его легаси-строками), ничьи у учётки без врача.
    ⛔ Пустой `scope` — это «никого», а не «всех»: перепутай их — и учётка без
    привязки увидела бы весь журнал."""
    return scope is None or (scope != "" and of_doctor(r, scope))


# Кнопки исхода — ПО СОСТОЯНИЮ записи, а не один набор на все живые статусы.
# Пациенту, который уже в кресле, «A sosit» повторяет сделанное, а «Nu a venit»
# рядом с ним предлагает записать неправду.
# ⭐ Закрытая запись получает ОДНУ кнопку — возврат в «programată». До 08-12
# промах по «Finalizat» был из журнала неисправим совсем: столбец «Acțiuni»
# просто пустел, а маршрут `to=confirmed` при этом существовал и работал —
# нажать его было нечем.
# ⛔ Статусы перечислены ПОИМЁННО. Правило «всё, что не живое, — переоткрыть»
# молча раздало бы свои кнопки новому статусу, и он получил бы чужое поведение
# без единой строки о себе (тот же урок, что PLAN_ACTIVE в db.py).
_REOPEN = ("confirmed", "b-reopen", "Redeschide")
# 08-13: конвейер приёма честный — «A venit» (waiting, пациент в приёмной) →
# «În cabinet» (arrived). Второй шаг НЕОБЯЗАТЕЛЕН намеренно: «Finalizat»
# доступен и из waiting, и прямиком из confirmed — иначе регистратура
# прокликивала бы статусы ради галочки, и «în cabinet» стал бы ритуалом, а не
# фактом. Кнопка зовётся словом статуса, который она ставит (STATUS_LABEL) —
# бывшая «A sosit» ставила arrived и потому теперь называется «În cabinet».
# ⚠️ «Nu a venit» у waiting НЕ предлагается: пациент пришёл, кнопка рядом
# предлагала бы записать неправду (тот же принцип, что у arrived).
_ACT_BUTTONS = {
    "confirmed": (("waiting", "b-waiting", "A venit"),
                  ("arrived", "b-arrived", "În cabinet"),
                  ("done", "b-done", "Finalizat"),
                  ("noshow", "b-noshow", "Nu a venit"),
                  ("cancelled", "b-cancel", "Anulează")),
    "waiting": (("arrived", "b-arrived", "În cabinet"),
                ("done", "b-done", "Finalizat"),
                ("cancelled", "b-cancel", "Anulează")),
    "arrived": (("done", "b-done", "Finalizat"),
                ("cancelled", "b-cancel", "Anulează")),
    "done": (_REOPEN,), "noshow": (_REOPEN,), "cancelled": (_REOPEN,),
}
# заметка — не визит: прихода и исхода у неё нет, есть «убрать» и «вернуть»
# (блокировка слота снимается и ставится обратно тем же статусом)
_NOTE_BUTTONS = {
    "confirmed": (("cancelled", "b-cancel", "Șterge"),),
    "cancelled": (("confirmed", "b-reopen", "Restabilește"),),
}
# возврат спрашивают подтверждением: это отмена уже записанного факта, а не
# следующий шаг приёма (так же ведёт себя «Redeschide» в плане лечения)
_ASK_APPT = "Redeschideți programarea (înapoi la «programată»)?"
_ASK_NOTE = "Restabiliți notița?"
# 03.10, слово Олега: «Anulează сразу удаляет его из списка, нужно сначала
# спросить». Отмена одним кликом убирает визит из сетки и повестки, а пункт
# стоит в меню правой кнопки вплотную к соседним. Вернуть можно («Redeschide»
# в «Lista zilei»), но в момент промаха этого никто не знает — вопрос это и
# говорит. ⚠️ Только у визита: «Șterge» у заметки стойки не спрашивает.
_ASK_CANCEL = ("Anulați programarea? Ea dispare din grila zilei; "
               "o puteți redeschide din «Lista zilei».")


def status_actions(status: str, is_note: bool = False) -> list[dict]:
    """Кнопки исхода для этого состояния — ОДНА матрица на всех.

    «Lista zilei», карточка визита, меню правой кнопки, повестка и экран у
    кресла спрашивают ЭТУ матрицу (через `all_status_actions` в ответе API).
    Это одно правило во многих видах, и расхождение молчит: закрытая запись
    теряла бы кнопку возврата в одном месте и сохраняла в другом, а увидеть
    это можно, только открыв оба.
    """
    src = (_NOTE_BUTTONS if is_note else _ACT_BUTTONS).get(status, ())
    ask = _ASK_NOTE if is_note else _ASK_APPT
    return [{"to": to, "cls": cls, "label": label,
             "confirm": (ask if cls == "b-reopen"
                         else _ASK_CANCEL if cls == "b-cancel" and not is_note else "")}
            for to, cls, label in src]


def all_status_actions(is_note: bool = False) -> dict:
    """Вся матрица разом — {состояние: кнопки}. Её отдаёт JSON API: клиент
    спрашивает по статусу карточки (`actions[card.status]`).

    ⚠️ Состояния перечисляет САМА матрица, а не список рядом: список пришлось
    бы дополнять при седьмом статусе, и забытая строка молча оставила бы
    новое состояние без кнопок.
    """
    return {st: status_actions(st, is_note)
            for st in (_NOTE_BUTTONS if is_note else _ACT_BUTTONS)}


def list_rows(rows: list) -> list[dict]:
    """«Lista zilei» данными — строка за строкой, в порядке страницы.

    ⚠️ Это НЕ сетка, и три отличия несущие. Список показывает ОТМЕНЁННЫЕ
    записи (в сетке их нет — там они только мешали бы) и заметки стойки; и
    только здесь заметку можно убрать и вернуть, потому что карточки визита у
    неё нет по замыслу.
    ⛔ Один текст живёт в ЧЕТЫРЁХ длинах — 80 в списке, 60 в карточке сетки,
    полный в `cards` и полный в базе, — и с 19.09 обрезок больше не носит
    имени полного значения: правят `comment`, печатают `comment_cut`. До этого
    оба звались одинаково в разных словарях, оба были `str`, и взять не тот
    было нечем помешать (прайор 08-16).
    ⚠️ Врач — СНИМОК имени из самой строки, а не колонка сетки: у записи без
    `doctor_id` другого адреса нет, и переименование врача не двигает историю.
    """
    out = []
    for r in rows:
        is_note = r["source"] == "note"
        st = r["status"]
        # вид — с учётом звонка-подтверждения (03.10): «programată» до звонка,
        # «confirmată» после ✓; `status` остаётся кодом — по нему кнопки
        view, word = status_view(st, r.get("call_result"))
        out.append({
            "id": r["id"], "is_note": is_note,
            "time": r["starts_at"].astimezone(eng.TZ).strftime("%H:%M"),
            "name": "" if is_note else (r["name"] or ""),
            "age": None if is_note else _age(r.get("birth_year")),
            "phone": "" if is_note else (r["phone"] or ""),
            "service": r["service"] or "",
            "urgent": not is_note and r["service"] in eng.URGENT_LABELS,
            # полное значение — источник правки, обрезок — то, что
            # печатает строка списка; имена разные намеренно
            "comment": r["comment"] or "",
            "comment_cut": (r["comment"] or "")[:80],
            "doctor": r["doctor"] or "",
            "source": "note" if is_note else r["source"],
            "source_label": "notiță" if is_note else (
                "bot" if r["source"] == "bot" else "manual"),
            "status": st, "status_view": view, "status_label": word,
            # «напомнили» — из ОБОИХ каналов: флаг Telegram и строка SMS
            # (`sms_sent` из day_appointments, S5); `reminded_sms` — чем именно,
            # чтобы подсказка колокольчика назвала канал
            "reminded": bool(r.get("reminded_day")) or bool(r.get("sms_sent")),
            "reminded_sms": bool(r.get("sms_sent")),
            "rec": bool(r.get("has_rec")),
        })
    return out


def call_fields(r) -> dict:
    """Отметка звонка-подтверждения на карточке визита (12.10, слово Олега:
    «вчера не позвонил — хочу подтвердить сегодня»).

    `call` — отметка как есть (`appt_calls`: ok / noanswer / пусто); `callable` —
    можно ли её ставить: запись «programată» (код `confirmed`) с пациентом, на
    сегодня или позже по часам клиники. ⛔ Одно правило на карточку дня, блок
    канвы панели и меню правой кнопки — все берут ЭТИ поля; дату в браузере не
    считает никто. Сервер отметку принимает у любой записи — граница здесь.
    ⚠️ `callable` меняется в полночь: живое тело дня меняется тогда же и так."""
    st = r["starts_at"].astimezone(eng.TZ)
    return {"call": r.get("call_result") or "",
            "callable": (r["status"] == "confirmed" and bool(r.get("patient_id"))
                         and st.date() >= datetime.now(eng.TZ).date())}


def _visit_refusal(r) -> str:
    """Можно ли менять процедуру ЭТОГО визита вообще, без оглядки на услугу:
    «» — можно, иначе код отказа из `MSG_BANNER`. Половина `service_refusal`,
    которую несёт и блок живого канала (`service_fields`): одно правило, не
    два.
    ⚠️ Врач — по `doctor_id`, и он обязан быть АКТИВНЫМ: выключенному журнал
    не пишет (`bad_off`, как у записи и переноса). У легаси-строки без
    `doctor_id` смены нет — её, как и перенос, сперва перевязывают к врачу
    (relink на канве).
    Закрытый визит не меняется, как и не переносится: смена процедуры — это
    правка ЗАПИСИ, а у состоявшегося приёма процедура — уже факт (дневник,
    043/e, статистика)."""
    if r["source"] == "note":
        return "bad"
    if r["status"] not in db.ACTIVE_STATUSES:
        return "svc_closed"
    if (r.get("doctor_id") or "") not in eng.ACTIVE_DOCTORS:
        return "bad_off"
    return ""


def service_refusal(r, sid: str) -> str:
    """Можно ли сменить процедуру визита `r` на услугу `sid` (22.10, Олег:
    «сменить процедуру, не удаляя запись»): «» — можно, иначе код отказа из
    `MSG_BANNER`.

    ⛔ Одно правило на окно и на сервер: список окна (`service_options`) и
    маршрут смены (`routes._set_service`) спрашивают ЭТУ функцию. Своё условие
    в браузере разошлось бы молча — окно предлагало бы услугу, которую сервер
    отбивает, или прятало бы законную.
    ⚠️ Здесь только то, что не зависит от часов: влезет ли новая длительность
    в график и не наедет ли на соседа, решает маршрут под `_slot_lock`.
    Врач делает услугу — по `allowed_doc_items` (её `docs`; пусто — все).
    """
    if code := _visit_refusal(r):
        return code
    if sid not in eng.SERVICES:
        return "bad"
    if all(k != r["doctor_id"] for k, _n in eng.allowed_doc_items(sid)):
        return "svc_doc"
    return ""


def service_fields(r) -> dict:
    """Процедура визита на карточке дня и на блоке канвы панели (22.10), как
    `call_fields`: `service_id` — ключ услуги в clinic.json (пусто у
    легаси-строки), `service_edit` — можно ли её менять вообще.
    ⛔ СПИСКА услуг здесь нет и не будет: блок едет в КАЖДОМ конверте живого
    канала, а список у всех визитов одного врача одинаков — 20 услуг на 30
    визитов раздули бы каждый опрос главной. Список окно спрашивает само при
    открытии (`service_options`, `GET …/service`).
    ⚠️ Оба поля — от данных записи и clinic.json, ни «сейчас», ни вошедшего:
    отпечаток канала они не шевелят."""
    return {"service_id": r.get("service_id") or "",
            "service_edit": not _visit_refusal(r)}


def service_options(r) -> list[dict]:
    """На какие услуги можно сменить процедуру визита — ключ и подпись, в
    порядке clinic.json; пусто — выбора нет. Тем же `service_refusal`, по
    которому маршрут смены отказывает."""
    return [{"id": k, "label": v["ro"]} for k, v in eng.SERVICES.items()
            if not service_refusal(r, k)]


def _collect_cards(rows: list) -> dict:
    """Данные карточек визита (диалог по клику) — по ВСЕМ записям дня (вкл.
    отменённые: их открывают из «Lista zilei», чтобы вернуть), кроме заметок."""
    cards: dict = {}
    for r in rows:
        if r["source"] == "note":
            continue
        cards[r["id"]] = {
            "name": r["name"] or "—", "phone": r["phone"] or "",
            "service": r["service"], "doctor": r["doctor"],
            "time": r["starts_at"].astimezone(eng.TZ).strftime("%H:%M"),
            "comment": r["comment"] or "",
            "age": _age(r["birth_year"]),
            # состояние, а не «можно ли действовать»: набор кнопок в диалоге
            # зависит от статуса так же, как в «Lista zilei», и одним «да/нет»
            # его больше не выразить
            # ⚠️ Имя `status`, а не `st` (C26.5.3-a): ровно так это
            # поле зовётся в блоке сетки, и рядом с ним лежит
            # `status_label`. Два имени одного состояния в двух
            # словарях — это 08-12 и 08-16, и в контракте, который
            # пишется ради ОДНОГО канонического состояния, их быть
            # не может.
            "status": r["status"],
            "pid": r.get("patient_id"),
            # .get: не всякий вызывающий тянет флаг дневника из day_appointments
            "rec": bool(r.get("has_rec")),
            **call_fields(r),
            # процедура и на что её можно сменить (22.10) — тем же правилом,
            # что у блока канвы панели
            **service_fields(r),
        }
    return cards


# --- палитра врачей и цвет записи ПО ТИПУ процедуры (референс v2) ---
# палитра карточек врача (макет 08-03): зелёный / синий / фиолетовый / янтарный —
# первые четыре цвета намеренно максимально различимы, дальше по кругу
_DOC_HUES = ["#10B981", "#3B82F6", "#8B5CF6", "#F59E0B", "#DC2626", "#0891B2",
             "#6366F1", "#DB2777"]


# палитра для явного цвета услуги в Setări (значение → фон/полоса)
SVC_PALETTE = {
    "green": ("var(--green-soft)", "var(--green)"),
    "blue": ("var(--blue-soft)", "var(--blue)"),
    "amber": ("var(--amber-soft)", "var(--amber)"),
    "violet": ("var(--violet-soft)", "var(--violet)"),
    "red": ("var(--red-soft)", "var(--red)"),
    "teal": ("var(--teal-soft)", "var(--teal)"),
}


def _doctors_dir() -> pathlib.Path:
    base = _data_dir() or pathlib.Path("data")
    d = base / "files" / "doctors"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _photo_path(dk: str) -> pathlib.Path | None:
    """Файл фото врача. Имя приходит из clinic.json — а его правят и руками,
    поэтому проверяем, что путь действительно внутри папки фотографий."""
    fn = str(eng.DOCTOR_META.get(dk, {}).get("photo") or "")
    if not fn or fn != pathlib.Path(fn).name:
        return None
    base = _doctors_dir()
    p = base / fn
    try:
        if p.resolve().parent != base.resolve() or not p.is_file():
            return None
    except OSError:
        return None
    return p


def photo_url(dk: str) -> str:
    """Адрес фото врача — один на шапку канвы дня и экраны врачей: `?v=` — имя
    файла, и кэш браузера сбрасывается сам при замене фото.

    ⚠️ Лежит в `core`, потому что спрашивают ДВА модуля — врачи (`/api/doctors`)
    и журнал (модель канвы). Копия формулы в каждом из них разошлась бы молча:
    у одного экрана фото обновилось бы после замены, у другого осталось бы
    старым из кэша, и выглядело бы это как «фото не сохранилось».
    """
    p = _photo_path(dk)
    if not p:
        return ""
    return (f"/admin/doctor-photo/{urllib.parse.quote(dk)}"
            f"?v={urllib.parse.quote(p.name)}")


def _doc_hue(dk: str) -> str:
    meta = eng.DOCTOR_META.get(dk, {})
    if meta.get("color"):
        return meta["color"]
    keys = list(eng.DOCTORS)
    idx = keys.index(dk) if dk in keys else 0
    return _DOC_HUES[idx % len(_DOC_HUES)]

