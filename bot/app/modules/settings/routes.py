"""Настройки клиники: профиль, часы работы, врачи и услуги, токен Telegram,
проверка и установка обновления.

Единственный экран, который ПИШЕТ `clinic.json` — и потому единственный, где
ошибка стоит дороже обычной: битый файл клиники означает старт с чужими
демо-врачами. Запись атомарная и с резервной копией, это в `eng.save_config`.

Правило то же: `core`, `db`, `engine` — да, `main.py` — нет.
"""
from __future__ import annotations

import html
import json
import logging
import os
import pathlib
import re
import shutil
import sys
import tempfile

from fastapi import APIRouter, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from starlette.background import BackgroundTask

from ... import db
from ... import dpapi, envfile
from ... import engine as eng
from ... import update as upd
from ...core.auth import (ADMIN_KEY, PERM_SETTINGS, PERM_USERS, ROLE_DIRECTOR,
                          ROLE_LABEL, ROLE_MEDIC, _pin_rec, all_users,
                          current_user, delete_user, find_user, n_directors,
                          pin_free, remember_auth_file, require, save_user)
from ...core.layout import (FEEDBACK_EMAIL, HOUR_MAX, HOUR_MIN, MSG_BANNER,
                            _DOC_STATE_RO, _DOW_FULL, _DOW_ORDER,
                            _doc_hours_text, _shell, tg_status)
from ...core.storage import _data_dir
from ...core.visits import SVC_PALETTE
from . import backup as bkp

router = APIRouter()

# id сотрудника: он попадает в подпись куки и в журнал доступа, поэтому только
# безопасные символы — точка в нём разделила бы куку не там, где надо
_UID_RE = re.compile(r"[a-z0-9_-]{2,20}")


def _set_back(msg: str) -> RedirectResponse:
    return RedirectResponse(f"/admin/settings?msg={msg}", status_code=303)


def _users_block() -> str:
    """Сотрудники клиники: кто входит и что ему можно.

    Вход идёт по ОДНОМУ паролю, без логина: регистратура набирает его десятки
    раз в день, и требовать ещё и id — трение на ровном месте. Отсюда правило,
    которое стережёт `pin_free`: пароли обязаны быть разными, иначе журнал
    доступа начнёт называть чужое имя. Id при этом есть у каждого — он нужен
    журналу и врачу на телефоне, где вход по одному паролю неочевиден.
    """
    e = html.escape
    doc_opts = "".join(f"<option value='{e(k)}'>{e(v)}</option>"
                       for k, v in eng.DOCTORS.items())
    rows = []
    for u in all_users():
        sel_role = "".join(
            f"<option value='{k}'{' selected' if k == u['role'] else ''}>{v}</option>"
            for k, v in ROLE_LABEL.items())
        sel_doc = "".join(
            f"<option value='{e(k)}'{' selected' if k == u['doctor_id'] else ''}>"
            f"{e(v)}</option>" for k, v in eng.DOCTORS.items())
        rows.append(
            f"<tr><td><b>{e(u['name'])}</b><br>"
            f"<small style='color:var(--text3)'>id: {e(u['id'])}</small></td>"
            f"<td><form method='post' action='/admin/users/save' "
            f"style='display:flex;gap:6px;flex-wrap:wrap;align-items:center'>"
            f"<input type='hidden' name='uid' value='{e(u['id'])}'>"
            f"<input type='hidden' name='name' value=\"{e(u['name'])}\">"
            f"<select name='role'>{sel_role}</select>"
            f"<select name='doctor_id'><option value=''>— nu e medic —</option>"
            f"{sel_doc}</select>"
            f"<input type='password' name='pin' placeholder='PIN nou (opțional)' "
            f"inputmode='numeric' maxlength='6' style='width:150px'>"
            f"<button>Salvează</button></form></td>"
            f"<td><form method='post' action='/admin/users/delete' "
            f"onsubmit=\"return confirm('Ștergeți contul {e(u['name'])}?')\">"
            f"<input type='hidden' name='uid' value='{e(u['id'])}'>"
            f"<button class='rowdel'>Șterge</button></form></td></tr>")
    role_opts = "".join(f"<option value='{k}'"
                        f"{' selected' if k == ROLE_MEDIC else ''}>{v}</option>"
                        for k, v in ROLE_LABEL.items())
    return f"""
<h2>👥 Utilizatori</h2>
<table class='set'><tr><th style='width:220px'>Persoana</th><th>Acces</th><th></th></tr>
{''.join(rows)}</table>
<form class='add' method='post' action='/admin/users/save'>
  <input name='name' placeholder='Nume și prenume' maxlength='60' required style='width:200px'>
  <input name='uid' placeholder='id (ex. d2, ana)' maxlength='20' required style='width:130px'>
  <select name='role'>{role_opts}</select>
  <select name='doctor_id'><option value=''>— nu e medic —</option>{doc_opts}</select>
  <input type='password' name='pin' placeholder='PIN 4–6 cifre' inputmode='numeric'
         maxlength='6' required style='width:150px'>
  <button>+ Adaugă utilizator</button>
</form>
<p class='hint'>Intrarea se face cu PIN-ul personal, fără nume de utilizator —
de aceea PIN-ul trebuie să fie unic în clinică. <b>Director</b> vede banii și
setările, <b>Recepție</b> și <b>Medic</b> — tot restul. Legătura cu un medic
face ca jurnalul să scrie numele lui la fiecare deschidere de fișă.</p>"""

