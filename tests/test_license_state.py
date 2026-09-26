"""Лицензия в программе (L3): пол часов, три состояния, память между запусками.

Машина состояний грузится по пути, как rsa_verify: она обязана жить без
импортов проекта, и каждая граница проверяется ПОДСТАВНЫМ временем — секунда
до и ровно в момент. Обвязка (файл в папке clinic.json, память, зеркало в
базе, ключ из окружения) проверяется живым сервером: память появляется на
диске, переживает рестарт и стирание своего файла, и не даёт льготы заново,
когда стёрт сам файл лицензии.

⭐ Строка состояния в логе сервера — ASCII (`license: state=...`): на
Windows stderr в файл идёт в кодовой странице консоли, и кириллицу там
искать нельзя.
"""
import importlib.util
import json
import pathlib
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone

from harness import BOT, ROOT, Result, Server, _rmtree_settled

FIX = ROOT / "tests" / "fixtures" / "license"
SEC = timedelta(seconds=1)
DAY = timedelta(days=1)


def _load(name: str, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod           # dataclass при отложенных аннотациях ищет модуль здесь
    spec.loader.exec_module(mod)
    return mod


lst = _load("license_state", BOT / "app" / "core" / "license_state.py")
rv = _load("rsa_verify", BOT / "app" / "core" / "rsa_verify.py")
gen = _load("license_fixtures", ROOT / "scripts" / "license_fixtures.py")


def _t(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _claim(name: str):
    k = gen.load_key()
    code, claim = rv.open_envelope((FIX / f"{name}.json").read_text(encoding="utf-8"),
                                   {"test": (k["n"], k["e"])})
    assert code == "" and claim is not None, (name, code)
    return claim


def suite_states(res: Result) -> None:
    """`evaluate`: границы, полы, отсчёт без файла, память на выходе."""
    E = lst.Memory()
    valid, trial, expired = _claim("valid"), _claim("trial"), _claim("expired")

    for name, c in (("valid", valid), ("trial", trial)):
        ok = ("", c)
        for label, now, want in (("за секунду до срока", c.valid_until - SEC, lst.ACTIVE),
                                 ("ровно в срок", c.valid_until, lst.GRACE),
                                 ("за секунду до конца льготы", c.grace_until - SEC, lst.GRACE),
                                 ("ровно в конец льготы", c.grace_until, lst.READONLY)):
            s, _ = lst.evaluate(ok, now, E, True)
            res.check(f"{name}, {label}: {want}", s.state, want)
    s, m = lst.evaluate(("", valid), valid.valid_until - SEC, E, True)
    res.ok("принятый файл: claim, даты файла, без кода и стены",
           s.claim is valid and s.valid_until == valid.valid_until
           and s.grace_until == valid.grace_until and s.code == "" and not s.wall)
    res.ok("память после приёма: seq 3 и даты файла",
           m.accepted_seq == 3 and m.valid_until == valid.valid_until
           and m.grace_until == valid.grace_until)
    res.check("память: first_start = now при первом запуске", m.first_start, valid.valid_until - SEC)
    res.check("память: last_seen = now", m.last_seen, valid.valid_until - SEC)
    s, _ = lst.evaluate(("", valid), valid.valid_until - SEC, E, False)
    res.ok("годный файл на пустой картотеке: active, стены нет",
           s.state == lst.ACTIVE and not s.wall)
    s, _ = lst.evaluate(("", expired), _t("2026-09-24T12:00:00Z"), E, True)
    res.check("expired сегодня: readonly", s.state, lst.READONLY)

    # ---- пол часов ----
    s, m = lst.evaluate(("", valid), valid.issued_at - 30 * DAY, E, True)
    res.check("часы раньше выдачи файла: now = issued_at", s.now, valid.issued_at)
    seen = lst.Memory(last_seen=valid.grace_until)
    s, m = lst.evaluate(("", valid), valid.valid_until - 10 * DAY, seen, True)
    res.check("часы переведены назад: состояние по виденному времени", s.state, lst.READONLY)
    res.check("часы переведены назад: now = last_seen", s.now, valid.grace_until)
    res.check("память: last_seen не уменьшается", m.last_seen, valid.grace_until)
    t0 = _t("2026-09-01T08:00:00Z")
    s, m = lst.evaluate(("", valid), t0 + 5 * DAY, lst.Memory(first_start=t0), True)
    res.check("память: first_start не сдвигается", m.first_start, t0)
    # без файла: иначе пол по issued_at поднял бы now выше t0, и проверялось бы не то
    s, m = lst.evaluate(None, t0, lst.Memory(first_start=t0 + DAY), True)
    res.check("память: first_start из будущего подтягивается к now", m.first_start, t0)

    # ---- файл старее принятого ----
    vu2, gu2 = _t("2026-10-01T00:00:00Z"), _t("2026-10-15T00:00:00Z")
    remembered = lst.Memory(accepted_seq=5, valid_until=vu2, grace_until=gu2)
    s, m = lst.evaluate(("", valid), _t("2026-10-05T00:00:00Z"), remembered, True)
    res.check("seq 3 поверх принятого 5: код license_older", s.code, lst.OLDER)
    res.ok("seq 3 поверх принятого 5: claim не принят, состояние по памяти",
           s.claim is None and s.state == lst.GRACE and s.valid_until == vu2)
    res.check("seq 3 поверх принятого 5: память не откатывается", m.accepted_seq, 5)

    # ---- файла нет ----
    n = _t("2026-11-01T09:00:00Z")
    s, m = lst.evaluate(None, n, E, True)
    res.ok("картотека без файла: grace с отсчётом 14 дней от первого запуска",
           s.state == lst.GRACE and s.valid_until == n and s.grace_until == n + 14 * DAY
           and not s.wall and s.code == "")
    res.ok("картотека без файла: память без принятого файла",
           m.accepted_seq == 0 and m.valid_until is None and m.first_start == n)
    first = lst.Memory(first_start=n)
    res.check("отсчёт: за секунду до 14 дней — grace",
              lst.evaluate(None, n + 14 * DAY - SEC, first, True)[0].state, lst.GRACE)
    res.check("отсчёт: ровно 14 дней — readonly",
              lst.evaluate(None, n + 14 * DAY, first, True)[0].state, lst.READONLY)
    s, _ = lst.evaluate(None, n, E, False)
    res.ok("пустая картотека без файла: missing и стена",
           s.state == lst.MISSING and s.wall and s.valid_until is None and s.code == "")
    s, _ = lst.evaluate(None, n, remembered, False)
    res.ok("файл стёрт после приёма: по запомненным датам, стены нет, льготы заново нет",
           s.state == lst.READONLY and not s.wall and s.valid_until == vu2)
    s, _ = lst.evaluate(None, _t("2026-10-05T00:00:00Z"), remembered, True)
    res.check("файл стёрт в льготе: grace по памяти, не отсчёт", s.grace_until, gu2)
    kept = lst.Memory(accepted_seq=3, valid_until=valid.valid_until, grace_until=valid.grace_until)
    s, _ = lst.evaluate(None, n, kept, True)
    res.ok("файл стёрт в срок: grace, но никогда не active",
           s.state == lst.GRACE and s.valid_until == valid.valid_until)

    # ---- файл не годен ----
    bad = (rv.BAD_SIGNATURE, None)
    s, _ = lst.evaluate(bad, n, E, False)
    res.ok("битый файл на пустой картотеке: invalid с кодом и стеной",
           s.state == lst.INVALID and s.code == rv.BAD_SIGNATURE and s.wall)
    s, _ = lst.evaluate(bad, n, E, True)
    res.ok("битый файл на картотеке: grace с кодом, отсчёт 14 дней",
           s.state == lst.GRACE and s.code == rv.BAD_SIGNATURE and not s.wall
           and s.grace_until == n + 14 * DAY)
    s, _ = lst.evaluate((rv.KEY_UNKNOWN, None), _t("2026-10-05T00:00:00Z"), remembered, True)
    res.ok("неизвестный ключ при принятом ранее: по памяти, код виден",
           s.state == lst.GRACE and s.code == rv.KEY_UNKNOWN and s.valid_until == vu2)


def suite_memory(res: Result) -> None:
    """Файл памяти: обход, терпимость к мусору, атомарность, слияние."""
    d = pathlib.Path(tempfile.mkdtemp(prefix="dp_lic_"))
    try:
        p = d / "license.state"
        full = lst.Memory(_t("2026-09-01T08:00:00Z"), _t("2026-09-24T12:00:00Z"), 3,
                          _t("2099-01-01T00:00:00Z"), _t("2099-01-15T00:00:00Z"))
        lst.save(p, full)
        res.check("память: полная — как записана", lst.load(p), full)
        res.ok("память: без хвоста .tmp", not p.with_name(p.name + ".tmp").exists())
        lst.save(p, lst.Memory())
        res.check("память: пустая — как записана", lst.load(p), lst.Memory())
        res.check("память: файла нет — пустая", lst.load(d / "nope.state"), lst.Memory())
        p.write_text("{ not json", encoding="utf-8")
        res.check("память: мусор — пустая, не отказ", lst.load(p), lst.Memory())
        p.write_text("[1, 2]", encoding="utf-8")
        res.check("память: список — пустая", lst.load(p), lst.Memory())
        p.write_text(json.dumps({"first_start": "2026-09-01T08:00:00Z", "accepted_seq": "3",
                                 "valid_until": "2099-01-01T00:00:00Z"}), encoding="utf-8")
        got = lst.load(p)
        res.ok("память: частичная — только годные поля",
               got.first_start == _t("2026-09-01T08:00:00Z") and got.accepted_seq == 0
               and got.valid_until is None and got.grace_until is None,
               repr(got))
        res.check("память: seq не бывает отрицательным",
                  lst.from_dict({"accepted_seq": -2}).accepted_seq, 0)
        res.check("память: seq не бывает булевым",
                  lst.from_dict({"accepted_seq": True}).accepted_seq, 0)
    finally:
        shutil.rmtree(d, ignore_errors=True)

    a = lst.Memory(_t("2026-09-05T00:00:00Z"), _t("2026-09-20T00:00:00Z"), 2,
                   _t("2026-10-01T00:00:00Z"), _t("2026-10-15T00:00:00Z"))
    b = lst.Memory(_t("2026-09-01T00:00:00Z"), _t("2026-09-25T00:00:00Z"), 5,
                   _t("2026-12-01T00:00:00Z"), _t("2026-12-15T00:00:00Z"))
    m = lst.merge(a, b)
    res.ok("слияние: самый ранний first_start, самый поздний last_seen",
           m.first_start == b.first_start and m.last_seen == b.last_seen)
    res.ok("слияние: принятый файл — у кого seq выше, с его датами",
           m.accepted_seq == 5 and m.valid_until == b.valid_until)
    m = lst.merge(a, lst.Memory())
    res.check("слияние с пустой: без изменений", m, a)
    m = lst.merge(lst.Memory(), a)
    res.check("слияние пустой с полной: полная", m, a)
    same = lst.merge(a, lst.Memory(accepted_seq=2, valid_until=b.valid_until, grace_until=b.grace_until))
    res.check("слияние при равном seq: даты первого", same.valid_until, a.valid_until)


def suite_keys(res: Result) -> None:
    """Таблица ключей: константа плюс файл из окружения, и только вне exe."""
    k = gen.load_key()
    path = str(FIX / "test-key.json")
    want = {"test": (k["n"], k["e"])}
    res.check("не заморожено: ключ из файла в таблице", lst.keys_from({}, path, False), want)
    base = {"prod": (12345, 65537)}
    res.check("заморожено: файл не читается вовсе", lst.keys_from(base, path, True), base)
    res.check("пустая переменная: только константа", lst.keys_from(base, "", False), base)
    res.check("путь в кавычках: снимаются", lst.keys_from({}, f'"{path}"', False), want)
    res.check("файла нет: только константа", lst.keys_from(base, str(FIX / "nope.json"), False), base)
    res.check("файл лицензии вместо файла ключа: ничего не добавлено",
              lst.keys_from(base, str(FIX / "valid.json"), False), base)
    got = lst.keys_from(base, path, False)
    res.ok("константа не меняется, таблица — копия", base == {"prod": (12345, 65537)} and got is not base)
    d = pathlib.Path(tempfile.mkdtemp(prefix="dp_lic_"))
    try:
        two = d / "two.json"
        two.write_text(json.dumps([json.loads((FIX / "test-key.json").read_text(encoding="utf-8")),
                                   {"kid": "two", "n": "ff", "e": 3},
                                   {"kid": 7, "n": "ff", "e": 3},
                                   {"kid": "bad", "n": "zz", "e": 3}]), encoding="utf-8")
        got = lst.keys_from({}, str(two), False)
        res.check("список ключей: годные взяты, негодные пропущены",
                  got, dict(want, two=(255, 3)))
        (d / "garbage.json").write_text("{", encoding="utf-8")
        res.check("битый файл ключа: только константа",
                  lst.keys_from(base, str(d / "garbage.json"), False), base)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _state(d: pathlib.Path) -> dict:
    return json.loads((d / "license.state").read_text(encoding="utf-8"))


def _log(s: Server) -> str:
    return s._log_path.read_text(encoding="utf-8", errors="replace")


def suite_server(res: Result) -> None:
    """Живой сервер: файл в папке clinic.json, память на диске и в базе."""
    key_env = {"DENTART_LICENSE_KEYS": str(FIX / "test-key.json")}
    d1 = pathlib.Path(tempfile.mkdtemp(prefix="dp_lic1_"))
    d2 = pathlib.Path(tempfile.mkdtemp(prefix="dp_lic2_"))
    d3 = pathlib.Path(tempfile.mkdtemp(prefix="dp_lic3_"))
    try:
        # 1. пустая картотека, файла нет: стена, память появилась
        with Server(dir_=d1) as s:
            st1 = _state(d1)
            res.ok("без файла: память записана на старте",
                   lst.parse(st1.get("first_start")) is not None
                   and lst.parse(st1.get("last_seen")) is not None, repr(st1))
            res.check("без файла: принятого файла нет", st1.get("accepted_seq"), 0)
            res.ok("без файла на пустой картотеке: missing в логе",
                   "license: state=missing code=- seq=0" in _log(s))

        # 2. годный файл + ключ из окружения: принят
        shutil.copy(FIX / "valid.json", d2 / "license.json")
        with Server(dir_=d2, env=key_env) as s:
            st2 = _state(d2)
            res.check("valid: принят, seq 3", st2.get("accepted_seq"), 3)
            res.check("valid: даты файла в памяти", st2.get("valid_until"), "2099-01-01T00:00:00Z")
            res.ok("valid: в логе нет предупреждений о лицензии",
                   "license: state=" not in _log(s), _log(s)[-300:])

        # 3. рестарт на той же папке: first_start прежний, last_seen не убывает
        with Server(dir_=d2, env=key_env):
            st3 = _state(d2)
            res.check("рестарт: first_start сохранён", st3.get("first_start"), st2.get("first_start"))
            res.ok("рестарт: last_seen не убывает", st3.get("last_seen") >= st2.get("last_seen"))

        # 4. тот же файл без ключа в окружении: ключ неизвестен, но память держит даты
        with Server(dir_=d2) as s:
            res.ok("без ключа: grace по памяти с кодом license_key_unknown",
                   "license: state=grace code=license_key_unknown seq=3" in _log(s), _log(s)[-300:])
            res.check("без ключа: память не откатилась", _state(d2).get("accepted_seq"), 3)

        # 5. файл стёрт: льготы заново нет, состояние по запомненным датам
        (d2 / "license.json").unlink()
        with Server(dir_=d2, env=key_env) as s:
            res.ok("файл стёрт: grace по памяти, не missing",
                   "license: state=grace code=- seq=3" in _log(s), _log(s)[-300:])

        # 6. стёрт и файл памяти: зеркало в базе восстанавливает её
        (d2 / "license.state").unlink()
        with Server(dir_=d2, env=key_env) as s:
            st6 = _state(d2)
            res.check("память из базы: seq", st6.get("accepted_seq"), 3)
            res.check("память из базы: first_start прежний", st6.get("first_start"), st2.get("first_start"))
            res.ok("память из базы: grace по датам", "license: state=grace code=- seq=3" in _log(s))
        con = sqlite3.connect(d2 / "dental.db")
        try:
            rows = dict(con.execute("SELECT key, value FROM schema_meta WHERE key LIKE 'lic_%'"))
        finally:
            con.close()
        res.ok("зеркало в базе: lic_accepted с seq 3",
               json.loads(rows.get("lic_accepted", "{}")).get("accepted_seq") == 3, repr(rows))
        res.check("зеркало в базе: lic_first = first_start", rows.get("lic_first"), st2.get("first_start"))

        # 7. просроченный файл: readonly уже на старте
        shutil.copy(FIX / "expired.json", d3 / "license.json")
        with Server(dir_=d3, env=key_env) as s:
            res.ok("expired: readonly в логе", "license: state=readonly code=- seq=2" in _log(s),
                   _log(s)[-300:])
    finally:
        for d in (d1, d2, d3):
            _rmtree_settled(d)
