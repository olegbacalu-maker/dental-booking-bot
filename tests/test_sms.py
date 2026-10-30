"""SMS-пакет в программе (S5): тексты, окно отправки, провод, живой цикл.

Контракт — docs/dentpilot-2/sms.md › «Программа (bot/)», «Шаблоны и
сегменты», «Порядок работ › S5». Сервер лицензий здесь подменён СТЕНДОМ в
процессе теста (http.server на loopback, как в test_license_renew): нужны
ответы, которых настоящий сервер по заказу не даёт, — «не сейчас», тишина,
«пакет не предлагается». Что настоящий сервер и этот провод понимают друг
друга — cloud/tests/test_sms_client.py: там провод грузится по пути.

Три набора: чистые модули (тексты — один сегмент, подстановки, окна часов,
настройки), провод (исходы по коду ответа, без редиректов, таймаут) и живой
сервер под поддельными часами (`harness.Clock`): кто получает SMS, когда,
без дубля, с летописью и колокольчиком; флаги Telegram не тронуты.

⭐ Пары, на которых набор был красным при разработке: без `created > start`
запись, сделанная после часа X, ждала бы следующего дня; без сверки
`appt_status` в очереди отменённый визит получал напоминание; `until_at` без
`<=` держал истёкшую строку в очереди вечно.
"""
import ast
import http.server
import importlib.util
import json
import pathlib
import re
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
from datetime import date, datetime, timedelta

from harness import (BOT, FIXTURES, ROOT, Client, Clock, Result, Server, TZ, _rmtree_settled,
                     add_appt, appt_id, day_model, new_patient, panel_live, pid_by_phone,
                     shell_model)
import test_license_renew as lr

FIX = ROOT / "tests" / "fixtures" / "license"
KEY_ENV = {"DENTART_LICENSE_KEYS": str(FIX / "test-key.json")}
WIRE = BOT / "app" / "core" / "sms.py"
PLAN = BOT / "app" / "core" / "sms_plan.py"
WIRE_IMPORTS = {"__future__", "http.client", "json", "urllib.error", "urllib.parse", "urllib.request"}
PLAN_IMPORTS = {"__future__", "re", "unicodedata", "datetime"}
TOKEN = "stand-sms-token-" + "y" * 28
TICK = {"DENTART_SMS_TICK_S": "0.3"}


