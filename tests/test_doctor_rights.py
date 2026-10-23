"""Права врача (Олег 22.10, подтверждено 23.10: «у врача виден только свой
график, а пациентов может видеть всех»).

Роль `medic` видит и правит в журнале ТОЛЬКО визиты своего врача: панель,
день, неделя, день врача, Excel дня, кресло, списки стойки. Чужой визит он не
видит, не добавляет, не двигает, не отменяет — и с ПК, и с телефона одинаково
(право, не канал). Картотека («Pacienți») открыта вся, но записать из фиши
можно только к себе. Учётка `medic` без привязки к врачу видит пустой журнал
и подсказку «contul nu e legat de un medic» (умолчание, названное Олегу).

⚠️ Ветка PIN-файла (`ADMIN_KEY` пустой): роль у ADMIN_KEY одна — директор, и
на нём ничего из этого не проверить. ⭐ Охрана проверяется на СЕРВЕРЕ, по
ответам `/api/*`: клиент чужих визитов не получает вовсе, но адрес набирается
руками, а вкладка живёт долго, — поэтому каждая команда к чужому визиту
обязана ответить отказом, а не «успехом» с пустыми данными.
"""
import io
import json
import pathlib
import sys
import zipfile
from datetime import timedelta

from harness import (Client, Result, Server, add_appt, appt_id, clinic_today,
                     day_model, panel_live, pid_by_phone, shell_model)

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "bot"))

NO_KEY = {"ADMIN_KEY": ""}          # без него издание уходит веткой ADMIN_KEY

# Врачи клиники прогона (`fixtures/clinic_test.json`): d2 и d3 активны.
D2, D3 = "Dr. Activ Doi", "Dr. Activ Trei"


def _j(r) -> dict:
    return json.loads(r.body)


def _params(page: str) -> dict:
    """Параметры узла React (`data-params`) — так их читает клиент."""
    if 'data-params="' not in page:
        return {}
    return json.loads(page.split('data-params="', 1)[1].split('"', 1)[0]
                      .replace("&quot;", '"'))


def _open_day(c: Client, start, days: int = 7) -> str:
    """Первый день с сеткой, начиная с `start`: у клиники прогона выходных
    нет, но правило держится не на этом — ищется день, где канва не пуста."""
    d = start
    for _ in range(days):
        if not day_model(c, d.isoformat())["canvas"]["empty"]:
            return d.isoformat()
        d += timedelta(days=1)
    raise AssertionError("за неделю не нашлось ни одного открытого дня")


def _login(url: str, pin: str) -> Client:
    c = Client(url)
    c.post("/admin/login", password=pin, next="/admin")
    return c


def _seed(boss: Client, day: str) -> None:
    """День двух врачей: у d2 два визита и заметка, у d3 визит."""
    add_appt(boss, day, "09:00", "Ion Popa", "069170170", doctor="d2")
    add_appt(boss, day, "11:00", "Vasile Lupu", "069170172", doctor="d2", service="long")
    add_appt(boss, day, "10:00", "Maria Rusu", "069170171", doctor="d3", service="pain")
    boss.post_json("/api/schedule/notes", {"date": day, "time": "15:00", "doctor": "d2",
                                          "text": "Livrare materiale"})


def _col_ids(canvas: dict) -> list:
    return [c["id"] for c in canvas["columns"]]


def _names(m: dict) -> list:
    return sorted(r["name"] for r in m["list"] if not r["is_note"])


def _sheet(c: Client, day: str) -> str:
    """Лист Excel дня текстом (xlsx — zip; строки в нём inline, `test_admin`)."""
    xl = c.get(f"/admin/export.xlsx?from={day}&to={day}")
    if xl.status != 200 or xl.raw[:2] != b"PK":
        raise AssertionError(f"выгрузка не отдана: {xl.status} {xl.raw[:40]!r}")
    with zipfile.ZipFile(io.BytesIO(xl.raw)) as z:
        return z.read("xl/worksheets/sheet1.xml").decode("utf-8")


