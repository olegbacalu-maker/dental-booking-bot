"""JSON API (DentPilot 2.0): охрана, конверт и первый экран «Clinica».

Проверяется поведение НА ДАННЫХ, а не разметка: тот же clinic.json, что правит
старая форма, и тот же результат в файле. Главное, что здесь стережётся:
  · отказ API — JSON с кодом состояния, а не 303 (fetch сходил бы за
    редиректом и вернул бы клиенту форму входа как «успех»);
  · текст для человека приезжает В КОНВЕРТЕ из MSG_BANNER — клиент кодов не
    переводит;
  · экран правит clinic.json, не затирая соседей.
(Рубильник «флаг профиля / `?ui=legacy`» и правило «узел React не внутри
#live» сняты шагом 6 снятия старого интерфейса, 13.10: старых страниц нет.)
"""
import json

from harness import Client, Result, Server

NO_KEY = {"ADMIN_KEY": ""}      # ветка PIN-файла — то, что получает клиника
API = "/api/settings/clinic"


def _j(r) -> dict:
    return json.loads(r.body)


def suite_guard(res: Result) -> None:
    """Охрана /api/*: 401 без входа, 403 без права и с чужим Origin —
    всегда JSON, никогда редирект."""
    with Server() as s:                       # вход по ADMIN_KEY (облачная ветка)
        anon = Client(s.url)
        r = anon.get(API)
        res.check("без входа — 401", r.status, 401)
        res.ok("отказ — JSON, не редирект",
               "application/json" in r.header("Content-Type") and not r.location,
               f"Content-Type {r.header('Content-Type')!r}, Location {r.location!r}")
        res.check("конверт: ok=false", _j(r).get("ok"), False)
        res.ok("конверт несёт code, text и tone",
               all(k in _j(r) for k in ("code", "text", "tone")), f"{r.body[:120]}")
        r = anon.post_json(API, {"name": "X", "phone": "1"})
        res.check("POST без входа — 401", r.status, 401)

        c = Client(s.url).login()
        res.check("после входа — 200", c.get(API).status, 200)
        evil = {"Origin": "http://atacator.example"}
        r = c.post_json(API, {"name": "Rău", "phone": "1"}, headers=evil)
        res.check("POST с чужим Origin — 403", r.status, 403)
        res.ok("чужой Origin ничего не записал",
               json.loads(s.clinic.read_text(encoding="utf-8"))["name"] == "Clinica Test",
               "профиль перезаписан чужой страницей")
        own = {"Origin": f"http://127.0.0.1:{s.port}"}
        r = c.post_json(API, {"name": "Clinica Test", "phone": "+373 60 000 000",
                              "address": {"ro": "str. Test 1, Cahul",
                                          "ru": "ул. Тест 1, Кахул"}}, headers=own)
        res.check("свой Origin (браузер программы) проходит", r.status, 200)

    with Server(env=NO_KEY) as s:             # ветка PIN-файла и роли
        anon = Client(s.url)
        r = anon.get(API)
        res.check("без PIN-файла API закрыт (401), а не ведёт на setup",
                  r.status, 401)
        res.ok("и это JSON", "application/json" in r.header("Content-Type"),
               r.header("Content-Type"))
        boss = Client(s.url)
        boss.post("/admin/setup", pin1="1111", pin2="1111")
        res.check("регистратура заводится",
                  boss.post_json("/api/settings/users", {"uid": "ana", "name": "Ana R",
                                                        "role": "receptie", "pin": "3333"}).msg, "ok_user")
        res.check("директор — 200", boss.get(API).status, 200)
        ana = Client(s.url)
        ana.post("/admin/login", password="3333", next="/admin")
        r = ana.get(API)
        res.check("регистратура — 403", r.status, 403)
        j = _j(r)
        res.check("код отказа — no_access (тот же, что у страницы)",
                  j.get("code"), "no_access")
        res.ok("текст отказа — из словаря, не пустой",
               j.get("tone") == "err" and "director" in j.get("text", ""),
               f"{j}")
        r = ana.post_json(API, {"name": "Ana", "phone": "1"})
        res.check("регистратура не пишет — 403", r.status, 403)


