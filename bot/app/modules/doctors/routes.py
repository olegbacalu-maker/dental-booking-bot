"""Врачи: список, карточка врача, услуги, фото, цвета, перепривязка записей.

Каталог врачей живёт не в базе, а в `clinic.json` — в записях лежит только
`doctor_id` и снимок имени на момент брони. Поэтому здешние правки идут через
`eng.save_config`, а не через SQL, и применяются на лету: бот начинает
предлагать нового врача сразу после сохранения.

Правило то же: сюда можно смотреть в `core`, `db` и `engine`, и нельзя — в
`main.py`.
"""
from __future__ import annotations

import html
import re
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Form, Request, UploadFile
from fastapi.responses import (FileResponse, HTMLResponse, RedirectResponse,
                               Response)

from ... import db
from ... import engine as eng
from ...core.auth import PERM_DOCTORS, _guard, require
from ...core.layout import _DOW_FULL, _DOW_ORDER, react_shell, shell_model
from ...core.visits import _doctors_dir, _photo_path

router = APIRouter()


@router.post("/admin/relink")
async def admin_relink(request: Request, old_name: str = Form(...),
                       dk: str = Form(...), back: str = Form("/admin")):
    """Переприкрепить сиротские записи (старое имя, без doctor_id) к врачу."""
    if (deny := require(request, PERM_DOCTORS)) is not None:
        return deny
    if dk not in eng.DOCTORS:
        return RedirectResponse("/admin", status_code=303)
    n = await db.relink_doctor(old_name.strip()[:80], dk)
    target = back if back.startswith("/admin") else "/admin"
    sep = "&" if "?" in target else "?"
    return RedirectResponse(f"{target}{sep}msg={'ok_set' if n >= 0 else 'bad'}",
                            status_code=303)


MAX_PHOTO_MB = 5


_DOC_STATE_HINT = {
    "activ": "apare în programări și în formulare",
    "concediu": "temporar nu primește; programările existente rămân",
    "arhivat": "a plecat din clinică; istoricul rămâne",
}


