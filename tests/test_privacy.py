"""Права пациента на свои данные — то, что спрашивает закон 195/2024.

Проверяется не «страница открылась», а ПОЛНОТА и безопасность выдачи. Копия с
отрезанным хвостом выглядит рабочей и молча нарушает право на доступ, поэтому
пациенту здесь заводится по записи каждого вида, и каждая ищется в архиве.
"""
import io
import json
import pathlib
import shutil
import sqlite3
import sys
import tempfile
import zipfile
from datetime import date, timedelta

from harness import BOT, TG_ON, Client, Result, Server


def _d(offset: int) -> str:
    return (date.today() + timedelta(days=offset)).isoformat()


def _pid(c: Client, phone: str) -> str:
    return c.get(f"/admin/search?q={phone}").body.split(
        "/admin/patient/", 1)[1].split("'")[0].split('"')[0].split("?")[0]


def _seed(c: Client) -> str:
    """Пациент со ВСЕМИ видами данных: визит, профиль, зуб, план, алерт, файл."""
    c.post("/admin/add", adate=_d(1), atime="09:00", adoctor="d2",
           aservice="consult", aname="Export Test", aphone="022778899",
           back="/admin/all")
    pid = _pid(c, "022778899")
    c.post(f"/admin/patient/{pid}/save", name="Export Test", phone="022778899",
           email="ex@example.com", idnp="2000000000000",
           address="str. Testului 1")
    c.post(f"/admin/patient/{pid}/tooth", tooth="11", state="carie",
           note="carie distală", doctor="d2")
    c.post(f"/admin/patient/{pid}/plan", procedure="Plombă 11", tooth="11",
           price="1200")
    c.post(f"/admin/patient/{pid}/pay", amount="500", method="numerar",
           note="avans plombă")
    c.post(f"/admin/patient/{pid}/alert", kind="allergy",
           text="Alergie la penicilină")
    c.post_file(f"/admin/patient/{pid}/doc", "file", "radiografie.png",
                b"\x89PNG\r\n\x1a\n" + b"x" * 64, category="radiografie")
    return pid


def suite_export(res: Result) -> None:
    with Server() as s:
        c = Client(s.url).login()
        pid = _seed(c)

        anon = Client(s.url)
        res.ok("без входа копия данных не отдаётся",
               anon.get(f"/admin/patient/{pid}/export").status == 303,
               "персональные данные ушли без входа в журнал")

        r = c.get(f"/admin/patient/{pid}/export")
        res.check("выгрузка отдаётся", r.status, 200)
        res.ok("отдаётся именно архивом", r.raw[:2] == b"PK",
               f"первые байты {r.raw[:8]!r}")
        res.ok("имя файла узнаваемо",
               "Export_Test" in r.header("Content-Disposition"),
               f"disposition {r.header('Content-Disposition')!r}")

        z = zipfile.ZipFile(io.BytesIO(r.raw))
        names = z.namelist()
        for want in ("CITESTE-MA.txt", "date-pacient.json", "fisa-pacient.html"):
            res.ok(f"в архиве есть {want}", want in names, f"состав: {names}")

        raw_json = z.read("date-pacient.json").decode("utf-8")
        data = json.loads(raw_json)
        res.check("профиль в выгрузке", data["pacient"]["name"], "Export Test")
        res.check("IDNP в выгрузке", data["pacient"]["idnp"], "2000000000000")
        res.check("визит в выгрузке", len(data["programari"]), 1)
        res.check("предупреждение в выгрузке", len(data["atentionari"]), 1)
        res.check("зуб в выгрузке", len(data["dinti"]), 1)
        res.check("план лечения в выгрузке", len(data["plan_tratament"]), 1)
        # деньги — тоже персональные данные: платежи входят в копию
        res.check("платёж в выгрузке", len(data["plati"]), 1)
        res.check("сумма платежа в выгрузке", data["plati"][0]["amount_mdl"], 500)
        res.ok("платёж виден и в читаемой фише",
               "Plăți (1)" in z.read("fisa-pacient.html").decode("utf-8"),
               "HTML-копия без платежей")
        res.check("документ в выгрузке", len(data["documente"]), 1)
        res.ok("история фиши не пуста", len(data["istoric"]) > 0, "летопись пуста")

        res.ok("раскладка диска клиники наружу НЕ уходит",
               "stored_path" not in raw_json,
               "в копию попал путь к файлу на компьютере клиники")

        docs = [n for n in names if n.startswith("documente/")]
        res.check("файл документа лежит в архиве", len(docs), 1)
        res.ok("содержимое файла настоящее",
               z.read(docs[0]).startswith(b"\x89PNG"), "файл пуст или подменён")
        res.check("JSON ссылается на то имя, под которым файл реально лежит",
                  data["documente"][0]["fisier_in_arhiva"], docs[0])

        page = z.read("fisa-pacient.html").decode("utf-8")
        res.ok("читаемая копия называет оператора данных", "Operator" in page,
               "в HTML не сказано, кто оператор")
        res.ok("читаемая копия содержит сами данные",
               "Export Test" in page and "penicilină" in page,
               "в HTML нет данных пациента")
        # ⚠️ в базе время в UTC. Без перевода в пояс клиники визит на 09:00
        # печатается как 06:00 — дата верна, формат верен, час чужой, и понять
        # это по виду документа нельзя
        want = (date.today() + timedelta(days=1)).strftime("%d.%m.%Y") + " 09:00"
        res.ok("время визита в местном поясе клиники, а не в UTC", want in page,
               f"нет строки {want!r} — пациенту показали чужой час")

        res.ok("выдача копии записана в летопись фиши",
               "Copie a datelor personale" in c.get(f"/admin/patient/{pid}").body,
               "выдача копии не попала в историю — на проверке спросят именно её")
        res.ok("несуществующий пациент не роняет журнал",
               c.get("/admin/patient/999999/export").status == 303,
               "должно вести на список, а не отдавать пустой архив")


