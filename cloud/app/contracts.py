"""Документы поставщика в кабинете клиники (29.10.2026): договор лицензии, соглашение об обработке
данных, декларация по закону 195 — и экземпляр, подписанный клиникой.

Слово Олега 29.10: «не слишком сложно — чтобы в кабинете клиники уже были бумаги, подписанные мною».
Поэтому договор устроен как декларация, а не как документ на каждую клинику: ОДИН PDF на версию
текста, подписанный Олегом вне системы (КЭП MoldSign) и положенный на сервер (`DP_CONTRACT`,
`DP_DPA`, как `DP_DECLARATION`). Клиника в тексте не именуется — она «clinica care a acceptat
termenii», и доказательством акцепта служит акт (сессия terms-evidence: `terms.py`, таблица
`terms_acceptances`, схема 19). Версия документа — дата в имени файла (`contract-licenta-2026-10-29.pdf`),
иначе дата изменения файла; файл читается при каждом запросе, как декларация: Олег кладёт новый
PDF — перезапуск не нужен.

Единственное действие клиники — «Încarcă exemplarul semnat de clinică»: тот же PDF, подписанный
её КЭП или распечатанный, подписанный и отсканированный. Хранится файлом
`folder()/<clinic_id>/<id>.pdf`, в базе — строка `clinic_contracts` (документ, версия, имя, sha256).
Проверяется сигнатура %PDF- и потолок MAX_BYTES; содержимое подписи сервер не проверяет — это
документ сторон. Без состояний, без подписи поставщика в ответ: подпись Олега уже стоит на самом
документе. Строки не удаляются — это бухгалтерская бумага клиники.

⛔ Файлы — на диске, не в базе (в отличие от заявления SMS): подписанный КЭП PDF весит мегабайты,
а копия базы — килобайты; папку `contracts` увозит `deploy/pull-backups.ps1` вместе с базой,
`tools check` предупреждает, если папка недоступна для записи.
"""
from __future__ import annotations

import hashlib
import logging
import pathlib
import re
import sqlite3
from datetime import datetime, timezone

from . import config, db, sms

log = logging.getLogger("cloud.contracts")

MAX_BYTES = 10 * 1024 * 1024
CONTRACT, DPA, DECLARATION = "contract", "dpa", "declaratie"
# документы раздела по порядку показа; env — имя переменной, по которой находится файл (значение
# читается из config при каждом запросе — тесты и Олег меняют его без перезапуска)
DOCS = {
    CONTRACT: {"title": "Contract de licență DentPilot", "env": "CONTRACT", "file": "Contract-licenta-DentPilot",
               "what": "condițiile de utilizare a programului, semnat de furnizor"},
    DPA: {"title": "Acord de prelucrare a datelor", "env": "DPA", "file": "Acord-prelucrare-date-DentPilot",
          "what": "ce date ajung la furnizor și în ce scop (Legea 195/2024), semnat de furnizor"},
    DECLARATION: {"title": "Declarația furnizorului (Legea 195/2024)", "env": "DECLARATION",
                  "file": "Declaratie-furnizor-DentPilot-Legea-195",
                  "what": "datele pacienților rămân pe calculatorul clinicii, semnată de furnizor"},
}
UPLOAD_DOCS = (CONTRACT, DPA)        # что клиника может загрузить со своей подписью
_DATE = (re.compile(r"(20\d{2})-(\d{2})-(\d{2})"), re.compile(r"(\d{2})\.(\d{2})\.(20\d{2})"),
         re.compile(r"(20\d{2})(\d{2})(\d{2})"))


# ---------- документы поставщика ----------


def path(doc: str) -> pathlib.Path | None:
    raw = getattr(config, DOCS[doc]["env"], "") if doc in DOCS else ""
    return pathlib.Path(raw) if raw else None


def version(doc: str) -> str:
    """Версия документа словами клиники: dd.mm.yyyy из имени файла (2026-10-29, 29.10.2026 или
    20261029), иначе день изменения файла по Кишинёву; '' — файла нет."""
    return version_of(path(doc))


def version_of(p: pathlib.Path | None) -> str:
    if p is None:
        return ""
    name = p.name
    m = _DATE[0].search(name) or _DATE[2].search(name)
    if m:
        return f"{m.group(3)}.{m.group(2)}.{m.group(1)}"
    m = _DATE[1].search(name)
    if m:
        return m.group(0)
    try:
        at = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return ""
    return sms.local(at).strftime("%d.%m.%Y")


def provider_pdf(doc: str) -> bytes | None:
    """Подписанный поставщиком PDF — (байты) или None: не настроен, не читается, не PDF. Читается
    при каждом запросе, как mail.declaration: новый файл Олега не ждёт перезапуска."""
    p = path(doc)
    if p is None:
        return None
    try:
        data = p.read_bytes()
    except OSError as e:
        log.warning("документ %s (%s) не прочитан: %r", doc, p, e)
        return None
    if not data.startswith(b"%PDF-"):
        log.warning("документ %s (%s) — не PDF", doc, p)
        return None
    return data


def filename(doc: str) -> str:
    """Имя для «Сохранить как» — без диакритики, с версией."""
    v = version(doc).replace(".", "-")
    return f"{DOCS[doc]['file']}{('-' + v) if v else ''}.pdf"


