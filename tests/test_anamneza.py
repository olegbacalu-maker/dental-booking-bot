"""Анамнез-опросник: то, что спрашивают ДО кресла.

Проверяется не «форма сохранилась», а что ответ доехал до места, где он спасает
приём: раздел 2 печатной 043/e и выгрузка по 195-му. Плюс граница закона:
опросник — медзапись, значит держит фишу от физического стирания и переживает
обезличивание под номером фиши.
"""
import io
import json
import zipfile
from datetime import date, timedelta

import subprocess

from harness import BOT, PYTHON, Client, Result, Server


def _d(offset: int) -> str:
    return (date.today() + timedelta(days=offset)).isoformat()


def _pid(c: Client, phone: str) -> str:
    return c.get(f"/admin/search?q={phone}").body.split(
        "/admin/patient/", 1)[1].split("'")[0].split('"')[0].split("?")[0]


def suite(res: Result) -> None:
    with Server() as s:
        c = Client(s.url).login()
        c.post("/admin/patients/new", name="Anamneza Test", phone="022141414")
        pid = _pid(c, "022141414")

        page = c.get(f"/admin/patient/{pid}").body
        res.ok("секция анамнеза на месте", "Anamneză" in page, "нет секции")
        res.ok("незаполненный анамнез виден как незаполненный",
               "necompletată" in page, "пустой опросник выглядит собранным")
        res.ok("опросник раскрыт, пока не заполнен",
               "<details class='anform' open>" in page,
               "чтобы заполнить впервые, нужен лишний клик")
        res.ok("вопросы на месте",
               "Diabet zaharat" in page and "Sarcină" in page
               and "Reacții la anestezice" in page, "нет вопросов опросника")

        res.check("пустой опросник не сохраняется",
                  c.post(f"/admin/patient/{pid}/anamneza", boli="  ").msg,
                  "bad_anam")

        r = c.post(f"/admin/patient/{pid}/anamneza", fl=["diabet", "cardio"],
                   boli="ulcer gastric operat 2019",
                   medicamente="Metformin 850 mg",
                   alergii="penicilină", anestezie="lipotimie la lidocaină")
        res.check("опросник сохраняется", r.msg, "ok_anam")

        page = c.get(f"/admin/patient/{pid}").body
        res.ok("отметки видны без раскрытия",
               "de reținut" in page and "⚠️ Diabet zaharat" in page,
               "риски не видны в свёрнутом виде")
        res.ok("свободный текст вернулся в форму",
               "ulcer gastric operat 2019" in page, "текст не сохранился")
        res.ok("галочки отмечены",
               "value='diabet' checked" in page, "флажок не восстановлен")
        res.ok("заполненный опросник свёрнут",
               "<details class='anform'>" in page, "форма осталась раскрытой")
        res.ok("видно, кто и когда заполнил",
               "Completat:" in page, "нет авторства опросника")
        res.ok("событие попало в летопись",
               "Anamneza completată" in page, "летопись молчит")

        # ⚠️ главное: опросник обязан ЗАКРЫТЬ жёлтые пропуски раздела 2 бланка
        f043 = c.get(f"/admin/patient/{pid}/fisa043").body
        sect = f043.split("2. Anamneza", 1)[1].split("<h2>", 1)[0]
        res.ok("отмеченное напечатано в «Bolile suportate»",
               "Diabet zaharat" in sect and "Boli cardiovasculare" in sect,
               "отметки опросника не попали на бланк")
        res.ok("дописанное от руки тоже",
               "ulcer gastric operat 2019" in sect, "нет свободного текста")
        res.ok("лекарства и анестезия — своими строками",
               "Metformin 850 mg" in sect and "lipotimie la lidocaină" in sect,
               "нет строк лекарств/анестезии")
        res.ok("аллергия из опросника на бланке", "penicilină" in sect,
               "аллергия потерялась")
        res.ok("в разделе не осталось жёлтых пропусков",
               "class='fill'" not in sect,
               "заполненный опросник оставил бланк пустым")

        # аллергия из ПРЕДУПРЕЖДЕНИЙ фиши печатается рядом с опросником
        c.post(f"/admin/patient/{pid}/alert", kind="allergy", text="latex")
        sect = c.get(f"/admin/patient/{pid}/fisa043").body.split(
            "2. Anamneza", 1)[1].split("<h2>", 1)[0]
        res.ok("оба источника аллергий на бланке",
               "penicilină" in sect and "latex" in sect,
               "один из источников аллергий потерян")

        # правка
        r = c.post(f"/admin/patient/{pid}/anamneza", fl=["diabet"],
                   boli="ulcer gastric operat 2019")
        res.check("опросник правится", r.msg, "ok_anam")
        page = c.get(f"/admin/patient/{pid}").body
        res.ok("снятая галочка снялась",
               "⚠️ Boli cardiovasculare" not in page
               and "⚠️ Diabet zaharat" in page, "отметка не снялась")
        res.ok("правка отмечена в летописи", "Anamneza actualizată" in page,
               "правка не отличается от первого заполнения")

        z = zipfile.ZipFile(io.BytesIO(c.get(f"/admin/patient/{pid}/export").raw))
        data = json.loads(z.read("date-pacient.json").decode("utf-8"))
        res.check("анамнез в выгрузке", data["anamneza"]["flags"], "diabet")
        res.ok("анамнез в читаемой фише",
               "Anamneză" in z.read("fisa-pacient.html").decode("utf-8"),
               "HTML-копия без опросника")

        anon = Client(s.url)
        res.ok("без входа опросник не пишется",
               anon.post(f"/admin/patient/{pid}/anamneza",
                         fl=["hiv"]).status == 303, "принял без входа")