def suite_export_full(res: Result) -> None:
    """Полнота: копия не должна обрезаться на пределе выборки.

    У карточки предел есть и уместен — боковому предпросмотру хватает двадцати
    визитов. У выгрузки его быть не может, и это единственная проверка, которая
    отличит одно от другого: обрезанный архив выглядит совершенно рабочим.
    """
    with Server() as s:
        c = Client(s.url).login()
        c.post("/admin/add", adate=_d(1), atime="09:00", adoctor="d2",
               aservice="consult", aname="Multi Vizite", aphone="022445566",
               back="/admin/all")
        pid = _pid(c, "022445566")
        added = 1
        for i in range(2, 32):
            # день может оказаться выходным — считаем ПРИНЯТЫЕ, а не посланные,
            # иначе проверка зависит от того, на какой день недели её запустили
            if c.post("/admin/add", adate=_d(i), atime="09:00", adoctor="d2",
                      aservice="consult", aname="Multi Vizite",
                      aphone="022445566", back="/admin/all").msg in ("ok", "ok_past"):
                added += 1
        res.ok("для проверки набралось больше 20 визитов", added > 20,
               f"принято только {added} — проверка ничего не докажет")

        z = zipfile.ZipFile(io.BytesIO(c.get(f"/admin/patient/{pid}/export").raw))
        data = json.loads(z.read("date-pacient.json"))
        res.check("в выгрузке ВСЕ визиты, а не первые 20",
                  len(data["programari"]), added)


