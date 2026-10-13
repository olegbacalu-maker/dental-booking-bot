"""Пародонтограмма: шесть точек на зуб, датированным осмотром.

Ломается такое молча: ответ 200, а числа уехали на соседнюю точку или прошлый
осмотр тихо переписан. Поэтому здесь проверяется не «запись прошла», а что
измерения доехали до ЧЕТЫРЁХ представлений — экран (модель JSON API, которую
рисует React; до 13.10 — старая страница), печатный лист, §4 печатной 043/e,
выгрузка по 195-му, — что арифметика итога совпадает с посчитанной руками и
что чужие зубы и прошлые осмотры не затираются.
"""
import io
import json
import zipfile

from harness import Client, Result, Server, pid_by_phone

# Все постоянные зубы. ⚠️ Целиком они попадают в поле `covers` только здесь:
# проверки правят карту разом, а живой лист называет лишь ТРОНУТЫЕ зубы.
PERM = ([18, 17, 16, 15, 14, 13, 12, 11, 21, 22, 23, 24, 25, 26, 27, 28]
        + [48, 47, 46, 45, 44, 43, 42, 41, 31, 32, 33, 34, 35, 36, 37, 38])


def _row(pd=None, rec=None, bop="000000", mob=0, furc=0) -> dict:
    """Строка зуба ЦЕЛИКОМ — так её шлёт экран и только так принимает API."""
    return {"pd": pd or [0] * 6, "rec": rec or [0] * 6, "bop": bop, "mob": mob, "furc": furc}


# 16: шесть точек, две кровоточат, карманы 4 и 5 мм, подвижность I, фуркация II
# 46: ровные двойки без кровоточивости
CHART = {"16": _row(pd=[3, 2, 3, 4, 2, 5], rec=[1, 0, 0, 0, 0, 2], bop="010010", mob=1, furc=2),
         "46": _row(pd=[2] * 6)}


def _new_exam(c: Client, api: str) -> int:
    """Новый осмотр (`POST …/perio/exams`) и его id."""
    return json.loads(c.post_json(f"{api}/perio/exams", {}).body)["data"]["exam"]["id"]


def _model(c: Client, api: str, exam: int | None = None) -> dict:
    """Пародонтограмма данными — то, что рисует экран."""
    q = f"?exam={exam}" if exam else ""
    return json.loads(c.get(f"{api}/perio{q}").body)["data"]