def suite_195(res: Result) -> None:
    """Опросник — медзапись: держит от физического стирания, переживает
    обезличивание."""
    with Server() as s:
        c = Client(s.url).login()
        c.post("/admin/patients/new", name="Erase Anamneza", phone="022151515")
        pid = _pid(c, "022151515")
        res.ok("без анамнеза фиша удаляется физически",
               "Șterge definitiv" in c.get(f"/admin/patient/{pid}").body,
               "ветка стирания уже не delete")

        c.post(f"/admin/patient/{pid}/anamneza", fl=["hepatita"])
        page = c.get(f"/admin/patient/{pid}").body
        # ⚠️ мутация: убери счётчик anamneza из erasure_kind — фиша с одним
        # опросником уйдёт в физическое удаление, и медзапись исчезнет
        res.ok("с анамнезом — только обезличивание",
               "Șterge datele personale" in page
               and "Șterge definitiv" not in page,
               "опросник не удержал фишу от удаления")

        res.check("обезличивание проходит",
                  c.post(f"/admin/patient/{pid}/erase", confirm="STERG").msg,
                  "ok_anon")
        sect = c.get(f"/admin/patient/{pid}/fisa043").body.split(
            "2. Anamneza", 1)[1].split("<h2>", 1)[0]
        res.ok("клиническая часть осталась под номером фиши",
               "Hepatită" in sect, "обезличивание стёрло медзапись")
        res.ok("личность стёрта",
               "Pacient anonimizat" in c.get(f"/admin/patient/{pid}").body,
               "имя пережило обезличивание")


