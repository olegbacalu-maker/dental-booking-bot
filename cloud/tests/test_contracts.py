"""Документы поставщика в кабинете и экземпляр клиники (contracts.py, 29.10.2026).

Договор лицензии и соглашение об обработке — общие PDF, подписанные Олегом один раз на версию
(DP_CONTRACT, DP_DPA, как DP_DECLARATION): кабинет отдаёт их любому вошедшему, версия — дата из
имени файла. Клиника может загрузить экземпляр со своей подписью: файл на диске рядом с базой,
строка clinic_contracts; отдаётся только своей клинике и админке. Здесь: правила версии и имён,
раздел и три PDF, отказы загрузки (не PDF, пусто, велико, не тот документ), чужая клиника — 404,
админка, строка в письме о лицензии, `check` с файлами и без, вывоз папки.
"""
import pathlib
import re
import sqlite3
import sys
import tempfile
import time

from harness import CLOUD, ROOT, Client, Result, Server, cid_from
from test_deploy import _tools
from test_receipts import _letters, _raw
from test_sms_paper import _cabinet

sys.path.insert(0, str(CLOUD))
from app import contracts, mail, pdf  # noqa: E402 — чистые функции сервера

DEPLOY = CLOUD / "deploy"


def _q(s: Server, sql: str, *args):
    con = sqlite3.connect(s.dir / "cloud.db")
    try:
        return con.execute(sql, args).fetchall()
    finally:
        con.close()


def _one(s: Server, sql: str, *args):
    rows = _q(s, sql, *args)
    return rows[0][0] if rows else None


def _msg(reply) -> str:
    m = re.search(r"msg=([a-z_]+)", reply.location or "")
    return m.group(1) if m else f"{reply.status} {reply.location}"


def _pdf(title: str) -> bytes:
    doc = pdf.Document(title)
    doc.text(48, 64, title, 14, bold=True)
    return doc.build()


def _multipart(data: bytes, doc: str, name: str = "semnat.pdf") -> tuple[bytes, str]:
    """Форма раздела: поле `doc` и файл — как её шлёт браузер."""
    b = "----dpDocBoundary29x"
    body = (f"--{b}\r\nContent-Disposition: form-data; name=\"doc\"\r\n\r\n{doc}\r\n"
            f"--{b}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{name}\"\r\n"
            f"Content-Type: application/pdf\r\n\r\n").encode() + data + f"\r\n--{b}--\r\n".encode()
    return body, f"multipart/form-data; boundary={b}"


def _upload(c: Client, data: bytes, doc: str = "contract", q: str = ""):
    body, ctype = _multipart(data, doc)
    return c._do("/cont/documente/incarca" + q, body, {"Content-Type": ctype})


def _clinic(admin: Client, name: str, email: str, idno: str = "1234567890123") -> str:
    return cid_from(admin.post("/admin/clinics", name=name, idno=idno, contact_name="Ion", email=email,
                               phone="").location)


