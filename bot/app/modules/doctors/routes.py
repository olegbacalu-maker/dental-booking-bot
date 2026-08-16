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

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import (FileResponse, HTMLResponse, RedirectResponse,
                               Response)

from ... import db
from ... import engine as eng
from ...core.auth import PERM_DOCTORS, _guard, require
from ...core.layout import (HOUR_MAX, HOUR_MIN, _DOC_STATE_RO,
                            _DOW_FULL, _DOW_ORDER, _doc_hours_text, _ic,
                            msg_banner, _shell)
from ...core.visits import (_avatar, _card_modal, _collect_cards, _doc_hue,
                            _doctors_dir, _list, _photo_path)

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


def _med_redirect(dk: str, msg: str = "") -> RedirectResponse:
    q = f"?msg={msg}" if msg else ""
    return RedirectResponse(f"/admin/doctor-card/{dk}{q}", status_code=303)


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


def _med_card_html(dk: str, name: str, rows: list, days: list) -> str:
    e = html.escape
    meta = eng.DOCTOR_META.get(dk, {})
    st = meta.get("status", "activ")
    s = _doc_stats(dk, name, rows, days)
    bits = [f"{_ic('door')} {e(meta['room'])}" if meta.get("room") else "",
            f"{_ic('phone')} {e(meta['phone'])}" if meta.get("phone") else "",
            f"{_ic('clock')} {e(_doc_hours_text(dk))}"]
    return f"""<a class="medcard{'' if st == 'activ' else ' off'}" href="/admin/doctor-card/{dk}">
  <div class="medhead">{_avatar(dk, name)}
    <div style="min-width:0"><b>{e(name)}</b>
      <small>{e(eng.DOCTOR_SPEC.get(dk, '') or '—')}</small></div>
    <span class="dbadge {st}" style="margin-left:auto">{_DOC_STATE_RO[st]}</span>
  </div>
  <div class="medmeta">{''.join(f'<span>{b}</span>' for b in bits if b)}</div>
  <div class="medstats">
    <div><b>{s['n']}</b><span>programări · 30 zile</span></div>
    <div><b>{s['pct']}%</b><span>ocupare</span></div>
    <div><b>{s['noshow']}</b><span>neprezentări</span></div>
  </div>
</a>"""


@router.get("/admin/medici", response_class=HTMLResponse)
async def admin_medici(request: Request, msg: str = ""):
    if (deny := require(request, PERM_DOCTORS)) is not None:
        return deny
    today = datetime.now(eng.TZ).date()
    d1 = today - timedelta(days=29)
    start = datetime(d1.year, d1.month, d1.day, tzinfo=eng.TZ)
    end = datetime(today.year, today.month, today.day, tzinfo=eng.TZ) + timedelta(days=1)
    rows = await db.day_appointments(start, end)
    days = [d1 + timedelta(days=i) for i in range(30)]

    live, arch = [], []
    for dk, name in eng.DOCTORS.items():
        card = _med_card_html(dk, name, rows, days)
        (arch if eng.DOCTOR_META.get(dk, {}).get("status") == "arhivat" else live).append(card)

    banner = msg_banner(msg)

    # ⚠️ старая таблица в Setări подставляла КАЖДОМУ врачу один и тот же цвет по
    # умолчанию — на таком конфиге карточки в расписании неразличимы. Молча
    # переписывать чужой выбор нельзя, поэтому просто предлагаем сброс.
    set_colors = {(d.get("color") or "").lower() for d in eng.CONFIG["doctors"]}
    same_color = len(eng.CONFIG["doctors"]) > 1 and len(set_colors) == 1 and "" not in set_colors
    color_hint = (
        "<div class='banner err'>Toți medicii au aceeași culoare, deci cardurile lor "
        "din programul zilei nu se disting. "
        "<form method='post' action='/admin/medici/colors' style='display:inline'>"
        "<button style='background:var(--teal);color:#fff;border:none;border-radius:8px;"
        "padding:5px 12px;cursor:pointer;font-size:12.5px;margin-left:8px'>"
        f"{_ic('palette')} Culori automate</button></form></div>") if same_color else ""
    arch_block = (f"<h2>{_ic('box')} Arhivă <small style='font-weight:400;color:var(--text3)'>"
                  f"· medici care nu mai lucrează; istoricul lor rămâne</small></h2>"
                  f"<div class='medgrid'>{''.join(arch)}</div>") if arch else ""
    body = f"""
<div class='nav'><a href='/admin'>{_ic('home')} Panou</a><a href='/admin/settings'>{_ic('set')} Setările clinicii</a></div>
{banner}{color_hint}
<div class='medgrid'>{''.join(live)}</div>
<h2>{_ic('plus')} Medic nou</h2>
<form class='add' method='post' action='/admin/medici/add'>
  <input type='text' name='name' placeholder='Dr. Nume Prenume' required style='width:260px'>
  <input type='text' name='spec' placeholder='Specializare (ex. Terapie)' style='width:220px'>
  <button>+ Adaugă medic</button>
</form>
<p class='hint'>Medicul nu se șterge niciodată: programările lui păstrează legătura cu el.
«În concediu» = pauză temporară, «Arhivat» = a plecat (posibil doar fără programări viitoare).</p>
{arch_block}"""
    return _shell(body, "medicii clinicii · fișă, program, servicii", active="med")


