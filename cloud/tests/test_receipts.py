"""Cont de plată после оплаты (receipts.py, 17.10): генератор PDF без библиотек,
снимок при подтверждении платежа, PDF из админки и из кабинета (только своей
клиники), вложение в письмо об оплате, снимок для оплаченных до таблицы.

Шрифта Inter в репозитории нет (OFL-файл кладёт Олег в app/assets): здесь
проверяется тот режим, который есть на машине прогона, — `pdf.fonts()` говорит
какой. Запасной (Helvetica) читается прямо из потока содержимого; вшитый — по
объектам Type0/ToUnicode.
"""
import email
import email.policy
import json
import re
import sqlite3
import sys
import urllib.request
import zlib

from harness import CLOUD, Client, Result, Server, cid_from

sys.path.insert(0, str(CLOUD))
from app import pdf, receipts  # noqa: E402 — чистые функции сервера

SELLER_ENV = {"DP_BANK_BENEFICIARY": "Oleg Bacalu", "DP_BANK_IBAN": "MD00TEST0000000000000001",
              "DP_BANK_NAME": "Banca Test", "DP_BANK_CODE": "1234567890123",
              "DP_SELLER_ADDRESS": "mun. Chișinău, str. Testelor 1"}
SNAPSHOT = {"number": "DP-2026-000007", "issued_at": "2026-10-17T09:15:00Z",
            "seller": {"name": "Oleg Bacalu", "form": receipts.SELLER_FORM, "idno": "1026023148339",
                       "iban": "MD24AG000225100013104168", "bank": "maib", "address": "mun. Chișinău, str. T 1",
                       "email": "dentpilotpro@gmail.com", "phone": "+373 60 508 048"},
            "buyer": {"name": "SRL „Zâmbet Sănătos”", "idno": "1012600012345",
                      "address": "or. Cahul, str. Ștefan cel Mare 12", "email": "director@zambet.md"},
            "item": {"title": "Abonament DentPilot — program de evidență pentru clinica stomatologică",
                     "detail": "abonament pentru 12 luni, 17.10.2026 – 17.10.2027"},
            "amount": 5489, "currency": "MDL", "paid_at": "2026-10-17T09:15:00Z", "paid_via": "card",
            "reference": "DP-2026-000007", "kind": "license"}


def _sql(s: Server, sql: str, *args):
    con = sqlite3.connect(s.dir / "cloud.db")
    try:
        rows = con.execute(sql, args).fetchall()
        con.commit()         # UPDATE без commit откатился бы при close (cloud.md)
        return rows
    finally:
        con.close()


def _clinic(c: Client, **over) -> str:
    f = dict(name="Clinica Cont", idno="1234567890123", contact_name="Ion", email="cont@example.md", phone="")
    f.update(over)
    return cid_from(c.post("/admin/clinics", **f).location)


def _letters(s: Server) -> list[tuple[str, str, str, list[str]]]:
    """(кому, тема, текст, имена вложений) по порядку отправки."""
    out = []
    for f in sorted(s.outbox.glob("*.eml")):
        m = email.message_from_bytes(f.read_bytes(), policy=email.policy.default)
        out.append((m["To"], m["Subject"], m.get_body(preferencelist=("plain",)).get_content(),
                    [p.get_filename() for p in m.iter_attachments()]))
    return out


def _raw(c: Client, path: str) -> tuple[int, dict, bytes]:
    """GET байтами: Reply.body харнесса — текст UTF-8, и PDF в нём ломается."""
    try:
        with c.opener.open(urllib.request.Request(c.base + path), timeout=30) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read()
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read()


def _xref_ok(b: bytes) -> str:
    """'' — таблица xref ведёт на каждый объект; иначе что не так."""
    if not b.startswith(b"%PDF-1.4") or not b.rstrip().endswith(b"%%EOF"):
        return "нет шапки или %%EOF"
    m = re.search(rb"startxref\n(\d+)\n%%EOF", b)
    if not m:
        return "нет startxref"
    xref = int(m.group(1))
    head = re.match(rb"xref\n0 (\d+)\n", b[xref:])
    if not head:
        return f"по startxref не xref: {b[xref:xref + 12]!r}"
    n = int(head.group(1))
    rows = re.findall(rb"(\d{10}) (\d{5}) ([nf])", b[xref:xref + 40 + 20 * n])
    if len(rows) != n:
        return f"строк xref {len(rows)}, объявлено {n}"
    for i, (off, _gen, _kind) in enumerate(rows[1:], 1):
        want = f"{i} 0 obj".encode()
        if b[int(off):int(off) + len(want)] != want:
            return f"объект {i}: по смещению {off.decode()} не он"
    return ""