_PHOTO_MIME = {".jpg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}


def _sniff_photo(head: bytes) -> tuple[str, str] | None:
    """(расширение, mime) по СОДЕРЖИМОМУ файла — имени и content-type не верим."""
    if head.startswith(b"\xff\xd8\xff"):
        return ".jpg", "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png", "image/png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return ".webp", "image/webp"
    return None


def _doc_rows(dk: str, name: str, rows: list) -> list:
    """Записи врача среди строк периода: по стабильному id, легаси — по имени."""
    return [r for r in rows
            if r.get("doctor_id") == dk or (not r.get("doctor_id") and r["doctor"] == name)]


def _doc_stats(dk: str, name: str, rows: list, days: list) -> dict:
    live = [r for r in _doc_rows(dk, name, rows)
            if r["source"] != "note" and r["status"] != "cancelled"]
    cap = sum(eng.work_minutes(dk, day) for day in days)
    busy = sum(int(r.get("duration_min") or 60) for r in live)
    return {"n": len(live), "pct": round(100 * busy / cap) if cap else 0,
            "noshow": sum(1 for r in live if r["status"] == "noshow")}


def _save_cfg(**changes) -> str | None:
    cfg = dict(eng.CONFIG)
    cfg.update(changes)
    return eng.save_config(cfg)


def _doctor_entry(prev: dict, **fields) -> dict:
    """Запись врача для конфига: правим поля, ничего чужого не теряем."""
    entry = dict(prev)
    entry.update(fields)
    for k in ("spec", "room", "phone", "email", "color", "photo"):
        if not entry.get(k):
            entry.pop(k, None)
    for k in ("work_from", "work_to"):
        if entry.get(k) is None:
            entry.pop(k, None)
    entry["status"] = eng.doctor_state(entry)
    # active остаётся в файле ради совместимости: старая версия программы
    # (откат) читает только его и поймёт «в отпуске / в архиве» как выключенного
    entry["active"] = entry["status"] == "activ"
    return entry


def _patch_doctor(dk: str, **fields) -> str | None:
    docs = [(_doctor_entry(d, **fields) if d["id"] == dk else d)
            for d in eng.CONFIG["doctors"]]
    return _save_cfg(doctors=docs)


# Услуги, которые остаются (или уже остались) без единого активного врача:
# бот тогда честно скажет «недоступна» (v1.8.1), но админ должен это ВИДЕТЬ.
# ⚠️ v1.9.1: раньше предупреждение показывалось только пока врач активен —
# то есть исчезало ровно в тот момент, когда становилось правдой.
_ORPHAN_SOON = ("Atenție: dacă acest medic nu mai e activ, serviciile {svc} "
                "rămân fără medic și nu vor mai putea fi programate.")
_ORPHAN_NOW = ("Cât timp acest medic nu e activ, serviciile {svc} nu au niciun "
               "medic activ și nu pot fi programate. Bifați-le la alt medic sau "
               "readuceți-l în activitate.")


def _orphan_services(dk: str, *, without: bool) -> list[str]:
    out = []
    for sv in eng.SERVICES.values():
        docs = sv.get("docs") or []
        if not docs or (without and dk not in docs):
            continue
        others = [k for k in docs
                  if (k != dk if without else True)
                  and eng.DOCTOR_META.get(k, {}).get("active")]
        if not others:
            out.append(sv["ro"])
    return out


def _orphan_warning(dk: str, st: str) -> tuple[str, list[str]]:
    """(шаблон с {svc}, имена услуг) — или ("", []) когда предупреждать не о
    чем. JSON API отдаёт имена сплошным текстом; фраза одна."""
    if st == "activ":
        names = _orphan_services(dk, without=True)
        return (_ORPHAN_SOON, names) if names else ("", [])
    names = _orphan_services(dk, without=False)
    return (_ORPHAN_NOW, names) if names else ("", [])


def _week_cells(dk: str, mine_wk: list, today) -> list[dict]:
    """Ближайшие 7 дней врача: сколько приёмов и открыт ли день (заметки не в
    счёт — это не приёмы). Отдаёт JSON API фиши."""
    out = []
    for i in range(7):
        day = today + timedelta(days=i)
        cnt = sum(1 for r in mine_wk
                  if r["starts_at"].astimezone(eng.TZ).date() == day
                  and r["source"] != "note" and r["status"] != "cancelled")
        out.append({"date": day.isoformat(),
                    "label": "Azi" if i == 0 else _DOW_FULL[_DOW_ORDER[day.weekday()]][:2],
                    "dm": f"{day.day:02d}.{day.month:02d}",
                    "count": cnt, "open": bool(eng.work_minutes(dk, day))})
    return out


def _service_rows(dk: str) -> list[dict]:
    """Услуги для галочек фиши: отмечена ли у этого врача и у скольких она."""
    out = []
    for sid, sv in eng.SERVICES.items():
        docs = sv.get("docs") or []
        out.append({"id": sid, "name": sv["ro"], "checked": (not docs) or dk in docs,
                    "note": ("toți medicii" if not docs
                             else "1 medic" if len(docs) == 1 else f"{len(docs)} medici")})
    return out


def _same_color() -> bool:
    """⚠️ Старая таблица в Setări подставляла КАЖДОМУ врачу один и тот же цвет
    по умолчанию — на таком конфиге карточки в расписании неразличимы."""
    set_colors = {(d.get("color") or "").lower() for d in eng.CONFIG["doctors"]}
    return (len(eng.CONFIG["doctors"]) > 1 and len(set_colors) == 1
            and "" not in set_colors)


@router.get("/admin/medici", response_class=HTMLResponse)
async def admin_medici(request: Request, msg: str = ""):
    if (deny := require(request, PERM_DOCTORS)) is not None:
        return deny
    # ⭐ B1, ПЕРВАЯ ВЕРТИКАЛЬ: оболочку рисует React. Сервер печатает только
    # голову и узел с моделью — ни сайдбара, ни шапки, ни заголовка, ни
    # баннеров, иначе на экране было бы по две штуки всего. Старая страница
    # списка снята 12.10 (docs/dentpilot-2/legacy-removal.md).
    return react_shell("doctors_list", request.url.path,
                       # подзаголовок печатает экран (08.10): «N activi · 30 de zile»
                       shell_model("med", "", msg=msg))


def _add_doctor(name: str, spec: str) -> tuple[str, str]:
    """Новый врач в профиле: (код ответа, id), id пустой при отказе.
    Зовёт JSON API (`api.py`)."""
    nm = name.strip()[:60]
    if not nm:
        return "bad_med", ""
    # тёзки слили бы истории (легаси-строки матчатся по имени) — запрещаем
    if any(d["name"].casefold() == nm.casefold() for d in eng.CONFIG["doctors"]):
        return "dup_med", ""
    seq = dict(eng.CONFIG.get("seq") or {})
    n = int(seq.get("doctor", 0))
    for d in eng.CONFIG.get("doctors", []):
        mnum = re.fullmatch(r"d(\d+)", str(d.get("id", "")))
        if mnum:
            n = max(n, int(mnum.group(1)))
    n += 1                      # id не переиспользуются (урок 08-01)
    seq["doctor"] = n
    did = f"d{n}"
    entry = _doctor_entry({"id": did, "name": nm}, spec=spec.strip()[:60], status="activ")
    if _save_cfg(doctors=list(eng.CONFIG["doctors"]) + [entry], seq=seq):
        return "save_err", ""
    return "new_med", did


def _reset_colors() -> str:
    """Сброс цветов врачей на автоматические (различимые по палитре)."""
    docs = [_doctor_entry(d, color="") for d in eng.CONFIG["doctors"]]
    return "save_err" if _save_cfg(doctors=docs) else "ok_med"


@router.get("/admin/doctor-card/{dk}", response_class=HTMLResponse)
async def admin_doctor_card(request: Request, dk: str, msg: str = ""):
    if (deny := require(request, PERM_DOCTORS)) is not None:
        return deny
    if dk not in eng.DOCTORS:
        return RedirectResponse("/admin/medici", status_code=303)
    # ⭐ B1: оболочку рисует React, сервер печатает голову и модель.
    return react_shell("doctor_card", request.url.path,
                       shell_model("med",
                                   f"fișa medicului · {html.escape(eng.DOCTORS[dk])}",
                                   msg=msg),
                       {"dk": dk})


async def _save_doctor(dk: str, *, name: str, spec: str = "", room: str = "",
                       phone: str = "", email: str = "", color: str = "",
                       auto_color: bool = False, work_from: str = "",
                       work_to: str = "", status: str = "activ") -> str:
    """Правила фиши врача (зовёт JSON API). Возвращает код ответа:
    bad_med / dup_med / last_med / arch_busy / save_err / ok_med. Часы приходят
    строками («» = как у клиники)."""
    nm = name.strip()[:60]
    if not nm:
        return "bad_med"
    if any(d["id"] != dk and d["name"].casefold() == nm.casefold()
           for d in eng.CONFIG["doctors"]):
        return "dup_med"
    st = status if status in eng.DOCTOR_STATES else "activ"
    if st != "activ" and not any(d["id"] != dk and eng.doctor_state(d) == "activ"
                                 for d in eng.CONFIG["doctors"]):
        return "last_med"
    if st == "arhivat":
        # архив = «его больше нет в расписании»; с живыми будущими бронями это
        # тихо оставило бы пациентов без врача — только «в отпуске»
        if await db.doctor_future_count(dk, eng.DOCTORS[dk], datetime.now(eng.TZ)):
            return "arch_busy"
    wf = int(work_from) if work_from.isdecimal() and 0 <= int(work_from) <= 23 else None
    wt = int(work_to) if work_to.isdecimal() and 1 <= int(work_to) <= 24 else None
    if wf is not None and wt is not None and wf >= wt:
        return "bad_med"
    col = "" if auto_color else color.strip()[:16]
    if col and not re.fullmatch(r"#[0-9a-fA-F]{6}", col):
        return "bad_med"
    err = _patch_doctor(dk, name=nm, spec=spec.strip()[:60], room=room.strip()[:30],
                        phone=phone.strip()[:30], email=email.strip()[:80],
                        color=col, work_from=wf, work_to=wt, status=st)
    return "save_err" if err else "ok_med"


def _set_services(dk: str, picked: set) -> str:
    """Галочки услуг врача (зовёт JSON API). Возвращает
    код ответа: svc_empty / save_err / ok_svc_med."""
    all_ids = [d["id"] for d in eng.CONFIG["doctors"]]
    services = []
    for s in eng.CONFIG["services"]:
        sid = s["id"]
        docs = list(s.get("docs") or [])
        entry = dict(s)
        if sid in picked:
            if docs and dk not in docs:
                docs.append(dk)
            # пустой docs = «все медики», этот тоже входит — менять нечего
        else:
            # ⭐ Гейт ниже стережёт только те услуги, которых касается ЭТА
            # отправка. Экран шлёт лишь отмеченные галочки, поэтому в эту ветку
            # приходит и услуга, где `dk` не значился никогда: её список не
            # меняется ни на элемент, а отказ по ней отбивал бы всё сохранение. Так
            # чужой отпуск (услуга осталась за одним отпускником) запирал
            # сохранение услуг у ВСЕХ остальных врачей до его возвращения.
            mine = not docs or dk in docs
            # «все врачи» → материализуем список, иначе бифу не снять.
            # Список берём ПОЛНЫЙ (с отпускниками): вернётся из отпуска —
            # снова будет выполнять услугу, забывать это нельзя.
            docs = ([k for k in all_ids if k != dk] if not docs
                    else [k for k in docs if k != dk])
            # ⚠️ v1.9.1: проверять НЕПУСТОТУ мало. Список из одних отпускников/
            # архивных непуст, но allowed_doc_items() пересекает его с
            # ACTIVE_DOCTORS → пусто → услуга ПРОПАДАЕТ из меню бота, а админ
            # видит зелёный баннер. Гейт считает только активных.
            if mine and not any(eng.DOCTOR_META.get(k, {}).get("active")
                                for k in docs):
                return "svc_empty"
        if docs:
            entry["docs"] = docs
        else:
            entry.pop("docs", None)
        services.append(entry)
    return "save_err" if _save_cfg(services=services) else "ok_svc_med"


async def _read_upload(file: UploadFile) -> bytes | None:
    """Файл целиком, но не больше MAX_PHOTO_MB; None — слишком большой."""
    cap, buf = MAX_PHOTO_MB * 1024 * 1024, bytearray()
    try:
        while chunk := await file.read(1024 * 256):
            buf += chunk
            if len(buf) > cap:
                return None
    finally:
        await file.close()
    return bytes(buf)


def _store_photo(dk: str, data: bytes) -> str:
    """Положить фото врача рядом с программой и прописать в профиль. Код
    ответа: bad_photo / save_err / ok_photo. Зовёт JSON API."""
    kind = _sniff_photo(data[:16])
    if not data or not kind:
        return "bad_photo"
    old = _photo_path(dk)
    stored = _doctors_dir() / f"{dk}_{secrets.token_hex(6)}{kind[0]}"
    try:
        stored.write_bytes(data)
    except OSError:
        stored.unlink(missing_ok=True)
        return "bad_photo"
    if _patch_doctor(dk, photo=stored.name):
        stored.unlink(missing_ok=True)      # конфиг не записался — файл не нужен
        return "save_err"
    if old and old != stored:
        old.unlink(missing_ok=True)
    return "ok_photo"


def _delete_photo(dk: str) -> str:
    old = _photo_path(dk)
    if _patch_doctor(dk, photo=""):
        return "save_err"                   # конфиг не записался — файл храним
    if old:
        old.unlink(missing_ok=True)
    return "ok_med"


@router.get("/admin/doctor-photo/{dk}")
async def doctor_photo_get(request: Request, dk: str, v: str = ""):
    # НАМЕРЕННО _guard, а не PERM_DOCTORS: фото тянет журнал (аватары в сетке
    # и в модалке визита) — закрыть правом значило бы отнять аватары у врача
    if (deny := _guard(request)) is not None:
        return deny
    p = _photo_path(dk)
    if not p:
        return Response(status_code=404)
    return FileResponse(p, media_type=_PHOTO_MIME.get(p.suffix.lower(), "image/jpeg"))