_PALETTE_RO = {"green": "verde", "blue": "albastru", "amber": "portocaliu",
               "violet": "violet", "red": "roșu", "teal": "turcoaz"}


_DOW_SHORT = {"ro": {"mon": "Lu", "tue": "Ma", "wed": "Mi", "thu": "Jo",
                     "fri": "Vi", "sat": "Sâ", "sun": "Du"},
              "ru": {"mon": "Пн", "tue": "Вт", "wed": "Ср", "thu": "Чт",
                     "fri": "Пт", "sat": "Сб", "sun": "Вс"}}


def _hours_summary(hours: dict, lang: str) -> str:
    """'Lu–Vi 9:00–18:00, Sâ 9:00–14:00' из hours-словаря."""
    names = _DOW_SHORT[lang]
    parts = []
    i = 0
    while i < 7:
        h = hours.get(_DOW_ORDER[i])
        j = i
        while j + 1 < 7 and hours.get(_DOW_ORDER[j + 1]) == h:
            j += 1
        if h:
            rng = (names[_DOW_ORDER[i]] if i == j
                   else f"{names[_DOW_ORDER[i]]}–{names[_DOW_ORDER[j]]}")
            txt = f"{rng} {h[0]}:00–{h[1]}:00"
            if len(h) >= 4:
                txt += (f" (pauză {h[2]}:00–{h[3]}:00)" if lang == "ro"
                        else f" (перерыв {h[2]}:00–{h[3]}:00)")
            parts.append(txt)
        i = j + 1
    return ", ".join(parts)


def _hour_opts(sel: int, lo: int = HOUR_MIN, hi: int = HOUR_MAX) -> str:
    return "".join(
        f"<option value='{h}'{' selected' if h == sel else ''}>{h}:00</option>"
        for h in range(lo, hi + 1)
    )


