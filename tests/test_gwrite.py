"""Провод записи Google (`app/core/gwrite.py`) на стенде: календарь врача и его события.

Стенд — `test_gapi.Google` с крючком записи `Calendars`: календари и события в памяти, как их описывает
справка и как ответил настоящий Google (409 на повторный id и на «надгробие», 410 на повторное
удаление, `cancelled` после удаления, отбор `privateExtendedProperty`, `dataOwner`). Сервер программы не
поднимается. `Calendars` и `put_license` — общие для наборов двери (`test_gdoc`) и тех, что строятся на ней.
"""
from __future__ import annotations

import json
import pathlib
import re
import urllib.parse
from datetime import datetime, timedelta, timezone

import test_gapi as tg
import test_ics as t
from harness import BOT, Result
from test_license_state import gen, lst

from app.core import gauth, gclient, gwrite  # noqa: E402 — путь к bot/ кладёт test_gapi

GWRITE = BOT / "app" / "core" / "gwrite.py"
WRITE_IMPORTS = {"__future__", "base64", "hashlib", "http.client", "json", "re", "urllib.error",
                 "urllib.parse", "urllib.request", "dataclasses", "datetime"}
OWNER = "medic@gmail.com"
DAY = timedelta(days=1)
_ID = re.compile(r"[0-9a-v]{5,1024}")
_KEY = []


def _err(status: int, reason: str, domain: str = "global") -> tuple:
    return status, {"error": {"code": status, "errors": [{"reason": reason, "domain": domain}]}}


