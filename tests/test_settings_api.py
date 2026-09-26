"""Настройки, пачка A (хаб, сеть, справка, часы): JSON API и рубильники.

Главное, что стережётся: старая страница и React-экран собраны из ОДНИХ
данных (`_hub_tiles`, `faq.entries`, `lan.*_html`, `_val_hours`) — подпись,
которой нет на старой странице, не может появиться и в JSON, и наоборот.
"""
import html
import json
import pathlib
import re
import tempfile

from harness import FIXTURES, TG_ON, Client, Result, Server, _rmtree_settled

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
FLAGS = ["settings_clinic", "doctors_list", "doctor_card", "settings_hub",
         "settings_lan", "settings_faq", "settings_hours", "settings_services",
         "settings_theme", "settings_security", "settings_backup",
         "settings_crypt", "settings_system", "patients_search"]
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 120
NO_KEY = {"ADMIN_KEY": ""}      # ветка PIN-файла — то, что получает клиника


def _j(r) -> dict:
    return json.loads(r.body)


def _rec(s: Server) -> dict:
    return json.loads((s.dir / "auth.json").read_text(encoding="utf-8"))


def _cfg(s: Server) -> dict:
    return json.loads(s.clinic.read_text(encoding="utf-8"))


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
        # группы (B5, шаг 9): порядок и подписи — с сервера, у каждой плитки
        # группа из этого списка; на старой странице те же подзаголовки
        keys = [g["key"] for g in d["groups"]]
        res.check("группы в порядке «Параметров»",
                  keys, ["general", "programari", "medici", "date", "securitate", "ajutor"])
        res.ok("у каждой плитки группа из списка",
               all(t["group"] in keys for t in d["tiles"]),
               f"{[(t['href'], t.get('group')) for t in d['tiles']]}")
        res.check("порядок внутри групп — прежний порядок плиток",
                  [t["href"] for t in d["tiles"] if t["group"] == "general"],
                  ["/admin/settings/system", "/admin/settings/clinic", "/admin/settings/theme"])
        shown = {t["group"] for t in d["tiles"]}
        res.ok("старая страница рисует подзаголовки только непустых групп",
               all((f"<h3>{g['label']}</h3>" in page) == (g["key"] in shown) for g in d["groups"]),
               f"группы с плитками: {sorted(shown)}")

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
        _rmtree_settled(tmp)


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
            fw = d["fw"]
            res.ok("вердикт словами и сеть, в которой он получен",
                   fw is None or (fw["verdict"] in ("ok", "missing", "blocked", "shut")
                                  and {"category", "network"} <= set(fw)), f"{fw!r}")
            res.ok("«да / нет» выведено из вердикта",
                   (fw is None and d["firewall"] is None)
                   or (fw is not None and d["firewall"] == (fw["verdict"] == "ok")),
                   f"{fw!r} / {d['firewall']!r}")
            # кнопка лечит отсутствие разрешения и запрет на exe; «закрыты все
            # входящие» — настройка профиля Windows, и кнопка ей не поможет
            res.ok("блок с кнопкой ровно тогда, когда кнопка лечит",
                   bool(d["blocks"]["firewall"])
                   == (fw is not None and fw["verdict"] in ("missing", "blocked")), f"{fw!r}")
            res.ok("проверка связи под адресом",
                   "Verificarea legăturii" in d["blocks"]["status"]
                   or "nu pare conectat" in d["blocks"]["status"], d["blocks"]["status"][-200:])
            res.ok("прогон ходит с петли — из сети не пришёл никто",
                   "Încă niciun dispozitiv" in d["blocks"]["status"]
                   or "nu pare conectat" in d["blocks"]["status"], d["blocks"]["status"][-200:])
            res.ok("совета «сеть обязана быть Private» больше нет — кнопка разрешает и "
                   "публичную", "«Private», nu «Public»" not in d["blocks"]["tips"], "совет остался")
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
        _rmtree_settled(tmp)


