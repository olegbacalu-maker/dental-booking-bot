"""Связь вкладки «Google Calendar» с аккаунтом Google клиники (`modules/schedule/gcal_link.py`).

Живой сервер программы и стенд Google из test_gapi в одном прогоне: сервер ходит на стенд
(`DENTART_GOOGLE_STAND`, только вне exe), клиент Google — JSON по `DENTART_GOOGLE_CLIENT`, право —
подписанный файл лицензии тестовым ключом. Браузер человека изображает `Google.consent`: адрес
согласия → строка возврата, её набор открывает свежим клиентом без куки, как браузер Windows.

Одна папка данных проходит Plus → Basic → Plus → режим чтения перезапусками сервера с новым файлом
лицензии: связь живёт в `google.json`, а не в памяти процесса, и это тоже проверяется.
"""
from __future__ import annotations

import json
import pathlib
import re
import tempfile
import time
import urllib.parse
from datetime import datetime, timedelta, timezone

import test_gapi as tg
from harness import BOT, FIXTURES, Client, Result, Server, TZ, _rmtree_settled, clinic_today
from test_gcal import cal, ev, listing, rows, upload
from test_license_state import gen, lst

KEYS = {"DENTART_LICENSE_KEYS": str(FIXTURES / "license" / "test-key.json")}
DAY = timedelta(days=1)
MAIN = "clinica@gmail.com"
CAL = "c_prog@group.calendar.google.com"
# Так стенд называет выданные токены и коды: ни один не должен лечь открытым текстом на диск.
SECRETS = re.compile(r"ya29-\d+|1//rt-\d+|4/code-\d+")
LINK_SRC = BOT / "app" / "modules" / "schedule" / "gcal_link.py"
_KEY = []


def _j(r) -> dict:
    return json.loads(r.body)


def _key():
    if not _KEY:
        _KEY.append(gen.load_key())
    return _KEY[0]


def put_license(d: pathlib.Path, seq: int, gcal_days: int | None, *, readonly: bool = False) -> None:
    """Подписанный файл в папке данных; `gcal_days` — право связи на столько дней вперёд."""
    now = datetime.now(timezone.utc).replace(microsecond=0)
    issued, valid, grace = (-40 * DAY, -20 * DAY, -6 * DAY) if readonly else (-DAY, 30 * DAY, 44 * DAY)
    features = {"gcal": lst.fmt(now + timedelta(days=gcal_days))} if gcal_days else {}
    claim = dict(gen.CLAIMS["valid"], seq=seq, issued_at=lst.fmt(now + issued),
                 valid_until=lst.fmt(now + valid), grace_until=lst.fmt(now + grace), features=features)
    payload = gen.claim_bytes(claim)
    (d / "license.json").write_text(gen.envelope(payload, gen.sign(payload, _key()), kid="test"),
                                    encoding="utf-8")


def client_file(d: pathlib.Path) -> pathlib.Path:
    p = d / "google-client.json"
    p.write_text(json.dumps({"installed": {"client_id": tg.CLIENT.id}}), encoding="utf-8")
    return p


def env(g: tg.Google, client: pathlib.Path, tick: str = "", **more) -> dict:
    out = {**KEYS, "DENTART_GOOGLE_CLIENT": str(client), "DENTART_GOOGLE_STAND": g.base, **more}
    if tick:
        out["DENTART_GCAL_TICK_S"] = tick
    return out


def gev(uid: str, n: int, hhmm: str, minutes: int, title: str) -> dict:
    """Событие `events.list`: день — через `n` дней от сегодня клиники, часы — по Кишинёву."""
    d = clinic_today() + timedelta(days=n)
    h, m = (int(x) for x in hhmm.split(":"))
    start = datetime(d.year, d.month, d.day, h, m, tzinfo=TZ)
    end = start + timedelta(minutes=minutes)
    return {"id": uid, "iCalUID": f"{uid}@google.com", "status": "confirmed", "summary": title,
            "start": {"dateTime": start.isoformat(), "timeZone": "Europe/Chisinau"},
            "end": {"dateTime": end.isoformat(), "timeZone": "Europe/Chisinau"}}


def stand() -> tg.Google:
    g = tg.Google()
    g.calendars = [
        {"id": MAIN, "summary": "Clinica", "primary": True, "accessRole": "owner", "timeZone": "Europe/Chisinau"},
        {"id": CAL, "summary": "Programări", "accessRole": "owner", "timeZone": "Europe/Chisinau"},
    ]
    g.events = {MAIN: [], CAL: [gev("g1", 3, "09:00", 30, "Popescu Ion 069123456"),
                                gev("g2", 4, "10:00", 60, "Balan Stefan"),
                                gev("g3", 5, "11:00", 30, "Rusu Ana")]}
    return g