@router.post("/admin/medici/add")
async def admin_medici_add(request: Request, name: str = Form(...), spec: str = Form("")):
    if (deny := require(request, PERM_DOCTORS)) is not None:
        return deny
    nm = name.strip()[:60]
    if not nm:
        return RedirectResponse("/admin/medici?msg=bad_med", status_code=303)
    # тёзки слили бы истории (легаси-строки матчатся по имени) — запрещаем
    if any(d["name"].casefold() == nm.casefold() for d in eng.CONFIG["doctors"]):
        return RedirectResponse("/admin/medici?msg=dup_med", status_code=303)
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
    err = _save_cfg(doctors=list(eng.CONFIG["doctors"]) + [entry], seq=seq)
    if err:
        return RedirectResponse("/admin/medici?msg=save_err", status_code=303)
    return _med_redirect(did, "new_med")


@router.post("/admin/medici/colors")
async def admin_medici_colors(request: Request):
    """Сброс цветов врачей на автоматические (различимые по палитре)."""
    if (deny := require(request, PERM_DOCTORS)) is not None:
        return deny
    docs = [_doctor_entry(d, color="") for d in eng.CONFIG["doctors"]]
    err = _save_cfg(doctors=docs)
    return RedirectResponse(f"/admin/medici?msg={'save_err' if err else 'ok_med'}",
                            status_code=303)


