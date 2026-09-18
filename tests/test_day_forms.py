"""Договор дневных страниц с браузером (C25.5b): запись, карточка, перенос.

Сетку этих страниц уже держат `test_grid` (контракт построителя) и
`test_schedule_api.suite_day_parity` (модель против разметки). Здесь —
ВСЁ ОСТАЛЬНОЕ, что страница кладёт в браузер, чтобы журналом можно было
пользоваться, а не только смотреть на него: список часов формы, диалог «+»,
полезная нагрузка карточки визита и поля переноса.

Пин пишется ДО переноса в React (порядок Олега), и вот почему именно эти
места. Каждое из них расходится молча:

* **Список врачей формы — НЕ колонки сетки.** `/admin/all` кормит форму
  `eng.ACTIVE_DOCTORS`, а сетку — активными ПЛЮС выключенными, у которых есть
  записи этого дня. Возьми React врачей из модели сетки — и регистратура
  выберет выключенного, чтобы получить `bad_off` на ровном месте. У
  разработчика такого врача обычно нет, и списки совпадают.
* **Часы в форме — часы ВРАЧА, и всегда на 30 минут**, независимо от
  длительности услуги. Пересчёт «по-умному» отнял бы 17:30 у получасового
  приёма — час, который сегодня законен.
* **Пустое окно врача подменяется часами клиники** (`or half`): пустой
  `<select>` не отправил бы поле вовсе, и вместо честного отказа вышел бы 422.
* **Комментарий в карточке ПОЛНЫЙ, а в сетке обрезан до 60.** Возьми React
  текст из карточки сетки — и пересохранение БЕЗ единой правки укоротит
  комментарий (прайор 08-16: пересохранение обязано быть тождественным).
* **CS_SHOW — транспонированный `_ACT_BUTTONS`.** Две записи одного правила;
  разойдутся — закрытая запись потеряет кнопку возврата в одном месте и
  сохранит в другом.
* **Перенос на СВОЁ место сервер принимает** (`ok_move` и строка в летописи).
  Значит, «бросили туда же — ничего не делать» обязано жить в браузере, и это
  не украшение.
"""
import json
import re
from datetime import timedelta

from harness import Client, Result, Server, clinic_today

# --------------------------------------------------------------- разборщики


def _form(body: str) -> str:
    """Нижняя форма записи целиком (пусто — формы на странице нет)."""
    if '<form class="add"' not in body:
        return ""
    return body.split('<form class="add"', 1)[1].split("</form>", 1)[0]


def _opts(block: str, name: str) -> list[str]:
    """Значения <option> у поля с этим именем."""
    if f"name='{name}'" in block:
        tail = block.split(f"name='{name}'", 1)[1]
    elif f'name="{name}"' in block:
        tail = block.split(f'name="{name}"', 1)[1]
    else:
        return []
    return re.findall(r"value='([^']*)'", tail.split("</select>", 1)[0])


def _selected(block: str, name: str) -> str:
    """Значение <option ... selected> — пусто, если предвыбора нет."""
    if f"name='{name}'" in block:
        tail = block.split(f"name='{name}'", 1)[1]
    elif f'name="{name}"' in block:
        tail = block.split(f'name="{name}"', 1)[1]
    else:
        return ""
    m = re.search(r"value='([^']*)' selected", tail.split("</select>", 1)[0])
    return m.group(1) if m else ""


def _js_var(body: str, name: str):
    """Значение инлайн-переменной страницы (`var CARDS = {…};`) как объект."""
    tail = body.split(f"var {name} = ", 1)[1]
    return json.loads(tail.split(";\n", 1)[0].rstrip(";"))


def _cs_show(body: str) -> dict:
    """CS_SHOW разобранный: {кнопка: [статусы]}. Литерал JS, не JSON."""
    tail = body.split("var CS_SHOW = ", 1)[1].split("}}", 1)[0]
    return {k: re.findall(r"'([a-z]+)'", v)
            for k, v in re.findall(r"(\w+): \[([^\]]*)\]", tail)}