def google(c: Client) -> dict | None:
    return listing(c)["google"]


def titles(c: Client) -> list:
    return sorted(x["title"] for x in rows(listing(c)))


def event_reads(g: tg.Google) -> int:
    return sum(1 for r in g.requests if r["path"].endswith("/events"))


def poll_minutes() -> int:
    m = re.search(r"^POLL_MINUTES = (\d+)", LINK_SRC.read_text(encoding="utf-8"), re.M)
    return int(m.group(1)) if m else -1


def login(res: Result, s: Server, c: Client, g: tg.Google, tag: str, *, keep: tuple | None = None):
    """Человек нажал «Conectează contul Google» и согласился в браузере: ответ страницы возврата."""
    r = c.post_json("/api/gcal/google/connect", {})
    res.check(f"{tag}: подключение отдаёт адрес Google", (r.status, r.msg), (200, "gc_g_url"))
    url = _j(r)["data"].get("url", "") if r.status == 200 else ""
    return url, Client(s.url).get("/google/back?" + g.consent(url, keep)) if url else None


def wait_until(fn, budget: float = 12.0) -> bool:
    end = time.time() + budget
    while time.time() < end:
        if fn():
            return True
        time.sleep(0.4)
    return False


# ---------- нет блока ----------


def suite_hidden(res: Result) -> None:
    """Блока связи нет без клиента Google в сборке, без ключей лицензии (сервер, `dev up`) и в
    демо; загрузка файла живёт как жила."""
    res.ok("исходник связи нашёлся", LINK_SRC.is_file(), str(LINK_SRC))
    g = stand()
    work = pathlib.Path(tempfile.mkdtemp(prefix="dp_glink_"))
    try:
        client = client_file(work)
        d1 = work / "a"
        d1.mkdir()
        put_license(d1, 1, 30)
        with Server(dir_=d1, env={**KEYS, "DENTART_GOOGLE_STAND": g.base}) as s:
            c = Client(s.url).login()
            res.check("без клиента Google: блока нет", google(c), None)
            r = c.post_json("/api/gcal/google/connect", {})
            res.check("без клиента Google: подключение — «недоступно»", (r.status, r.msg), (409, "gc_g_none"))
            res.check("без клиента Google: загрузка файла работает",
                      upload(c, cal([ev("h1", 3, "09:00", 30, "Fisier Ion")])).msg, "gc_loaded")
        with Server(env={"DENTART_GOOGLE_CLIENT": str(client), "DENTART_GOOGLE_STAND": g.base}) as s:
            c = Client(s.url).login()
            res.check("лицензия не применяется (сервер, песочница): блока нет", google(c), None)
            r = c.post_json("/api/gcal/google/connect", {})
            res.check("лицензия не применяется: подключение — «недоступно»", r.msg, "gc_g_none")
        d3 = work / "c"
        d3.mkdir()
        put_license(d3, 1, 30)
        with Server(dir_=d3, env=env(g, client, DENTART_DEMO="1")) as s:
            c = Client(s.url).login()
            res.check("демо: блока нет", google(c), None)
            r = c.post_json("/api/gcal/google/connect", {})
            res.check("демо: маршрута подключения нет", (r.status, r.msg), (403, "demo_off"))
            res.check("демо: адреса возврата нет", Client(s.url).get("/google/back?state=x").status, 303)
        res.ok("Google не спрашивали ни разу", not g.requests, repr(g.requests[:2]))
    finally:
        g.close()
        _rmtree_settled(work)


def suite_basic(res: Result) -> None:
    """Basic: блок виден строкой Plus и путём к лицензии, подключения нет; файл грузится."""
    g = stand()
    work = pathlib.Path(tempfile.mkdtemp(prefix="dp_glink_"))
    try:
        client = client_file(work)
        d = work / "data"
        d.mkdir()
        put_license(d, 1, None)
        with Server(dir_=d, env=env(g, client)) as s:
            c = Client(s.url).login()
            b = google(c) or {}
            res.check("Basic: состояние и строка — «face parte din DentPilot Plus»",
                      (b.get("state"), (b.get("why") or {}).get("text"), b.get("connected")),
                      ("plus", "Conectarea la contul Google face parte din DentPilot Plus", False))
            res.check("Basic: путь назад — страница лицензии", (b.get("plus") or {}).get("href"), "/admin/license")
            res.check("Basic: кнопок нет", b.get("can"),
                      {"connect": False, "calendar": False, "check": False, "disconnect": False})
            r = c.post_json("/api/gcal/google/connect", {})
            res.check("Basic: подключение — отказ Plus", (r.status, r.msg), (409, "gc_g_plus"))
            r = c.post_json("/api/gcal/google/check", {})
            res.check("Basic: проверка — отказ Plus", (r.status, r.msg), (409, "gc_g_plus"))
            res.check("Basic: загрузка файла .ics работает у всех тарифов",
                      upload(c, cal([ev("b1", 3, "09:00", 30, "Fisier Basic")])).msg, "gc_loaded")
            res.check("Basic: событие файла в списке", titles(c), ["Fisier Basic"])
        res.ok("Google не спрашивали ни разу", not g.requests, repr(g.requests[:2]))
    finally:
        g.close()
        _rmtree_settled(work)