def suite_erase(res: Result) -> None:
    """Право на стирание: ветку выбирает состояние фиши, не рецепция."""
    with Server() as s:
        c = Client(s.url).login()

        # --- ветка 1: контакт без лечения -> физическое удаление ---
        c.post("/admin/add", adate=_d(1), atime="10:00", adoctor="d2",
               aservice="consult", aname="Doar Contact", aphone="022111222",
               back="/admin/all")
        pid = _pid(c, "022111222")
        page = c.get(f"/admin/patient/{pid}").body
        res.ok("фиша без лечения предлагает полное удаление",
               "ștearsă definitiv" in page, "не та ветка в фише")

        r = c.post(f"/admin/patient/{pid}/erase", confirm="greșit")
        res.check("без слова подтверждения — отказ", r.msg, "bad_erase")
        res.ok("пациент на месте после отказа",
               c.get(f"/admin/patient/{pid}").status == 200, "удалён без подтверждения")

        r = c.post(f"/admin/patient/{pid}/erase", confirm="STERG")
        res.check("с подтверждением — удалён", r.msg, "ok_del")
        res.ok("фиша больше не открывается",
               c.get(f"/admin/patient/{pid}").status == 303, "фиша осталась")
        # искать по ссылке на фишу, не по имени: имя эхом возвращается в поле
        # поиска, и проверка по нему ловила бы собственный запрос
        res.ok("из поиска пациент исчез",
               f"/admin/patient/{pid}" not in
               c.get("/admin/search?q=Doar+Contact").body,
               "остался в поиске")
        res.ok("вместе с пациентом ушёл и его визит из журнала",
               "Doar Contact" not in c.get(f"/admin/all?date={_d(1)}").body,
               "визит-сирота остался в журнале дня")

        # --- ветка 2: пациент с лечением -> обезличивание ---
        pid2 = _seed(c)   # визит + профиль с IDNP + зуб + план + алерт + файл
        page = c.get(f"/admin/patient/{pid2}").body
        res.ok("фиша с лечением предлагает только обезличивание",
               "datele de identitate" in page, "не та ветка в фише")

        r = c.post(f"/admin/patient/{pid2}/erase", confirm="sterg")
        res.check("подтверждение принимается и строчными", r.msg, "ok_anon")
        page = c.get(f"/admin/patient/{pid2}").body
        res.ok("личность стёрта со страницы",
               "Export Test" not in page and "2000000000000" not in page
               and "022778899" not in page,
               "имя, IDNP или телефон видны после обезличивания")
        res.ok("фиша живёт под обезличенным именем",
               f"Pacient anonimizat #{pid2}" in page, "нет обезличенного имени")
        res.ok("клиника осталась: план лечения на месте", "Plombă 11" in page,
               "медзаписи пропали вместе с личностью")
        res.ok("алерт остался (медицинское)", "penicilină" in page,
               "алерт стёрт")

        z = zipfile.ZipFile(io.BytesIO(c.get(f"/admin/patient/{pid2}/export").raw))
        data = json.loads(z.read("date-pacient.json"))
        res.check("в выгрузке после стирания нет телефона",
                  data["pacient"]["phone"], None)
        res.check("нет IDNP", data["pacient"]["idnp"], None)
        res.check("ключ канала обезличен", data["pacient"]["session_key"],
                  f"anon:{pid2}")
        res.ok("событие стирания записано",
               any(e["kind"] == "erase" for e in data["istoric"]),
               "стирание не оставило следа в летописи")
        # деньги переживают обезличивание (касса клиники под номером фиши),
        # но записка платежа — свободный текст рецепции — стёрта
        res.check("платёж остался под анонимной фишей", len(data["plati"]), 1)
        res.check("сумма платежа цела", data["plati"][0]["amount_mdl"], 500)
        res.check("записка платежа стёрта", data["plati"][0]["note"], "")

        # --- ветка 3: платёж БЕЗ лечения тоже запирает полное удаление ---
        # (вычеркнуть деньги = переписать кассу задним числом)
        c.post("/admin/add", adate=_d(1), atime="11:00", adoctor="d3",
               aservice="consult", aname="Doar Plata", aphone="022555777",
               back="/admin/all")
        pid3 = _pid(c, "022555777")
        c.post(f"/admin/patient/{pid3}/pay", amount="300", method="card")
        res.ok("фиша с платежом предлагает только обезличивание",
               "datele de identitate" in c.get(f"/admin/patient/{pid3}").body,
               "платёж не удержал фишу от полного удаления")

        # обезличенный скрыт из списков, как архивный
        res.ok("обезличенный не показывается в живом списке",
               f"Pacient anonimizat #{pid2}" not in c.get("/admin/search").body,
               "обезличенный висит в списке")


