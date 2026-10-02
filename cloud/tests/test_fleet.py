"""Флот (шаг 3, 02.10): компьютеры клиник из заголовков программы, страница и JSON.

Главное из cloud.md › «Флот»: строка на компьютер заводится и обновляется
запросами самой программы (/v1/license, /v1/trial, /v1/verify) по заголовкам
X-DentPilot-*; мусор в заголовках строки не заводит; «отстаёт» — сравнение с
последним выпуском GitHub (стенд), «молчит» — давно без связи; JSON того же
отчёта отвечает 401 без куки, а не 303 на вход.
"""
import json
import sqlite3
import sys

from harness import CLOUD, ROOT, Client, Result, Server, cid_from, load_by_path
from test_account import DIRECTOR, FakeGitHub, FakeGoogle, _google_login

sys.path.insert(0, str(CLOUD))
from app import fleet  # noqa: E402

rv = load_by_path("rsa_verify", ROOT / "bot" / "app" / "core" / "rsa_verify.py")
DEV1, DEV2 = "d_0123456789ab", "d_fedcba987654"


def _hdr(device: str = DEV1, version: str = "1.35.2", channel: str = "stable",
         os_: str = "Windows 11 (10.0.26200)", token: str = "") -> dict:
    h = {"User-Agent": f"DentPilot/{version}", "X-DentPilot-Device": device,
         "X-DentPilot-Channel": channel, "X-DentPilot-OS": os_}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _sql(s: Server, sql: str, *args):
    con = sqlite3.connect(s.dir / "cloud.db")
    try:
        rows = con.execute(sql, args).fetchall()
        con.commit()
        return rows
    finally:
        con.close()


def _devices(s: Server):
    return _sql(s, "SELECT id, clinic_id, version, channel, os, last_seq FROM devices ORDER BY id")


def suite_rules(res: Result) -> None:
    """Чистые правила: заголовки → личность, сравнение версий."""
    class R:
        def __init__(self, h):
            self.headers = {k.lower(): v for k, v in h.items()}
    good = fleet.from_request(R(_hdr()))
    res.check("личность из заголовков", good, {"id": DEV1, "version": "1.35.2", "channel": "stable",
                                                  "os": "Windows 11 (10.0.26200)"})
    res.check("без X-DentPilot-Device — не программа", fleet.from_request(R({"User-Agent": "DentPilot/1.0.0"})), None)
    res.check("кривой id — не программа", fleet.from_request(R(_hdr(device="d_xyz"))), None)
    weird = fleet.from_request(R(_hdr(version="x", channel="nightly", os_="  a  b " + "c" * 100)))
    res.ok("чужая версия, чужой канал, длинная ОС — пусто, пусто, обрезано",
           weird["version"] == "" and weird["channel"] == "" and len(weird["os"]) <= fleet.OS_MAX
           and weird["os"].startswith("a b"), repr(weird))
    res.ok("отстаёт: 1.35.2 < 1.35.3, 1.35.10 > 1.35.9, пустое не отстаёт",
           fleet.behind("1.35.2", "1.35.3") and not fleet.behind("1.35.10", "1.35.9")
           and not fleet.behind("", "1.35.3") and not fleet.behind("1.35.2", "") and not fleet.behind("1.35.3", "1.35.3"))