def suite_lang(res: Result) -> None:
    """Печать на языке пациента: ro по умолчанию, ru по выбору.

    ⚠️ Официальные наименования (номер формуляра, приказ МЗ, закон 195)
    не переводятся НИКОГДА — по ним лист опознаёт проверяющий.
    """
    with Server() as s:
        c = Client(s.url).login()
        c.post("/admin/patients/new", name="Limba Test", phone="022161616")
        pid = _pid(c, "022161616")

        ro = c.get(f"/admin/patient/{pid}/fisa043").body
        res.ok("по умолчанию бланк румынский",
               "FIȘA MEDICALĂ A BOLNAVULUI STOMATOLOGIC" in ro
               and 'lang="ro"' in ro, "дефолт уехал с румынского")
        res.ok("на листе есть переключатель языка",
               "?lang=ru" in ro, "нет ссылки на вторую версию")

        ru = c.get(f"/admin/patient/{pid}/fisa043?lang=ru").body
        res.ok("русский бланк по адресу",
               "МЕДИЦИНСКАЯ КАРТА СТОМАТОЛОГИЧЕСКОГО БОЛЬНОГО" in ru
               and 'lang="ru"' in ru, "русской версии нет")
        res.ok("разделы переведены",
               "1. Общие данные" in ru and "6. Дневник визитов" in ru
               and "Врач (подпись)" in ru, "подписи остались румынскими")
        res.ok("номер формуляра и приказ НЕ переведены",
               "043/e" in ru and "828 din 31.10.2011" in ru
               and "Ministerul Sănătății" in ru,
               "официальные наименования перевели — лист не опознают")

        acord_ro = c.get(f"/admin/patient/{pid}/acord").body
        res.ok("формуляр информирования по умолчанию румынский",
               "Informare privind prelucrarea" in acord_ro,
               "дефолт acord уехал")
        acord_ru = c.get(f"/admin/patient/{pid}/acord?lang=ru").body
        res.ok("русское информирование",
               "Информирование об обработке персональных данных" in acord_ru
               and "Ваши права" in acord_ru, "acord не переведён")
        res.ok("закон назван и по-румынски",
               "Legea nr. 195/2024" in acord_ru, "потеряно имя закона")
        res.ok("русская версия помечена как перевод",
               "опорной является версия на румынском" in acord_ru,
               "перевод выдан за оригинал — расходится с листом на стойке")
        res.ok("CNPDCP не переведён", "CNPDCP" in acord_ru,
               "название органа переведено")

        # язык пациента: ставится в профиле и становится ДЕФОЛТОМ печати
        res.check("язык сохраняется в профиле",
                  c.post(f"/admin/patient/{pid}/save", name="Limba Test",
                         phone="022161616", lang="ru").msg, "ok_card")
        res.ok("выбор виден в форме профиля",
               "value='ru' selected" in c.get(f"/admin/patient/{pid}").body,
               "выбор языка не сохранился")
        res.ok("бланк без параметра теперь русский",
               "МЕДИЦИНСКАЯ КАРТА" in c.get(f"/admin/patient/{pid}/fisa043").body,
               "язык пациента не стал дефолтом печати")
        res.ok("и информирование тоже",
               "Информирование об обработке" in c.get(f"/admin/patient/{pid}/acord").body,
               "acord не следует за языком пациента")
        res.ok("явный ?lang=ro перебивает язык пациента",
               "FIȘA MEDICALĂ" in c.get(f"/admin/patient/{pid}/fisa043?lang=ro").body,
               "нельзя вернуться к румынскому")
        # выдуманный язык не ломает лист и не молчит: он просто игнорируется,
        # и печатается язык пациента (здесь уже ru)
        res.ok("выдуманный язык игнорируется",
               "МЕДИЦИНСКАЯ КАРТА" in c.get(f"/admin/patient/{pid}/fisa043?lang=de").body,
               "неизвестный язык сломал лист")
        c.post(f"/admin/patient/{pid}/save", name="Limba Test",
               phone="022161616", lang="ro")
        res.ok("у румынского пациента выдуманный язык даёт румынский",
               "FIȘA MEDICALĂ" in c.get(f"/admin/patient/{pid}/fisa043?lang=de").body,
               "откат не к языку пациента")