def _scan_marker(work: pathlib.Path, needles: tuple[str, ...]) -> list[str]:
    """Где маркер пережил стирание: ВСЕ таблицы базы (по sqlite_master) плюс
    имена файлов пациентов на диске. Тест-сторона читает базу сырым sqlite3
    (как test_migrate): сервер уже погашен, шифрования в тестах нет."""
    found: list[str] = []
    con = sqlite3.connect(str(work / "dental.db"))
    try:
        tables = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")]
        for t in tables:
            for row in con.execute(f'SELECT * FROM "{t}"'):
                blob = " · ".join(str(v) for v in row)
                for n in needles:
                    if n in blob:
                        found.append(f"{t}: {blob[:150]}")
    finally:
        con.close()
    files = work / "files"
    if files.exists():
        for p in files.rglob("*"):
            for n in needles:
                if n in p.name:
                    found.append(f"файл: {p}")
    return found


# маркер-«личность»: буквы вне hex-алфавита, чтобы случайные совпадения с
# отпечатками/токенами были невозможны; телефон длинный по той же причине
_MARK = "Zqmarcaj"
_MARK_PHONE = "07100230045"


def suite_erase_marker(res: Result) -> None:
    """Стирание по маркеру: уникальная строка-личность прогоняется по всем
    местам, куда её может вписать рецепция, и после обезличивания не должна
    находиться НИ В ОДНОЙ таблице базы и ни в одном имени файла.

    ⚠️ Медицинский текст (план, зуб, анамнез, дневник) остаётся ПО ЗАМЫСЛУ —
    это «ЧТО лечили», маркер-личность в него не кладётся. Но сами действия
    прогоняются: их эхо в летописи (log_event дублирует заметку платежа и имя
    файла) носит маркер — именно летопись и имя документа переживали
    обезличивание до 08-15.
    """
    work = pathlib.Path(tempfile.mkdtemp(prefix="dp_test_"))
    try:
        with Server(dir_=work) as s:
            c = Client(s.url).login()
            c.post("/admin/add", adate=_d(1), atime="09:00", adoctor="d2",
                   aservice="consult", aname=f"Ion {_MARK}",
                   aphone=_MARK_PHONE, back="/admin/all")
            pid = _pid(c, _MARK_PHONE)
            c.post(f"/admin/patient/{pid}/save", name=f"Ion {_MARK}",
                   phone=_MARK_PHONE, email=f"{_MARK}@exemplu.md",
                   address=f"str. {_MARK} 7", notes=f"vecin cu {_MARK}")
            # комментарий визита — свободный текст рецепции
            aid = c.get(f"/admin/all?date={_d(1)}").body.split(
                "/admin/status/", 1)[1].split("'")[0].split('"')[0]
            c.post(f"/admin/comment/{aid}", comment=f"vine cu {_MARK}",
                   back="/admin/all")
            # платёж с заметкой: note дублируется летописью («… — {note}»)
            c.post(f"/admin/patient/{pid}/pay", amount="500", method="numerar",
                   note=f"transfer de la {_MARK}")
            # медзаписи БЕЗ маркера — держат фишу в ветке обезличивания
            c.post(f"/admin/patient/{pid}/tooth", tooth="11", state="carie",
                   note="carie distală", doctor="d2")
            c.post(f"/admin/patient/{pid}/plan", procedure="Plombă 11",
                   tooth="11", price="800")
            c.post(f"/admin/patient/{pid}/anamneza", fl=["diabet"])
            # документ с маркером в ИМЕНИ (содержимое — снимок, остаётся)
            c.post_file(f"/admin/patient/{pid}/doc", "file",
                        f"radiografie-{_MARK}.png",
                        b"\x89PNG\r\n\x1a\n" + b"x" * 64,
                        category="radiografie")
            r = c.post(f"/admin/patient/{pid}/erase", confirm="STERG")
            res.check("фиша с лечением обезличена", r.msg, "ok_anon")
            page = c.get(f"/admin/patient/{pid}").body
            res.ok("клиника уцелела: план на месте", "Plombă 11" in page,
                   "медзаписи пропали вместе с личностью")
        found = _scan_marker(work, (_MARK, _MARK_PHONE))
        res.ok("маркер не пережил обезличивание нигде",
               not found, f"уцелевшие следы: {found}")
    finally:
        shutil.rmtree(work, ignore_errors=True)