def suite_rule(res: Result) -> None:
    """`auth.schedule_scope` — чистое правило: None всем с правом, ключ врача у
    привязанной учётки, пусто у непривязанной и у чужого ключа."""
    from app.core import auth  # noqa: E402 — только правило, без сервера
    known = {"d2": D2, "d3": D3}
    sc = auth.schedule_scope
    res.check("директор — весь журнал", sc({"role": "director", "doctor_id": "d2"}, known), None)
    res.check("регистратура — весь журнал", sc({"role": "receptie"}, known), None)
    res.check("врач с привязкой — свой ключ", sc({"role": "medic", "doctor_id": "d3"}, known), "d3")
    res.check("врач без привязки — ничей", sc({"role": "medic"}, known), "")
    res.check("врач, которого нет в справочнике, — ничей",
              sc({"role": "medic", "doctor_id": "d9"}, known), "")
    res.check("человека нет — ничей (как у can)", sc(None, known), "")
    res.check("неизвестная роль — ничей", sc({"role": "guest", "doctor_id": "d2"}, known), "")
    # право — строкой в PERMS, не сравнением роли (держит и test_structure)
    res.ok("право schedule_all у директора и регистратуры, у врача нет",
           auth.can({"role": "director"}, auth.PERM_SCHEDULE_ALL)
           and auth.can({"role": "receptie"}, auth.PERM_SCHEDULE_ALL)
           and not auth.can({"role": "medic"}, auth.PERM_SCHEDULE_ALL))


