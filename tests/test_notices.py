"""Уведомления у часов, «мало SMS» по штукам и запуск вместе с Windows (Tauri, Т8).

Контракт — docs/dentpilot-2/tauri-contract.md § 2 («Запуск вместе с Windows»)
и § 4 («Уведомления»). Что держится здесь:
  - `GET /shell/notices` — только с токеном запуска оболочки, только с
    loopback, иначе 404 тем же телом, что у несуществующего адреса;
  - `id` детерминирован: тот же на повторном опросе, новый — только когда
    событие надо показать снова (версия, срок и порог, эпизод «мало SMS»);
  - пороги на границах: лицензия 8/7 дней и 1 день, SMS 31/30 и 11/10;
  - «мало SMS» — ОДНО правило: подсказка меню, баннер экрана SMS и
    уведомление говорят одно и то же одними словами;
  - галочка автозапуска — факт из реестра (подставной ключ HKCU прогона;
    настоящая автозагрузка разработчика не трогается).
"""
import json
import secrets
import sys
import tempfile
import pathlib
import types
from datetime import datetime, timedelta, timezone

from harness import (BOT, Client, Clock, Result, Server, TZ, _rmtree_settled,
                     shell_model)
import test_license_renew as lr
import test_sms as ts

sys.path.insert(0, str(BOT))

from app.core import notices, sms_loop  # noqa: E402
from app.modules.settings import autostart  # noqa: E402

TOKEN = secrets.token_hex(16)                     # 32 hex, как у оболочки
SHELL = {notices.TOKEN_ENV: TOKEN}
HDR = {notices.HEADER: TOKEN}
TS = "%Y-%m-%dT%H:%M:%SZ"


def _notices(s: Server, headers: dict | None = HDR) -> dict:
    r = Client(s.url).get("/shell/notices", headers=headers)
    return json.loads(r.body) if r.status == 200 else {"status": r.status, "body": r.body}


def _ids(data: dict, kind: str) -> list[str]:
    return [it["id"] for it in data.get("items", []) if it["id"].startswith(kind + ":")]


def _item(data: dict, kind: str) -> dict:
    return next((it for it in data.get("items", []) if it["id"].startswith(kind + ":")), {})


def _license(plan: str, issued: datetime, until: datetime, seq: int = 5,
             renew: dict | None = None) -> str:
    """Файл с подписью тестового ключа на заданные даты (льгота — 14 дней)."""
    base = lr.gen.CLAIMS["trial" if plan == "trial" else "valid"]
    claim = dict(base, seq=seq, issued_at=issued.strftime(TS), valid_until=until.strftime(TS),
                 grace_until=(until + timedelta(days=14)).strftime(TS))
    if renew is not None:
        claim["renew"] = renew
    payload = lr.gen.claim_bytes(claim)
    return lr.gen.envelope(payload, lr.gen.sign(payload, lr.gen.load_key()))


# ---------- чистые части: пороги, тексты, кто спрашивает ----------


