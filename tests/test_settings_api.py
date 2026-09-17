"""Настройки, пачка A (хаб, сеть, справка, часы): JSON API и рубильники.

Главное, что стережётся: старая страница и React-экран собраны из ОДНИХ
данных (`_hub_tiles`, `faq.entries`, `lan.*_html`, `_val_hours`) — подпись,
которой нет на старой странице, не может появиться и в JSON, и наоборот.
"""
import json
import pathlib
import shutil
import tempfile

from harness import TG_ON, Client, Result, Server

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
FLAGS = ["settings_clinic", "doctors_list", "doctor_card", "settings_hub",
         "settings_lan", "settings_faq", "settings_hours"]


def _j(r) -> dict:
    return json.loads(r.body)


def _server_with_flags(env: dict | None = None) -> Server:
    s = Server(env=env)
    cfg = json.loads(s.clinic.read_text(encoding="utf-8"))
    cfg["ui"] = {"react": list(FLAGS)}
    s.clinic.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    return s


def suite_hub(res: Result) -> None:
    """Плитки хаба — данными, и ровно те же, что рисует старая страница."""
    with Server() as s:
        res.check("без входа — 401", Client(s.url).get("/api/settings/hub").status, 401)
        c = Client(s.url).login()
        d = _j(c.get("/api/settings/hub"))["data"]
        hrefs = [t["href"] for t in d["tiles"]]
        res.check("порядок плиток — как на старой странице", hrefs[:6],
                  ["/admin/settings/system", "/admin/settings/clinic",
                   "/admin/settings/theme", "/admin/settings/hours",
                   "/admin/settings/services", "/admin/medici"])
        res.check("справка — последней", hrefs[-1], "/admin/settings/faq")
        res.ok("без dental.env плитки сети нет", "/admin/settings/lan" not in hrefs, f"{hrefs}")
        by = {t["href"]: t for t in d["tiles"]}
        sys_t = by["/admin/settings/system"]
        res.ok("система: иконка и тон именами, версия первым куском",
               sys_t["icon"] == "info" and sys_t["tone"] == "b"
               and sys_t["hint"][0]["t"].startswith("v"), f"{sys_t}")
        res.check("клиника: имя из профиля", by["/admin/settings/clinic"]["hint"],
                  [{"t": "Clinica Test"}])
        th = by["/admin/settings/theme"]["hint"]
        res.ok("тема: подпись стиля, точка цвета и hex",
               th[0]["t"].endswith(" · ") and "dot" in th[1] and th[2]["t"].startswith("#"),
               f"{th}")
        res.ok("часы: «azi 7:00–21:00» (фикстура без выходных)",
               by["/admin/settings/hours"]["hint"] == [{"t": "azi 7:00–21:00"}],
               f"{by['/admin/settings/hours']['hint']}")
        res.ok("услуги: число", by["/admin/settings/services"]["hint"][0]["t"].endswith(" servicii"),
               f"{by['/admin/settings/services']['hint']}")
        res.ok("врачи: активных трое", by["/admin/medici"]["hint"][0]["t"].startswith("3 activi"),
               f"{by['/admin/medici']['hint']}")
        res.ok("шифрование: кусок с иконкой или слово",
               by["/admin/settings/crypt"]["hint"] in ([{"t": "oprită"}],
                                                       [{"icon": "check", "t": "activă"}]),
               f"{by['/admin/settings/crypt']['hint']}")
        page = c.get("/admin/settings").body
        res.ok("каждая подпись плитки есть и на старой странице",
               all(t["label"] in page for t in d["tiles"]), "подписи разошлись")
        res.ok("каждая ссылка плитки есть и на старой странице",
               all(f"href='{t['href']}'" in page for t in d["tiles"]), "адреса разошлись")

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="dp_hub_"))
    env_path = tmp / "dental.env"
    env_path.write_text("TELEGRAM_TOKEN=\n", encoding="utf-8")
    try:
        with Server(env={"DENTART_ENV_FILE": str(env_path)}) as s:
            c = Client(s.url).login()
            by = {t["href"]: t for t in _j(c.get("/api/settings/hub"))["data"]["tiles"]}
            res.check("с dental.env — плитка сети с подписью «выключено»",
                      by.get("/admin/settings/lan", {}).get("hint"),
                      [{"t": "al doilea calculator, telefon — oprit"}])
            res.ok("без токена плитки Telegram нет", "/admin/settings/telegram" not in by,
                   f"{list(by)}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def suite_lan(res: Result) -> None:
    """Сеть клиники: состояние и проза с сервера, переключение — тот же
    _set_lan, что у формы; брандмауэр в тестах не трогаем (UAC)."""
    with Server() as s0:
        c0 = Client(s0.url).login()
        res.check("без dental.env — 404", c0.get("/api/settings/lan").status, 404)
        res.check("без dental.env и POST — 404",
                  c0.post_json("/api/settings/lan", {"mode": "on"}).status, 404)

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="dp_lanapi_"))
    env_path = tmp / "dental.env"
    env_path.write_text("TELEGRAM_TOKEN=\n", encoding="utf-8")
    try:
        with Server(env={"DENTART_ENV_FILE": str(env_path)}) as s:
            res.check("без входа — 401", Client(s.url).get("/api/settings/lan").status, 401)
            c = Client(s.url).login()
            d = _j(c.get("/api/settings/lan"))["data"]
            res.check("выключен", d["enabled"], False)
            res.ok("порт — число", isinstance(d["port"], int), f"{d['port']!r}")
            res.check("адреса нет, пока выключен", d["url"], "")
            res.ok("проза: предупреждение о второй установке",
                   "Nu instalați programul" in d["blocks"]["intro"], "предупреждения нет")
            res.ok("состояние: «oprit»", "oprit" in d["blocks"]["status"], d["blocks"]["status"][:80])
            res.ok("советов и брандмауэра нет, пока выключен",
                   d["blocks"]["tips"] == "" and d["blocks"]["firewall"] == "", "лишние блоки")

            r = c.post_json("/api/settings/lan", {"mode": "on"})
            res.check("включение — 200", r.status, 200)
            j = _j(r)
            res.check("код ok_set", j["code"], "ok_set")
            res.ok("вне настольного издания перезапуска и текста нет",
                   j["data"]["restart"] is False and j["data"]["text"] == "", f"{j['data']}")
            res.ok("dental.env получил DENTART_LAN=1",
                   "DENTART_LAN=1" in env_path.read_text(encoding="utf-8"), "флага нет")
            d = _j(c.get("/api/settings/lan"))["data"]
            res.check("включён", d["enabled"], True)
            res.ok("состояние: адрес с QR либо «нет сети»",
                   ("Activ" in d["blocks"]["status"] and d["url"].startswith("http://")
                    and "/qr?data=" in d["blocks"]["status"])
                   or "nu pare conectat" in d["blocks"]["status"], d["blocks"]["status"][:120])
            res.ok("советы приехали", "De știut" in d["blocks"]["tips"], "советов нет")
            res.ok("брандмауэр: да / нет / проверить нечем", d["firewall"] in (True, False, None),
                   f"{d['firewall']!r}")
            res.ok("блок брандмауэра ровно тогда, когда правила нет",
                   bool(d["blocks"]["firewall"]) == (d["firewall"] is False), f"{d['firewall']!r}")
            res.ok("старая страница видит включённый режим",
                   "Dezactivează accesul" in c.get("/admin/settings/lan").body, "не видит")

            r = c.post_json("/api/settings/lan", {"mode": "off"})
            res.check("выключение — ok_set", _j(r)["code"], "ok_set")
            res.ok("флаг в файле погашен",
                   "DENTART_LAN=1" not in env_path.read_text(encoding="utf-8"), "не погашен")
            res.ok("соседние ключи env уцелели",
                   "TELEGRAM_TOKEN=" in env_path.read_text(encoding="utf-8"), "затёрты")
            r = c.post_json("/api/settings/lan", {"mode": "sideways"})
            res.ok("неизвестный режим — 422 с полем", r.status == 422 and _j(r).get("field") == "mode",
                   r.body)
            res.check("брандмауэр без входа — 401",
                      Client(s.url).post_json("/api/settings/lan/firewall", {}).status, 401)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def suite_faq(res: Result) -> None:
    """Справка: те же вопросы и ответы, что на старой странице, данными."""
    with Server() as s:
        c = Client(s.url).login()
        d = _j(c.get("/api/settings/faq"))["data"]
        res.ok("вопросов не меньше десяти", len(d["items"]) >= 10, f"{len(d['items'])}")
        res.check("контакт — почта поддержки", d["contact"], "dentpilotpro@gmail.com")
        first = d["items"][0]
        res.ok("первый вопрос — про копии", "copii de rezervă" in first["question"], first["question"])
        res.check("иконка — имя, не разметка", first["icon"], "save")
        res.ok("ответ — HTML с абзацами", "<p" in first["answer"] and "<svg" not in first["question"],
               first["answer"][:60])
        res.ok("ответ про 7-Zip есть (как на старой странице)",
               any("7-Zip" in it["answer"] for it in d["items"]), "нет")
        res.ok("без бота абзац про токен не отдаётся",
               not any("tokenul botului" in it["answer"] for it in d["items"]), "есть")
        page = c.get("/admin/settings/faq").body
        res.ok("старая страница задаёт те же вопросы",
               all(it["question"] in page for it in d["items"]), "вопросы разошлись")
    with Server(env=TG_ON) as s:
        c = Client(s.url).login()
        d = _j(c.get("/api/settings/faq"))["data"]
        res.ok("клинике с ботом — абзац про токен",
               any("tokenul botului" in it["answer"] for it in d["items"]), "нет")