def suite_perio(res: Result) -> None:
    with Server() as s:
        c = Client(s.url).login()
        c.post_json("/api/patients", {"name": "Perio Test", "phone": "022676767"})
        pid = pid_by_phone(c, "022676767")
        base = f"/admin/patient/{pid}"
        api = f"/api/patients/{pid}"

        # --- пустое состояние: GET ничего не создаёт ---
        res.check("пустая карта — осмотров нет, экран предложит начать",
                  (_model(c, api)["exam"], _model(c, api)["exams"]), (None, []))
        c.get(f"{base}/parodontograma")
        res.check("GET (и страница, и данные) не плодит осмотры", _model(c, api)["exams"], [])

        # --- осмотр и первые измерения ---
        eid = _new_exam(c, api)
        r = c.post_json(f"{api}/perio/{eid}", {"teeth": CHART, "covers": PERM,
                                               "doctor": "Dr. Activ Doi", "note": "reevaluare"})
        res.check("измерения сохраняются", r.msg, "ok_perio")

        m = _model(c, api, eid)
        res.check("значения доехали до своих точек",
                  (m["rows"]["16"]["pd"], m["rows"]["16"]["rec"], m["rows"]["46"]["pd"]),
                  ([3, 2, 3, 4, 2, 5], [1, 0, 0, 0, 0, 2], [2] * 6))
        res.check("кровоточивость отмечена на своих точках", m["rows"]["16"]["bop"], "010010")
        # арифметика: 12 измеренных точек, 2 кровоточат → 17%;
        # сумма 31 мм / 12 = 2.6; карманов ≥4 мм — два (4 и 5)
        sm = m["summary"]
        res.check("BOP считается от ИЗМЕРЕННЫХ точек", (sm["sites"], sm["bop"]), (12, 17))
        res.check("средняя глубина", sm["pd_mean"], 2.6)
        res.check("карманы ≥4 мм посчитаны, глубоких 6+ нет", (sm["deep"], sm["severe"]), (2, 0))
        res.check("порог глубокого кармана — серверный", m["limits"]["deep"], 4)

        # --- летопись говорит словами ---
        feed = [a["text"] for a in json.loads(c.get(api).body)["data"]["activity"]["items"]]
        res.ok("летопись называет итог словами",
               any("BOP 17%" in t and "pungi 4+ mm: 2" in t for t in feed),
               f"в ленте фиши нет строки пародонтограммы: {feed}")

        # --- печатный лист ---
        sheet = c.get(f"{base}/parodontograma/print").body
        res.ok("печатный лист несёт измерения",
               "Parodontogramă" in sheet and "3 2 3" in sheet,
               "на листе нет строки точек")
        # ⚠️ Кружок кровоточивости рисуется СТИЛЯМИ, а не знаком: U+25CF во
        # вшитый Inter не входит, и на бумаге его рисовал бы шрифт Windows.
        res.ok("на листе видна кровоточивость", "class='bd'" in sheet,
               "кровоточивость на бумаге пропала")
        res.ok("непомеренная точка — точкой, а не нулём", "·" in sheet,
               "пустое место на листе читается как измеренный ноль")
        res.ok("лист объясняет обозначения", "CAL = PD + recesiune" in sheet,
               "без легенды лист нечитаем чужим врачом")

        # --- §4 печатной 043/e, оба языка ---
        fisa = c.get(f"{base}/fisa043").body
        res.ok("043/e несёт строку состояния пародонта",
               "Stare parodontală" in fisa and "BOP 17%" in fisa,
               "в §4 нет итога пародонтограммы")
        fisa_ru = c.get(f"{base}/fisa043?lang=ru").body
        res.ok("русский бланк говорит по-русски",
               "Состояние пародонта" in fisa_ru and "средняя глубина" in fisa_ru,
               "итог пародонта остался румынским на русском бланке")

        # --- выгрузка по 195-му: точки ИМЕНАМИ, а не позиционным кодом ---
        z = zipfile.ZipFile(io.BytesIO(c.get(f"{base}/export").raw))
        doc = z.read([n for n in z.namelist()
                      if n.endswith(".html")][0]).decode("utf-8")
        res.ok("выгрузка несёт раздел пародонтограммы",
               "Parodontogramă" in doc and "MV 3" in doc,
               "в копии по 195-му измерений нет или они позиционным кодом")

        # --- дисциплина разбора: мусор до базы не доезжает ---
        eid2 = _new_exam(c, api)
        r = c.post_json(f"{api}/perio/{eid2}", {"teeth": {"55": _row(pd=[3] * 6),   # молочный
                                                          "99": _row(pd=[3] * 6)},  # чужой номер
                                                "covers": PERM})
        res.check("молочный и чужой номер на лист не попадают",
                  (r.msg, _model(c, api, eid2)["rows"]), ("ok_perio", {}))
        for tooth, row, why in (("17", _row(pd=[99] * 6), "99 мм — опечатка ввода"),
                                ("27", _row(), "пустой зуб")):
            r = c.post_json(f"{api}/perio/{eid2}", {"teeth": {tooth: row}, "covers": PERM})
            res.check(f"{why}: ни одного показания — отказ, а не запись нулями",
                      (r.status, r.msg), (422, "bad_perio"))
        res.check("после всех попыток лист пуст", _model(c, api, eid2)["summary"]["teeth"], 0)

        # --- ⛔ зуб, о котором запись не сообщала, не стирается ---
        r = c.post_json(f"{api}/perio/{eid}", {"teeth": {"16": CHART["16"]}, "covers": [16]})
        res.check("узкая запись сохраняется", r.msg, "ok_perio")
        res.check("зуб, о котором не сообщали, НЕ стёрт",
                  (sorted(_model(c, api, eid)["rows"]), _model(c, api, eid)["rows"]["46"]["pd"]),
                  (["16", "46"], [2] * 6))

        # --- пересохранение без правок тождественно ---
        before = _model(c, api, eid)
        c.post_json(f"{api}/perio/{eid}", {"teeth": CHART, "covers": PERM,
                                           "doctor": "Dr. Activ Doi", "note": "reevaluare"})
        after = _model(c, api, eid)
        res.ok("пересохранение без правок ничего не меняет",
               (before["rows"], before["summary"], before["exam"], before["rev"])
               == (after["rows"], after["summary"], after["exam"], after["rev"]),
               "тот же ввод дал другой результат — где-то состояние копится")

        # --- осмотры независимы ---
        c.post_json(f"{api}/perio/{eid2}", {"teeth": {"36": _row(pd=[4] * 6, bop="111111")},
                                            "covers": PERM})
        res.check("прошлый осмотр не тронут новым", _model(c, api, eid)["summary"]["bop"], 17)

        # --- удаление осмотров ---
        empty = _new_exam(c, api)
        r = c.post_json(f"{api}/perio/{empty}/delete", {})
        res.check("пустой осмотр снимается", r.msg, "ok_perio_del")
        r = c.post_json(f"{api}/perio/{eid}/delete", {})
        res.check("осмотр с измерениями не удаляется", r.msg, "bad_perio_del")

        # --- чужой осмотр по прямому адресу ---
        other = Client(s.url).login()
        other.post_json("/api/patients", {"name": "Perio Altul", "phone": "022686868"})
        pid2 = pid_by_phone(other, "022686868")
        r = other.post_json(f"/api/patients/{pid2}/perio/{eid}",
                            {"teeth": {"11": _row(pd=[3] * 6)}, "covers": PERM})
        res.check("чужой id осмотра отбивается", r.msg, "bad_perio")
        res.check("чужие измерения не приписаны", _model(c, api, eid)["summary"]["bop"], 17)

        # --- пародонтограмма — медицинская запись: фиша обезличивается ---
        third = Client(s.url).login()
        third.post_json("/api/patients", {"name": "Perio Erase", "phone": "022696969"})
        pid3 = pid_by_phone(third, "022696969")
        api3 = f"/api/patients/{pid3}"
        e3 = _new_exam(third, api3)
        third.post_json(f"{api3}/perio/{e3}", {"teeth": {"21": _row(pd=[3] * 6)}, "covers": PERM})
        r = third.post_json(f"{api3}/erase", {"confirm": "STERG"})
        res.check("фиша с осмотром обезличивается, а не стирается",
                  r.msg, "ok_anon")
