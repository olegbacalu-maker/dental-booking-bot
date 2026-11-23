"""Подключение врача к его Google Calendar (`modules/doctors/gcal_doctor.py`, маршруты `/api/gdoc…`).

Живой сервер программы и стенд Google в одном прогоне, как у связи клиники (`test_gcal_link`): сервер
ходит на стенд (`DENTART_GOOGLE_STAND`, только вне exe), клиент Google — JSON по `DENTART_GOOGLE_CLIENT`,
право — подписанный файл лицензии тестовым ключом (`test_gwrite.put_license`), календари врача — крючок
записи стенда (`test_gwrite.Calendars`). Браузер врача изображает `Google.consent`: адрес согласия →
строка возврата, её открывает свежий клиент без куки, как браузер Windows.

Чего HTTP с этого ПК не достать — адрес из сети, смена права между входом и возвратом, крючки сверки —
гоняет рабочий в отдельном интерпретаторе (как `test_gdoc`): в общем процессе `app.db` уже открыт.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import urllib.parse

import test_gapi as tg
import test_gwrite as tw
from harness import BOT, FIXTURES, PYTHON, Client, Result, Server, _rmtree_settled

SRC = BOT / "app" / "modules" / "doctors" / "gcal_doctor.py"
KEYS = {"DENTART_LICENSE_KEYS": str(FIXTURES / "license" / "test-key.json")}
BACK = "/google/back/medic"
FILE = "google-medici.json"
D2, D2_NAME = "d2", "Dr. Activ Doi"
CAL_NAME = "DentPilot · Clinica Test · Dr. Activ Doi"
# Так стенд называет выданные токены и коды: ни один не должен лечь открытым текстом на диск.
SECRETS = re.compile(r"ya29-\d+|1//rt-\d+|4/code-\d+")
BOTH = {"gcal": 30, "gcal_doctor": 30}
CARD_KEYS = {"title", "lead", "hint", "details", "connect", "connect_here", "reconnect", "check", "disconnect",
             "disconnect_ask", "waiting_title", "waiting_detail", "reopen", "cancel", "connected", "calendar_label",
             "last", "all_in", "last_ok", "pending", "level_lead", "level_link", "premium_lead"}
LIST_KEYS = {"title", "lead", "count", "label", "phone", "change", "only_dir", "remote", "premium", "premium_more",
             "default", "rewrite", "dlg_title", "dlg_ack", "dlg_ok", "dlg_cancel", "chip"}
PREMIUM = {"href": "/admin/license", "label": "Setări › Licența"}


def _j(r) -> dict:
    return json.loads(r.body)


def client_file(d: pathlib.Path) -> pathlib.Path:
    p = d / "google-client.json"
    p.write_text(json.dumps({"installed": {"client_id": tg.CLIENT.id}}), encoding="utf-8")
    return p


def env(g: tg.Google, client: pathlib.Path | None, **more) -> dict:
    out = {**KEYS, "DENTART_GOOGLE_STAND": g.base, **more}
    if client is not None:
        out["DENTART_GOOGLE_CLIENT"] = str(client)
    return out


def view(c: Client, dk: str = D2) -> dict | None:
    """Блок врача; без `data` в конверте блока нет."""
    return _j(c.get(f"/api/gdoc/{dk}")).get("data")


def entry(d: pathlib.Path, dk: str = D2) -> dict | None:
    p = d / FILE
    return json.loads(p.read_text(encoding="utf-8"))["doctors"].get(dk) if p.exists() else None


def gq(url: str) -> dict:
    return {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlsplit(url).query).items()}


def connect(res: Result, s: Server, c: Client, g: tg.Google, tag: str, dk: str = D2, *,
            keep: tuple | None = None):
    """Регистратура нажала «Conectează», врач согласился в браузере: (адрес, ответ страницы возврата)."""
    r = c.post_json(f"/api/gdoc/{dk}/connect", {})
    res.check(f"{tag}: подключение отдаёт адрес Google", (r.status, r.msg), (200, "gd_url"))
    url = _j(r)["data"].get("url", "") if r.status == 200 else ""
    return url, Client(s.url).get(BACK + "?" + g.consent(url, keep)) if url else None


def revokes(g: tg.Google) -> list:
    return [r for r in g.requests if r.get("path") == "/revoke"]


def activity(d: pathlib.Path) -> list:
    import sqlite3
    con = sqlite3.connect(d / "dental.db")
    try:
        return [f"{a}: {t}" for a, t in con.execute(
            "SELECT actor, text FROM activity WHERE kind = 'gdoc' ORDER BY id")]
    finally:
        con.close()


# ---------- блока нет ----------


def suite_hidden(res: Result) -> None:
    """Блока нет без клиента Google в сборке, на сервере без ключей лицензии и в демо."""
    if not res.ok("исходник подключения врача нашёлся", SRC.is_file(), str(SRC)):
        return
    g = tg.Google()
    tw.Calendars(g)
    work = pathlib.Path(tempfile.mkdtemp(prefix="dp_gdocl_"))
    try:
        client = client_file(work)
        d1 = work / "a"
        d1.mkdir()
        tw.put_license(d1, 1, BOTH)
        with Server(dir_=d1, env=env(g, None)) as s:
            c = Client(s.url).login()
            res.check("без клиента Google: списка, блока и ключа карточки нет",
                      [_j(c.get("/api/gdoc")).get("data"), view(c), _j(c.get(f"/api/doctors/{D2}"))["data"]["google"]],
                      [None, None, None])
            r = c.post_json(f"/api/gdoc/{D2}/connect", {})
            res.check("без клиента Google: подключение — «недоступно»", (r.status, r.msg), (409, "gd_none"))
        with Server(env={"DENTART_GOOGLE_CLIENT": str(client), "DENTART_GOOGLE_STAND": g.base}) as s:
            c = Client(s.url).login()
            res.check("лицензия не применяется (сервер, песочница): блока нет", view(c), None)
        d3 = work / "c"
        d3.mkdir()
        tw.put_license(d3, 1, BOTH)
        with Server(dir_=d3, env=env(g, client, DENTART_DEMO="1")) as s:
            c = Client(s.url).login()
            res.check("демо: карточка без блока", _j(c.get(f"/api/doctors/{D2}"))["data"]["google"], None)
            res.check("демо: маршрутов календаря врача нет",
                      [(x.status, x.msg) for x in (c.get("/api/gdoc"), c.post_json(f"/api/gdoc/{D2}/connect", {}))],
                      [(403, "demo_off"), (403, "demo_off")])
            res.check("демо: адреса возврата врача нет", Client(s.url).get(BACK + "?state=x").status, 303)
        res.ok("Google не спрашивали ни разу", not g.requests, repr(g.requests[:2]))
    finally:
        g.close()
        _rmtree_settled(work)


def suite_premium(res: Result) -> None:
    """Plus без Premium: блок виден строкой Premium и путём к лицензии, подключения нет."""
    g = tg.Google()
    tw.Calendars(g)
    work = pathlib.Path(tempfile.mkdtemp(prefix="dp_gdocl_"))
    try:
        client = client_file(work)
        d = work / "data"
        d.mkdir()
        tw.put_license(d, 1, {"gcal": 30})
        with Server(dir_=d, env=env(g, client)) as s:
            c = Client(s.url).login()
            v = view(c) or {}
            res.check("Plus: состояние, строка «face parte din DentPilot Premium» и серый замок",
                      [v.get("state"), (v.get("why") or {}).get("text"), (v.get("why") or {}).get("tone"),
                       bool((v.get("why") or {}).get("detail"))],
                      ["premium", "Calendarul medicului în Google face parte din DentPilot Premium", "plus", True])
            res.check("Plus: путь к Premium — фраза и ссылка на страницу лицензии",
                      ((v.get("words") or {}).get("premium_lead"), v.get("premium")),
                      ("O porniți plătind varianta Premium în", {"href": "/admin/license", "label": "Setări › Licența"}))
            res.check("Plus: кнопок нет", v.get("can"), {"connect": False, "check": False, "disconnect": False})
            r = c.post_json(f"/api/gdoc/{D2}/connect", {})
            res.check("Plus: подключение — отказ Premium", (r.status, r.msg), (409, "gd_premium"))
            r = c.post_json(f"/api/gdoc/{D2}/check", {})
            res.check("Plus: «Sincronizează acum» — отказ Premium", (r.status, r.msg), (409, "gd_premium"))
            lst = (_j(c.get("/api/gdoc")).get("data") or {})
            res.check("Plus: плашки списка — Premium у каждого врача, у блока списка — путь к лицензии",
                      [sorted({x["state"] for x in (lst.get("doctors") or {}).values()}), lst.get("premium")],
                      [["premium"], PREMIUM])
            res.check("карточка врача несёт блок одним кадром", _j(c.get(f"/api/doctors/{D2}"))["data"]["google"], v)
        res.ok("Google не спрашивали ни разу", not g.requests, repr(g.requests[:2]))
    finally:
        g.close()
        _rmtree_settled(work)


# ---------- подключение, повтор, уход, подхват календаря ----------


def suite_link(res: Result) -> None:
    """Вход врача, его календарь, повтор адреса, отказы браузера, уход без отзыва, подхват календаря
    после потери файла связи, предупреждение «Deconectează» связи клиники."""
    g = tg.Google()
    cals = tw.Calendars(g)
    work = pathlib.Path(tempfile.mkdtemp(prefix="dp_gdocl_"))
    try:
        client = client_file(work)
        d = work / "data"
        d.mkdir()
        tw.put_license(d, 1, BOTH)
        with Server(dir_=d, env=env(g, client)) as s:
            c = Client(s.url).login()
            card = _j(c.get(f"/api/doctors/{D2}"))["data"]
            saved = c.post_json(f"/api/doctors/{D2}", {
                "name": card["name"], "spec": card["spec"], "room": card["room"], "phone": card["phone"],
                "email": tw.OWNER, "auto_color": True, "status": "activ"})
            res.check("почта врача в фише", saved.msg, "ok_med")
            v = view(c) or {}
            res.check("до входа: off, только «Conectează», уровень по умолчанию",
                      [v.get("state"), v.get("can"), v.get("waiting"), (v.get("level") or {}).get("code"),
                       v.get("calendar"), v.get("why")],
                      ["off", {"connect": True, "check": False, "disconnect": False}, False, "time", None, None])
            w = v.get("words") or {}
            res.check("слова блока — ровно ключи экрана", sorted(set(w) ^ CARD_KEYS), [])
            res.ok("слова блока непустые (кроме «в пути»), срок — «în cel mult 5 minute», уведомление и политика",
                   all(w[k] for k in CARD_KEYS - {"pending"}) and w.get("pending") == ""
                   and "în cel mult 5 minute" in w.get("lead", "") and bool(v.get("notice"))
                   and (v.get("privacy") or {}).get("href", "").endswith("#google"), repr(w)[:300])
            res.check("с этого ПК подсказки «только с ПК программы» нет; уровень — длинным словом",
                      [v.get("remote"), v.get("level")],
                      [None, {"code": "time", "label": "doar ora, fără numele pacientului"}])

            r = c.post_json(f"/api/gdoc/{D2}/connect", {})
            url = _j(r)["data"].get("url", "")
            q = gq(url)
            res.check("согласие: одно право календаря врача, экран согласия каждый раз, почта врача подсказкой",
                      [q.get("scope"), q.get("prompt"), q.get("login_hint"), q.get("code_challenge_method")],
                      ["https://www.googleapis.com/auth/calendar.app.created", "consent", tw.OWNER, "S256"])
            res.check("согласие: возврат на 127.0.0.1 этого сервера, путь врача",
                      q.get("redirect_uri"), f"http://127.0.0.1:{s.url.rsplit(':', 1)[1]}{BACK}")
            res.check("ждём браузер: состояние и кнопки ожидания",
                      [(_j(r)["data"]["view"] or {}).get(k) for k in ("state", "waiting")], ["waiting", True])
            reply = g.consent(url)
            back = Client(s.url).get(BACK + "?" + reply)
            res.check("возврат: страница «conectat» и совет выйти из Google",
                      [back.status, "Calendarul medicului este conectat" in back.body,
                       "să iasă din contul său Google" in back.body], [200, True, True])
            res.check("страница возврата не кэшируется и не отдаёт адрес дальше",
                      [back.header("cache-control"), back.header("referrer-policy")], ["no-store", "no-referrer"])
            v = view(c) or {}
            res.check("после входа: on, аккаунт врача, календарь клиники и врача, кнопки связи",
                      [v.get("state"), v.get("account"), (v.get("calendar") or {}).get("name"), v.get("can"),
                       v.get("waiting")],
                      ["on", tw.OWNER, CAL_NAME, {"connect": False, "check": True, "disconnect": True}, False])
            res.check("вопрос «Deconectează» — готовой строкой с именем календаря; без сверки «в пути» пусто",
                      [f"„{CAL_NAME}”" in (v.get("words") or {}).get("disconnect_ask", ""),
                       (v.get("words") or {}).get("pending"), v.get("pending")], [True, "", 0])
            ids = list(cals.cals)
            cal = cals.cals[ids[0]] if ids else {}
            e = entry(d) or {}
            res.check("у Google один календарь: имя, пояс, метка связи последней строкой описания",
                      [len(ids), cal.get("summary"), cal.get("timeZone"),
                       cal.get("description", "").endswith("Actualizat de DentPilot · " + e.get("mark", "?"))],
                      [1, CAL_NAME, "Europe/Chisinau", True])
            res.check("связь в файле: токен под DPAPI, календарь, эпоха 1, кто подключил",
                      [e.get("token", "").startswith("dpapi:"), (e.get("calendar") or {}).get("id") == (ids or [""])[0],
                       e.get("epoch"), e.get("seq"), e.get("connected_by"), e.get("rebuild", False)],
                      [True, True, 1, 0, "Director", False])
            again = Client(s.url).get(BACK + "?" + reply)
            res.check("повтор адреса возврата — «deja conectat», второго календаря нет",
                      [again.status, "deja conectat" in again.body, len(cals.cals)], [200, True, 1])
            r = c.post_json(f"/api/gdoc/{D2}/connect", {})
            res.check("живую связь «Conectează» не перезаписывает", (r.status, r.msg), (409, "gd_on"))
            r = c.post_json(f"/api/gdoc/{D2}/check", {})
            res.check("«Sincronizează acum» без цикла сверки — «продолжится в фоне»",
                      [r.status, r.msg, (_j(r)["data"]["view"] or {}).get("state")], [200, "gd_check_late", "on"])
            lst = (_j(c.get("/api/gdoc")).get("data") or {})
            res.check("плашки списка: врач подключён, у прочих — off",
                      [(lst["doctors"].get(D2) or {}).get("state"), (lst["doctors"].get("d3") or {}).get("state"),
                       (lst["doctors"].get(D2) or {}).get("account")], ["on", "off", tw.OWNER])
            lw = lst.get("words") or {}
            res.check("слова списка — ровно ключи экрана; счёт готовой строкой (архивный врач не в счёт)",
                      [sorted(set(lw) ^ LIST_KEYS), lw.get("count"), lst.get("premium")],
                      [[], "Conectați: 1 din 3 medici", None])
            res.check("слова плашек по состояниям",
                      [(lw.get("chip") or {}).get(k) for k in ("on", "off", "reconnect", "paused", "premium")],
                      ["Google conectat", "Google neconectat", "Google: de refăcut", "Google oprit", None])

            # предупреждение «Deconectează» связи клиники: тот же аккаунт держит календарь врача
            gl = {"v": 1, "device": "", "token": "dpapi:x", "account": tw.OWNER, "calendars": [], "calendar": None}
            (d / "google.json").write_text(json.dumps(gl), encoding="utf-8")
            ask = ((_j(c.get("/api/gcal"))["data"].get("google") or {}).get("words") or {}).get("disconnect_ask", "")
            res.ok("«Deconectează» связи клиники называет врача на том же аккаунте Google",
                   D2_NAME in ask and "calendarul medicului" in ask, ask)
            (d / "google.json").write_text(json.dumps({**gl, "account": "alt@gmail.com"}), encoding="utf-8")
            ask = ((_j(c.get("/api/gcal"))["data"].get("google") or {}).get("words") or {}).get("disconnect_ask", "")
            res.ok("другой аккаунт — врача не называет", D2_NAME not in ask, ask)
            (d / "google.json").unlink()

            g.requests.clear()
            r = c.post_json(f"/api/gdoc/{D2}/disconnect", {})
            res.check("«Deconectează»: календарь удалён у Google, связь закрыта",
                      [r.status, r.msg, (_j(r)["data"]["view"] or {}).get("state"), len(cals.cals), entry(d)],
                      [200, "gd_off", "off", 0, None])
            res.check("«Deconectează» без отзыва у Google", revokes(g), [])
            r = c.post_json(f"/api/gdoc/{D2}/disconnect", {})
            res.check("второй раз — «не подключён»", (r.status, r.msg), (409, "gd_gone"))

            # снова: прежнего календаря нет — новый
            _url, back = connect(res, s, c, g, "второй вход")
            first = set(cals.cals)
            res.check("второй вход: новый календарь, связь on",
                      [back.status if back else 0, len(first), (view(c) or {}).get("state")], [200, 1, "on"])

        # новый ПК с той же картотекой: файла связи нет, id календаря — в картотеке
        (d / FILE).unlink()
        with Server(dir_=d, env=env(g, client)) as s:
            c = Client(s.url).login()
            res.check("файла связи нет — off", (view(c) or {}).get("state"), "off")
            _url, back = connect(res, s, c, g, "подхват")
            e = entry(d) or {}
            cal = cals.cals.get((e.get("calendar") or {}).get("id", ""), {})
            res.check("подхват: тот же календарь, новая метка в описании, первая сверка пересоберёт",
                      [back.status if back else 0, set(cals.cals) == first, e.get("rebuild"),
                       cal.get("description", "").endswith(e.get("mark", "?")), cal.get("summary")],
                      [200, True, True, True, CAL_NAME])

            # браузер отказал, права нет, чужой state, отмена
            r = c.post_json(f"/api/gdoc/{D2}/disconnect", {})
            res.check("уход перед отказами", r.msg, "gd_off")
            r = c.post_json(f"/api/gdoc/{D2}/connect", {})
            st = gq(_j(r)["data"]["url"])["state"]
            back = Client(s.url).get(BACK + "?" + urllib.parse.urlencode({"error": "access_denied", "state": st}))
            res.check("«Cancel» в Google: страница словами, связи нет, ожидание погасло",
                      [back.status, "Conectarea a fost anulată în Google" in back.body, (view(c) or {}).get("state"),
                       (view(c) or {}).get("waiting")], [200, True, "off", False])
            before = len(cals.cals)
            _url, back = connect(res, s, c, g, "без права", keep=())
            res.check("право календаря снято галочкой: отказ словами, календаря нет, отзыва нет",
                      [back.status if back else 0, "Google nu a dat dreptul" in (back.body if back else ""),
                       len(cals.cals) == before, entry(d), revokes(g)], [400, True, True, None, []])
            back = Client(s.url).get(BACK + "?state=zzz&code=4/code-1")
            res.check("чужой state — «linkul nu mai este valabil»", back.status, 400)
            r = c.post_json(f"/api/gdoc/{D2}/connect", {})
            url = _j(r)["data"]["url"]
            r = c.post_json(f"/api/gdoc/{D2}/cancel", {})
            res.check("«Renunță»: ожидание погасло", [r.msg, (_j(r)["data"]["view"] or {}).get("waiting")],
                      ["gd_cancel", False])
            back = Client(s.url).get(BACK + "?" + g.consent(url))
            res.check("после «Renunță» вернувшийся браузер связи не делает", [back.status, entry(d)], [400, None])

            # архив и чужие ключи
            v = view(c, "d1") or {}
            res.check("архивный врач: «Conectează» нет", (v.get("state"), v.get("can", {}).get("connect")), ("off", False))
            r = c.post_json("/api/gdoc/d1/connect", {})
            res.check("архивный врач: подключение — отказ", (r.status, r.msg), (409, "gd_archived"))
            res.check("врача нет — 404", [c.get("/api/gdoc/d99").status,
                                         c.post_json("/api/gdoc/d99/connect", {}).status], [404, 404])

            _url, back = connect(res, s, c, g, "перед режимом чтения")

        # режим чтения: из записи ворота пропускают только «Deconectează»
        tw.put_license(d, 2, BOTH, readonly=True)
        with Server(dir_=d, env=env(g, client)) as s:
            c = Client(s.url).login()
            v = view(c) or {}
            res.check("режим чтения: связь видна, серый замок, кнопка одна — «Deconectează»",
                      [v.get("state"), (v.get("why") or {}).get("code"), (v.get("why") or {}).get("tone"), v.get("can")],
                      ["readonly", "gd_readonly", "plus", {"connect": False, "check": False, "disconnect": True}])
            lst = (_j(c.get("/api/gdoc")).get("data") or {})
            res.check("режим чтения: у списка нет строки Premium, уровень не меняется — почему, одним словом",
                      [lst.get("premium"), (lst.get("level") or {}).get("can_set"), (lst.get("level") or {}).get("lock")],
                      [None, False, "Se schimbă după plata abonamentului."])
            r = c.post_json(f"/api/gdoc/{D2}/check", {})
            res.check("режим чтения: «Sincronizează acum» закрыт воротами", (r.status, r.msg),
                      (423, "license_readonly"))
            r = c.post_json(f"/api/gdoc/{D2}/disconnect", {})
            res.check("режим чтения: «Deconectează» проходит ворота и удаляет календарь",
                      [r.status, r.msg, entry(d), len(cals.cals)], [200, "gd_off", None, 0])

        texts = activity(d)
        res.ok("летопись: подключение и уход — словами, кто сделал",
               f"Director: Calendarele medicilor: „{CAL_NAME}” — conectat" in texts
               and f"Director: Calendarele medicilor: „{CAL_NAME}” — deconectat" in texts, repr(texts))
        disk = "".join(p.read_bytes().decode("latin-1") for p in d.glob("dental.db*"))
        disk += (d / FILE).read_text(encoding="utf-8") if (d / FILE).exists() else ""
        res.check("токены не легли открытым текстом ни в файл связи, ни в картотеку", SECRETS.findall(disk), [])
        sent = json.dumps(g.requests, ensure_ascii=False, default=str)
        device = json.loads((d / "device.json").read_text(encoding="utf-8")).get("id", "?")
        agents = {r.get("agent") for r in g.requests if r.get("agent")}
        res.check("Google получает подпись версии программы и не получает id машины (Anexa 2)",
                  [bool(agents) and all(a.startswith("DentPilot/") for a in agents), device in sent], [True, False])
    finally:
        g.close()
        _rmtree_settled(work)


# ---------- уровень подробности ----------


def suite_level(res: Result) -> None:
    """Подробность события одна на клинику: имя пациента — только после «am înțeles»."""
    g = tg.Google()
    tw.Calendars(g)
    work = pathlib.Path(tempfile.mkdtemp(prefix="dp_gdocl_"))
    try:
        client = client_file(work)
        d = work / "data"
        d.mkdir()
        tw.put_license(d, 1, BOTH)
        with Server(dir_=d, env=env(g, client)) as s:
            c = Client(s.url).login()
            lv = ((_j(c.get("/api/gdoc")).get("data") or {})).get("level") or {}
            res.check("выбор: три варианта по порядку, умолчание «doar ora», окно — у вариантов с пациентом",
                      [lv.get("code"), [x["code"] for x in lv.get("choices", [])],
                       [x["label"] for x in lv.get("choices", [])], [bool(x["warn"]) for x in lv.get("choices", [])],
                       lv.get("can_set"), lv.get("lock")],
                      ["time", ["time", "initials", "name"], ["Doar ora", "Inițiale", "Nume și serviciu"],
                       [False, True, True], True, ""])
            res.check("образец события — тем же телом, что пишет сверка",
                      [x.get("sample") for x in lv.get("choices", [])],
                      ["Programare · Cabinet 1", "M.L. · Fișa 124 · Cabinet 1",
                       "Maria Lungu · Tratament carie · Cabinet 1"])
            r = c.post_json("/api/gdoc/level", {"level": "initials"})
            res.check("инициалы без «am înțeles» — тоже отказ полем", (r.status, r.msg, _j(r).get("field")),
                      (422, "gd_level_ack", "ack"))
            r = c.post_json("/api/gdoc/level", {"level": "name"})
            res.check("имя пациента без «am înțeles» — отказ полем", (r.status, r.msg, _j(r).get("field")),
                      (422, "gd_level_ack", "ack"))
            r = c.post_json("/api/gdoc/level", {"level": "name", "ack": True})
            res.check("с «am înțeles» — сохранено", [r.status, r.msg, ((_j(r)["data"] or {}).get("level") or {}).get("code")],
                      [200, "gd_level_ok", "name"])
            res.check("блок врача называет уровень длинным словом", (view(c) or {}).get("level"),
                      {"code": "name", "label": "numele pacientului și serviciul"})
            r = c.post_json("/api/gdoc/level", {"level": "name", "ack": True})
            res.check("тот же уровень — «уже так»", r.msg, "gd_level_same")
            r = c.post_json("/api/gdoc/level", {"level": "all"})
            res.check("незнакомый уровень — отказ", (r.status, r.msg), (422, "gd_level_bad"))
            r = c.post_json("/api/gdoc/level", {"level": "time"})
            res.check("назад к «doar ora» — без галочки; ответ называет срок переписи",
                      (r.status, r.msg, "în cel mult 5 minute" in _j(r).get("text", "")), (200, "gd_level_ok", True))
        res.ok("летопись: уровень словом", "Director: Calendarele medicilor: nivelul „nume și serviciu”"
               in activity(d), repr(activity(d)))
    finally:
        g.close()
        _rmtree_settled(work)


# ---------- права ролей ----------


def _login(url: str, pin: str) -> Client:
    c = Client(url)
    c.post("/admin/login", password=pin, next="/admin")
    return c


def suite_rights(res: Result) -> None:
    """Подключает директор или регистратура; врачу — 403; уровень — только директор; право
    нажавшего читается из файла учёток на возврате."""
    g = tg.Google()
    cals = tw.Calendars(g)
    work = pathlib.Path(tempfile.mkdtemp(prefix="dp_gdocl_"))
    try:
        client = client_file(work)
        d = work / "data"
        d.mkdir()
        tw.put_license(d, 1, BOTH)
        with Server(dir_=d, env=env(g, client, ADMIN_KEY="")) as s:
            boss = Client(s.url)
            boss.post("/admin/setup", pin1="1111", pin2="1111")
            for body in ({"uid": "d2", "name": D2_NAME, "role": "medic", "doctor_id": "d2", "pin": "2222"},
                         {"uid": "ana", "name": "Ana R", "role": "receptie", "pin": "4444"}):
                res.check(f"учётка {body['role']} заведена", boss.post_json("/api/settings/users", body).msg, "ok_user")
            med, ana = _login(s.url, "2222"), _login(s.url, "4444")
            res.check("врачу: список, блок и подключение закрыты",
                      [med.get("/api/gdoc").status, med.get(f"/api/gdoc/{D2}").status,
                       med.post_json(f"/api/gdoc/{D2}/connect", {}).status], [403, 403, 403])
            lv = ((_j(ana.get("/api/gdoc")).get("data") or {})).get("level") or {}
            res.check("регистратура видит выбор уровня, но менять не может — «Schimbă doar directorul.»",
                      [lv.get("code"), lv.get("can_set"), lv.get("lock"),
                       ana.post_json("/api/gdoc/level", {"level": "time"}).status],
                      ["time", False, "Schimbă doar directorul.", 403])
            _url, back = connect(res, s, ana, g, "регистратура")
            res.check("регистратура подключает врача; в связи — её имя",
                      [back.status if back else 0, (entry(d) or {}).get("connected_by")], [200, "Ana R"])
            r = ana.post_json("/api/gdoc/d3/connect", {})
            url = _j(r)["data"].get("url", "")
            res.check("понижение роли между входом и возвратом",
                      boss.post_json("/api/settings/users", {"uid": "ana", "name": "Ana R", "role": "medic",
                                                            "doctor_id": "d3", "pin": ""}).msg, "ok_user")
            n = len(cals.cals)
            back = Client(s.url).get(BACK + "?" + g.consent(url))
            res.check("право снято — возврат отказывает, календаря нет",
                      [back.status, "nu are dreptul" in back.body, len(cals.cals), entry(d, "d3")], [403, True, n, None])
    finally:
        g.close()
        _rmtree_settled(work)


# ---------- рабочий: сеть, гейт между входом и возвратом, крючки сверки ----------


def _worker(tmpdir: str) -> None:
    import asyncio

    base = pathlib.Path(tmpdir)
    (base / "clinic.json").write_text((FIXTURES / "clinic_test.json").read_text(encoding="utf-8"), encoding="utf-8")
    os.environ.update({"CLINIC_CONFIG": str(base / "clinic.json"),
                       "DATABASE_URL": f"sqlite:///{base / 'dental.db'}", "ADMIN_KEY": "",
                       "DENTART_LICENSE_KEYS": str(FIXTURES / "license" / "test-key.json")})
    os.environ.pop("DENTART_DEMO", None)
    g = tg.Google()
    cals = tw.Calendars(g)
    client_file(base)
    os.environ["DENTART_GOOGLE_CLIENT"] = str(base / "google-client.json")
    os.environ["DENTART_GOOGLE_STAND"] = g.base

    from starlette.requests import Request

    from app import db
    from app import engine as eng
    from app.core import auth, gdoc
    from app.core import license as lic
    from app.modules.doctors import gcal_doctor as gd

    checks: list = []
    seq = {"n": 5}

    def chk(label, got, want):
        checks.append([label, got, want])

    def req(query: str = "", ip: str = "127.0.0.1") -> Request:
        return Request({"type": "http", "method": "GET", "scheme": "http", "path": "/", "raw_path": b"/",
                        "root_path": "", "query_string": query.encode(), "headers": [],
                        "client": (ip, 40000), "server": ("127.0.0.1", 8088)})

    async def license(features):
        seq["n"] += 1
        tw.put_license(base, seq["n"], features)
        await lic.refresh()

    async def link(dk="d2"):
        _code, url = await gd.start(req(), dk)
        return await gd.finish(req(g.consent(url)))

    async def main() -> None:
        await db.init([])
        await license(BOTH)
        # вошедший — как его ставит посредник сервера: подключение помнит, кто нажал
        auth._REQ_USER.set({"id": "clinic", "role": "director", "name": "Director", "doctor_id": ""})
        try:
            phone = req(ip="192.168.1.23")
            v = await gd.view(phone, "d2")
            lv = await gd.level_view(phone)
            chk("из сети: строка вместо кнопок «Conectează» и «Deconectează», уровень не меняется — почему",
                [v["remote"], v["can"]["connect"], v["can"]["disconnect"], lv["can_set"], lv["lock"]],
                [gd.REMOTE, False, False, False, "Se schimbă doar de pe calculatorul pe care rulează programul."])
            chk("возврат из сети — отказ до всего", await gd.finish(req("state=x&code=y", ip="192.168.1.23")),
                ("gc_g_back_local", 403))

            code, url = await gd.start(req(), "d2")
            chk("вход начат", code, "gd_url")
            await license({"gcal": 30})
            g.requests.clear()
            chk("право кончилось между входом и возвратом — отказ без обмена кода и без календаря",
                [await gd.finish(req(g.consent(url))), [r["path"] for r in g.requests], len(cals.cals),
                 gdoc.linked()], [("gd_premium", 409), [], 0, {}])
            await license(BOTH)

            woke, runs = [], {"delay": 0.0, "raise": False}
            stats = {"error": "", "error_at": "", "pending": 0, "last_ok": ""}

            async def run(dk):
                await asyncio.sleep(runs["delay"])
                if runs["raise"]:
                    raise RuntimeError("sync")
                return "ok"

            gdoc.attach_sync(wake=woke.append, run=run, stats=lambda dk: dict(stats))
            chk("подключение будит сверку врача", [await link(), list(woke)], [("gd_back_ok", 200), ["d2"]])
            chk("«Sincronizează acum»: проход дошёл — «actualizat»", await gd.check("d2"), "gd_checked")
            stats.update(error="rate_limited", error_at="2027-03-01T09:00:00Z", pending=7)
            v = await gd.view(req(), "d2")
            chk("ошибка прохода — общий заголовок, причина словом её кода, время, сколько не доехало",
                [await gd.check("d2"), v["state"], (v["why"] or {}).get("code"), (v["why"] or {}).get("text"),
                 (v["why"] or {}).get("detail", "").startswith("Google a cerut o pauză"),
                 (v["why"] or {}).get("when"), v["pending"], v["words"]["pending"]],
                ["gc_g_rate", "on", "gc_g_rate", "Ultima actualizare nu a reușit", True, "01.03.2027 11:00", 7,
                 "încă 7 programări în drum."])
            got = []
            for n in (1, 19, 20, 37, 101, 120):
                stats.update(error="", pending=n)
                got.append((await gd.view(req(), "d2"))["words"]["pending"])
            chk("«в пути» по-румынски: 1, 19, 20, 37, 101, 120",
                got, ["încă 1 programare în drum.", "încă 19 programări în drum.", "încă 20 de programări în drum.",
                      "încă 37 de programări în drum.", "încă 101 programări în drum.",
                      "încă 120 de programări în drum."])
            stats.update(error="", pending=0)
            gd.CHECK_WAIT, runs["delay"] = 0.2, 1.0
            chk("проход не успел — «продолжится в фоне»", await gd.check("d2"), "gd_check_late")
            runs.update(delay=0.0, **{"raise": True})
            chk("проход упал — то же, без 500", await gd.check("d2"), "gd_check_late")
            runs["raise"] = False
            woke.clear()
            chk("смена уровня будит сверку всех врачей", [await gd.set_level("initials", True, "Director"), list(woke)],
                ["gd_level_ok", [None]])

            cals.fail("DELETE", "/calendars/", 503, times=2)
            chk("Google не дал удалить календарь — связь держится, второе нажатие закроет её в программе",
                [await gd.disconnect("d2", "Director"), gdoc.linked().get("d2", {}).get("state"),
                 await gd.disconnect("d2", "Director"), gdoc.linked().get("d2")],
                ["gd_off_later", gdoc.S_ON, "gd_off_local", None])

            chk("снова подключён", await link(), ("gd_back_ok", 200))
            eng.DOCTOR_META.setdefault("d2", {})["status"] = "arhivat"
            v = await gd.view(req(), "d2")
            chk("архив при живой связи — своего состояния нет, подсказка: календарь уберёт сверка",
                [v["state"], (v["why"] or {}).get("code"), v["can"]["connect"], v["can"]["disconnect"]],
                ["on", "gd_archived_wait", False, True])
            eng.DOCTOR_META["d2"]["status"] = "activ"

            await license({"gcal": 30})
            v = await gd.view(req(), "d2")
            chk("Premium кончился при связи — paused: строка Premium, путь к оплате, только «Deconectează»",
                [v["state"], (v["why"] or {}).get("code"), bool((v["why"] or {}).get("detail")),
                 (v["premium"] or {}).get("href"), v["can"]],
                ["paused", "gd_paused", True, "/admin/license",
                 {"connect": False, "check": False, "disconnect": True}])
            chk("Premium кончился: связь и ключ хранятся", gdoc.linked().get("d2", {}).get("state"), gdoc.S_ON)
            chk("Premium кончился: «Sincronizează acum» — отказ Premium", await gd.check("d2"), "gd_premium")
            seq["n"] += 1
            tw.put_license(base, seq["n"], BOTH, readonly=True)
            await lic.refresh()
            v = await gd.view(req(), "d2")
            chk("режим чтения при связи — readonly: только «Deconectează»",
                [v["state"], (v["why"] or {}).get("code"), v["premium"], v["can"]],
                ["readonly", "gd_readonly", None, {"connect": False, "check": False, "disconnect": True}])
            chk("режим чтения: «Deconectează» уходит без права — календарь удалён",
                [await gd.disconnect("d2", "Director"), gdoc.linked().get("d2")], ["gd_off", None])
            v = await gd.view(req(), "d2")
            chk("режим чтения без связи — readonly, кнопок нет",
                [v["state"], v["can"]], ["readonly", {"connect": False, "check": False, "disconnect": False}])
        finally:
            gdoc.attach_sync(wake=None, run=None, stats=None)
            await db.close()
            g.close()
        print(json.dumps({"checks": checks}, ensure_ascii=False, default=str))

    asyncio.run(main())


def suite_worker(res: Result) -> None:
    """Из сети, право между входом и возвратом, крючки сверки, неудачное удаление, архив."""
    base = pathlib.Path(tempfile.mkdtemp(prefix="dp_gdocw_"))
    try:
        r = subprocess.run([str(PYTHON), str(pathlib.Path(__file__).resolve()), "worker", str(base)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=180, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        lines = [ln for ln in (r.stdout or "").splitlines() if ln.startswith("{")]
        if not res.ok("проба поднялась", r.returncode == 0 and len(lines) == 1,
                      f"rc={r.returncode}: {(r.stdout or '')[-600:]} {(r.stderr or '')[-2500:]}"):
            return
        got = json.loads(lines[0])
    finally:
        _rmtree_settled(base)
    for label, have, want in got["checks"]:
        res.check(label, have, want)


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "worker":
        sys.path.insert(0, str(BOT))
        _worker(sys.argv[2])
