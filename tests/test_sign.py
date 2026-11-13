"""Подпись бланка на экране (09.11.2026): `POST /api/patients/{pid}/forms/{key}/sign`.

Результат подписи — PDF-документ в категории бланка, тем же путём, что скан
(`sign.py`, `core/pdf.py`). Отметки «подписан» в базе нет: статус «semnat» и
`stale` согласия к плану обязаны работать от подписанного PDF так же, как от
скана, — это и проверяется здесь, а не флагом.

PDF печатает настоящий headless Edge (на Windows он есть всегда, в CI тоже).
Ветка «Edge нет» (демо в Docker) — подмена `DENTART_EDGE=<путь в никуда>`:
названный путь не найден = Edge нет, без поиска дальше.
⚠️ Проверять `code` конверта, а не только HTTP: удача и отказ различаются им.
"""
import base64
import hashlib
import json
import math
import os
import pathlib
import re
import struct
import sys
import tempfile
import time
import zlib

from harness import Client, Result, Server, _rmtree_settled, pid_by_phone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "bot"))


def _j(r) -> dict:
    return json.loads(r.body)


def _png(w: int = 480, h: int = 160, ink: bool = True, dot: bool = False) -> str:
    """Подпись как её шлёт холст: RGBA, прозрачный фон, синусоида чернилами.
    `ink=False` — пустой холст, `dot=True` — одна точка от случайного касания."""
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))
    rows = []
    for y in range(h):
        row = bytearray(b"\x00")
        for x in range(w):
            if dot:
                on = abs(x - w // 2) < 2 and abs(y - h // 2) < 2
            else:
                on = ink and abs(y - (h // 2 + int(h / 4 * math.sin(x / 25)))) < 3
            row += bytes([20, 30, 120, 255]) if on else bytes(4)
        rows.append(bytes(row))
    raw = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(b"".join(rows))) + chunk(b"IEND", b""))
    return "data:image/png;base64," + base64.b64encode(raw).decode()


SIG = _png()


def _forms(card: dict) -> dict:
    return {f["key"]: f for f in card["forms"]}


def _card(c: Client, pid: int) -> dict:
    return _j(c.get(f"/api/patients/{pid}"))["data"]


def _patient(c: Client, phone: str, plan: bool = True, anam: bool = True) -> int:
    c.post_json("/api/patients", {"name": "Semn Test", "phone": phone})
    pid = pid_by_phone(c, phone)
    if plan:
        c.post_json(f"/api/patients/{pid}/plan", {"procedure": "Obturație 26", "tooth": "26",
                                                 "price": "600", "doctor": "Dr. Ana"})
    if anam:
        c.post_json(f"/api/patients/{pid}/anamneza", {"flags": ["cardio"], "alergii": "latex"})
    return pid


def _boxes(pdf: bytes) -> list[tuple[float, float]]:
    return [(float(w), float(h)) for w, h in
            re.findall(rb"/MediaBox\s*\[\s*0\s+0\s+([\d.]+)\s+([\d.]+)\s*\]", pdf)]


def _left(s: Server) -> list[str]:
    """Что осталось в папке печати (`core/pdf._room`): после подписи — ничего."""
    room = s.dir / "tmp" / "pdf"
    return sorted(p.name for p in room.iterdir()) if room.exists() else []


def suite_sign(res: Result) -> None:
    """Три бланка подписаны на экране: PDF A4 в категории бланка, «semnat»,
    `stale` от подписанного PDF, отпечаток в летописи, временное убрано."""
    with Server() as s:
        c = Client(s.url).login()
        pid = _patient(c, "069555101")
        forms = _forms(_card(c, pid))
        res.check("«Semnează» у трёх бланков, у 043/e нет",
                  {k: f["sign"] for k, f in forms.items()},
                  {"acord195": True, "acord_plan": True, "chestionar": True, "fisa043": False})

        # предпросмотр окна подписи: лист как будет подписан, событий не пишет
        feed0 = [a["text"] for a in _card(c, pid)["activity"]["items"]]
        r = c.get(f"/admin/patient/{pid}/sign/chestionar")
        res.ok("предпросмотр анкеты: ответы из фиши, A4, без кнопок",
               r.status == 200 and "chk on" in r.body and "latex" in r.body
               and "size:A4" in r.body and "noprint" not in r.body.split("</style>")[1],
               f"код {r.status}")
        res.check("предпросмотр 043/e — 404", c.get(f"/admin/patient/{pid}/sign/fisa043").status, 404)
        feed1 = [a["text"] for a in _card(c, pid)["activity"]["items"]]
        res.ok("предпросмотр не пишет «tipărit» в летопись",
               not any("tipărire" in t or "generat" in t for t in feed1[:len(feed1) - len(feed0)]),
               str(feed1[:3]))

        # 1. Informare 195 — пациент сам, согласия DA/NU с экрана
        r = c.post_json(f"/api/patients/{pid}/forms/acord195/sign",
                        {"signer": "pacient", "sig_patient": SIG,
                         "consents": {"mkt": True, "photo": False},
                         "pressure": [0.4, 0.7], "strokes": [[1, 2, 3]]})
        j = _j(r)
        res.check("acord195: удача", (r.status, j["code"]), (200, "ok_sign"))
        doc = j["data"]["doc"]
        res.check("документ: PDF своим просмотрщиком, категория бланка, имя «… - semnat.pdf»",
                  (doc["category"], doc["view"], doc["mime"],
                   doc["filename"].startswith("Informare și acord (Legea 195) - Semn Test - "),
                   doc["filename"].endswith(" - semnat.pdf")),
                  ("acord195", "pdf", "application/pdf", True, True))
        forms = _forms(j["data"])
        res.check("бланк «semnat» этим документом (без флага в базе)",
                  forms["acord195"]["signed"]["doc_id"], doc["id"])
        res.check("документ — первым в списке «Documente» фиши ответа",
                  j["data"]["documents"][0]["id"], doc["id"])
        raw = c.get(f"/admin/doc/{doc['id']}").raw
        res.ok("файл — настоящий PDF A4", raw.startswith(b"%PDF-") and _boxes(raw)
               and all(abs(w - 595.92) < 1.5 and abs(h - 842.88) < 1.5 for w, h in _boxes(raw)),
               f"{raw[:8]!r} {_boxes(raw)[:2]}")
        sha = hashlib.sha256(raw).hexdigest()
        feed = [a for a in j["data"]["activity"]["items"] if a["kind"] == "sign"]
        res.ok("летопись: что, кто подписал и отпечаток ИМЕННО этого файла",
               len(feed) == 1 and feed[0]["text"] ==
               f"Semnat pe ecran: Informare și acord (Legea 195) · pacientul · SHA-256 {sha}"
               and feed[0]["icon"] == "pen", str(feed))
        res.check("временное печати убрано (папка данных)", _left(s), [])

        # 2. Acord informat — пациент и врач; новая позиция ПОСЛЕ подписи → stale
        r = c.post_json(f"/api/patients/{pid}/forms/acord_plan/sign",
                        {"signer": "pacient", "sig_patient": SIG, "sig_doctor": _png(300, 100)})
        j = _j(r)
        f = _forms(j["data"])["acord_plan"]
        res.check("acord_plan: удача, «semnat», не устарел",
                  (r.status, j["code"], f["signed"]["doc_id"] == j["data"]["doc"]["id"], f["stale"]),
                  (200, "ok_sign", True, False))
        c.post_json(f"/api/patients/{pid}/plan", {"procedure": "Detartraj", "price": "300"})
        res.check("позиция после подписанного PDF — согласие устарело (stale)",
                  _forms(_card(c, pid))["acord_plan"]["stale"], True)

        # 3. анкета — подписывает представитель с именем
        r = c.post_json(f"/api/patients/{pid}/forms/chestionar/sign",
                        {"signer": "reprezentant", "signer_name": "  Ana   Mama ",
                         "sig_patient": SIG})
        j = _j(r)
        res.check("chestionar: удача, «semnat»",
                  (r.status, j["code"], _forms(j["data"])["chestionar"]["signed"]["doc_id"]
                   == j["data"]["doc"]["id"]), (200, "ok_sign", True))
        last = next(a for a in j["data"]["activity"]["items"] if a["kind"] == "sign")
        res.ok("летопись называет представителя", "· reprezentant Ana Mama · SHA-256 " in last["text"],
               last["text"])
        res.check("три подписанных документа — три файла", len(j["data"]["documents"]), 3)
        res.check("и после трёх подписей временного нет", _left(s), [])


def suite_sign_start_sweep(res: Result) -> None:
    """Хвост печати от упавшего запуска (лист с медданными) снимает СТАРТ
    движка, а не следующая подпись через недели (`pdf.sweep_on_start`)."""
    s = Server()
    dead = s.dir / "tmp" / "pdf" / "deadbeefdeadbeef"
    dead.mkdir(parents=True)
    (dead / "sheet.html").write_text("<p>Semn Test — anamneză</p>", encoding="utf-8")
    (dead / "profile").mkdir()
    res.ok("хвост на месте до старта", dead.exists(), "песочница не завелась")
    with s:
        res.check("после старта папка печати пуста", _left(s), [])


def suite_sign_refuse(res: Result) -> None:
    """Отказы: кривая или пустая подпись, SVG, представитель без имени, врач
    без подписи, нечего подписывать, 043/e, без входа. Ничего не записано."""
    with Server() as s:
        anon = Client(s.url)
        c = Client(s.url).login()
        pid = _patient(c, "069555102")
        url = f"/api/patients/{pid}/forms/acord195/sign"
        res.check("без входа — 401", anon.post_json(url, {"signer": "pacient", "sig_patient": SIG}).status, 401)
        for label, key, body, want in (
            ("нет signer", "acord195", {"sig_patient": SIG}, (422, "bad_sign", "signer")),
            ("чужой signer", "acord195", {"signer": "medic", "sig_patient": SIG}, (422, "bad_sign", "signer")),
            ("пустой холст", "acord195", {"signer": "pacient", "sig_patient": _png(ink=False)},
             (422, "bad_sign", "sig_patient")),
            ("одна точка — не подпись", "acord195", {"signer": "pacient", "sig_patient": _png(dot=True)},
             (422, "bad_sign", "sig_patient")),
            ("SVG — никогда", "acord195",
             {"signer": "pacient",
              "sig_patient": "data:image/svg+xml;base64," + base64.b64encode(
                  b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>").decode()},
             (422, "bad_sign", "sig_patient")),
            ("не PNG под видом PNG", "acord195",
             {"signer": "pacient", "sig_patient": "data:image/png;base64," + base64.b64encode(
                 b"\xff\xd8\xff" + b"0" * 2000).decode()}, (422, "bad_sign", "sig_patient")),
            ("крошечная картинка", "acord195", {"signer": "pacient", "sig_patient": _png(20, 10)},
             (422, "bad_sign", "sig_patient")),
            ("представитель без имени", "acord195",
             {"signer": "reprezentant", "signer_name": " ", "sig_patient": SIG},
             (422, "bad_sign_name", "signer_name")),
            ("согласие к плану без подписи врача", "acord_plan",
             {"signer": "pacient", "sig_patient": SIG}, (422, "bad_sign", "sig_doctor")),
        ):
            j = _j(r := c.post_json(f"/api/patients/{pid}/forms/{key}/sign", body))
            res.check(f"отказ: {label}", (r.status, j["code"], j.get("field")), want)
        res.check("043/e не подписывается — 404",
                  c.post_json(f"/api/patients/{pid}/forms/fisa043/sign",
                              {"signer": "pacient", "sig_patient": SIG}).status, 404)
        res.check("чужой пациент — 404",
                  c.post_json("/api/patients/99999/forms/acord195/sign",
                              {"signer": "pacient", "sig_patient": SIG}).status, 404)

        # нечего подписывать: план без активных, анкета не введена
        bare = _patient(c, "069555103", plan=False, anam=False)
        f = _forms(_card(c, bare))
        res.check("кнопка скрыта: план без активных, анкета не введена",
                  (f["acord195"]["sign"], f["acord_plan"]["sign"], f["chestionar"]["sign"]),
                  (True, False, False))
        j = _j(r := c.post_json(f"/api/patients/{bare}/forms/acord_plan/sign",
                                {"signer": "pacient", "sig_patient": SIG, "sig_doctor": SIG}))
        res.check("согласие к пустому плану — 409", (r.status, j["code"]), (409, "bad_sign_plan"))
        j = _j(r := c.post_json(f"/api/patients/{bare}/forms/chestionar/sign",
                                {"signer": "pacient", "sig_patient": SIG}))
        res.check("анкета без анамнеза — 409", (r.status, j["code"]), (409, "bad_sign_anam"))
        res.check("предпросмотр пустого плана — 404",
                  c.get(f"/admin/patient/{bare}/sign/acord_plan").status, 404)

        card = _card(c, pid)
        res.check("после отказов: ни документа, ни строки «Semnat»",
                  (len(card["documents"]),
                   [a for a in card["activity"]["items"] if a["kind"] == "sign"]), (0, []))
        res.check("после отказов временного нет", _left(s), [])


def suite_sign_no_edge(res: Result) -> None:
    """Машина без Edge (демо в Docker): кнопки нет, маршрут — честный 503."""
    with Server(env={"DENTART_EDGE": r"Z:\nu-exista\msedge.exe"}) as s:
        c = Client(s.url).login()
        pid = _patient(c, "069555104")
        res.check("без Edge «Semnează» нет ни у одного бланка",
                  sorted(k for k, f in _forms(_card(c, pid)).items() if f["sign"]), [])
        j = _j(r := c.post_json(f"/api/patients/{pid}/forms/acord195/sign",
                                {"signer": "pacient", "sig_patient": SIG}))
        res.check("подпись без Edge — 503 pdf_none с текстом",
                  (r.status, j["code"], bool(j["text"])), (503, "pdf_none", True))
        res.check("ничего не записано", len(_card(c, pid)["documents"]), 0)


_FAKE_PDF = b"%PDF-1.4\n" + b"x" * 40000 + b"\n%%EOF\n"

# Подменный Edge: пускач выходит сразу, лист дописывает оторванный от него
# процесс — с задержкой и кусками. Настоящий Edge так себя ведёт не всегда,
# поэтому ветку ожидания держит подмена, а не машина прогона.
_FAKE_EDGE = r'''
import os, subprocess, sys, time
PDF = b"%PDF-1.4\n" + b"x" * 40000 + b"\n%%EOF\n"
if sys.argv[1] == "write":
    out, mode = sys.argv[2], sys.argv[3]
    time.sleep(0.5)
    body = PDF if mode == "late" else PDF[:30000]
    with open(out, "wb") as f:
        for i in range(0, len(body), 10000):
            f.write(body[i:i + 10000])
            f.flush()
            time.sleep(0.15)
    sys.exit(0)
mode = os.environ["FAKE_EDGE"]
out = next(a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--print-to-pdf="))
if mode == "ready":
    open(out, "wb").write(PDF)
elif mode != "never":
    subprocess.Popen([sys.executable, __file__, "write", out, mode],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
'''


def suite_sign_late_pdf(res: Result) -> None:
    """Edge-пускач вышел раньше, чем лист дописан (без сервера, подменный
    Edge): `html_to_pdf` ждёт ЦЕЛЫЙ файл, оборванный и отсутствующий — отказ
    к потолку, а не чтение половины листа."""
    from app.core import pdf
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="dp_fakeedge_"))
    script = tmp / "fake_edge.py"
    script.write_text(_FAKE_EDGE, encoding="utf-8")
    if sys.platform == "win32":
        edge = tmp / "msedge.cmd"
        edge.write_text(f'@"{sys.executable}" "{script}" %*\n', encoding="ascii")
    else:
        edge = tmp / "msedge"
        edge.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="ascii")
        edge.chmod(0o755)
    room = tmp / "room"
    keep = (pdf._room, pdf.TIMEOUT_S, os.environ.get("DENTART_EDGE"), os.environ.get("FAKE_EDGE"))
    pdf._room = lambda: room
    os.environ["DENTART_EDGE"] = str(edge)

    def run(mode: str, ceiling: float):
        os.environ["FAKE_EDGE"] = mode
        pdf.TIMEOUT_S = ceiling
        t0 = time.monotonic()
        try:
            got = pdf.html_to_pdf("<p>Semn Test</p>")
        except pdf.PdfError as e:
            got = e.code
        return got, time.monotonic() - t0

    try:
        res.ok("подменный Edge найден", pdf.available(), "подмена не завелась")
        got, _ = run("ready", 15)
        res.ok("лист готов к выходу Edge — отдан как есть", got == _FAKE_PDF, repr(got)[:80])
        got, took = run("late", 15)
        res.ok("Edge вышел сразу, лист дописан позже и кусками — дождались целого",
               got == _FAKE_PDF, repr(got)[:80])
        res.ok("ожидание — доли секунды, не потолок", took < 10, f"{took:.1f} с")
        got, took = run("torn", 3)
        res.check("лист оборван (нет %%EOF) — отказ, половина не отдана", got, "pdf_err")
        res.ok("отказ пришёл к потолку, а не через минуту", 2.5 < took < 12, f"{took:.1f} с")
        got, took = run("never", 2)
        res.check("листа нет до потолка — отказ", got, "pdf_err")
        res.ok("и здесь к потолку", 1.5 < took < 12, f"{took:.1f} с")
        res.check("временное печати убрано при любом исходе", pdf.leftovers(), [])
    finally:
        pdf._room, pdf.TIMEOUT_S = keep[0], keep[1]
        for key, old in (("DENTART_EDGE", keep[2]), ("FAKE_EDGE", keep[3])):
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old
        _rmtree_settled(tmp)