def suite_clinic(res: Result) -> None:
    """Данные экрана «Clinica»: GET отдаёт профиль, POST пишет тот же файл,
    что и старая форма, соседи не страдают, повтор тождествен."""
    with Server() as s:
        c = Client(s.url).login()
        j = _j(c.get(API))
        d = j["data"]
        res.check("GET: имя из профиля", d["name"], "Clinica Test")
        res.check("GET: телефон", d["phone"], "+373 60 000 000")
        res.check("GET: адрес RO", d["address"]["ro"], "str. Test 1, Cahul")
        res.check("GET: адрес RU", d["address"]["ru"], "ул. Тест 1, Кахул")
        res.check("GET: профиль не шаблонный", d["template"], False)
        res.check("GET: юрлицо и IDNO есть в конверте, по умолчанию пустые",
                  (d["legal_name"], d["idno"]), ("", ""))
        res.ok("GET: подсказка шаблона есть в конверте (для пустого состояния)",
               "datele de exemplu" in d["hint"], d["hint"])
        res.ok("GET: успех без кода — пустой текст, tone ok",
               j["code"] == "" and j["text"] == "" and j["tone"] == "ok", f"{j}")

        body = {"name": "Clinica Nouă", "phone": "+373 60 111 222",
                "address": {"ro": "str. Nouă 2", "ru": ""}}
        r = c.post_json(API, body)
        res.check("POST: 200", r.status, 200)
        j = _j(r)
        res.check("POST: код ok_set", j["code"], "ok_set")
        res.check("POST: текст из MSG_BANNER", j["text"], "Setări salvate")
        res.check("POST: tone ok", j["tone"], "ok")
        res.check("POST: ответ несёт сохранённые данные", j["data"]["name"],
                  "Clinica Nouă")
        after = json.loads(s.clinic.read_text(encoding="utf-8"))
        res.check("файл: имя обновилось", after["name"], "Clinica Nouă")
        res.check("файл: адрес RO", after["address"]["ro"], "str. Nouă 2")
        res.ok("файл: услуги пережили сохранение",
               len(after["services"]) >= 4 and any(
                   sv.get("id") == "hygiene" for sv in after["services"]),
               "services затёрты")
        res.check("файл: врачи пережили сохранение", len(after["doctors"]), 4)
        res.ok("файл: contacts пересобраны из новых значений",
               "str. Nouă 2" in after["contacts"]["ro"]
               and "+373 60 111 222" in after["contacts"]["ru"],
               f"{after.get('contacts')}")

        # ⭐ пересохранение БЕЗ единой правки обязано быть тождественным —
        # дешёвая проверка на весь класс потерь данных (08-16)
        before = s.clinic.read_bytes()
        res.check("повторный POST того же тела — 200", c.post_json(API, body).status, 200)
        res.ok("повторный POST тождествен байт в байт",
               s.clinic.read_bytes() == before, "файл изменился без правки")

        res.check("GET после сохранения", _j(c.get(API))["data"]["name"], "Clinica Nouă")
        r = c.post_json(API, {"name": "Clinica Veche", "phone": "+373 60 111 222",
                              "address": {"ro": "str. Nouă 2", "ru": ""},
                              "legal_name": "Veche SRL", "idno": "1003600012345"})
        res.check("юрлицо и IDNO сохраняются", r.msg, "ok_set")
        res.check("API отдаёт юрлицо и IDNO",
                  (_j(c.get(API))["data"]["legal_name"], _j(c.get(API))["data"]["idno"]),
                  ("Veche SRL", "1003600012345"))
        res.ok("старая форма настроек снята (12.10)",
               c.post("/admin/settings/save", part="clinic", name="X").status in (404, 405),
               "форма жива")

        # ---- отказы: тот же _val_clinic, что у формы, плюс имя поля ----
        r = c.post_json(API, {"name": "", "phone": "1"})
        res.check("пустое имя — 422", r.status, 422)
        j = _j(r)
        res.check("код bad_set", j["code"], "bad_set")
        res.check("виновное поле — name", j.get("field"), "name")
        res.ok("текст отказа из словаря", j["text"].startswith("Setări invalide"), j["text"])
        r = c.post_json(API, {"name": "X", "phone": ""})
        res.check("пустой телефон — 422, поле phone", _j(r).get("field"), "phone")
        r = c._do(API, b"not json at all", {"Content-Type": "application/json"})
        res.check("не-JSON тело — 422", r.status, 422)
        res.ok("не-JSON тело — без поля", "field" not in _j(r), r.body)
        r = c.post_json(API, {"name": "X", "phone": "1", "address": ["не", "объект"]})
        res.check("адрес не объектом — принимается как пустой", r.status, 200)
        res.ok("отказы не тронули файл, удача — записала",
               json.loads(s.clinic.read_text(encoding="utf-8"))["name"] == "X",
               "в файле не то, что ждали")
        r = c.post_json(API, {"name": "Й" * 200, "phone": "+373 " + "9" * 40})
        res.check("длина режется как у формы: имя 80", len(_j(r)["data"]["name"]), 80)
        res.check("телефон 30", len(_j(r)["data"]["phone"]), 30)