def suite_rules(res: Result) -> None:
    """Без сервера: версия из имени файла, имена для скачивания, письмо, вывоз, пример окружения."""
    P = pathlib.Path
    res.check("версия из имени: ГГГГ-ММ-ДД → дд.мм.гггг", contracts.version_of(P("x/contract-licenta-2026-10-29.pdf")),
              "29.10.2026")
    res.check("версия из имени: дд.мм.гггг как есть", contracts.version_of(P("acord 29.10.2026.pdf")), "29.10.2026")
    res.check("версия из имени: ГГГГММДД", contracts.version_of(P("dpa_20261029_semnat.pdf")), "29.10.2026")
    res.check("файла нет и даты в имени нет — пусто", contracts.version_of(P("nu-exista/contract.pdf")), "")
    with tempfile.TemporaryDirectory() as d:
        f = P(d) / "contract.pdf"
        f.write_bytes(b"%PDF-1.4\n")
        res.ok("без даты в имени — день изменения файла, дд.мм.гггг",
               re.fullmatch(r"\d{2}\.\d{2}\.20\d{2}", contracts.version_of(f)) is not None, contracts.version_of(f))
    res.check("три документа раздела по порядку: договор, соглашение, декларация",
              list(contracts.DOCS), [contracts.CONTRACT, contracts.DPA, contracts.DECLARATION])
    res.check("загрузить со своей подписью можно договор и соглашение, декларацию — нет",
              contracts.UPLOAD_DOCS, (contracts.CONTRACT, contracts.DPA))
    res.ok("PDF — по сигнатуре в первом КБ, не по имени",
           contracts.is_pdf(b"%PDF-1.7 x") and contracts.is_pdf(b"\xef\xbb\xbf junk %PDF-1.4")
           and not contracts.is_pdf(b"<html>%PDF") and not contracts.is_pdf(b"PK\x03\x04"))
    # строка о документах — только когда договор на сервере есть (координатор 29.10): письмо не обещает
    # документ, которого в кабинете нет; config читается при каждом письме — подменяется прямо здесь
    with tempfile.TemporaryDirectory() as d:
        f = pathlib.Path(d) / "contract-2026-10-29.pdf"
        f.write_bytes(b"%PDF-1.4\n")
        keep = mail.config.CONTRACT
        try:
            mail.config.CONTRACT = str(f)
            with_doc = mail.license_letter("C", "2026-12-01", "standard")[1]
            mail.config.CONTRACT = ""
            without = mail.license_letter("C", "2026-12-01", "standard")[1]
            mail.config.CONTRACT = str(pathlib.Path(d) / "nu-exista.pdf")
            gone = mail.license_letter("C", "2026-12-01", "standard")[1]
        finally:
            mail.config.CONTRACT = keep
    res.ok("письмо о лицензии ведёт в раздел документов, когда договор на сервере есть",
           mail.DOCUMENTS_URL.endswith("/cont/documente") and mail.DOCUMENTS_URL in with_doc
           and with_doc.index(mail.DOCUMENTS_URL) < with_doc.index(mail.FOOTER))
    res.ok("без DP_CONTRACT или без файла — строки о документах нет, подвал на месте",
           mail.DOCUMENTS_URL not in without and mail.DOCUMENTS_URL not in gone
           and "\n\n\n" not in without and without.endswith(mail.FOOTER))
    res.ok("закон о персональных данных в описании соглашения — 195/2024, не 133/2011",
           "195/2024" in contracts.DOCS[contracts.DPA]["what"] and "133/2011" not in contracts.DOCS[contracts.DPA]["what"])
    res.ok("письмо без DP_DECLARATION не называет декларацию и после строки о документах",
           "Declarația furnizorului" not in mail.license_letter("C", "2026-12-01", "standard")[1])
    pull = (DEPLOY / "pull-backups.ps1").read_bytes()
    res.ok("pull-backups.ps1: папка contracts вывозится вместе с базой, BOM на месте",
           pull.startswith(b"\xef\xbb\xbf") and b"ContractsDir" in pull and b"/srv/dentpilot/data/contracts" in pull
           and b'"${Server}:${ContractsDir}/."' in pull)
    example = (DEPLOY / "cloud.env.example").read_text(encoding="utf-8")
    res.ok("cloud.env.example: DP_CONTRACT и DP_DPA с датой в имени файла",
           re.search(r"^DP_CONTRACT=.*20\d{2}-\d{2}-\d{2}\.pdf$", example, re.M) is not None
           and re.search(r"^DP_DPA=.*20\d{2}-\d{2}-\d{2}\.pdf$", example, re.M) is not None)
    res.ok("имена файлов без диакритики",
           all(re.fullmatch(r"[A-Za-z0-9.-]+", contracts.DOCS[d]["file"] + ".pdf") for d in contracts.DOCS))
    res.ok("экземпляры клиник — папка contracts рядом с базой (её увозит pull-backups.ps1)",
           contracts.folder().name == "contracts")