def _load(name: str, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


wire = _load("sms_wire", WIRE)
plan = _load("sms_plan_pure", PLAN)
rule = _load("sms_rule_pure", BOT / "app" / "core" / "sms_rule.py")


def _pure(res: Result, label: str, path: pathlib.Path, allowed: set) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    res.check(f"{label}: импорты только из разрешённого списка", sorted(imported - allowed), [])
    res.ok(f"{label}: нет относительных импортов проекта",
           not any(isinstance(n, ast.ImportFrom) and n.level for n in ast.walk(tree)))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    res.ok(f"{label}: ни open, ни __file__, ни environ",
           not ({"open", "__file__"} & names or "environ" in attrs))


# ---------- чистые модули ----------

RO_NAME = "Centrul Stomatologic Zambet Nr"      # ровно 30 знаков — предел правила
RU_NAME = "Зымбет Дент+"                        # 12 знаков — предел для русского
PHONE = "+373 22 123 456"


def suite_plan(res: Result) -> None:
    """Готовые тексты — один сегмент; подстановки — белый список; окно отправки."""
    _pure(res, "провод", WIRE, WIRE_IMPORTS)
    _pure(res, "тексты и окно", PLAN, PLAN_IMPORTS)
    res.check("название клиники для правила — 30 знаков", len(RO_NAME), plan.NAME_MAX["ro"])
    res.check("русское название для правила — 12 знаков", len(RU_NAME), plan.NAME_MAX["ru"])
    # среда (miercuri) — самое длинное слово дня; день отправки за неделю до визита
    starts = datetime(2026, 11, 11, 12, 30, tzinfo=TZ)
    on_day = date(2026, 11, 4)
    for v in plan.VARIANTS:
        for line in (False, True):
            t = plan.text("ro", v, clinic=RO_NAME, phone=PHONE, phone_line=line, starts=starts, on_day=on_day)
            enc, units, segs = rule.parts(t)
            res.ok(f"RO «{v}»{' + telefon' if line else ''}: один сегмент GSM-7 с названием в 30 знаков",
                   enc == rule.GSM7 and segs == 1, f"{enc} {units} ед., {segs} сегм.: {t!r}")
            res.ok(f"RO «{v}»: клиника, день, дата и час на месте",
                   RO_NAME in t and "miercuri" in t and "11.11" in t and "12:30" in t, t)
            res.check(f"RO «{v}»: строка отмены {'есть' if line else 'нет'}",
                      t.endswith("\nAnulare: " + PHONE), line)
        t = plan.text("ru", v, clinic=RU_NAME, phone=PHONE, phone_line=False, starts=starts, on_day=on_day)
        enc, units, segs = rule.parts(t)
        res.ok(f"RU «{v}»: один сегмент UCS-2 с названием в 12 знаков",
               enc == rule.UCS2 and segs == 1, f"{enc} {units} ед., {segs} сегм.: {t!r}")
        res.ok(f"RU «{v}»: клиника, день, дата и час на месте",
               RU_NAME in t and "в среду" in t and "11.11" in t and "12:30" in t, t)
    # данные о здоровье в текст не попадают: подстановки — только белый список
    holes = set()
    for lang in plan.LANGS:
        for tpl in list(plan.TEXTS[lang].values()) + [plan.PHONE_LINE[lang]]:
            holes |= plan.placeholders(tpl)
    res.ok("подстановки готовых текстов — подмножество белого списка",
           holes <= set(plan.PLACEHOLDERS), f"лишние: {sorted(holes - set(plan.PLACEHOLDERS))}")
    res.ok("в белом списке нет врача, услуги и имени",
           not {"medic", "doctor", "serviciu", "nume", "pacient"} & set(plan.PLACEHOLDERS))
    # диакритика и типографика из названия клиники сворачиваются — иначе UCS-2
    t = plan.text("ro", plan.STANDARD, clinic="Zâmbet — „Dent”", phone="022–123", phone_line=True,
                  starts=starts, on_day=on_day)
    res.ok("название с диакритикой и тире — текст остаётся GSM-7",
           rule.parts(t)[0] == rule.GSM7 and 'Zambet - "Dent"' in t, t)
    res.check("fold: ă â î ș ț и кавычки", plan.fold("Ștefan Țărână „x” ’y’ — z"), "Stefan Tarana \"x\" 'y' - z")
    # слово дня — от дня ОТПРАВКИ
    res.check("день: сегодня", plan.day_word("ro", date(2026, 11, 9), date(2026, 11, 9)), "astazi")
    res.check("день: завтра", plan.day_word("ro", date(2026, 11, 7), date(2026, 11, 6)), "maine")
    res.check("день: понедельник при отправке в пятницу", plan.day_word("ro", date(2026, 11, 9), date(2026, 11, 6)), "luni")
    res.check("день RU: в субботу", plan.day_word("ru", date(2026, 11, 7), date(2026, 11, 5)), "в субботу")
    # личный текст клиники — по белому списку и с обязательными подстановками
    res.ok("личный текст: годен с клиникой, датой и часом",
           plan.custom_ok("Clinica {clinica}: {ziua} {data} {ora}") and plan.custom_ok("{clinica} {data} {ora}"))
    res.ok("личный текст: врач, пустота, не строка — негодны",
           not plan.custom_ok("Dr {medic} {clinica} {data} {ora}") and not plan.custom_ok("")
           and not plan.custom_ok(None) and not plan.custom_ok("{clinica} {ziua}"))
    t = plan.text("ro", plan.CUSTOM, clinic="Dentpro", phone="", phone_line=True, starts=starts, on_day=on_day,
                  custom={"ro": "{clinica}: {ziua} {data} la {ora}"})
    res.check("личный текст подставляется, строки отмены у него нет", t, "Clinica Dentpro: miercuri 11.11 la 12:30")
    res.check("подпись клиники: слово добавляется, когда его нет в названии",
              [plan.clinic_label(n, "ro") for n in ("Dentpro", "Clinica Test", "Clinică Dr. Pop", "Dental Clinic", "")],
              ["Clinica Dentpro", "Clinica Test", "Clinică Dr. Pop", "Dental Clinic", ""])
    res.check("подпись клиники RU", plan.clinic_label("Zâmbet", "ru"), "Клиника Zâmbet")
    t = plan.text("ro", plan.CUSTOM, clinic="Dentpro", phone="", phone_line=False, starts=starts, on_day=on_day)
    res.ok("выбран личный, а его нет — стандартный", t.startswith("Buna ziua! Clinica Dentpro"), t)
    res.ok("незнакомый вариант — стандартный",
           plan.text("ro", "xyz", clinic="D", phone="", phone_line=False, starts=starts, on_day=on_day)
           == plan.text("ro", plan.STANDARD, clinic="D", phone="", phone_line=False, starts=starts, on_day=on_day))
    res.check("подстановка одним проходом: скобки в названии не разбираются второй раз",
              plan.render("{clinica} {ora}", {"clinica": "A {ora} B", "ora": "9:00"}), "A {ora} B 9:00")
    res.check("ключ повтора", plan.idem(7, "day_before", "2026-11-09T10:00:00Z"),
              "appt:7:day_before:2026-11-09T10:00:00Z")

    # ---- настройки ----
    s = plan.settings(None)
    res.check("умолчания: накануне в 10:00 включено, в день визита выключено, без телефона",
              (s["day_before"], s["same_day"], s["phone_line"]),
              ({"on": True, "hour": 10, "variant": "standard"}, {"on": False, "hours": 2, "variant": "standard"}, False))
    s = plan.settings({"day_before": {"on": False, "hour": 25, "variant": "cald"},
                       "same_day": {"on": True, "hours": True, "variant": "nope"}, "phone_line": 1})
    res.check("кривые значения — умолчания, годные — как есть",
              (s["day_before"], s["same_day"], s["phone_line"]),
              ({"on": False, "hour": 10, "variant": "cald"}, {"on": True, "hours": 2, "variant": "standard"}, True))
    res.ok("any_on", plan.any_on(plan.settings(None)) and not plan.any_on(
        plan.settings({"day_before": {"on": False}})))

    # ---- окно отправки (часы клиники; выходные — сб, вс) ----
    open_ = lambda d: d.weekday() < 5           # noqa: E731
    fri, mon = date(2026, 11, 6), date(2026, 11, 9)
    at = lambda d, h, m=0: datetime(d.year, d.month, d.day, h, m, tzinfo=TZ)   # noqa: E731
    w = plan.window(plan.DAY_BEFORE, at(mon, 8), at(fri, 9), hour=10, is_open=open_)
    res.check("накануне: визит в понедельник 08:00 — пятница с 10:00 до 21:00", w, (at(fri, 10), at(fri, 21)))
    w = plan.window(plan.DAY_BEFORE, at(mon, 12), at(fri, 15), hour=10, is_open=open_)
    res.check("накануне: записан в пятницу в 15:00 — сразу, до 21:00", w, (at(fri, 15), at(fri, 21)))
    res.check("накануне: записан в пятницу в 21:30 — окна нет",
              plan.window(plan.DAY_BEFORE, at(mon, 12), at(fri, 21, 30), hour=10, is_open=open_), None)
    res.check("накануне: записан в день визита — окна нет",
              plan.window(plan.DAY_BEFORE, at(mon, 12), at(mon, 8), hour=10, is_open=open_), None)
    res.check("накануне: клиника без выходных — предыдущий день",
              plan.window(plan.DAY_BEFORE, at(mon, 12), at(fri, 9), hour=9), (at(date(2026, 11, 8), 9), at(date(2026, 11, 8), 21)))
    res.check("накануне: час X 20 — окно 20:00–21:00",
              plan.window(plan.DAY_BEFORE, at(mon, 12), at(fri, 9), hour=20, is_open=open_), (at(fri, 20), at(fri, 21)))
    w = plan.window(plan.SAME_DAY, at(mon, 12), at(fri, 9), hours=2)
    res.check("в день визита: за 2 часа, до получаса перед началом", w, (at(mon, 10), at(mon, 11, 30)))
    res.check("в день визита: 09:00 — за 2 часа попадает до 08:00 → в 08:00 (до визита ≥ 1 ч)",
              plan.window(plan.SAME_DAY, at(mon, 9), at(fri, 9), hours=2), (at(mon, 8), at(mon, 8, 30)))
    res.check("в день визита: 08:30 — до визита меньше часа от 08:00 → не слать",
              plan.window(plan.SAME_DAY, at(mon, 8, 30), at(fri, 9), hours=2), None)
    res.check("в день визита: запись меньше чем за 2 часа — не слать",
              plan.window(plan.SAME_DAY, at(mon, 12), at(mon, 10, 30), hours=2), None)
    res.check("в день визита: запись ровно за 2 часа — слать сразу",
              plan.window(plan.SAME_DAY, at(mon, 12), at(mon, 10), hours=2), (at(mon, 10), at(mon, 11, 30)))
    res.check("в день визита: визит в 21:30 — окно до 21:00",
              plan.window(plan.SAME_DAY, at(mon, 21, 30), at(fri, 9), hours=1), (at(mon, 20, 30), at(mon, 21)))
    res.check("в день визита: за 3 часа", plan.window(plan.SAME_DAY, at(mon, 14), at(fri, 9), hours=3),
              (at(mon, 11), at(mon, 13, 30)))
    res.check("неизвестное событие — окна нет", plan.window("xyz", at(mon, 14), at(fri, 9)), None)
    res.ok("тихие часы: 07:59 и 21:00 — нет, 08:00 и 20:59 — да",
           not plan.awake(at(mon, 7, 59)) and not plan.awake(at(mon, 21)) and plan.awake(at(mon, 8))
           and plan.awake(at(mon, 20, 59)))
    res.check("последний рабочий день перед визитом: отпуск две недели — всё равно вчера",
              plan.send_day(mon, lambda d: False), date(2026, 11, 8))


# ---------- стенд сервера лицензий с SMS ----------


class Stand:
    """Сервер лицензий: /v1/license (204 — файл не трогаем) и /v1/sms/*.

    `account` — что отвечает счёт; `account_reply` — отказ вместо него;
    `send_mode` — ok | retry_once | down; сообщения помнит по ключу повтора,
    как настоящий сервер: повтор с тем же ключом получает тот же id.
    `states` — состояния по id для /v1/sms/status. `delay` — секунды сна на
    /v1/sms/account (старт программы не должен его ждать)."""

    def __init__(self):
        self.account = {"offered": True, "enabled": True, "sender": "", "sender_state": "none",
                        "sender_note": "", "sender_until": None, "sender_prepaid": 0, "from": "DentPilot",
                        "balance": 100, "packs": [], "name_price": 0, "name_days": 365,
                        "daily_cap": 500, "used_today": 0, "blocked": "", "custom": {}}
        self.account_reply: tuple[int, dict] | None = None
        self.send_mode = "ok"
        self.delay = 0.0
        self.states: dict[int, str] = {}
        self.requests: list[dict] = []       # все, по порядку
        self.sends: list[dict] = []          # только /v1/sms/send
        self._by_idem: dict[str, int] = {}
        self._retried: set[str] = set()
        self._lock = threading.Lock()
        stand = self

        class H(http.server.BaseHTTPRequestHandler):
            def _reply(self, status: int, data: dict | None) -> None:
                body = json.dumps(data).encode("utf-8") if data is not None else b""
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                if status != 204:
                    self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if status != 204:
                    self.wfile.write(body)

            def do_GET(self):
                stand.requests.append({"path": self.path, "auth": self.headers.get("Authorization", ""),
                                       "agent": self.headers.get("User-Agent", "")})
                if self.path.startswith("/v1/license"):
                    self._reply(204, None)
                    return
                if self.path == "/v1/sms/account":
                    if stand.delay:
                        time.sleep(stand.delay)
                    if stand.account_reply is not None:
                        self._reply(*stand.account_reply)
                    else:
                        self._reply(200, {"ok": True, **stand.account})
                    return
                if self.path == "/redir":
                    self.send_response(302)
                    self.send_header("Location", stand.base + "/trap")
                    self.end_headers()
                    return
                self._reply(404, {"ok": False})

            def do_POST(self):
                raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                try:
                    sent = json.loads(raw.decode("utf-8"))
                except ValueError:
                    sent = None
                rec = {"path": self.path, "json": sent, "auth": self.headers.get("Authorization", ""),
                       "agent": self.headers.get("User-Agent", "")}
                stand.requests.append(rec)
                if (self.path in ("/v1/sms/send", "/v1/sms/sender", "/v1/sms/order")
                        and stand.account_reply is not None and stand.account_reply[0] >= 400):
                    self._reply(*stand.account_reply)      # пакет не предложен — как у настоящего сервера
                    return
                if self.path == "/v1/sms/send":
                    stand.sends.append(rec)
                    self._send(sent or {})
                elif self.path == "/v1/sms/status":
                    ids = (sent or {}).get("ids") or []
                    self._reply(200, {"ok": True, "items": [
                        {"id": i, "state": stand.states.get(i, "queued"), "error": ""} for i in ids]})
                elif self.path == "/v1/sms/sender":
                    stand.account["sender"] = str((sent or {}).get("name") or "")
                    stand.account["sender_state"] = "requested"
                    self._reply(200, {"ok": True, **stand.account})
                elif self.path == "/v1/sms/order":
                    name = bool((sent or {}).get("name"))
                    self._reply(200, {"ok": True, "kind": "sms_name" if name else "sms", "reference": "DP-77",
                                      "amount": 200 if name else 150, "units": None if name else int((sent or {}).get("pack") or 0),
                                      "pay_url": stand.base + "/plata/x", "created": True})
                else:
                    self._reply(404, {"ok": False})

            def _send(self, body: dict) -> None:
                idem = str(body.get("idem") or "")
                mode = stand.send_mode
                if mode == "down":
                    self._reply(500, None)
                    return
                if mode == "balance":
                    self._reply(402, {"ok": False, "code": "sms_balance", "text": "Pachetul SMS s-a terminat"})
                    return
                if mode == "retry_once" and idem not in stand._retried:
                    stand._retried.add(idem)
                    self._reply(503, {"ok": False, "code": "sms_retry", "text": "Operatorul SMS nu a răspuns"})
                    return
                with stand._lock:
                    if idem not in stand._by_idem:
                        stand._by_idem[idem] = len(stand._by_idem) + 1
                        stand.account["balance"] -= 1
                    mid = stand._by_idem[idem]
                self._reply(200, {"ok": True, "id": mid, "segments": 1, "state": "queued",
                                  "balance": stand.account["balance"]})

            def log_message(self, *a):
                pass

        self.srv = lr._Quiet(("127.0.0.1", 0), H)
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"
        self.url = self.base + "/v1/license"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.srv.shutdown()
        self.srv.server_close()


# ---------- провод ----------


def suite_wire(res: Result) -> None:
    """core/sms.py: исход по коду ответа, заголовки, без редиректов, таймаут."""
    res.check("base_of: /v1/sms/ у того же сервера", wire.base_of("https://cloud.dentpilot.md/v1/license"),
              "https://cloud.dentpilot.md/v1/sms/")
    res.check("base_of: мусор — пусто", wire.base_of("not a url"), "")
    stand = Stand()
    base = stand.base + "/v1/sms/"
    try:
        out, body = wire.account(base, TOKEN, timeout=5, agent="DentPilot/9.9", extra={"X-DentPilot-Device": "d_1"})
        res.ok("account: 200 — OK и тело счёта", out == wire.OK and body.get("balance") == 100, repr((out, body)))
        req = stand.requests[-1]
        res.ok("запрос: Bearer, User-Agent, личность машины",
               req["auth"] == f"Bearer {TOKEN}" and req["agent"] == "DentPilot/9.9", repr(req))
        out, body = wire.send(base, TOKEN, "69000111", "Text", "day_before", "appt:1:day_before:x", timeout=5)
        res.ok("send: 200 — OK с id и остатком", out == wire.OK and body.get("id") == 1 and body.get("balance") == 99,
               repr((out, body)))
        res.check("send: тело запроса — номер, текст, вид, ключ", stand.sends[-1]["json"],
                  {"to": "69000111", "text": "Text", "kind": "day_before", "idem": "appt:1:day_before:x"})
        out, body = wire.send(base, TOKEN, "69000111", "Text", "day_before", "appt:1:day_before:x", timeout=5)
        res.ok("send: повтор ключа — тот же id, остаток не списан", out == wire.OK and body.get("id") == 1
               and body.get("balance") == 99, repr(body))
        out, body = wire.status(base, TOKEN, [1, 2], timeout=5)
        res.ok("status: items по id", out == wire.OK and [i["id"] for i in body["items"]] == [1, 2], repr(body))
        stand.send_mode = "balance"
        out, body = wire.send(base, TOKEN, "69000111", "Text", "day_before", "appt:2:day_before:x", timeout=5)
        res.ok("402 sms_balance — DENIED с кодом", out == wire.DENIED and body.get("code") == "sms_balance", repr((out, body)))
        stand.send_mode = "ok"
        stand.account_reply = (503, {"ok": False, "code": "sms_not_offered", "text": "nu"})
        out, body = wire.account(base, TOKEN, timeout=5)
        res.ok("503 sms_not_offered — DENIED, не OFFLINE", out == wire.DENIED and body.get("code") == "sms_not_offered",
               repr((out, body)))
        stand.account_reply = (401, {"ok": False, "code": "token_unknown"})
        res.check("401 token_unknown — REFUSED", wire.account(base, TOKEN, timeout=5), (wire.REFUSED, {}))
        stand.account_reply = (403, {})
        res.check("403 без кода — REFUSED", wire.account(base, TOKEN, timeout=5), (wire.REFUSED, {}))
        stand.account_reply = (500, {"ok": False})
        res.check("500 — OFFLINE", wire.account(base, TOKEN, timeout=5), (wire.OFFLINE, {}))
        stand.account_reply = (200, {"ok": False, "code": "x"})
        res.check("200 без ok — OFFLINE (чужой ответ)", wire.account(base, TOKEN, timeout=5), (wire.OFFLINE, {}))
        stand.account_reply = None
        n = len(stand.requests)
        res.check("редирект — OFFLINE", wire._call(stand.base + "/", "redir", TOKEN, None, 5, "DentPilot", None),
                  (wire.OFFLINE, {}))
        res.ok("за редиректом клиент не идёт: токен не уезжает на чужой адрес",
               len(stand.requests) == n + 1 and not any(r["path"].endswith("/trap") for r in stand.requests))
        stand.delay = 3.0
        t0 = time.time()
        got = wire.account(base, TOKEN, timeout=1.0)
        res.ok("таймаут — OFFLINE раньше, чем ответил бы стенд", got == (wire.OFFLINE, {}) and time.time() - t0 < 2.5,
               f"{got} за {time.time() - t0:.1f} с")
        stand.delay = 0
    finally:
        stand.close()
    res.check("порт закрыт — OFFLINE", wire.account(base, TOKEN, timeout=5), (wire.OFFLINE, {}))


# ---------- живой сервер ----------


def _db(d: pathlib.Path) -> sqlite3.Connection:
    con = sqlite3.connect(str(d / "dental.db"), timeout=5)
    con.row_factory = sqlite3.Row
    return con


def _rows(d: pathlib.Path, sql: str, *args) -> list[dict]:
    con = _db(d)
    try:
        return [dict(r) for r in con.execute(sql, args)]
    finally:
        con.close()


def _sms_log(d: pathlib.Path) -> list[dict]:
    return _rows(d, "SELECT * FROM sms_log ORDER BY id")


def _events(d: pathlib.Path, pid: int) -> list[str]:
    return [r["text"] for r in _rows(d, "SELECT text FROM activity WHERE patient_id = ? AND kind LIKE 'sms%' "
                                        "ORDER BY id", pid)]


def _wait(cond, timeout: float = 12.0, every: float = 0.2):
    deadline = time.time() + timeout
    while time.time() < deadline:
        got = cond()
        if got:
            return got
        time.sleep(every)
    return cond()


def _clinic_weekdays(d: pathlib.Path, sms: dict | None = None) -> None:
    """clinic_test.json с выходными сб и вс — иначе «последний рабочий день» = вчера."""
    cfg = json.loads((FIXTURES / "clinic_test.json").read_text(encoding="utf-8"))
    cfg["hours"]["sat"] = None
    cfg["hours"]["sun"] = None
    if sms is not None:
        cfg["sms"] = sms
    (d / "clinic.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")


def _at(y, m, dd, h, mi=0, s=0) -> datetime:
    return datetime(y, m, dd, h, mi, s, tzinfo=TZ)


def _log(s: Server) -> str:
    return s.log_text()


def suite_live(res: Result) -> None:
    """Накануне в час X, кому нет, без дубля, перенос, повтор, тишина, истечение,
    доставка, летопись, колокольчик; затем «в день визита»; затем «не предлагается»."""
    stand = Stand()
    renew = {"url": stand.url, "token": TOKEN}
    d = pathlib.Path(tempfile.mkdtemp(prefix="dp_sms_"))
    env = {**KEY_ENV, **TICK}
    fri, mon = (2026, 11, 6), (2026, 11, 9)         # пятница и понедельник, зимнее время (+2)
    try:
        _clinic_weekdays(d)
        (d / "license.json").write_text(lr._file(5, renew), encoding="utf-8")
        stand.delay = 3.0
        with Clock(_at(*fri, 9, 0)) as clock:
            with Server(dir_=d, env=env) as s:
                c = Client(s.url).login()
                t0 = time.time()
                res.ok("старт не ждёт сервер SMS: журнал отвечает, пока стенд молчит",
                       c.get("/admin").status == 200 and time.time() - t0 < 2.5)
                stand.delay = 0
                # кому: A — да; B — sms_off; C — архив; D — 77…; E — без телефона; F — визит сегодня
                r = add_appt(c, "2026-11-09", "12:00", "Sms Alfa", "069000111")
                res.check("визит A записан", r.msg, "ok")
                add_appt(c, "2026-11-09", "13:00", "Sms Beta", "069000222", doctor="d3")
                add_appt(c, "2026-11-09", "14:00", "Sms Gamma", "069000333", doctor="d4")
                add_appt(c, "2026-11-09", "15:00", "Sms Delta", "077000444", doctor="d3")
                r = add_appt(c, "2026-11-09", "16:00", "Sms Epsilon", "", doctor="d4", nophone=True)
                res.check("визит без телефона записан", r.msg, "ok")
                add_appt(c, "2026-11-06", "15:00", "Sms Zeta", "069000666", doctor="d3")
                a_id = appt_id(c, "2026-11-09", "Sms Alfa")
                a_pid, b_pid, c_pid = (pid_by_phone(c, p) for p in ("069000111", "069000222", "069000333"))
                con = _db(d)
                con.execute("UPDATE patients SET sms_off = 1 WHERE id = ?", (b_pid,))
                con.commit()
                con.close()
                res.check("C в архив", c.post_json(f"/api/patients/{c_pid}/archive", {"on": True}).msg, "ok_arh")
                time.sleep(1.5)
                res.ok("счёт спрошен у сервера при старте",
                       any(r["path"] == "/v1/sms/account" and r["auth"] == f"Bearer {TOKEN}" for r in stand.requests),
                       repr(stand.requests[:3]))
                res.ok("до часа X ничего не ушло и в очереди пусто", stand.sends == [] and _sms_log(d) == [],
                       repr(_sms_log(d)))

                # час X: 10:00 — только A
                clock.set(_at(*fri, 10, 0, 30))
                got = _wait(lambda: len(stand.sends) >= 1)
                res.ok("в 10:00 пятницы ушла SMS накануне", got, repr(stand.sends))
                time.sleep(1.2)
                res.check("ушла ровно одна: sms_off, архив, 77…, без телефона, визит сегодня — мимо",
                          len(stand.sends), 1)
                body = stand.sends[0]["json"] if stand.sends else {}
                res.ok("кому и что: номер A, вид day_before, ключ appt:{id}:day_before:{starts_at}",
                       body.get("to") == "69000111" and body.get("kind") == "day_before"
                       and body.get("idem") == f"appt:{a_id}:day_before:2026-11-09T10:00:00Z", repr(body))
                res.ok("текст: клиника, «luni, 09.11», «12:00», без диакритики, один сегмент",
                       "Clinica Test" in body.get("text", "") and "luni, 09.11" in body.get("text", "")
                       and "12:00" in body.get("text", "") and rule.parts(body.get("text", ""))[2] == 1
                       and rule.parts(body.get("text", ""))[0] == rule.GSM7, repr(body.get("text")))
                res.ok("запрос несёт Bearer из файла и DentPilot в User-Agent",
                       stand.sends[0]["auth"] == f"Bearer {TOKEN}" and stand.sends[0]["agent"].startswith("DentPilot/"))
                rows = _wait(lambda: [r for r in _sms_log(d) if r["state"] == "sent"])
                res.ok("строка sms_log: sent, id сервера, сегменты", rows and rows[0]["cloud_id"] == 1
                       and rows[0]["segments"] == 1 and rows[0]["appt_id"] == a_id, repr(rows))
                res.ok("летопись A: «SMS trimis (cu o zi înainte) — vizita 09.11.2026 12:00»",
                       _wait(lambda: any(t.startswith("SMS trimis (cu o zi înainte) — vizita 09.11.2026 12:00")
                                         for t in _events(d, a_pid))), repr(_events(d, a_pid)))
                lst = {r["name"]: r for r in day_model(c, "2026-11-09")["list"]}
                res.ok("колокольчик дня: у A горит и назван SMS, у B — нет",
                       lst["Sms Alfa"]["reminded"] and lst["Sms Alfa"]["reminded_sms"]
                       and not lst["Sms Beta"]["reminded"], repr({k: (v["reminded"], v["reminded_sms"]) for k, v in lst.items()}))

                # повтор прохода — без дубля
                clock.set(_at(*fri, 10, 5))
                time.sleep(1.2)
                res.check("следующие проходы SMS не повторяют", len(stand.sends), 1)

                # перенос: другое начало — другой ключ, новое напоминание
                r = c.post_json(f"/api/schedule/appointments/{a_id}/move?date=2026-11-09",
                                {"date": "2026-11-09", "time": "17:00", "doctor": "d2"})
                res.check("перенос A на 17:00", r.msg, "ok_move")
                got = _wait(lambda: len(stand.sends) >= 2)
                res.ok("перенос — новая SMS с новым часом", got and stand.sends[1]["json"].get("idem")
                       == f"appt:{a_id}:day_before:2026-11-09T15:00:00Z" and "17:00" in stand.sends[1]["json"]["text"],
                       repr(stand.sends[1:]))
                time.sleep(0.8)
                res.check("прежнее напоминание не дублируется", len(stand.sends), 2)

                # записан после часа X — сразу; сервер «не сейчас» — повтор с тем же ключом, одна SMS
                stand.send_mode = "retry_once"
                add_appt(c, "2026-11-09", "15:30", "Sms Eta", "069000777", doctor="d2")
                e_id = appt_id(c, "2026-11-09", "Sms Eta")
                key = f"appt:{e_id}:day_before:2026-11-09T13:30:00Z"
                got = _wait(lambda: len([x for x in stand.sends if x["json"].get("idem") == key]) >= 2)
                res.ok("запись после 10:00 — SMS сразу; после «не сейчас» повтор с тем же ключом",
                       got, repr([x["json"].get("idem") for x in stand.sends]))
                row = _wait(lambda: next((r for r in _sms_log(d) if r["idem"] == key and r["state"] == "sent"), None))
                res.ok("после повтора строка одна и sent", row is not None
                       and len([r for r in _sms_log(d) if r["idem"] == key]) == 1, repr(_sms_log(d)))
                stand.send_mode = "ok"

                # сервер молчит: строка ждёт в очереди, старт её не теряет; окно прошло — expired
                stand.send_mode = "down"
                add_appt(c, "2026-11-09", "18:00", "Sms Theta", "069000888", doctor="d3")
                h_id = appt_id(c, "2026-11-09", "Sms Theta")
                h_pid = pid_by_phone(c, "069000888")
                hkey = f"appt:{h_id}:day_before:2026-11-09T16:00:00Z"
                row = _wait(lambda: next((r for r in _sms_log(d) if r["idem"] == hkey), None))
                res.ok("сервер молчит — строка в очереди с причиной offline",
                       row is not None and row["state"] == "queued"
                       and _wait(lambda: next((r for r in _sms_log(d) if r["idem"] == hkey), {}).get("error") == "offline"),
                       repr(row))
                n_h = len([x for x in stand.sends if x["json"].get("idem") == hkey])
                time.sleep(1.0)
                res.ok("очередь пробует снова на каждом проходе",
                       len([x for x in stand.sends if x["json"].get("idem") == hkey]) > n_h)
                res.ok("журнал работает, пока сервер SMS молчит", c.get("/admin").status == 200)
                clock.set(_at(*fri, 21, 30))
                row = _wait(lambda: next((r for r in _sms_log(d) if r["idem"] == hkey and r["state"] == "expired"), None))
                res.ok("окно прошло — expired", row is not None, repr(_sms_log(d)))
                res.ok("летопись: «SMS netrimis … serverul nu a răspuns»",
                       _wait(lambda: any(t.startswith("SMS netrimis (cu o zi înainte) — vizita 09.11.2026 18:00: serverul nu a răspuns")
                                         for t in _events(d, h_pid))), repr(_events(d, h_pid)))
                stand.send_mode = "ok"

                # доставка: опрос у сервера, летопись
                stand.states = {1: "delivered", 2: "undelivered"}
                clock.set(_at(*fri, 21, 40))
                # ждать ОБЕ строки: на медленном раннере опрос успевает перевести одну, и ожидание,
                # отпускающее по первой, роняло проверку (CI 30.10 на b9d28f7)
                rows = _wait(lambda: (lambda xs: xs if len(xs) == 2 else None)(
                    [r for r in _sms_log(d) if r["cloud_id"] in (1, 2) and r["state"] != "sent"]))
                res.ok("опрос доставки: 1 — delivered, 2 — undelivered",
                       rows and {r["cloud_id"]: r["state"] for r in rows} == {1: "delivered", 2: "undelivered"}, repr(rows))
                ev = _wait(lambda: [t for t in _events(d, a_pid) if t.startswith(("SMS livrat", "SMS nelivrat"))] or None)
                res.ok("летопись A: «SMS livrat» и «SMS nelivrat»",
                       ev and any(t.startswith("SMS livrat") for t in ev) and any(t.startswith("SMS nelivrat") for t in ev),
                       repr(_events(d, a_pid)))

                # флаги Telegram не тронуты; номера нет в логе сервера
                flags = _rows(d, "SELECT reminded_day, reminded_2h FROM appointments")
                res.ok("флаги Telegram reminded_day/reminded_2h у всех визитов — 0",
                       all(not f["reminded_day"] and not f["reminded_2h"] for f in flags), repr(flags))
                log = _log(s)
                res.ok("в логе сервера нет ни номера, ни текста SMS, ни трейсбека",
                       "000111" not in log and "000888" not in log and "reaminteste" not in log
                       and "Traceback" not in log, log[-600:])
                res.ok("лог: sms: tick added= sent=", "sms: tick added=" in log, log[-400:])
                lst = {r["name"]: r for r in day_model(c, "2026-11-09")["list"]}
                res.ok("колокольчик не горит у недошедшей (undelivered) и у не ушедшей",
                       not lst["Sms Theta"]["reminded"], repr(lst["Sms Theta"]))
                # зарегистрировать визиты для понедельника: L 09:00 (за 2 ч → 08:00), M 08:30 (не слать)
                add_appt(c, "2026-11-09", "09:00", "Sms Lambda", "069000999", doctor="d4")
                add_appt(c, "2026-11-09", "08:30", "Sms Mu", "069000555", doctor="d2")
            n_fri = len(stand.sends)

            # ---- понедельник: «в день визита» за 2 часа, строка телефона, накануне выключено ----
            _clinic_weekdays(d, {"day_before": {"on": False}, "same_day": {"on": True, "hours": 2, "variant": "scurt"},
                                 "phone_line": True})
            clock.set(_at(*mon, 8, 5))
            with Server(dir_=d, env=env) as s:
                c = Client(s.url).login()
                l_id = appt_id(c, "2026-11-09", "Sms Lambda")
                lkey = f"appt:{l_id}:same_day:2026-11-09T07:00:00Z"
                got = _wait(lambda: any(x["json"].get("idem") == lkey for x in stand.sends))
                res.ok("визит 09:00: «за 2 часа» попало до 08:00 — ушло в 08:00", got, repr(stand.sends[n_fri:]))
                txt = next((x["json"]["text"] for x in stand.sends if x["json"].get("idem") == lkey), "")
                res.ok("текст «astazi, 09.11», час 09:00, короткий вариант, строка отмены с телефоном клиники",
                       "astazi, 09.11" in txt and "09:00" in txt and txt.startswith("Clinica Test: programare")
                       and txt.endswith("\nAnulare: +373 60 000 000") and rule.parts(txt)[2] == 1, repr(txt))
                add_appt(c, "2026-11-09", "12:00", "Sms Iota", "069000123", doctor="d3")
                add_appt(c, "2026-11-09", "09:30", "Sms Kappa", "069000321", doctor="d3")
                i_id = appt_id(c, "2026-11-09", "Sms Iota")
                k_id = appt_id(c, "2026-11-09", "Sms Kappa")
                time.sleep(1.2)
                res.check("визит 08:30 (меньше часа от 08:00) и запись меньше чем за 2 часа — не слать",
                          [x["json"]["idem"] for x in stand.sends[n_fri:]], [lkey])
                clock.set(_at(*mon, 10, 0, 30))
                ikey = f"appt:{i_id}:same_day:2026-11-09T10:00:00Z"
                got = _wait(lambda: any(x["json"].get("idem") == ikey for x in stand.sends))
                res.ok("визит 12:00 — SMS в 10:00", got, repr([x["json"]["idem"] for x in stand.sends[n_fri:]]))
                time.sleep(0.8)
                res.ok("визит A в 17:00 ещё ждёт своих 15:00",
                       not any(x["json"].get("idem") == f"appt:{a_id}:same_day:2026-11-09T15:00:00Z" for x in stand.sends))
                clock.set(_at(*mon, 15, 0, 30))
                akey = f"appt:{a_id}:same_day:2026-11-09T15:00:00Z"
                got = _wait(lambda: any(x["json"].get("idem") == akey for x in stand.sends))
                res.ok("визит A 17:00 — SMS в 15:00, прежние напоминания накануне не повторены",
                       got and not any(x["json"].get("idem", "").startswith(f"appt:{a_id}:day_before")
                                       for x in stand.sends[n_fri:]), repr([x["json"]["idem"] for x in stand.sends[n_fri:]]))
                res.ok("записанному меньше чем за 2 часа (Kappa) SMS не было",
                       not any(str(k_id) in x["json"].get("idem", "") for x in stand.sends))
                flags = _rows(d, "SELECT reminded_day, reminded_2h FROM appointments")
                res.ok("флаги Telegram по-прежнему нули", all(not f["reminded_day"] and not f["reminded_2h"] for f in flags))
    finally:
        stand.close()
        _rmtree_settled(d)


def suite_not_offered(res: Result) -> None:
    """Сервер не предлагает пакет (503 sms_not_offered): ни очереди, ни отправок,
    ни строки в летописи; без файла с renew — цикл спит."""
    stand = Stand()
    stand.account_reply = (503, {"ok": False, "code": "sms_not_offered", "text": "Pachetul SMS nu este disponibil"})
    d = pathlib.Path(tempfile.mkdtemp(prefix="dp_sms2_"))
    env = {**KEY_ENV, **TICK}
    try:
        _clinic_weekdays(d)
        (d / "license.json").write_text(lr._file(5, {"url": stand.url, "token": TOKEN}), encoding="utf-8")
        with Clock(_at(2026, 11, 6, 10, 30)) as clock:
            with Server(dir_=d, env=env) as s:
                c = Client(s.url).login()
                res.check("визит записан", add_appt(c, "2026-11-09", "12:00", "Sms Omega", "069000111").msg, "ok")
                time.sleep(1.5)
                res.ok("счёт спрошен, пакет не предлагается — отправок нет",
                       any(r["path"] == "/v1/sms/account" for r in stand.requests) and stand.sends == [], repr(stand.sends))
                res.check("очередь пуста", _sms_log(d), [])
                res.ok("лог без проходов SMS", "sms: tick" not in _log(s), _log(s)[-300:])
                # сервер передумал: предлагает — очередь оживает без перезапуска (счёт перечитывается)
                stand.account_reply = None
                clock.set(_at(2026, 11, 6, 10, 35))
                time.sleep(1.0)
                res.ok("пока счёт не перечитан (раз в 10 минут по часам), отправок нет", stand.sends == [])
                clock.set(_at(2026, 11, 6, 10, 45))
                got = _wait(lambda: len(stand.sends) >= 1)
                res.ok("после перечитывания счёта напоминание ушло", got, repr(stand.sends))
        # без файла с renew: спрашивать некого
        d2 = pathlib.Path(tempfile.mkdtemp(prefix="dp_sms3_"))
        try:
            _clinic_weekdays(d2)
            shutil.copy(FIX / "valid.json", d2 / "license.json")
            n = len(stand.requests)
            with Clock(_at(2026, 11, 6, 10, 30)):
                with Server(dir_=d2, env=env) as s:
                    c = Client(s.url).login()
                    add_appt(c, "2026-11-09", "12:00", "Sms Psi", "069000111")
                    time.sleep(1.0)
                    res.ok("файл без renew: ни одного запроса к серверу", len(stand.requests) == n)
                    res.check("и ни одной строки очереди", _sms_log(d2), [])
        finally:
            _rmtree_settled(d2)
    finally:
        stand.close()
        _rmtree_settled(d)


# ---------- экраны (S6) ----------


def _j(r) -> dict:
    return json.loads(r.body)


def suite_screen(res: Result) -> None:
    """Setări › SMS и его API, плитка и пункт меню, отказ пациента в фише,
    лист acord по состоянию пакета, баннер остатка; затем «не предлагается»."""
    stand = Stand()
    renew = {"url": stand.url, "token": TOKEN}
    d = pathlib.Path(tempfile.mkdtemp(prefix="dp_sms4_"))
    env = {**KEY_ENV, **TICK}
    try:
        _clinic_weekdays(d)
        (d / "license.json").write_text(lr._file(5, renew), encoding="utf-8")
        with Clock(_at(2026, 11, 6, 9, 0)) as clock:
            with Server(dir_=d, env=env) as s:
                c = Client(s.url).login()
                res.check("без входа — 401", Client(s.url).get("/api/settings/sms").status, 401)
                page = c.get("/admin/settings/sms")
                res.ok("страница — React-экран settings_sms", page.status == 200
                       and 'data-screen="settings_sms"' in page.body, page.body[:300])
                data = _wait(lambda: (_j(c.get("/api/settings/sms"))["data"] or {}) if
                             _j(c.get("/api/settings/sms"))["data"].get("offered") else None) or _j(c.get("/api/settings/sms"))["data"]
                res.ok("экран: доступен, предложен, включён, остаток 100, от DentPilot, директору можно заказывать",
                       data["available"] and data["offered"] and data["enabled"] and data["account"]["balance"] == 100
                       and data["account"]["from"] == "DentPilot" and data["can_order"] and data["why"] == "", repr(data)[:600])
                res.check("настройки — умолчания (кнопка Rechemări включена, Олег 30.10)", data["settings"],
                          {"day_before": {"on": True, "hour": 10, "variant": "standard"},
                           "same_day": {"on": False, "hours": 2, "variant": "standard"}, "phone_line": False,
                           "recall": {"on": True, "variant": "standard", "auto": False}})
                res.check("лимит автоматических рекламаций в день — число экрану", data["options"]["recall_auto_daily"], 20)
                pr = data["previews"]["recall"]["standard"]
                res.ok("предпросмотр Rechemări: клиника и телефон, без даты и услуги, один сегмент RO и RU",
                       "Clinica Test" in pr["ro"]["text"] and "+373 60 000 000" in pr["ro"]["text"]
                       and "controlul periodic" in pr["ro"]["text"] and pr["ro"]["segments"] == 1
                       and pr["ru"]["segments"] == 1 and "осмотр" in pr["ru"]["text"], repr(pr))
                res.check("варианты Rechemări — Standard и Scurt",
                          [v["key"] for v in data["options"]["recall_variants"]], ["standard", "scurt"])
                pv = data["previews"]["day_before"]["standard"]
                res.ok("предпросмотр накануне: «maine», название клиники, один сегмент, RO и RU",
                       "maine" in pv["ro"]["text"] and "Clinica Test" in pv["ro"]["text"] and pv["ro"]["segments"] == 1
                       and "завтра" in pv["ru"]["text"] and pv["ru"]["segments"] == 1, repr(pv))
                res.ok("предпросмотр в день визита: «astazi»",
                       "astazi" in data["previews"]["same_day"]["scurt"]["ro"]["text"])
                res.ok("варианты и часы — списком, личного текста нет",
                       [v["key"] for v in data["options"]["variants"]] == ["standard", "scurt", "oficial", "cald"]
                       and data["options"]["hours"][0] == 8 and data["options"]["leads"] == [1, 2, 3], repr(data["options"]))
                res.ok("плитка хаба и пункт меню «SMS pacienți»",
                       any(t["href"] == "/admin/settings/sms" and "100 SMS" in t["hint"][0]["t"]
                           for t in _j(c.get("/api/settings/hub"))["data"]["tiles"])
                       and any(i["key"] == "sms" and i["dot"] == "ok" for i in shell_model(c.get("/admin").body)["nav"]["sync"]))
                res.ok("предупреждения у пункта меню нет: 100 SMS — выше порога 30",
                       not any(i.get("alert") for i in shell_model(c.get("/admin").body)["nav"]["sync"]))

                # переключатели — сохраняются сразу, цикл просыпается
                r = c.post_json("/api/settings/sms", {"day_before": {"on": True, "hour": 11, "variant": "cald"},
                                                      "same_day": {"on": True, "hours": 3, "variant": "scurt"},
                                                      "phone_line": True})
                res.ok("сохранение — ok_sms с данными", r.msg == "ok_sms" and _j(r)["data"]["settings"]["same_day"]["on"], r.body[:300])
                cfg = json.loads((d / "clinic.json").read_text(encoding="utf-8"))
                res.check("clinic.json › sms (ключ recall — умолчание, не стёрт: прайор 08-16)", cfg.get("sms"),
                          {"day_before": {"on": True, "hour": 11, "variant": "cald"},
                           "same_day": {"on": True, "hours": 3, "variant": "scurt"}, "phone_line": True,
                           "recall": {"on": True, "variant": "standard", "auto": False}})
                data = _j(c.get("/api/settings/sms"))["data"]
                res.ok("предпросмотр со строкой телефона клиники",
                       data["previews"]["day_before"]["cald"]["ro"]["text"].endswith("\nAnulare: +373 60 000 000"))
                r = c.post_json("/api/settings/sms", {"day_before": {"on": True, "hour": 99, "variant": "zzz"}})
                res.check("кривые значения — умолчания, не отказ", _j(r)["data"]["settings"]["day_before"],
                          {"on": True, "hour": 10, "variant": "standard"})
                res.check("не JSON — 422 bad_sms", c.post("/api/settings/sms", x="1").msg, "bad_sms")

                # директор: нота, имя, тест
                r = c.post_json("/api/settings/sms/order", {"pack": 100})
                res.ok("пополнение — sms_order_ok с нотой и ссылкой", r.msg == "sms_order_ok"
                       and _j(r)["data"]["reference"] == "DP-77" and _j(r)["data"]["units"] == 100, r.body[:300])
                res.check("стенд получил заказ",
                          next((x["json"] for x in reversed(stand.requests) if x["path"] == "/v1/sms/order"), None),
                          {"pack": 100})
                r = c.post_json("/api/settings/sms/sender", {"name": "Clinica Tst"})
                res.ok("заявка на имя — sms_sender_ok, в счёте requested", r.msg == "sms_sender_ok"
                       and _j(r)["data"]["account"]["sender_state"] == "requested", r.body[:300])
                r = c.post_json("/api/settings/sms/test", {"phone": "069000111"})
                res.ok("тестовая SMS — sms_test_ok, ушла стендом видом test", r.msg == "sms_test_ok"
                       and stand.sends[-1]["json"]["kind"] == "test" and stand.sends[-1]["json"]["to"] == "69000111", r.body[:200])
                r = c.post_json("/api/settings/sms/test", {"phone": "12345"})
                res.ok("кривой номер — 409 sms_denied с полем phone и словами",
                       r.status == 409 and r.msg == "sms_denied" and _j(r).get("field") == "phone", r.body[:300])
                stand.send_mode = "balance"
                r = c.post_json("/api/settings/sms/test", {"phone": "069000111"})
                res.ok("отказ сервера — его словами", r.msg == "sms_denied" and "terminat" in _j(r)["text"], r.body[:300])
                stand.send_mode = "ok"

                # фиша: отказ пациента одним полем; лист acord по состоянию пакета
                pid = new_patient(c, "Sms Refuz", "069000777")
                r = c.post_json(f"/api/patients/{pid}/sms-off", {"on": True})
                j = _j(r)
                res.ok("«Fără remindere SMS» — ok_card, профиль sms_off, летопись",
                       r.msg == "ok_card" and j["data"]["profile"]["sms_off"] is True
                       and any(a["kind"] == "sms_off" and a["text"].startswith("Remindere SMS oprite")
                               for a in j["data"]["activity"]["items"]), r.body[:300])
                res.check("остальной профиль цел", j["data"]["profile"]["phone"], "069000777")
                r = c.post_json(f"/api/patients/{pid}/sms-off", {"on": False})
                res.check("снято", _j(r)["data"]["profile"]["sms_off"], False)
                sheet = c.get(f"/admin/patient/{pid}/acord").body
                res.ok("acord при работающем пакете: SMS в основаниях и в разделе хранения",
                       "(prin SMS)" in sheet and "operatorului SMS.MD" in sheet, sheet[-2500:])
                sheet_ru = c.get(f"/admin/patient/{pid}/acord?lang=ru").body
                res.ok("acord RU: то же", "(по SMS)" in sheet_ru and "оператору SMS.MD" in sheet_ru)
                # кнопка «SMS» в Rechemări (30.10) — тоже SMS: пока её галочка стоит
                # (умолчание), лист говорит про SMS и при выключенных событиях
                c.post_json("/api/settings/sms", {"day_before": {"on": False}, "same_day": {"on": False}})
                sheet = c.get(f"/admin/patient/{pid}/acord").body
                res.ok("события выключены, галочка Rechemări стоит — лист всё ещё с SMS (active по ней)",
                       "(prin SMS)" in sheet and "telefon, e-mail sau SMS" in sheet, sheet[-2500:])
                c.post_json("/api/settings/sms", {"day_before": {"on": False}, "same_day": {"on": False},
                                                  "recall": {"on": False}})
                sheet = c.get(f"/admin/patient/{pid}/acord").body
                res.ok("события и галочка Rechemări выключены — лист прежний, без SMS",
                       "(prin SMS)" not in sheet and "operatorului SMS.MD" not in sheet)
                res.ok("плитка: «oprit», пункт меню с точкой off",
                       any(t["href"] == "/admin/settings/sms" and t["hint"][0]["t"] == "oprit"
                           for t in _j(c.get("/api/settings/hub"))["data"]["tiles"])
                       and any(i["key"] == "sms" and i["dot"] == "off" for i in shell_model(c.get("/admin").body)["nav"]["sync"]))
                c.post_json("/api/settings/sms", {"day_before": {"on": True}})

                # «мало SMS» по штукам (Tauri, 18.10): прогноз расхода — справка экрана,
                # порогом он больше не служит; пороги на границах — test_notices
                for i in range(12):
                    r = add_appt(c, "2026-10-30", f"{8 + i % 6:02d}:00", f"Sms Vechi {i}", f"0690001{i:02d}",
                                 doctor="d2" if i < 6 else "d3")
                    res.check(f"визит прошлого месяца {i} записан", r.msg, "ok_past")
                stand.account["balance"] = 1
                clock.set(_at(2026, 11, 6, 9, 30))
                r = c.post_json("/api/settings/sms/refresh", {})
                data = _wait(lambda: (lambda x: x if x["forecast"]["visits"] >= 12 else None)(_j(c.get("/api/settings/sms"))["data"]))
                res.ok("прогноз: 12 визитов за 30 дней, остаток 1 — мало (порог 30)",
                       data and data["forecast"]["month"] == 12 and data["forecast"]["days_left"] == 2
                       and data["low"] and data["low"]["left"] == 1 and data["low"]["limit"] == 30,
                       repr(data and data["forecast"]) + repr(data and data["low"]))
                item = next((i for i in shell_model(c.get("/admin").body)["nav"]["sync"] if i["key"] == "sms"), {})
                res.ok("у пункта меню — предупреждение с остатком, без дней; баннера в оболочке нет",
                       item.get("alert", "").startswith("Pachetul SMS se termină. Au rămas 1 SMS în pachet")
                       and "zile" not in item.get("alert", "")
                       and "sms" not in shell_model(c.get("/admin").body)["signals"], repr(item))

                # модуль выключен в облаке, два кода (23.10): тариф Basic и тумблер облака;
                # у тумблера причина без «Plus» — клиника под ним может быть и на Plus
                for code, plus in (("sms_basic", True), ("sms_off", False)):
                    stand.account.update(enabled=False, blocked=code)
                    c.post_json("/api/settings/sms/refresh", {})
                    data = _wait(lambda: (lambda x: x if x.get("blocked") == code else None)(
                        _j(c.get("/api/settings/sms"))["data"])) or _j(c.get("/api/settings/sms"))["data"]
                    res.ok(f"модуль выключен ({code}): offered, не enabled, код с сервера, "
                           f"причина {'называет' if plus else 'не называет'} Plus",
                           data["offered"] and not data["enabled"] and data["blocked"] == code
                           and data["why"].startswith("modulul SMS este oprit")
                           and ("DentPilot Plus" in data["why"]) == plus, repr(data)[:400])
                src = (BOT / "app" / "core" / "layout.py").read_text(encoding="utf-8")
                want = {k: re.search(rf'^{n} = "([^"]+)"', src, re.M).group(1)
                        for k, n in (("phone", "SUPPORT_PHONE"), ("email", "FEEDBACK_EMAIL"))}
                res.check("контакты для возобновления — те же, что на странице активации", data.get("support"), want)
                stand.account.update(enabled=True, blocked="")
                c.post_json("/api/settings/sms/refresh", {})

                # не предлагается: плитка молчит, пункта нет, экран объясняет
                stand.account_reply = (503, {"ok": False, "code": "sms_not_offered", "text": "nu"})
                c.post_json("/api/settings/sms/refresh", {})
                data = _j(c.get("/api/settings/sms"))["data"]
                res.ok("не предлагается: offered=false, причина словами, счёта нет",
                       data["available"] and not data["offered"] and data["account"] is None
                       and "disponibil" in data["why"], repr(data)[:300])
                res.ok("плитки и пункта меню нет, баннера нет",
                       not any(t["href"] == "/admin/settings/sms" for t in _j(c.get("/api/settings/hub"))["data"]["tiles"])
                       and not any(i["key"] == "sms" for i in shell_model(c.get("/admin").body)["nav"]["sync"]))
                res.check("заказ без пакета — 409 sms_denied", c.post_json("/api/settings/sms/order", {"pack": 100}).status, 409)
        # файл без renew: экран говорит «только в активированном программе»
        d2 = pathlib.Path(tempfile.mkdtemp(prefix="dp_sms5_"))
        try:
            _clinic_weekdays(d2)
            shutil.copy(FIX / "valid.json", d2 / "license.json")
            with Server(dir_=d2, env=env) as s:
                c = Client(s.url).login()
                data = _j(c.get("/api/settings/sms"))["data"]
                res.ok("без renew: available=false, предпросмотров нет", not data["available"] and data["previews"] == {})
                res.check("заказ — 409 sms_unavailable", c.post_json("/api/settings/sms/order", {"pack": 100}).msg, "sms_unavailable")
        finally:
            _rmtree_settled(d2)
    finally:
        stand.close()
        _rmtree_settled(d)


def _off(d: pathlib.Path, pid: int) -> int:
    return _rows(d, "SELECT COALESCE(sms_off, 0) AS v FROM patients WHERE id = ?", pid)[0]["v"]


def suite_box(res: Result) -> None:
    """Галочка «SMS reminder» окна записи (Олег 19.10, п.7 четверга 22.10).

    Видна по `sms_loop.active()` И праву `PERM_SMS` (врач — нет); пишет
    `patients.sms_off` — то же поле, что фиша, — только присланная и только
    переменой, строкой летописи фиши. Без поля, на отказе записи, без телефона,
    у врача и при выключенном пакете `sms_off` не трогается.
    ⚠️ Ветка PIN-файла, а не ADMIN_KEY: роль у ADMIN_KEY одна — директор."""
    stand = Stand()
    renew = {"url": stand.url, "token": TOKEN}
    d = pathlib.Path(tempfile.mkdtemp(prefix="dp_sms6_"))
    env = {**KEY_ENV, **TICK, "ADMIN_KEY": ""}
    mon, tue = "2026-11-09", "2026-11-10"
    oprite, pornite = ("Remindere SMS oprite — la cererea pacientului",
                       "Remindere SMS pornite din nou")
    try:
        _clinic_weekdays(d)
        (d / "license.json").write_text(lr._file(5, renew), encoding="utf-8")
        with Clock(_at(2026, 11, 6, 9, 0)):
            with Server(dir_=d, env=env) as s:
                boss = Client(s.url)
                boss.post("/admin/setup", pin1="1111", pin2="1111")
                for uid, role, pin, extra in (("ana", "receptie", "3333", {}),
                                              ("d2", "medic", "2222", {"doctor_id": "d2"})):
                    res.check(f"учётка {role} заведена", boss.post_json(
                        "/api/settings/users", {"uid": uid, "name": uid.title(), "role": role,
                                                "pin": pin, **extra}).msg, "ok_user")
                rec, med = Client(s.url), Client(s.url)
                rec.post("/admin/login", password="3333", next="/admin")
                med.post("/admin/login", password="2222", next="/admin")

                # видимость: пакет и право
                res.ok("пакет заработал — директору галочка в форме дня",
                       _wait(lambda: day_model(boss, mon)["form"]["sms"]) is True)
                res.ok("регистратуре — в форме дня и в форме пустого часа панели",
                       day_model(rec, mon)["form"]["sms"] is True
                       and panel_live(rec, mon)["slotform"]["sms"] is True)
                res.ok("врачу — ни там, ни там (Олег 22.10)",
                       day_model(med, mon)["form"]["sms"] is False
                       and panel_live(med, mon)["slotform"]["sms"] is False)

                # справка окна по номеру
                r = rec.post_json("/api/schedule/sms-of", {"phone": "069000801"})
                res.ok("новый номер — галочка стоит", r.status == 200 and _j(r)["data"] == {"sms": True},
                       r.body[:200])
                r = med.post_json("/api/schedule/sms-of", {"phone": "069000801"})
                res.check("врачу справка закрыта", (r.status, r.msg), (403, "no_access"))

                # новый без поля — SMS включены, летопись молчит
                res.check("A: запись без поля", add_appt(rec, mon, "12:00", "Box Alfa", "069000801").msg, "ok")
                a = pid_by_phone(boss, "069000801")
                res.ok("A: новый пациент — SMS включены, строк SMS в летописи нет",
                       _off(d, a) == 0 and _events(d, a) == [], repr(_events(d, a)))
                # новый со снятой галочкой
                res.check("B: запись со снятой галочкой",
                          add_appt(rec, mon, "13:00", "Box Beta", "069000802", sms=False).msg, "ok")
                b = pid_by_phone(boss, "069000802")
                res.ok("B: sms_off=1 и строка летописи фиши, подписанная вошедшим",
                       _off(d, b) == 1 and _events(d, b) == [oprite]
                       and _rows(d, "SELECT actor FROM activity WHERE patient_id = ? AND kind = 'sms_off'",
                                 b)[0]["actor"] == "Ana", repr(_events(d, b)))
                card = _j(boss.get(f"/api/patients/{b}"))["data"]["profile"]
                res.check("фиша B показывает тот же отказ", card["sms_off"], True)
                r = rec.post_json("/api/schedule/sms-of", {"phone": "069 000-802"})
                res.check("справка по номеру B (те же цифры с пробелами) — не стоит", _j(r)["data"], {"sms": False})

                # без поля — не тронут; то же значение — без второй строки
                res.check("B: вторая запись без поля",
                          add_appt(rec, tue, "12:00", "Box Beta", "069000802").msg, "ok")
                res.ok("B: без поля sms_off не тронут", _off(d, b) == 1 and len(_events(d, b)) == 1)
                res.check("B: третья запись с той же снятой галочкой",
                          add_appt(rec, tue, "13:00", "Box Beta", "069000802", sms=False).msg, "ok")
                res.ok("B: значение не сменилось — второй строки нет", _events(d, b) == [oprite],
                       repr(_events(d, b)))
                res.check("B: запись с поставленной галочкой",
                          add_appt(rec, tue, "14:00", "Box Beta", "069000802", sms=True).msg, "ok")
                res.ok("B: SMS снова включены, строка «pornite din nou»",
                       _off(d, b) == 0 and _events(d, b) == [oprite, pornite], repr(_events(d, b)))

                # не ответ пациента — не запись
                r = add_appt(rec, mon, "12:00", "Box Alfa", "069000801", sms=False)
                res.ok("A: отказ записи (тот же час) — sms_off не тронут",
                       r.msg != "ok" and _off(d, a) == 0, f"{r.msg} {_off(d, a)}")
                res.check("A: поле не bool (0) — «не сообщали»",
                          (add_appt(rec, tue, "15:00", "Box Alfa", "069000801", sms=0).msg, _off(d, a)),
                          ("ok", 0))
                res.check("без телефона: запись со снятой галочкой",
                          add_appt(rec, tue, "16:00", "Box Fara", "", nophone=True, sms=False).msg, "ok")
                res.check("без телефона: sms_off не тронут",
                          _rows(d, "SELECT COALESCE(sms_off, 0) AS v FROM patients WHERE name = 'Box Fara'")[0]["v"], 0)
                res.check("C: врач прислал снятую галочку — запись идёт",
                          add_appt(med, mon, "14:00", "Box Gama", "069000803", sms=False).msg, "ok")
                cc = pid_by_phone(boss, "069000803")
                res.ok("C: у врача права нет — sms_off не тронут", _off(d, cc) == 0 and _events(d, cc) == [])
                # ⛔ Словарь общий с фишей: летопись хранит ГОТОВУЮ строку, и после
                # переезда текстов в `db.SMS_OFF_EVENT` фиша обязана писать прежние
                # литералы байт в байт (тире, диакритика)
                rec.post_json(f"/api/patients/{cc}/sms-off", {"on": True})
                rec.post_json(f"/api/patients/{cc}/sms-off", {"on": False})
                res.ok("фиша пишет в летопись прежние строки байт в байт",
                       [t.encode("utf-8") for t in _events(d, cc)]
                       == [b"Remindere SMS oprite \xe2\x80\x94 la cererea pacientului",
                           b"Remindere SMS pornite din nou"], repr(_events(d, cc)))

                # пакет выключен — галочки нет, присланное не пишется. Кнопка «SMS» в
                # Rechemări (30.10) — тоже SMS: пока её галочка стоит, пакет активен
                boss.post_json("/api/settings/sms", {"day_before": {"on": False}, "same_day": {"on": False}})
                res.ok("события выключены, галочка Rechemări стоит — пакет активен, галочка окна есть",
                       day_model(rec, mon)["form"]["sms"] is True)
                boss.post_json("/api/settings/sms", {"day_before": {"on": False}, "same_day": {"on": False},
                                                     "recall": {"on": False}})
                res.ok("события и галочка Rechemări выключены — галочки нет ни в форме дня, ни у панели",
                       day_model(rec, mon)["form"]["sms"] is False
                       and panel_live(rec, mon)["slotform"]["sms"] is False)
                res.check("A: запись со снятой галочкой при выключенном пакете",
                          add_appt(rec, mon, "15:00", "Box Alfa", "069000801", sms=False).msg, "ok")
                res.ok("A: sms_off не тронут", _off(d, a) == 0 and _events(d, a) == [])
    finally:
        stand.close()
        _rmtree_settled(d)