def suite_rules(res: Result) -> None:
    """Пороги на границах и дверь маршрута — без сервера."""
    d = timedelta(days=1)
    res.check("лицензия: 8 дней — рано", notices.license_step(8 * d), 0)
    res.check("лицензия: 7 дней и 1 с — ещё рано", notices.license_step(7 * d + timedelta(seconds=1)), 0)
    res.check("лицензия: ровно 7 дней — порог 7", notices.license_step(7 * d), 7)
    res.check("лицензия: 2 дня — всё ещё порог 7", notices.license_step(2 * d), 7)
    res.check("лицензия: 1 день и 1 с — порог 7", notices.license_step(d + timedelta(seconds=1)), 7)
    res.check("лицензия: ровно 1 день — порог 1", notices.license_step(d), 1)
    res.check("лицензия: час до конца — порог 1", notices.license_step(timedelta(hours=1)), 1)

    res.check("SMS платный: 31 — хватает", sms_loop.low_limit(31, False), 0)
    res.check("SMS платный: 30 — мало (порог 30)", sms_loop.low_limit(30, False), 30)
    res.check("SMS платный: 0 — мало", sms_loop.low_limit(0, False), 30)
    res.check("SMS пробный: 11 — хватает", sms_loop.low_limit(11, True), 0)
    res.check("SMS пробный: 10 — мало (порог 10)", sms_loop.low_limit(10, True), 10)
    res.check("SMS пробный: 30 пробных — не «мало» с первой SMS", sms_loop.low_limit(30, True), 0)
    texts = [sms_loop.low_text(n, t) for n in (0, 1, 30) for t in (False, True)]
    res.ok("тексты «мало SMS» — без дней", not any("zi" in w.lower().split() or "zile" in w for w in texts),
           repr(texts))
    res.ok("0 — «s-a terminat», 30 — «Au rămas 30 SMS în pachet», пробный — «din perioada de probă»",
           "s-a terminat" in sms_loop.low_text(0, False)
           and sms_loop.low_text(30, False).startswith("Au rămas 30 SMS în pachet")
           and "din perioada de probă" in sms_loop.low_text(10, True), repr(texts))

    def req(host: str, tok: str | None) -> object:
        return types.SimpleNamespace(client=types.SimpleNamespace(host=host),
                                     headers={notices.HEADER: tok} if tok is not None else {})

    import os
    keep = os.environ.get(notices.TOKEN_ENV)
    try:
        os.environ[notices.TOKEN_ENV] = TOKEN
        res.ok("дверь: loopback и верный токен — пускает", notices.shell_request_ok(req("127.0.0.1", TOKEN)))
        res.ok("дверь: ::1 и ::ffff:127.0.0.1 — тоже этот ПК",
               notices.shell_request_ok(req("::1", TOKEN)) and notices.shell_request_ok(req("::ffff:127.0.0.1", TOKEN)))
        res.ok("дверь: адрес из сети клиники с верным токеном — нет",
               not notices.shell_request_ok(req("192.168.1.5", TOKEN)))
        res.ok("дверь: пустой пир — нет", not notices.shell_request_ok(req("", TOKEN)))
        res.ok("дверь: чужой токен той же длины — нет",
               not notices.shell_request_ok(req("127.0.0.1", secrets.token_hex(16))))
        res.ok("дверь: без заголовка — нет", not notices.shell_request_ok(req("127.0.0.1", None)))
        os.environ[notices.TOKEN_ENV] = "1"
        res.ok("дверь: короткий «токен» из чужих рук — не токен",
               not notices.shell_request_ok(req("127.0.0.1", "1")))
        os.environ.pop(notices.TOKEN_ENV)
        res.ok("дверь: без токена запуска — нет", not notices.shell_request_ok(req("127.0.0.1", "")))
    finally:
        if keep is None:
            os.environ.pop(notices.TOKEN_ENV, None)
        else:
            os.environ[notices.TOKEN_ENV] = keep


# ---------- маршрут и обновление ----------


def suite_route(res: Result) -> None:
    """404 без токена, с чужим, без оболочки; ответ без сессии; обновление."""
    with Server(env={**SHELL, "DENTART_FAKE_UPDATE_URL": "http://127.0.0.1:9/DentPilot.exe"}) as s:
        nope = Client(s.url).get("/shell/nope")
        for label, headers in (("без заголовка", None), ("с чужим токеном", {notices.HEADER: secrets.token_hex(16)}),
                               ("с пустым", {notices.HEADER: ""})):
            r = Client(s.url).get("/shell/notices", headers=headers)
            res.ok(f"{label} — 404 тем же телом, что у несуществующего адреса",
                   r.status == 404 and r.body == nope.body, f"{r.status} {r.body[:80]}")
        r = Client(s.url).get("/shell/notices", headers=HDR)
        res.ok("верный токен без входа — 200, конверт v1, пусто, без кэша",
               r.status == 200 and json.loads(r.body) == {"v": 1, "items": []}
               and "no-store" in r.header("cache-control"), f"{r.status} {r.body[:200]}")
        c = Client(s.url).login()
        c.post_json("/api/settings/system/check", {})
        data = _notices(s)
        it = _item(data, "update")
        res.check("обновление: id по версии", it.get("id"), "update:9.9.9")
        res.ok("обновление: текст с версией и экраном, клик — Stare sistem",
               it.get("body") == "DentPilot 9.9.9 este gata — actualizați în Setări › Stare sistem."
               and it.get("open") == "/admin/settings/system" and it.get("title"), repr(it))
        res.check("повторный опрос — тот же id", _ids(_notices(s), "update"), ["update:9.9.9"])
        res.ok("ни слова о пациентах: только три вида", all(i["id"].split(":")[0] in ("update", "license", "sms")
                                                            for i in data["items"]), repr(data))
    with Server() as s:
        res.check("без токена запуска (окно pywebview, браузер) — 404 и с заголовком",
                  Client(s.url).get("/shell/notices", headers=HDR).status, 404)