def suite_switch(res: Result) -> None:
    """Экран «Clinica» — узел React в оболочке из модели (старая форма снята
    12.10, рубильник — 13.10). Старая оболочка (уголок, сайдбар) проверяется
    на странице, которая ещё серверная: «QR pacienți» без бота."""
    with Server() as s:
        c = Client(s.url).login()
        page = c.get("/admin/settings/clinic").body
        res.ok("узел React с именем экрана, старой формы нет",
               '<div id="root" data-screen="settings_clinic"' in page and "name='name'" not in page,
               "узла нет или вернулась старая форма")
        # ⭐ B1: модель оболочки приезжает ИНЛАЙНОМ тем же узлом.
        shell = json.loads(page.split('data-shell="', 1)[1].split('"', 1)[0]
                           .replace("&quot;", '"'))
        res.ok("бандл и его стили подключены с версией",
               "/static/js/bundle.js?v=" in page and "/static/css/bundle.css?v=" in page,
               "нет ссылок на бандл")
        # заглушка зовёт перезагрузить ТОТ ЖЕ адрес (старой страницы нет с 13.10)
        res.ok("серверная заглушка с объяснением, если бандл не загрузился",
               "Interfața nu s-a încărcat" in page
               and '<a href="/admin/settings/clinic">Reîncărcați pagina</a>' in page
               and "ui=legacy" not in page, "пустой узел без объяснения или ссылка не та")
        # ⛔ Рамку больше не печатает сервер — она в модели. Проверяем ЗНАЧЕНИЯ,
        # а не литералы разметки: крошка, подпись раздела и активный пункт.
        res.ok("рамка на месте: крошка к хабу, подпись раздела, активный пункт",
               [c["href"] for c in shell["frame"]["crumbs"]] == ["/admin/settings", "/admin"]
               and shell["frame"]["crumbs"][0]["label"] == "Setări"
               and shell["frame"]["title"] == "Setări"
               and shell["frame"]["sub"] == "setări · clinica"
               and shell["nav"]["active"] == "set",
               f"{shell['frame']['crumbs']} {shell['frame']['sub']} {shell['nav']['active']}")
        res.check("колокольчика в модели оболочки нет (снят 13.10 со старой панелью)",
                  "bell" in shell["frame"], False)
        # Уголок (06.10): знак со словом — ссылка на сайт, почта — на домене
        # сайта. Знак — SVG сервера со СВОЕЙ приставкой id, не та, что у сайдбара.
        site, fb = shell["frame"].get("site") or {}, shell["frame"]["feedback"]
        res.ok("уголок в модели: сайт, знак со своей приставкой, почта на домене сайта",
               site.get("href") == "https://dentpilot.md"
               and "bcmark" in site.get("mark", "") and "svg" in site.get("mark", "")
               and fb["email"] == "contact@dentpilot.md"
               and fb["href"].startswith("mailto:contact@dentpilot.md?subject="),
               f"{site.get('href')!r} {fb}")
        res.ok("серверного каркаса на React-странице нет",
               "<aside" not in page and 'class="top"' not in page
               and "/static/js/panel.js" not in page, "две оболочки разом")
        res.ok("?msg= на React-странице показывает плашку сервера",
               "dp_toast" in c.get("/admin/settings/clinic?msg=ok_set").body,
               "ответ на действие потерян")
        # ⛔ Сайт — только в системном браузере: без target=_blank окно
        # программы само ушло бы на сайт, и вернуться было бы нечем.
        # Серверная оболочка (`_shell`) жива у страниц замороженного бота —
        # Setări › Telegram и «QR pacienți» без бота (Олег 13.10: бот заморожен,
        # его страницы не трогаем).
        old = c.get("/admin/qr-print").body
        res.ok("старая оболочка: знак — ссылка на сайт с target=_blank, почта contact@",
               'class="bc-site" href="https://dentpilot.md" target="_blank" rel="noopener"' in old
               and 'href="mailto:contact@dentpilot.md?subject=' in old,
               "уголок не тот")
        res.ok("старая оболочка: под именем клиники нет подписи DentPilot (06.10)",
               "<small>DentPilot</small>" not in old and '<div class="txt"><b' in old,
               "подпись вернулась или сайдбар не тот")
        res.ok("старая оболочка: ни живой обёртки, ни опроса, ни колокольчика (шаг 6)",
               'id="live"' not in old and "data-reload" not in old
               and "class='bell'" not in old, "каркас старой панели вернулся")
        res.ok("хаб настроек не изменился (плитка клиники на месте)",
               any(t["href"] == "/admin/settings/clinic"
                   for t in _j(c.get("/api/settings/hub"))["data"]["tiles"]), "плитки нет")
        res.check("API сохраняет",
                  c.post_json(API, {"name": "Clinica Flag 2", "phone": "+373 2"}).status, 200)
        after = json.loads(s.clinic.read_text(encoding="utf-8"))
        res.check("имя после API", after["name"], "Clinica Flag 2")
        res.check("ключа ui.react в профиле нет (снят шагом 6)", "ui" in after, False)

    # право: React-страница закрыта той же require, что была у старой
    with Server(env=NO_KEY) as s:
        boss = Client(s.url)
        boss.post("/admin/setup", pin1="1111", pin2="1111")
        boss.post_json("/api/settings/users", {"uid": "ana", "name": "Ana R", "role": "receptie", "pin": "3333"})
        ana = Client(s.url)
        ana.post("/admin/login", password="3333", next="/admin")
        r = ana.get("/admin/settings/clinic")
        res.ok("регистратуре React-страница закрыта",
               r.status == 303 and r.msg == "no_access", f"{r!r}")