def suite_erase_marker_delete(res: Result) -> None:
    """То же для ветки физического удаления: контакт без лечения, но с
    комментарием визита и заметками — после «șters definitiv» маркер не должен
    находиться ни в одной таблице (включая летопись и журнал доступа)."""
    work = pathlib.Path(tempfile.mkdtemp(prefix="dp_test_"))
    try:
        with Server(dir_=work) as s:
            c = Client(s.url).login()
            c.post("/admin/add", adate=_d(1), atime="10:00", adoctor="d3",
                   aservice="consult", aname=f"Doar {_MARK}",
                   aphone=_MARK_PHONE, back="/admin/all")
            pid = _pid(c, _MARK_PHONE)
            c.post(f"/admin/patient/{pid}/save", name=f"Doar {_MARK}",
                   phone=_MARK_PHONE, notes=f"ruda lui {_MARK}")
            aid = c.get(f"/admin/all?date={_d(1)}").body.split(
                "/admin/status/", 1)[1].split("'")[0].split('"')[0]
            c.post(f"/admin/comment/{aid}", comment=f"suna {_MARK}",
                   back="/admin/all")
            r = c.post(f"/admin/patient/{pid}/erase", confirm="STERG")
            res.check("контакт без лечения удалён физически", r.msg, "ok_del")
        found = _scan_marker(work, (_MARK, _MARK_PHONE))
        res.ok("после полного удаления маркера нет нигде",
               not found, f"уцелевшие следы: {found}")
    finally:
        shutil.rmtree(work, ignore_errors=True)


def suite_access_log(res: Result) -> None:
    """Журнал доступа: просмотры пишутся, но ленту фиши не засоряют."""
    with Server() as s:
        c = Client(s.url).login()
        pid = _seed(c)
        c.get(f"/admin/patient/{pid}")            # ещё один просмотр

        page = c.get(f"/admin/patient/{pid}").body
        res.ok("лента фиши БЕЗ строк «Fișa deschisă»",
               "Fișa deschisă" not in page,
               "просмотры засоряют ленту — рецепция откроет карту 30 раз в день")

        z = zipfile.ZipFile(io.BytesIO(c.get(f"/admin/patient/{pid}/export").raw))
        data = json.loads(z.read("date-pacient.json"))
        views = [e for e in data["istoric"] if e["kind"] == "view"]
        res.ok("а в выгрузке просмотры ЕСТЬ", len(views) >= 2,
               f"просмотров в копии {len(views)} — журнал доступа не пишется")

        # просмотр документа — отдельное событие
        docs = [n for n in zipfile.ZipFile(io.BytesIO(
            c.get(f"/admin/patient/{pid}/export").raw)).namelist()]
        doc_id = data["documente"][0]["id"]
        c.get(f"/admin/doc/{doc_id}")
        z2 = zipfile.ZipFile(io.BytesIO(c.get(f"/admin/patient/{pid}/export").raw))
        data2 = json.loads(z2.read("date-pacient.json"))
        res.ok("открытие документа записано",
               any(e["kind"] == "doc_view" for e in data2["istoric"]),
               "скачивание снимка не оставило следа")

        # журнал обязан ПОКАЗЫВАТЬСЯ, а не только писаться: «программа ведёт
        # журнал доступа» без экрана — заявление, которое нечем предъявить
        page = c.get(f"/admin/patient/{pid}?views=1").body
        res.ok("?views=1 показывает просмотры фиши", "Fișa deschisă" in page,
               "журнал доступа не виден даже по клику")
        res.ok("и просмотры документов", "Document deschis" in page,
               "открытия документов не видны в журнале")
        res.ok("ссылка на журнал есть в обычной ленте",
               "views=1" in c.get(f"/admin/patient/{pid}").body,
               "к журналу нет пути с фиши")