def suite_system(res: Result) -> None:
    """«Stare sistem»: версия, база, ПУТЬ к папке данных, обновление, вход.

    ⭐ Главное, что стережётся, — ФАКТ вместо описания. Это единственный экран,
    по которому директор сверяет, куда программа пишет; описание раскладки
    словами протухает молча (хвост P1, 21.09: семь фраз уехали клиникам,
    описывая «рядом с exe»), а путь из того же места, куда программа пишет, —
    нет.
    """
    with Server() as s:
        res.check("без входа — 401", Client(s.url).get("/api/settings/system").status, 401)
        c = Client(s.url).login()
        d = _j(c.get("/api/settings/system"))["data"]
        res.ok("версия — три числа", d["version"].count(".") == 2, f"{d['version']!r}")
        res.check("база названа", d["db"], "SQLite (local, data/dental.db)")
        # ⚠️ Прогон идёт ИЗ ИСХОДНИКОВ, а раскладку задаёт лаунчер
        # (`$DENTART_DATA_DIR`): здесь её нет, и строки быть не должно вовсе.
        # Врать «папка рядом с exe» — ровно то, чем кончился хвост P1.
        res.check("без заданной раскладки пути нет", d["folder"]["path"], "")
        res.ok("рядом с путём сказано, что в нём лежит",
               "copiile de rezervă" in d["folder"]["hint"], d["folder"]["hint"])
        res.ok("вход: значок и слово по отдельности",
               d["access"]["icon"] == "lock" and d["access"]["text"],
               f"{d['access']}")
        res.ok("обновление: состояние из перечисления",
               d["update"]["state"] in ("self", "pending", "link", "fresh",
                                        "unknown", "checking"), f"{d['update']}")
        res.ok("у состояния есть слово для человека", bool(d["update"]["text"]),
               f"{d['update']}")
        res.ok("ссылка непуста ТОЛЬКО там, где качать надо руками",
               bool(d["update"]["url"]) == (d["update"]["state"] == "link"),
               f"{d['update']}")
        res.check("канал stable строки не даёт", d["channel"], None)
        res.ok("почта поддержки на месте", "@" in d["feedback"], d["feedback"])
        res.ok("проза о локальности приехала обоими языками",
               "funcționează local" in d["privacy"]
               and "работает локально" in d["privacy"], d["privacy"][:80])
        # ⛔ Бот заморожен (08-08): строки канала быть не должно, иначе она
        # отправляет клинику искать раздел, который заморозка спрятала.
        res.check("без настроенного бота строки канала нет", d["telegram"], "")

        # ⛔ Паритет: JSON и старая страница собраны из ОДНИХ кусков.
        page = c.get("/admin/settings/system").body
        res.ok("без пути строки о папке нет и на старой странице",
               "Folderul cu date" not in page, "строка появилась без раскладки")
        res.ok("слово об обновлении есть и на старой странице",
               d["update"]["text"] in page, "строка обновления разошлась")
        res.ok("проза о локальности есть и на старой странице",
               "funcționează local" in page, "проза разошлась")

        r = c.post_json("/api/settings/system/check", {})
        res.check("проверка обновлений — 200", r.status, 200)
        res.ok("ответ — СВЕЖАЯ модель целиком, а не «проверено»",
               _j(r)["data"]["version"] == d["version"] and "update" in _j(r)["data"],
               f"{_j(r)['data'].keys()}")

    # ⭐ Раскладка задана лаунчером — экран показывает ФАКТ, и тот же факт
    # видит старая страница. Это единственное место, по которому директор
    # сверяет, куда программа пишет, поэтому путь ЦЕЛИКОМ: сокращение вроде
    # «%ProgramData%» с адресной строкой Проводника не сверить.
    with Server(env={"DENTART_DATA_DIR": str(FIXTURES)}) as s:
        c = Client(s.url).login()
        d = _j(c.get("/api/settings/system"))["data"]
        res.check("папка данных — та, что задал лаунчер", d["folder"]["path"],
                  str(FIXTURES))
        res.ok("тот же путь на старой странице",
               html.escape(str(FIXTURES)) in c.get("/admin/settings/system").body,
               "путь разошёлся")

    # ⭐ Канал НЕ stable виден намеренно: на этой машине обновление приходит
    # раньше, чем клиникам, и перепутать её с боевой установкой нельзя.
    with Server(env={"DENTART_CHANNEL": "beta"}) as s:
        c = Client(s.url).login()
        ch = _j(c.get("/api/settings/system"))["data"]["channel"]
        res.ok("beta названа и объяснена",
               ch and "beta" in ch["name"] and "ÎNAINTE" in ch["warn"], f"{ch}")
        res.ok("та же строка есть и на старой странице",
               ch and ch["name"] in c.get("/admin/settings/system").body, "разошлась")

    # клиника с настроенным ботом (grandfather) — строка канала возвращается
    with Server(env=TG_ON) as s:
        c = Client(s.url).login()
        d = _j(c.get("/api/settings/system"))["data"]
        res.ok("у grandfather-клиники строка канала есть", bool(d["telegram"]),
               "строки нет")

    s = _server_with_flags(env=NO_KEY)
    with s:
        boss = Client(s.url)
        boss.post("/admin/setup", pin1="1111", pin2="1111")
        boss.post("/admin/users/save", uid="ana", name="Ana R", role="receptie", pin="3333")
        page = boss.get("/admin/settings/system").body
        res.ok("узел React", 'data-screen="settings_system"' in page, "узла нет")
        res.ok("старой таблицы нет", "Stare sistem</h2>" not in page, "две разметки")
        res.ok("?ui=legacy: старая страница",
               "Confidențialitate" in boss.get("/admin/settings/system?ui=legacy").body, "нет")
        res.ok("вход по PIN виден как PIN",
               _j(boss.get("/api/settings/system"))["data"]["access"]["text"] == "PIN setat",
               "вход назван не так")
        ana = Client(s.url)
        ana.post("/admin/login", password="3333", next="/admin")
        res.check("регистратуре JSON закрыт", ana.get("/api/settings/system").status, 403)
        res.check("и проверка обновлений закрыта",
                  ana.post_json("/api/settings/system/check", {}).status, 403)