def suite_live_envelope(res: Result) -> None:
    """Конверт живого канала — без сервера, обе полярности (C26.5.2).

    (До 13.10 здесь же держалось правило «узел React не внутри #live
    серверного каркаса»: `_shell` не объявлял страницу живой при узле React.
    Живых страниц у каркаса больше нет — `#live`, `LIVE_RELOAD` и
    `react_mount` сняты шагом 6 снятия старого интерфейса.)
    """
    import pathlib
    import sys
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "bot"))

    # ---- конверт живого канала: обе полярности, без сервера (C26.5.2) ----
    # ⭐ Ветка «состояния нет» раньше включалась ФЛАГОМ React и потому не
    # исполнялась ничем: имени `schedule_dash` не было в REACT_SCREENS. Теперь
    # это чистая функция, и обе её полярности проходят в КАЖДОМ прогоне.
    # ⛔ Здесь же держится главное правило конверта: `live` — не отдельное
    # утверждение, а имя того же факта, что и состав. Разойдись они — клиент
    # получил бы «успех», по которому нечего нарисовать.
    import datetime as _dt

    from app.core import api as A

    d = _dt.date(2026, 9, 19)
    full = A.live_envelope("panel", d, {"canvas": {"columns": []}, "agenda": {}})
    empty = A.live_envelope("panel", d, None)
    res.check("состояние есть → live истинно И состав на месте",
              (full["live"], full["screen"], full["date"], "canvas" in full),
              (True, "panel", "2026-09-19", True))
    res.check("состояния нет → live ложно, и в конверте ТОЛЬКО эхо",
              (empty["live"], sorted(empty)), (False, ["date", "live", "screen"]))
    res.ok("флаг и состав — ОДИН факт, а не два",
           all(A.live_envelope("panel", d, st)["live"] == (st is not None)
               for st in (None, {}, {"canvas": 1})),
           "live посчитан отдельно от состава — однажды разойдутся")

    # ⛔ Ни поверхность, ни версия, ни часы НЕ ТЕКУТ В ОТПЕЧАТОК: всё, что
    # попало в data, попало и в отпечаток, и панель перерисовалась бы, хотя в
    # дне не изменилось ничего. (Поверхность ехала заголовком до 13.10 — со
    # снятием старой панели спрашивать её стало некому.)
    res.check("в конверте нет ни поверхности, ни версии, ни часов",
              [k for k in ("surface", "ui", "version", "updated") if k in full],
              [])
