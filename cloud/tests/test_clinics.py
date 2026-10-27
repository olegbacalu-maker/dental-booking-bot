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


TABS = ("overview", "pay", "lic", "sms", "access", "profile", "log")


def _pane(card: str, key: str) -> str:
    """Содержимое одной вкладки карточки: от её section до следующей."""
    start = card.index(f"<section class='pane' data-pane='{key}'>")
    end = card.find("<section class='pane'", start + 1)
    return card[start:end if end > 0 else len(card)]


def suite_tabs(res: Result) -> None:
    """Карточка клиники (16.10; 17.10 «Оплата» и «Лицензия» раздельно): обзор + вкладки в одной
    странице, «Ждёт вас» по состоянию, редкие формы за кнопкой, журнал словами с фильтрами."""
    with Server() as s:
        c = Client(s.url).login()
        cid = cid_from(c.post("/admin/clinics", name="Clinica Filă", idno="1234567890123",
                              contact_name="Ion", email="file@example.md").location)
        card = c.get(f"/admin/clinics/{cid}").body
        res.ok("семь вкладок и семь разделов, обзор первым, оплата перед лицензией",
               all(f"data-tab='{k}'" in card and f"data-pane='{k}'" in card for k in TABS)
               and card.index("data-pane='overview'") < card.index("data-pane='pay'") < card.index("data-pane='lic'"))
        res.ok("ни одного id с именем вкладки: метка #pay не прокручивает страницу",
               not any(f"id='{k}'" in card or f'id="{k}"' in card for k in TABS))
        res.ok("скрипт вкладок дописывает метку раздела в action формы",
               "closest('[data-pane]')" in card and "split('#')[0]+'#'" in card)
        res.ok("без файла: «Ждёт вас» говорит, что файл не выдан, и ведёт во вкладку лицензии",
               "Ждёт вас" in _pane(card, "overview") and "Файл лицензии не выдан" in card
               and "href='#lic'>Выдать</a>" in _pane(card, "overview"))
        res.ok("нота — во вкладке «Оплата», выдача вручную — во вкладке «Лицензия», не наоборот",
               f"/admin/clinics/{cid}/payments" in _pane(card, "pay") and f"/admin/clinics/{cid}/issue" in _pane(card, "lic")
               and f"/admin/clinics/{cid}/issue" not in _pane(card, "pay")
               and f"/admin/clinics/{cid}/payments" not in _pane(card, "lic"))
        res.ok("формы ноты и выдачи — за кнопкой (свёрнуты, пока не нажали)",
               "<details class='drop p'><summary>Выставить ноту</summary>" in _pane(card, "pay")
               and "<summary>Выдать вручную</summary>" in _pane(card, "lic"))
        res.ok("правка реквизитов — во вкладке «Реквизиты», не на обзоре",
               f"/admin/clinics/{cid}/edit" in _pane(card, "profile")
               and f"/admin/clinics/{cid}/edit" not in _pane(card, "overview"))
        c.post(f"/admin/clinics/{cid}/issue", kind="trial")
        card = c.get(f"/admin/clinics/{cid}").body
        res.ok("пробный выдан, ящик не подтверждён (27.10): в «Ждёт вас» одна строка — о e-mail",
               _pane(card, "overview").count("<li>") == 1 and "не подтверждён" in _pane(card, "overview"),
               _pane(card, "overview")[:1500])
        con = sqlite3.connect(s.dir / "cloud.db")
        con.execute("UPDATE clinics SET email_confirmed_at='2026-10-27T09:00:00Z' WHERE id=?", (cid,))
        con.commit()
        con.close()
        card = c.get(f"/admin/clinics/{cid}").body
        res.ok("пробный выдан, ноты нет, e-mail подтверждён: «Ничего не ждёт»",
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
        res.ok("вкладка оплаты считает ожидающую ноту", "Оплата<span class='n'>1</span>" in card)
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
        # журнал словами (17.10): слово видно, код — в подсказке; фильтр раздела отбирает строки, числа у всех
        log = _pane(c.get(f"/admin/clinics/{cid}").body, "log")
        res.ok("журнал: слова вместо кодов, код в подсказке",
               "title='payment_paid'>оплата подтверждена</span>" in log and ">payment_paid<" not in log
               and "title='issue'>файл выдан</span>" in log, log[:3000])
        res.ok("журнал: фильтры с числами по всем событиям клиники",
               f"href='/admin/clinics/{cid}?log=pay#log'>Оплата 2</a>" in log and "class='on'" in log, log[:1500])
        pay = _pane(c.get(f"/admin/clinics/{cid}?log=pay").body, "log")
        res.ok("фильтр «Оплата»: только оплаты, фильтр подсвечен, «Все» ведёт без фильтра",
               "оплата подтверждена" in pay and "файл выдан" not in pay and "реквизиты изменены" not in pay
               and f"<a class='on' href='/admin/clinics/{cid}?log=pay#log'>" in pay
               and f"href='/admin/clinics/{cid}#log'>Все " in pay, pay[:3000])
        res.ok("неизвестный раздел — как «Все»",
               "файл выдан" in _pane(c.get(f"/admin/clinics/{cid}?log=x%27%20or%201").body, "log"))


def _q(s: Server, sql: str, *args):
    con = sqlite3.connect(s.dir / "cloud.db")
    try:
        return con.execute(sql, args).fetchall()
    finally:
        con.close()


def suite_menu(res: Result) -> None:
    """Разделы меню (17.10, Олег: «сделать красиво и организованно с вкладками»): Клиники —
    вкладки и фильтр состояний; Платежи — ждут / оплачены за месяц с суммой / отклонены с
    причиной; Журнал — слова и фильтры; счётчики шапки — на каждой странице."""
    with Server() as s:
        c = Client(s.url).login()
        a = cid_from(c.post("/admin/clinics", name="Clinica Activă", idno="1234567890123", email="a@example.md").location)
        b = cid_from(c.post("/admin/clinics", name="Clinica Fără Fișier", email="b@example.md").location)
        c.post(f"/admin/clinics/{a}/issue", kind="trial")
        c.post(f"/admin/clinics/{a}/payments", months="1", amount="", method="transfer")
        paid_ref, paid_sum = _q(s, "SELECT reference, amount FROM payments WHERE clinic_id=?", a)[0]
        c.post(f"/admin/payments/{_q(s, 'SELECT id FROM payments WHERE reference=?', paid_ref)[0][0]}/confirm")
        c.post(f"/admin/clinics/{a}/payments", months="1", amount="", method="transfer")
        wait_ref, wait_id = _q(s, "SELECT reference, id FROM payments WHERE status='pending'")[0]
        c.post(f"/admin/clinics/{b}/payments", months="1", amount="", method="transfer")
        rej_ref, rej_id = _q(s, "SELECT reference, id FROM payments WHERE clinic_id=?", b)[0]
        c.post(f"/admin/payments/{rej_id}/reject", reason="nu a venit transferul")

        lst = c.get("/admin").body
        res.ok("Клиники: две вкладки — список и заявки, список первым",
               "data-tab='list'" in lst and "data-tab='requests'" in lst
               and lst.index("data-pane='list'") < lst.index("data-pane='requests'"))
        res.ok("Клиники: состояния — кнопки-фильтры с числами",
               "Состояния:" in lst and "href='/admin?state=active'>действует 1</a>" in lst
               and "href='/admin?state=none'>нет файла 1</a>" in lst and "<a class='on' href='/admin'>Все 2</a>" in lst)
        only_none = c.get("/admin?state=none").body
        res.ok("фильтр «нет файла»: только клиника без файла, фильтр подсвечен",
               "Clinica Fără Fișier" in only_none and "Clinica Activă" not in only_none
               and "<a class='on' href='/admin?state=none'>" in only_none)
        res.ok("«+ Новая клиника» — форма за кнопкой", "<summary>+ Новая клиника</summary>" in lst
               and "action='/admin/clinics'" in lst)
        res.ok("без заявок: вкладка заявок спокойна и без счётчика",
               "Новых заявок на пробный период нет" in lst and "Заявки на пробный<span class='n'>" not in lst)

        pay = c.get("/admin/payments").body
        wait = _pane(pay, "wait")
        res.ok("Платежи: три вкладки, ждущая нота — в «Ждут подтверждения» со счётчиком",
               all(f"data-tab='{k}'" in pay for k in ("wait", "paid", "rejected"))
               and wait_ref in wait and paid_ref not in wait and "Ждут подтверждения<span class='n'>1</span>" in pay)
        paid = _pane(pay, "paid")
        res.ok("«Оплачены»: этот месяц, сумма и число платежей, cont PDF",
               paid_ref in paid and f"<b>{paid_sum} MDL</b> · 1 платёж</p>" in paid and "Пришло в " in paid
               and "cont PDF" in paid and wait_ref not in paid, paid[:2500])
        rej = _pane(pay, "rejected")
        res.ok("«Отклонены»: нота и причина из журнала", rej_ref in rej and "nu a venit transferul" in rej, rej[:2000])
        res.ok("чужой месяц в адресе — показан последний, без падения",
               paid_ref in _pane(c.get("/admin/payments?month=1999-01").body, "paid"))
        r = c.post(f"/admin/payments/{wait_id}/confirm", headers={"Referer": s.url + "/admin/payments?msg=payment_confirmed"})
        res.ok("подтверждение со страницы платежей после прошлого действия (адрес с ?msg=) — обратно туда же",
               r.status == 303 and r.location.startswith("/admin/payments?"), r.location)

        log = c.get("/admin/audit").body
        res.ok("Журнал: слова вместо кодов, фильтры с числами",
               "title='payment_paid'>оплата подтверждена</span>" in log and "title='clinic_new'>клиника заведена</span>" in log
               and "href='/admin/audit?kind=pay'>Оплата " in log, log[:2500])
        only_pay = c.get("/admin/audit?kind=pay").body
        res.ok("фильтр «Оплата»: оплаты есть, заведение клиник нет",
               "оплата подтверждена" in only_pay and "клиника заведена" not in only_pay
               and "<a class='on' href='/admin/audit?kind=pay'>" in only_pay)

        c.post(f"/admin/clinics/{b}/payments", months="1", amount="", method="transfer")  # снова одна ждущая
        for path in ("/admin", "/admin/payments", "/admin/fleet", "/admin/sms", "/admin/audit", f"/admin/clinics/{a}"):
            body = c.get(path).body
            res.ok(f"счётчик шапки «Платежи (1)» на {path}", "href='/admin/payments'>Платежи (1)</a>" in body)
        keys = ("list", "requests", "wait", "paid", "rejected", "all", "behind", "silent", "multi",
                "summary", "names", "failures", "tools")
        bodies = [c.get(p).body for p in ("/admin", "/admin/payments", "/admin/fleet", "/admin/sms")]
        res.ok("разделы меню: ни одного id с именем вкладки (метка адреса не прокручивает страницу)",
               not any(f"id='{k}'" in b or f'id="{k}"' in b for k in keys for b in bodies)
               and all(f"data-pane='{k}'" in "".join(bodies) for k in keys))


def suite_audit_words(res: Result) -> None:
    """Журнал словами (17.10): у каждого кода, который пишет сервер, есть слово и раздел в
    `views.AUDIT_RU` — иначе строка журнала видна сырым кодом и не попадает ни в один фильтр."""
    import ast
    import sys

    from harness import CLOUD
    sys.path.insert(0, str(CLOUD))
    from app import views  # noqa: E402

    codes: set[str] = set()
    for f in sorted((CLOUD / "app").glob("*.py")):
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.Call) and len(node.args) >= 3):
                continue
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            if name != "audit":
                continue
            for sub in ast.walk(node.args[2]):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    codes.add(sub.value)
    res.ok("исходники нашлись: кодов журнала больше двадцати", len(codes) > 20, sorted(codes))
    res.check("каждый код журнала — со словом и разделом", sorted(codes - set(views.AUDIT_RU)), [])
    cats = {k for k, _ in views.AUDIT_CATS}
    res.check("раздел каждого слова — из списка фильтров",
              sorted(w for w, (_, c) in views.AUDIT_RU.items() if c not in cats), [])