def suite_crypt(res: Result) -> None:
    """Шифрование картотеки: состояние, проза и заказ.

    ⭐ Раздел до 21.09 не был покрыт НИ ОДНОЙ проверкой, и это самое дорогое
    место продукта: ошибка здесь не роняет программу, а тихо отнимает у
    клиники доступ к картотеке навсегда. Поэтому проверок больше, чем у
    соседних разделов настроек.
    """
    with Server() as s:
        res.check("без входа — 401", Client(s.url).get("/api/settings/crypt").status, 401)
        c = Client(s.url).login()
        d = _j(c.get("/api/settings/crypt"))["data"]
        res.check("состояние: выключено", d["state"], "off")
        res.check("адрес листа — от сервера", d["sheet"], "/admin/settings/crypt/sheet")
        b = d["blocks"]
        # ⭐ Три абзаца «что даёт / чего стоит / чего НЕ делает» — решение Олега
        # 08-09: раздел не уговаривает, он называет цену. Потеряйся один — и
        # экран станет рекламой шифрования, за которым стоит потеря базы.
        res.ok("сказано, что не обязательно", "Nu este obligatorie" in b["status"], b["status"][:80])
        res.ok("сказано, что оно даёт", "Ce face" in b["what"], b["what"][:80])
        res.ok("сказано, чего стоит: лист и потеря без него",
               "foaia de recuperare" in b["cost"] and "nu poate fi reparată" in b["cost"],
               b["cost"][:120])
        res.ok("сказано, чего НЕ делает", "Ce NU face" in b["limit"], b["limit"][:80])
        res.ok("заметки о копиях в выключенном состоянии нет", b["note"] == "", b["note"][:60])

        # ⛔ Паритет: JSON и старая страница собраны из ОДНИХ кусков. Разойдись
        # они — директор прочёл бы про риск на одной поверхности и не прочёл на
        # другой, а увидеть это можно только открыв обе.
        page = c.get("/admin/settings/crypt").body
        res.ok("каждый кусок прозы есть и на старой странице",
               all(part in page for part in (b["status"], b["what"], b["cost"], b["limit"])),
               "проза разошлась")

        r = c.post_json("/api/settings/crypt/prepare", {})
        res.check("подготовка — 200", r.status, 200)
        res.check("ответ ведёт на печатный лист", _j(r)["data"]["sheet"],
                  "/admin/settings/crypt/sheet")
        sheet = c.get("/admin/settings/crypt/sheet").body
        res.ok("лист показывает код", "Foaie de recuperare" in sheet, sheet[:120])
        code = re.search(r"class=\"code\">([^<]+)<", sheet)
        res.ok("код на листе нашёлся", code is not None, sheet[:200])
        first = code.group(1).strip() if code else ""

        # ⛔ Второе нажатие НЕ создаёт новый ключ (враждебное ревью 08-09):
        # иначе напечатанный лист перестаёт открывать базу, а человек об этом
        # не узнает до смены ПК.
        res.check("второе нажатие — тоже 200",
                  c.post_json("/api/settings/crypt/prepare", {}).status, 200)
        again = re.search(r"class=\"code\">([^<]+)<",
                          c.get("/admin/settings/crypt/sheet").body)
        res.check("код НЕ сменился", again.group(1).strip() if again else "", first)

        # ⭐ Заказ кладёт ГАЛОЧКА на листе, а не подготовка: закрытая без
        # подтверждения страница не должна оставлять на диске приказ шифровать.
        res.ok("до подтверждения заказа на диске нет",
               not (s.dir / "db-key.pending").exists(), "заказ появился раньше галочки")
        c.post("/admin/settings/crypt/confirm", ack="1")
        res.ok("после галочки заказ лежит на диске",
               (s.dir / "db-key.pending").exists(), "заказа нет")
        d = _j(c.get("/api/settings/crypt"))["data"]
        res.check("состояние: заказано", d["state"], "pending")
        res.ok("в заказанном состоянии проза уговаривания исчезла",
               d["blocks"]["what"] == "" and d["blocks"]["cost"] == "",
               "проза осталась")
        res.ok("сказано, что применится при следующем запуске",
               "la următoarea pornire" in d["blocks"]["status"], d["blocks"]["status"][:80])

        # ⛔ Нажатие при УЖЕ включённом шифровании — отказ, а не новый ключ:
        # заказ на переезд не выполнился бы никогда (база под старым ключом),
        # а лист напечатался бы с ключом, который не открывает ничего.
        (s.dir / "db.key").write_text("x", encoding="utf-8")
        r = c.post_json("/api/settings/crypt/prepare", {})
        res.check("при включённом шифровании подготовка отказывает", r.status, 409)
        res.check("и называет причину словом", _j(r)["code"], "crypt_on")
        (s.dir / "db.key").unlink()

        r = c.post_json("/api/settings/crypt/off", {})
        res.check("выключение — 200", r.status, 200)
        res.check("код ok_set", _j(r)["code"], "ok_set")
        res.ok("вне настольного издания текста перезапуска нет",
               _j(r)["data"]["text"] == "" and _j(r)["data"]["restart"] is False,
               f"{_j(r)['data']}")
        # ⛔ Сам переезд делает ЛАУНЧЕР до старта приложения: подмена файла под
        # открытым соединением с -wal/-shm даёт порчу часами позже.
        res.ok("страница только ЗАКАЗЫВАЕТ расшифровку",
               (s.dir / "db-decrypt.request").exists(), "заказа на расшифровку нет")

    # ---- права: деньги и настройки закрыты не только в меню ----
    s = _server_with_flags(env=NO_KEY)
    with s:
        boss = Client(s.url)
        boss.post("/admin/setup", pin1="1111", pin2="1111")
        boss.post("/admin/users/save", uid="ana", name="Ana R", role="receptie", pin="3333")
        page = boss.get("/admin/settings/crypt").body
        res.ok("узел React", 'data-screen="settings_crypt"' in page, "узла нет")
        res.ok("старой кнопки нет", "Pregătește criptarea" not in page, "две разметки")
        res.ok("?ui=legacy: старая страница",
               "Pregătește criptarea" in boss.get("/admin/settings/crypt?ui=legacy").body, "нет")
        # ⛔ Лист остаётся серверным и при включённом флаге: он обязан
        # открываться, когда бандл не загрузился.
        boss.post_json("/api/settings/crypt/prepare", {})
        res.ok("лист восстановления и под флагом серверный",
               "Foaie de recuperare" in boss.get("/admin/settings/crypt/sheet").body,
               "лист уехал в React")
        # ⚠️ СТАРАЯ форма выключения не была покрыта ничем (карта экранов
        # называла её поимённо). Она правится тем же `crypt.turn_off`, что и
        # JSON, и при включённом флаге остаётся рабочим откатом.
        boss.post("/admin/settings/crypt/off")
        res.ok("старая форма выключения заказывает расшифровку",
               (s.dir / "db-decrypt.request").exists(), "заказа нет")
        ana = Client(s.url)
        ana.post("/admin/login", password="3333", next="/admin")
        res.check("регистратуре JSON закрыт", ana.get("/api/settings/crypt").status, 403)
        res.check("и подготовка закрыта",
                  ana.post_json("/api/settings/crypt/prepare", {}).status, 403)
        r = ana.post("/admin/settings/crypt/off")
        res.ok("и старая форма выключения тоже",
               r.status == 303 and r.msg == "no_access", f"{r!r}")


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