def suite_hours(res: Result) -> None:
    """Часы работы: тот же payload, что слал скрипт страницы, та же _val_hours."""
    with Server() as s:
        c = Client(s.url).login()
        d = _j(c.get("/api/settings/hours"))["data"]
        res.check("семь дней по порядку", [x["key"] for x in d["days"]], list(DAYS))
        res.check("подписи дней — с сервера", d["days"][0]["label"], "Luni")
        res.check("диапазон часов из констант", d["range"], {"min": 7, "max": 21})
        res.check("часы фикстуры", d["hours"]["mon"], [7, 21])

        body = {"hours": {"mon": [9, 18], "tue": [9, 18], "wed": None, "thu": [9, 18],
                          "fri": [9, 18, 13, 14], "sat": None, "sun": None}}
        r = c.post_json("/api/settings/hours", body)
        res.check("сохранение — 200", r.status, 200)
        j = _j(r)
        res.check("код ok_set", j["code"], "ok_set")
        res.ok("ответ несёт сохранённые часы",
               j["data"]["hours"]["wed"] is None and j["data"]["hours"]["fri"] == [9, 18, 13, 14],
               f"{j['data']['hours']}")
        after = json.loads(s.clinic.read_text(encoding="utf-8"))
        res.ok("файл: среда закрыта, обед пятницы записан",
               after["hours"]["wed"] is None and after["hours"]["fri"] == [9, 18, 13, 14],
               f"{after['hours']}")
        res.ok("соседи профиля целы", after["name"] == "Clinica Test" and len(after["services"]) >= 4
               and len(after["doctors"]) == 4, "затёрты")
        res.ok("строка контактов боту пересобрана", "13" in after.get("contacts", {}).get("ro", ""),
               "contacts не отражает обед")
        before = s.clinic.read_bytes()
        c.post_json("/api/settings/hours", body)
        res.ok("повторный POST тождествен", s.clinic.read_bytes() == before, "файл изменился")
        res.ok("старая страница видит среду закрытой",
               "id='hc_wed' checked" in c.get("/admin/settings/hours").body, "не видит")

        r = c.post_json("/api/settings/hours", {"hours": {dd: None for dd in DAYS}})
        res.ok("вся неделя закрыта — 422 bad_set", r.status == 422 and _j(r)["code"] == "bad_set",
               r.body)
        r = c.post_json("/api/settings/hours", {"hours": {"mon": [9, 18, 13, 20]}})
        res.check("обед за пределами дня — 422", r.status, 422)
        r = c.post_json("/api/settings/hours", {"hours": {"mon": "9"}})
        res.check("день не списком — 422", r.status, 422)
        r = c.post_json("/api/settings/hours", {"hours": "x"})
        res.check("часы не объектом — 422", r.status, 422)
        res.ok("отказы файл не тронули",
               json.loads(s.clinic.read_text(encoding="utf-8"))["hours"]["fri"] == [9, 18, 13, 14],
               "тронули")

        r = c.post("/admin/settings/save", part="hours",
                   payload=json.dumps({"hours": {dd: [8, 20] for dd in DAYS}}))
        res.check("старая форма всё ещё сохраняет", r.msg, "ok_set")
        res.check("API видит правку старой формы",
                  _j(c.get("/api/settings/hours"))["data"]["hours"]["sun"], [8, 20])