def _content(b: bytes) -> bytes:
    """Поток содержимого страницы (последний сжатый поток) — текст запасного режима."""
    streams = re.findall(rb"/Filter /FlateDecode >>\nstream\n(.*?)\nendstream", b, re.S)
    return zlib.decompress(streams[-1]) if streams else b""


def _has_text(b: bytes, *needles: str) -> bool:
    """Текст в документе: в запасном режиме — буквально в потоке (без диакритики),
    во вшитом — проверяется структура Type0 (текст там номерами глифов)."""
    if pdf.fonts()[0].embedded:
        return all(x in b for x in (b"/Subtype /Type0", b"/CIDFontType2", b"beginbfchar", b"/FontFile2"))
    content = _content(b)
    helv = pdf.Standard("Helvetica", pdf._W_REG)
    return all(helv.show(n)[1:-1] in content for n in needles)      # как в потоке: без диакритики, скобки экранированы


def suite_pdf(res: Result) -> None:
    """Чистые правила: генератор, деньги, имя файла, номер, режим шрифта."""
    doc = pdf.Document("Probă — ș ț ă")
    doc.text(48, 60, "Cont de plată", 14, bold=True)
    w = doc.text(500, 80, "Suma, MDL", 9, align="right")
    doc.line(48, 90, 500, 90)
    doc.rect(48, 100, 100, 20, (0.9, 0.9, 0.9))
    lines = doc.wrap("Abonament DentPilot — program de evidență pentru clinica stomatologică", 10, 120)
    b = doc.build()
    res.check("PDF: xref ведёт на каждый объект", _xref_ok(b), "")
    res.ok("PDF: заголовок UTF-16 с BOM в Info", b"/Title <FEFF" in b and b"/Producer (DentPilot Cloud)" in b)
    res.ok("ширина текста считается и выравнивание вправо не уходит за край", 0 < w < 60, str(w))
    res.ok("перенос по словам в 120 pt — несколько строк, слова целы",
           len(lines) >= 4 and " ".join(lines) == "Abonament DentPilot — program de evidență pentru clinica stomatologică",
           repr(lines))
    helv = pdf.Standard("Helvetica", pdf._W_REG)
    res.check("запасной режим снимает диакритику, кавычки и тире",
              helv.plain("Cont de plată — „Zâmbet” «Sănătos» ș ț Ă"), 'Cont de plata - "Zambet" "Sanatos" s t A')
    res.ok("запасной режим: строка PDF экранирует скобки", helv.show("a(b)c\\") == b"(a\\(b\\)c\\\\)", repr(helv.show("a(b)c\\")))
    embedded, line = pdf.font_status()
    res.ok("font_status: режим назван словами — вшит или Helvetica с переводом букв",
           (embedded and pdf.REGULAR in line) or (not embedded and "Helvetica" in line and "ă→a" in line), line)
    res.check("деньги: разряды пробелом, копейки запятой",
              [receipts.money(499), receipts.money(5489), receipts.money(1234567)], ["499,00", "5 489,00", "1 234 567,00"])
    res.check("имя файла без диакритики", receipts.filename("DP-2026-000007"), "Cont-de-plata-DP-2026-000007.pdf")
    res.ok("номер документа — только вид reference",
           receipts.NUMBER_RE.match("DP-2026-000007") and not receipts.NUMBER_RE.match("DP-2026-7")
           and not receipts.NUMBER_RE.match("../x"))
    row = {"data": json.dumps(SNAPSHOT, ensure_ascii=False), "number": SNAPSHOT["number"]}
    b = receipts.render(row)
    res.check("cont de plată из снимка: xref цел", _xref_ok(b), "")
    res.ok("cont de plată: номер, ACHITAT, стороны, сумма, способ оплаты, без TVA, режим 228/2025",
           _has_text(b, "Cont de plată nr. DP-2026-000007", "ACHITAT", "Oleg Bacalu", "IDNO 1026023148339",
                     "IBAN MD24AG000225100013104168", "Zâmbet Sănătos", "IDNO 1012600012345", "5 489,00",
                     "plată cu cardul (maib)", "Data: 17.10.2026", "Fără TVA", "Legea nr. 228/2025",
                     "17.10.2026 – 17.10.2027", "fără semnătură și ștampilă"), _content(b)[:400].decode("latin-1"))
    for kind, title in (("sms", "Pachet SMS"), ("sms_name", "Nume de expeditor")):
        res.ok(f"предмет {kind} — по виду платежа", title in receipts.item_for(
            None if kind == "sms" else _FakeCon(), _FakeRow(kind))["title"])