def suite_services(res: Result) -> None:
    """Услуги: та же _val_services, тело как у старой таблицы (врачи списком
    и длительность числом приводятся на сервере к её виду)."""
    api = "/api/settings/services"
    with Server() as s:
        c = Client(s.url).login()
        res.check("без входа — 401", Client(s.url).get(api).status, 401)
        d = _j(c.get(api))["data"]
        res.check("услуги фикстуры по порядку", [x["id"] for x in d["services"]],
                  ["consult", "pain", "hygiene", "orphan", "long"])
        by = {x["id"]: x for x in d["services"]}
        res.check("двуязычная цена — её RO", by["consult"]["price"], "gratuit")
        res.check("длительность по умолчанию 60", by["consult"]["duration"], 60)
        res.check("своя длительность", by["long"]["duration"], 120)
        res.ok("срочная услуга с врачами списком",
               by["pain"]["urgent"] is True and by["pain"]["docs"] == ["d1", "d2"], f"{by['pain']}")
        res.ok("без врачей — пустой список", by["consult"]["docs"] == [], f"{by['consult']}")
        res.check("палитра — шесть ключей", set(d["palette"]),
                  {"green", "blue", "amber", "violet", "red", "teal"})
        res.check("длительности как в старом списке", d["durations"], [15, 30, 45, 60, 90, 120])
        res.check("врачи для галочек", [x["id"] for x in d["doctors"]], ["d1", "d2", "d3", "d4"])

        rows = d["services"] + [{"id": "", "ro": "Albire", "ru": "Отбеливание",
                                 "price": "1500 MDL", "duration": 90, "color": "violet",
                                 "urgent": False, "docs": ["d2", "d9"]}]
        r = c.post_json(api, {"services": rows})
        res.check("сохранение — 200", r.status, 200)
        j = _j(r)
        res.check("код ok_set", j["code"], "ok_set")
        new = j["data"]["services"][-1]
        res.ok("новая услуга: id по счётчику, поля как прислали, чужой врач отброшен",
               new["id"] == "s1" and new["price"] == "1500 MDL" and new["duration"] == 90
               and new["color"] == "violet" and new["docs"] == ["d2"] and not new["urgent"],
               f"{new}")
        after = _cfg(s)
        res.check("файл: шесть услуг", len(after["services"]), 6)
        res.check("счётчик seq.service", after["seq"]["service"], 1)
        res.ok("файл: цена словаря сплющена в строку (как у старой формы)",
               after["services"][0]["price"] == "gratuit", f"{after['services'][0]}")
        res.ok("врачи и часы целы", len(after["doctors"]) == 4 and after["hours"]["mon"] == [7, 21],
               "затёрты")
        current = _j(c.get(api))["data"]["services"]
        before = s.clinic.read_bytes()
        c.post_json(api, {"services": current})
        res.ok("повторный POST того же тождествен", s.clinic.read_bytes() == before, "изменился")
        res.ok("старая страница видит новую услугу",
               "Albire" in c.get("/admin/settings/services").body, "не видит")

        dup = current + [{"id": "", "ro": "consultație", "ru": "", "price": "", "duration": 60,
                          "color": "", "urgent": False, "docs": []}]
        r = c.post_json(api, {"services": dup})
        res.ok("дубль подписи RO без учёта регистра — 422 bad_set",
               r.status == 422 and _j(r)["code"] == "bad_set", r.body)
        dup_ru = current + [{"id": "", "ro": "Nou", "ru": "Консультация", "price": "",
                             "duration": 60, "color": "", "urgent": False, "docs": []}]
        res.check("дубль по RU — 422", c.post_json(api, {"services": dup_ru}).status, 422)
        res.check("пустой список — 422", c.post_json(api, {"services": []}).status, 422)
        res.check("не список — 422", c.post_json(api, {"services": "x"}).status, 422)
        res.check("строка не объект — 422", c.post_json(api, {"services": ["x"]}).status, 422)
        res.check("отказы файл не тронули", len(_cfg(s)["services"]), 6)

        r = c.post_json(api, {"services": [x for x in current if x["id"] != "orphan"]})
        res.check("удаление услуги — ok_set", _j(r)["code"], "ok_set")
        res.ok("orphan исчез из файла",
               "orphan" not in [x["id"] for x in _cfg(s)["services"]], "остался")

        r = c.post("/admin/settings/save", part="services",
                   payload=json.dumps({"services": [
                       {"id": "consult", "ro": "Consultație", "ru": "Консультация",
                        "price": "300 MDL", "duration": "30", "docs": ""}]}))
        res.check("старая форма всё ещё сохраняет", r.msg, "ok_set")
        res.check("API видит правку старой формы",
                  [x["id"] for x in _j(c.get(api))["data"]["services"]], ["consult"])


