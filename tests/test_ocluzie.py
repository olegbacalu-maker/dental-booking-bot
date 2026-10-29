"""Прикус — графа «Ocluzia» формы 043/e (26.10.2026, волна 3 одонтограммы).

До того графа печаталась жёлтым пропуском. Проверяется не «форма сохранилась»,
а что запись доехала до бумаги (раздел 4 листа на обоих языках), до выгрузки
по 195-му и что она — медзапись (держит фишу от физического стирания,
переживает обезличивание). И граница прайора 08-16: отсутствие поля в теле
значит «не сообщали», а не «стереть»; пересохранение без правки тождественно.
⛔ Никаких норм: пустая запись печатает прежнюю черту, а не «norm».
"""
import io
import json
import sqlite3
import sys

from harness import BOT, Client, Result, Server, new_patient

sys.path.insert(0, str(BOT))
from app import db as appdb  # noqa: E402

OCCL = "/api/patients/{pid}/ocluzie"
FULL = {"angle_dr": "I", "angle_st": "II/1", "overjet": "3", "overbite": "2,5",
        "incrucisata": "13–43", "deschisa": "frontal 12–22",
        "mediana_mm": "2", "mediana_spre": "dreapta", "nota": "abraziune 31–41",
        "doctor": "Dr. Activ Doi"}


def _card(c: Client, pid) -> dict:
    return json.loads(c.get(f"/api/patients/{pid}").body)["data"]


def _feed(c: Client, pid) -> list[str]:
    return [a["text"] for a in _card(c, pid)["activity"]["items"]]


def _sect4(c: Client, pid, lang: str = "") -> str:
    """Раздел 4 листа 043/e — от его заголовка до следующего."""
    q = f"?lang={lang}" if lang else ""
    body = c.get(f"/admin/patient/{pid}/fisa043{q}").body
    head = "4. Date obiective" if lang != "ru" else "4. Объективные данные"
    return body.split(head, 1)[1].split("<h2>", 1)[0]


def _occl(sect: str) -> str:
    """Кусок строки «Ocluzia: …» до «Examen radiologic» (на любом языке):
    строка mucoasa выше ВСЕГДА жёлтый пропуск, и смотреть надо только графу."""
    head = "Ocluzia:" if "Ocluzia:" in sect else "Прикус:"
    tail = "Examen radiologic" if head == "Ocluzia:" else "Рентгенологическое"
    return sect.split(head, 1)[1].split(tail, 1)[0]


def _row(s: Server, pid) -> tuple:
    """Строка записи из базы — поля без даты/автора (тождественность)."""
    con = sqlite3.connect(str(s.dir / "dental.db"))
    try:
        cols = ", ".join(appdb.OCLUZIE_FIELDS)
        return con.execute(f"SELECT {cols} FROM ocluzie WHERE patient_id = ?",
                           (int(pid),)).fetchone()
    finally:
        con.close()