# ---------- связь целиком ----------


def suite_link(res: Result) -> None:
    g = stand()
    work = pathlib.Path(tempfile.mkdtemp(prefix="dp_glink_"))
    try:
        client = client_file(work)
        d = work / "data"
        d.mkdir()
        put_license(d, 1, 30)
        _plus_first(res, g, client, d)
        put_license(d, 2, None)
        _basic_pause(res, g, client, d)
        put_license(d, 3, 30)
        _plus_again(res, g, client, d)
        put_license(d, 4, 30, readonly=True)
        _readonly(res, g, client, d)
    finally:
        g.close()
        _rmtree_settled(work)


def _plus_first(res: Result, g: tg.Google, client: pathlib.Path, d: pathlib.Path) -> None:
    with Server(dir_=d, env=env(g, client)) as s:
        c = Client(s.url).login()
        b = google(c) or {}
        n = poll_minutes()
        res.check("Plus без связи: «off», кнопка подключения", (b.get("state"), b.get("can", {}).get("connect")),
                  ("off", True))
        res.ok(f"уведомление называет опрос «din {n} în {n} minute» и политику",
               f"din {n} în {n} minute" in b.get("notice", "") and n > 0
               and b.get("privacy", {}).get("href", "").endswith("privacy.html#google"), b.get("notice", ""))
        res.check("слова кнопок — как в документах", b.get("words"),
                  {"connect": "Conectează contul Google", "disconnect": "Deconectează",
                   "check": "Verifică acum", "calendar": "Alege calendarul"})

        # Отказ на экране Google: вход погашен, связи нет.
        r = c.post_json("/api/gcal/google/connect", {})
        url = _j(r)["data"]["url"]
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        res.ok("адрес — экран согласия стенда, PKCE S256, наши права, возврат на этот порт",
               url.startswith(g.auth_url + "?") and q.get("code_challenge_method") == "S256"
               and q.get("scope") == " ".join(tg.gauth.SCOPES)
               and q.get("redirect_uri") == f"http://127.0.0.1:{s.port}/google/back", url)
        res.check("вход начат — экран ждёт браузер", google(c)["waiting"], True)
        back = Client(s.url).get("/google/back?" + urllib.parse.urlencode(
            {"error": "access_denied", "state": q["state"]}))
        res.ok("«Cancel» в Google — страница отказа, связи нет",
               back.status == 200 and "anulată" in back.body and google(c)["state"] == "off", back.body[:300])
        res.check("чужой state — «linkul nu mai este valabil»",
                  Client(s.url).get("/google/back?state=zzz&code=4/code-x").status, 400)

        url, back = login(res, s, c, g, "вход")
        res.ok("возврат — «contul este conectat» в браузере",
               back is not None and back.status == 200 and "este conectat" in back.body, back and back.body[:300])
        again = Client(s.url).get("/google/back?" + urllib.parse.urlsplit(url).query)
        res.ok("тот же вход ещё раз (F5) — «deja conectat», не ошибка и не второй обмен",
               again.status == 200 and "deja conectat" in again.body, f"{again.status} {again.body[:200]}")
        res.check("после возврата экран больше не ждёт", google(c)["waiting"], False)
        raw = (d / "google.json").read_text(encoding="utf-8")
        link = json.loads(raw)
        device = json.loads((d / "device.json").read_text(encoding="utf-8")).get("id")
        res.ok("файл связи: токен под DPAPI, открытого токена нет, привязан к device.json",
               link.get("token", "").startswith("dpapi:") and not SECRETS.search(raw)
               and link.get("device") == device, raw[:200])
        b = google(c)
        res.check("два календаря — выбор; адрес аккаунта — основной календарь",
                  (b["state"], [x["id"] for x in b["calendars"]], b["account"], b["can"]["calendar"]),
                  ("choose", [MAIN, CAL], MAIN, True))
        agents = {r.get("agent") for r in g.requests if r.get("agent")}
        res.ok("Google не получает личности машины: агент — только версия",
               agents and all(a.startswith("DentPilot/") and "d_" not in a for a in agents), repr(agents))

        r = c.post_json("/api/gcal/google/calendar", {"id": "nu-exista"})
        res.check("календарь не из списка — отказ", (r.status, r.msg), (422, "gc_g_bad"))
        r = c.post_json("/api/gcal/google/calendar", {"id": CAL})
        load = _j(r).get("data", {}).get("load") or {}
        res.check("выбор календаря — сразу первая проверка", (r.status, r.msg, load.get("new")),
                  (200, "gc_g_calendar", 3))
        b = google(c)
        res.ok("связь идёт: календарь, штамп проверки",
               b["state"] == "on" and b["calendar"] == {"id": CAL, "name": "Programări"}
               and b["last"] and b["last"]["when"], repr(b))
        res.check("события календаря в списке вкладки",
                  titles(c), ["Balan Stefan", "Popescu Ion 069123456", "Rusu Ana"])
        res.ok("источник — аккаунт Google по id календаря",
               any(x["kind"] == "google" and x["name"] == "Programări" for x in listing(c)["sources"]),
               repr(listing(c)["sources"]))
        q = next(r["query"] for r in reversed(g.requests) if r["path"].endswith("/events"))
        t_min = datetime.strptime(q["timeMin"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        t_max = datetime.strptime(q["timeMax"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        res.ok("окно опроса: сутки назад … год вперёд, серии развёрнуты",
               abs((now - t_min) - DAY) < timedelta(minutes=5)
               and abs((t_max - now) - 365 * DAY) < timedelta(minutes=5) and q.get("singleEvents") == "true",
               repr(q))

        g.events[CAL] = [gev("g1", 3, "09:30", 30, "Popescu Ion 069123456"),
                         gev("g3", 5, "11:00", 30, "Rusu Ana"), gev("g4", 6, "12:00", 30, "Nou Pacient")]
        r = c.post_json("/api/gcal/google/check", {})
        load = _j(r).get("data", {}).get("load") or {}
        res.check("«Verifică acum»: перенесённое, новое и пропавшее",
                  (r.msg, load.get("new"), load.get("updated"), load.get("same"), load.get("gone")),
                  ("gc_g_checked", 1, 1, 1, 1))
        res.check("пропавшее ушло из «De mutat»", titles(c), ["Nou Pacient", "Popescu Ion 069123456", "Rusu Ana"])

        # «Șterge tot» при связи: пауза, стирание, проверка снимает паузу.
        r = c.post_json("/api/gcal/clear", {})
        res.check("«Șterge tot» при связи — стёрто, связь на паузе",
                  (r.msg, google(c)["state"], titles(c)), ("gc_cleared_paused", "paused", []))
        r = c.post_json("/api/gcal/google/check", {})
        res.check("«Verifică acum» снимает паузу — события вернулись",
                  (r.msg, google(c)["state"], len(titles(c))), ("gc_g_checked", "on", 3))

        # Токен отозван в Google: опрос стоп, «reconectați»; файл и загрузка живут.
        for rt in list(g.refreshes):
            g._revoke(rt)
        r = c.post_json("/api/gcal/google/check", {})
        b = google(c)
        res.check("отзыв в Google — «conectați din nou», вход снова предложен",
                  (r.msg, b["state"], (b["why"] or {}).get("code"), b["can"]["connect"], b["connected"]),
                  ("gc_g_dead", "reconnect", "gc_g_dead", True, True))
        res.check("при мёртвой связи загрузка файла работает",
                  upload(c, cal([ev("f1", 7, "09:00", 30, "Din Fisier")])).msg, "gc_loaded")
        url, back = login(res, s, c, g, "вход заново")
        b = google(c)
        res.ok("вход заново — тот же календарь, без нового выбора",
               back is not None and back.status == 200 and b["state"] == "on"
               and (b["calendar"] or {}).get("id") == CAL, repr(b))
        res.check("после входа заново проверка идёт", c.post_json("/api/gcal/google/check", {}).msg,
                  "gc_g_checked")

        # Тик здесь — раз в POLL_MINUTES, файл связи сейчас никто не пишет.
        raw = (d / "google.json").read_text(encoding="utf-8")
        link = json.loads(raw)
        (d / "google.json").write_text(json.dumps({**link, "device": "d_000000000000"}), encoding="utf-8")
        b = google(c)
        res.check("файл связи с чужого компьютера — «conectați aici», считается на лету",
                  (b["state"], (b["why"] or {}).get("code")), ("reconnect", "gc_g_elsewhere"))
        (d / "google.json").write_text(raw, encoding="utf-8")
        res.check("файл свой — связь снова идёт", google(c)["state"], "on")

        leaks = [name for name in ("google.json", "dental.db", "dental.db-wal")
                 if (d / name).exists() and SECRETS.search((d / name).read_bytes().decode("latin-1"))]
        if SECRETS.search(s.log_text()):
            leaks.append("server.log")
        res.ok("ни токена, ни кода входа — ни в файлах, ни в базе, ни в логе", not leaks, repr(leaks))


def _basic_pause(res: Result, g: tg.Google, client: pathlib.Path, d: pathlib.Path) -> None:
    with Server(dir_=d, env=env(g, client, tick="1")) as s:
        c = Client(s.url).login()
        b = google(c) or {}
        res.check("Plus → Basic: пауза — строка «oprită», связь хранится, уйти можно",
                  (b.get("state"), (b.get("why") or {}).get("code"), b.get("connected"), b.get("can")),
                  ("plus", "gc_g_plus_off", True,
                   {"connect": False, "calendar": False, "check": False, "disconnect": True}))
        before = event_reads(g)
        time.sleep(3.5)
        res.check("Basic: опрос не ходит в Google, хотя тик — секунда", event_reads(g), before)
        link = json.loads((d / "google.json").read_text(encoding="utf-8"))
        res.ok("Basic: файл связи цел, не мёртв", link.get("token", "").startswith("dpapi:")
               and not link.get("dead"), repr({k: v for k, v in link.items() if k != "token"}))
        res.check("Basic: события остались в списке", len(titles(c)), 4)


def _plus_again(res: Result, g: tg.Google, client: pathlib.Path, d: pathlib.Path) -> None:
    with Server(dir_=d, env=env(g, client, tick="1")) as s:
        c = Client(s.url).login()
        res.check("Basic → Plus: связь работает без нового входа", google(c)["state"], "on")
        g.events[CAL].append(gev("g5", 8, "13:00", 30, "Adus De Opros"))
        res.ok("опрос сам приносит новое событие", wait_until(lambda: "Adus De Opros" in titles(c)),
               repr(titles(c)))

        r = c.post_json("/api/gcal/clear", {})
        res.check("«Șterge tot» при живом опросе — пауза", (r.msg, google(c)["state"]),
                  ("gc_cleared_paused", "paused"))
        before = event_reads(g)
        time.sleep(3.5)
        res.check("на паузе опрос не возвращает стёртое", (event_reads(g), titles(c)), (before, []))
        res.check("«Verifică acum» снимает паузу", c.post_json("/api/gcal/google/check", {}).msg, "gc_g_checked")
        res.ok("после паузы события снова в списке", len(titles(c)) >= 4, repr(titles(c)))


def _readonly(res: Result, g: tg.Google, client: pathlib.Path, d: pathlib.Path) -> None:
    with Server(dir_=d, env=env(g, client)) as s:
        c = Client(s.url).login()
        b = google(c) or {}
        res.check("режим чтения: связь стоит, уйти можно",
                  (b.get("state"), (b.get("why") or {}).get("code"), b.get("can", {}).get("disconnect")),
                  ("readonly", "gc_g_readonly", True))
        for path, body in (("/api/gcal/google/connect", {}), ("/api/gcal/google/check", {}),
                           ("/api/gcal/google/calendar", {"id": CAL})):
            res.check(f"режим чтения: {path.rsplit('/', 1)[-1]} — 423", c.post_json(path, body).status, 423)
        alive = len(g.refreshes)
        r = c.post_json("/api/gcal/google/disconnect", {})
        res.check("режим чтения: «Deconectează» — отзыв у Google и файл удалён",
                  (r.status, r.msg, (d / "google.json").exists(), len(g.refreshes) < alive),
                  (200, "gc_g_off", False, True))
        res.check("после отключения связи нет", google(c)["connected"], False)
        res.check("второй раз отключать нечего", c.post_json("/api/gcal/google/disconnect", {}).msg, "gc_g_gone")
        (d / "google.json").write_text(json.dumps({"token": "dpapi:AAAA", "device": "d_000000000000"}),
                                       encoding="utf-8")
        r = c.post_json("/api/gcal/google/disconnect", {})
        res.check("чужой файл связи (другой ПК) — удаляется без отзыва, слово «Google nu a confirmat»",
                  (r.msg, (d / "google.json").exists()), ("gc_g_off_local", False))
