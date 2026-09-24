"""Клиники: завести, показать, править, отказы формы, журнал."""
import sqlite3

from harness import Client, Result, Server, cid_from


def suite(res: Result) -> None:
    with Server() as s:
        c = Client(s.url).login()
        r = c.post("/admin/clinics", name="Clinica Exemplu", idno="1234567890123",
                   contact_name="Ion Popescu", email="clinica@example.md", phone="+373 60 000 000")
        res.ok("новая клиника: на карточку с кодом",
               r.status == 303 and r.location.startswith("/admin/clinics/c_")
               and r.location.endswith("?msg=clinic_ok"), f"{r.status} {r.location!r}")
        cid = cid_from(r.location)
        res.ok("идентификатор по схеме c_ + 12 hex", len(cid) == 14 and cid.startswith("c_"))
        page = c.get("/admin").body
        res.ok("список показывает клинику без файла",
               "Clinica Exemplu" in page and "нет файла" in page, "нет в списке")
        card = c.get(f"/admin/clinics/{cid}").body
        res.ok("карточка: IDNO, контакт, e-mail, форма выдачи",
               "1234567890123" in card and "Ion Popescu" in card and "clinica@example.md" in card
               and "Выдать файл" in card and "Файлов ещё не выдавали" in card)
        r = c.post("/admin/clinics", name="", idno="")
        res.check("без названия: отказ", r.location, "/admin?msg=bad_name")
        r = c.post("/admin/clinics", name="X", idno="12345")
        res.check("IDNO не 13 цифр: отказ", r.location, "/admin?msg=bad_idno")
        r = c.post("/admin/clinics", name="Fără IDNO", idno="")
        res.ok("без IDNO завести можно (пробный файл)", r.status == 303 and "msg=clinic_ok" in r.location)
        r = c.post(f"/admin/clinics/{cid}/edit", name="Clinica Exemplu SRL", idno="1234567890123",
                   contact_name="Ion Popescu", email="nou@example.md", phone="", address="Chișinău")
        res.check("правка реквизитов: сохранено", r.location, f"/admin/clinics/{cid}?msg=saved")
        card = c.get(f"/admin/clinics/{cid}").body
        res.ok("карточка после правки", "Clinica Exemplu SRL" in card and "nou@example.md" in card)
        res.check("чужой идентификатор: 404", c.get("/admin/clinics/c_000000000000").status, 404)
        con = sqlite3.connect(s.dir / "cloud.db")
        try:
            rows = con.execute("SELECT what FROM audit WHERE clinic_id=? ORDER BY id", (cid,)).fetchall()
        finally:
            con.close()
        res.check("журнал клиники: заведена, правлена", [r[0] for r in rows], ["clinic_new", "clinic_edit"])
