"""Охрана доступа, страницы журнала, настройки с горячей перезагрузкой,
карточка пациента и чистые функции расписания.
"""
import json
import os
import subprocess
from datetime import date, timedelta

from harness import BOT, PIN, PYTHON, Client, Result, Server


def _d(offset: int) -> str:
    return (date.today() + timedelta(days=offset)).isoformat()


def suite_auth(res: Result) -> None:
    with Server() as s:
        anon = Client(s.url)
        for path in ("/admin", "/admin/all", "/admin/settings", "/admin/stats"):
            r = anon.get(path)
            res.ok(f"без входа {path} не отдаётся",
                   r.status == 303 and "/admin/login" in r.location,
                   f"код {r.status}, location {r.location!r}")

        bad = Client(s.url)
        bad.post("/admin/login", password="wrong-pin", next="/admin")
        res.ok("неверный пароль не пускает",
               bad.get("/admin").status == 303, "пустил в журнал")

        good = Client(s.url).login()
        res.ok("верный пароль пускает", good.get("/admin").status == 200,
               "не пустил")
        res.ok("health отвечает всегда",
               json.loads(anon.get("/health").body).get("app") == "dentpilot",
               "health не тот")


def suite_pages(res: Result) -> None:
    """Страницы отдаются и содержат то, ради чего открываются."""
    with Server() as s:
        c = Client(s.url).login()
        c.post("/admin/add", adate=_d(1), atime="10:00", adoctor="d2",
               aservice="consult", aname="Pagina Test", aphone="022321321",
               back="/admin/all")

        pages = {
            "/admin": "Clinica Test",
            f"/admin/all?date={_d(1)}": "Pagina Test",
            "/admin/week": "",
            "/admin/stats": "",
            "/admin/settings": "Clinica Test",
            "/admin/medici": "Dr. Activ Doi",
            "/admin/search?q=Pagina": "Pagina Test",
            "/admin/qr-print": "",
        }
        for path, needle in pages.items():
            r = c.get(path)
            res.ok(f"страница {path} открывается", r.status == 200,
                   f"код {r.status}")
            if needle and r.status == 200:
                res.ok(f"страница {path} содержит нужное", needle in r.body,
                       f"нет {needle!r}")

        csv = c.get(f"/admin/export?from={_d(1)}&to={_d(1)}")
        res.ok("экспорт CSV отдаётся", csv.status == 200 and "Pagina Test" in csv.body,
               f"код {csv.status}")

        css = c.get("/admin").body
        res.ok("стили на странице есть", ".banner" in css, "CSS не подключён")


def suite_patient_card(res: Result) -> None:
    """Фиша: профиль, зубная формула, план лечения, алерты, архив."""
    with Server() as s:
        c = Client(s.url).login()
        c.post("/admin/add", adate=_d(1), atime="09:00", adoctor="d2",
               aservice="consult", aname="Card Test", aphone="022654654",
               back="/admin/all")
        pid = c.get("/admin/search?q=022654654").body.split(
            "/admin/patient/", 1)[1].split("'")[0].split('"')[0].split("?")[0]

        r = c.post(f"/admin/patient/{pid}/save", name="Card Test Nou",
                   phone="022654654", email="test@example.com")
        res.check("профиль сохраняется", r.msg, "ok_card")
        res.ok("новое имя видно в карточке",
               "Card Test Nou" in c.get(f"/admin/patient/{pid}").body,
               "имя не обновилось")

        r = c.post(f"/admin/patient/{pid}/tooth", tooth="11", state="caries",
                   note="test", doctor="d2")
        res.ok("зуб отмечается", r.status == 303, f"код {r.status}")

        r = c.post(f"/admin/patient/{pid}/plan", procedure="Plombă 11",
                   tooth="11", price="1200")
        res.ok("пункт плана добавляется", r.status == 303, f"код {r.status}")
        res.ok("пункт плана виден в карточке",
               "Plombă 11" in c.get(f"/admin/patient/{pid}").body,
               "плана нет на странице")

        r = c.post(f"/admin/patient/{pid}/alert", kind="allergy",
                   text="Alergie la penicilină")
        res.ok("предупреждение добавляется", r.status == 303, f"код {r.status}")
        res.ok("предупреждение видно в карточке",
               "penicilină" in c.get(f"/admin/patient/{pid}").body,
               "алерт не показан")

        # архив = скрыть из списка «недавних», но по явному запросу найти можно:
        # карточку с историей лечения нельзя терять, её именно прячут
        c.post(f"/admin/patient/{pid}/archive", on="1")
        res.ok("архивный ушёл из списка недавних",
               "Card Test Nou" not in c.get("/admin/search").body,
               "архивный всё ещё в недавних")
        res.ok("архивный находится по явному поиску",
               "Card Test Nou" in c.get("/admin/search?q=Card+Test").body,
               "архивный потерялся совсем")


