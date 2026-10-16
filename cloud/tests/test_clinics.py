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
               and "Лицензия вручную" in card and "Файлов ещё не выдавали" in card)
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


TABS = ("overview", "pay", "sms", "access", "profile", "log")


def _pane(card: str, key: str) -> str:
    """Содержимое одной вкладки карточки: от её section до следующей."""
    start = card.index(f"<section class='pane' data-pane='{key}'>")
    end = card.find("<section class='pane'", start + 1)
    return card[start:end if end > 0 else len(card)]


def suite_tabs(res: Result) -> None:
    """Карточка клиники (16.10): обзор + вкладки в одной странице, «Ждёт вас» по состоянию."""
    with Server() as s:
        c = Client(s.url).login()
        cid = cid_from(c.post("/admin/clinics", name="Clinica Filă", idno="1234567890123",
                              contact_name="Ion", email="file@example.md").location)
        card = c.get(f"/admin/clinics/{cid}").body
        res.ok("шесть вкладок и шесть разделов, обзор первым",
               all(f"data-tab='{k}'" in card and f"data-pane='{k}'" in card for k in TABS)
               and card.index("data-pane='overview'") < card.index("data-pane='pay'"))
        res.ok("ни одного id с именем вкладки: метка #pay не прокручивает страницу",
               not any(f"id='{k}'" in card or f'id="{k}"' in card for k in TABS))
        res.ok("скрипт вкладок дописывает метку раздела в action формы",
               "closest('[data-pane]')" in card and "split('#')[0]+'#'" in card)
        res.ok("без файла: «Ждёт вас» говорит, что файл не выдан, и ведёт во вкладку оплаты",
               "Ждёт вас" in _pane(card, "overview") and "Файл лицензии не выдан" in card and "href='#pay'" in card)
        res.ok("формы раздела оплаты лежат во вкладке оплаты",
               f"/admin/clinics/{cid}/payments" in _pane(card, "pay") and f"/admin/clinics/{cid}/issue" in _pane(card, "pay"))
        res.ok("правка реквизитов — во вкладке «Реквизиты», не на обзоре",
               f"/admin/clinics/{cid}/edit" in _pane(card, "profile")
               and f"/admin/clinics/{cid}/edit" not in _pane(card, "overview"))
        c.post(f"/admin/clinics/{cid}/issue", kind="trial")
        card = c.get(f"/admin/clinics/{cid}").body
        res.ok("пробный выдан, ноты нет, e-mail есть: «Ничего не ждёт»",
               "Ничего не ждёт" in card and "Ждёт вас" not in card, _pane(card, "overview")[:1500])
        c.post(f"/admin/clinics/{cid}/payments", months="1", amount="", method="transfer")
        card = c.get(f"/admin/clinics/{cid}").body
        con = sqlite3.connect(s.dir / "cloud.db")
        try:
            pid, ref = con.execute("SELECT id, reference FROM payments WHERE clinic_id=?", (cid,)).fetchone()
        finally:
            con.close()
        ov = _pane(card, "overview")
        res.ok("ожидающая нота: на обзоре её reference и «Подтвердить»",
               "Ждёт вас" in ov and ref in ov and f"/admin/payments/{pid}/confirm" in ov, ov[:2000])
        res.ok("вкладка оплаты считает ожидающую ноту", "Лицензия и оплата<span class='n'>1</span>" in card)
        r = c.post(f"/admin/payments/{pid}/confirm")
        res.ok("подтверждение с обзора возвращает на карточку без своей метки (метку держит браузер)",
               r.status == 303 and r.location.startswith(f"/admin/clinics/{cid}?") and "#" not in r.location,
               f"{r.status} {r.location!r}")
        card = c.get(f"/admin/clinics/{cid}").body
        res.ok("после подтверждения снова спокойно", "Ничего не ждёт" in card)
        c.post(f"/admin/clinics/{cid}/edit", name="Clinica Filă", idno="1234567890123", contact_name="Ion",
               email="", phone="", address="")
        res.ok("без e-mail: «Ждёт вас» просит вписать его",
               "нет e-mail" in _pane(c.get(f"/admin/clinics/{cid}").body, "overview"))
