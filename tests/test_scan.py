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
import struct
import tempfile
import zlib

from harness import Client, Result, Server


def _j(r) -> dict:
    return json.loads(r.body)


def _pid(c: Client, phone: str) -> int:
    return int(c.get(f"/admin/search?q={phone}").body.split(
        "<tr id='plr", 1)[1].split("'", 1)[0])


def _png(w: int = 48, h: int = 64) -> bytes:
    """Настоящий PNG (серый прямоугольник) — Pillow его откроет; поддельного
    заголовка из test_patient_card здесь мало: сканер собирает PDF из пикселей."""
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))
    raw = b"".join(b"\x00" + bytes([200]) * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


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