def suite(res: Result) -> None:
    """Запись → фиша и лист; «не сообщали» ≠ «стереть»; белые списки."""
    with Server() as s:
        c = Client(s.url).login()
        pid = new_patient(c, "Ocluzia Test", "022171717")

        card = _card(c, pid)
        res.ok("секция прикуса в фише", "ocluzie" in card, "нет секции")
        res.check("не записан — filled false, сводка пустая",
                  (card["ocluzie"]["filled"], card["ocluzie"]["summary"]), (False, ""))
        res.check("справочник формы: классы Энгля с «neevaluat» первым",
                  [x["id"] for x in card["options"]["ocluzie"]["angle"]],
                  ["", "I", "II/1", "II/2", "III"])
        res.ok("на листе графа пустая — прежняя черта, без слова «norm»",
               "class='fill'" in _occl(_sect4(c, pid))
               and "norm" not in _sect4(c, pid).lower(),
               "пустая запись не печатается пропуском")

        res.check("пустая форма на пустой записи — промах",
                  c.post_json(OCCL.format(pid=pid), {"nota": "  "}).msg, "bad_occl")
        res.check("нет записи после промаха", _row(s, pid), None)

        r = c.post_json(OCCL.format(pid=pid), FULL)
        res.check("запись сохраняется", r.msg, "ok_occl")
        oc = json.loads(r.body)["data"]["ocluzie"]
        res.check("поля вернулись в форму (запятая → точка в мм)",
                  (oc["fields"]["angle_st"], oc["fields"]["overbite"], oc["fields"]["doctor"]),
                  ("II/1", "2.5", "Dr. Activ Doi"))
        res.check("сводка — та же строка, что на листе",
                  oc["summary"],
                  "Angle dr. I, stg. II/1 · overjet 3 mm · overbite 2.5 mm · "
                  "încrucișată: 13–43 · deschisă: frontal 12–22 · "
                  "linia mediană: 2 mm spre dreapta · abraziune 31–41")
        res.ok("видно, кто и когда записал", oc["when"] and oc["author"], "нет авторства")
        res.ok("событие в летописи",
               any(t.startswith("Ocluzia înregistrată") for t in _feed(c, pid)), "летопись молчит")

        # ⚠️ прайор 08-16: пересохранение без правки — тождественно
        before = _row(s, pid)
        res.check("пересохранение той же формы — ok", c.post_json(OCCL.format(pid=pid), FULL).msg, "ok_occl")
        res.check("…и строка базы та же", _row(s, pid), before)

        # ключ отсутствует → значение цело; пустая строка → стёрто
        res.check("одно поле отдельно — ok",
                  c.post_json(OCCL.format(pid=pid), {"overjet": "4"}).msg, "ok_occl")
        after = _row(s, pid)
        res.check("присланное поменялось, остальное цело (не сообщали ≠ стереть)",
                  after, tuple("4" if k == "overjet" else v
                               for k, v in zip(appdb.OCLUZIE_FIELDS, before)))
        res.check("пустая строка стирает поле",
                  c.post_json(OCCL.format(pid=pid), {"deschisa": ""}).msg, "ok_occl")
        res.check("…только его", _row(s, pid),
                  tuple("" if k == "deschisa" else v for k, v in zip(appdb.OCLUZIE_FIELDS, after)))
        res.ok("правка отмечена в летописи с прежней записью",
               any(t.startswith("Ocluzia actualizată (anterior: Angle dr. I") for t in _feed(c, pid)),
               f"прежняя запись не ушла в летопись: {_feed(c, pid)[:3]}")

        # белые списки — отказ с полем, ничего не пишется
        snap = _row(s, pid)
        for k, v in (("angle_dr", "IV"), ("mediana_spre", "sus"), ("overbite", "mult"),
                     ("overjet", "3.456")):
            r = c.post_json(OCCL.format(pid=pid), {k: v})
            res.check(f"незнакомое {k}={v!r} — отказ с полем",
                      (r.msg, json.loads(r.body).get("field")), ("bad_occl_val", k))
        res.check("после отказов запись не тронута", _row(s, pid), snap)
        res.check("мм с минусом и запятой принимаются",
                  c.post_json(OCCL.format(pid=pid), {"overbite": "-1,5"}).msg, "ok_occl")
        res.check("чужой врач не пишется (как у зуба)",
                  (c.post_json(OCCL.format(pid=pid), {"doctor": "Dr. Nimeni"}).msg,
                   _row(s, pid)[appdb.OCLUZIE_FIELDS.index("doctor")]), ("ok_occl", ""))

        # снятие до пустого на СУЩЕСТВУЮЩЕЙ записи — законно
        r = c.post_json(OCCL.format(pid=pid), {k: "" for k in appdb.OCLUZIE_FIELDS})
        res.check("пустое сохранение существующей записи — снятие, не промах", r.msg, "ok_occl")
        oc = json.loads(r.body)["data"]["ocluzie"]
        res.check("запись есть, но пустая: filled true, сводка пуста",
                  (oc["filled"], oc["summary"]), (True, ""))
        res.ok("на листе снова черта", "class='fill'" in _occl(_sect4(c, pid)),
               "снятая запись печатает не черту")

        anon = Client(s.url)
        res.check("без входа не пишется (JSON API — 401)",
                  anon.post_json(OCCL.format(pid=pid), FULL).status, 401)


