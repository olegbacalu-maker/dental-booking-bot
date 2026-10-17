"""Заявление клиники на имя отправителя SMS в кабинете (sms_paper.py, 17.10).

sms.md клиник не знает: имя принадлежит клинике по её подписанному заявлению на
бланке sms.md. Кабинет даёт два шага: скачать заявление уже заполненным (PDF из
реквизитов клиники) и загрузить подписанное — файл ложится в базу облака, и
отметка «Заявление получено» ставится сама. Здесь: текст бланка и заполнение,
отказы (нет заявки, нет реквизитов, не PDF, пусто, велико), чужая клиника,
новая заявка обнуляет файл, подача Олегом после загрузки, раздел не виден без
пакета.
"""
import re
import sys

from harness import CLOUD, Client, Result, Server
from test_receipts import _content, _letters, _raw, _xref_ok
from test_sms import FakeSmsMd, _clinic_with_license, _one, _sql

sys.path.insert(0, str(CLOUD))
from app import pdf, sms_paper  # noqa: E402 — чистые функции сервера

CLINIC = {"name": "SRL „Zâmbet Sănătos”", "idno": "1012600012345", "address": "or. Cahul, str. Ștefan cel Mare 12",
          "email": "director@zambet.md", "phone": "+373 299 12 345", "contact_name": "Ion Popescu"}
_PLAIN = pdf.Standard("Helvetica", pdf._W_REG)


def _pdf_text(b: bytes) -> str:
    """Текст листа без пробелов, упрощённый, как в запасном шрифте: вшитый шрифт —
    номерами глифов через ToUnicode, Helvetica — строками потока."""
    maps = {m.group(1).decode(): bytes.fromhex(m.group(2).decode()).decode("utf-16-be")
            for m in re.finditer(rb"<([0-9A-F]{4})> <([0-9A-F]+)>", b)}
    out = []
    for tok in re.finditer(r"<([0-9A-F]+)> Tj|\((.*?)\) Tj", _content(b).decode("latin-1")):
        h = tok.group(1)
        out.append("".join(maps.get(h[i:i + 4], "?") for i in range(0, len(h), 4)) if h else tok.group(2))
    return re.sub(r"\s+", "", _PLAIN.plain(" ".join(out)))


def _has(b: bytes, *needles: str) -> list[str]:
    """Каких строк нет в листе (пробелы и диакритика не в счёт)."""
    text = _pdf_text(b)
    return [n for n in needles if re.sub(r"\s+", "", _PLAIN.plain(n)) not in text]


def _multipart(data: bytes, name: str = "cerere.pdf", ctype: str = "application/pdf") -> tuple[bytes, str]:
    b = "----dpPaperBoundary7d1"
    body = (f"--{b}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{name}\"\r\n"
            f"Content-Type: {ctype}\r\n\r\n").encode() + data + f"\r\n--{b}--\r\n".encode()
    return body, f"multipart/form-data; boundary={b}"


def _upload(c: Client, data: bytes, name: str = "cerere.pdf"):
    body, ctype = _multipart(data, name)
    return c._do("/cont/sms/cerere", body, {"Content-Type": ctype})


def _post_raw(c: Client, path: str, **fields) -> tuple[int, dict, bytes]:
    """POST формы, ответ байтами (PDF в тексте UTF-8 ломается)."""
    import urllib.error
    import urllib.parse
    import urllib.request
    req = urllib.request.Request(c.base + path, data=urllib.parse.urlencode(fields).encode())
    try:
        with c.opener.open(req, timeout=30) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read()
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read()


def _cabinet(s: Server, email: str) -> Client:
    """Вход в кабинет кодом на ящик клиники."""
    c = Client(s.url)
    r = c.post("/cont/login/email", email=email)
    vid = re.search(r"name='verify_id' value='([^']+)'", r.body).group(1)
    code = re.search(r": (\d{6})\n", _letters(s)[-1][2]).group(1)
    c.post("/cont/login/cod", verify_id=vid, code=code, email=email)
    return c


def _msg(r) -> str:
    m = re.search(r"[?&]msg=([a-z_]+)", r.location or "")
    return m.group(1) if m else f"{r.status} {r.location}"


