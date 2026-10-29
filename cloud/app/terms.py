"""Акт акцепта условий (29.10, план review/plan-contract-dataflows-maib-2026-10-29.md § 3.2, вариант A/C).

Договор с клиникой — публичные «Termeni și condiții» сайта; клиника принимает их галочкой на
странице активации программы и на странице оплаты. До 29.10 доказательство лежало только у
клиники (летопись в её `dental.db`, `license.pending`), а серверу уходило одно `consent=1`
(`clinics.consent_at`) — без версии условий. Теперь каждое принятие — строка `terms_acceptances`:
клиника, ВЕРСИЯ (дата «Ultima actualizare» страницы), кто принял (имя директора, как его
записала программа), когда, с какого адреса, какой компьютер (`X-DentPilot-Device`) и какая
программа (`User-Agent`), откуда:

  trial    — заявка на пробный из программы (`/v1/trial` с полем `terms`);
  verify   — активация на новом компьютере кодом из письма (`/v1/verify` с `terms`);
  pay      — галочка на странице оплаты `/plata/<id>` (версия — CURRENT сервера);
  program  — повторное принятие новой версии из программы (`/v1/terms/accept`, Bearer файла).

Программа без поля `terms` (старые версии) принимается как раньше — строки акта нет, есть
`consent_at`. Ответ `/v1/license` несёт заголовок `X-DentPilot-Terms` — последняя принятая версия
клиники: по нему программа на любом её компьютере знает, просить ли принять новую версию
(баннер в программе — уведомление, не замок: условия § 13).

Клиника видит свои акты в кабинете (`/cont/acceptari`, печатная страница акта — её экземпляр к
общему договору, подписанному Олегом один раз; раздел «Documente» кабинета делает `contract-sign`
и зовёт `cont_fragment`). Админка — список во вкладке «Лицензия» карточки (`admin_fragment`).

⚠️ `CURRENT` — та же дата, что `TERMS_VERSION` программы и «Ultima actualizare» termeni.html:
равенство держит cloud/tests/test_terms.py (сервер своей копии текста не имеет, страница оплаты
принимает «текущие» условия сайта). `terms_sha256` — хеш текста, если клиент его назвал
(сегодня программа текста не имеет и поле пусто; колонка — на будущее, когда текст поедет
с сервером).
"""
from __future__ import annotations

import html
import re
import secrets
import sqlite3
from datetime import date

from . import config, db

API_ACCEPT = "/v1/terms/accept"          # повторное принятие из программы (Bearer — токен файла)
H_TERMS = "X-DentPilot-Terms"            # заголовок ответа /v1/license: последняя принятая версия
PAGE = "/cont/acceptari"                 # кабинет: список актов; /<id> — печатная страница акта
CURRENT = "27.10.2026"                   # = license.TERMS_VERSION программы = termeni.html (test_terms)
SRC_TRIAL, SRC_VERIFY, SRC_PAY, SRC_PROGRAM = "trial", "verify", "pay", "program"
SOURCES = (SRC_TRIAL, SRC_VERIFY, SRC_PAY, SRC_PROGRAM)
SOURCE_RO = {SRC_TRIAL: "cererea de perioadă de probă, din program",
             SRC_VERIFY: "activarea programului pe un calculator nou",
             SRC_PAY: "pagina de plată", SRC_PROGRAM: "din program, la actualizarea termenilor"}
SOURCE_RU = {SRC_TRIAL: "заявка на пробный из программы", SRC_VERIFY: "активация кодом на новом ПК",
             SRC_PAY: "страница оплаты", SRC_PROGRAM: "из программы (новая версия условий)"}