def _row_actions(body: str, appt_id: str) -> list[str]:
    """Статусы, которые предлагает кнопками строка списка дня."""
    rows = re.findall(r"<tr class='[a-z]+'>(.*?)</tr>", body, re.S)
    for tr in rows:
        if f"<td>{appt_id}</td>" in tr[:40]:
            return re.findall(r"name='to' value='([a-z]+)'", tr)
    return []


def _grid_card(body: str, appt_id: str) -> str:
    """Блок записи В СЕТКЕ (а не в списке под ней)."""
    grid = body.split("<table class='grid'>", 1)[1].split("</table>", 1)[0]
    m = re.search(r"<div class='appt[^']*' data-appt='" + appt_id + r"'.*?</div>\s*</td>",
                  grid, re.S)
    return m.group(0) if m else ""


def _free_cell(body: str, dk: str, hour: int) -> str:
    """Ячейка «+» этого врача в этом часу."""
    m = re.search(r"<td data-dk='" + dk + r"' data-h='" + str(hour)
                  + r"'><a class='free'.*?</a></td>", body, re.S)
    return m.group(0) if m else ""


def _seed(c: Client, day: str) -> list[str]:
    """Шесть записей и заметка: по одной на каждое состояние конвейера."""
    for i, (hh, name) in enumerate((("08:00", "Sta Confirmat"), ("09:00", "Sta Venit"),
                                    ("10:00", "Sta Cabinet"), ("11:00", "Sta Finalizat"),
                                    ("12:00", "Sta Neprezentat"), ("13:00", "Sta Anulat"))):
        c.post("/admin/add", adate=day, atime=hh, adoctor="d2", aservice="consult",
               aname=name, aphone=f"06915010{i}", back=f"/admin/all?date={day}")
    c.post("/admin/note", ndate=day, ntime="16:00", ndoctor="d2",
           ntext="Livrare materiale", back=f"/admin/all?date={day}")
    ids = re.findall(r"<tr class='[a-z]+'><td>(\d+)</td>",
                     c.get(f"/admin/all?date={day}").body)
    back = f"/admin/all?date={day}"
    for aid, to in zip(ids[1:], ("waiting", "arrived", "done", "noshow", "cancelled")):
        c.post(f"/admin/status/{aid}", to=to, back=back)
    return ids


# ------------------------------------------------------------- форма записи


