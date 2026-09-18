"""Пародонтограмма: шесть точек на зуб, датированным осмотром.

Ломается такое молча: страница отвечает 200, а числа уехали на соседнюю точку
или прошлый осмотр тихо переписан. Поэтому здесь проверяется не «форма
сохранилась», а что измерения доехали до ЧЕТЫРЁХ представлений — экран,
печатный лист, §4 печатной 043/e, выгрузка по 195-му, — что арифметика итога
совпадает с посчитанной руками и что чужие зубы и прошлые осмотры не
затираются.
"""
import io
import re
import zipfile

from harness import Client, Result, Server


def _pid(c: Client, phone: str) -> str:
    return c.get(f"/admin/search?q={phone}").body.split(
        "/admin/patient/", 1)[1].split("'")[0].split('"')[0].split("?")[0]


def _new_exam(c: Client, base: str) -> str:
    """Новый осмотр и его id из адреса возврата."""
    loc = c.post(f"{base}/perio/new").location or ""
    m = re.search(r"exam=(\d+)", loc)
    return m.group(1) if m else "0"


# Все постоянные зубы. ⚠️ Целиком они попадают в поле `covers` только здесь:
# проверки правят карту разом, а живой лист называет лишь ТРОНУТЫЕ зубы.
ALL_TEETH = ",".join(str(n) for n in (
    [18, 17, 16, 15, 14, 13, 12, 11, 21, 22, 23, 24, 25, 26, 27, 28]
    + [48, 47, 46, 45, 44, 43, 42, 41, 31, 32, 33, 34, 35, 36, 37, 38]))

# 16: шесть точек, две кровоточат, карманы 4 и 5 мм, подвижность I, фуркация II
# 46: ровные двойки без кровоточивости
CHART = ("16:3,2,3,4,2,5/1,0,0,0,0,2/010010/1/2;"
         "46:2,2,2,2,2,2/0,0,0,0,0,0/000000/0/0")