# ---------- лицензия ----------


def suite_license(res: Result) -> None:
    """За 7 и за 1 день до конца; продлилась — молчит; пробный — своими словами."""
    t0 = datetime(2026, 11, 2, 10, 0, tzinfo=TZ)
    until = (t0 + timedelta(days=8)).astimezone(timezone.utc)
    stamp = until.strftime("%Y%m%dT%H%M%SZ")
    day = until.astimezone(TZ).strftime("%d.%m.%Y")
    d = pathlib.Path(tempfile.mkdtemp(prefix="dp_notice_lic_"))
    try:
        (d / "license.json").write_text(_license("standard", t0 - timedelta(days=40), until),
                                        encoding="utf-8")
        with Clock(t0) as clock:
            with Server(dir_=d, env={**ts.KEY_ENV, **SHELL}) as s:
                res.check("8 дней до конца — молчит", _ids(_notices(s), "license"), [])
                clock.set(until - timedelta(days=7))
                it = _item(_notices(s), "license")
                res.check("ровно 7 дней — порог 7", it.get("id"), f"license:{stamp}:7")
                res.ok("текст: дата конца и куда идти, клик — Licența",
                       it.get("title") == "Abonamentul se termină" and day in it.get("body", "")
                       and "Setări › Licența" in it.get("body", "") and it.get("open") == "/admin/license",
                       repr(it))
                clock.set(until - timedelta(days=1, minutes=5))
                res.check("1 день и 5 минут — тот же id, повторно не показывается",
                          _ids(_notices(s), "license"), [f"license:{stamp}:7"])
                clock.set(until - timedelta(days=1))
                res.check("ровно 1 день — порог 1, новый id", _ids(_notices(s), "license"), [f"license:{stamp}:1"])
                c = Client(s.url).login()
                later = until + timedelta(days=365)
                r = c.post("/admin/license", text=_license("standard", until - timedelta(days=2), later, seq=6),
                           terms="1")
                res.check("новый файл принят", r.msg, "license_ok")
                res.check("продлилась — молчит", _ids(_notices(s), "license"), [])
        trial_until = (t0 + timedelta(days=1)).astimezone(timezone.utc)
        d2 = pathlib.Path(tempfile.mkdtemp(prefix="dp_notice_trial_"))
        try:
            (d2 / "license.json").write_text(_license("trial", t0 - timedelta(days=13), trial_until),
                                             encoding="utf-8")
            with Clock(t0):
                with Server(dir_=d2, env={**ts.KEY_ENV, **SHELL}) as s:
                    it = _item(_notices(s), "license")
                    res.ok("пробный за день до конца: «Perioada de probă», активировать в Licența",
                           it.get("id", "").endswith(":1") and it.get("title") == "Perioada de probă se termină"
                           and "activați abonamentul în Setări › Licența" in it.get("body", ""), repr(it))
        finally:
            _rmtree_settled(d2)
    finally:
        _rmtree_settled(d)


# ---------- «мало SMS»: одно правило на меню, экран и часы ----------


def _three(c: Client, s: Server) -> tuple[dict | None, str, dict]:
    """(low экрана SMS, подсказка пункта меню, уведомление) — три места одного правила."""
    data = ts._j(c.get("/api/settings/sms"))["data"]
    item = next((i for i in shell_model(c.get("/admin").body)["nav"]["sync"] if i["key"] == "sms"), {})
    return data["low"], item.get("alert", ""), _item(_notices(s), "sms")


def _balance(c: Client, stand, n: int) -> None:
    stand.account["balance"] = n
    c.post_json("/api/settings/sms/refresh", {})