@router.get("/admin/settings", response_class=HTMLResponse)
async def admin_settings(request: Request, msg: str = ""):
    if (deny := require(request, PERM_SETTINGS)) is not None:
        return deny
    cfg = eng.CONFIG
    e = html.escape

    def _break_opts(sel) -> str:
        out = [f"<option value=''{' selected' if sel is None else ''}>—</option>"]
        for x in range(HOUR_MIN, HOUR_MAX + 1):
            out.append(f"<option value='{x}'{' selected' if sel == x else ''}>{x}:00</option>")
        return "".join(out)

    hours_rows = []
    for day in _DOW_ORDER:
        h = cfg.get("hours", {}).get(day)
        closed = h is None
        hv = list(h) if h else [9, 18]
        f, t = int(hv[0]), int(hv[1])
        bf = int(hv[2]) if len(hv) >= 4 else None
        bt = int(hv[3]) if len(hv) >= 4 else None
        hours_rows.append(
            f"<tr><td>{_DOW_FULL[day]}</td>"
            f"<td><input type='checkbox' id='hc_{day}'{' checked' if closed else ''}> închis</td>"
            f"<td><select id='hf_{day}'>{_hour_opts(f)}</select></td>"
            f"<td><select id='ht_{day}'>{_hour_opts(t, HOUR_MIN + 1, HOUR_MAX)}</select></td>"
            f"<td><select id='hb_{day}'>{_break_opts(bf)}</select></td>"
            f"<td><select id='he_{day}'>{_break_opts(bt)}</select></td></tr>"
        )

    def _color_opts(sel: str) -> str:
        out = [f"<option value=''{' selected' if not sel else ''}>auto</option>"]
        for k, ro in _PALETTE_RO.items():
            out.append(f"<option value='{k}'{' selected' if sel == k else ''}>{ro}</option>")
        return "".join(out)

    # v1.9.0: таблица врачей уехала в раздел «Medici» — здесь только сводка,
    # чтобы у каталога врачей было ровно одно место правки
    doc_rows = "".join(
        f"<tr><td><a href='/admin/doctor-card/{e(d['id'])}'>{e(d['name'])}</a></td>"
        f"<td>{e(d.get('spec', '')) or '—'}</td><td>{e(d.get('room', '')) or '—'}</td>"
        f"<td>{e(d.get('phone', '')) or '—'}</td>"
        f"<td>{e(_doc_hours_text(d['id']))}</td>"
        f"<td><span class='dbadge {eng.doctor_state(d)}'>"
        f"{_DOC_STATE_RO[eng.doctor_state(d)]}</span></td></tr>"
        for d in cfg["doctors"]
    )
    def _dur_opts(sel) -> str:
        cur = int(sel) if sel else 60
        return "".join(f"<option value='{x}'{' selected' if cur == x else ''}>{x} min</option>"
                       for x in (15, 30, 45, 60, 90, 120))

    svc_rows = "".join(
        f"<tr><td><input type='hidden' class='s_id' value='{e(s['id'])}'>"
        f"<input type='text' class='s_ro' value='{e(s['ro'])}'></td>"
        f"<td><input type='text' class='s_ru' value='{e(s['ru'])}'></td>"
        f"<td><input type='text' class='s_price' value='{e(str(s.get('price', '')) if not isinstance(s.get('price'), dict) else s['price'].get('ro', ''))}'></td>"
        f"<td><select class='s_dur'>{_dur_opts(s.get('duration'))}</select></td>"
        f"<td><select class='s_color'>{_color_opts(s.get('color', ''))}</select></td>"
        f"<td style='text-align:center'><input type='checkbox' class='s_urg'{' checked' if s.get('urgent') else ''}></td>"
        f"<td><input type='text' class='s_docs' value='{e(' '.join(s.get('docs', [])))}' placeholder='gol = toți'></td>"
        f"<td><button type='button' class='rowdel' onclick='this.closest(\"tr\").remove()'>✖</button></td></tr>"
        for s in cfg["services"]
    )
    doc_ids_hint = ", ".join(f"{d['id']}={e(d['name'])}" for d in cfg["doctors"])

    banner = ""
    if msg in MSG_BANNER:
        cls, text = MSG_BANNER[msg]
        banner = f"<div class='banner {cls}'>{text}</div>"

    # статус спрашиваем у core, а не повторяем трюк с sys.modules: имя пакета
    # зависит от того, где лежит файл, и своя копия уже один раз соврала
    tg = tg_status()
    if tg["running"]:
        tg_line = f"✅ activ — @{html.escape(tg['username'])}"
    elif os.environ.get("DENTART_TOKEN_UNREADABLE") == "1":
        # шифротекст не с этой машины (см. dpapi.py). Молчаливое «fără token»
        # отправило бы клинику чинить настройки бота, которые в порядке
        tg_line = ("🔑 tokenul nu poate fi citit pe acest calculator — "
                   "reintroduceți-l mai jos")
    elif os.environ.get("TELEGRAM_TOKEN", "").strip():
        tg_line = f"⚠️ {html.escape(tg.get('error') or 'pornire…')}"
    else:
        tg_line = "— fără token (adăugați TELEGRAM_TOKEN în dental.env / .env)"
    if upd.can_self_update():
        up_line = (
            f"🔄 disponibilă {html.escape(upd.STATE['latest'])} "
            f"<form method='post' action='/admin/update/run' style='display:inline'>"
            f"<button style='background:#e8710a;color:#fff;border:none;border-radius:6px;"
            f"padding:6px 14px;cursor:pointer;font-size:14px;margin-left:8px'>"
            f"⬆️ Actualizează acum</button></form>"
        )
    elif upd.asset_pending() and upd.is_desktop():
        up_line = (f"🕐 versiunea {html.escape(upd.STATE['latest'])} este anunțată, "
                   f"dar fișierul programului încă nu e publicat — "
                   f"reverificăm automat peste câteva minute")
    elif upd.newer_available():
        up_line = (f"<a href='{html.escape(upd.STATE['url'])}' target='_blank'>"
                   f"🔄 disponibilă {html.escape(upd.STATE['latest'])} — descărcați</a>")
    elif upd.STATE["checked"] and not upd.STATE["error"]:
        up_line = "✅ la zi"
    elif upd.STATE["error"]:
        up_line = "— necunoscut (offline?)"
    else:
        up_line = "se verifică…"
    # Канал виден в интерфейсе намеренно: на этой машине обновление приходит
    # РАНЬШЕ, чем клиникам, и перепутать её с боевой установкой нельзя.
    chan_row = ""
    ch = upd.channel()
    if ch != "stable":
        # beta — публичные пре-релизы, ключ не нужен; draft — ещё и черновики,
        # но для них нужен токен с правом записи. Названия разные намеренно:
        # риск у этих двух режимов разный, и путать их нельзя.
        name = "🧪 draft (test)" if ch == "draft" else "🧪 beta (pre-lansări)"
        note = ""
        if upd.STATE.get("draft"):
            note = " · versiunea curentă din canal este nepublicată"
        elif upd.STATE.get("prerelease"):
            note = " · versiunea curentă din canal este pre-lansare"
        chan_row = (f"<tr><th>Canal actualizări</th><td>"
                    f"<b style='color:var(--amber-t)'>{name}</b> — "
                    "acest calculator vede versiunile ÎNAINTE de clinici"
                    + note + "</td></tr>")
    up_line += ("<form method='post' action='/admin/update/check' style='display:inline'>"
                "<button style='background:none;border:1px solid var(--line);border-radius:8px;"
                "padding:4px 10px;cursor:pointer;font-size:12px;color:var(--text2);"
                "margin-left:10px'>🔄 Verifică acum</button></form>")
    status_tbl = f"""
<h2>ℹ️ Stare sistem</h2>
<table class='set'>
<tr><th style='width:180px'>Versiune</th><td>v{eng.APP_VERSION}</td></tr>
<tr><th>Bază de date</th><td>{"SQLite (local, data/dental.db)" if db.IS_SQLITE else "PostgreSQL"}</td></tr>
<tr><th>Canal Telegram</th><td>{tg_line}</td></tr>
<tr><th>Actualizări</th><td>{up_line}</td></tr>
{chan_row}
<tr><th>Acces jurnal</th><td>{"🔒 PIN setat" if _pin_rec() else ("🔒 parolă (ADMIN_KEY)" if ADMIN_KEY else "🔓 deschis")}</td></tr>
<tr><th>Feedback / suport</th><td><a href='mailto:{FEEDBACK_EMAIL}'>{FEEDBACK_EMAIL}</a></td></tr>
</table>

<h2>🔐 Confidențialitate</h2>
<div class='pcard' style='max-width:760px'>
<p style='margin:0 0 8px;font-size:13px;line-height:1.55;color:var(--text2)'>
<b style='color:var(--text)'>Programul funcționează local.</b> Datele personale ale pacienților
nu sunt transmise dezvoltatorului și nu sunt stocate pe serverele acestuia.
Actualizările descarcă doar fișierele programului. Baza de date, jurnalele și
copiile de rezervă rămân pe acest calculator, în folderul programului.</p>
<p style='margin:0;font-size:12.5px;line-height:1.55;color:var(--text3)'>
Программа работает локально. Персональные данные пациентов не передаются
разработчику и не хранятся на его серверах. Обновления загружают только файлы
программы. База данных, журналы и резервные копии остаются на этом компьютере.</p>
</div>"""
    if db.IS_SQLITE and os.environ.get("DENTART_ENV_FILE"):
        tok_set = bool(os.environ.get("TELEGRAM_TOKEN", "").strip())
        ph = ("••• token setat — introduceți altul pentru schimbare" if tok_set
              else "token de la @BotFather (ex. 123456789:AA...)")
        status_tbl += f"""
<h2>📱 Telegram — token bot</h2>
<form class='add' method='post' action='/admin/telegram/save'
      onsubmit="return confirm('Programul se va reporni pentru aplicare. Continuați?')">
  <input type='password' name='token' placeholder="{ph}" style='width:430px'>
  <button>💾 Salvează și repornește</button>
</form>
<p class='hint'>Creați botul clinicii la @BotFather (2 minute) și lipiți tokenul aici.
Câmp gol + salvare = dezactivează canalul Telegram.</p>"""
    if db.IS_SQLITE and bkp.available():
        status_tbl += f"""
<h2>💾 Copie de rezervă criptată</h2>
<form class='add' method='post' action='/admin/backup/export'>
  <input type='password' name='parola' placeholder='parolă (min. {bkp.MIN_PASS} caractere)'
         minlength='{bkp.MIN_PASS}' required style='width:280px' autocomplete='new-password'>
  <button>📦 Exportă arhiva</button>
</form>
<p class='hint'>Arhivă ZIP criptată (AES-256) cu baza de date, profilul clinicii și
documentele pacienților — pentru stick USB sau alt calculator. Se deschide cu 7-Zip
prin parola aleasă. <b>Parola nu se salvează nicăieri</b> — fără ea arhiva nu poate
fi citită de nimeni, nici de noi.</p>"""
    if _pin_rec():
        status_tbl += """
<h2>🔒 Schimbă PIN</h2>
<form class='add' method='post' action='/admin/pin/change'>
  <input type='password' name='old_pin' placeholder='PIN actual' inputmode='numeric' maxlength='6' required style='width:140px'>
  <input type='password' name='new1' placeholder='PIN nou' inputmode='numeric' maxlength='6' required style='width:140px'>
  <input type='password' name='new2' placeholder='repetați' inputmode='numeric' maxlength='6' required style='width:140px'>
  <button>Schimbă</button>
</form>"""
        status_tbl += _users_block()

    body = f"""
<div class='nav'><a href='/admin'>🏠 Panou</a></div>
{banner}
{status_tbl}
<form method='post' action='/admin/settings/save' onsubmit='return collectSettings()'>
<input type='hidden' name='payload' id='payload'>

<h2>🏥 Clinica</h2>
<table class='set'>
<tr><th style='width:180px'>Nume</th><td><input type='text' id='cname' value='{e(cfg["name"])}'></td></tr>
<tr><th>Telefon</th><td><input type='text' id='cphone' value='{e(cfg["phone"])}'></td></tr>
<tr><th>Adresa (RO)</th><td><input type='text' id='caddr_ro' value='{e(cfg.get("address", {}).get("ro", ""))}'></td></tr>
<tr><th>Adresa (RU)</th><td><input type='text' id='caddr_ru' value='{e(cfg.get("address", {}).get("ru", ""))}'></td></tr>
</table>

<h2>🕘 Program de lucru</h2>
<table class='set'>
<tr><th>Ziua</th><th>Închis</th><th>De la</th><th>Până la</th>
<th>Pauză de la</th><th>Pauză până la</th></tr>
{''.join(hours_rows)}
</table>
<p class='hint'>Pauza (ex. prânz 13:00–14:00) dispare din calendarul botului și din registru.
«—» = fără pauză.</p>

<h2>👨‍⚕️ Medici</h2>
<table class='set'>
<tr><th>Nume</th><th>Specializare</th><th style='width:90px'>Cabinet</th>
<th style='width:110px'>Telefon</th><th style='width:150px'>Program</th>
<th style='width:110px'>Stare</th></tr>
{doc_rows}
</table>
<p class='hint'>Medicii se editează în secțiunea
<a href='/admin/medici'><b>👨‍⚕️ Medici</b></a> — acolo sunt fișa completă, fotografia,
serviciile și starea (activ / în concediu / arhivat). Aici sunt afișați doar pentru
verificare, ca datele lor să aibă un singur loc de modificare.</p>

<h2>🦷 Servicii</h2>
<table class='set' id='svc_t'>
<tr><th>Denumire (RO)</th><th>Denumire (RU)</th><th style='width:120px'>Preț</th>
<th style='width:90px'>Durată</th><th style='width:100px'>Culoare</th>
<th style='width:40px'>🆘</th><th style='width:140px'>Medici (id)</th><th></th></tr>
<tbody id='svc_tb'>{svc_rows}</tbody>
</table>
<button type='button' class='addrow' onclick='addSvc()'>+ Adaugă serviciu</button>
<p class='hint'>Coloana «Medici»: id-uri separate prin spațiu ({doc_ids_hint}); gol = toți medicii.
🆘 = flux urgent (fără alegerea medicului, sloturi din ziua curentă).</p>

<button class='savebtn'>💾 Salvează setările</button>
</form>

<script>
const SVC_COLORS = {json.dumps(_PALETTE_RO)};
function addSvc() {{
  const tb = document.getElementById('svc_tb');
  const tr = document.createElement('tr');
  let opts = "<option value=''>auto</option>";
  for (const k in SVC_COLORS) opts += "<option value='" + k + "'>" + SVC_COLORS[k] + "</option>";
  let dopts = "";
  for (const x of [15, 30, 45, 60, 90, 120])
    dopts += "<option value='" + x + "'" + (x === 60 ? " selected" : "") + ">" + x + " min</option>";
  tr.innerHTML = "<td><input type='hidden' class='s_id' value=''>" +
    "<input type='text' class='s_ro' placeholder='Serviciu'></td>" +
    "<td><input type='text' class='s_ru' placeholder='Услуга'></td>" +
    "<td><input type='text' class='s_price' placeholder='500 MDL'></td>" +
    "<td><select class='s_dur'>" + dopts + "</select></td>" +
    "<td><select class='s_color'>" + opts + "</select></td>" +
    "<td style='text-align:center'><input type='checkbox' class='s_urg'></td>" +
    "<td><input type='text' class='s_docs' placeholder='gol = toți'></td>" +
    "<td><button type='button' class='rowdel' onclick='this.closest(\\"tr\\").remove()'>✖</button></td>";
  tb.appendChild(tr);
}}
function collectSettings() {{
  const days = ['mon','tue','wed','thu','fri','sat','sun'];
  const hours = {{}};
  for (const d of days) {{
    if (document.getElementById('hc_' + d).checked) {{ hours[d] = null; continue; }}
    const f = parseInt(document.getElementById('hf_' + d).value);
    const t = parseInt(document.getElementById('ht_' + d).value);
    const bf = document.getElementById('hb_' + d).value;
    const bt = document.getElementById('he_' + d).value;
    if (bf !== '' && bt !== '') hours[d] = [f, t, parseInt(bf), parseInt(bt)];
    else hours[d] = [f, t];
  }}
  const services = [];
  document.querySelectorAll('#svc_tb tr').forEach(tr => {{
    services.push({{ id: tr.querySelector('.s_id').value,
                    ro: tr.querySelector('.s_ro').value,
                    ru: tr.querySelector('.s_ru').value,
                    price: tr.querySelector('.s_price').value,
                    duration: tr.querySelector('.s_dur').value,
                    color: tr.querySelector('.s_color').value,
                    urgent: tr.querySelector('.s_urg').checked,
                    docs: tr.querySelector('.s_docs').value }});
  }});
  // валидация ДО отправки: при серверной ошибке форма перерисуется из
  // сохранённого конфига и все правки админа пропадут — не доводим до этого
  const seen = {{}};
  for (const s of services) {{
    const key = s.ro.trim().toLowerCase();
    if (!key) continue;
    if (seen[key]) {{
      alert('Două rânduri au aceeași denumire de serviciu: «' + s.ro.trim() +
            '». Redenumiți unul dintre ele.');
      return false;
    }}
    seen[key] = true;
  }}
  // медиков форма больше не отправляет — их каталог правится în «Medici»
  const payload = {{
    name: document.getElementById('cname').value,
    phone: document.getElementById('cphone').value,
    address: {{ ro: document.getElementById('caddr_ro').value,
               ru: document.getElementById('caddr_ru').value }},
    hours: hours, services: services
  }};
  document.getElementById('payload').value = JSON.stringify(payload);
  return true;
}}
</script>"""
    return _shell(body, "setările clinicii · se aplică imediat, fără restart", active="set")