def suite_print(res: Result) -> None:
    """Лист 043/e на обоих языках: термины не переводятся, единицы и подписи —
    да; дата и врач записи рядом; пустая запись — черта."""
    with Server() as s:
        c = Client(s.url).login()
        pid = new_patient(c, "Ocluzia Print", "022172727")
        c.post_json(OCCL.format(pid=pid), FULL)
        ro = _sect4(c, pid)
        res.ok("румынский лист: вся строка",
               "Ocluzia: Angle dr. I, stg. II/1 · overjet 3 mm · overbite 2.5 mm · "
               "încrucișată: 13–43 · deschisă: frontal 12–22 · "
               "linia mediană: 2 mm spre dreapta · abraziune 31–41" in ro,
               f"строка прикуса не та: {ro[:400]}")
        res.ok("дата и врач записи рядом", "Dr. Activ Doi)" in ro and "<small>(" in ro,
               "нет даты/врача записи")
        res.ok("жёлтого пропуска у графы нет, у рентгена остался",
               "class='fill'" not in _occl(ro)
               and "class='fill'" in ro.split("Examen radiologic")[1],
               "пропуски не на месте")
        ru = _sect4(c, pid, "ru")
        res.ok("русский лист: подписи и единицы переведены, термины — нет",
               "Прикус: Angle спр. I, сл. II/1 · overjet 3 мм · overbite 2.5 мм · "
               "перекрёстный: 13–43 · открытый: frontal 12–22 · "
               "средняя линия: 2 мм вправо · abraziune 31–41" in ru,
               f"русская строка не та: {ru[:400]}")

        # одинаковые классы с двух сторон — одним словом; только одна сторона
        c.post_json(OCCL.format(pid=pid), {"angle_dr": "II/2", "angle_st": "II/2"})
        res.ok("класс один на обе стороны — «Angle II/2»",
               "Ocluzia: Angle II/2 ·" in _sect4(c, pid), "обе стороны печатаются порознь")
        c.post_json(OCCL.format(pid=pid), {"angle_st": ""})
        res.ok("оценена одна сторона — только она",
               "Ocluzia: Angle dr. II/2 ·" in _sect4(c, pid), "пустая сторона печатается")

        # ⚠️ XSS-класс: заметка — данные, на листе экранируется
        c.post_json(OCCL.format(pid=pid), {"nota": "<img src=x onerror=alert(1)>"})
        sect = _sect4(c, pid)
        res.ok("заметка на листе экранирована", "<img" not in sect and "&lt;img" in sect,
               "заметка прикуса попала в разметку листа")


def suite_195(res: Result) -> None:
    """Медзапись: выгрузка по 195-му, стирание только обезличиванием, запись
    переживает обезличивание под номером фиши."""
    with Server() as s:
        c = Client(s.url).login()
        pid = new_patient(c, "Erase Ocluzia", "022173737")
        res.check("без записи фиша удаляется физически", _card(c, pid)["erasure"], "delete")
        c.post_json(OCCL.format(pid=pid), {"angle_dr": "III"})
        # ⚠️ мутация: убери счётчик ocluzie из erasure_kind — фиша с одной
        # записью прикуса уйдёт в физическое удаление, и медзапись исчезнет
        res.check("с записью прикуса — только обезличивание", _card(c, pid)["erasure"], "anon")

        import zipfile
        z = zipfile.ZipFile(io.BytesIO(c.get(f"/admin/patient/{pid}/export").raw))
        data = json.loads(z.read("date-pacient.json").decode("utf-8"))
        res.check("прикус в машинной копии", data["ocluzie"]["angle_dr"], "III")
        html = z.read("fisa-pacient.html").decode("utf-8")
        res.ok("прикус в читаемой копии — раздел и строка листа",
               "<h2>Ocluzia</h2>" in html and "Angle dr. III" in html,
               "HTML-копия без прикуса")
        res.ok("состав выгрузки = состав удаления",
               "ocluzie" in appdb._PATIENT_CHILD_TABLES, "таблицы нет в _PATIENT_CHILD_TABLES")

        res.check("обезличивание проходит",
                  c.post_json(f"/api/patients/{pid}/erase", {"confirm": "STERG"}).msg, "ok_anon")
        res.ok("запись прикуса осталась под номером фиши",
               "Angle dr. III" in _sect4(c, pid), "обезличивание стёрло медзапись")
        res.ok("личность стёрта", _card(c, pid)["name"].startswith("Pacient anonimizat"),
               "имя пережило обезличивание")

        # физическое стирание фиши без медзаписей сносит и таблицу (FK-дети)
        pid2 = new_patient(c, "Delete Ocluzia", "022174747")
        res.check("физическое удаление проходит",
                  c.post_json(f"/api/patients/{pid2}/erase", {"confirm": "STERG"}).msg, "ok_del")


def suite_schema(res: Result) -> None:
    """DDL шага 7 и схемы — один текст: расхождение дало бы разные таблицы у
    свежей базы и у обновлённой, молча."""
    res.ok("OCLUZIE_DDL дословно в SQLITE_CARD_SCHEMA",
           appdb.OCLUZIE_DDL in appdb.SQLITE_CARD_SCHEMA,
           "текст таблицы в схеме и в шаге 7 разошёлся")
    res.check("шаг 7 кладёт именно его", appdb.MIGRATIONS[7], [appdb.OCLUZIE_DDL])
    res.ok("версия схемы не ниже 7 (шаг 8 — Rechemări, 29.10)", appdb.SCHEMA_VERSION >= 7,
           f"{appdb.SCHEMA_VERSION}")