def suite_cabinet(res: Result) -> None:
    """С файлами: раздел, три PDF, загрузка экземпляра, своя/чужая клиника, админка, письмо, check."""
    with tempfile.TemporaryDirectory(prefix="dp_docs_") as d:
        docs = pathlib.Path(d)
        files = {"contract": docs / "contract-licenta-2026-10-29.pdf", "dpa": docs / "acord-prelucrare-29.10.2026.pdf",
                 "declaratie": docs / "declaratie-195.pdf"}
        data = {k: _pdf(k.upper()) for k in files}
        for k, p in files.items():
            p.write_bytes(data[k])
        env = {"DP_CONTRACT": str(files["contract"]), "DP_DPA": str(files["dpa"]),
               "DP_DECLARATION": str(files["declaratie"])}
        with Server(env=env) as s:
            admin = Client(s.url).login()
            cid = _clinic(admin, "Clinica Docs", "docs@example.md")
            cid2 = _clinic(admin, "Clinica Alta", "alta@example.md", idno="2234567890123")
            res.check("миграция 20: таблица clinic_contracts",
                      _one(s, "SELECT count(*) FROM sqlite_master WHERE name='clinic_contracts'"), 1)
            anon = Client(s.url)
            res.check("без входа: раздел — на вход", (anon.get("/cont/documente").status, anon.get("/cont/documente").location),
                      (303, "/cont/login"))
            res.check("без входа: PDF поставщика — на вход", anon.get("/cont/documente/contract.pdf").location, "/cont/login")
            up = _upload(anon, data["contract"])
            res.check("без входа: загрузка — на вход, тело не читается", (up.status, up.location), (303, "/cont/login"))

            cab = _cabinet(s, "docs@example.md")
            home = cab.get("/cont").body
            res.ok("дашборд: карточка «Documente» с тремя PDF и версиями",
                   "id='documente'" in home and "/cont/documente/contract.pdf" in home
                   and "/cont/documente/dpa.pdf" in home and "/cont/documente/declaratie.pdf" in home
                   and "versiunea 29.10.2026" in home and "href='/cont/documente'" in home, home[-4000:])
            page = cab.get("/cont/documente").body
            res.ok("раздел: три документа, акцепт — общая строка (модуля terms нет), форма загрузки",
                   all(contracts.DOCS[k]["title"] in page for k in contracts.DOCS)
                   and "Acceptarea termenilor" in page and "înregistrată la activarea programului" in page
                   and "action='/cont/documente/incarca'" in page and "enctype='multipart/form-data'" in page
                   and "<option value='contract'>" in page and "<option value='dpa'>" in page
                   and "<option value='declaratie'>" not in page, page[-5000:])
            res.ok("раздел: ещё нет загруженных — таблицы нет", "/clinica.pdf" not in page)
            for k in ("contract", "dpa", "declaratie"):
                st, h, body = _raw(cab, f"/cont/documente/{k}.pdf")
                res.ok(f"PDF поставщика «{k}»: 200, байт в байт, в окно, имя с версией",
                       st == 200 and body == data[k] and h.get("content-type") == "application/pdf"
                       and h.get("content-disposition", "").startswith("inline;")
                       and (k == "declaratie" or "29-10-2026" in h.get("content-disposition", "")),
                       f"{st} {h.get('content-disposition')}")
            res.check("неизвестный документ — 404", _raw(cab, "/cont/documente/altceva.pdf")[0], 404)

            res.check("не PDF — doc_pdf", _msg(_upload(cab, b"<html>semnat</html>")), "doc_pdf")
            res.check("пустой файл — doc_empty", _msg(_upload(cab, b"")), "doc_empty")
            res.check("не тот документ — doc_kind", _msg(_upload(cab, data["contract"], doc="declaratie")), "doc_kind")
            res.check("больше потолка — doc_big", _msg(_upload(cab, b"%PDF-" + b"0" * contracts.MAX_BYTES)), "doc_big")
            res.check("пока ни строки", _one(s, "SELECT count(*) FROM clinic_contracts"), 0)
            signed = data["contract"] + b"\n% semnat de clinica\n"
            res.check("подписанный договор принят — doc_ok", _msg(_upload(cab, signed)), "doc_ok")
            row = _q(s, "SELECT id, clinic_id, doc, version, file, sha256, size, who FROM clinic_contracts")[0]
            import hashlib
            res.check("строка: клиника, документ, версия из имени файла поставщика, имя файла, sha256, размер, кто",
                      tuple(row), (1, cid, "contract", "29.10.2026", "1.pdf", hashlib.sha256(signed).hexdigest(),
                                   len(signed), "docs@example.md"))
            on_disk = s.dir / "contracts" / cid / "1.pdf"
            res.ok("файл — на диске рядом с базой, data/contracts/<clinic>/<id>.pdf, байт в байт",
                   on_disk.exists() and on_disk.read_bytes() == signed, str(on_disk))
            res.check("журнал: doc_signed", _one(s, "SELECT count(*) FROM audit WHERE what='doc_signed' AND clinic_id=?", cid), 1)
            res.check("и соглашение принято — вторая строка", _msg(_upload(cab, data["dpa"] + b"\n%x", doc="dpa")), "doc_ok")
            res.check("строки не перезаписываются: две", _one(s, "SELECT count(*) FROM clinic_contracts WHERE clinic_id=?", cid), 2)
            page = cab.get("/cont/documente").body
            res.ok("раздел: таблица загруженных с ссылками на оба экземпляра",
                   "/cont/documente/1/clinica.pdf" in page and "/cont/documente/2/clinica.pdf" in page
                   and page.index("/cont/documente/2/clinica.pdf") < page.index("/cont/documente/1/clinica.pdf"))
            st, h, body = _raw(cab, "/cont/documente/1/clinica.pdf")
            res.ok("свой экземпляр: 200, вложением с nosniff, байт в байт",
                   st == 200 and body == signed and h.get("content-disposition", "").startswith("attachment;")
                   and "semnat-1234567890123-1.pdf" in h.get("content-disposition", "")
                   and h.get("x-content-type-options") == "nosniff", f"{st} {h}")
            res.check("несуществующая строка — 404", _raw(cab, "/cont/documente/99/clinica.pdf")[0], 404)

            cab2 = _cabinet(s, "alta@example.md")
            res.check("чужая клиника: экземпляр — 404", _raw(cab2, "/cont/documente/1/clinica.pdf")[0], 404)
            res.ok("чужая клиника: в её разделе загруженных нет, PDF поставщика — есть",
                   "/clinica.pdf" not in cab2.get("/cont/documente").body
                   and _raw(cab2, "/cont/documente/contract.pdf")[0] == 200)

            card = admin.get(f"/admin/clinics/{cid}").body
            lic = card[card.index("data-pane='lic'"):card.index("data-pane='sms'")]
            res.ok("админка: во вкладке «Лицензия» блок «Документы» — версии выложенных и ссылки на экземпляры",
                   "Документы" in lic and "версия 29.10.2026" in lic
                   and f"/admin/clinics/{cid}/documente/1.pdf" in lic and f"/admin/clinics/{cid}/documente/2.pdf" in lic
                   and "не выложен" not in lic, lic[-3000:])
            st, h, body = _raw(admin, f"/admin/clinics/{cid}/documente/1.pdf")
            res.ok("админка: экземпляр клиники вложением с nosniff",
                   st == 200 and body == signed and h.get("content-disposition", "").startswith("attachment;")
                   and h.get("x-content-type-options") == "nosniff")
            res.check("админка: строка не этой клиники — 404", _raw(admin, f"/admin/clinics/{cid2}/documente/1.pdf")[0], 404)
            res.check("админка без входа — на вход", anon.get(f"/admin/clinics/{cid}/documente/1.pdf").status, 303)
            res.ok("журнал словами: doc_signed в карточке", "экземпляр документа, подписанный клиникой" in card)

            before = len(_letters(s))
            admin.post(f"/admin/clinics/{cid}/issue", kind="trial", send="1")
            letters = _letters(s)
            res.ok("письмо о лицензии: строка о документах в кабинете, декларация во вложении",
                   len(letters) == before + 1 and mail.DOCUMENTS_URL in letters[-1][2]
                   and mail.DECLARATION_NAME in letters[-1][3], letters[-1][2] if letters else "")

            rc, out = _tools(s, "check")
            res.ok("check с файлами: договор и соглашение названы с версией, папка экземпляров пишется",
                   "Contract de licență DentPilot 29.10.2026" in out and "Acord de prelucrare a datelor 29.10.2026" in out
                   and "папка экземпляров клиник" in out and "пишется" in out and "DP_CONTRACT пуст" not in out, out)

            on_disk.unlink()
            res.check("файл с диска пропал — 404, а не 500", _raw(cab, "/cont/documente/1/clinica.pdf")[0], 404)
            files["contract"].write_bytes(b"not a pdf at all")
            res.check("файл поставщика подменён не-PDF — 404 (без перезапуска)", _raw(cab, "/cont/documente/contract.pdf")[0], 404)