def _build_config(data: dict) -> dict:
    name = str(data.get("name", "")).strip()[:80]
    phone = str(data.get("phone", "")).strip()[:30]
    if not name or not phone:
        raise ValueError("name/phone")
    addr_ro = str(data.get("address", {}).get("ro", "")).strip()[:120]
    addr_ru = str(data.get("address", {}).get("ru", "")).strip()[:120]

    hours = {}
    for day in _DOW_ORDER:
        h = data.get("hours", {}).get(day)
        if h is None:
            hours[day] = None
            continue
        vals = [int(x) for x in h]
        if len(vals) == 2:
            f, t = vals
            if not (0 <= f < t <= 24):
                raise ValueError("hours")
            hours[day] = [f, t]
        elif len(vals) == 4:
            f, t, bf, bt = vals
            if not (0 <= f < t <= 24 and f <= bf < bt <= t):
                raise ValueError("break")
            if bf <= f and bt >= t:
                raise ValueError("break=whole day")
            hours[day] = [f, t, bf, bt]
        else:
            raise ValueError("hours format")
    if all(v is None for v in hours.values()):
        raise ValueError("all closed")

    # ⭐ Счётчики id ПЕРСИСТЕНТНЫ (cfg["seq"]) и только растут. Раньше id искался
    # как первый свободный d{n} среди текущего списка: удалили d2, добавили врача —
    # он получал d2 и наследовал историю уволенного. Теперь id не переиспользуется.
    seq = dict(eng.CONFIG.get("seq") or {})
    seq_d = int(seq.get("doctor", 0))
    seq_s = int(seq.get("service", 0))
    for d in eng.CONFIG.get("doctors", []):
        mnum = re.fullmatch(r"d(\d+)", str(d.get("id", "")))
        if mnum:
            seq_d = max(seq_d, int(mnum.group(1)))
    for s in eng.CONFIG.get("services", []):
        mnum = re.fullmatch(r"s(\d+)", str(s.get("id", "")))
        if mnum:
            seq_s = max(seq_s, int(mnum.group(1)))

    # v1.9.0: врачей эта форма больше не присылает — их каталог правится только
    # в разделе «Medici», поэтому переносим список как есть (фото/e-mail/статус
    # не должны теряться из-за сохранения настроек клиники)
    doctors = [dict(d) for d in eng.CONFIG.get("doctors", [])]
    if not doctors:
        raise ValueError("doctors")
    doc_ids = {d["id"] for d in doctors}
    # то же для услуг: одинаковые подписи ломали бы бэкфилл service_id и отчёты
    labels_seen: set[str] = set()

    services = []
    sused: set[str] = set()
    for s in data.get("services", []):
        ro = str(s.get("ro", "")).strip()[:60]
        ru = str(s.get("ru", "")).strip()[:60] or ro
        if not ro:
            continue
        if ro.casefold() in labels_seen or (ru.casefold() != ro.casefold()
                                            and ru.casefold() in labels_seen):
            raise ValueError("duplicate service label")
        labels_seen.add(ro.casefold())
        labels_seen.add(ru.casefold())
        sid = str(s.get("id", "")).strip()
        if not re.fullmatch(r"[a-z0-9_]{1,20}", sid) or sid in sused:
            seq_s += 1
            sid = f"s{seq_s}"
        sused.add(sid)
        entry: dict = {"id": sid, "ro": ro, "ru": ru}
        price = str(s.get("price", "")).strip()[:60]
        if price:
            entry["price"] = price
        dur_raw = str(s.get("duration", "") or "").strip()
        if dur_raw.isdecimal() and int(dur_raw) in (15, 30, 45, 60, 90, 120):
            if int(dur_raw) != 60:
                entry["duration"] = int(dur_raw)  # 60 = дефолт, не пишем
        color_s = str(s.get("color", "")).strip()
        if color_s in SVC_PALETTE:
            entry["color"] = color_s
        if s.get("urgent"):
            entry["urgent"] = True
        docs = [tok for tok in re.split(r"[,\s]+", str(s.get("docs", "")))
                if tok in doc_ids]
        if docs:
            entry["docs"] = docs
        services.append(entry)
    if not services:
        raise ValueError("services")

    cfg = dict(eng.CONFIG)
    cfg.pop("template", None)      # клинику заполнили — подсказка больше не нужна
    cfg.pop("_comment", None)
    cfg.update({"name": name, "phone": phone,
                "address": {"ro": addr_ro, "ru": addr_ru},
                "hours": hours, "doctors": doctors, "services": services,
                "seq": {"doctor": seq_d, "service": seq_s}})
    cfg["contacts"] = {
        "ro": (f"📍 {addr_ro}\n" if addr_ro else "")
              + f"☎️ {phone}\n🕘 {_hours_summary(hours, 'ro')}",
        "ru": (f"📍 {addr_ru}\n" if addr_ru else "")
              + f"☎️ {phone}\n🕘 {_hours_summary(hours, 'ru')}",
    }
    return cfg