ACTOR_MAX = 60
VERSION_RE = re.compile(r"^(\d{2})\.(\d{2})\.(\d{4})$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
BODY_MAX = 4 * 1024
esc = html.escape


def clean_version(raw) -> str:
    """Версия условий — дата dd.mm.yyyy, существующая в календаре; иначе ''."""
    s = str(raw or "").strip()
    m = VERSION_RE.match(s)
    if not m:
        return ""
    try:
        date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return ""
    return s


def clean_actor(raw) -> str:
    return " ".join(str(raw or "").split())[:ACTOR_MAX]


def version_key(v: str) -> tuple:
    """Порядок версий — по дате (год, месяц, день); пусто или мусор — раньше всех."""
    m = VERSION_RE.match(v or "")
    return (int(m.group(3)), int(m.group(2)), int(m.group(1))) if m else (0, 0, 0)


def record(con: sqlite3.Connection, clinic_id: str, version: str, actor: str, source: str, ip: str,
           ident: dict | None = None, sha256: str = "", who: str = "program") -> sqlite3.Row:
    """Строка акта. `ident` — личность программы из заголовков (fleet.from_request): компьютер и
    версия; у браузера (страница оплаты) её нет. Строка журнала — рядом."""
    if source not in SOURCES:
        raise ValueError(source)
    aid = "a_" + secrets.token_hex(8)
    ident = ident or {}
    con.execute("INSERT INTO terms_acceptances(id, clinic_id, version, actor, at, ip, device, app_version, "
                "source, terms_sha256) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (aid, clinic_id, version, actor[:ACTOR_MAX], db.now_iso(), ip[:64], (ident.get("id") or "")[:32],
                 (ident.get("version") or "")[:32], source, sha256 if SHA_RE.match(sha256 or "") else ""))
    db.audit(con, who, "terms_accept", clinic_id, f"условия {version}, {actor[:ACTOR_MAX] or '—'}, "
                                                   f"{SOURCE_RU[source]}, {ip}")
    return get(con, clinic_id, aid)


def get(con: sqlite3.Connection, clinic_id: str, aid: str) -> sqlite3.Row | None:
    """Акт СВОЕЙ клиники или None: чужой id не отличается от несуществующего."""
    if not aid or len(aid) > 40:
        return None
    return con.execute("SELECT * FROM terms_acceptances WHERE id=? AND clinic_id=?", (aid, clinic_id)).fetchone()


def of_clinic(con: sqlite3.Connection, clinic_id: str) -> list:
    return con.execute("SELECT * FROM terms_acceptances WHERE clinic_id=? ORDER BY at DESC, rowid DESC",
                       (clinic_id,)).fetchall()


def latest(con: sqlite3.Connection, clinic_id: str) -> str:
    """Старшая принятая версия клиники (по дате версии, не по времени акта) или ''."""
    rows = con.execute("SELECT DISTINCT version FROM terms_acceptances WHERE clinic_id=?", (clinic_id,)).fetchall()
    return max((r["version"] for r in rows), key=version_key, default="")


def headers(con: sqlite3.Connection, clinic: sqlite3.Row) -> dict:
    """Заголовок ответа /v1/license (200 и 204): без акта — ничего (программа читает «не знаем»)."""
    v = latest(con, clinic["id"])
    return {H_TERMS: v} if v else {}


def view(row: sqlite3.Row) -> dict:
    """Квитанция программе: что положить в `contract\\acceptare-<версия>.json`."""
    return {"id": row["id"], "version": row["version"], "at": row["at"]}


def from_body(body: dict) -> tuple[str, str]:
    """(версия, актёр) из тела запроса программы; версии нет или она не дата — ('', актёр)."""
    return clean_version(body.get("terms")), clean_actor(body.get("actor"))


# ---------- разметка: кабинет (RO) и админка (RU) ----------


def _dt(s: str) -> str:
    """2026-10-29T12:03:44Z → 29.10.2026 12:03 (UTC)."""
    if not s or len(s) < 16:
        return "—"
    return f"{s[8:10]}.{s[5:7]}.{s[0:4]} {s[11:16]} (UTC)"


def _ro(s: str) -> str:
    return f"{s[8:10]}.{s[5:7]}.{s[0:4]}" if s and len(s) >= 10 else "—"