class Calendars:
    """Календари врача у стенда Google: крючок `Google.write`. `owner` — аккаунт, чей токен пишет
    (его отдаёт `dataOwner`); `fail(…)` — следующий подходящий запрос отвечает заказанным;
    `purge(id)` — «надгробие» исчезло, как обещает справка."""

    def __init__(self, g: tg.Google, owner: str = OWNER):
        self.g = g
        self.owner = owner
        self.cals: dict[str, dict] = {}
        self.events: dict[str, dict[str, dict]] = {}
        self.faults: list[dict] = []
        self.page = 2500
        self._n = 0
        g.write = self.handle

    def fail(self, method: str, part: str, status: int, body: dict | None = None, *,
             headers: dict | None = None, times: int = 1) -> None:
        self.faults.append({"method": method, "part": part, "reply": (status, body or {}, headers or {}),
                            "times": times})

    def purge(self, cal_id: str, event_id: str) -> None:
        self.events.get(cal_id, {}).pop(event_id, None)

    def live(self, cal_id: str) -> dict:
        return {k: v for k, v in self.events.get(cal_id, {}).items() if v.get("status") != "cancelled"}

    def handle(self, method: str, path: str, query: dict, body, scopes: frozenset):
        for f in self.faults:
            if f["method"] == method and f["part"] in path and f["times"] > 0:
                f["times"] -= 1
                return f["reply"]
        if path == "/calendar/v3/users/me/calendarList" or path.startswith("/calendar/v3/users/me/calendarList/"):
            # право календаря врача списка календарей не даёт
            return _err(403, "insufficientPermissions")
        if gauth.APP_CREATED not in scopes:
            return _err(403, "insufficientPermissions")
        rest = path[len("/calendar/v3/"):]
        parts = [urllib.parse.unquote(p) for p in rest.split("/")]
        if parts == ["calendars"] and method == "POST":
            return self._cal_insert(body)
        if len(parts) >= 2 and parts[0] == "calendars":
            cid = parts[1]
            if cid not in self.cals:
                return _err(404, "notFound")
            if len(parts) == 2:
                return self._cal(method, cid, body)
            if len(parts) == 3 and parts[2] == "events":
                if method == "POST":
                    return self._ev_insert(cid, body)
                if method == "GET":
                    return self._ev_list(cid, query)
            if len(parts) == 4 and parts[2] == "events":
                return self._ev(method, cid, parts[3], body)
        return None

    def _cal_insert(self, body) -> tuple:
        if not isinstance(body, dict) or not body.get("summary"):
            return _err(400, "required")
        self._n += 1
        cid = f"c{self._n}x@group.calendar.google.com"
        self.cals[cid] = {"kind": "calendar#calendar", "id": cid, "summary": body["summary"],
                          "description": body.get("description", ""), "timeZone": body.get("timeZone", "UTC"),
                          "dataOwner": self.owner, "etag": f'"{self._n}"'}
        self.events[cid] = {}
        return 200, dict(self.cals[cid])

    def _cal(self, method: str, cid: str, body) -> tuple:
        if method == "GET":
            return 200, dict(self.cals[cid])
        if method == "PATCH":
            for k in ("summary", "description"):
                if isinstance(body, dict) and k in body:
                    self.cals[cid][k] = body[k]
            return 200, dict(self.cals[cid])
        if method == "DELETE":
            del self.cals[cid]
            self.events.pop(cid, None)
            return 204, {}
        return _err(400, "badRequest")

    def _ev_insert(self, cid: str, body) -> tuple:
        if not isinstance(body, dict):
            return _err(400, "required")
        eid = body.get("id", "")
        if not isinstance(eid, str) or not _ID.fullmatch(eid):
            return _err(400, "invalid")
        if eid in self.events[cid]:
            return _err(409, "duplicate")
        self.events[cid][eid] = {**body, "status": body.get("status") or "confirmed"}
        return 200, {"id": eid, "status": self.events[cid][eid]["status"]}

    def _ev(self, method: str, cid: str, eid: str, body) -> tuple:
        ev = self.events[cid].get(eid)
        if method == "PUT":
            if ev is None:
                return _err(404, "notFound")
            if not isinstance(body, dict):
                return _err(400, "required")
            self.events[cid][eid] = {**body, "id": eid, "status": body.get("status") or "confirmed"}
            return 200, {"id": eid, "status": self.events[cid][eid]["status"]}
        if method == "DELETE":
            if ev is None:
                return _err(404, "notFound")
            if ev.get("status") == "cancelled":
                return _err(410, "deleted")
            ev["status"] = "cancelled"
            return 204, {}
        if method == "GET" and ev is not None:
            return 200, dict(ev)
        return _err(404, "notFound")

    def _ev_list(self, cid: str, query: dict) -> tuple:
        want = query.get("privateExtendedProperty", "")
        key, _, val = want.partition("=")
        items = [e for e in self.events[cid].values()
                 if (query.get("showDeleted") == "true" or e.get("status") != "cancelled")
                 and (not want or (e.get("extendedProperties") or {}).get("private", {}).get(key) == val)]
        size = min(int(query.get("maxResults") or 250), self.page)
        start = int((query.get("pageToken") or "p0")[1:])
        out = {"items": [{"id": e["id"], "status": e.get("status", ""),
                          "extendedProperties": e.get("extendedProperties", {})} for e in items[start:start + size]]}
        if start + size < len(items):
            out["nextPageToken"] = f"p{start + size}"
        return 200, out


def put_license(d: pathlib.Path, seq: int, features: dict, *, readonly: bool = False) -> None:
    """Подписанный файл лицензии в папке данных; `features` — имя права → на сколько дней вперёд
    (None или 0 — права нет)."""
    if not _KEY:
        _KEY.append(gen.load_key())
    now = datetime.now(timezone.utc).replace(microsecond=0)
    issued, valid, grace = (-40 * DAY, -20 * DAY, -6 * DAY) if readonly else (-DAY, 30 * DAY, 44 * DAY)
    feats = {k: lst.fmt(now + timedelta(days=v)) for k, v in features.items() if v}
    claim = dict(gen.CLAIMS["valid"], seq=seq, issued_at=lst.fmt(now + issued),
                 valid_until=lst.fmt(now + valid), grace_until=lst.fmt(now + grace), features=feats)
    payload = gen.claim_bytes(claim)
    (d / "license.json").write_text(gen.envelope(payload, gen.sign(payload, _KEY[0]), kid="test"),
                                    encoding="utf-8")


def doctor_grant(g: tg.Google, agent: str = "DentPilot") -> gauth.Grant:
    """Врач вошёл своим Google с правом календаря врача: токены стенда."""
    verifier, chal = gauth.pkce()
    state, redirect = gauth.new_state(), gauth.loopback(51234, "/google/back/medic")
    url = gauth.consent_url(tg.CLIENT, redirect, state, chal, scopes=gauth.DOCTOR_SCOPES, prompt="consent",
                            auth_url=g.auth_url)
    b = gauth.back(g.consent(url), state)
    return gauth.exchange(tg.CLIENT, b.auth_code, verifier, redirect, token_url=g.token_url, agent=agent).grant