@router.get("/admin/doctor-card/{dk}", response_class=HTMLResponse)
async def admin_doctor_card(request: Request, dk: str, msg: str = ""):
    if (deny := require(request, PERM_DOCTORS)) is not None:
        return deny
    if dk not in eng.DOCTORS:
        return RedirectResponse("/admin/medici", status_code=303)
    e = html.escape
    name = eng.DOCTORS[dk]
    meta = eng.DOCTOR_META.get(dk, {})
    st = meta.get("status", "activ")
    today = datetime.now(eng.TZ).date()

    # один запрос на всё: сегодняшний список + ближайшие 7 дней
    wk_start = datetime(today.year, today.month, today.day, tzinfo=eng.TZ)
    wk_rows = await db.day_appointments(wk_start, wk_start + timedelta(days=7))
    mine_wk = _doc_rows(dk, name, wk_rows)
    today_rows = [r for r in mine_wk if r["starts_at"].astimezone(eng.TZ).date() == today]

    d1 = today - timedelta(days=29)
    m_start = datetime(d1.year, d1.month, d1.day, tzinfo=eng.TZ)
    stat_rows = await db.day_appointments(m_start, wk_start + timedelta(days=1))
    stats = _doc_stats(dk, name, stat_rows, [d1 + timedelta(days=i) for i in range(30)])
    future = await db.doctor_future_count(dk, name, datetime.now(eng.TZ))

    banner = msg_banner(msg)

    # услуги, которые останутся (или уже остались) без единого активного врача:
    # бот тогда честно скажет «недоступна» (v1.8.1), но админ должен это ВИДЕТЬ.
    # ⚠️ v1.9.1: раньше предупреждение показывалось только пока врач активен —
    # то есть исчезало ровно в тот момент, когда становилось правдой.
    def _orphans(*, without: bool) -> list[str]:
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

    warn = ""
    if st == "activ":
        if (soon := _orphans(without=True)):
            warn = (f"<div class='banner err'>Atenție: dacă acest medic nu mai e activ, "
                    f"serviciile <b>{e(', '.join(soon))}</b> rămân fără medic și "
                    f"nu vor mai putea fi programate.</div>")
    elif (now_orphan := _orphans(without=False)):
        warn = (f"<div class='banner err'>Cât timp acest medic nu e activ, serviciile "
                f"<b>{e(', '.join(now_orphan))}</b> nu au niciun medic activ și "
                f"nu pot fi programate. Bifați-le la alt medic sau readuceți-l în "
                f"activitate.</div>")

    def _wh_opts(sel, lo: int = HOUR_MIN, hi: int = HOUR_MAX) -> str:
        out = [f"<option value=''{' selected' if sel is None else ''}>—</option>"]
        for x in range(lo, hi + 1):
            out.append(f"<option value='{x}'{' selected' if sel == x else ''}>{x}:00</option>")
        return "".join(out)

    st_opts = "".join(
        f"<option value='{k}'{' selected' if st == k else ''}>{v} — {_DOC_STATE_HINT[k]}</option>"
        for k, v in _DOC_STATE_RO.items())
    photo_form = f"""
<form class='fform' method='post' action='/admin/doctor-card/{dk}/photo'
      enctype='multipart/form-data' style='margin-top:10px'>
  <div class='filepick'>
    <input type='file' name='file' id='docphoto' accept='image/jpeg,image/png,image/webp'
           required onchange='pickName(this)'>
    <label for='docphoto'>{_ic('clip')} Alege fotografia</label>
    <span class='fname' id='docphoto_n'>niciun fișier ales</span>
  </div>
  <button>{_ic('camera')} Încarcă fotografia</button>
</form>
<p class='hint' style='margin:6px 0 0'>JPEG / PNG / WebP, max {MAX_PHOTO_MB} MB.
Rămâne local, în folderul programului; pacienții nu o văd.</p>"""
    if meta.get("photo"):
        photo_form += (f"<form method='post' action='/admin/doctor-card/{dk}/photo/del' "
                       f"style='margin-top:6px' onsubmit=\"return confirm('Ștergeți fotografia?')\">"
                       f"<button class='rowdel' style='background:none;border:1px solid var(--line);"
                       f"border-radius:8px;padding:4px 10px;cursor:pointer;font-size:12px;"
                       f"color:var(--text2)'>{_ic('trash')} Șterge fotografia</button></form>")

    left = f"""<div class='fcard'>
  <div class='fhead'>{_avatar(dk, name, big=True)}
    <div style='min-width:0'><b>{e(name)}</b>
      <small>{e(eng.DOCTOR_SPEC.get(dk, '') or '—')}</small>
      <span class='dbadge {st}' style='display:inline-block;margin-top:6px'>{_DOC_STATE_RO[st]}</span>
    </div>
  </div>
  {photo_form}
</div>
<div class='fcard'><h3>Date de contact și program</h3>
<form class='fform' method='post' action='/admin/doctor-card/{dk}/save'>
  <input name='name' value="{e(name)}" placeholder='Nume' maxlength='60' required>
  <input name='spec' value="{e(eng.DOCTOR_SPEC.get(dk, ''))}" placeholder='Specializare' maxlength='60'>
  <div class='r2'><input name='room' value="{e(meta.get('room', ''))}" placeholder='Cabinet'>
  <input name='phone' value="{e(meta.get('phone', ''))}" placeholder='Telefon intern'></div>
  <input name='email' value="{e(meta.get('email', ''))}" placeholder='E-mail (opțional)' maxlength='80'>
  <div style='font-size:11.5px;color:var(--text3);margin-top:2px'>Program personal (de la / până la)</div>
  <div class='r2'><select name='work_from'>{_wh_opts(meta.get('work_from'))}</select>
  <select name='work_to'>{_wh_opts(meta.get('work_to'), HOUR_MIN + 1, HOUR_MAX)}</select></div>
  <div style='font-size:11.5px;color:var(--text3);margin-top:2px'>Culoare în calendar</div>
  <div class='r2' style='align-items:center'>
    <input type='color' name='color' value="{e(meta.get('color') or _doc_hue(dk))}"
           style='width:56px;padding:3px;height:var(--h-ctl);flex:0 0 56px'>
    <label style='font-size:12px;color:var(--text2);display:flex;align-items:center;gap:6px'>
      <input type='checkbox' name='auto_color' value='1'
             {'checked' if not meta.get('color') else ''} style='width:auto'> automată</label>
  </div>
  <div style='font-size:11.5px;color:var(--text3);margin-top:2px'>Starea medicului</div>
  <select name='status'>{st_opts}</select>
  <button>{_ic('save')} Salvează</button>
</form>
<p class='hint' style='margin:8px 0 0'>Programul «—» = ca al clinicii. Culoarea se
folosește în calendarul zilei. Arhivarea e posibilă doar fără programări viitoare
(acum: <b>{future}</b>).</p>
</div>"""

    # центр: сегодня + ближайшая неделя (заметки не в счёт — это не приёмы)
    wk_cells = []
    for i in range(7):
        day = today + timedelta(days=i)
        cnt = sum(1 for r in mine_wk
                  if r["starts_at"].astimezone(eng.TZ).date() == day
                  and r["source"] != "note" and r["status"] != "cancelled")
        cap = eng.work_minutes(dk, day)
        lbl = ("Azi" if i == 0 else _DOW_FULL[_DOW_ORDER[day.weekday()]][:2])
        tone = ("var(--teal-soft)" if cnt else "var(--bg)") if cap else "var(--line2)"
        wk_cells.append(
            f"<a href='/admin/doctor/{dk}?date={day.isoformat()}' style='flex:1;min-width:0;"
            f"text-decoration:none;color:inherit;background:{tone};border-radius:10px;"
            f"padding:8px 6px;text-align:center'>"
            f"<div style='font-size:11px;color:var(--text3)'>{lbl} {day.day:02d}.{day.month:02d}</div>"
            f"<div style='font-size:16px;font-weight:600'>{cnt if cap else '—'}</div></a>")
    back = f"/admin/doctor-card/{dk}"
    cards = _collect_cards(today_rows)
    # 9 колонок в узкой средней колонке — таблица скроллится сама, страница нет
    day_list = _list(today_rows, back,
                     title=f"Astăzi, {today.strftime('%d.%m.%Y')}").replace(
        "<table class='list'>", "<div style='overflow-x:auto'><table class='list'>", 1).replace(
        "</table>", "</table></div>", 1).replace(
        "</h2>", f" <small style='font-size:12px;font-weight:400'>"
                 f"<a href='/admin/doctor/{dk}?date={today.isoformat()}'>grila zilei {_ic('out')}</a>"
                 f"</small></h2>", 1)
    center = f"""<div class='fcard'><h3>Următoarele 7 zile <small>· click = ziua completă</small></h3>
<div style='display:flex;gap:6px'>{''.join(wk_cells)}</div></div>
<div class='fcard' style='padding-top:4px'>{day_list}</div>"""

    # справа: услуги галочками + цифры за 30 дней
    svc_lines = []
    for sid, sv in eng.SERVICES.items():
        docs = sv.get("docs") or []
        checked = (not docs) or dk in docs
        note = ("toți medicii" if not docs
                else "1 medic" if len(docs) == 1 else f"{len(docs)} medici")
        svc_lines.append(
            f"<label><input type='checkbox' name='svc' value='{e(sid)}'"
            f"{' checked' if checked else ''}> {e(sv['ro'])}<small>{note}</small></label>")
    right = f"""<div class='fcard'><h3>Servicii pe care le face</h3>
<form method='post' action='/admin/doctor-card/{dk}/services'>
  <div class='svcpick'>{''.join(svc_lines)}</div>
  <button class='savebtn' style='margin-top:10px'>{_ic('save')} Salvează serviciile</button>
</form>
<p class='hint' style='margin:8px 0 0'>Serviciul fără bife explicite se oferă la
<b>toți</b> medicii activi. Dacă scoateți bifa de la un astfel de serviciu, lista lui
devine explicită — un medic nou va trebui bifat manual.</p>
</div>
<div class='fcard'><h3>Ultimele 30 de zile</h3>
{"".join(f"<div class='frow'><span>{lbl}</span><span class='v'>{val}</span></div>" for lbl, val in
         [("Programări", stats['n']), ("Ocupare", f"{stats['pct']}%"),
          ("Neprezentări", stats['noshow']), ("Programări viitoare", future)])}
<p class='hint' style='margin:8px 0 0'><a href='/admin/stats'>Statistica întregii clinici {_ic('out')}</a></p>
</div>"""

    body = (f"<div class='nav'><a href='/admin/medici'>{_ic('med')} Toți medicii</a>"
            f"<a href='/admin/doctor/{dk}'>{_ic('cal')} Ziua medicului</a>"
            f"<a href='/admin'>{_ic('home')} Panou</a></div>{banner}{warn}"
            f"<div class='fisa med'><div class='fcol-l'>{left}</div>"
            f"<div class='fcol-c'>{center}</div><div class='fcol-r'>{right}</div></div>"
            + _card_modal(cards, back))
    return _shell(body, f"fișa medicului · {html.escape(name)}", active="med")