def cont_fragment(con: sqlite3.Connection, clinic: sqlite3.Row, q: str = "") -> str:
    """Блок кабинета «Acceptarea Termenilor și condițiilor»: таблица актов клиники со ссылкой на
    печатную страницу каждого; без актов (активация до 29.10) — слова и совет принять текущую
    версию из программы (баннер программы). `q` — `?c=<id>` у записи с несколькими клиниками."""
    rows = of_clinic(con, clinic["id"])
    site = config.SITE_URL.rstrip("/")
    head = (f"<p class='muted' style='margin:0 0 10px'>Contractul dintre clinică și DentPilot sunt "
            f"<a href='{esc(site)}/termeni.html' target='_blank' rel='noopener'>Termenii și condițiile</a> "
            f"publicate pe site, acceptate la activarea programului. Fiecare acceptare este un act cu versiunea "
            f"termenilor, data, ora și persoana care a acceptat — exemplarul clinicii.</p>")
    if not rows:
        return head + (f"<p><b>Acceptarea a fost înregistrată local, la activarea programului</b> (înainte de "
                       f"29.10.2026 actul nu ajungea pe server). Pentru un act și aici: deschideți "
                       f"<b>Setări › Licența</b> în program și acceptați versiunea curentă a termenilor "
                       f"({esc(CURRENT)}).</p>")
    trs = "".join(
        f"<tr><td><b>{esc(r['version'])}</b></td><td>{esc(r['actor'] or '—')}</td><td>{esc(_dt(r['at']))}</td>"
        f"<td>{esc(SOURCE_RO.get(r['source'], r['source']))}</td>"
        f"<td><a href='{PAGE}/{esc(r['id'])}{esc(q)}'>Actul</a></td></tr>" for r in rows)
    return (head + f"<div class='tscroll'><table><tr><th>Versiunea termenilor</th><th>Acceptat de</th>"
                   f"<th>Data și ora</th><th>Unde</th><th></th></tr>{trs}</table></div>")


def cont_list_page(acc, clinic: sqlite3.Row, con: sqlite3.Connection, msg: str = "", multi: bool = False) -> str:
    """Страница кабинета `/cont/acceptari`: тот же блок страницей (пока раздел «Documente» не сшит)."""
    from . import views   # разметка кабинета; views сам terms не импортирует
    q = f"?c={clinic['id']}" if multi else ""
    inner = (f"<div class='card'>{views._chead('file', 'Acceptarea Termenilor și condițiilor', esc(clinic['name']))}"
             f"{cont_fragment(con, clinic, q)}</div>")
    return views._cont_shell("Acceptarea termenilor", inner, acc, msg, eyebrow="Contul clinicii · documente",
                             lead=f"<a href='/cont{q}'>Înapoi la clinicile mele</a>")


_PRINT_CSS = ("<style>.act{max-width:720px}.act h2{font-size:20px;margin:0 0 4px}.act .sub{color:var(--muted);margin:0 0 18px}"
              ".act dl{display:grid;grid-template-columns:max-content 1fr;gap:8px 18px;margin:0 0 18px}"
              ".act dt{color:var(--muted)}.act dd{margin:0;font-weight:600}.act .mono{font-family:ui-monospace,Consolas,monospace;font-size:13px}"
              ".act .sign{margin-top:26px;padding-top:14px;border-top:1px solid var(--line);color:var(--muted);font-size:13px}"
              "@media print{.top,.foot,.eyebrow,.lead,.noprint{display:none!important}body{background:#fff}"
              ".wrap{padding:0;max-width:none}.card{box-shadow:none;border:0;padding:0}@page{size:A4;margin:18mm}}</style>")