def suite_devices(res: Result) -> None:
    """Запросы программы заводят и обновляют компьютеры; страница, карточка, JSON, кабинет."""
    gh, g = FakeGitHub(), FakeGoogle()
    with Server(env={**gh.env, **g.env, "DP_TRIAL_MODE": "auto", "DP_TRIAL_NOTIFY": "oleg@example.md"}) as s:
        admin = Client(s.url).login()
        res.ok("флот пуст: страница говорит об этом", "ещё не выходил на связь" in admin.get("/admin/fleet").body)
        cid = cid_from(admin.post("/admin/clinics", name="Clinica Flotă", idno="1234567890123",
                                  email=DIRECTOR["email"]).location)
        admin.post(f"/admin/clinics/{cid}/issue", kind="trial")
        token = _sql(s, "SELECT renew_token FROM clinics WHERE id=?", cid)[0][0]
        anon = Client(s.url)
        r = anon.get("/v1/license?seq=0", headers=_hdr(token=token))
        res.ok("суточный запрос с заголовками: файл выдан, компьютер заведён с версией, каналом, ОС, seq 0",
               r.status == 200 and _devices(s) == [(DEV1, cid, "1.35.2", "stable", "Windows 11 (10.0.26200)", 0)],
               f"{r.status} {_devices(s)}")
        first = _sql(s, "SELECT first_seen_at, last_seen_at FROM devices WHERE id=?", DEV1)[0]
        r = anon.get("/v1/license?seq=1", headers=_hdr(version="1.35.3", channel="beta", token=token))
        row = _devices(s)[0]
        res.ok("второй запрос того же компьютера: 204, версия и канал обновлены, seq 1, строка одна",
               r.status == 204 and row == (DEV1, cid, "1.35.3", "beta", "Windows 11 (10.0.26200)", 1)
               and len(_devices(s)) == 1, f"{r.status} {row}")
        second = _sql(s, "SELECT first_seen_at, last_seen_at FROM devices WHERE id=?", DEV1)[0]
        res.ok("первый выход на связь не переписан, последний — не раньше первого",
               second[0] == first[0] and second[1] >= first[1])
        r = anon.get("/v1/license?seq=1", headers={"Authorization": f"Bearer {token}", "User-Agent": "DentPilot/1.35.3"})
        res.ok("запрос без X-DentPilot-Device (старая программа) — 204 и строки нет",
               r.status == 204 and len(_devices(s)) == 1)
        r = anon.get("/v1/license?seq=1", headers=_hdr(device="d_not-an-id!!", token=token))
        res.ok("кривой id — 204, строки нет", r.status == 204 and len(_devices(s)) == 1)
        r = anon.get("/v1/license?seq=0", headers=_hdr(device=DEV2, version="1.35.2", token=token))
        res.ok("второй компьютер клиники: своя строка", r.status == 200 and len(_devices(s)) == 2)
        r = anon.get("/v1/license?seq=1", headers=_hdr(token="not-a-token"))
        res.ok("чужой токен: 401 и строки не трогаются", r.status == 401 and len(_devices(s)) == 2)
        # страница флота: последний выпуск от стенда GitHub (1.35.3), отстаёт только 1.35.2
        page = admin.get("/admin/fleet").body
        res.ok("страница «Флот»: последний выпуск, оба компьютера, отстаёт ровно один, клиника со ссылкой",
               "Последний выпуск: <b>1.35.3</b>" in page and DEV1 in page and DEV2 in page
               and page.count(">отстаёт<") == 1 and f"/admin/clinics/{cid}" in page
               and "компьютеров 2 у 1 клиник · отстают 1 · молчат дольше недели 0" in page, page[-2500:])
        res.ok("шапка админки ведёт на флот", "href='/admin/fleet'>Флот</a>" in admin.get("/admin").body)
        card = admin.get(f"/admin/clinics/{cid}").body
        res.ok("карточка клиники: раздел «Компьютеры» с обоими", "Компьютеры" in card and DEV1 in card and DEV2 in card)
        # JSON того же отчёта
        res.check("JSON без куки — 401, не 303", anon.get("/admin/api/fleet").status, 401)
        data = json.loads(admin.get("/admin/api/fleet").body)
        res.ok("JSON: latest, оба компьютера, counts, behind и state",
               data.get("ok") is True and data["data"]["latest"] == "1.35.3"
               and {d["device"] for d in data["data"]["devices"]} == {DEV1, DEV2}
               and data["data"]["counts"] == {"devices": 2, "clinics": 1, "behind": 1, "silent": 0}
               and all(d["state"] == "active" and d["clinic"] == "Clinica Flotă" for d in data["data"]["devices"])
               and [d["behind"] for d in sorted(data["data"]["devices"], key=lambda d: d["device"])] == [False, True],
               json.dumps(data)[:600])
        # молчит: последняя связь 9 дней назад
        _sql(s, "UPDATE devices SET last_seen_at='2026-09-01T00:00:00Z' WHERE id=?", DEV2)
        data = json.loads(admin.get("/admin/api/fleet").body)["data"]
        res.ok("компьютер без связи дольше недели — silent", data["counts"]["silent"] == 1
               and next(d for d in data["devices"] if d["device"] == DEV2)["silent"] is True)
        res.ok("страница: «молчит» с числом дней", ">молчит<" in admin.get("/admin/fleet").body)
        # кабинет клиники видит свои компьютеры
        c = Client(s.url)
        res.check("директор входит по ящику клиники", _google_login(c, s, g).location, "/cont")
        home = c.get("/cont").body
        res.ok("кабинет: «Calculatoare cu DentPilot», версия и метка старой версии",
               "Calculatoare cu DentPilot" in home and "DentPilot 1.35.3" in home and "DentPilot 1.35.2" in home
               and home.count("versiune veche") == 1, home[-3000:])


def suite_activation(res: Result) -> None:
    """Заявка из программы и код: компьютер привязывается к клинике при активации."""
    with Server(env={"DP_TRIAL_MODE": "auto", "DP_TRIAL_NOTIFY": "oleg@example.md"}) as s:
        anon = Client(s.url)
        body = json.dumps({"name": "Clinica Nouă", "idno": "", "contact_name": "X", "email": "nou@example.md",
                           "phone": "", "consent": "1"}).encode()
        r = anon._do("/v1/trial", body, {"Content-Type": "application/json", **_hdr(version="1.36.0")})
        res.ok("заявка из программы с заголовками: клиника заведена, компьютер привязан к ней",
               r.status == 200 and len(_devices(s)) == 1 and _devices(s)[0][2] == "1.36.0"
               and _devices(s)[0][1] == _sql(s, "SELECT id FROM clinics")[0][0], f"{r.status} {_devices(s)}")
        cid = _devices(s)[0][1]
        # повтор с другого компьютера: до кода строки нет, после кода — есть
        r = anon._do("/v1/trial", body, {"Content-Type": "application/json", **_hdr(device=DEV2)})
        res.ok("повтор: 409 с verify_id, второй компьютер ещё не привязан",
               r.status == 409 and "verify_id" in r.body and len(_devices(s)) == 1, f"{r.status} {r.body[:200]}")
        vid = json.loads(r.body)["verify_id"]
        import email, email.policy, re
        letters = [email.message_from_bytes(f.read_bytes(), policy=email.policy.default) for f in sorted(s.outbox.glob("*.eml"))]
        code = next(re.search(r"(\d{6})", m.get_body(preferencelist=("plain",)).get_content()).group(1)
                    for m in letters if m["Subject"].startswith("DentPilot: codul de activare"))
        r = anon._do("/v1/verify", json.dumps({"verify_id": vid, "code": code}).encode(),
                     {"Content-Type": "application/json", **_hdr(device=DEV2, version="1.36.0")})
        res.ok("верный код: токен, второй компьютер привязан к той же клинике",
               r.status == 200 and [d[:2] for d in _devices(s)] == [(DEV1, cid), (DEV2, cid)], f"{r.status} {_devices(s)}")