@router.post("/admin/update/check")
def admin_update_check(request: Request):
    """Проверить обновления прямо сейчас — не ждать следующего цикла.
    Синхронный def → threadpool, сетевой запрос не блокирует сервер."""
    if (deny := require(request, PERM_SETTINGS)) is not None:
        return deny
    upd.check_now()
    return RedirectResponse("/admin/settings", status_code=303)


@router.post("/admin/update/run", response_class=HTMLResponse)
def admin_update_run(request: Request):
    """Одним кликом: скачать новый exe, подменить себя, перезапуститься.
    Синхронный def — FastAPI выполняет в threadpool (скачивание блокирует)."""
    if (deny := require(request, PERM_SETTINGS)) is not None:
        return deny
    err = upd.self_update()
    if err:
        return RedirectResponse("/admin/settings?msg=upd_err", status_code=303)
    return f"""<!doctype html><html lang="ro"><head><meta charset="utf-8">
<meta http-equiv="refresh" content="18;url=/admin/settings">
<title>Actualizare…</title><style>
 body{{font-family:system-ui,sans-serif;display:flex;flex-direction:column;align-items:center;
      justify-content:center;height:100vh;margin:0;background:#0E9F8A;color:#fff;text-align:center}}
 .sp{{font-size:44px;animation:r 1.2s linear infinite;display:inline-block}}
 @keyframes r{{to{{transform:rotate(360deg)}}}}
</style></head><body>
<div class="sp">🔄</div>
<h1>Se actualizează la {html.escape(upd.STATE['latest'])}…</h1>
<p>Programul se închide și repornește singur.<br>
Această pagină se va reîncărca automat în ~18 secunde.</p>
</body></html>"""