def suite_sms(res: Result) -> None:
    """Платный 31/30, пополнение — новый эпизод; пробный 11/10."""
    stand = ts.Stand()
    renew = {"url": stand.url, "token": ts.TOKEN}
    d = pathlib.Path(tempfile.mkdtemp(prefix="dp_notice_sms_"))
    t0 = ts._at(2026, 11, 6, 9, 0)
    try:
        ts._clinic_weekdays(d)
        (d / "license.json").write_text(lr._file(5, renew), encoding="utf-8")
        with Clock(t0) as clock:
            with Server(dir_=d, env={**ts.KEY_ENV, **ts.TICK, **SHELL}) as s:
                c = Client(s.url).login()
                ts._wait(lambda: ts._j(c.get("/api/settings/sms"))["data"].get("active"))
                _balance(c, stand, 31)
                low, alert, it = _three(c, s)
                res.ok("31 платных — ни баннера, ни треугольника, ни уведомления",
                       low is None and not alert and not it, repr((low, alert, it)))
                _balance(c, stand, 30)
                low, alert, it = _three(c, s)
                res.ok("30 платных — экран: порог 30, «Au rămas 30 SMS în pachet»",
                       low is not None and low["limit"] == 30 and low["left"] == 30 and not low["trial"]
                       and low["text"].startswith("Au rămas 30 SMS în pachet"), repr(low))
                res.ok("одно правило: меню, экран и часы — одни слова",
                       low is not None and alert == f"{low['title']}. {low['text']}"
                       and it.get("title") == low["title"] and it.get("body") == low["text"]
                       and it.get("open") == "/admin/settings/sms", repr((alert, it)))
                first = it.get("id", "")
                res.ok("id — порог и эпизод", first.startswith("sms:30:") and len(first) > len("sms:30:"), first)
                res.check("повторный опрос — тот же id", _item(_notices(s), "sms").get("id"), first)
                clock.set(t0 + timedelta(hours=1))
                _balance(c, stand, 29)
                res.check("ниже в том же эпизоде — тот же id", _item(_notices(s), "sms").get("id"), first)
                _balance(c, stand, 130)
                low, alert, it = _three(c, s)
                res.ok("пополнили — молчат все три", low is None and not alert and not it, repr((low, alert, it)))
                clock.set(t0 + timedelta(hours=2))
                _balance(c, stand, 0)
                low, alert, it = _three(c, s)
                res.ok("снова у порога после пополнения — новый эпизод, новый id",
                       it.get("id", "").startswith("sms:30:") and it.get("id") != first, repr((first, it)))
                res.ok("0 — «s-a terminat» во всех трёх",
                       low is not None and "s-a terminat" in low["text"] and "s-a terminat" in alert
                       and "s-a terminat" in it.get("body", ""), repr((low, alert)))
                c.post_json("/api/settings/sms", {"day_before": {"on": False}, "same_day": {"on": False}})
                low, alert, it = _three(c, s)
                res.ok("события выключены (пакет не работает) — не «мало»", low is None and not alert and not it,
                       repr((low, alert, it)))
        d2 = pathlib.Path(tempfile.mkdtemp(prefix="dp_notice_smstrial_"))
        try:
            ts._clinic_weekdays(d2)
            now = datetime.now(timezone.utc).replace(microsecond=0)
            (d2 / "license.json").write_text(
                _license("trial", now - timedelta(days=3), now + timedelta(days=11), renew=renew),
                encoding="utf-8")
            with Server(dir_=d2, env={**ts.KEY_ENV, **ts.TICK, **SHELL}) as s:
                c = Client(s.url).login()
                ts._wait(lambda: ts._j(c.get("/api/settings/sms"))["data"].get("active"))
                _balance(c, stand, 11)
                low, alert, it = _three(c, s)
                res.ok("пробный: 11 — хватает", low is None and not alert and not it, repr((low, alert, it)))
                _balance(c, stand, 10)
                low, alert, it = _three(c, s)
                res.ok("пробный: 10 — порог 10, «din perioada de probă», id sms:10:…",
                       low is not None and low["limit"] == 10 and low["trial"]
                       and "din perioada de probă" in low["text"] and it.get("id", "").startswith("sms:10:")
                       and it.get("body") == low["text"] and alert == f"{low['title']}. {low['text']}",
                       repr((low, it)))
        finally:
            _rmtree_settled(d2)
    finally:
        stand.close()
        _rmtree_settled(d)


# ---------- запуск вместе с Windows ----------