def suite_journal(res: Result) -> None:
    """Врач видит в журнале только свои визиты: день, панель, неделя, канва,
    Excel, кресло, страницы; команды к чужому визиту — отказ."""
    with Server(env=NO_KEY) as s:
        boss = Client(s.url)
        boss.post("/admin/setup", pin1="1111", pin2="1111")
        for body in ({"uid": "d2", "name": D2, "role": "medic", "doctor_id": "d2", "pin": "2222"},
                     {"uid": "ana", "name": "Ana R", "role": "receptie", "pin": "4444"}):
            res.check(f"учётка {body['role']} заведена",
                      boss.post_json("/api/settings/users", body).msg, "ok_user")
        day = _open_day(boss, clinic_today() + timedelta(days=3))
        _seed(boss, day)
        own = appt_id(boss, day, "Ion Popa")
        other = appt_id(boss, day, "Maria Rusu")
        med = _login(s.url, "2222")

        # ---- день «Programări» -------------------------------------------
        m = day_model(med, day)
        res.check("день врача: врачи шапки — только он", [x["id"] for x in m["doctors"]], ["d2"])
        res.check("день врача: колонка канвы — только его", _col_ids(m["canvas"]), ["d2"])
        res.check("день врача: список — только его визиты", _names(m), ["Ion Popa", "Vasile Lupu"])
        res.check("день врача: форма записи — только на него",
                  [x["id"] for x in m["form"]["doctors"]], ["d2"])
        res.ok("день врача: карточек чужого визита нет", str(other) not in m["cards"],
               "карточка чужого визита уехала врачу")
        res.ok("день врача без подсказки «не привязан»", m.get("notice") is None, repr(m.get("notice")))
        # общий день для врача — его день: факты карточки и календарь шапки (22.10, A + H)
        res.ok("общий день врача несёт факты и календарь, как день врача",
               isinstance(m.get("extras"), dict) and isinstance(m.get("minical"), dict),
               f"extras={type(m.get('extras'))}, minical={type(m.get('minical'))}")
        r = med.get(f"/api/schedule/day?date={day}&doctor=d3")
        res.check("день чужого врача — 403 other_doctor", (r.status, r.msg), (403, "other_doctor"))
        res.check("день своего врача адресом — открыт",
                  _col_ids(day_model(med, day, doctor="d2")["canvas"]), ["d2"])

        # ---- панель, канва, неделя --------------------------------------
        live = panel_live(med, day)
        res.check("панель: колонка — только его", _col_ids(live["canvas"]), ["d2"])
        res.ok("панель: повестка — только его визиты",
               live["agenda"]["items"] and all(it["doctor_id"] == "d2" for it in live["agenda"]["items"]),
               repr([(it["name"], it["doctor_id"]) for it in live["agenda"]["items"]]))
        res.check("панель: «primul loc liber» — только его окно",
                  [x["dk"] for x in live["desk"]["free"]], ["d2"])
        res.ok("панель: ответ детерминирован (второй опрос — 204)",
               med.get(f"/api/schedule/live?screen=panel&date={day}",
                       {"X-DP-Hash": med.get(f"/api/schedule/live?screen=panel&date={day}")
                        .header("X-DP-Hash")}).status == 204,
               "один и тот же день у одного человека даёт разный отпечаток")
        res.check("канва панели — только его колонка",
                  _col_ids(_j(med.get(f"/api/schedule/canvas?date={day}"))["data"]), ["d2"])
        week = _j(med.get(f"/api/schedule/week?date={day}"))["data"]
        wd = next(x for x in week["days"] if x["date"] == day)
        res.check("неделя: чипы дня — только его визиты",
                  sorted(x["name"] for x in wd["items"] if x["kind"] == "appt"),
                  ["Ion Popa", "Vasile Lupu"])
        boss_wd = next(x for x in _j(boss.get(f"/api/schedule/week?date={day}"))["data"]["days"]
                       if x["date"] == day)
        res.check("…а директор в той же неделе видит всех", boss_wd["count"], 3)

        # ---- списки стойки: обзвон на завтра — только его пациенты ----------
        nxt = _open_day(boss, clinic_today() + timedelta(days=1))
        add_appt(boss, nxt, "09:00", "Mâine Doi", "069170180", doctor="d2")
        add_appt(boss, nxt, "10:00", "Mâine Trei", "069170181", doctor="d3")
        conf = panel_live(med)["desk"]["confirm"]
        res.check("«De confirmat»: только его визит",
                  [(x["name"], x["doctor"]) for x in conf["items"]], [("Mâine Doi", D2)])
        res.check("…а у директора оба", len(panel_live(boss)["desk"]["confirm"]["items"]), 2)

        # ---- команды к чужому визиту — отказ, визит не тронут ---------------
        for label, r in (
            ("исход", med.post_json(f"/api/schedule/appointments/{other}/status", {"to": "cancelled"})),
            ("комментарий", med.post_json(f"/api/schedule/appointments/{other}/comment",
                                          {"comment": "hack"})),
            ("список процедур", med.get(f"/api/schedule/appointments/{other}/service")),
            ("смена процедуры", med.post_json(f"/api/schedule/appointments/{other}/service",
                                              {"service_id": "consult"})),
            ("перенос", med.post_json(f"/api/schedule/appointments/{other}/move",
                                      {"date": day, "time": "16:00", "doctor": "d3"})),
            ("перенос к себе", med.post_json(f"/api/schedule/appointments/{other}/move",
                                             {"date": day, "time": "16:00", "doctor": "d2"})),
            ("отметка звонка", med.post_json(f"/api/schedule/desk/call/{other}", {"result": "ok"})),
        ):
            res.check(f"чужой визит, {label} — 403 other_doctor", (r.status, r.msg),
                      (403, "other_doctor"))
        card = day_model(boss, day)["cards"][str(other)]
        res.check("чужой визит цел: статус, комментарий, час, врач",
                  (card["status"], card["comment"], card["time"], card["doctor"]),
                  ("confirmed", "", "10:00", D3))
        # запись и заметка к чужому врачу, перенос своего к чужому
        res.check("запись к чужому врачу — 403",
                  add_appt(med, day, "14:00", "Hack", "069170190", doctor="d3").msg, "other_doctor")
        res.check("заметка у чужого врача — 403",
                  med.post_json("/api/schedule/notes", {"date": day, "time": "16:00",
                                                       "doctor": "d3", "text": "x"}).msg,
                  "other_doctor")
        res.check("перенос своего визита к чужому врачу — 403",
                  med.post_json(f"/api/schedule/appointments/{own}/move",
                                {"date": day, "time": "16:00", "doctor": "d3"}).msg, "other_doctor")
        # свои команды работают, ответ — его день
        r = med.post_json(f"/api/schedule/appointments/{own}/comment", {"comment": "al meu"})
        res.ok("свой визит: комментарий сохранён, ответ — его день",
               r.msg == "ok_comment" and _col_ids(_j(r)["data"]["canvas"]) == ["d2"], f"{r!r}")
        res.check("запись к себе — ок",
                  add_appt(med, day, "14:00", "Al Meu", "069170191", doctor="d2").msg, "ok")
        res.check("кривой врач в записи остаётся кривым вводом, а не чужим",
                  add_appt(med, day, "14:30", "Zz", "069170192", doctor="zz").msg, "bad")

        # ---- Excel дня: те же строки, что в журнале -------------------------
        sheet = _sheet(med, day)
        res.ok("Excel врача: свои строки есть, чужой нет",
               "Ion Popa" in sheet and "Maria Rusu" not in sheet,
               "в выгрузке врача строка чужого визита")
        res.ok("Excel директора — все", "Maria Rusu" in _sheet(boss, day),
               "директор потерял строки выгрузки")

        # ---- кресло: только своё, чужой адрес заменяется своим --------------
        ch = _j(med.get("/api/chair?doctor=d3"))["data"]
        res.check("кресло: ?doctor=чужой → своё",
                  (ch["doctor"]["dk"], [x["dk"] for x in ch["doctors"]]), ("d2", ["d2"]))
        res.check("кресло директора по адресу — чужое открывается",
                  _j(boss.get("/api/chair?doctor=d3"))["data"]["doctor"]["dk"], "d3")
        res.check("страница кресла врача — параметр своего врача",
                  _params(med.get("/admin/cabinet?doctor=d3").body), {"doctor": "d2"})

        # ---- страницы и оболочка -------------------------------------------
        r = med.get("/admin/doctor/d3")
        res.check("страница дня чужого врача — на свой журнал",
                  (r.status in (303, 307), r.location), (True, "/admin/all"))
        res.check("страница своего дня — открыта", med.get("/admin/doctor/d2").status, 200)
        ident = shell_model(med.get("/admin").body)["identity"]
        res.check("оболочка врача: права и свой врач",
                  (ident["can"]["schedule_all"], ident["doctor"]), (False, "d2"))
        ident = shell_model(boss.get("/admin").body)["identity"]
        res.check("оболочка директора: весь журнал",
                  (ident["can"]["schedule_all"], ident["doctor"]), (True, ""))

        # ---- регистратура — весь журнал, как и раньше -----------------------
        rec = _login(s.url, "4444")
        res.check("регистратура: все врачи дня",
                  [x["id"] for x in day_model(rec, day)["doctors"]], ["d2", "d3", "d4"])
        res.check("регистратура правит любой визит",
                  rec.post_json(f"/api/schedule/appointments/{other}/comment",
                                {"comment": "ok"}).msg, "ok_comment")
        res.check("оболочка регистратуры: весь журнал",
                  shell_model(rec.get("/admin").body)["identity"]["can"]["schedule_all"], True)