@router.post("/admin/users/save")
async def users_save(request: Request, uid: str = Form(...), name: str = Form(""),
                     role: str = Form(ROLE_MEDIC), doctor_id: str = Form(""),
                     pin: str = Form("")):
    """Завести сотрудника или поправить его доступ."""
    if (deny := require(request, PERM_USERS)) is not None:
        return deny
    uid, name, pin = uid.strip().lower()[:20], name.strip()[:60], pin.strip()
    if not _UID_RE.fullmatch(uid) or role not in ROLE_LABEL:
        return _set_back("bad_user")
    existing = find_user(uid)
    if not existing and not pin:
        return _set_back("bad_user")           # новому нужен пароль
    if pin and (not pin.isdigit() or not (4 <= len(pin) <= 6)):
        return _set_back("bad_user")
    # ⚠️ проверка ДО записи: вход идёт по одному лишь паролю, и два одинаковых
    # означают, что журнал доступа однажды назовёт не того человека
    if pin and not pin_free(pin, except_uid=uid):
        return _set_back("dup_user")
    # директор, снимающий с себя роль последним, запирает настройки НАВСЕГДА:
    # вернуть право станет некому
    if (existing and (existing.get("role") or ROLE_DIRECTOR) == ROLE_DIRECTOR
            and role != ROLE_DIRECTOR and n_directors(excluding=uid) == 0):
        return _set_back("last_dir")
    save_user(uid, name=name or (existing or {}).get("name") or uid, role=role,
              doctor_id=doctor_id if doctor_id in eng.DOCTORS else "",
              pin=pin or None)
    await remember_auth_file()      # своя запись — не «взлом» при след. старте
    return _set_back("ok_user")