def suite_acord(res: Result) -> None:
    """Печатный «Informare și acord» из фиши: автозаполнение и след в летописи.

    ⭐ Главное, что стережётся, — незаполненное поле обязано остаться ВИДИМЫМ
    пропуском (жёлтый `fill`), а не пустым местом: лист подписывается на бумаге,
    и пробел, который не видно, так и уйдёт неподписанным. И второе — генерация
    формы пишется в летопись: лист с персональными данными — событие обработки.
    """
    with Server() as s:
        c = Client(s.url).login()
        c.post("/admin/add", adate=_d(1), atime="10:00", adoctor="d2",
               aservice="consult", aname="Acord Test", aphone="022556677",
               back="/admin/all")
        pid = _pid(c, "022556677")
        # профиль с IDNP и адресом, но БЕЗ даты рождения — она должна
        # напечататься жёлтым пропуском
        c.post(f"/admin/patient/{pid}/save", name="Acord Test",
               phone="022556677", idnp="2011111111111", address="str. Acord 5")

        anon = Client(s.url)
        res.ok("без входа формуляр не отдаётся",
               anon.get(f"/admin/patient/{pid}/acord").status == 303,
               "лист с персональными данными ушёл без входа")

        r = c.get(f"/admin/patient/{pid}/acord")
        res.check("формуляр отдаётся", r.status, 200)
        for want in ("Acord Test", "2011111111111", "str. Acord 5",
                     "Clinica Test", "nr. 195/2024"):
            res.ok(f"в формуляре есть {want!r}", want in r.body,
                   "автозаполнение потеряло поле")
        res.ok("пустая дата рождения — видимый жёлтый пропуск",
               "class='fill'" in r.body, "незаполненное поле не видно на бумаге")
        res.ok("основание — договор и закон, не согласие",
               "contractului de servicii medicale" in r.body
               and "obligație legală" in r.body,
               "формуляр строит лечение на отзываемом согласии")
        res.ok("согласия-галочки только про необязательное",
               "marketing" in r.body, "нет блока опциональных согласий")

        res.ok("ссылка на формуляр есть в фише",
               f"/admin/patient/{pid}/acord" in c.get(f"/admin/patient/{pid}").body,
               "к формуляру нет пути с фиши")
        res.ok("генерация формуляра оставила след в летописи",
               "Formular «Informare și acord»" in c.get(f"/admin/patient/{pid}").body,
               "выдача листа не записана")


def suite_bot_notice(res: Result) -> None:
    """Уведомление об обработке — в момент, когда бот впервые просит имя."""
    from harness import Bot
    with Server(env=TG_ON) as s:
        c = Client(s.url)
        bot = Bot(c, "privacy-notice-test")
        bot.say("start")
        _, buttons = bot.say("📅 Programare")
        texts, buttons = bot.say(buttons[0])          # услуга -> врач/день
        # доходим до вопроса об имени: жмём первую кнопку, пока он не появится
        for _ in range(6):
            if "numiți" in texts:
                break
            if not buttons:
                break
            texts, buttons = bot.say(buttons[0])
        res.ok("бот дошёл до вопроса об имени", "numiți" in texts,
               f"диалог застрял: {texts[:120]!r}")
        res.ok("в вопросе есть уведомление об обработке",
               "prelucrate" in texts and "🔒" in texts,
               "нет уведомления в момент сбора данных")
        res.ok("уведомление называет клинику по имени",
               "Clinica Test" in texts, "вместо клиники — {CLINIC} или пусто")