def suite_theme(res: Result) -> None:
    """Вид клиники: палитры считает сервер, сохранение — та же _val_theme,
    логотип — тот же _logo_action, что у формы."""
    api = "/api/settings/theme"
    with Server() as s:
        c = Client(s.url).login()
        anon = Client(s.url)
        res.check("без входа — 401", anon.get(api).status, 401)
        d = _j(c.get(api))["data"]
        res.ok("по умолчанию Fluent и фирменный зелёный",
               d["style"] == "fluent" and d["primary"] == "#0E9F8A" and not d["custom"], f"{d}")
        res.check("четыре стиля", [x["key"] for x in d["styles"]],
                  ["modern", "elegant", "calm", "fluent"])
        res.ok("стиль несёт подпись и переменные",
               d["styles"][0]["label"] == "Modern" and "--bg" in d["styles"][0]["vars"],
               f"{d['styles'][0]}")
        res.check("шесть цветов", len(d["presets"]), 6)
        res.ok("палитры посчитаны сервером для каждого стиля и цвета",
               d["palettes"]["modern"]["#0E9F8A"]["--teal"] == "#0E9F8A"
               and set(d["palettes"]) == {"modern", "elegant", "calm", "fluent"}
               and len(d["palettes"]["calm"]) == 6, f"{list(d['palettes'])}")
        res.ok("логотипа нет", d["logo"] is None and d["logo_topbar"] is False, f"{d['logo']}")
        res.check("потолок логотипа 2 МБ", d["logo_max_mb"], 2)

        # меню и шрифт (B5): умолчания, варианты для предпросмотра, сохранение,
        # «не прислали — не трогали», отказ на незнакомом
        res.ok("меню фирменное и шрифт Inter по умолчанию, варианты приехали",
               d["menu"] == "brand" and d["font"] == "inter"
               and [m["key"] for m in d["menus"]] == ["brand", "neutral"]
               and [x["key"] for x in d["fonts"]] == ["inter", "system"]
               and d["menus"][1]["vars"].get("--side-bg") == "var(--bg)"
               and "Segoe" in d["fonts"][1]["stack"],
               f"{d.get('menu')} {d.get('font')} {[m['key'] for m in d.get('menus', [])]}")
        r = c.post_json(api, {"style": "fluent", "primary": "#0E9F8A", "custom": "",
                              "logo_topbar": False, "menu": "neutral", "font": "system"})
        j = _j(r)
        res.ok("меню и шрифт сохраняются",
               r.status == 200 and j["data"]["menu"] == "neutral" and j["data"]["font"] == "system",
               r.body[:160])
        page = c.get("/admin").body
        res.ok("нейтральное меню и системный шрифт в шапке",
               "--side-bg:var(--bg)" in page and "--font:'Segoe UI Variable Text'" in page,
               "не приехали")
        r = c.post_json(api, {"style": "fluent", "primary": "#0E9F8A", "custom": "",
                              "logo_topbar": False})
        j = _j(r)
        res.ok("без полей меню и шрифта прежний выбор цел",
               j["data"]["menu"] == "neutral" and j["data"]["font"] == "system", r.body[:160])
        r = c.post_json(api, {"style": "fluent", "primary": "#0E9F8A", "menu": "розовое"})
        res.ok("незнакомое меню — 422, поле menu",
               r.status == 422 and _j(r).get("field") == "menu", r.body)
        r = c.post_json(api, {"style": "fluent", "primary": "#0E9F8A", "font": "Comic Sans"})
        res.ok("незнакомый шрифт — 422, поле font",
               r.status == 422 and _j(r).get("field") == "font", r.body)

        r = c.post_json(api, {"style": "calm", "primary": "#7C3AED", "custom": "",
                              "logo_topbar": False})
        res.check("сохранение — 200", r.status, 200)
        j = _j(r)
        res.check("код ok_theme", j["code"], "ok_theme")
        res.ok("ответ несёт свежую тему", j["data"]["style"] == "calm"
               and j["data"]["primary"] == "#7C3AED", f"{j['data']['style']}")
        page = c.get("/admin").body
        res.ok("журнал перекрашен: стиль и цвет",
               'data-style="calm"' in page and "--teal:#7C3AED" in page, "не перекрашен")
        after = _cfg(s)
        res.ok("остальной профиль цел", len(after["doctors"]) == 4
               and len(after["services"]) >= 4 and after["hours"]["mon"] == [7, 21], "затёрт")
        before = s.clinic.read_bytes()
        c.post_json(api, {"style": "calm", "primary": "#7C3AED", "custom": "", "logo_topbar": False})
        res.ok("повторный POST тождествен", s.clinic.read_bytes() == before, "изменился")
        r = c.post_json(api, {"style": "modern", "primary": "custom", "custom": "#123456",
                              "logo_topbar": False})
        res.ok("свой цвет", _j(r)["data"]["primary"] == "#123456" and _j(r)["data"]["custom"] is True,
               r.body[:120])
        r = c.post_json(api, {"style": "modern", "primary": "red"})
        res.ok("мусорный цвет — 422, поле primary",
               r.status == 422 and _j(r).get("field") == "primary", r.body)
        r = c.post_json(api, {"style": "хакер", "primary": "#0E9F8A"})
        res.ok("незнакомый стиль — 422, поле style",
               r.status == 422 and _j(r).get("field") == "style", r.body)
        res.check("после отказов тема прежняя", _j(c.get(api))["data"]["primary"], "#123456")
        r = c.get("/api/settings/theme/palette?c=%23123456&style=modern")
        res.ok("предпросмотр своего цвета считает сервер",
               r.status == 200 and _j(r)["data"]["--teal"] == "#123456", r.body[:120])
        res.check("мусор в предпросмотре — 422", c.get("/api/settings/theme/palette?c=red").status, 422)

        r = c.post_file("/api/settings/theme/logo", "file", "logo.png", PNG)
        res.check("PNG — 200", r.status, 200)
        j = _j(r)
        res.ok("код ok_logo и адрес логотипа",
               j["code"] == "ok_logo" and str(j["data"]["logo"]).startswith("/clinic-logo?v="), r.body[:120])
        res.ok("логотип отдаётся без входа", anon.get("/clinic-logo").raw == PNG, "не тот файл")
        r = c.post_json(api, {"style": "modern", "primary": "#0E9F8A", "custom": "", "logo_topbar": False})
        res.ok("логотип пережил смену цвета", _j(r)["data"]["logo"] is not None, "пропал")
        r = c.post_json(api, {"style": "modern", "primary": "#0E9F8A", "custom": "", "logo_topbar": True})
        res.ok("галочка шапки сохраняется",
               _j(r)["data"]["logo_topbar"] is True and _cfg(s)["theme"]["logo_topbar"] is True, r.body[:120])
        r = c.post_file("/api/settings/theme/logo", "file", "x.png", b"MZ not an image at all")
        res.ok("не картинка — 422 bad_logo", r.status == 422 and _j(r)["code"] == "bad_logo", r.body)
        res.check("после отказа прежний логотип цел", anon.get("/clinic-logo").status, 200)
        r = c.post_json("/api/settings/theme/logo/delete", {})
        res.ok("удаление — no_logo, логотипа нет",
               _j(r)["code"] == "no_logo" and _j(r)["data"]["logo"] is None, r.body[:120])
        res.check("файл логотипа удалён — 404", anon.get("/clinic-logo").status, 404)
        res.ok("старая страница темы — прежняя",
               "class='th-styles'" in c.get("/admin/settings/theme").body, "изменилась")