def suite_sign_sheets(res: Result) -> None:
    """Листы в режиме подписи (без сервера): картинка вместо линии, A4;
    без подписи — прежний лист; разбор тела — по белому списку."""
    from app.modules.patients import acord as pacord
    from app.modules.patients import anamneza as panam
    from app.modules.patients import plan_acord as pplan
    from app.modules.patients import sign as psign
    p = {"id": 5, "name": "Ion <b>Popa</b>", "phone": "060", "file_no": "", "idnp": "",
         "birth_date": None, "address": ""}
    plan = [{"status": "planificat", "tooth": 11, "procedure": "Obt", "doctor": "Dr A",
             "due_date": None, "price_mdl": 100}]
    code, field, sign = psign.parse("acord_plan", {
        "signer": "reprezentant", "signer_name": "Ana <i>X</i>", "sig_patient": SIG,
        "sig_doctor": SIG, "pressure": [1], "timestamps": [1, 2]})
    res.check("тело разобрано: только белый список (нажим и время не читаются)",
              (code, sorted(sign)), ("", ["consents", "doctor", "name", "patient", "signer"]))
    res.ok("PNG перекодирован сервером", sign["patient"].startswith("data:image/png;base64,")
           and sign["patient"] != SIG, "картинка уехала как пришла")
    for name, plain, signed in (
        ("acord", pacord.render(p, "ro"), pacord.render(p, "ro", sign=sign)),
        ("plan-acord", pplan.render(p, plan, "", "ro"), pplan.render(p, plan, "", "ro", sign=sign)),
        ("анкета", panam.render_form(p, "ro"),
         panam.render_form(p, "ro", sign=sign, anam={"flags": "cardio", "alergii": "x"})),
    ):
        res.ok(f"{name}: без подписи — прежний лист (кнопки, без A4 и картинок)",
               "noprint" in plain and "size:A4" not in plain and "class='sig'" not in plain, name)
        res.ok(f"{name}: с подписью — картинка, A4, имя представителя экранировано",
               "class='sig'" in signed and "size:A4" in signed
               and "Ana &lt;i&gt;X&lt;/i&gt;" in signed and "<i>X</i>" not in signed, name)
    two = pplan.render(p, plan, "", "ro", sign=sign).count("class='sig'")
    res.check("plan-acord: подпись представителя и врача (без блока отказа — две)", two, 2)
    acc = pacord.render(p, "ro", sign={**sign, "consents": {"mkt": True, "photo": False}})
    res.check("acord: DA маркетинга и NU фото закрашены, остальные пусты",
              acc.count("chk on"), 2)