def suite_backup(res: Result) -> None:
    """Зашифрованный бэкап клиники: полнота и круг «закрыл-открыл».

    Проверяется тем же pyzipper, которым архив создан, — но проверка «неверный
    пароль НЕ открывает» от этого не слабеет: она о формате, не о библиотеке.
    """
    sys.path.insert(0, str(BOT))
    try:
        import pyzipper
    except ImportError:
        res.ok("pyzipper установлен в .venv-desktop", False,
               "нет pyzipper — зашифрованный бэкап мёртв и в сборке")
        return

    with Server() as s:
        c = Client(s.url).login()
        pid = _seed(c)                     # чтобы в базе и файлах что-то было

        r = c.post("/admin/backup/export", parola="scurt")
        res.check("короткий пароль отбит", r.msg, "bad_bkp_pass")

        anon = Client(s.url)
        res.ok("без входа бэкап не отдаётся",
               anon.post("/admin/backup/export",
                         parola="parola-foarte-buna").status == 303,
               "вся база клиники ушла без входа")

        r = c.post("/admin/backup/export", parola="parola-foarte-buna")
        res.check("бэкап отдаётся", r.status, 200)
        res.ok("это zip", r.raw[:2] == b"PK", f"байты {r.raw[:4]!r}")

        z = pyzipper.AESZipFile(io.BytesIO(r.raw))
        z.setpassword(b"parola-foarte-buna")
        names = z.namelist()
        for want in ("CITESTE-MA.txt", "data/dental.db", "clinic.json"):
            res.ok(f"в бэкапе есть {want}", want in names, f"состав: {names}")
        res.ok("файлы пациентов в бэкапе",
               any(n.startswith("data/files/") for n in names),
               f"нет data/files/: {names}")

        head = z.read("data/dental.db")[:16]
        res.ok("база читается верным паролем и это SQLite",
               head.startswith(b"SQLite format 3"), f"заголовок {head!r}")

        z2 = pyzipper.AESZipFile(io.BytesIO(r.raw))
        z2.setpassword(b"parola-gresita!!")
        try:
            z2.read("data/dental.db")
            opened = True
        except RuntimeError:
            opened = False
        res.ok("неверный пароль НЕ открывает", not opened,
               "архив читается любым паролем — шифрования нет")

        plain = zipfile.ZipFile(io.BytesIO(r.raw))
        try:
            plain.read("data/dental.db")
            opened = True
        except RuntimeError:
            opened = False
        res.ok("и без пароля стандартный zipfile тоже не читает", not opened,
               "содержимое доступно без пароля")

        # ⚠️ инструкция «чем открыть» обязана читаться БЕЗ пароля: Проводник
        # Windows не умеет AES-zip, и запертый readme не существует — человек
        # на чужой машине видит «архив не извлекается» и тупик (случай 08-06)
        try:
            note = plain.read("CITESTE-MA.txt").decode("utf-8", "replace")
        except RuntimeError:
            note = ""
        res.ok("CITESTE-MA читается без пароля", "7-Zip" in note,
               "инструкция по открытию заперта внутри шифра — её никто не увидит")

        # опись: распакованный бэкап — база-кирпич и hex-имена; без описи
        # человек не может проверить, что его данные вообще внутри (случай
        # 08-06: «ни имён, ничего, пара фотографий»)
        cont = z.read("CONTINUT.txt").decode("utf-8", "replace")
        res.ok("опись называет документ настоящим именем",
               "radiografie.png" in cont, "в описи нет имени документа")
        res.ok("опись связывает документ с пациентом", "Export Test" in cont,
               "в описи нет имени пациента")
        res.ok("опись считает пациентов", "Pacienti: " in cont
               and "Pacienti: ?" not in cont, f"счётчики пусты: {cont[:200]!r}")
        try:
            plain.read("CONTINUT.txt")
            cont_open = True
        except RuntimeError:
            cont_open = False
        res.ok("опись (с именами пациентов) БЕЗ пароля не читается",
               not cont_open, "имена пациентов легли в открытую часть архива")


def suite_export_names(res: Result) -> None:
    """Имена файлов внутри архива. Имя пришло от пользователя при загрузке,
    значит распаковщик, честно повторяющий путь, может писать мимо папки."""
    sys.path.insert(0, str(BOT))
    from app.modules.patients import export

    used: set[str] = set()
    cases = [
        ("../../../evil.txt", "выход вверх по дереву"),
        ("..\\..\\evil.txt", "то же через обратный слэш (Linux-издание)"),
        ("/etc/passwd", "абсолютный путь"),
        ("..", "только точки"),
        ("", "пустое имя"),
        ("C:\\Windows\\System32\\x.dll", "путь с буквой диска"),
    ]
    for name, why in cases:
        got = export._safe_name(name, used)
        res.ok(f"обезврежено: {why}",
               "/" not in got and "\\" not in got and ".." not in got and got,
               f"{name!r} -> {got!r}")

    dup: set[str] = set()
    a = export._safe_name("radiografie.png", dup)
    b = export._safe_name("radiografie.png", dup)
    res.ok("одинаковые имена разводятся, а не затирают друг друга", a != b,
           f"оба файла легли как {a!r}")