def suite_review(res: Result) -> None:
    """Находки адверсарного ревью 08-08 — каждая своим сторожем.

    Все шесть были невидимы для зелёного прогона: экран показывал зелёное
    «нет рисков» над записанной аллергией, ошибочную отметку нельзя было
    снять, а русский бланк печатал румынские подписи.
    """
    with Server() as s:
        c = Client(s.url).login()
        c.post("/admin/patients/new", name="Review Probe", phone="022181818")
        pid = _pid(c, "022181818")

        # 1. заметка зуба уезжает в innerHTML — экранировать обязан клиент
        c.post(f"/admin/patient/{pid}/tooth", tooth="54", state="carie",
               note="<img src=x onerror=alert(1)>", doctor="d2", sf=["M"])
        card = c.get(f"/admin/patient/{pid}").body
        res.ok("заметка зуба идёт через tesc(), а не сырьём в innerHTML",
               "tesc(t.note)" in card and "tesc(x.text)" in card,
               "значение попадёт в innerHTML сырым — XSS при наведении на зуб")

        # 2. свободный текст — тоже риск: аллергия там, а не в галочках
        c.post(f"/admin/patient/{pid}/anamneza", alergii="PENICILINA")
        card = c.get(f"/admin/patient/{pid}").body
        res.ok("нет зелёного «fără riscuri» над записанной аллергией",
               "fără riscuri" not in card and "de reținut" in card,
               "сводка врёт: текстовые поля не считаются риском")
        res.ok("риск виден без раскрытия опросника", "PENICILINA" in card,
               "аллергия спрятана в свёрнутом details")

        # 3. ошибочную отметку обязано быть можно снять
        c.post(f"/admin/patient/{pid}/anamneza", fl=["hiv"])
        res.ok("отметка ставится", "value='hiv' checked"
               in c.get(f"/admin/patient/{pid}").body, "флажок не сохранился")
        res.check("пустое сохранение снимает отметку",
                  c.post(f"/admin/patient/{pid}/anamneza").msg, "ok_anam")
        card = c.get(f"/admin/patient/{pid}").body
        res.ok("снятая отметка исчезла и из фиши, и из бланка",
               "value='hiv' checked" not in card
               and "HIV" not in c.get(f"/admin/patient/{pid}/fisa043").body,
               "неверная запись осталась в первичной документации")
        # но на ПУСТОМ опроснике пустая форма по-прежнему промах
        c.post("/admin/patients/new", name="Gol Anam", phone="022191919")
        pid2 = _pid(c, "022191919")
        res.check("пустая форма на пустом опроснике — отказ",
                  c.post(f"/admin/patient/{pid2}/anamneza").msg, "bad_anam")

        # 4. русский бланк — русские подписи отметок и легенда
        c.post(f"/admin/patient/{pid}/anamneza", fl=["cardio", "diabet"])
        ru = c.get(f"/admin/patient/{pid}/fisa043?lang=ru").body
        sect = ru.split("2. Анамнез", 1)[1].split("<h2>", 1)[0]
        res.ok("отметки анамнеза по-русски",
               "Сахарный диабет" in sect and "Diabet zaharat" not in sect,
               "русский лист печатает румынские подписи")
        res.ok("легенда одонтограммы по-русски",
               "кариес" in ru and "медиальная" in ru, "легенда нечитаема")
        res.ok("имя приказа в подвале НЕ переведено",
               "Ordinul MS nr. 828/2011" in ru and "приказ МЗ" not in ru,
               "переведённый приказ — лист не опознают")

        # 5. поверхности печатаются и при состоянии «ok»
        c.post(f"/admin/patient/{pid}/tooth", tooth="26", state="ok",
               note="control", sf=["M", "O"])
        res.ok("поверхности при «ok» не теряются на бланке",
               ">MO</td>" in c.get(f"/admin/patient/{pid}/fisa043").body,
               "карточка и выгрузка их показывают, а бланк молчит")

        # 6. закон 195: копия в ПОНЯТНОЙ форме, а не слагами
        z = zipfile.ZipFile(io.BytesIO(c.get(f"/admin/patient/{pid}/export").raw))
        page = z.read("fisa-pacient.html").decode("utf-8")
        data = json.loads(z.read("date-pacient.json").decode("utf-8"))
        res.ok("в читаемой копии — вопросы, а не ключи",
               "Diabet zaharat" in page and ">cardio,diabet<" not in page,
               "слаги вместо вопросов — копия не в понятной форме")
        res.check("в JSON ключи остались машинными",
                  data["anamneza"]["flags"], "cardio,diabet")

        # 7. все состояния рисуются на всех номерах (легенда падала на extras)
        res.check("страница фиши цела на всех состояниях",
                  c.get(f"/admin/patient/{pid}").status, 200)

    # ---------- находки аудита 08-10 ----------

    # ⛔ Встраивание JSON в <script> — ТОЛЬКО через core.layout.js_json.
    # Аудит нашёл, что на карточке пациента четыре площадки экранировали `</`,
    # а две нет, и незащищённым оказалось имя врача — поле, которое правит
    # регистратура, то есть МЛАДШАЯ роль. Скрипт оттуда выполнялся в сессии
    # директора. Правило по месту не удержалось; проверка ищет нарушителей во
    # ВСЕХ файлах, печатающих <script>, поэтому пятую площадку так не заведут.
    bad = []
    for f in (BOT / "app").rglob("*.py"):
        # ⚠️ layout.py пропускается ОСОЗНАННО: там живёт сам js_json, и его
        # определение вместе с объясняющей документацией — единственное место,
        # где `json.dumps` рядом со словом <script> обязано встречаться.
        if f.name == "layout.py":
            continue
        txt = f.read_text(encoding="utf-8", errors="replace")
        if "<script" not in txt:
            continue
        for i, line in enumerate(txt.splitlines(), 1):
            if "json.dumps" in line and not any(
                    ok in line for ok in ("js_json", "html.escape")):
                bad.append(f"{f.relative_to(BOT)}:{i}")
    res.ok("JSON в <script> идёт только через js_json", not bad,
           f"незащищённые площадки: {bad}")

    esc = subprocess.run(
        [str(PYTHON), "-c",
         "import sys;sys.path.insert(0,r'%s');"
         "from app.core.layout import js_json;"
         "print(js_json({'d':'Ana</script><img src=x>'}))" % str(BOT)],
        capture_output=True, text=True, encoding="utf-8")
    res.ok("js_json разрывает закрывающий тег",
           "</script>" not in esc.stdout and "<\\/script>" in esc.stdout,
           f"вывод: {esc.stdout.strip()[:120]} {esc.stderr[-200:]}")

    # ⛔ Демо-строки едут в admin_add ПО ИМЕНАМ. Позиционная распаковка через
    # границу модуля уже разъехалась молча: 08-07 в admin_add вставили
    # birth_date седьмым, и ключ врача уехал в дату рождения, ключ услуги — в
    # id врача. Типов у SQLite нет, поэтому не упало ничего. Проверка связывает
    # то, что отдаёт engine, с настоящей подписью — следующая вставка параметра
    # покраснеет здесь, а не у клиники.
    bind = subprocess.run(
        [str(PYTHON), "-c",
         "import sys,inspect,json;sys.path.insert(0,r'%s');"
         "from app import db, engine as eng;"
         "r=eng.build_seed_rows();"
         "b=inspect.signature(db.admin_add).bind(**r[0]);"
         "print(json.dumps({'doctor_id':b.arguments.get('doctor_id'),"
         "'service_id':b.arguments.get('service_id'),"
         "'birth_date':b.arguments.get('birth_date'),"
         "'dur':b.arguments.get('duration_min')}))" % str(BOT)],
        capture_output=True, text=True, encoding="utf-8")
    try:
        got = json.loads(bind.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        got = {}
        res.failed.append(("демо-строки не связались с admin_add",
                           bind.stderr[-400:]))
    if got:
        res.ok("ключ врача попал в doctor_id",
               str(got.get("doctor_id", "")).startswith("d"),
               f"в doctor_id уехало {got.get('doctor_id')!r}")
        res.ok("дата рождения не занята ключом врача",
               got.get("birth_date") in (None, ""),
               f"в birth_date уехало {got.get('birth_date')!r}")
        res.ok("длительность услуги доехала",
               isinstance(got.get("dur"), int) and got["dur"] > 0,
               f"duration_min = {got.get('dur')!r}")

    # ⛔ Инструкция восстановления обязана требовать удаления -wal. Забытый
    # хвост от прежней базы накатывается поверх восстановленной, и картотека
    # возвращается к состоянию «до» — БЕЗ ошибки, `integrity_check` говорит ok.
    # Воспроизведено: 500 пациентов превратились в 1.
    readme = (BOT / "app" / "modules" / "settings" / "backup.py").read_text(
        encoding="utf-8", errors="replace")
    res.ok("инструкция восстановления велит удалить -wal и -shm",
           "dental.db-wal" in readme and "dental.db-shm" in readme,
           "без этого шага восстановление молча откатывается на прежнюю базу")


def suite_form(res: Result) -> None:
    """Бумажный бланк опросника и место 043/e наверху фиши."""
    with Server() as s:
        c = Client(s.url).login()
        c.post("/admin/patients/new", name="Formular Test", phone="022202020")
        pid = _pid(c, "022202020")
        c.post(f"/admin/patient/{pid}/save", name="Formular Test",
               phone="022202020", birth_date="1990-04-04")

        card = c.get(f"/admin/patient/{pid}").body
        # 043/e — в шапке фиши, а не в конце страницы
        hero = card.split("hero-acts", 1)[1].split("</div>", 1)[0]
        res.ok("043/e стоит в шапке фиши", "/fisa043" in hero,
               "документ спрятан внизу — за ним придётся скроллить")
        res.ok("ссылка на бумажный бланк есть в секции анамнеза",
               "/anamneza/print" in card, "нет печатного опросника")

        r = c.get(f"/admin/patient/{pid}/anamneza/print")
        res.check("бланк отдаётся", r.status, 200)
        page = r.body
        res.ok("бланк называет себя анкетой пациента",
               "CHESTIONAR MEDICAL AL PACIENTULUI" in page, "нет заголовка")
        res.ok("имя и дата рождения подставлены",
               "Formular Test" in page and "1990-04-04" in page,
               "шапка бланка пустая")
        res.ok("все двенадцать вопросов на листе",
               page.count("DA &nbsp;&nbsp;") == 12, "вопросов не 12")
        res.ok("есть строки под свободный текст и подпись",
               "class='ln'" in page and "Semnătura pacientului" in page,
               "нечем заполнить и негде подписать")
        res.ok("закон назван", "195/2024" in page, "нет основания обработки")

        ru = c.get(f"/admin/patient/{pid}/anamneza/print?lang=ru").body
        res.ok("русская версия бланка",
               "МЕДИЦИНСКАЯ АНКЕТА ПАЦИЕНТА" in ru and "Сахарный диабет" in ru,
               "бланк не переведён")
        res.ok("в русской версии закон назван и по-румынски",
               "Legea nr. 195/2024" in ru, "потеряно имя закона")

        anon = Client(s.url)
        res.ok("без входа бланк не отдаётся",
               anon.get(f"/admin/patient/{pid}/anamneza/print").status == 303,
               "лист с именем пациента ушёл без входа")