def appt(**kw) -> gwrite.Appt:
    base = dict(id=17, start=datetime(2027, 3, 1, 9, 0, tzinfo=t.TZ), minutes=30, room="Cab. 2",
                patient="Ștefan Țurcanu", file_no="0420", service="Detartraj")
    return gwrite.Appt(**{**base, **kw})


# ---------- чистота и вход ----------


def suite_pure(res: Result) -> None:
    if not res.ok("исходник провода записи нашёлся", GWRITE.is_file(), str(GWRITE)):
        return
    t.pure(res, GWRITE, WRITE_IMPORTS, set())
    res.check("коды исходов перечислены без повторов", len(set(gwrite.CODES)), len(gwrite.CODES))
    res.check("уровни — три, умолчание «doar ora»", (gwrite.LEVELS, gwrite.DEFAULT_LEVEL),
              (("time", "initials", "name"), "time"))
    res.check("право календаря врача — одно узкое", gauth.DOCTOR_SCOPES,
              ("https://www.googleapis.com/auth/calendar.app.created",))
    res.ok("права связи клиники не тронуты — только чтение", all(s.endswith(".readonly") for s in gauth.SCOPES)
           and gauth.APP_CREATED not in gauth.SCOPES, str(gauth.SCOPES))

    redirect = gauth.loopback(51234, "/google/back/medic")
    url = gauth.consent_url(tg.CLIENT, redirect, "st", "ch", scopes=gauth.DOCTOR_SCOPES, prompt="consent",
                            login_hint="medic@gmail.com")
    q = {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlsplit(url).query).items()}
    res.check("согласие врача: одно право, экран согласия каждый раз, подсказка аккаунта",
              (q.get("scope"), q.get("prompt"), q.get("login_hint")),
              (gauth.APP_CREATED, "consent", "medic@gmail.com"))
    plain = gauth.consent_url(tg.CLIENT, redirect, "st", "ch")
    res.ok("без prompt — параметра нет (связь клиники как была)", "prompt=" not in plain, plain)

    res.check("стенд: вне exe — адрес из переменной без хвостового /",
              gclient.stand_base_from(False, " http://127.0.0.1:5000/ "), "http://127.0.0.1:5000")
    res.check("стенд: в exe переменная не читается", gclient.stand_base_from(True, "http://127.0.0.1:5000"), "")
    res.check("стенд: та же переменная, что у связи клиники", gclient.STAND_ENV, "DENTART_GOOGLE_STAND")


# ---------- тело события ----------