def status(doc: str) -> dict:
    """Строка раздела: {key, title, what, version, ok, filename}; ok — файл есть и это PDF."""
    return {"key": doc, "title": DOCS[doc]["title"], "what": DOCS[doc]["what"], "version": version(doc),
            "ok": provider_pdf(doc) is not None, "filename": filename(doc)}


def statuses() -> list[dict]:
    return [status(d) for d in DOCS]


def check_lines() -> list[tuple[bool, str]]:
    """Для `tools check`: (всё ли в порядке, строка) по договору и соглашению — как у декларации."""
    out = []
    for doc in UPLOAD_DOCS:
        var = "DP_" + DOCS[doc]["env"]
        p = path(doc)
        if p is None:
            out.append((False, f"{var} пуст: в кабинете «{DOCS[doc]['title']}» показан как ещё не выложенный"))
        elif provider_pdf(doc) is None:
            out.append((False, f"{var}={p}: файла нет или это не PDF — в кабинете документ ещё не выложен"))
        else:
            out.append((True, f"{DOCS[doc]['title']} {version(doc)}: {p} — в кабинете клиник"))
    return out


# ---------- экземпляр клиники ----------


def folder() -> pathlib.Path:
    """Папка экземпляров клиник — рядом с базой (/srv/dentpilot/data/contracts на боевом)."""
    return config.DB_PATH.parent / "contracts"


def folder_ok() -> str:
    """'' — папка есть и пишется; иначе почему нет (для `tools check`)."""
    try:
        folder().mkdir(parents=True, exist_ok=True)
        probe = folder() / ".dp_write_probe"
        probe.write_bytes(b"1")
        probe.unlink()
        return ""
    except OSError as e:
        return repr(e)


def is_pdf(body: bytes) -> bool:
    """PDF по сигнатуре, не по имени (спецификация разрешает мусор до неё в первом КБ)."""
    return b"%PDF-" in body[:1024]


def file_path(row: sqlite3.Row) -> pathlib.Path:
    return folder() / row["clinic_id"] / row["file"]


def attach(con: sqlite3.Connection, clinic_id: str, doc: str, body: bytes, who: str) -> str:
    """Экземпляр, подписанный клиникой → строка clinic_contracts и файл. '' или код отказа
    (doc_kind, doc_empty, doc_big, doc_pdf). Повтор — новая строка, прежняя остаётся."""
    if doc not in UPLOAD_DOCS:
        return "doc_kind"
    if not body:
        return "doc_empty"
    if len(body) > MAX_BYTES:
        return "doc_big"
    if not is_pdf(body):
        return "doc_pdf"
    now = db.now_iso()
    ver = version(doc)
    cur = con.execute("INSERT INTO clinic_contracts(clinic_id, doc, version, file, sha256, size, uploaded_at, who) "
                      "VALUES(?,?,?,?,?,?,?,?)",
                      (clinic_id, doc, ver, "", hashlib.sha256(body).hexdigest(), len(body), now, who[:120]))
    name = f"{cur.lastrowid}.pdf"
    con.execute("UPDATE clinic_contracts SET file=? WHERE id=?", (name, cur.lastrowid))
    p = folder() / clinic_id / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(body)          # OSError — наружу: транзакция откатится, строки без файла не будет
    db.audit(con, who, "doc_signed", clinic_id,
             f"{DOCS[doc]['title']} v{ver or '—'}: экземпляр клиники загружен, {max(1, len(body) // 1024)} КБ, {name}")
    return ""


def get(con: sqlite3.Connection, row_id: int) -> sqlite3.Row | None:
    return con.execute("SELECT * FROM clinic_contracts WHERE id=?", (row_id,)).fetchone()


def of_clinic(con: sqlite3.Connection, clinic_id: str) -> list:
    return con.execute("SELECT * FROM clinic_contracts WHERE clinic_id=? ORDER BY id DESC", (clinic_id,)).fetchall()


def read_file(row: sqlite3.Row) -> bytes | None:
    """Байты экземпляра клиники или None — файла на диске нет (переезд без папки contracts)."""
    try:
        return file_path(row).read_bytes()
    except OSError as e:
        log.warning("экземпляр клиники %s не прочитан: %r", row["id"], e)
        return None


def clinic_filename(c: sqlite3.Row, row: sqlite3.Row) -> str:
    """Имя экземпляра клиники для скачивания — без диакритики."""
    who = re.sub(r"[^A-Za-z0-9]+", "", c["idno"] or c["id"]) or "clinica"
    return f"{DOCS[row['doc']]['file']}-semnat-{who}-{row['id']}.pdf"


def terms_fragment(con: sqlite3.Connection, c: sqlite3.Row, q: str = "") -> str:
    """Акты акцепта условий в том же разделе — фрагмент сессии terms-evidence (`terms.cont_fragment`),
    когда модуль есть; иначе '' (кабинет показывает общую строку). `q` — `?c=<id>` у записи с несколькими клиниками."""
    try:
        from . import terms  # noqa: PLC0415 — модуль другой сессии, его может ещё не быть
    except ImportError:
        return ""
    fn = getattr(terms, "cont_fragment", None)
    return fn(con, c, q) if callable(fn) else ""