@router.post("/admin/users/delete")
async def users_delete(request: Request, uid: str = Form(...)):
    if (deny := require(request, PERM_USERS)) is not None:
        return deny
    me = current_user(request)
    if me and me.get("id") == uid:
        return _set_back("self_user")
    if n_directors(excluding=uid) == 0:
        return _set_back("last_dir")
    delete_user(uid)
    await remember_auth_file()
    return _set_back("ok_user")


@router.post("/admin/backup/export")
async def admin_backup_export(request: Request, parola: str = Form(...)):
    """Зашифрованный архив клиники — целиком, для флешки или переезда.

    Пишется во временную папку и отдаётся файлом; временное подчищает фоновая
    задача после отдачи (как у выгрузки данных пациента). minlength в форме —
    вежливость, настоящая проверка тут: форму можно послать и без браузера.
    """
    if (deny := require(request, PERM_SETTINGS)) is not None:
        return deny
    d = _data_dir()
    if d is None or not bkp.available():
        return RedirectResponse("/admin/settings", status_code=303)
    if len(parola) < bkp.MIN_PASS:
        return RedirectResponse("/admin/settings?msg=bad_bkp_pass", status_code=303)
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="dp_backup_"))
    dest = tmp / "backup.zip"
    clinic = os.environ.get("CLINIC_CONFIG", "")
    try:
        n = bkp.write_encrypted(d, pathlib.Path(clinic) if clinic else None,
                                parola, dest)
    except OSError as ex:
        logging.getLogger("settings").warning("backup export: %r", ex)
        shutil.rmtree(tmp, ignore_errors=True)
        return RedirectResponse("/admin/settings?msg=bad_bkp", status_code=303)
    logging.getLogger("settings").warning("encrypted backup exported (%d files)", n)
    return FileResponse(
        dest, filename=bkp.archive_name(), media_type="application/zip",
        background=BackgroundTask(shutil.rmtree, tmp, ignore_errors=True))