def suite_form(res: Result) -> None:
    """Что нижняя форма предлагает выбрать — и чего не предлагает.

    ⚠️ Часы у формы СВОИ, они не выводятся из сетки: сетка рисует непрерывный
    диапазон с обеденным часом внутри (`hours_range`), а форма — только те
    получасовые старты, куда влезает 30 минут приёма.
    """
    day = (clinic_today() + timedelta(days=3)).isoformat()
    with Server() as s:
        c = Client(s.url).login()
        c.post("/admin/add", adate=day, atime="09:00", adoctor="d3",
               aservice="consult", aname="Pacient Trei", aphone="069151151",
               back=f"/admin/all?date={day}")
        body = c.get(f"/admin/all?date={day}").body
        f = _form(body)

        res.check("часы: получасовая сетка от открытия до последнего влезающего старта",
                  (_opts(f, "atime")[:2], _opts(f, "atime")[-1]),
                  (["07:00", "07:30"], "20:30"))
        res.check("услуги — все из clinic.json, в его порядке и без предвыбора",
                  (_opts(f, "aservice"), _selected(f, "aservice")),
                  (["consult", "pain", "hygiene", "orphan", "long"], ""))
        res.check("врачи формы — активные справочника",
                  _opts(f, "adoctor"), ["d2", "d3", "d4"])
        res.ok("дата — поле, а не подпись: записать можно и на другой день",
               'type="date" name="adate"' in f and f'value="{day}"' in f,
               "дата визита перестала быть полем")
        res.ok("галочка «fără telefon» несёт имя поля и требование",
               'name="anophone"' in f and 'data-for="aphone"' in f
               and 'data-req="1"' in f, "галочка потеряла привязку к телефону")
        res.ok("дата рождения ограничена сегодняшним днём",
               'name="abirth"' in f and "max=" in f.split('name="abirth"', 1)[1][:40],
               "поле рождения без потолка — «в будущем» отобьёт только сервер")

        # выключенный врач: колонка в сетке есть, строки в форме нет
        c.post("/admin/doctor-card/d3/save", name="Dr. Activ Trei", status="concediu")
        body = c.get(f"/admin/all?date={day}").body
        heads = re.findall(r"<a class='dh-n'[^>]*>([^<]+)</a>", body)
        res.check("ВЫКЛЮЧЕННЫЙ ВРАЧ: колонка в сетке осталась, из формы ушёл",
                  ("Dr. Activ Trei" in heads, "d3" in _opts(_form(body), "adoctor")),
                  (True, False))

        # предвыбор из адреса
        pre = _form(c.get(f"/admin/all?date={day}&doctor=d4&time_pre=10:30").body)
        res.check("?doctor= и ?time_pre= предвыбирают врача и час",
                  (_selected(pre, "adoctor"), _selected(pre, "atime")),
                  ("d4", "10:30"))
        res.check("час, которого нет в списке, предвыбора не даёт",
                  _selected(_form(c.get(f"/admin/all?date={day}&time_pre=10:15").body),
                            "atime"), "")

        # фильтр плитки обязан пережить отправку формы
        res.ok("back несёт фильтр плитки",
               f'value="/admin/all?date={day}&amp;f=noshow"'
               in _form(c.get(f"/admin/all?date={day}&f=noshow").body),
               "после записи с отфильтрованной страницы фильтр потеряется")

        # день врача: одна строка вместо выбора
        doc = _form(c.get(f"/admin/doctor/d2?date={day}").body)
        res.check("день врача: врач — скрытым полем, а не выпадающим списком",
                  ("<input type='hidden' name='adoctor' value='d2'>" in doc,
                   "name='adoctor'><option" in doc), (True, False))
        res.ok("у выключенного врача формы нет вовсе",
               _form(c.get(f"/admin/doctor/d3?date={day}").body) == "",
               "страница выключенного врача предлагает в него записать")

    # часы ВРАЧА, а не клиники: два окна в одном дне
    with Server(clinic="clinic_split.json") as s:
        c = Client(s.url).login()
        body = c.get(f"/admin/all?date={day}").body
        times = _js_var(body, "DOC_TIMES")
        res.check("DOC_TIMES: у каждого врача формы свои часы",
                  ({"da", "db"} <= set(times), times["da"][0], times["da"][-1],
                   times["db"][0], times["db"][-1]),
                  (True, "09:00", "12:30", "14:00", "17:30"))
        res.check("список в самом поле — часы врача, открытого по умолчанию",
                  _opts(_form(body), "atime"), times["da"])
        res.check("?doctor= меняет и список часов",
                  _opts(_form(c.get(f"/admin/all?date={day}&doctor=db").body), "atime"),
                  times["db"])

    # окно врача, целиком съеденное обедом: список подменяется часами клиники
    with Server(clinic="clinic_hours.json") as s:
        c = Client(s.url).login()
        res.check("врач переведён на 13–14 (иначе проверка ниже пуста)",
                  c.post_json("/api/doctors/d4",
                              {"name": "Dr. Activ Patru", "spec": "Protetică",
                               "work_from": 13, "work_to": 14,
                               "status": "activ", "auto_color": True}).status, 200)
        times = _js_var(c.get(f"/admin/all?date={day}").body, "DOC_TIMES")
        res.check("ПУСТОЕ ОКНО подменяется часами КЛИНИКИ, а не пустым списком",
                  (bool(times["d4"]), times["d4"][0], times["d4"][-1],
                   times["d4"] == times["d2"]),
                  (True, "07:00", "20:30", False))
        res.check("а у врача с окном 9–17 список остаётся его собственным",
                  (times["d2"][0], times["d2"][-1]), ("09:00", "16:30"))
        res.ok("обеденный час из списка выброшен",
               not any(t.startswith("13:") for t in times["d2"]),
               "форма предлагает записать в обед")


# ---------------------------------------------------------- диалог «+» и заметки