def suite_security(res: Result) -> None:
    """Учётки и свой PIN: те же правила, что у форм (_apply_user, _drop_user,
    change_pin), с кодами ответа; смена PIN обновляет куку вошедшего."""
    api = "/api/settings/security"
    users_api = "/api/settings/users"
    pin_api = "/api/settings/pin"
    with Server() as s0:                       # вход по ADMIN_KEY: людей нет
        c0 = Client(s0.url).login()
        res.check("без PIN-файла — 404", c0.get(api).status, 404)

    with Server(env=NO_KEY) as s:
        res.check("без входа — 401", Client(s.url).get(api).status, 401)
        boss = Client(s.url)
        boss.post("/admin/setup", pin1="1111", pin2="1111")
        d = _j(boss.get(api))["data"]
        res.check("один директор", [(u["id"], u["role"]) for u in d["users"]],
                  [("clinic", "director")])
        res.check("подписи ролей — с сервера", d["roles"],
                  {"director": "Director", "receptie": "Recepție", "medic": "Medic"})
        res.check("врачи для привязки", [x["id"] for x in d["doctors"]], ["d1", "d2", "d3", "d4"])
        res.check("это я", d["me"], "clinic")
        res.check("границы PIN из констант", d["pin"], {"min": 4, "max": 8})

        r = boss.post_json(users_api, {"uid": "ana", "name": "Ana R", "role": "receptie",
                                       "doctor_id": "", "pin": "3333"})
        res.ok("новая учётка — 200 ok_user", r.status == 200 and _j(r)["code"] == "ok_user", r.body)
        res.check("ответ несёт список с новой учёткой",
                  [u["id"] for u in _j(r)["data"]["users"]], ["clinic", "ana"])
        r = boss.post_json(users_api, {"uid": "d2", "name": "Dr. Liviu", "role": "medic",
                                       "doctor_id": "d2", "pin": "2222"})
        res.ok("врач с привязкой", _j(r)["code"] == "ok_user"
               and next(u for u in _j(r)["data"]["users"] if u["id"] == "d2")["doctor_id"] == "d2",
               r.body[:160])
        r = boss.post_json(users_api, {"uid": "x1", "name": "X", "role": "medic", "pin": "2222"})
        res.ok("чужой пароль повторить нельзя — 409 dup_user",
               r.status == 409 and _j(r)["code"] == "dup_user", r.body)
        r = boss.post_json(users_api, {"uid": "Ана!", "name": "X", "role": "medic", "pin": "4444"})
        res.ok("id из небезопасных символов — 422 bad_user",
               r.status == 422 and _j(r)["code"] == "bad_user", r.body)
        res.check("новому нужен пароль — 422",
                  boss.post_json(users_api, {"uid": "x2", "name": "X", "role": "medic"}).status, 422)
        res.check("9 цифр — 422",
                  boss.post_json(users_api, {"uid": "n9", "name": "N", "role": "receptie",
                                             "pin": "444455556"}).status, 422)
        res.check("8 цифр — ok_user",
                  _j(boss.post_json(users_api, {"uid": "r8", "name": "R", "role": "receptie",
                                                "pin": "44445555"}))["code"], "ok_user")
        res.check("незнакомая роль — 422",
                  boss.post_json(users_api, {"uid": "z", "name": "Z", "role": "boss", "pin": "9876"}).status, 422)
        r = boss.post_json(users_api, {"uid": "clinic", "name": "D", "role": "medic"})
        res.ok("последний директор не снимает с себя роль — 409 last_dir",
               r.status == 409 and _j(r)["code"] == "last_dir", r.body)
        r = boss.post_json("/api/settings/users/clinic/delete", {})
        res.ok("сам себя не удаляет — 409 self_user",
               r.status == 409 and _j(r)["code"] == "self_user", r.body)
        r = boss.post_json("/api/settings/users/r8/delete", {})
        res.ok("удаление — ok_user, r8 исчез", _j(r)["code"] == "ok_user"
               and "r8" not in [u["id"] for u in _j(r)["data"]["users"]], r.body[:160])
        res.ok("старая страница видит новые учётки",
               "Ana R" in boss.get("/admin/settings/security").body, "не видит")

        ana = Client(s.url)
        ana.post("/admin/login", password="3333", next="/admin")
        res.check("регистратуре раздел закрыт — 403", ana.get(api).status, 403)
        res.check("регистратура не заводит учётки — 403",
                  ana.post_json(users_api, {"uid": "q", "name": "Q", "role": "medic", "pin": "1234"}).status,
                  403)
        res.ok("последний вход регистратуры виден директору",
               next(u for u in _j(boss.get(api))["data"]["users"] if u["id"] == "ana")["last_login"] != "",
               "пусто")

        r = ana.post_json(pin_api, {"old_pin": "9999", "new1": "5678", "new2": "5678"})
        res.ok("неверный старый PIN — 422 bad_pin", r.status == 422 and _j(r)["code"] == "bad_pin", r.body)
        res.check("новые не совпали — 422",
                  ana.post_json(pin_api, {"old_pin": "3333", "new1": "5678", "new2": "5679"}).status, 422)
        res.check("короткий — 422",
                  ana.post_json(pin_api, {"old_pin": "3333", "new1": "123", "new2": "123"}).status, 422)
        r = ana.post_json(pin_api, {"old_pin": "3333", "new1": "2222", "new2": "2222"})
        res.ok("чужой PIN — 409 dup_user", r.status == 409 and _j(r)["code"] == "dup_user", r.body)
        key_before = _rec(s)["cookie_key"]
        r = ana.post_json(pin_api, {"old_pin": "3333", "new1": "5678", "new2": "5678"})
        res.ok("смена — 200 ok_pin", r.status == 200 and _j(r)["code"] == "ok_pin", r.body)
        res.ok("ключ подписи повёрнут", _rec(s)["cookie_key"] != key_before, "не повёрнут")
        res.ok("та же вкладка жива: кука обновлена ответом", ana.get("/admin").status == 200,
               "выкинуло на вход")
        old = Client(s.url)
        old.post("/admin/login", password="3333", next="/admin")
        res.ok("старый PIN больше не пускает", old.get("/admin").status == 303, "пустил")
        new = Client(s.url)
        new.post("/admin/login", password="5678", next="/admin")
        res.ok("новый PIN пускает", new.get("/admin").status == 200, "не пустил")