def suite_render(res: Result) -> None:
    """Чистые правила: текст бланка sms.md, заполненные поля, имя файла, проверки."""
    b = sms_paper.render(CLINIC, "Zambet Dent", "Ion Popescu")
    res.check("лист: xref ведёт на каждый объект", _xref_ok(b), "")
    res.check("лист: бланк sms.md с текстом без правок и заполненными пропусками", _has(
        b, sms_paper.TITLE, "Către: ROCK SOFT S.R.L", "IDNO: 1021600014623",
        "Subsemnatul, Ion Popescu in calitate de reprezentant legal al companiei SRL „Zâmbet Sănătos”",
        "IDNO: 1012600012345", "Adresa juridica: or. Cahul, str. Ștefan cel Mare 12", "Email director@zambet.md",
        "Telefon +373 299 12 345", "prin prezenta solicit activarea Alias-ului SMS după cum urmeaza:",
        "Alias propus: Zambet Dent",
        "Sunt de acord ca acest Alias sa fie folosit de către Oleg Bacalu, antreprenor independent, IDNO 1026023148339",
        "către clientii programati prin platforma DentPilot", "utilizarea neautorizat a denumirii.",
        "Nume si prenume: Ion Popescu", "Semnatura:"), [])
    day = re.search(r"Data:(\d\d\.\d\d\.\d{4})", _pdf_text(b))
    res.ok("обе даты — сегодня по Кишинёву", day is not None and _pdf_text(b).count(day.group(1)) == 2,
           _pdf_text(b)[-200:])
    res.check("имя файла — латиница, без пробелов", sms_paper.filename("Zambet Dent"), "Cerere-alias-SMS-Zambet-Dent.pdf")
    res.check("реквизиты: всё есть — пусто", sms_paper.missing(CLINIC), [])
    res.check("реквизиты: IDNO короче, нет адреса и телефона — названы по-румынски",
              sms_paper.missing({**CLINIC, "idno": "123", "address": " ", "phone": ""}),
              ["IDNO (13 cifre)", "adresa", "telefonul"])
    res.ok("представитель: пробелы схлопнуты; цифры и пустое — не имя",
           sms_paper.clean_rep("  Ion   Popescu ") == "Ion Popescu" and sms_paper.clean_rep("12345") == ""
           and sms_paper.clean_rep("") == "" and len(sms_paper.clean_rep("A" * 200)) == sms_paper.REP_MAX)
    res.ok("PDF — по сигнатуре в первом КБ, не по имени",
           sms_paper.is_pdf(b"%PDF-1.7\n") and sms_paper.is_pdf(b"\x00" * 100 + b"%PDF-1.4")
           and not sms_paper.is_pdf(b"MZ\x90\x00") and not sms_paper.is_pdf(b"\x00" * 2000 + b"%PDF-1.4"))