def suite_settings(res: Result) -> None:
    """Настройки клиники применяются на лету — без перезапуска программы."""
    with Server() as s:
        c = Client(s.url).login()
        cfg = json.loads(s.clinic.read_text(encoding="utf-8"))
        cfg["name"] = "Clinica Redenumită"
        r = c.post("/admin/settings/save",
                   payload=json.dumps(cfg, ensure_ascii=False))
        res.check("настройки сохраняются", r.msg, "ok_set")
        res.ok("новое название видно сразу",
               "Clinica Redenumită" in c.get("/admin").body,
               "hot-reload не сработал")
        res.ok("название записано в файл клиники",
               "Clinica Redenumită" in s.clinic.read_text(encoding="utf-8"),
               "clinic.json не переписан")


def suite_pure(res: Result) -> None:
    """Чистая логика расписания — без сервера и без базы."""
    code = r"""
import json, sys
sys.path.insert(0, r"%s")
from datetime import datetime, timedelta, date
from app import engine as eng
now = datetime.now(eng.TZ)
out = {
 "past_hour":      eng.is_past(now - timedelta(hours=1)),
 "future_hour":    eng.is_past(now + timedelta(hours=1)),
 "past_day":       eng.is_past_day(date.today() - timedelta(days=1)),
 "today_not_past": eng.is_past_day(date.today()),
 "dur_default":    eng.svc_duration("consult"),
 "dur_long":       eng.svc_duration("long"),
 "dur_unknown":    eng.svc_duration("nope"),
 "fits_noon":      eng.fits_clinic(now.replace(hour=12, minute=0), 60),
 "orphan_docs":    eng.allowed_doc_items("orphan"),
 "consult_docs":   len(eng.allowed_doc_items("consult")),
}
print(json.dumps(out))
""" % str(BOT)
    # ⚠️ окружение НАСЛЕДУЕТСЯ: с обрезанным PATH Windows не грузит winsock,
    # и import asyncio падает на ровном месте (WinError 10106)
    env = dict(os.environ)
    env["CLINIC_CONFIG"] = str(_fixture())
    p = subprocess.run([str(PYTHON), "-c", code], cwd=str(BOT), text=True,
                       capture_output=True, env=env)
    if p.returncode != 0:
        res.failed.append(("чистые функции: запуск", p.stderr[-500:]))
        return
    v = json.loads(p.stdout)
    res.check("прошедший час — в прошлом", v["past_hour"], True)
    res.check("будущий час — не в прошлом", v["future_hour"], False)
    res.check("вчерашний день закрыт", v["past_day"], True)
    res.check("сегодня НЕ закрытый день", v["today_not_past"], False)
    res.check("длительность по умолчанию", v["dur_default"], 60)
    res.check("длительность из конфига", v["dur_long"], 120)
    res.check("неизвестная услуга — дефолт", v["dur_unknown"], 60)
    res.check("полдень в графике", v["fits_noon"], True)
    res.check("услугу без активных врачей выполнять некому",
              v["orphan_docs"], [])
    res.check("консультацию выполняют все активные", v["consult_docs"], 3)


def _fixture():
    from harness import FIXTURES
    return FIXTURES / "clinic_test.json"