@router.post("/admin/doctor-card/{dk}/save")
async def doctor_card_save(request: Request, dk: str, name: str = Form(...),
                           spec: str = Form(""), room: str = Form(""),
                           phone: str = Form(""), email: str = Form(""),
                           color: str = Form(""), auto_color: str = Form(""),
                           work_from: str = Form(""), work_to: str = Form(""),
                           status: str = Form("activ")):
    if (deny := require(request, PERM_DOCTORS)) is not None:
        return deny
    if dk not in eng.DOCTORS:
        return RedirectResponse("/admin/medici", status_code=303)
    nm = name.strip()[:60]
    if not nm:
        return _med_redirect(dk, "bad_med")
    if any(d["id"] != dk and d["name"].casefold() == nm.casefold()
           for d in eng.CONFIG["doctors"]):
        return _med_redirect(dk, "dup_med")
    st = status if status in eng.DOCTOR_STATES else "activ"
    if st != "activ" and not any(d["id"] != dk and eng.doctor_state(d) == "activ"
                                 for d in eng.CONFIG["doctors"]):
        return _med_redirect(dk, "last_med")
    if st == "arhivat":
        # архив = «его больше нет в расписании»; с живыми будущими бронями это
        # тихо оставило бы пациентов без врача — только «в отпуске»
        if await db.doctor_future_count(dk, eng.DOCTORS[dk], datetime.now(eng.TZ)):
            return _med_redirect(dk, "arch_busy")
    wf = int(work_from) if work_from.isdecimal() and 0 <= int(work_from) <= 23 else None
    wt = int(work_to) if work_to.isdecimal() and 1 <= int(work_to) <= 24 else None
    if wf is not None and wt is not None and wf >= wt:
        return _med_redirect(dk, "bad_med")
    col = "" if auto_color else color.strip()[:16]
    if col and not re.fullmatch(r"#[0-9a-fA-F]{6}", col):
        return _med_redirect(dk, "bad_med")
    err = _patch_doctor(dk, name=nm, spec=spec.strip()[:60], room=room.strip()[:30],
                        phone=phone.strip()[:30], email=email.strip()[:80],
                        color=col, work_from=wf, work_to=wt, status=st)
    return _med_redirect(dk, "save_err" if err else "ok_med")


