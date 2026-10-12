"""Сканер (01.10): «Scanează» во вкладке «Documente» — лист за листом в сессию
пациента, «Salvează» склеивает их в один PDF с категорией бланка.

⚠️ Живого сканера в прогоне нет и быть не должно: настоящий WIA на машине со
сканером ПОТЯНУЛ БЫ ЛИСТ (и ждал бы его до трёх минут). Поэтому сервер
поднимается с подменой `DENTART_SCAN_FAKE=<png>` — путь, которым живёт весь
модуль, кроме самого разговора с драйвером. Ветка ошибки — подмена на
несуществующий файл: статус «нет сканера», лист не берётся.
"""
import json
import os
import pathlib
import re
import struct
import subprocess
import sys
import tempfile
import zlib

from harness import Client, Result, Server

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "bot"))
from app.modules.patients import scan as pscan  # noqa: E402


def _j(r) -> dict:
    return json.loads(r.body)


def _pid(c: Client, phone: str) -> int:
    return int(c.get(f"/admin/search?q={phone}").body.split(
        "<tr id='plr", 1)[1].split("'", 1)[0])


def _png(w: int = 48, h: int = 64, dpi: int = 0) -> bytes:
    """Настоящий PNG (серый прямоугольник) — Pillow его откроет; поддельного
    заголовка из test_patient_card здесь мало: сканер собирает PDF из пикселей.
    `dpi` — разрешение в самой картинке (pHYs), как его несёт лист драйвера."""
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))
    raw = b"".join(b"\x00" + bytes([200]) * w for _ in range(h))
    phys = b""
    if dpi:
        ppm = round(dpi / 0.0254)
        phys = chunk(b"pHYs", struct.pack(">IIB", ppm, ppm, 1))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0))
            + phys + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def _boxes(pdf: bytes) -> list[tuple[float, float]]:
    """Размеры страниц PDF в пунктах (1/72 дюйма) — из /MediaBox каждой."""
    return [(float(w), float(h)) for w, h in
            re.findall(rb"/MediaBox\s*\[\s*0\s+0\s+([\d.]+)\s+([\d.]+)\s*\]", pdf)]


def _near(got: list[tuple[float, float]], want: list[tuple[float, float]]) -> bool:
    return len(got) == len(want) and all(
        abs(a - c) < 0.05 and abs(b - d) < 0.05 for (a, b), (c, d) in zip(got, want))


# Поддельные свойства 6147 для `Pick-Dpi`: (описание, PowerShell-объект, ждём).
_PICK_CASES = (
    ("список Canon 150/300/600 → 300 (200 нет — ближайшее выше)",
     "[pscustomobject]@{SubType=2; SubTypeValues=@(150,300,600)}", 300),
    ("список с 200 → ровно 200",
     "[pscustomobject]@{SubType=2; SubTypeValues=@(600,75,200,100,300,150)}", 200),
    ("выше просимого ничего — наибольшее (150)",
     "[pscustomobject]@{SubType=2; SubTypeValues=@(75,150)}", 150),
    ("диапазон 50..1200 шаг 1 → 200",
     "[pscustomobject]@{SubType=1; SubTypeMin=50; SubTypeMax=1200; SubTypeStep=1}", 200),
    ("диапазон 75..600 шаг 75 → 225 (ступень выше 200)",
     "[pscustomobject]@{SubType=1; SubTypeMin=75; SubTypeMax=600; SubTypeStep=75}", 225),
    ("диапазон от 300 → 300",
     "[pscustomobject]@{SubType=1; SubTypeMin=300; SubTypeMax=1200; SubTypeStep=100}", 300),
    ("свойство без описания — как просили",
     "[pscustomobject]@{SubType=0}", 200),
)