def suite_without(res: Result) -> None:
    """Без DP_CONTRACT / DP_DPA: раздел говорит «ещё не выложен», PDF — 404, check предупреждает."""
    with Server() as s:
        admin = Client(s.url).login()
        cid = _clinic(admin, "Clinica Gol", "gol@example.md")
        cab = _cabinet(s, "gol@example.md")
        page = cab.get("/cont/documente").body
        res.ok("раздел: три документа «încă nepublicat», форма загрузки всё равно есть",
               page.count("încă nepublicat") == 3 and "action='/cont/documente/incarca'" in page, page[-3000:])
        res.check("PDF поставщика — 404", _raw(cab, "/cont/documente/contract.pdf")[0], 404)
        res.check("загрузка экземпляра работает и без документов поставщика",
                  _msg(_upload(cab, b"%PDF-1.4\n%%EOF\n")), "doc_ok")
        res.check("версия строки — пусто: документа поставщика не было",
                  _one(s, "SELECT version FROM clinic_contracts WHERE clinic_id=?", cid), "")
        card = admin.get(f"/admin/clinics/{cid}").body
        res.ok("админка: документы помечены «не выложен» с именем переменной",
               card.count("не выложен") == 3 and "DP_CONTRACT" in card and "DP_DPA" in card)
        before = len(_letters(s))
        admin.post(f"/admin/clinics/{cid}/issue", kind="trial", send="1")
        letters = _letters(s)
        res.ok("письмо о лицензии без договора на сервере — без строки о документах",
               len(letters) == before + 1 and mail.DOCUMENTS_URL not in letters[-1][2], letters[-1][2] if letters else "")
        rc, out = _tools(s, "check")
        res.ok("check: DP_CONTRACT и DP_DPA пусты — предупреждения, не препятствия",
               rc == 0 and "DP_CONTRACT пуст" in out and "DP_DPA пуст" in out, out)
        env = dict(s.env)
        env["DP_CONTRACT"] = str(s.dir / "nu-exista.pdf")
        rc, out = _tools(s, "check", env=env)
        res.ok("check: путь задан, файла нет — предупреждение", "файла нет или это не PDF" in out, out)