def suite_perio(res: Result) -> None:
    with Server() as s:
        c = Client(s.url).login()
        c.post("/admin/patients/new", name="Perio Test", phone="022676767")
        pid = _pid(c, "022676767")
        base = f"/admin/patient/{pid}"

        # --- пустое состояние: GET ничего не создаёт ---
        page = c.get(f"{base}/parodontograma").body
        res.ok("пустая карта предлагает начать осмотр",
               "niciun examen parodontal" in page and "Începe primul" in page,
               "нет экрана «осмотров ещё нет»")
        c.get(f"{base}/parodontograma")
        res.ok("GET не плодит осмотры",
               "niciun examen parodontal" in c.get(f"{base}/parodontograma").body,
               "обновление страницы завело осмотр — так их будут десятки")

        # --- осмотр и первые измерения ---
        eid = _new_exam(c, base)
        r = c.post(f"{base}/perio", exam=eid, chart=CHART, covers=ALL_TEETH,
                   doctor="Dr. Activ Doi", note="reevaluare")
        res.check("измерения сохраняются", r.msg, "ok_perio")

        page = c.get(f"{base}/parodontograma").body
        res.ok("значения доехали до полей",
               "value='5'" in page and "value='3'" in page,
               "чисел нет на странице")
        res.ok("карман ≥4 мм подсвечен",
               "pcell deep" in page,
               "глубокий карман ничем не отличается от здоровой борозды")
        res.ok("кровоточивость отмечена", "pdot on" in page,
               "точка кровоточивости не сохранилась")

        # арифметика: 12 измеренных точек, 2 кровоточат → 17%;
        # сумма 31 мм / 12 = 2.6; карманов ≥4 мм — два (4 и 5)
        res.ok("BOP считается от ИЗМЕРЕННЫХ точек", "<b>17%</b>" in page,
               "процент кровоточивости не 17 — знаменатель не тот")
        res.ok("средняя глубина", "<b>2.6 mm</b>" in page, "средняя не 2.6")
        res.ok("карманы ≥4 мм посчитаны", "<b>2</b>" in page, "не два кармана")

        # --- летопись говорит словами ---
        card = c.get(base).body
        res.ok("летопись называет итог словами",
               "BOP 17%" in card and "pungi 4+ mm: 2" in card,
               "в ленте фиши нет строки пародонтограммы")

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

        # --- дисциплина разбора ---
        eid2 = _new_exam(c, base)
        c.post(f"{base}/perio", exam=eid2, covers=ALL_TEETH,
               chart="55:3,3,3,3,3,3/0/000000/0/0;"      # молочный
                     "99:3,3,3,3,3,3/0/000000/0/0;"      # чужой номер
                     "17:99,99,99,99,99,99/0/000000/0/0;"  # 99 мм — опечатка
                     "27:0,0,0,0,0,0/0/000000/0/0")      # пустой зуб
        page2 = c.get(f"{base}/parodontograma?exam={eid2}").body
        # ⚠️ Ищем именно ПОЛЕ ввода: «value='3'» есть и у <option> подвижности,
        # и проверка без maxlength зеленела бы на любой странице.
        res.ok("мусор не сохраняется",
               "maxlength='2' value='3'" not in page2
               and "<span>Dinți măsurați</span><b>0</b>" in page2,
               "молочный, чужой номер, 99 мм или пустой зуб доехали до базы")

        # --- ⛔ зуб, о котором форма не сообщала, не стирается ---
        r = c.post(f"{base}/perio", exam=eid, chart="16:3,2,3,4,2,5/1,0,0,0,0,2/010010/1/2",
                   covers="16")
        res.check("узкая форма сохраняется", r.msg, "ok_perio")
        page = c.get(f"{base}/parodontograma?exam={eid}").body
        res.ok("зуб, о котором не сообщали, НЕ стёрт",
               "<b>2</b>" in page and "value='2'" in page,
               "форма на один зуб стёрла остальные — «поля нет» приняли за "
               "«стереть» (грабля 08-16)")

        # --- пересохранение без правок тождественно ---
        before = c.get(f"{base}/parodontograma?exam={eid}").body
        c.post(f"{base}/perio", exam=eid, chart=CHART, covers=ALL_TEETH,
               doctor="Dr. Activ Doi", note="reevaluare")
        after = c.get(f"{base}/parodontograma?exam={eid}").body
        res.ok("пересохранение без правок ничего не меняет",
               before == after,
               "тот же ввод дал другой результат — где-то состояние копится")

        # --- осмотры независимы ---
        c.post(f"{base}/perio", exam=eid2, chart="36:4,4,4,4,4,4/0/111111/0/0",
               covers=ALL_TEETH)
        first = c.get(f"{base}/parodontograma?exam={eid}").body
        res.ok("прошлый осмотр не тронут новым",
               "<b>17%</b>" in first,
               "новый осмотр переписал измерения прошлого — сравнивать во "
               "времени станет нечего")

        # --- удаление осмотров ---
        empty = _new_exam(c, base)
        r = c.post(f"{base}/perio/{empty}/del")
        res.check("пустой осмотр снимается", r.msg, "ok_perio_del")
        r = c.post(f"{base}/perio/{eid}/del")
        res.check("осмотр с измерениями не удаляется", r.msg, "bad_perio_del")

        # --- чужой осмотр по прямому адресу ---
        other = Client(s.url).login()
        other.post("/admin/patients/new", name="Perio Altul", phone="022686868")
        pid2 = _pid(other, "022686868")
        r = other.post(f"/admin/patient/{pid2}/perio", exam=eid,
                       chart="11:3,3,3,3,3,3/0/000000/0/0", covers=ALL_TEETH)
        res.check("чужой id осмотра отбивается", r.msg, "bad_perio")
        res.ok("чужие измерения не приписаны",
               "<b>17%</b>" in c.get(f"{base}/parodontograma?exam={eid}").body,
               "осмотр одного пациента дописан из фиши другого")

        # --- пародонтограмма — медицинская запись: фиша обезличивается ---
        third = Client(s.url).login()
        third.post("/admin/patients/new", name="Perio Erase", phone="022696969")
        pid3 = _pid(third, "022696969")
        e3 = _new_exam(third, f"/admin/patient/{pid3}")
        third.post(f"/admin/patient/{pid3}/perio", exam=e3, covers=ALL_TEETH,
                   chart="21:3,3,3,3,3,3/0/000000/0/0")
        r = third.post(f"/admin/patient/{pid3}/erase", confirm="STERG")
        res.check("фиша с осмотром обезличивается, а не стирается",
                  r.msg, "ok_anon")