def suite_unlinked(res: Result) -> None:
    """Учётка `medic` без привязки к врачу: пустой журнал везде и подсказка
    «contul nu e legat de un medic» — состоянием в модели, одним кодом."""
    with Server(env=NO_KEY) as s:
        boss = Client(s.url)
        boss.post("/admin/setup", pin1="1111", pin2="1111")
        res.check("учётка без врача заведена",
                  boss.post_json("/api/settings/users", {"uid": "nolink", "name": "Dr. Fără",
                                                        "role": "medic", "pin": "3333"}).msg,
                  "ok_user")
        day = _open_day(boss, clinic_today() + timedelta(days=3))
        _seed(boss, day)
        med = _login(s.url, "3333")
        code = "no_doctor_link"

        m = day_model(med, day)
        res.check("день: ни врачей, ни колонок, ни строк, ни формы",
                  ([x["id"] for x in m["doctors"]], _col_ids(m["canvas"]), m["list"], m["form"]),
                  ([], [], [], None))
        res.ok("день: подсказка «не привязан» со словами сервера",
               m["notice"] and m["notice"]["code"] == code and m["notice"]["tone"] == "warn"
               and "medic" in m["notice"]["text"], repr(m.get("notice")))
        live = panel_live(med, day)
        res.check("панель: пусто и подсказка",
                  (_col_ids(live["canvas"]), live["agenda"]["items"], live["desk"]["free"],
                   live["notice"]["code"]), ([], [], [], code))
        week = _j(med.get(f"/api/schedule/week?date={day}"))["data"]
        res.check("неделя: пусто и подсказка", (week["total"], week["notice"]["code"]), (0, code))
        ch = _j(med.get("/api/chair?doctor=d2"))["data"]
        res.check("кресло: ничьё, выбирать некого, подсказка",
                  (ch["doctor"], ch["doctors"], ch["notice"]["code"]), (None, [], code))
        res.ok("Excel: только шапка", "Ion Popa" not in _sheet(med, day) and "Maria Rusu" not in _sheet(med, day),
               "в выгрузке непривязанной учётки строки визитов")
        res.check("запись — 403", add_appt(med, day, "14:00", "Hack", "069170190").msg, "other_doctor")
        res.check("день врача адресом — 403",
                  med.get(f"/api/schedule/day?date={day}&doctor=d2").msg, "other_doctor")
        res.check("страница дня врача — на журнал", med.get("/admin/doctor/d2").location, "/admin/all")
        ident = shell_model(med.get("/admin").body)["identity"]
        res.check("оболочка: ни права, ни врача", (ident["can"]["schedule_all"], ident["doctor"]),
                  (False, ""))
        # привязал директор — журнал появился без перевхода (роль и врач — из файла)
        boss.post_json("/api/settings/users", {"uid": "nolink", "name": D3, "role": "medic",
                                              "doctor_id": "d3"})
        m = day_model(med, day)
        res.check("после привязки директором — его колонка и визит, подсказки нет",
                  (_col_ids(m["canvas"]), _names(m), m["notice"]), (["d3"], ["Maria Rusu"], None))