@router.post("/admin/telegram/save", response_class=HTMLResponse)
async def admin_telegram_save(request: Request, token: str = Form("")):
    if (deny := require(request, PERM_SETTINGS)) is not None:
        return deny
    env_file = os.environ.get("DENTART_ENV_FILE", "")
    if not (db.IS_SQLITE and env_file):
        return RedirectResponse("/admin/settings", status_code=303)
    tok = token.strip()
    if tok and not re.fullmatch(r"\d{6,12}:[\w-]{30,120}", tok):
        return RedirectResponse("/admin/settings?msg=bad_tok", status_code=303)
    # в файл — шифротекст (dpapi), в окружение — открытый токен: им дальше
    # пользуются и бот, и статус на этой же странице. Если DPAPI недоступен
    # (запуск из исходников не под Windows), пишем как раньше — иначе правка
    # токена перестала бы работать у разработчика вовсе.
    envfile.set_value(pathlib.Path(env_file), "TELEGRAM_TOKEN",
                      (dpapi.protect(tok) or tok) if tok else "")
    os.environ["TELEGRAM_TOKEN"] = tok
    os.environ.pop("DENTART_TOKEN_UNREADABLE", None)
    if upd.restart_app() is not None:
        # dev-режим/тест-хук: перезапуск не случился — просто баннер
        return RedirectResponse("/admin/settings?msg=ok_tok", status_code=303)
    return f"""<!doctype html><html lang="ro"><head><meta charset="utf-8">
<meta http-equiv="refresh" content="15;url=/admin/settings">
<title>Repornire…</title><style>
 body{{font-family:system-ui,sans-serif;display:flex;flex-direction:column;align-items:center;
      justify-content:center;height:100vh;margin:0;background:#0E9F8A;color:#fff;text-align:center}}
 .sp{{font-size:44px;animation:r 1.2s linear infinite;display:inline-block}}
 @keyframes r{{to{{transform:rotate(360deg)}}}}
</style></head><body>
<div class="sp">🔄</div>
<h1>Token salvat — programul repornește…</h1>
<p>Fereastra se va redeschide singură în câteva secunde.</p>
</body></html>"""


@router.post("/admin/settings/save")
async def admin_settings_save(request: Request, payload: str = Form(...)):
    if (deny := require(request, PERM_SETTINGS)) is not None:
        return deny
    try:
        cfg = _build_config(json.loads(payload))
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return RedirectResponse("/admin/settings?msg=bad_set", status_code=303)
    if eng.save_config(cfg) is not None:
        return RedirectResponse("/admin/settings?msg=bad_set", status_code=303)
    return RedirectResponse("/admin/settings?msg=ok_set", status_code=303)
