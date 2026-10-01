"""Демо-режим (DENTART_DEMO=1, core/demo.py): живое демо с сайта.

Что стережётся: флаг прячет ровно то, что меняет машину и учётки (список
BLOCKED) — страницы, JSON и плитки хаба одним списком — и ничего больше;
баннер демо на каждом экране; вход по ключу остаётся входом (демо не
открывает журнал без куки); потолок загрузки ниже. Без флага ничего из этого
не происходит — иначе клиника получила бы «демо» вместо программы.
"""
import json
import pathlib
import shutil
import sys
import tempfile

from harness import ROOT, Client, Result, Server

DEMO = {"DENTART_DEMO": "1"}
CLOSED_PAGES = ("/admin/settings/system", "/admin/settings/crypt",
                "/admin/settings/backup", "/admin/settings/security",
                "/admin/settings/telegram", "/admin/settings/lan", "/admin/license")
CLOSED_API = ("/api/settings/system", "/api/settings/crypt", "/api/settings/backup",
              "/api/settings/security", "/api/license")
OPEN_PAGES = ("/admin/settings", "/admin/settings/clinic", "/admin/settings/hours",
              "/admin/settings/services", "/admin/settings/theme", "/admin/settings/faq",
              "/admin/all", "/admin/search", "/admin/medici", "/admin/stats")
HUB_CLOSED = {"/admin/settings/system", "/admin/settings/crypt",
              "/admin/settings/backup", "/admin/settings/security"}
HUB_OPEN = {"/admin/settings/clinic", "/admin/settings/hours", "/admin/settings/services",
            "/admin/settings/theme", "/admin/settings/faq"}
BANNER = "Versiune demonstrativă"


def _j(r) -> dict:
    return json.loads(r.body)


def _hub(c: Client) -> set:
    return {t["href"] for t in _j(c.get("/api/settings/hub"))["data"]["tiles"]}


def _upload(c: Client, size: int) -> int:
    """Код ответа на загрузку файла в `size` байт. Потолок срабатывает ДО
    чтения тела, и сервер закрывает соединение, пока клиент ещё шлёт мегабайты:
    под нагрузкой это приходит не ответом 413, а обрывом (WinError 10053) —
    тот же отказ, и считать его падением набора нельзя (поймано полным
    прогоном 01.10: один в один набор зелёный, в общем прогоне — обрыв)."""
    try:
        return c.post_file("/api/patients/1/doc", "file", "f.pdf", b"0" * size,
                           mime="application/pdf").status
    except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
        return 413


def suite_demo(res: Result) -> None:
    with Server(env=DEMO) as s:
        r = Client(s.url).get("/admin")
        res.ok("без куки демо не пускает — вход по ключу остаётся входом",
               r.status == 303 and r.location.startswith("/admin/login"), repr(r))
        c = Client(s.url).login()
        r = c.get("/admin")
        res.check("после входа журнал открыт", r.status, 200)
        res.ok("баннер демо на журнале", BANNER in r.body, "полосы демо нет")
        res.ok("баннер ведёт в шлюз: /demo/reset", "href='/demo/reset'" in r.body,
               "ссылки сброса нет")
        res.ok("баннер демо и на списке пациентов", BANNER in c.get("/admin/search").body,
               "полоса есть только на главной")
        # закрытые адреса — страницы и формы, одним кодом
        for path in CLOSED_PAGES:
            r = c.get(path)
            res.ok(f"{path}: в демо нет", r.status == 303 and r.msg == "demo_off", repr(r))
        for path, fields in (("/admin/update/check", {}), ("/admin/backup/export", {}),
                             ("/admin/users/save", {"name": "x"}), ("/admin/pin/change", {}),
                             ("/admin/telegram/save", {"token": "1:x"}),
                             ("/admin/settings/crypt/prepare", {})):
            r = c.post(path, **fields)
            res.ok(f"POST {path}: в демо нет", r.status == 303 and r.msg == "demo_off", repr(r))
        # отказ стоит ДО маршрута: адрес под закрытым префиксом, которого нет,
        # получает тот же отказ, а не 404 — и ничего под ним не разбирается
        r = c.get("/admin/settings/crypt/oricare")
        res.ok("закрытый префикс закрывает и адрес под ним", r.status == 303 and r.msg == "demo_off",
               repr(r))
        # закрытые адреса — JSON: 403 тем же кодом, не 303 на вход
        for path in CLOSED_API:
            r = c.get(path)
            res.ok(f"{path}: 403 demo_off", r.status == 403 and _j(r).get("code") == "demo_off",
                   repr(r)[:120])
        r = c.post_json("/api/settings/users", {"name": "x"})
        res.ok("POST /api/settings/users: 403 demo_off",
               r.status == 403 and _j(r).get("code") == "demo_off", repr(r)[:120])
        # код отказа — слово для человека, не голый код
        res.ok("demo_off переводится в текст", _j(c.get("/api/license")).get("text", "").startswith("În versiunea"),
               _j(c.get("/api/license")).get("text", ""))
        # открытые разделы — как у клиники
        for path in OPEN_PAGES:
            res.check(f"{path}: открыт", c.get(path).status, 200)
        hrefs = _hub(c)
        res.ok("плитки закрытых разделов спрятаны", not (hrefs & HUB_CLOSED),
               str(sorted(hrefs & HUB_CLOSED)))
        res.ok("плитки клиники, часов, услуг, вида и FAQ на месте", HUB_OPEN <= hrefs,
               str(sorted(HUB_OPEN - hrefs)))
        # потолок загрузки ниже: 9 МБ — 413 ещё до маршрута, 1 МБ проходит
        res.check("загрузка 9 МБ в демо — 413", _upload(c, 9 * 1024 * 1024), 413)
        small = _upload(c, 1024 * 1024)
        res.ok("1 МБ проходит потолок демо", small != 413, str(small))
    with Server() as s:
        c = Client(s.url).login()
        res.ok("без флага полосы демо нет", BANNER not in c.get("/admin").body,
               "полоса демо у клиники")
        res.check("без флага «Stare sistem» открыт", c.get("/admin/settings/system").status, 200)
        res.ok("без флага плитка системы на месте", "/admin/settings/system" in _hub(c),
               "плитка пропала без демо")
        big = _upload(c, 9 * 1024 * 1024)
        res.ok("без флага 9 МБ не упираются в потолок демо", big != 413, str(big))