def suite_body(res: Result) -> None:
    tag = gwrite.clinic_tag("c_0123456789ab")
    res.ok("метка клиники: 10 знаков base32hex, без самого id лицензии",
           len(tag) == 10 and all(c in gwrite.B32HEX for c in tag) and "0123456789ab" not in tag, tag)
    res.check("метка клиники детерминирована и своя у каждой клиники",
              (gwrite.clinic_tag("c_0123456789ab") == tag, gwrite.clinic_tag("c_0123456789ac") != tag), (True, True))
    eid = gwrite.event_id(tag, 1, 17, 0)
    res.ok("id события — только a–v и 0–9, читается однозначно", _ID.fullmatch(eid) is not None
           and eid == f"dp{tag}e1a17g0", eid)
    res.ok("новое поколение и новая эпоха — новый id",
           len({eid, gwrite.event_id(tag, 1, 17, 1), gwrite.event_id(tag, 2, 17, 0)}) == 3)
    bad = []
    for args in ((tag[:9], 1, 1, 0), (tag[:9] + "w", 1, 1, 0), (tag, -1, 1, 0), (tag, 1, True, 0), (tag, 1, 1, "0")):
        try:
            gwrite.event_id(*args)
            bad.append(args)
        except ValueError:
            pass
    res.check("id события: кривая метка или число — отказ", bad, [])

    a = appt()
    bodies = {lv: gwrite.event_body(lv, a, tag=tag, event_id=eid, note="Modificările — doar în DentPilot")
              for lv in gwrite.LEVELS}
    res.ok("ключи тела — ровно белый список", all(tuple(b) == gwrite.EVENT_KEYS for b in bodies.values()),
           str([list(b) for b in bodies.values()]))
    res.check("заголовок по уровню", {lv: b["summary"] for lv, b in bodies.items()},
              {"time": "Programare · Cab. 2", "initials": "Ș.Ț. · Fișa 0420 · Cab. 2",
               "name": "Ștefan Țurcanu · Detartraj · Cab. 2"})
    plain = json.dumps(bodies["time"], ensure_ascii=False)
    res.ok("«doar ora»: ни имени, ни букв, ни фиши, ни услуги",
           not any(x in plain for x in ("Ștefan", "Țurcanu", "Ș.Ț.", "0420", "Detartraj")), plain)
    inits = json.dumps(bodies["initials"], ensure_ascii=False)
    res.ok("«inițiale»: буквы и фиша, без имени и услуги",
           "Ș.Ț." in inits and "0420" in inits and not any(x in inits for x in ("Ștefan", "Țurcanu", "Detartraj")), inits)
    b = bodies["name"]
    res.check("время — UTC с поясом клиники, конец по минутам",
              (b["start"], b["end"]), ({"dateTime": "2027-03-01T07:00:00Z", "timeZone": "Europe/Chisinau"},
                                       {"dateTime": "2027-03-01T07:30:00Z", "timeZone": "Europe/Chisinau"}))
    res.check("без напоминаний, занято, только владельцу, подтверждено",
              (b["reminders"], b["transparency"], b["visibility"], b["status"]),
              ({"useDefault": False}, "opaque", "private", "confirmed"))
    res.check("частные свойства — только метка клиники и id записи", b["extendedProperties"],
              {"private": {"dp": tag, "dp_appt": "17"}})
    res.check("описание — переданная строка", b["description"], "Modificările — doar în DentPilot")
    summer = gwrite.event_body("time", appt(start=datetime(2027, 7, 1, 9, 0, tzinfo=t.TZ)), tag=tag,
                               event_id=eid, note="")
    res.check("летом сдвиг другой — 09:00 по Кишинёву = 06:00 UTC", summer["start"]["dateTime"],
              "2027-07-01T06:00:00Z")
    bare = gwrite.event_body("initials", appt(patient="", file_no="", room=""), tag=tag, event_id=eid, note="")
    res.check("пустые поля не оставляют разделителей", bare["summary"], "Programare")

    bad = []
    for fn in (lambda: gwrite.event_body("full", a, tag=tag, event_id=eid, note=""),
               lambda: gwrite.event_body("time", appt(start=datetime(2027, 3, 1, 9)), tag=tag, event_id=eid, note=""),
               lambda: gwrite.event_body("time", appt(minutes=0), tag=tag, event_id=eid, note="")):
        try:
            fn()
            bad.append(fn)
        except ValueError:
            pass
    res.check("незнакомый уровень, момент без пояса, нулевая длина — отказ", len(bad), 0)

    s1 = gwrite.body_stamp(bodies["name"])
    other_gen = gwrite.event_body("name", a, tag=tag, event_id=gwrite.event_id(tag, 2, 17, 3), note=b["description"])
    res.check("отпечаток не зависит от id: новое поколение без правки — ноль запросов",
              gwrite.body_stamp(other_gen), s1)
    moved = gwrite.event_body("name", appt(start=datetime(2027, 3, 1, 9, 15, tzinfo=t.TZ)), tag=tag, event_id=eid,
                              note=b["description"])
    res.ok("отпечаток: перенос времени и смена уровня — другой",
           gwrite.body_stamp(moved) != s1 and gwrite.body_stamp(bodies["time"]) != s1)
    renamed = gwrite.event_body("time", appt(patient="Alt Nume", file_no="9"), tag=tag, event_id=eid,
                                note=b["description"])
    res.check("«doar ora»: правка имени пациента отпечаток не меняет", gwrite.body_stamp(renamed),
              gwrite.body_stamp(bodies["time"]))
    res.ok("отпечаток — 16 hex", re.fullmatch(r"[0-9a-f]{16}", s1) is not None, s1)

    res.check("имя календаря врача", gwrite.calendar_summary(" Clinica  Zâmbet ", "Dr. Ion Rusu"),
              "DentPilot · Clinica Zâmbet · Dr. Ion Rusu")
    desc = gwrite.calendar_description("k7q2m9v4", "Programările dr. Rusu din DentPilot.")
    res.check("метка связи — последней строкой описания, читается обратно",
              (desc.splitlines()[-1], gwrite.mark_of(desc)), ("Actualizat de DentPilot · k7q2m9v4", "k7q2m9v4"))
    res.check("описание без метки или с чужим текстом — метки нет",
              [gwrite.mark_of(x) for x in ("", "Calendar", "Actualizat de DentPilot · k7q2m9v4 și altceva")],
              ["", "", ""])
    bad = []
    for m in ("k7q2m9v", "k7q2m9vw", "K7Q2M9V4"):
        try:
            gwrite.calendar_description(m)
            bad.append(m)
        except ValueError:
            pass
    res.check("метка связи: 8 знаков base32hex, иначе отказ", bad, [])