def suite_slot(res: Result) -> None:
    """Диалог свободной ячейки: чем его открывают и что он посылает."""
    day = (clinic_today() + timedelta(days=3)).isoformat()
    with Server() as s:
        c = Client(s.url).login()
        body = c.get(f"/admin/all?date={day}").body

        cell = _free_cell(body, "d2", 10)
        res.ok("«+» зовёт диалог с врачом, ЕГО ИМЕНЕМ и часом",
               'openSlot.apply(null,[&quot;d2&quot;, &quot;Dr. Activ Doi&quot;, '
               '&quot;10:00&quot;])' in cell,
               f"проводка ячейки изменилась: {cell[:160]}")
        res.ok("и остаётся ссылкой на страницу с тем же часом (без JS)",
               f"href='/admin/all?date={day}&doctor=d2&time_pre=10:00#addform'" in cell,
               "у «+» пропал запасной адрес")

        res.check("NOTE_ENDS: конец блокировки — час открытых слотов плюс один",
                  _js_var(body, "NOTE_ENDS"), list(range(8, 22)))
        res.ok("у диалога две вкладки: запись и заметка",
               'id="tab_a"' in body and 'action="/admin/note"' in body
               and 'id="m_until"' in body, "диалог «+» потерял вкладку")
        res.ok("получас меняет только время ЗАПИСИ, не заметки",
               "pickHalf" in body and "m_time_a" in body
               and "m_time_n" not in body.split("function pickHalf", 1)[1].split("}", 1)[0],
               "получас поехал в заметку — блокировки живут часами")
        res.ok("текст заметки ограничен 120 знаками",
               'name="ntext"' in body
               and 'maxlength="120"' in body.split('name="ntext"', 1)[1][:120],
               "ограничение длины заметки ушло из разметки")

        # --- правила самой заметки (их переносит API, значит пин обязателен) ---
        back = f"/admin/all?date={day}"
        res.check("заметка на три часа: nuntil — ГОЛЫЙ час, граница верхняя открытая",
                  c.post("/admin/note", ndate=day, ntime="15:00", ndoctor="d2",
                         ntext="Ședință", nuntil="18", back=back).msg, "ok_note")
        rows = re.findall(r"<tr class='[a-z]+'><td>\d+</td><td>(\d\d:\d\d)</td>",
                          c.get(f"/admin/all?date={day}").body)
        res.check("заблокированы 15, 16 и 17 — но не 18",
                  [t for t in rows if t in ("15:00", "16:00", "17:00", "18:00")],
                  ["15:00", "16:00", "17:00"])
        res.check("час занят — остальные лечь успели: part_note",
                  c.post("/admin/note", ndate=day, ntime="17:00", ndoctor="d2",
                         ntext="Altă pauză", nuntil="19", back=back).msg, "part_note")
        res.check("все часы заняты — conflict",
                  c.post("/admin/note", ndate=day, ntime="15:00", ndoctor="d2",
                         ntext="A treia", nuntil="16", back=back).msg, "conflict")
        res.check("конец раньше начала — bad",
                  c.post("/admin/note", ndate=day, ntime="12:00", ndoctor="d2",
                         ntext="Invers", nuntil="11", back=back).msg, "bad")
        res.check("пустой текст — bad",
                  c.post("/admin/note", ndate=day, ntime="12:00", ndoctor="d3",
                         ntext="   ", back=back).msg, "bad")
        c.post("/admin/doctor-card/d4/save", name="Dr. Activ Patru", status="concediu")
        res.check("выключенному врачу заметку не ставим — и это «bad», не «bad_off»",
                  c.post("/admin/note", ndate=day, ntime="12:00", ndoctor="d4",
                         ntext="Concediu", back=back).msg, "bad")

    with Server(clinic="clinic_hours.json") as s:
        c = Client(s.url).login()
        res.check("обед выпадает и из концов блокировки: 14:00 выбрать нельзя",
                  _js_var(c.get(f"/admin/all?date={day}").body, "NOTE_ENDS"),
                  list(range(8, 14)) + list(range(15, 22)))
        res.check("…ни в саму блокировку: обед перепрыгнут",
                  c.post("/admin/note", ndate=day, ntime="12:00", ndoctor="d2",
                         ntext="Peste pauză", nuntil="15",
                         back=f"/admin/all?date={day}").msg, "ok_note")
        rows = re.findall(r"<tr class='[a-z]+'><td>\d+</td><td>(\d\d:\d\d)</td>",
                          c.get(f"/admin/all?date={day}").body)
        res.check("заметка легла на 12 и 14, обеденного часа в ней нет",
                  sorted(t for t in rows if t in ("12:00", "13:00", "14:00")),
                  ["12:00", "14:00"])


