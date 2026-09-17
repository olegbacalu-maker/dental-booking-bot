"""JSON API (DentPilot 2.0): охрана, конверт, первый экран «Clinica» и
рубильник React/старая форма.

Проверяется поведение НА ДАННЫХ, а не разметка: тот же clinic.json, что правит
старая форма, и тот же результат в файле. Главное, что здесь стережётся:
  · отказ API — JSON с кодом состояния, а не 303 (fetch сходил бы за
    редиректом и вернул бы клиенту форму входа как «успех»);
  · текст для человека приезжает В КОНВЕРТЕ из MSG_BANNER — клиент кодов не
    переводит;
  · старая форма и React-экран правят ОДИН файл и не затирают соседей;
  · флаг в профиле переключает экран без сборки, `?ui=legacy` возвращает
    старую форму, и React-узел никогда не лежит внутри #live.
"""
import json

from harness import Client, Result, Server

NO_KEY = {"ADMIN_KEY": ""}      # ветка PIN-файла — то, что получает клиника
API = "/api/settings/clinic"


def _j(r) -> dict:
    return json.loads(r.body)


def _server_with_flag() -> Server:
    """Сервер, у которого экран «Clinica» уже отдан React: флаг пишется в
    копию профиля ДО старта — так профиль читается, как у клиники."""
    s = Server()
    cfg = json.loads(s.clinic.read_text(encoding="utf-8"))
    cfg["ui"] = {"react": ["settings_clinic"]}
    s.clinic.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    return s


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
                  boss.post("/admin/users/save", uid="ana", name="Ana R",
                            role="receptie", pin="3333").msg, "ok_user")
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
        res.ok("старая форма видит то же имя (один файл на два экрана)",
               "Clinica Nouă" in c.get("/admin/settings/clinic").body,
               "старая форма показывает не то, что сохранил API")
        r = c.post("/admin/settings/save", part="clinic", name="Clinica Veche",
                   phone="+373 60 111 222", addr_ro="str. Nouă 2", addr_ru="")
        res.check("старая форма всё ещё сохраняет", r.msg, "ok_set")
        res.check("API видит правку старой формы",
                  _j(c.get(API))["data"]["name"], "Clinica Veche")

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
    """Рубильник: без флага старая форма, с флагом узел React в той же рамке,
    ?ui=legacy возвращает форму, флаг переживает оба пути сохранения."""
    with Server() as s:
        c = Client(s.url).login()
        page = c.get("/admin/settings/clinic").body
        res.ok("без флага — старая форма",
               "name='name'" in page and 'id="root"' not in page, "форма не та")
        res.ok("без флага бандл не подключается", "bundle.js" not in page,
               "бандл уехал на страницу без флага")

    s = _server_with_flag()
    with s:
        c = Client(s.url).login()
        page = c.get("/admin/settings/clinic").body
        res.ok("с флагом — узел React с именем экрана",
               '<div id="root" data-screen="settings_clinic">' in page, "узла нет")
        res.ok("бандл и его стили подключены с версией",
               "/static/js/bundle.js?v=" in page and "/static/css/bundle.css?v=" in page,
               "нет ссылок на бандл")
        res.ok("серверная заглушка со ссылкой на старую страницу",
               "?ui=legacy" in page and "Deschideți varianta clasică" in page,
               "пустой узел без объяснения")
        res.ok("рамка на месте: навигация к хабу и подпись раздела",
               "href='/admin/settings'>" in page and "Setări</a>" in page
               and "setări · clinica" in page, "рамка потеряна")
        res.ok("формы старого экрана на React-странице нет", "name='name'" not in page,
               "два экрана на одной странице")
        res.ok("узел React не внутри #live", 'id="live"' not in page,
               "panel.js подменит innerHTML под смонтированным деревом")
        res.ok("?msg= на React-странице показывает плашку сервера",
               "dp_toast" in c.get("/admin/settings/clinic?msg=ok_set").body,
               "ответ на действие потерян")
        legacy = c.get("/admin/settings/clinic?ui=legacy").body
        res.ok("?ui=legacy возвращает старую форму",
               "name='name'" in legacy and 'id="root"' not in legacy, "форма не вернулась")
        res.ok("хаб настроек не изменился (плитка клиники на месте)",
               "/admin/settings/clinic" in c.get("/admin/settings").body, "плитки нет")
        dash = c.get("/admin").body
        res.ok("живой журнал без узла React (#live и #root не встречаются)",
               'id="live"' in dash and 'id="root"' not in dash, "флаг задел журнал")

        r = c.post("/admin/settings/save", part="clinic", name="Clinica Flag",
                   phone="+373 1", addr_ro="", addr_ru="")
        res.check("старая форма сохраняет при флаге", r.msg, "ok_set")
        after = json.loads(s.clinic.read_text(encoding="utf-8"))
        res.check("флаг пережил сохранение старой формой",
                  after.get("ui"), {"react": ["settings_clinic"]})
        res.check("API сохраняет при флаге",
                  c.post_json(API, {"name": "Clinica Flag 2", "phone": "+373 2"}).status, 200)
        after = json.loads(s.clinic.read_text(encoding="utf-8"))
        res.check("флаг пережил сохранение через API",
                  after.get("ui"), {"react": ["settings_clinic"]})
        res.check("имя после API", after["name"], "Clinica Flag 2")

    # право: React-страница закрыта той же require, что и старая
    s = _server_with_flag()
    s.extra_env = dict(NO_KEY)
    with s:
        boss = Client(s.url)
        boss.post("/admin/setup", pin1="1111", pin2="1111")
        boss.post("/admin/users/save", uid="ana", name="Ana R", role="receptie", pin="3333")
        ana = Client(s.url)
        ana.post("/admin/login", password="3333", next="/admin")
        r = ana.get("/admin/settings/clinic")
        res.ok("регистратуре React-страница закрыта, как и старая",
               r.status == 303 and r.msg == "no_access", f"{r!r}")