# ---------- календарь и события на стенде ----------


def suite_write(res: Result) -> None:
    g = tg.Google()
    cals = Calendars(g)
    try:
        grant = doctor_grant(g)
        res.ok("врач вошёл: refresh-токен и право календаря врача",
               bool(grant.refresh) and grant.scopes == frozenset(gauth.DOCTOR_SCOPES), str(grant))
        tok, api = grant.access, g.api
        desc = gwrite.calendar_description("k7q2m9v4", "Programările — doar în DentPilot")
        r = gwrite.calendar_insert(tok, "DentPilot · Clinica · Dr. Ștefan Țurcanu", desc, base=api)
        cid = (r.data or {}).get("id", "")
        res.check("календарь создан: id, имя с диакритикой целиком, пояс клиники, владелец",
                  (r.code, (r.data or {}).get("summary"), (r.data or {}).get("timeZone"), (r.data or {}).get("dataOwner")),
                  (gwrite.OK, "DentPilot · Clinica · Dr. Ștefan Țurcanu", "Europe/Chisinau", OWNER))
        req = g.requests[-1]
        res.check("запрос: POST JSON в UTF-8, Bearer, без лишних полей",
                  (req["method"], req["type"], req["auth"], sorted(req["json"])),
                  ("POST", "application/json; charset=utf-8", f"Bearer {tok}", ["description", "summary", "timeZone"]))
        res.check("отобраны только нужные поля календаря", sorted(r.data), sorted(gwrite.CALENDAR_KEYS))
        r = gwrite.calendar_get(tok, cid, base=api)
        res.check("календарь по id; метка в описании", (r.code, gwrite.mark_of(r.data["description"])),
                  (gwrite.OK, "k7q2m9v4"))
        r = gwrite.calendar_patch(tok, cid, summary="DentPilot · Clinica · Dr. Rusu", base=api)
        res.check("переименование — только имя, описание на месте",
                  (r.code, cals.cals[cid]["summary"], cals.cals[cid]["description"], sorted(g.requests[-1]["json"])),
                  (gwrite.OK, "DentPilot · Clinica · Dr. Rusu", desc, ["summary"]))
        try:
            gwrite.calendar_patch(tok, cid, base=api)
            res.ok("пустая правка календаря — отказ вызова", False)
        except ValueError:
            res.ok("пустая правка календаря — отказ вызова", True)

        tag = gwrite.clinic_tag("c_0123456789ab")
        e1 = gwrite.event_id(tag, 1, 17, 0)
        body = gwrite.event_body("name", appt(), tag=tag, event_id=e1, note="n")
        r = gwrite.event_insert(tok, cid, body, base=api)
        res.check("вставка своим id", (r.code, r.data), (gwrite.OK, {"id": e1, "status": "confirmed"}))
        res.check("в Google пришло ровно тело белого списка, с диакритикой",
                  (sorted(cals.events[cid][e1]), cals.events[cid][e1]["summary"]),
                  (sorted(gwrite.EVENT_KEYS), "Ștefan Țurcanu · Detartraj · Cab. 2"))
        res.check("ответ вставки — только id и статус", g.requests[-1]["query"].get("fields"), gwrite.EVENT_FIELDS)
        res.check("та же вставка ещё раз — duplicate (ответ потерялся → update)",
                  gwrite.event_insert(tok, cid, body, base=api).code, gwrite.DUPLICATE)
        moved = gwrite.event_body("name", appt(start=datetime(2027, 3, 1, 10, 0, tzinfo=t.TZ)), tag=tag,
                                  event_id=e1, note="n")
        r = gwrite.event_update(tok, cid, e1, moved, base=api)
        res.check("обновление полным телом (PUT)", (r.code, g.requests[-1]["method"],
                                                     cals.events[cid][e1]["start"]["dateTime"]),
                  (gwrite.OK, "PUT", "2027-03-01T08:00:00Z"))
        res.check("удаление", gwrite.event_delete(tok, cid, e1, base=api).code, gwrite.OK)
        res.check("удалённое лежит «надгробием»", cals.events[cid][e1]["status"], "cancelled")
        res.check("удаление ещё раз — gone (успех)", gwrite.event_delete(tok, cid, e1, base=api).code, gwrite.GONE)
        res.check("вставить «надгробие» тем же id — duplicate", gwrite.event_insert(tok, cid, body, base=api).code,
                  gwrite.DUPLICATE)
        r = gwrite.event_update(tok, cid, e1, body, base=api)
        res.check("update «надгробия» со status confirmed — событие воскресло",
                  (r.code, cals.events[cid][e1]["status"]), (gwrite.OK, "confirmed"))
        gwrite.event_delete(tok, cid, e1, base=api)
        cals.purge(cid, e1)
        res.check("«надгробие» исчезло: update — not_found (вставлять с новым поколением)",
                  gwrite.event_update(tok, cid, e1, body, base=api).code, gwrite.NOT_FOUND)
        res.check("удалить несуществующее — not_found (тоже «нет события»)",
                  gwrite.event_delete(tok, cid, gwrite.event_id(tag, 1, 99, 0), base=api).code, gwrite.NOT_FOUND)

        other = gwrite.clinic_tag("c_ffffffffffff")
        for i in range(1, 8):
            gwrite.event_insert(tok, cid, gwrite.event_body("time", appt(id=100 + i), tag=tag,
                                                            event_id=gwrite.event_id(tag, 1, 100 + i, 0), note=""),
                                base=api)
        gwrite.event_insert(tok, cid, gwrite.event_body("time", appt(id=500), tag=other,
                                                        event_id=gwrite.event_id(other, 1, 500, 0), note=""), base=api)
        gwrite.event_delete(tok, cid, gwrite.event_id(tag, 1, 107, 0), base=api)
        cals.page = 3
        g.requests.clear()
        r = gwrite.events_ours(tok, cid, tag, base=api)
        res.check("наши события: все страницы, только своя метка, без удалённых",
                  (r.code, sorted(x["appt"] for x in r.items)), (gwrite.OK, [101, 102, 103, 104, 105, 106]))
        q = g.requests[0]["query"]
        res.check("наши события: отбор по метке, поля отобраны",
                  (q.get("privateExtendedProperty"), q.get("fields"), q.get("showDeleted")),
                  (f"dp={tag}", gwrite.OURS_FIELDS, None))
        res.check("страница за страницей", [x["query"].get("pageToken") for x in g.requests], [None, "p3"])
        r = gwrite.events_ours(tok, cid, tag, show_deleted=True, base=api)
        res.check("с удалёнными — и «надгробия»",
                  sorted((x["appt"], x["status"]) for x in r.items if x["status"] == "cancelled"),
                  [(107, "cancelled")])
        first = {"done": False}
        real = cals.handle

        def second_fails(method, path, query, body, scopes):
            if method == "GET" and path.endswith("/events") and query.get("pageToken"):
                return 503, {"error": {"code": 503, "status": "UNAVAILABLE"}}
            first["done"] = True
            return real(method, path, query, body, scopes)
        g.write = second_fails
        r = gwrite.events_ours(tok, cid, tag, base=api)
        res.check("сбой второй страницы — отказ всего набора", (r.code, r.items, first["done"]),
                  (gwrite.OFFLINE, (), True))

        def looping(method, path, query, body, scopes):
            return 200, {"items": [], "nextPageToken": "same"}
        g.write = looping
        r = gwrite.events_ours(tok, cid, tag, base=api)
        res.check("страница по кругу — отказ, а не вечный проход", (r.code, r.reason), (gwrite.OFFLINE, "page_loop"))
        g.write = real

        res.check("календарь удалён", gwrite.calendar_delete(tok, cid, base=api).code, gwrite.OK)
        res.check("календаря нет — not_found у чтения, вставки и удаления",
                  [gwrite.calendar_get(tok, cid, base=api).code, gwrite.event_insert(tok, cid, body, base=api).code,
                   gwrite.calendar_delete(tok, cid, base=api).code], [gwrite.NOT_FOUND] * 3)

        g.access["ro"] = frozenset(gauth.SCOPES)
        res.check("токен без права календаря врача — no_scope",
                  gwrite.calendar_insert("ro", "x", "", base=api).code, gwrite.NO_SCOPE)
        res.check("чужой токен — unauthorized", gwrite.calendar_insert("bad", "x", "", base=api).code,
                  gwrite.UNAUTHORIZED)

        r = gwrite.calendar_insert(tok, "DentPilot · B", "", base=api)
        cid = r.data["id"]
        replies = [
            (_err(403, "rateLimitExceeded", "usageLimits"), (gwrite.RATE_LIMITED, "rateLimitExceeded", 0)),
            (_err(403, "userRateLimitExceeded", "usageLimits"), (gwrite.RATE_LIMITED, "userRateLimitExceeded", 0)),
            (_err(403, "accessNotConfigured", "usageLimits"), (gwrite.FORBIDDEN, "accessNotConfigured", 0)),
            (_err(403, "forbidden"), (gwrite.FORBIDDEN, "forbidden", 0)),
            ((*_err(429, "rateLimitExceeded"), {"Retry-After": "30"}), (gwrite.RATE_LIMITED, "rateLimitExceeded", 30)),
            ((*_err(429, "rateLimitExceeded"), {"Retry-After": "86400"}), (gwrite.RATE_LIMITED, "rateLimitExceeded", 3600)),
            (_err(409, "duplicate"), (gwrite.DUPLICATE, "duplicate", 0)),
            (_err(410, "deleted"), (gwrite.GONE, "deleted", 0)),
            (_err(404, "notFound"), (gwrite.NOT_FOUND, "notFound", 0)),
            (_err(400, "invalid"), (gwrite.BAD_REQUEST, "invalid", 0)),
            ((500, {"error": {"code": 500, "status": "INTERNAL"}}), (gwrite.OFFLINE, "INTERNAL", 0)),
            ((200, b"<html>captive portal</html>"), (gwrite.OFFLINE, "bad_body", 0)),
            ((200, {"status": "confirmed"}), (gwrite.OFFLINE, "bad_body", 0)),
        ]
        got = []
        for reply, _ in replies:
            status, data, *hdr = reply
            cals.fail("POST", "/events", status, data, headers=hdr[0] if hdr else None)
            r = gwrite.event_insert(tok, cid, body, base=api)
            got.append((r.code, r.reason, r.retry_after))
        res.check("ответ Google → код исхода", got, [want for _, want in replies])

        g.requests.clear()
        r = gwrite.calendar_get(tok, cid, base=g.base + "/redir")
        res.ok("редиректу не следует — токен не уезжает", r.code == gwrite.OFFLINE
               and not any(x["path"] == "/trap" for x in g.requests), str(g.requests))
        res.check("сеть недоступна — offline",
                  gwrite.calendar_get(tok, cid, base=f"http://127.0.0.1:{tg.dead_port()}/calendar/v3").code,
                  gwrite.OFFLINE)
        try:
            gwrite.calendar_get(tok, cid, base="http://www.googleapis.com/calendar/v3")
            res.ok("адрес не https — отказ вызова", False)
        except ValueError:
            res.ok("адрес не https — отказ вызова", True)
        res.ok("id календаря с # и @ — одним сегментом пути",
               gwrite._seg("ro.md#holiday@group.v.calendar.google.com") == "ro.md%23holiday%40group.v.calendar.google.com")
    finally:
        g.close()