def cont_act_page(acc, clinic: sqlite3.Row, row: sqlite3.Row, multi: bool = False) -> str:
    """Печатная страница акта (A4): furnizor, clinica, versiunea, data, persoana, sursa, identificatorul.
    Экземпляр клиники к общему договору; подписи сторон не требует — подпись электронная простая."""
    from . import receipts, views
    q = f"?c={clinic['id']}" if multi else ""
    b = config.BANK
    seller = ", ".join(x for x in (b.get("beneficiary"), receipts.SELLER_FORM) if x)
    seller_more = " · ".join(x for x in ((f"IDNO {b['code']}" if b.get("code") else ""), config.SELLER_ADDRESS,
                                         config.SUPPORT_EMAIL) if x)
    clinic_more = " · ".join(x for x in ((f"IDNO {clinic['idno']}" if clinic["idno"] else ""), clinic["address"],
                                         clinic["email"]) if x)
    site = config.SITE_URL.rstrip("/")
    body = (f"<div class='card act'><h2>Act de acceptare a Termenilor și condițiilor</h2>"
            f"<p class='sub'>DentPilot — program pentru evidența clinicii stomatologice · nr. "
            f"<span class='mono'>{esc(row['id'])}</span></p>"
            f"<dl><dt>Furnizor</dt><dd>{esc(seller or 'DentPilot')}<br><span class='mono'>{esc(seller_more)}</span></dd>"
            f"<dt>Clinica</dt><dd>{esc(clinic['name'])}<br><span class='mono'>{esc(clinic_more)}</span></dd>"
            f"<dt>Documentul acceptat</dt><dd>Termenii și condițiile DentPilot, versiunea din "
            f"<b>{esc(row['version'])}</b><br><span class='mono'>{esc(site)}/termeni.html</span></dd>"
            f"<dt>Data și ora acceptării</dt><dd>{esc(_dt(row['at']))}</dd>"
            f"<dt>Acceptat de</dt><dd>{esc(row['actor'] or '—')}</dd>"
            f"<dt>Modul acceptării</dt><dd>bifă „Am citit și accept Termenii și condițiile” — "
            f"{esc(SOURCE_RO.get(row['source'], row['source']))}</dd>"
            f"<dt>Identificatorul actului</dt><dd class='mono'>{esc(row['id'])}</dd></dl>"
            f"<p class='sign'>Acceptarea prin bifă este o semnătură electronică simplă (Legea nr. 124/2022). "
            f"Actul este păstrat de furnizor pe serverul cloud.dentpilot.md și, ca chitanță, de program în "
            f"folderul de date al clinicii. Contractul și acordul de prelucrare, semnate de furnizor, se găsesc "
            f"în contul clinicii, secțiunea «Documente».</p>"
            f"<p class='noprint' style='margin:18px 0 0'><button class='primary' onclick='window.print()'>Tipărește</button> "
            f"<a class='btn second' href='{PAGE}{esc(q)}' style='margin-left:8px'>Toate actele</a></p></div>")
    return views._cont_shell("Act de acceptare", _PRINT_CSS + body, acc, eyebrow="Contul clinicii · documente",
                             lead=f"<a href='{PAGE}{esc(q)}'>Înapoi la acte</a>")


def admin_fragment(rows: list) -> str:
    """Карточка клиники › «Лицензия»: акты акцепта (версия, кто, когда, откуда, ПК и программа)."""
    trs = "".join(
        f"<tr><td><b>{esc(r['version'])}</b></td><td>{esc(r['actor'] or '—')}</td>"
        f"<td class='mono'>{esc(r['at'][:16].replace('T', ' '))}</td><td>{esc(SOURCE_RU.get(r['source'], r['source']))}</td>"
        f"<td class='mono'>{esc(r['device'] or '—')}{(' · ' + esc(r['app_version'])) if r['app_version'] else ''}</td>"
        f"<td class='mono'>{esc(r['ip'] or '—')}</td></tr>" for r in rows
    ) or "<tr><td colspan='6' class='muted'>Актов нет: активация до 29.10 или программа старше 2.4 — акцепт записан только у клиники</td></tr>"
    return (f"<div class='card'><div class='chead'><div><h2 style='margin:0'>Акты акцепта условий</h2>"
            f"<p class='muted' style='margin:2px 0 0'>кто и когда принял какую версию Termeni și condiții; "
            f"текущая версия {esc(CURRENT)}</p></div></div>"
            f"<table><tr><th>Версия</th><th>Кто</th><th>Когда (UTC)</th><th>Откуда</th><th>ПК · программа</th>"
            f"<th>Адрес</th></tr>{trs}</table></div>")