def suite_sms_and_card(res: Result) -> None:
    """SMS врачу закрыт целиком (экран и API, Олег 22.10); фиша открыта вся,
    но окно записи из неё — только к своему врачу."""
    with Server(env=NO_KEY) as s:
        boss = Client(s.url)
        boss.post("/admin/setup", pin1="1111", pin2="1111")
        for body in ({"uid": "d2", "name": D2, "role": "medic", "doctor_id": "d2", "pin": "2222"},
                     {"uid": "ana", "name": "Ana R", "role": "receptie", "pin": "4444"}):
            boss.post_json("/api/settings/users", body)
        day = _open_day(boss, clinic_today() + timedelta(days=3))
        _seed(boss, day)
        med, rec = _login(s.url, "2222"), _login(s.url, "4444")

        # ---- SMS: страница, API, меню ---------------------------------------
        r = med.get("/admin/settings/sms")
        res.ok("страница SMS врачу закрыта", r.status == 303 and "no_access" in r.location,
               f"код {r.status}, location {r.location!r}")
        for label, r in (("чтение", med.get("/api/settings/sms")),
                         ("сохранение", med.post_json("/api/settings/sms", {"day_before": True})),
                         ("обновление", med.post_json("/api/settings/sms/refresh", {}))):
            res.check(f"API SMS врачу: {label} — 403", (r.status, r.msg), (403, "no_access"))
        res.check("регистратуре API SMS открыт", rec.get("/api/settings/sms").status, 200)
        res.check("регистратуре страница SMS открыта", rec.get("/admin/settings/sms").status, 200)
        res.ok("в меню врача нет SMS",
               "sms" not in [x["key"] for x in shell_model(med.get("/admin").body)["nav"]["sync"]],
               "пункт SMS остался в меню врача")

        # ---- фиша: вся картотека, запись только к себе ----------------------
        pid = pid_by_phone(med, "069170171")          # Maria Rusu — пациентка d3
        card = _j(med.get(f"/api/patients/{pid}"))["data"]
        res.ok("врач открывает фишу чужого пациента", card["profile"]["name"] == "Maria Rusu",
               "картотека закрылась для врача")
        res.ok("в фише видны визиты у любого врача",
               any(v["doctor"] == D3 for v in card["visits"]["history"] + card["visits"]["live"]),
               "визиты чужого врача пропали из фиши")
        docs = card["appoint"]["doctors"]
        res.ok("окно записи фиши предлагает врачу только его самого",
               docs and all(set(v) <= {"d2"} for v in docs.values()) and any(docs.values()),
               repr(docs))
        res.ok("…а регистратуре — всех по услуге",
               any("d3" in v for v in _j(rec.get(f"/api/patients/{pid}"))["data"]["appoint"]["doctors"].values()),
               "регистратура потеряла врачей в окне записи фиши")
        nxt = _open_day(boss, clinic_today() + timedelta(days=5))
        r = med.post_json(f"/api/patients/{pid}/appoint", {"date": nxt, "time": "09:00",
                                                           "doctor": "d3", "service": "consult"})
        res.check("запись из фиши к чужому врачу — 403", (r.status, r.msg), (403, "other_doctor"))
        res.check("свободные часы чужого врача — пусто",
                  _j(med.get(f"/api/patients/{pid}/slots?date={nxt}&doctor=d3&service=consult"))
                  ["data"]["slots"], [])
        res.ok("свободные часы своего — есть",
               _j(med.get(f"/api/patients/{pid}/slots?date={nxt}&doctor=d2&service=consult"))
               ["data"]["slots"], "у своего врача нет ни одного часа")
        res.check("запись из фиши к себе — ок",
                  med.post_json(f"/api/patients/{pid}/appoint", {"date": nxt, "time": "09:00",
                                                                 "doctor": "d2", "service": "consult"}).msg,
                  "ok")