def suite_scan_dpi(res: Result) -> None:
    """Разрешение листа (12.10.2026, первый живой скан у Олега): Canon TS3400
    через WIA принимает 150/300/600, просьба «200» уходила мимо, лист приходил
    в 150 dpi, а PDF считал его двухсотым — страница 75 % от листа. Здесь:
    выбор разрешения скриптом, разбор принятого, размер страницы PDF по
    НАСТОЯЩЕМУ разрешению — от модуля до файла в фише."""
    # выбор разрешения — та же функция PowerShell, что в `_PS_SCAN`
    # ⚠️ Объект — в скобках: в режиме аргументов PowerShell принял бы
    # `[pscustomobject]@{…}` за строку, и скрипт упал бы без вывода
    script = pscan._PS_PICK_DPI + "\n".join(
        f"Write-Output (Pick-Dpi ({obj}) 200)" for _, obj, _ in _PICK_CASES)
    r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive",
                        "-ExecutionPolicy", "Bypass", "-Command", script],
                       capture_output=True, timeout=60)
    got = r.stdout.decode("utf-8", "replace").split()
    res.check("Pick-Dpi отработал на всех поддельных свойствах",
              (r.returncode, len(got)), (0, len(_PICK_CASES)))
    for (name, _, want), g in zip(_PICK_CASES, got + [""] * len(_PICK_CASES)):
        res.check(f"Pick-Dpi: {name}", g, str(want))
    res.ok("скрипт скана выбирает разрешение этой функцией, ставит выбранное и печатает принятое",
           pscan._PS_PICK_DPI in pscan._PS_SCAN
           and "$dpi = Pick-Dpi $p $want" in pscan._PS_SCAN
           and "6147 { $p.Value = $dpi }" in pscan._PS_SCAN
           and 'Write-Output "DPI $x $y"' in pscan._PS_SCAN,
           "выбор, установка или строка DPI выпали из _PS_SCAN")

    res.check("разбор вывода: «DPI 300 300» — принятое разрешение",
              pscan._parse_dpi(b"\r\nDPI 300 300\r\n"), (300.0, 300.0))
    res.check("разбор вывода: пусто и нули — неизвестно",
              (pscan._parse_dpi(b""), pscan._parse_dpi(None), pscan._parse_dpi(b"DPI 0 0")),
              (None, None, None))

    # размер страницы = пиксели ÷ разрешение листа (72 пункта на дюйм)
    a150 = _png(300, 420, dpi=150)
    res.check("PDF: разрешение из самой картинки — 300×420 px при 150 dpi = 144×201,6 pt",
              _near(_boxes(pscan.to_pdf([a150])), [(144.0, 201.6)]), True)
    res.check("PDF: сказанное драйвером важнее записанного в картинке",
              _near(_boxes(pscan.to_pdf([(a150, (300.0, 300.0))])), [(72.0, 100.8)]), True)
    res.check("PDF: разрешения нет нигде — DPI модуля",
              _near(_boxes(pscan.to_pdf([_png(200, 100)])),
                    [(200 * 72 / pscan.DPI, 100 * 72 / pscan.DPI)]), True)
    res.check("PDF: страница с другим разрешением пересчитана — размер листа тот же",
              _near(_boxes(pscan.to_pdf([(a150, None), (_png(600, 840), (300.0, 300.0))])),
                    [(144.0, 201.6), (144.0, 201.6)]), True)

    # весь путь: лист с разрешением → сессия → PDF в фише
    fd, path = tempfile.mkstemp(prefix="dp_scan_fake_", suffix=".png")
    os.write(fd, a150)
    os.close(fd)
    try:
        with Server(env={"DENTART_SCAN_FAKE": path}) as s:
            c = Client(s.url).login()
            c.post("/admin/patients/new", name="Scan Dpi", phone="069777002")
            pid = _pid(c, "069777002")
            c.post_json(f"/api/patients/{pid}/scan/page", {})
            r = c.post_json(f"/api/patients/{pid}/scan/finish", {"category": "alt"})
            d = _j(r)["data"]["documents"][0]
            body = c.get(f"/admin/doc/{d['id']}").raw     # байты: body портит бинарь
            res.check("фиша: PDF скана — лист 150 dpi размером 144×201,6 pt, а не 75 %",
                      (r.status, _near(_boxes(body), [(144.0, 201.6)])), (200, True))
    finally:
        os.unlink(path)