def _reg_read(key: str, name: str) -> str | None:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
            return str(winreg.QueryValueEx(k, name)[0])
    except OSError:
        return None


def _reg_drop(key: str) -> None:
    import winreg
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)
    except OSError:
        pass


def suite_autostart(res: Result) -> None:
    """Галочка — факт реестра; только в режиме движка; подсказка при сети."""
    if sys.platform != "win32":
        res.ok("не Windows — реестр не проверяется", True, "")
        return
    import winreg
    key = rf"Software\DentPilotTest\Run-{secrets.token_hex(4)}"
    real = _reg_read(autostart.RUN_KEY, autostart.VALUE)
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="dp_autostart_"))
    exe = tmp / "DentPilot.exe"
    exe.write_bytes(b"MZ")
    env = {"DENTART_SHELL": "tauri", autostart.KEY_ENV: key, autostart.EXE_ENV: str(exe)}
    want = f'"{exe}" --tray'
    try:
        with Server(env=env) as s:
            c = Client(s.url).login()
            sysd = lambda: ts._j(c.get("/api/settings/system"))["data"]  # noqa: E731
            res.check("режим движка, значения нет — галочка снята, без подсказки",
                      sysd()["autostart"], {"on": False, "other": "", "hint": ""})
            r = c.post_json("/api/settings/autostart", {"on": True})
            res.ok("включить — ok_set, свежая модель: on", r.msg == "ok_set" and ts._j(r)["data"]["autostart"]["on"],
                   r.body[:300])
            res.check("в реестре — «<BASE>\\DentPilot.exe» --tray", _reg_read(key, autostart.VALUE), want)
            res.check("не булево — 422 bad_set", c.post_json("/api/settings/autostart", {"on": "da"}).msg, "bad_set")
            r = c.post_json("/api/settings/autostart", {"on": False})
            res.ok("снять — значение убрано", not ts._j(r)["data"]["autostart"]["on"]
                   and _reg_read(key, autostart.VALUE) is None, r.body[:300])
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as k:
                winreg.SetValueEx(k, autostart.VALUE, 0, winreg.REG_SZ, r'"D:\Vechi\DentPilot.exe" --tray')
            st = sysd()["autostart"]
            res.ok("значение ведёт к другому exe — снята, и он назван",
                   not st["on"] and r"D:\Vechi\DentPilot.exe" in st["other"], repr(st))
            c.post_json("/api/settings/autostart", {"on": True})
            res.check("включение переписывает на этот exe", _reg_read(key, autostart.VALUE), want)
            res.ok("галочку сняли мимо программы (Диспетчер задач) — экран видит факт",
                   (_reg_drop(key) or True) and sysd()["autostart"]["on"] is False)
        with Server(env={**env, "DENTART_LAN": "1"}) as s:
            c = Client(s.url).login()
            st = ts._j(c.get("/api/settings/system"))["data"]["autostart"]
            res.check("доступ из сети и галочка снята — подсказка включить", st["hint"], autostart.LAN_HINT)
            c.post_json("/api/settings/autostart", {"on": True})
            st = ts._j(c.get("/api/settings/system"))["data"]["autostart"]
            res.ok("включили — подсказки нет", st["on"] and st["hint"] == "", repr(st))
        env_no = {autostart.KEY_ENV: key, autostart.EXE_ENV: str(exe), "DENTART_SHELL": ""}
        with Server(env=env_no) as s:
            c = Client(s.url).login()
            res.check("не режим движка (окно pywebview, браузер) — строки нет",
                      ts._j(c.get("/api/settings/system"))["data"]["autostart"], None)
            res.check("и маршрута нет — 404", c.post_json("/api/settings/autostart", {"on": False}).status, 404)
        with Server(env={"DENTART_SHELL": "tauri", autostart.EXE_ENV: str(exe), autostart.KEY_ENV: ""}) as s:
            c = Client(s.url).login()
            res.check("из исходников без подставного ключа — строки нет (настоящий Run не тронуть)",
                      ts._j(c.get("/api/settings/system"))["data"]["autostart"], None)
        res.check("настоящая автозагрузка разработчика не тронута",
                  _reg_read(autostart.RUN_KEY, autostart.VALUE), real)
    finally:
        _reg_drop(key)
        _reg_drop(r"Software\DentPilotTest")
        _rmtree_settled(tmp)