def suite_switch(res: Result) -> None:
    """Четыре флага пачки A: узел React в той же рамке, ?ui=legacy, охрана."""
    s = _server_with_flags()
    with s:
        c = Client(s.url).login()
        for path, screen, old in (("/admin/settings", "settings_hub", "class='pl-tile'"),
                                  ("/admin/settings/faq", "settings_faq", "<details class='faq'"),
                                  ("/admin/settings/hours", "settings_hours", "id='hc_mon'")):
            page = c.get(path).body
            res.ok(f"{path}: узел React", f'data-screen="{screen}"' in page, "узла нет")
            res.ok(f"{path}: старой разметки нет", old not in page, "две разметки")
            res.ok(f"{path}: бандл подключён", "/static/js/bundle.js?v=" in page, "нет бандла")
            legacy = c.get(f"{path}?ui=legacy").body
            res.ok(f"{path}?ui=legacy: старая разметка", old in legacy and 'id="root"' not in legacy,
                   "не вернулась")
        res.ok("хаб: рамка и плашка сервера",
               "setările clinicii" in c.get("/admin/settings").body
               and "dp_toast" in c.get("/admin/settings?msg=ok_set").body, "рамка потеряна")
        res.ok("сеть без dental.env — по-прежнему на хаб, флаг не мешает",
               c.get("/admin/settings/lan").location == "/admin/settings", "иначе")

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="dp_lanflag_"))
    env_path = tmp / "dental.env"
    env_path.write_text("TELEGRAM_TOKEN=\n", encoding="utf-8")
    try:
        s = _server_with_flags(env={"DENTART_ENV_FILE": str(env_path)})
        with s:
            c = Client(s.url).login()
            page = c.get("/admin/settings/lan").body
            res.ok("сеть: узел React", 'data-screen="settings_lan"' in page, "узла нет")
            res.ok("сеть: старой кнопки нет", "Activează accesul" not in page, "две разметки")
            res.ok("сеть ?ui=legacy: старая страница",
                   "Activează accesul" in c.get("/admin/settings/lan?ui=legacy").body, "нет")
            r = c.post("/admin/lan/save", mode="on")
            res.check("старая форма переключает при флаге", r.msg, "ok_set")
            res.ok("флаги пережили правку профиля (сеть живёт в env, профиль цел)",
                   json.loads(s.clinic.read_text(encoding="utf-8")).get("ui") == {"react": FLAGS},
                   "флаги потеряны")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    s = _server_with_flags(env={"ADMIN_KEY": ""})
    with s:
        boss = Client(s.url)
        boss.post("/admin/setup", pin1="1111", pin2="1111")
        boss.post("/admin/users/save", uid="ana", name="Ana R", role="receptie", pin="3333")
        ana = Client(s.url)
        ana.post("/admin/login", password="3333", next="/admin")
        for path in ("/admin/settings", "/admin/settings/faq", "/admin/settings/hours"):
            r = ana.get(path)
            res.ok(f"регистратуре React-страница {path} закрыта, как и старая",
                   r.status == 303 and r.msg == "no_access", f"{r!r}")
        res.check("регистратуре закрыт и JSON хаба", ana.get("/api/settings/hub").status, 403)