def suite_scan(res: Result) -> None:
    """Статус сканера, страницы сессии, PDF в фише со статусом бланка; без
    сканера — честный отказ."""
    fd, path = tempfile.mkstemp(prefix="dp_scan_fake_", suffix=".png")
    os.write(fd, _png())
    os.close(fd)
    try:
        with Server(env={"DENTART_SCAN_FAKE": path}) as s:
            res.check("без входа статус закрыт — 401",
                      Client(s.url).get("/api/scan/status").status, 401)
            c = Client(s.url).login()
            c.post("/admin/patients/new", name="Scan Test", phone="069777000")
            pid = _pid(c, "069777000")
            j = _j(c.get("/api/scan/status"))
            res.check("сканер есть (подмена)", (j["data"]["ok"], j["data"]["name"]),
                      (True, "Scaner de test"))

            r = c.post_json(f"/api/patients/{pid}/scan/page", {})
            j = _j(r)
            res.check("первый лист — одна страница с превью data:",
                      (r.status, j["data"]["pages"], j["data"]["previews"][0][:22]),
                      (200, 1, "data:image/png;base64,"))
            j = _j(c.post_json(f"/api/patients/{pid}/scan/page", {}))
            res.check("второй лист — две страницы, два превью",
                      (j["data"]["pages"], len(j["data"]["previews"])), (2, 2))

            r = c.post_json(f"/api/patients/{pid}/scan/finish",
                            {"category": "acord_plan",
                             "title": "Acord informat la planul de tratament"})
            j = _j(r)
            d = j["data"]["documents"][0]
            res.check("PDF в фише: код, категория, вид, имя с пациентом и датой",
                      (r.status, j["code"], d["category"], d["view"],
                       d["filename"].endswith(".pdf"), "Scan Test" in d["filename"],
                       d["filename"].startswith("Acord informat la planul de tratament - ")),
                      (200, "ok_scan", "acord_plan", "pdf", True, True, True))
            forms = {f["key"]: f for f in j["data"]["forms"]}
            res.check("бланк acord informat — подписан этим сканом",
                      forms["acord_plan"]["signed"]["doc_id"], d["id"])
            body = c.get(f"/admin/doc/{d['id']}").body
            res.ok("файл — настоящий PDF из двух страниц",
                   body.startswith("%PDF") and body.count("/Type /Page\n") + body.count("/Type /Page ") >= 2
                   or (body.startswith("%PDF") and "/Count 2" in body),
                   f"{body[:40]!r}")
            res.ok("в летописи — загрузка документа",
                   any(a["text"].startswith("Document încărcat: Acord informat")
                       for a in j["data"]["activity"]["items"]),
                   "скан не оставил следа")
            r = c.post_json(f"/api/patients/{pid}/scan/finish", {"category": "alt"})
            res.check("сессия закрыта — повторный finish: 409 scan_empty",
                      (r.status, _j(r)["code"]), (409, "scan_empty"))
            c.post_json(f"/api/patients/{pid}/scan/page", {})
            c.post_json(f"/api/patients/{pid}/scan/cancel", {})
            r = c.post_json(f"/api/patients/{pid}/scan/finish", {"category": "alt"})
            res.check("после cancel страниц нет", (r.status, _j(r)["code"]), (409, "scan_empty"))
            res.check("чужой пациент — 404",
                      c.post_json("/api/patients/777/scan/page", {}).status, 404)
            r = c.post_json(f"/api/patients/{pid}/scan/page", {})
            r = c.post_json(f"/api/patients/{pid}/scan/finish", {"category": "nu_exista"})
            res.check("незнакомая категория — «Alt document»",
                      (r.status, _j(r)["data"]["documents"][0]["category"]), (200, "alt"))
            res.check("текст плашки — из словаря", _j(r)["text"], "Document scanat și salvat în fișă")
    finally:
        os.unlink(path)

    # сканера нет: подмена указывает на файл, которого нет — статус честный,
    # лист не берётся. ⛔ Настоящий путь (WIA) в прогоне не исполняется никогда.
    with Server(env={"DENTART_SCAN_FAKE": path}) as s:
        c = Client(s.url).login()
        c.post("/admin/patients/new", name="Scan Fara", phone="069777001")
        pid = _pid(c, "069777001")
        res.check("статус: сканера нет", _j(c.get("/api/scan/status"))["data"]["ok"], False)
        r = c.post_json(f"/api/patients/{pid}/scan/page", {})
        res.check("лист не берётся — 503 scan_err с текстом",
                  (r.status, _j(r)["code"], "nu a reușit" in _j(r)["text"]),
                  (503, "scan_err", True))