def suite_seed(res: Result) -> None:
    """Засев демо (demo/seed.py) ложится на схему ПРОГРАММЫ: базу создаёт
    первый сервер, засев её наполняет, второй сервер открывает экраны. Это
    единственный сторож колонок, которые засев знает сам: смена схемы без
    правки засева краснеет здесь, а не у посетителя сайта."""
    sys.path.insert(0, str(ROOT))
    from demo import seed as dseed  # noqa: E402 — пакет демо лежит в корне репозитория
    work = pathlib.Path(tempfile.mkdtemp(prefix="dp_demo_"))
    try:
        shutil.copy(ROOT / "demo" / "clinic.json", work / "clinic.json")
        with Server(env=DEMO, dir_=work):
            pass                                   # схема и миграции — от программы
        counts = dseed.seed(work / "dental.db", work / "clinic.json")
        res.ok("засев: пациенты, визиты, план, оплаты",
               counts["patients"] > 200 and counts["appointments"] > 400
               and counts["plan_items"] > 100 and counts["payments"] > 100, str(counts))
        res.ok("засев: сегодня есть визиты", sum(counts["today"].values()) > 0, str(counts["today"]))
        with Server(env=DEMO, dir_=work) as s:
            c = Client(s.url).login()
            res.check("журнал открывается на засеве", c.get("/admin").status, 200)
            live = _j(c.get("/api/schedule/live"))["data"]
            desk = live.get("desk") or {}
            res.ok("«La recepție» не пуста: подтверждения и план без записи",
                   bool(desk.get("confirm")) and bool(desk.get("unscheduled")),
                   str({k: len(v) if isinstance(v, list) else v for k, v in desk.items()}))
            pats = _j(c.get("/api/patients?q=Popescu"))["data"]
            rows = pats.get("rows") or pats.get("patients") or pats.get("items") or []
            pid = next((r["id"] for r in rows if r.get("name") == "Maria Popescu"), None)
            res.ok("витринный пациент находится поиском", pid is not None, str(pats)[:200])
            if pid is not None:
                card = _j(c.get(f"/api/patients/{pid}"))
                res.ok("фиша витринного пациента отдаётся", card.get("ok") is True
                       and "Maria Popescu" in json.dumps(card, ensure_ascii=False), str(card)[:200])
                odo = _j(c.get(f"/api/patients/{pid}/odontogram"))
                res.ok("одонтограмма с состояниями", odo.get("ok") is True
                       and "carie" in json.dumps(odo), str(odo)[:200])
                perio = _j(c.get(f"/api/patients/{pid}/perio"))
                res.ok("пародонтограмма с осмотром", perio.get("ok") is True
                       and "Examen parodontal" in json.dumps(perio, ensure_ascii=False), str(perio)[:200])
                page = c.get(f"/admin/patient/{pid}/fisa043").body
                res.ok("043/e печатается с данными", "Maria Popescu" in page and "2003078140017" in page,
                       "в 043/e нет пациента или IDNP")
                res.ok("acord печатается с юрлицом демо", "Clinica Demo SRL" in c.get(f"/admin/patient/{pid}/acord").body,
                       "acord без юрлица")
                res.ok("карточка пациента (старая страница) открывается",
                       c.get(f"/admin/patient/{pid}?ui=legacy").status == 200, "")
            for path in ("/admin/all", "/admin/week", "/admin/medici", "/admin/stats",
                         "/admin/search", "/admin/settings"):
                res.check(f"{path} на засеве", c.get(path).status, 200)
            st = _j(c.get("/api/stats"))
            res.ok("аналитика считается на засеве", st.get("ok") is True, str(st)[:200])
    finally:
        shutil.rmtree(work, ignore_errors=True)