# ------------------------------------------------------- карточка визита


def suite_card(res: Result) -> None:
    """Полезная нагрузка карточки и набор кнопок по статусу."""
    day = (clinic_today() + timedelta(days=3)).isoformat()
    with Server() as s:
        c = Client(s.url).login()
        ids = _seed(c, day)
        back = f"/admin/all?date={day}"
        long_text = "Alergie la penicilină; de sunat cu o zi înainte; " \
                    "vine cu mama; preferă dimineața"
        res.check("длинный комментарий сохранён", len(long_text) > 60, True)
        c.post(f"/admin/comment/{ids[0]}", comment=long_text, back=back)
        body = c.get(back).body
        cards = _js_var(body, "CARDS")

        res.check("состав карточки", sorted(cards[ids[0]]),
                  sorted(["name", "phone", "service", "doctor", "time", "comment",
                          "age", "st", "pid", "rec"]))
        res.check("КОММЕНТАРИЙ В КАРТОЧКЕ ПОЛНЫЙ, а в сетке обрезан до 60",
                  (cards[ids[0]]["comment"], long_text[:60] in _grid_card(body, ids[0]),
                   long_text in _grid_card(body, ids[0])),
                  (long_text, True, False))
        res.ok("заметки стойки карточки не имеют",
               all(v["service"] != "Livrare materiale" for v in cards.values()),
               "заметка попала в карточки — у неё нет ни пациента, ни исхода")
        res.ok("ОТМЕНЁННАЯ запись карточку имеет, хотя из сетки исчезла",
               cards.get(ids[5], {}).get("st") == "cancelled"
               and f"data-appt='{ids[5]}'" not in
               body.split("<table class='grid'>", 1)[1].split("</table>", 1)[0],
               "отменённую запись больше не открыть — вернуть её будет нечем")
        res.ok("карточка помнит фишу и наличие дневника",
               cards[ids[0]]["pid"] and cards[ids[0]]["rec"] is False,
               f"{cards[ids[0]]}")

        # CS_SHOW и кнопки списка — одно правило в двух видах
        cs = _cs_show(body)
        to_of = {"waiting": "waiting", "arrived": "arrived", "done": "done",
                 "noshow": "noshow", "cancel": "cancelled", "reopen": "confirmed"}
        res.check("кнопок модалки шесть, и это весь конвейер",
                  sorted(cs), sorted(to_of))
        for i, st in enumerate(("confirmed", "waiting", "arrived", "done",
                                "noshow", "cancelled")):
            res.check(f"«{st}»: модалка и список предлагают одно и то же",
                      sorted(_row_actions(body, ids[i])),
                      sorted(to_of[k] for k, v in cs.items() if st in v))

        res.ok("возврат спрашивают подтверждением",
               "Redeschideți programarea" in body, "возврат стал бесшумным")
        res.ok("комментарий ограничен 300 знаками и в поле, и на сервере",
               'maxlength="300"' in body, "ограничение ушло из разметки")
        c.post(f"/admin/comment/{ids[1]}", comment="x" * 400, back=back)
        res.check("длинный комментарий обрезан сервером",
                  len(_js_var(c.get(back).body, "CARDS")[ids[1]]["comment"]), 300)
        res.check("комментарий стирается пустой строкой",
                  (c.post(f"/admin/comment/{ids[1]}", comment="", back=back).msg,
                   _js_var(c.get(back).body, "CARDS")[ids[1]]["comment"]),
                  ("ok_comment", ""))

        # отказы смены статуса
        res.check("неизвестный статус — тихо назад, без баннера и без правки",
                  (c.post(f"/admin/status/{ids[0]}", to="pending", back=back).msg,
                   _js_var(c.get(back).body, "CARDS")[ids[0]]["st"]),
                  ("", "confirmed"))
        # час отменённой записи занят другим пациентом: возврат теперь отбивается
        res.check("час освободился и занят другим (иначе отказа ниже не будет)",
                  c.post("/admin/add", adate=day, atime="13:00", adoctor="d2",
                         aservice="consult", aname="Ocupa Ora",
                         aphone="069151900", back=back).msg, "ok")
        res.check("отказ уводит на СТРАНИЦУ, с которой пришли",
                  c.post(f"/admin/status/{ids[5]}", to="confirmed",
                         back=back).location.split("?")[0], "/admin/all")
        res.check("а без внятного back — на панель дня",
                  c.post(f"/admin/status/{ids[5]}", to="confirmed",
                         back="http://evil.example").location, "/admin?msg=conflict")