class _FakeRow(dict):
    def __init__(self, kind: str):
        super().__init__(kind=kind, sms_units=200, clinic_id="c1", months=1)

    def keys(self):
        return super().keys()


class _FakeCon:
    def execute(self, *a):
        return self

    def fetchone(self):
        return {"sender": "Zambet"}


def suite_flow(res: Result) -> None:
    """Сервер: снимок при подтверждении, PDF админки и кабинета, вложение в письмо,
    чужой документ, неоплаченная нота, стабильность снимка, оплаченные до таблицы."""
    with Server(env={**SELLER_ENV, "DP_TRIAL_MODE": "auto"}) as s:
        c = Client(s.url).login()
        cid = _clinic(c)
        other = _clinic(c, name="Clinica Străină", idno="9876543210987", email="alta@example.md")
        res.check("таблица receipts есть (миграция 13)",
                  _sql(s, "SELECT count(*) FROM sqlite_master WHERE name='receipts'")[0][0], 1)
        r = c.post(f"/admin/clinics/{cid}/payments", months="1", amount="", send="1")
        ref = re.search(r"DP-\d{4}-\d{6}", c.get(f"/admin/clinics/{cid}").body).group(0)
        pid = _sql(s, "SELECT id FROM payments WHERE reference=?", ref)[0][0]
        res.check("неоплаченная нота: документа нет — 404", c.get(f"/admin/payments/{pid}/cont.pdf").status, 404)
        res.ok("в карточке у ожидающей ноты нет ссылки на PDF", "cont PDF" not in c.get(f"/admin/clinics/{cid}").body)
        n0 = len(_letters(s))
        r = c.post(f"/admin/payments/{pid}/confirm")
        res.ok("перевод подтверждён", "payment_confirmed" in r.location, r.location)
        rows = _sql(s, "SELECT payment_id, clinic_id, number, data FROM receipts")
        res.ok("снимок один, номер = reference, клиника та", len(rows) == 1 and rows[0][0] == pid
               and rows[0][1] == cid and rows[0][2] == ref, repr(rows)[:200])
        d = json.loads(rows[0][3])
        res.ok("снимок: продавец из окружения, адрес, покупатель из строки клиники, предмет с периодом, перевод",
               d["seller"]["name"] == "Oleg Bacalu" and d["seller"]["idno"] == "1234567890123"
               and d["seller"]["iban"] == "MD00TEST0000000000000001" and d["seller"]["address"] == SELLER_ENV["DP_SELLER_ADDRESS"]
               and d["buyer"]["name"] == "Clinica Cont" and d["buyer"]["idno"] == "1234567890123"
               and d["item"]["title"].startswith("Abonament DentPilot") and "1 lună" in d["item"]["detail"]
               and re.search(r"\d\d\.\d\d\.\d{4} – \d\d\.\d\d\.\d{4}", d["item"]["detail"])
               and d["paid_via"] == "transfer" and d["amount"] > 0 and d["kind"] == "license", json.dumps(d, ensure_ascii=False)[:400])
        status, hdr, body = _raw(c, f"/admin/payments/{pid}/cont.pdf")
        res.ok("админка: PDF, inline с именем файла, xref цел",
               status == 200 and hdr.get("content-type", "").startswith("application/pdf")
               and hdr.get("content-disposition") == f'inline; filename="Cont-de-plata-{ref}.pdf"'
               and _xref_ok(body) == "",
               f"{status} {hdr.get('content-type')} {hdr.get('content-disposition')} {_xref_ok(body)}")
        res.ok("админка: ссылка «cont PDF» у оплаченной ноты", f"/admin/payments/{pid}/cont.pdf" in c.get(f"/admin/clinics/{cid}").body)
        letters = _letters(s)[n0:]
        res.ok("письмо об оплате: вложение cont de plată и фраза о нём",
               len(letters) == 1 and letters[0][0] == "cont@example.md"
               and f"Cont-de-plata-{ref}.pdf" in letters[0][3]
               and f"Contul de plată nr. {ref}" in letters[0][2] and "/cont" in letters[0][2], repr(letters)[:300])
        # снимок не меняется вслед за реквизитами клиники
        _sql(s, "UPDATE clinics SET name='Clinica Redenumită', address='str. Nouă 5' WHERE id=?", cid)
        d2 = json.loads(_sql(s, "SELECT data FROM receipts WHERE payment_id=?", pid)[0][0])
        res.ok("снимок стабилен после правки клиники", d2["buyer"]["name"] == "Clinica Cont" and d2["buyer"]["address"] == "")
        # кабинет: вход кодом на ящик клиники
        anon = Client(s.url)
        res.check("кабинет без входа: PDF — на страницу входа",
                  (anon.get(f"/cont/plati/{ref}.pdf").status, anon.get(f"/cont/plati/{ref}.pdf").location),
                  (303, "/cont/login"))
        r = anon.post("/cont/login/email", email="cont@example.md")
        vid = re.search(r"name='verify_id' value='([^']+)'", r.body).group(1)
        code = re.search(r": (\d{6})\n", _letters(s)[-1][2]).group(1)
        r = anon.post("/cont/login/cod", verify_id=vid, code=code, email="cont@example.md")
        res.check("вход кодом: клиника найдена по ящику — в кабинет", (r.status, r.location), (303, "/cont"))
        home = anon.get("/cont").body
        res.ok("кабинет: колонка Document и ссылка на cont de plată оплаченной ноты",
               "<th>Document</th>" in home and f"/cont/plati/{ref}.pdf" in home and "cont de plată (PDF)" in home, home[-1500:])
        status, hdr, mine = _raw(anon, f"/cont/plati/{ref}.pdf")
        res.ok("кабинет: свой документ — PDF, тот же номер",
               status == 200 and hdr.get("content-type", "").startswith("application/pdf")
               and _xref_ok(mine) == "" and _has_text(mine, f"Cont de plată nr. {ref}"),
               f"{status} {hdr.get('content-type')} {_xref_ok(mine)}")
        # чужой оплаченный платёж — 404
        c.post(f"/admin/clinics/{other}/payments", months="1", amount="", send="")
        ref2 = re.search(r"DP-\d{4}-\d{6}", c.get(f"/admin/clinics/{other}").body).group(0)
        pid2 = _sql(s, "SELECT id FROM payments WHERE reference=?", ref2)[0][0]
        c.post(f"/admin/payments/{pid2}/confirm")
        res.check("кабинет: документ другой клиники — 404", anon.get(f"/cont/plati/{ref2}.pdf").status, 404)
        c.post(f"/admin/clinics/{cid}/payments", months="12", amount="", send="")
        ref3 = [x for x in re.findall(r"DP-\d{4}-\d{6}", c.get(f"/admin/clinics/{cid}").body) if x != ref][0]
        res.check("кабинет: своя, но ещё не оплаченная нота — 404", anon.get(f"/cont/plati/{ref3}.pdf").status, 404)
        res.check("кабинет: кривой номер — 404", anon.get("/cont/plati/DP-1.pdf").status, 404)
        # оплаченный до таблицы: строка без снимка → снимок при первом запросе
        _sql(s, "DELETE FROM receipts WHERE payment_id=?", pid2)
        r = c.get(f"/admin/payments/{pid2}/cont.pdf")
        res.ok("оплаченный без снимка: PDF есть, снимок появился",
               r.status == 200 and _sql(s, "SELECT number FROM receipts WHERE payment_id=?", pid2) == [(ref2,)], str(r.status))
        res.ok("документ текстом: номер и покупатель", _has_text(body, f"Cont de plată nr. {ref}", "Clinica Cont", "transfer bancar"))