def suite_cabinet(res: Result) -> None:
    """Кабинет › SMS: заявка, заполненное заявление, загрузка подписанного, админка."""
    fake = FakeSmsMd()
    try:
        with Server(env=fake.env()) as s:
            admin = Client(s.url).login()
            cid, _token = _clinic_with_license(admin, s, "Zambet Dent", "zd@example.md")
            cid2, _token2 = _clinic_with_license(admin, s, "Clinica Doi", "doi@example.md")
            _sql(s, "UPDATE clinics SET idno='2234567890123' WHERE id=?", cid2)
            res.check("миграция 14: таблица sms_papers",
                      _one(s, "SELECT count(*) FROM sqlite_master WHERE name='sms_papers'"), 1)
            cab = _cabinet(s, "zd@example.md")
            home = cab.get("/cont").body
            res.ok("кабинет: раздел SMS, имени нет, предложение из названия",
                   "SMS · numele expeditorului" in home and "nu are încă nume propriu" in home
                   and "value='Zambet Dent'" in home and "de la «DentPilot»" in home, home[-3000:])
            res.check("просмотр кабинета счёт SMS не заводит",
                      _one(s, "SELECT count(*) FROM sms_accounts WHERE clinic_id=?", cid), 0)
            res.check("без заявки заявление не скачать",
                      _msg(cab.post("/cont/sms/cerere.pdf", rep="Ion Popescu")), "sms_paper_state")
            res.check("без заявки не загрузить", _msg(_upload(cab, b"%PDF-1.4\n%%EOF\n")), "sms_paper_state")
            res.check("кривое имя — sms_name", _msg(cab.post("/cont/sms/nume", name="Zambet Dent!")), "sms_name")
            admin.post(f"/admin/clinics/{cid2}/sms", action="request", name="Doi Dent")
            res.check("чужое имя — sms_name_taken", _msg(cab.post("/cont/sms/nume", name="doi-dent")), "sms_name_taken")
            res.check("заявка из кабинета принята", _msg(cab.post("/cont/sms/nume", name="Zambet Dent")), "sms_requested")
            res.ok("заявка: requested, журнал от ящика кабинета",
                   _one(s, "SELECT sender_state FROM sms_accounts WHERE clinic_id=?", cid) == "requested"
                   and "zd@example.md" == _one(s, "SELECT who FROM audit WHERE what='sms_sender' AND clinic_id=? "
                                                  "ORDER BY id DESC LIMIT 1", cid))
            home = cab.get("/cont").body
            res.ok("кабинет: шаги — скачать, подписать, загрузить; не хватает адреса и телефона",
                   "cerere în lucru" in home and "Descărcați cererea completată" in home
                   and "Încarcă cererea semnată" in home and "enctype='multipart/form-data'" in home
                   and "Lipsesc din <a href='#date'>datele clinicii</a>: adresa, telefonul" in home, home[-4000:])
            res.check("без адреса и телефона заявление не скачать — sms_paper_data",
                      _msg(cab.post("/cont/sms/cerere.pdf", rep="Ion Popescu")), "sms_paper_data")
            cab.post("/cont/date", name="Zambet Dent", idno="1234567890123", contact_name="Ion Popescu",
                     phone="+373 299 12 345", address="or. Cahul, str. Ștefan cel Mare 12")
            home = cab.get("/cont").body
            res.ok("реквизиты есть — форма с представителем из контактного лица",
                   "name='rep' value='Ion Popescu'" in home and "Descarcă cererea (PDF)" in home, home[-4000:])
            res.check("без представителя — sms_paper_rep", _msg(cab.post("/cont/sms/cerere.pdf", rep="  ")), "sms_paper_rep")
            st, hdr, b = _post_raw(cab, "/cont/sms/cerere.pdf", rep="Maria  Ionescu")
            res.ok("заявление: PDF вложением с именем по имени отправителя, xref цел",
                   st == 200 and hdr.get("content-type", "").startswith("application/pdf")
                   and hdr.get("content-disposition") == 'attachment; filename="Cerere-alias-SMS-Zambet-Dent.pdf"'
                   and _xref_ok(b) == "", f"{st} {hdr.get('content-type')} {hdr.get('content-disposition')}")
            res.check("заявление заполнено из строки клиники и формы", _has(
                b, "Subsemnatul, Maria Ionescu", "IDNO: 1234567890123", "Adresa juridica: or. Cahul",
                "Email zd@example.md", "Telefon +373 299 12 345", "Alias propus: Zambet Dent",
                "Nume si prenume: Maria Ionescu"), [])
            # загрузка подписанного
            res.check("не PDF — sms_paper_pdf", _msg(_upload(cab, b"MZ\x90\x00 not a pdf", "cerere.exe")), "sms_paper_pdf")
            res.check("пустой файл — sms_paper_empty", _msg(_upload(cab, b"")), "sms_paper_empty")
            body, ctype = _multipart(b"x")
            res.check("форма без поля file — sms_paper_empty",
                      _msg(cab._do("/cont/sms/cerere", body.replace(b'name="file"', b'name="other"'),
                                   {"Content-Type": ctype})), "sms_paper_empty")
            big = b"%PDF-1.4\n" + b"0" * (sms_paper.MAX_BYTES + 100 * 1024)
            res.check("больше 5 МБ — sms_paper_big, ответ, а не обрыв", _msg(_upload(cab, big)), "sms_paper_big")
            res.check("после отказов файлов нет и отметки нет",
                      (_one(s, "SELECT count(*) FROM sms_papers"),
                       _one(s, "SELECT sender_paper_at FROM sms_accounts WHERE clinic_id=?", cid)), (0, None))
            signed = b"%PDF-1.7\n% semnat de Maria Ionescu\n" + bytes(range(256)) * 40 + b"\n%%EOF\n"
            res.check("подписанное заявление принято", _msg(_upload(cab, signed, "C:\\scan\\cerere semnată.pdf")),
                      "sms_paper_ok")
            row = _sql(s, "SELECT clinic_id, sender, body, size, filename, who FROM sms_papers")
            res.ok("файл в базе байт в байт: клиника, имя, размер, имя файла без пути, кто",
                   len(row) == 1 and row[0][0] == cid and row[0][1] == "Zambet Dent" and bytes(row[0][2]) == signed
                   and row[0][3] == len(signed) and row[0][4] == "cerere semnată.pdf" and row[0][5] == "zd@example.md",
                   repr([r[:2] + r[3:] for r in row]))
            res.ok("загрузка ставит «Заявление получено» и ссылку на файл",
                   _sql(s, "SELECT sender_paper_at IS NOT NULL, sender_paper_id FROM sms_accounts WHERE clinic_id=?", cid)
                   == [(1, _one(s, "SELECT id FROM sms_papers"))])
            res.ok("журнал: заявление загружено в кабинете",
                   "загружено в кабинете" in _one(s, "SELECT detail FROM audit WHERE what='sms_sender' AND clinic_id=? "
                                                     "ORDER BY id DESC LIMIT 1", cid))
            res.ok("кабинет: «Primită la», можно заменить", "Primită la" in cab.get("/cont").body)
            # админка
            card = admin.get(f"/admin/clinics/{cid}").body
            res.ok("карточка: заявление загружено клиникой, ссылка на PDF, кнопка «Подано»",
                   "заявление загружено клиникой" in card and f"/admin/clinics/{cid}/sms/cerere.pdf" in card
                   and "Подано в sms.md" in card, card[-5000:])
            res.ok("очередь имён: ссылка на заявление", f"/admin/clinics/{cid}/sms/cerere.pdf" in admin.get("/admin/sms").body)
            st, hdr, got = _raw(admin, f"/admin/clinics/{cid}/sms/cerere.pdf")
            res.ok("админка отдаёт тот же файл вложением, nosniff",
                   st == 200 and got == signed and hdr.get("content-disposition", "").startswith("attachment;")
                   and "Zambet-Dent-semnata.pdf" in hdr.get("content-disposition", "")
                   and hdr.get("x-content-type-options") == "nosniff", f"{st} {hdr}")
            res.check("без входа админки — на вход", Client(s.url).get(f"/admin/clinics/{cid}/sms/cerere.pdf").status, 303)
            res.check("у клиники без заявления — 404", admin.get(f"/admin/clinics/{cid2}/sms/cerere.pdf").status, 404)
            # другая клиника своим кабинетом чужой файл не видит и не трогает
            cab2 = _cabinet(s, "doi@example.md")
            home2 = cab2.get("/cont").body
            res.ok("кабинет другой клиники: своё имя, чужого файла нет",
                   "Doi Dent" in home2 and "Primită la" not in home2 and "Zambet" not in home2, home2[-3000:])
            res.check("у второй клиники нет реквизитов — её заявление не скачать",
                      _msg(cab2.post("/cont/sms/cerere.pdf", rep="Ana Doi")), "sms_paper_data")
            # подача Олегом и дальше загрузка закрыта
            r = admin.post(f"/admin/clinics/{cid}/sms", action="submitted")
            res.check("после загрузки Олег сразу подаёт — без кнопки «Заявление получено»", r.location,
                      f"/admin/clinics/{cid}?msg=sms_saved")
            res.check("подано — загрузка закрыта", _msg(_upload(cab, signed)), "sms_paper_state")
            res.ok("кабинет: «la operatori»", "la operatori" in cab.get("/cont").body)
            res.check("подано — файл в админке остаётся", _raw(admin, f"/admin/clinics/{cid}/sms/cerere.pdf")[0], 200)
            # новая заявка — новое заявление: ссылка обнуляется, прежний файл остаётся в таблице
            res.check("новое имя из кабинета", _msg(cab.post("/cont/sms/nume", name="Zambet")), "sms_requested")
            res.ok("новая заявка: отметки и ссылки нет, файл остался в таблице",
                   _sql(s, "SELECT sender_paper_at, sender_paper_id FROM sms_accounts WHERE clinic_id=?", cid) == [(None, None)]
                   and _one(s, "SELECT count(*) FROM sms_papers") == 1)
            res.check("новая заявка: в админке файла текущей заявки нет — 404",
                      admin.get(f"/admin/clinics/{cid}/sms/cerere.pdf").status, 404)
    finally:
        fake.close()


def suite_not_offered(res: Result) -> None:
    """Пакет не предложен — раздела SMS в кабинете нет, маршруты отказывают."""
    fake = FakeSmsMd()
    try:
        with Server(env=fake.env(DP_SMS_OFFERED="")) as s:
            admin = Client(s.url).login()
            cid, _token = _clinic_with_license(admin, s, "Clinica Fara", "fara@example.md")
            cab = _cabinet(s, "fara@example.md")
            res.ok("без пакета раздела SMS нет", "numele expeditorului" not in cab.get("/cont").body)
            res.check("заявка на имя — sms_not_offered", _msg(cab.post("/cont/sms/nume", name="Fara")), "sms_not_offered")
            res.check("загрузка — sms_not_offered", _msg(_upload(cab, b"%PDF-1.4\n")), "sms_not_offered")
            res.check("ни счёта, ни файла", (_one(s, "SELECT count(*) FROM sms_accounts"),
                                            _one(s, "SELECT count(*) FROM sms_papers")), (0, 0))
            admin.post(f"/admin/clinics/{cid}/sms", action="pilot_on")
            res.ok("пилот этой клинике — раздел появился", "numele expeditorului" in cab.get("/cont").body)
    finally:
        fake.close()