# ------------------------------------------------------------- перенос


def suite_move(res: Result) -> None:
    """Диалог переноса и то, что перетаскивание берёт из разметки.

    Атрибуты самой записи (`data-min`/`data-dur`/`data-busy`/`data-mv`) пинит
    `test_booking.suite_move`; здесь — остальные три четверти договора: имя в
    диалоге, поля самого диалога и поведение сервера на бросок «туда же».
    """
    day = (clinic_today() + timedelta(days=3)).isoformat()
    with Server() as s:
        c = Client(s.url).login()
        back = f"/admin/all?date={day}"
        long_name = "Alexandru-Constantin Popescu-Tăutu de la Ungheni"
        res.check("имя длиннее сорока знаков", len(long_name) > 40, True)
        c.post("/admin/add", adate=day, atime="09:00", adoctor="d2",
               aservice="consult", aname=long_name, aphone="069152152", back=back)
        c.post("/admin/note", ndate=day, ntime="11:00", ndoctor="d2",
               ntext="Livrare materiale", back=back)
        body = c.get(back).body
        ids = re.findall(r"<tr class='[a-z]+'><td>(\d+)</td>", body)

        res.check("ИМЯ В ДИАЛОГЕ обрезано до сорока знаков",
                  re.search(r"data-appt='" + ids[0] + r"'[^>]*data-nm=\"([^\"]*)\"",
                            body).group(1), long_name[:40])
        res.check("у заметки вместо имени пациента — её текст",
                  re.search(r"data-appt='" + ids[1] + r"'[^>]*data-nm=\"([^\"]*)\"",
                            body).group(1), "Livrare materiale")

        for path in (back, f"/admin/doctor/d2?date={day}"):
            page = c.get(path).body
            missing = [x for x in ("movedlg", "mv_nm", "mv_from", "mv_to", "mv_time",
                                   "mv_doc", "mv_warn", "mv_yes", "mv_form")
                       if f'id="{x}"' not in page]
            res.ok(f"{path}: диалог переноса на месте целиком",
                   not missing, f"диалог потерял поля: {missing}")
            res.ok(f"{path}: диалог несёт дату страницы и возврат",
                   f'name="mdate" value="{day}"' in page
                   and 'name="back"' in page.split('id="movedlg"', 1)[1],
                   "перенос отправился бы без даты или без возврата")

        res.ok("мишень переноса — приёмный час, ЗАНЯТЫЙ он или нет",
               f"data-dk='d2' data-h='9'" in body,
               "занятая ячейка перестала быть мишенью — 09:30 стало недоступно")

        res.check("БРОСОК НА СВОЁ МЕСТО сервер принимает как обычный перенос",
                  c.post(f"/admin/move/{ids[0]}", mdate=day, mtime="09:00",
                         mdoctor="d2", back=back).msg, "ok_move")
        pid = c.get("/admin/search?q=069152152").body.split(
            "/admin/patient/", 1)[1].split("'")[0].split('"')[0].split("?")[0]
        res.ok("и пишет это в летопись пациента — значит охрана «туда же» "
               "обязана стоять в браузере",
               "Vizită mutată" in c.get(f"/admin/patient/{pid}").body,
               "перенос в себя не оставил следа — правило браузера стало "
               "необязательным, и его можно потерять незаметно")
