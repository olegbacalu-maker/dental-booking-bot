"""Ответ пациента ссылкой из SMS (Premium, волна 2а): провод, коды, забор ответов, отметка в журнале.

Сервер лицензий подменён стендом в процессе теста — тем же, что у SMS (`test_sms.Stand`), плюс
`/v1/link/*` по контракту `review/premium-w2-ready-2026-11-26.md` § 2.3 (без `slots` и `result`).
Что настоящий сервер понимает этот провод, проверяет прогон облака: он грузит `core/plink.py`
по пути и сверяет двойник `CODE_RE`.

Живой набор идёт под поддельными часами (`harness.Clock`): пятница перед визитами понедельника.
Код выдаётся накануне ДО постановки SMS; сервер ссылок молчит — строки нет; право снято
(`link_plan`) — обычный текст; «Vin», «Nu pot veni», смена ответа, звонок стойки новее
ответа; перенос после отправки закрывает старую ссылку и даёт новую; стирание пациента
закрывает его код; «În ziua vizitei» ссылку не несёт.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import tempfile
import time
import urllib.parse
from datetime import datetime, timedelta, timezone

import test_license_renew as lr
import test_sms as ts
from harness import (BOT, Client, Clock, Result, Server, _rmtree_settled, add_appt, appt_id, day_model,
                     panel_live, pid_by_phone)

WIRE = BOT / "app" / "core" / "plink.py"
SHELL_TOKEN = "t" * 40
HOST = "v.dentpilot.md"
ALPHA = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _load(name: str, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


wire = _load("plink_wire", WIRE)


def _license(d: pathlib.Path, renew: dict, features: dict) -> None:
    """Подписанный файл с `renew` и правами (`features`: имя → дней вперёд)."""
    now = datetime.now(timezone.utc).replace(microsecond=0)
    day = timedelta(days=1)
    claim = dict(lr.gen.CLAIMS["valid"], seq=5, issued_at=(now - 40 * day).strftime(lr.TS),
                 valid_until=(now + 400 * day).strftime(lr.TS), grace_until=(now + 414 * day).strftime(lr.TS),
                 renew=renew, features={k: (now + v * day).strftime(lr.TS) for k, v in features.items()})
    payload = lr.gen.claim_bytes(claim)
    (d / "license.json").write_text(lr.gen.envelope(payload, lr.gen.sign(payload, lr.gen.load_key())),
                                    encoding="utf-8")


class LinkStand(ts.Stand):
    """Стенд SMS + ссылки. `link_mode`: ok | down | plan; `inbox_mode`: ok | down.
    `answer(code, state, at)` — пациент нажал кнопку: новая перемена с номером `seq`."""

    def __init__(self):
        super().__init__()
        self.link_mode = "ok"
        self.inbox_mode = "ok"
        self.issued: list[dict] = []        # запросы /v1/link/new
        self.closed: list[str] = []
        self.inbox_calls: list[int] = []
        self.events: list[dict] = []
        self.codes: dict[str, str] = {}     # код → язык
        self._n = 0
        stand = self
        base_h = self.srv.RequestHandlerClass

        class H(base_h):
            def do_GET(self):
                if self.path.startswith("/v1/link/inbox"):
                    after = int(urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)["after"][0])
                    stand.inbox_calls.append(after)
                    if stand.inbox_mode == "down":
                        self._reply(500, None)
                        return
                    items = [e for e in stand.events if e["seq"] > after]
                    self._reply(200, {"ok": True, "seq": max([after] + [e["seq"] for e in stand.events]),
                                      "items": items})
                    return
                super().do_GET()

            def do_POST(self):
                if not self.path.startswith("/v1/link/"):
                    super().do_POST()
                    return
                raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                body = json.loads(raw.decode("utf-8"))
                if self.path == "/v1/link/new":
                    stand.issued.append(body)
                    if stand.link_mode == "down":
                        self._reply(503, None)
                        return
                    if stand.link_mode == "plan":
                        self._reply(403, {"ok": False, "code": "link_plan", "text": "Premium"})
                        return
                    codes = []
                    for lang in body["langs"]:
                        stand._n += 1
                        n = stand._n
                        code = "K" + "".join(ALPHA[(n * 7 + i * 11) % 32] for i in range(5))
                        stand.codes[code] = lang
                        codes.append(code)
                    self._reply(200, {"ok": True, "host": HOST, "codes": codes})
                elif self.path == "/v1/link/close":
                    stand.closed.extend(body.get("codes") or [])
                    self._reply(200, {"ok": True})
                else:
                    self._reply(404, {"ok": False})

        self.srv.RequestHandlerClass = H

    def answer(self, code: str, state: str, at: datetime) -> None:
        seq = (self.events[-1]["seq"] if self.events else 9100) + 1
        self.events.append({"code": code, "seq": seq, "state": state,
                            "at": at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})


# ---------- провод ----------


def suite_wire(res: Result) -> None:
    """core/plink.py: чистый модуль, правило кода, форма ответов, исходы по коду, без редиректов."""
    if not res.ok("исходник провода ссылок нашёлся", WIRE.is_file(), str(WIRE)):
        return
    ts._pure(res, "провод ссылок", WIRE, ts.WIRE_IMPORTS | {"re"})
    res.check("алфавит кода: 32 знака без I O 0 1, длина 6",
              (all(wire.code_ok(c * 6) for c in ALPHA), [wire.code_ok(c * 6) for c in "IO01"],
               wire.code_ok("K7Q2M"), wire.code_ok("K7Q2MXX"), wire.code_ok("k7q2mx")),
              (True, [False] * 4, False, False, False))
    res.check("адрес в SMS — без схемы", wire.url(HOST, "K7Q2MX"), "v.dentpilot.md/K7Q2MX")
    res.check("кривой хост или код — пустой адрес",
              [wire.url("evil.md/x", "K7Q2MX"), wire.url(HOST, "K7Q2M0"), wire.url("", "K7Q2MX")], ["", "", ""])
    res.check("base_of: /v1/link/ того же сервера", wire.base_of("https://cloud.dentpilot.md/v1/license"),
              "https://cloud.dentpilot.md/v1/link/")
    stand = LinkStand()
    base = stand.base + "/v1/link/"
    try:
        out, body = wire.new(base, ts.TOKEN, "2026-11-09T10:00:00Z", ["ro", "ru"], "Clinica Test", "022")
        res.ok("выдача: два кода по языкам и хост", out == wire.OK and len(body["codes"]) == 2
               and body["host"] == HOST and stand.issued[-1] == {"kind": "confirm", "until": "2026-11-09T10:00:00Z",
                                                                  "langs": ["ro", "ru"], "label": "Clinica Test",
                                                                  "phone": "022"}, repr((out, body, stand.issued)))
        stand.link_mode = "plan"
        out, body = wire.new(base, ts.TOKEN, "2026-11-09T10:00:00Z", ["ro"], "X", "")
        res.check("право снято — DENIED с кодом link_plan", (out, body.get("code")), (wire.DENIED, "link_plan"))
        stand.link_mode = "down"
        res.check("сервер упал — OFFLINE", wire.new(base, ts.TOKEN, "x", ["ro"], "X", "")[0], wire.OFFLINE)
        stand.link_mode = "ok"
        stand.answer("K7Q2MX", "yes", datetime(2026, 11, 6, 8, 4, tzinfo=timezone.utc))
        stand.events.append({"code": "BAD0", "seq": 9300, "state": "yes", "at": "x"})
        stand.events.append({"code": "K7Q2MY", "seq": 9301, "state": "pick", "at": "2026-11-06T08:05:00Z"})
        out, body = wire.inbox(base, ts.TOKEN, 0)
        res.ok("забор: кривой код и незнакомое состояние отброшены, seq — наибольший",
               out == wire.OK and [i["code"] for i in body["items"]] == ["K7Q2MX"] and body["seq"] == 9301,
               repr(body))
        stand.inbox_mode = "down"
        res.check("забор: сервер молчит — OFFLINE", wire.inbox(base, ts.TOKEN, 0)[0], wire.OFFLINE)
        res.check("закрытие: только годные коды", (wire.close(base, ts.TOKEN, ["K7Q2MX", "nope"])[0], stand.closed),
                  (wire.OK, ["K7Q2MX"]))
        res.check("редиректу не следует", wire.new(stand.base + "/redir?", ts.TOKEN, "x", ["ro"], "X", "")[0],
                  wire.OFFLINE)
    finally:
        stand.close()


# ---------- живой цикл ----------


def _card(c: Client, day: str, aid: int) -> dict:
    """Поля отметки визита в модели дня (канва и карточка — одним правилом `call_fields`)."""
    found = []

    def walk(x):
        if isinstance(x, dict):
            if x.get("id") == aid and "call_via" in x:
                found.append(x)
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(day_model(c, day))
    return found[0] if found else {}


def _link_rows(d: pathlib.Path) -> list[dict]:
    return ts._rows(d, "SELECT * FROM sms_links ORDER BY created_at, code")


def _call(d: pathlib.Path, aid: int) -> dict:
    rows = ts._rows(d, "SELECT result, via, actor, at FROM appt_calls WHERE appointment_id = ?", aid)
    return rows[0] if rows else {}


def _calls_events(d: pathlib.Path, pid: int) -> list[tuple]:
    return [(r["actor"], r["text"]) for r in ts._rows(
        d, "SELECT actor, text FROM activity WHERE patient_id = ? AND kind = 'call' ORDER BY id", pid)]


def _sent_for(stand, aid: int, kind: str = "day_before") -> list[str]:
    return [x["json"]["text"] for x in stand.sends if x["json"].get("idem", "").startswith(f"appt:{aid}:{kind}:")]


def _code_of(text: str) -> str:
    for line in text.splitlines():
        for head in ("Confirmare/anulare: ", "Ответить: "):
            if line.startswith(head):
                return line[len(head):].rsplit("/", 1)[-1]
    return ""


def suite_live(res: Result) -> None:
    """Накануне: код до SMS, текст со ссылкой, ответы в журнал, смена ответа, звонок стойки,
    перенос, сервер молчит, право снято, стирание; в день визита ссылки нет."""
    stand = LinkStand()
    renew = {"url": stand.url, "token": ts.TOKEN}
    d = pathlib.Path(tempfile.mkdtemp(prefix="dp_plink_"))
    env = {**ts.KEY_ENV, **ts.TICK, "DENTART_PLINK_TICK_S": "0.3", "DENTART_SHELL_TOKEN": SHELL_TOKEN}
    fri, mon = (2026, 11, 6), (2026, 11, 9)
    sms = {"day_before": {"on": True, "hour": 10, "variant": "standard"},
           "same_day": {"on": True, "hours": 2, "variant": "standard"}, "phone_line": True,
           "link": {"confirm": True}}
    try:
        ts._clinic_weekdays(d, sms)
        _license(d, renew, {"sms_link": 400})
        with Clock(ts._at(*fri, 9, 0)) as clock:
            with Server(dir_=d, env=env) as s:
                c = Client(s.url).login()
                data = ts._wait(lambda: (ts._j(c.get("/api/settings/sms"))["data"] or {}).get("link", {}).get("on")
                                and ts._j(c.get("/api/settings/sms"))["data"]) or ts._j(c.get("/api/settings/sms"))["data"]
                res.ok("экран: право Premium есть, галочка стоит, ссылка работает, 2 части",
                       data["link"]["allowed"] and data["link"]["confirm"] and data["link"]["on"]
                       and data["link"]["parts"] == 2 and data["link"]["until"], repr(data.get("link")))
                res.ok("прогноз: накануне — 2 части (ссылка), в день визита — 1",
                       data["forecast"]["parts"] == {"day_before": 2, "same_day": 1}, repr(data["forecast"]))
                for day, hh, name, phone in ((mon, "12:00", "Link Alfa", "069100111"),
                                             (mon, "12:00", "Link Beta", "069100222"),
                                             (mon, "13:00", "Link Gamma", "069100333"),
                                             (mon, "14:00", "Link Delta", "069100444")):
                    r = add_appt(c, "2026-11-09", hh, name, phone, doctor="d3" if name == "Link Beta" else "d2")
                    res.check(f"визит {name} записан", r.msg, "ok")
                a, b, g, dl = (appt_id(c, "2026-11-09", n) for n in ("Link Alfa", "Link Beta", "Link Gamma", "Link Delta"))
                con = ts._db(d)
                con.execute("UPDATE patients SET lang = 'ru' WHERE phone LIKE '%100222%'")
                con.commit()
                con.close()
                time.sleep(1.0)
                res.ok("до часа X ни кода, ни SMS", not stand.issued and not stand.sends and not _link_rows(d),
                       repr(stand.issued))

                # ---- час X: коды до SMS, текст со ссылкой ----
                clock.set(ts._at(*fri, 10, 0, 30))
                res.ok("в 10:00 ушли четыре напоминания", ts._wait(lambda: len(stand.sends) >= 4), repr(stand.sends))
                res.ok("коды выданы запросом на каждое начало визита: until — начало, подпись и телефон клиники",
                       sorted((x["until"], tuple(sorted(x["langs"]))) for x in stand.issued)
                       == [("2026-11-09T10:00:00Z", ("ro", "ru")), ("2026-11-09T11:00:00Z", ("ro",)),
                           ("2026-11-09T12:00:00Z", ("ro",))]
                       and all(x["kind"] == "confirm" and x["label"] == "Clinica Test"
                               and x["phone"] == "+373 60 000 000" for x in stand.issued), repr(stand.issued))
                ta, tb = (_sent_for(stand, a) or [""])[0], (_sent_for(stand, b) or [""])[0]
                rows = {r["appt_id"]: r for r in _link_rows(d)}
                res.ok("текст RO: Detaliat со ссылкой, ссылка строкой выше «Anulare», ровно 2 части",
                       ta.startswith("Buna ziua! Clinica Test va reaminteste de programarea dvs.:\nluni, 09.11, ora 12:00.")
                       and f"\nConfirmare/anulare: {HOST}/{rows.get(a, {}).get('code')}\nAnulare: +373 60 000 000" in ta
                       and ta.endswith("Anulare: +373 60 000 000") and ts.rule.parts(ta)[2] == 2, repr(ta))
                res.ok("текст RU: «Ответить:» и код его языка", f"\nОтветить: {HOST}/{rows.get(b, {}).get('code')}" in tb
                       and stand.codes.get(rows.get(b, {}).get("code")) == "ru" and ts.rule.parts(tb)[2] == 2, repr(tb))
                res.ok("строка кода у визита: начало, срок — начало визита, open",
                       rows.get(a, {}).get("starts_key") == "2026-11-09T10:00:00Z" and rows[a]["state"] == "open"
                       and rows[a]["until_at"].startswith("2026-11-09T10:00:00"), repr(rows.get(a)))
                time.sleep(1.0)
                res.check("коды не множатся следующими проходами", len(stand.issued), 3)

                # ---- ответы: сервер молчит, потом «Vin» ----
                stand.inbox_mode = "down"
                stand.answer(rows[a]["code"], "yes", ts._at(*fri, 10, 4))
                time.sleep(1.5)
                res.ok("забор: сервер молчит — отметки нет, журнал работает",
                       not _call(d, a) and c.get("/admin").status == 200 and stand.inbox_calls, repr(_call(d, a)))
                stand.inbox_mode = "ok"
                got = ts._wait(lambda: _call(d, a).get("result") == "ok")
                res.ok("«Vin» → отметка ok · sms, подпись pacient, время нажатия",
                       got and _call(d, a)["via"] == "sms" and _call(d, a)["actor"] == "pacient"
                       and _call(d, a)["at"].startswith("2026-11-06T08:04"), repr(_call(d, a)))
                pa = pid_by_phone(c, "069100111")
                res.check("летопись готовой строкой, автор pacient", _calls_events(d, pa),
                          [("pacient", "Confirmare prin SMS (09.11 12:00): confirmat")])
                card = _card(c, "2026-11-09", a)
                res.check("окно визита: call / call_via / call_at", (card.get("call"), card.get("call_via"),
                                                                    card.get("call_at")), ("ok", "sms", "06.11, 10:04"))
                h = c.get("/api/schedule/live?screen=panel").header("X-DP-Hash")
                res.check("живой канал неподвижен после ответа: второй опрос — 204",
                          c.get("/api/schedule/live?screen=panel", {"X-DP-Hash": h}).status, 204)

                # ---- смена ответа: «Nu pot veni» ----
                clock.set(ts._at(*fri, 10, 6, 30))
                stand.answer(rows[a]["code"], "no", ts._at(*fri, 10, 6))
                got = ts._wait(lambda: _call(d, a).get("result") == "cant")
                res.ok("смена ответа: последняя перемена побеждает — cant · sms", got and _call(d, a)["via"] == "sms",
                       repr(_call(d, a)))
                res.check("летопись: вторая строка", _calls_events(d, pa)[-1],
                          ("pacient", "Confirmare prin SMS (09.11 12:00): nu poate veni"))
                # второй «Nu pot veni» — у визита в 14:00: он обязан встать выше неотмеченного 12:00
                stand.answer(rows[dl]["code"], "no", ts._at(*fri, 10, 6))
                ts._wait(lambda: _call(d, dl).get("result") == "cant")
                conf = panel_live(c)["desk"]["confirm"]
                order = [x["id"] for x in conf["items"]]
                res.ok("«De confirmat»: «Nu poate veni» первыми (и 14:00 выше неотмеченного 12:00), счётчик n_cant",
                       order[:2] == [a, dl] and conf["items"][0]["call"] == "cant"
                       and conf["items"][0]["call_via"] == "sms" and conf["n_cant"] == 2, repr(conf))
                res.ok("окно визита: статус не тронут — программа ничего не отменяет",
                       ts._rows(d, "SELECT status FROM appointments WHERE id = ?", a)[0]["status"] == "confirmed")
                notes = ts._j(c.get("/shell/notices", {"X-DentPilot-Shell": SHELL_TOKEN}))
                item = next((i for i in notes.get("items", []) if i["id"].startswith("plink:no:")), None)
                res.ok("уведомление у часов на «Nu pot veni» — без имени пациента",
                       item is not None and "Link Alfa" not in json.dumps(item, ensure_ascii=False), repr(notes))

                # ---- звонок стойки новее ответа ----
                clock.set(ts._at(*fri, 10, 9))
                r = c.post_json(f"/api/schedule/desk/call/{a}?screen=panel", {"result": "ok"})
                res.check("стойка дозвонилась", r.status, 200)
                stand.answer(rows[a]["code"], "yes", ts._at(*fri, 10, 7))
                time.sleep(1.5)
                res.ok("ответ, нажатый раньше звонка, звонок не перебивает: отметка стойки, канал ''",
                       _call(d, a).get("via") == "" and _call(d, a).get("result") == "ok"
                       and _call(d, a).get("actor") != "pacient", repr(_call(d, a)))

                # ---- перенос после отправки: старая ссылка закрыта, новая — новым кодом ----
                old = rows[g]["code"]
                r = c.post_json(f"/api/schedule/appointments/{g}/move?date=2026-11-09",
                                {"date": "2026-11-09", "time": "16:00", "doctor": "d2"})
                res.check("перенос Gamma на 16:00", r.msg, "ok_move")
                res.ok("старый код закрыт на сервере", ts._wait(lambda: old in stand.closed), repr(stand.closed))
                res.ok("у себя: closed и подтверждён сервером", ts._wait(lambda: next(
                    (x for x in _link_rows(d) if x["code"] == old and x["state"] == "closed" and x["shut_at"]), None)),
                       repr(_link_rows(d)))
                got = ts._wait(lambda: len(_sent_for(stand, g)) >= 2)
                new_code = _code_of(_sent_for(stand, g)[-1]) if got else ""
                res.ok("новое напоминание — с новым кодом и новым часом",
                       got and new_code and new_code != old and "ora 16:00" in _sent_for(stand, g)[-1],
                       repr(_sent_for(stand, g)))
                stand.answer(old, "yes", ts._at(*fri, 10, 12))
                time.sleep(1.5)
                res.ok("ответ по старому коду отметку не ставит", not _call(d, g), repr(_call(d, g)))

                # ---- сервер ссылок молчит: нет кода — нет строки ----
                stand.link_mode = "down"
                add_appt(c, "2026-11-09", "15:30", "Link Eps", "069100555", doctor="d4")
                e = appt_id(c, "2026-11-09", "Link Eps")
                time.sleep(1.5)
                res.ok("сервер ссылок молчит: SMS не ушла, в очереди строки нет",
                       not _sent_for(stand, e) and not ts._rows(d, "SELECT id FROM sms_log WHERE appt_id = ?", e),
                       repr(_sent_for(stand, e)))
                stand.link_mode = "ok"
                res.ok("сервер ответил — SMS со ссылкой", ts._wait(lambda: _code_of((_sent_for(stand, e) or [""])[0])),
                       repr(_sent_for(stand, e)))

                # ---- право снято на сервере: обычный текст ----
                stand.link_mode = "plan"
                add_appt(c, "2026-11-09", "17:00", "Link Zeta", "069100666", doctor="d4")
                z = appt_id(c, "2026-11-09", "Link Zeta")
                got = ts._wait(lambda: _sent_for(stand, z))
                tz_ = (got or [""])[0]
                res.ok("link_plan: обычный текст выбранного варианта, без ссылки, одна часть",
                       got and "Confirmare/anulare" not in tz_ and tz_.startswith("Buna ziua! Clinica Test va reaminteste ca")
                       and ts.rule.parts(tz_)[2] == 1, repr(tz_))
                res.ok("и кода у визита нет", not [x for x in _link_rows(d) if x["appt_id"] == z])
                stand.link_mode = "ok"

                # ---- стирание пациента: код закрыт на сервере ----
                pd = pid_by_phone(c, "069100444")
                dcode = next(x["code"] for x in _link_rows(d) if x["appt_id"] == dl)
                r = c.post_json(f"/api/patients/{pd}/erase", {"confirm": "STERG"})
                res.check("пациент без лечения стёрт", r.msg, "ok_del")
                res.ok("строк кода стёртого нет", not [x for x in _link_rows(d) if x["code"] == dcode])
                res.ok("его код закрыт на сервере, список закрытия пуст",
                       ts._wait(lambda: dcode in stand.closed)
                       and ts._wait(lambda: not (ts._rows(d, "SELECT value FROM schema_meta WHERE key = 'plink_close'")
                                                 or [{"value": ""}])[0]["value"]), repr(stand.closed))
                log = s.log_text()
                codes = [x["code"] for x in _link_rows(d)] + [old, dcode]
                res.ok("в логе сервера нет ни кода, ни адреса ссылки",
                       not any(cd in log for cd in codes) and HOST not in log and "Traceback" not in log, log[-600:])

            # ---- понедельник: «În ziua vizitei» ссылку не несёт ----
            clock.set(ts._at(*mon, 10, 0, 30))
            with Server(dir_=d, env=env) as s:
                got = ts._wait(lambda: _sent_for(stand, b, "same_day"))
                res.ok("в день визита — обычный текст без ссылки",
                       got and "Ответить" not in got[0] and "Confirmare/anulare" not in got[0], repr(got))
    finally:
        stand.close()
        _rmtree_settled(d)


def suite_rights(res: Result) -> None:
    """Без права `sms_link` (Plus): галочка не действует — текст без ссылки, кодов не просят."""
    stand = LinkStand()
    renew = {"url": stand.url, "token": ts.TOKEN}
    d = pathlib.Path(tempfile.mkdtemp(prefix="dp_plink2_"))
    env = {**ts.KEY_ENV, **ts.TICK, "DENTART_PLINK_TICK_S": "0.3"}
    try:
        ts._clinic_weekdays(d, {"day_before": {"on": True, "hour": 10, "variant": "detaliat"},
                                "link": {"confirm": True}})
        _license(d, renew, {})
        with Clock(ts._at(2026, 11, 6, 10, 0, 30)):
            with Server(dir_=d, env=env) as s:
                c = Client(s.url).login()
                add_appt(c, "2026-11-09", "12:00", "Plus Alfa", "069200111")
                got = ts._wait(lambda: stand.sends)
                text = got[0]["json"]["text"] if got else ""
                res.ok("Plus: Detaliat без ссылки, ровно 2 части, кодов не просили",
                       got and "Confirmare/anulare" not in text and "10 minute mai devreme" in text
                       and ts.rule.parts(text)[2] == 2 and not stand.issued, repr(text))
                data = ts._j(c.get("/api/settings/sms"))["data"]
                res.ok("экран Plus: права нет, галочка в файле, ссылка не работает",
                       not data["link"]["allowed"] and data["link"]["confirm"] and not data["link"]["on"],
                       repr(data["link"]))
                res.check("прогноз Plus: накануне — по варианту Detaliat", data["forecast"]["parts"]["day_before"], 2)
                time.sleep(1.0)
                res.check("забор ответов без права не идёт", stand.inbox_calls, [])
    finally:
        stand.close()
        _rmtree_settled(d)