@router.post("/admin/doctor-card/{dk}/services")
async def doctor_card_services(request: Request, dk: str):
    if (deny := require(request, PERM_DOCTORS)) is not None:
        return deny
    if dk not in eng.DOCTORS:
        return RedirectResponse("/admin/medici", status_code=303)
    form = await request.form()
    picked = set(form.getlist("svc"))
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
            # отправка. Форма шлёт лишь отмеченные галочки, поэтому в эту ветку
            # приходит и услуга, где `dk` не значился никогда: её список не
            # меняется ни на элемент, а отказ по ней отбивал бы всю форму. Так
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
                return _med_redirect(dk, "svc_empty")
        if docs:
            entry["docs"] = docs
        else:
            entry.pop("docs", None)
        services.append(entry)
    err = _save_cfg(services=services)
    return _med_redirect(dk, "save_err" if err else "ok_svc_med")


@router.post("/admin/doctor-card/{dk}/photo")
async def doctor_card_photo(request: Request, dk: str, file: UploadFile = File(...)):
    if (deny := require(request, PERM_DOCTORS)) is not None:
        return deny
    if dk not in eng.DOCTORS:
        return RedirectResponse("/admin/medici", status_code=303)
    cap, buf = MAX_PHOTO_MB * 1024 * 1024, bytearray()
    try:
        while chunk := await file.read(1024 * 256):
            buf += chunk
            if len(buf) > cap:
                return _med_redirect(dk, "bad_photo")
    finally:
        await file.close()
    kind = _sniff_photo(bytes(buf[:16]))
    if not buf or not kind:
        return _med_redirect(dk, "bad_photo")
    old = _photo_path(dk)
    stored = _doctors_dir() / f"{dk}_{secrets.token_hex(6)}{kind[0]}"
    try:
        stored.write_bytes(bytes(buf))
    except OSError:
        stored.unlink(missing_ok=True)
        return _med_redirect(dk, "bad_photo")
    if _patch_doctor(dk, photo=stored.name):
        stored.unlink(missing_ok=True)      # конфиг не записался — файл не нужен
        return _med_redirect(dk, "save_err")
    if old and old != stored:
        old.unlink(missing_ok=True)
    return _med_redirect(dk, "ok_photo")


@router.post("/admin/doctor-card/{dk}/photo/del")
async def doctor_card_photo_del(request: Request, dk: str):
    if (deny := require(request, PERM_DOCTORS)) is not None:
        return deny
    if dk not in eng.DOCTORS:
        return RedirectResponse("/admin/medici", status_code=303)
    old = _photo_path(dk)
    if _patch_doctor(dk, photo=""):
        return _med_redirect(dk, "save_err")  # конфиг не записался — файл храним
    if old:
        old.unlink(missing_ok=True)
    return _med_redirect(dk, "ok_med")


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