def suite_backup(res: Result) -> None:
    """Копия: порог пароля с сервера, сама выгрузка — старым маршрутом."""
    with Server() as s:
        res.check("без входа — 401", Client(s.url).get("/api/settings/backup").status, 401)
        c = Client(s.url).login()
        d = _j(c.get("/api/settings/backup"))["data"]
        res.check("порог пароля", d["min_pass"], 10)
        res.ok("имя архива", d["filename"].endswith(".zip"), d["filename"])
        r = c.post("/admin/backup/export", parola="scurt")
        res.ok("старый маршрут: короткая парола — назад с bad_bkp_pass",
               r.status == 303 and r.msg == "bad_bkp_pass", f"{r!r}")
        r = c.post("/admin/backup/export", parola="parola-lunga-10")
        res.ok("старый маршрут отдаёт архив",
               r.status == 200 and r.raw[:2] == b"PK" and "zip" in r.header("Content-Type"),
               f"код {r.status}, {r.header('Content-Type')!r}")


def suite_switch(res: Result) -> None:
    """Флаги настроек: узел React в той же рамке, ?ui=legacy, охрана."""
    s = _server_with_flags()
    with s:
        c = Client(s.url).login()
        for path, screen, old in (("/admin/settings", "settings_hub", "class='pl-tile'"),
                                  ("/admin/settings/faq", "settings_faq", "<details class='faq'"),
                                  ("/admin/settings/hours", "settings_hours", "id='hc_mon'"),
                                  ("/admin/settings/services", "settings_services", "id='svc_tb'"),
                                  ("/admin/settings/theme", "settings_theme", "class='th-styles'"),
                                  ("/admin/settings/backup", "settings_backup", "name='parola'")):
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
        _rmtree_settled(tmp)

    s = _server_with_flags(env={"ADMIN_KEY": ""})
    with s:
        boss = Client(s.url)
        boss.post("/admin/setup", pin1="1111", pin2="1111")
        boss.post("/admin/users/save", uid="ana", name="Ana R", role="receptie", pin="3333")
        page = boss.get("/admin/settings/security").body
        res.ok("учётки: узел React", 'data-screen="settings_security"' in page, "узла нет")
        res.ok("учётки: старой формы нет", "name='old_pin'" not in page, "две разметки")
        res.ok("учётки ?ui=legacy: старая форма",
               "name='old_pin'" in boss.get("/admin/settings/security?ui=legacy").body, "нет")
        r = boss.post("/admin/pin/change", old_pin="1111", new1="1234", new2="1234")
        res.check("старая форма смены PIN при флаге работает", r.msg, "ok_pin")
        ana = Client(s.url)
        ana.post("/admin/login", password="3333", next="/admin")
        for path in ("/admin/settings", "/admin/settings/faq", "/admin/settings/hours",
                     "/admin/settings/security"):
            r = ana.get(path)
            res.ok(f"регистратуре React-страница {path} закрыта, как и старая",
                   r.status == 303 and r.msg == "no_access", f"{r!r}")
        res.check("регистратуре закрыт и JSON хаба", ana.get("/api/settings/hub").status, 403)
