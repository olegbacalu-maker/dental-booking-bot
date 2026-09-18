"""Фиша пациента (C18): поведение старой страницы записано руками, а JSON API
`/api/patients/{pid}` обязан повторять её цифры, порядок и слова.

Что стережётся. У `GET /admin/patient/{pid}` девятьсот строк одной функцией и
пятнадцать обращений к базе; вся арифметика фиши (сумма активного плана,
прогресс без отказов, долг, «следующий» и «последний» визит, пилюли шапки,
цифры KPI, риски анамнеза) жила внутри f-строк и проверялась только через
готовую разметку. Здесь она впервые получает СВОИ проверки: `suite_pin`
записывает старую страницу как эталон на пациенте, у которого есть каждая
ветка, `suite_api` сверяет с ней ответ API строка в строку, `suite_actions`
гоняет действия фиши через JSON с теми же кодами, что у форм.
"""
import json
import re
from datetime import timedelta

from harness import Client, Result, Server, clinic_today

PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 64
PDF = b"%PDF-1.4 " + b"x" * 64


def _d(offset: int) -> str:
    return (clinic_today() + timedelta(days=offset)).isoformat()


def _dmy(offset: int) -> str:
    return (clinic_today() + timedelta(days=offset)).strftime("%d.%m.%Y")


def _j(r) -> dict:
    return json.loads(r.body)


def _pid(c: Client, phone: str) -> int:
    return int(c.get(f"/admin/search?q={phone}").body.split(
        "<tr id='plr", 1)[1].split("'", 1)[0])


def _aid(c: Client, day: str) -> int:
    """id последней записи дня — со страницы дня, как в test_visit."""
    return int(re.findall(r"/admin/status/(\d+)", c.get(f"/admin/all?date={day}").body)[-1])


def _seed(c: Client) -> dict:
    """Пациент с каждой веткой фиши: четыре визита (прошлый завершённый с
    дневником, отменённый, прошлый подтверждённый без дневника, будущий),
    план из пяти позиций во всех четырёх статусах с просроченным сроком и
    позицией без цены, платёж и возврат, четыре предупреждения (в шапку
    попадают три), анамнез с галочками и свободным текстом, три документа
    трёх видов (картинка, PDF, чужая программа), два зуба, один из них
    имплант."""
    def visit(day: int, time: str, doc: str, svc: str = "consult") -> int:
        c.post("/admin/add", adate=_d(day), atime=time, adoctor=doc, aservice=svc,
               aname="Pin Test", aphone="069000111", back="/admin/all")
        return _aid(c, _d(day))

    s = {}
    s["v_done"] = visit(-10, "10:00", "d2")
    c.post(f"/admin/status/{s['v_done']}", to="done", back="/admin/all")
    c.post(f"/admin/visit/{s['v_done']}", acuze="Durere", diagnostic="Pulpită 26",
           tratament="Trat")
    s["v_canc"] = visit(-3, "11:00", "d3", "hygiene")
    c.post(f"/admin/status/{s['v_canc']}", to="cancelled", back="/admin/all")
    s["v_last"] = visit(-1, "12:00", "d2")
    s["v_next"] = visit(2, "09:30", "d2")
    pid = s["pid"] = _pid(c, "069000111")
    c.post(f"/admin/patient/{pid}/save", name="Pin Test", phone="069000111",
           birth_date="1985-03-07", gender="f", idnp="2000000000001",
           email="pin@example.com", address="str. Pin 1", insurance="CNAM activă",
           primary_doctor="Dr. Activ Doi", file_no="D-5", notes="nota internă")
    c.post(f"/admin/patient/{pid}/tooth", tooth="11", state="carie", note="distal",
           doctor="Dr. Activ Doi")
    c.post(f"/admin/patient/{pid}/tooth", tooth="36", state="implant", doctor="Dr. Activ Doi")
    for proc, tooth, price, due in (("Coroană 11", "11", "1200", ""),
                                    ("Detartraj", "", "500", ""),
                                    ("Extracție 48", "48", "700", "2020-01-01"),
                                    ("Consult gratuit", "", "", ""),
                                    ("Implant 36", "36", "9000", "")):
        c.post(f"/admin/patient/{pid}/plan", procedure=proc, tooth=tooth, price=price,
               due_date=due, doctor="Dr. Activ Doi" if proc == "Coroană 11" else "")
    page = c.get(f"/admin/patient/{pid}").body
    ids = sorted({int(x) for x in re.findall(r"/plan/(\d+)/status", page)})
    s["p_lucru"], s["p_fin"], s["p_due"], s["p_free"], s["p_refuz"] = ids
    c.post(f"/admin/patient/{pid}/plan/{s['p_lucru']}/status", to="in_lucru")
    c.post(f"/admin/patient/{pid}/plan/{s['p_fin']}/status", to="in_lucru")
    c.post(f"/admin/patient/{pid}/plan/{s['p_fin']}/status", to="finalizat")
    c.post(f"/admin/patient/{pid}/plan/{s['p_refuz']}/status", to="refuzat",
           motiv="refuză implantul")
    c.post(f"/admin/patient/{pid}/pay", amount="300", method="numerar", note="avans")
    c.post(f"/admin/patient/{pid}/pay", amount="-100", method="card", note="restituire")
    for kind, text in (("allergy", "Penicilină"), ("medication", "Anticoagulante"),
                       ("warning", "Leșină"), ("info", "Vorbește rusă")):
        c.post(f"/admin/patient/{pid}/alert", kind=kind, text=text)
    c.post(f"/admin/patient/{pid}/anamneza", fl=["diabet", "cardio"], alergii="latex")
    c.post_file(f"/admin/patient/{pid}/doc", "file", "rx.png", PNG, mime="image/png",
                category="radiografie")
    c.post_file(f"/admin/patient/{pid}/doc", "file", "acord.pdf", PDF,
                mime="application/pdf", category="acord")
    c.post_file(f"/admin/patient/{pid}/doc", "file", "trimitere.docx", b"PK" + b"x" * 64,
                category="trimitere")
    return s


# ---- разбор старой страницы: то, что сверяется с API ----

def _plan_rows(page: str) -> list[tuple[str, str, bool]]:
    """(статус, процедура, спрятана ли строка) в порядке страницы."""
    return [(st, proc, "display:none" in attrs) for st, attrs, proc in re.findall(
        r"<div class='plan-row[^>]*data-st='(\w+)'([^>]*)>.*?<span class='pp'>([^<]+)",
        page, re.S)]


def _pills(page: str) -> list[tuple[str, str]]:
    block = page.split("<div class='hero-badges'>", 1)[1].split("</div>", 1)[0]
    return [(tone, text.strip()) for tone, text in
            re.findall(r"<span class='pill (\w+)'>(?:<svg.*?</svg>)?([^<]*)</span>", block, re.S)]


def _kpi(page: str) -> list[tuple[str, str, str]]:
    return re.findall(r"<b>([^<]*)</b><span>([^<]*)</span><small>([^<]*)</small></div></button>",
                      page.split("<div class='kpi5'>", 1)[1].split("<div class='pv2'>", 1)[0])


def _hist(page: str) -> list[tuple[str, str, str]]:
    """(дата и статус, услуга, хвост дневника) строк истории визитов."""
    block = page.split("<h3>Istoric vizite", 1)[1].split("Vezi tot istoricul", 1)[0]
    return [(when, svc, re.sub(r"<svg.*?</svg> ", "", tail))
            for when, svc, tail in re.findall(
                r"<small>([^<]*)</small><b[^>]*>([^<]*)</b><small>[^<]*</small>(.*?)</div></div>",
                block, re.S)]


def _acti(page: str) -> list[str]:
    return re.findall(r"<div class='ab'><b>([^<]*)</b>", page)


def _frows(page: str) -> list[tuple[str, str]]:
    return re.findall(r"<div class='frow'><span>([^<]*)</span><span class='v[^']*'>([^<]*)</span>",
                      page.split("<h3>Date pacient</h3>", 1)[1].split("id='pedit'", 1)[0])


def suite_pin(res: Result) -> None:
    """Старая фиша — эталон, записанный руками на засеянном пациенте."""
    with Server() as s:
        c = Client(s.url).login()
        sd = _seed(c)
        pid = sd["pid"]
        page = c.get(f"/admin/patient/{pid}").body

        # ---- шапка ----
        res.check("инициалы", re.search(r"<div class='hero-av'>([^<]*)<", page).group(1), "PT")
        meta = re.findall(r"<span>([^<]*)</span>",
                          page.split("<div class='hero-meta'>", 1)[1].split("</div>", 1)[0])
        res.check("строка под именем: возраст, канал, дело, год фиши",
                  meta[:4], ["41 ani", "recepție", "dosar D-5", "Pacient din " + _dmy(0)[-4:]])
        res.ok("номер фиши копируется кликом", f"data-id='{pid}'" in page and f"ID #{pid}" in page,
               "нет idchip")
        res.check("пилюли: активен, ТРИ первых предупреждения, страховка, долг, импланты",
                  _pills(page),
                  [("green", "Pacient activ"), ("orange", "Penicilină"),
                   ("orange", "Anticoagulante"), ("red", "Leșină"), ("green", "CNAM activă"),
                   ("red", "De achitat: 300 MDL"), ("purple", "1 implant")])
        res.check("сбоку: последний визит и медик курант",
                  re.findall(r"<div class='hs'><span>([^<]*)</span><b>([^<]*)</b>(?:<div[^>]*>([^<]*)</div>)?", page),
                  [("Ultima vizită", _dmy(-1), "Consultație"),
                   ("Medic curant", "Dr. Activ Doi", "din fișa pacientului")])
        res.ok("быстрые действия: звонок, письмо, запись, 043/e",
               "href='tel:069000111'" in page and "href='mailto:pin@example.com'" in page
               and "onclick='openAppt()'" in page and f"/admin/patient/{pid}/fisa043'" in page,
               "не все действия")

        # ---- KPI: пять цифр и откуда они ----
        res.check("KPI: визиты без отменённого, активные, давность, следующий, готово",
                  _kpi(page),
                  [("3", "Vizite în total", "din " + _dmy(0)[-4:]),
                   ("3", "Proceduri active", "în planul de tratament"),
                   ("1 zile", "Ultima vizită", _dmy(-1)),
                   (_dmy(2)[:5], "Următoarea vizită", "09:30"),
                   ("1", "Proceduri finalizate", "istoric complet")])
        kpi = json.loads(re.search(r"const KPI = (.*?);\n", page).group(1))
        res.ok("список за цифрой «визиты» — три живых и строка про отменённый",
               kpi["visits"][1].count("<div class='lrow'>") == 3
               and "+ 1 anulate" in kpi["visits"][1], kpi["visits"][1][:200])
        res.ok("за «активные» — три позиции и ссылка на план",
               kpi["active"][1].count("<div class='lrow'>") == 3 and "#plan" in kpi["active"][1],
               kpi["active"][1][:200])
        res.ok("за «последний визит» — давность словами", "acum 1 zile" in kpi["last"][1],
               kpi["last"][1])

        # ---- план ----
        res.check("порядок плана: в работе, планируемое по сроку, готовое, отказ; закрытые спрятаны",
                  _plan_rows(page),
                  [("in_lucru", "Coroană 11", False), ("planificat", "Extracție 48", False),
                   ("planificat", "Consult gratuit", False), ("finalizat", "Detartraj", True),
                   ("refuzat", "Implant 36", True)])
        res.ok("активный план = в работе + запланированное с ценой, без отказа и без готового",
               "plan activ: 1 900 MDL" in page and "<b>1 900 MDL</b>" in page
               and "finalizate: 500 MDL" in page, "сумма плана не та")
        res.ok("прогресс без отказа в знаменателе",
               "<small>1/4 finalizate · 1 refuzate</small>" in page
               and "style='width:25%'" in page, "прогресс не тот")
        res.ok("вкладки со счётом, активная по умолчанию",
               "class='on' data-f='act' onclick='planTab(this)'>Active (3)" in page
               and ">Finalizate (1)<" in page and ">Refuzate (1)<" in page
               and ">Toate (5)<" in page, "вкладки не те")
        res.ok("просроченный срок подсвечен", "title='Termen depășit'" in page
               and "01.01.2020" in page, "срок не подсвечен")
        rows = page.split("<div class='plan-row")
        lucru = next(r for r in rows if "Coroană 11" in r)
        plan_ = next(r for r in rows if "Extracție 48" in r)
        fin = next(r for r in rows if "data-st='finalizat'" in r)
        ref = next(r for r in rows if "data-st='refuzat'" in r)
        res.ok("в работе: Finalizează и Refuz, без удаления",
               "Finalizează" in lucru and "Refuz" in lucru and "/del'" not in lucru, "кнопки не те")
        res.ok("запланировано: Începe, Refuz и удаление",
               "Începe" in plan_ and "Refuz" in plan_ and f"/plan/{sd['p_due']}/del" in plan_,
               "кнопки не те")
        res.ok("готово: только Redeschide и дата", "Redeschide" in fin and "Începe" not in fin
               and "Refuz" not in fin and _dmy(0) in fin, "кнопки не те")
        res.ok("отказ: причина под процедурой и Reia",
               "<em class='pmotiv'>refuză implantul</em>" in ref and "Reia" in ref
               and "Data refuzului" in ref, "отказ не тот")
        res.ok("лист согласия в шапке плана", f"/admin/patient/{pid}/plan-acord" in page,
               "нет acord")

        # ---- платежи ----
        res.ok("итоги: начислено 500, оплачено 200, долг 300",
               "lucrări finalizate: 500 MDL · plătit: 200 MDL" in page
               and "<div class='sold bad'><span>De achitat</span><b>300 MDL</b>" in page,
               "сальдо не то")
        pays = re.findall(r"<div class='pay-row( neg)?'>.*?<b class='pa'>([^<]*)</b><span class='pn'>([^<]*)</span>",
                          page, re.S)
        res.check("платежи: свежие первыми, возврат с минусом, кто принял",
                  pays, [(" neg", "- 100 MDL", "restituire · Director"),
                         ("", "300 MDL", "avans · Director")])
        res.ok("директор видит удаление платежа", "/pay/" in page and "/del'" in page, "нет")

        # ---- документы ----
        docs = re.findall(r"<div class='doccard'><a href='/admin/doc/(\d+)'.*?<b>([^<]*)</b><small>([^<]*)</small>",
                          page, re.S)
        res.check("документы: свежие первыми, дата и размер",
                  [(n, w) for _i, n, w in docs],
                  [("trimitere.docx", _dmy(0) + " · 0 KB"), ("acord.pdf", _dmy(0) + " · 0 KB"),
                   ("rx.png", _dmy(0) + " · 0 KB")])
        dmeta = json.loads(re.search(r"const DOCS = (.*?);\n", page).group(1))
        res.check("чем открывать: картинка у себя, PDF у себя, docx — программой Windows",
                  [dmeta[i]["view"] for i, _n, _w in docs], ["ext", "pdf", "img"])
        res.ok("у картинки миниатюра", f"src='/admin/doc/{docs[2][0]}?thumb=1'" in page,
               "нет миниатюры")

        # ---- визиты ----
        res.check("история: следующий отмечен, прошлый без дневника зовёт заполнить, "
                  "отменённый молчит, завершённый несёт диагноз",
                  _hist(page),
                  [(f"{_dmy(2)} 09:30 · confirmată", "Consultație", ""),
                   (f"{_dmy(-1)} 12:00 · confirmată", "Consultație",
                    f"<small><a href='/admin/visit/{sd['v_last']}?back=/admin/patient/{pid}'>+ Consultație</a></small>"),
                   (f"{_dmy(-3)} 11:00 · anulată", "Igienizare", ""),
                   (f"{_dmy(-10)} 10:00 · finalizată", "Consultație",
                    f"<small style='overflow-wrap:anywhere'><a href='/admin/visit/{sd['v_done']}?back=/admin/patient/{pid}'>Consultație</a>: Pulpită 26</small>")])
        res.ok("следующий визит — своей карточкой",
               f"Următoarea vizită</h3><div style='font-size:13.5px;font-weight:600'>{_dmy(2)} · 09:30</div>" in page
               and "Consultație · Dr. Activ Doi" in page, "карточки нет")
        res.ok("класс next у будущего", "<div class='tline next'>" in page, "нет")

        # ---- летопись ----
        acts = _acti(page)
        res.check("летопись: 29 событий, свежие первыми, показаны 10",
                  (len(acts), acts[0], acts[-1], "Toate evenimentele (29)" in page),
                  (29, "Document încărcat: trimitere.docx",
                   f"Programare: Consultație · Dr. Activ Doi · {_dmy(-10)} 10:00", True))
        res.ok("просмотров в ленте нет, ссылка на них есть",
               "Fișa deschisă" not in page and f"/admin/patient/{pid}?views=1" in page, "нет")
        res.check("с ?views=1 — плюс просмотры",
                  len(_acti(c.get(f"/admin/patient/{pid}?views=1").body)) > 29, True)

        # ---- анамнез, предупреждения, профиль ----
        res.ok("анамнез: три риска — две галочки и свободный текст",
               "<span class='pill orange'>3 de reținut</span>" in page
               and "Alergii (medicamente, materiale): latex</span>" in page
               and f"Completat: {_dmy(0)} · Director" in page
               and "<details class='anform'>" in page, "анамнез не тот")
        res.check("предупреждения: все четыре, по порядку, словом вида",
                  re.findall(r"<div class='alert (\w+)'>(?:<svg.*?</svg>) ([^<]*)<form", page, re.S),
                  [("allergy", "Alergie Penicilină"), ("medication", "Medicație Anticoagulante"),
                   ("warning", "Atenție Leșină"), ("info", "Info Vorbește rusă")])
        res.check("профиль: строки по порядку, дата рождения по-человечески",
                  _frows(page),
                  [("Telefon", "069000111"), ("Data nașterii", "07.03.1985"), ("Gen", "F"),
                   ("IDNP", "2000000000001"), ("E-mail", "pin@example.com"),
                   ("Adresă", "str. Pin 1"), ("Asigurare", "CNAM activă"),
                   ("Medic curant", "Dr. Activ Doi"), ("Pacient din", _dmy(0))])
        res.ok("заметка, свёрнутая форма, архив и обезличивание",
               "nota internă" in page and "style='display:none;margin-top:10px'" in page
               and "Arhivează pacientul" in page and "datele de identitate" in page,
               "профиль не тот")
        res.check("окно записи: врачи по услуге, медик курант выбран",
                  (json.loads(re.search(r"const AP_DOCS = (.*?);\n", page).group(1)),
                   re.search(r'const AP_PRIM = "(\w*)"', page).group(1)),
                  ({"consult": ["d2", "d3", "d4"], "pain": ["d2"], "hygiene": ["d3"],
                    "orphan": [], "long": ["d2"]}, "d2"))

        # ---- ветки, которых у богатого пациента нет ----
        c.post("/admin/patients/new", name="Gol Fără")
        bare = _pid(c, "Gol")
        page = c.get(f"/admin/patient/{bare}").body
        res.check("пустая фиша: пилюля одна, KPI пустые",
                  (_pills(page), [k[0] for k in _kpi(page)]),
                  ([("green", "Pacient activ")], ["0", "0", "—", "—", "0"]))
        res.ok("пустая фиша: план пуст без согласия, платежей нет, визитов нет, анамнез открыт",
               "— plan gol —" in page and "plan-acord" not in page and "class='sold" not in page
               and "încă fără plăți" in page and "încă fără vizite" in page
               and "<details class='anform' open>" in page and "necompletată" in page
               and "fără atenționări" in page, "пустые состояния не те")
        res.ok("без телефона — явная метка и полное удаление",
               "<span class='v notel'>fără telefon</span>" in page
               and "ștearsă definitiv" in page and "neprogramat" in page, "не то")

        # аванс, полная оплата, архив, вкладка одних отказов
        c.post(f"/admin/patient/{bare}/plan", procedure="Sigilare", price="200")
        iid = re.findall(r"/plan/(\d+)/status", c.get(f"/admin/patient/{bare}").body)[0]
        c.post(f"/admin/patient/{bare}/plan/{iid}/status", to="in_lucru")
        c.post(f"/admin/patient/{bare}/plan/{iid}/status", to="finalizat")
        c.post(f"/admin/patient/{bare}/pay", amount="200", method="card")
        page = c.get(f"/admin/patient/{bare}").body
        res.ok("оплачено ровно — «achitat integral», без пилюли долга",
               "<b>achitat integral</b>" in page and "De achitat" not in page
               and "Avans" not in page, "сальдо не то")
        c.post(f"/admin/patient/{bare}/pay", amount="50", method="card")
        page = c.get(f"/admin/patient/{bare}").body
        res.ok("переплата — аванс в сальдо и в шапке",
               "<div class='sold plus'><span>Avans</span><b>50 MDL</b>" in page
               and ("green", "Avans: 50 MDL") in _pills(page), "аванс не виден")
        c.post(f"/admin/patient/{bare}/archive", on="1")
        page = c.get(f"/admin/patient/{bare}").body
        # ⚠️ в строке под именем архива НЕТ: строка `meta` в обработчике
        # собирается, но не рисуется (мёртвый код с 1.19.0) — архив виден
        # только пилюлей и кнопкой; API повторяет то, что на экране
        res.ok("архив: серая пилюля вместо «активен», кнопка возврата",
               ("grey", "Arhivat") in _pills(page)
               and ("green", "Pacient activ") not in _pills(page)
               and "<span>arhivat</span>" not in page
               and "Scoate din arhivă" in page, "архив не виден")
        c.post("/admin/patients/new", name="Doar Refuz")
        rf = int(re.findall(r"/admin/patient/(\d+)", c.get("/admin/search?q=Doar").body)[0])
        c.post(f"/admin/patient/{rf}/plan", procedure="Implant", price="100")
        iid = re.findall(r"/plan/(\d+)/status", c.get(f"/admin/patient/{rf}").body)[0]
        c.post(f"/admin/patient/{rf}/plan/{iid}/status", to="refuzat", motiv="nu vrea")
        page = c.get(f"/admin/patient/{rf}").body
        res.ok("план из одних отказов открывает вкладку Refuzate, прогресс 0/0",
               "class='on' data-f='refuzat'" in page and "0/0 finalizate · 1 refuzate" in page
               and "plan activ: 0 MDL" in page, "вкладка не та")


def _card(c: Client, pid: int, views: bool = False) -> dict:
    r = c.get(f"/api/patients/{pid}" + ("?views=1" if views else ""))
    assert r.status == 200, r.body[:200]
    return _j(r)["data"]


def suite_api(res: Result) -> None:
    """`GET /api/patients/{pid}` повторяет старую страницу цифра в цифру:
    пилюли, KPI, план, сальдо, документы, визиты, летопись, анамнез, профиль."""
    with Server() as s:
        res.check("без входа — 401", Client(s.url).get("/api/patients/1").status, 401)
        c = Client(s.url).login()
        res.check("чужая фиша — 404", c.get("/api/patients/777").status, 404)
        sd = _seed(c)
        pid = sd["pid"]
        page = c.get(f"/admin/patient/{pid}").body
        d = _card(c, pid)
        res.check("состав ответа", sorted(d),
                  sorted(["id", "name", "initials", "archived", "erasure", "profile", "hero",
                          "kpi", "alerts", "anamneza", "plan", "finance", "documents",
                          "visits", "activity", "appoint", "options"]))
        res.check("шапка: те же пилюли в том же порядке",
                  [(pl["tone"], pl["text"]) for pl in d["hero"]["pills"]], _pills(page))
        res.ok("пилюли несут имена значков", all(pl["icon"] for pl in d["hero"]["pills"]),
               f"{d['hero']['pills']}")
        k = _kpi(page)
        res.check("KPI: те же цифры",
                  (d["kpi"]["visits"], d["kpi"]["active"], d["kpi"]["done"], d["kpi"]["canc"],
                   d["hero"]["days_ago"], d["hero"]["next"]["date"][:5], d["hero"]["next"]["time"],
                   d["hero"]["last"]["date"], d["hero"]["last"]["service"]),
                  (int(k[0][0]), int(k[1][0]), int(k[4][0]), 1, int(k[2][0].split()[0]),
                   k[3][0], k[3][2], k[2][2], "Consultație"))
        pl = d["plan"]
        hidden = pl["items"] and [it["status"] not in d["options"]["tab_states"][pl["default_tab"]]
                                  for it in pl["items"]]
        res.check("план: тот же порядок и те же спрятанные строки",
                  [(it["status"], it["procedure"], h) for it, h in zip(pl["items"], hidden)],
                  _plan_rows(page))
        res.check("план: суммы, прогресс, счёт, вкладка",
                  (pl["total"], pl["total_done"], pl["n_track"], pl["pct_done"], pl["counts"],
                   pl["default_tab"], pl["n_act"]),
                  (1900, 500, 4, 25, {"planificat": 2, "in_lucru": 1, "finalizat": 1, "refuzat": 1},
                   "act", 3))
        by = {it["procedure"]: it for it in pl["items"]}
        res.check("план: кнопки по статусу — те же переходы, что у форм страницы",
                  [(it["status"], it["next"], it["refusable"], it["deletable"]) for it in pl["items"]],
                  [("in_lucru", "finalizat", True, False), ("planificat", "in_lucru", True, True),
                   ("planificat", "in_lucru", True, True), ("finalizat", "in_lucru", False, False),
                   ("refuzat", "planificat", False, False)])
        res.check("план: срок просрочен, дата закрытия, причина отказа, подписи",
                  (by["Extracție 48"]["due"], by["Extracție 48"]["overdue"],
                   by["Detartraj"]["done"], by["Implant 36"]["motiv"], by["Coroană 11"]["label"],
                   by["Consult gratuit"]["price"], by["Coroană 11"]["tooth"]),
                  ("01.01.2020", True, _dmy(0), "refuză implantul", "În lucru", None, 11))
        fin = d["finance"]
        res.check("сальдо: начислено, оплачено, долг, плашка",
                  (fin["charged"], fin["paid"], fin["debt"], fin["sold"], fin["can_delete"]),
                  (500, 200, 300, {"kind": "bad", "amount": 300}, True))
        res.check("платежи: те же строки",
                  [(p_["neg"], p_["amount"], p_["method"], p_["note"], p_["taken_by"])
                   for p_ in fin["payments"]],
                  [(True, 100, "card", "restituire", "Director"),
                   (False, 300, "numerar", "avans", "Director")])
        res.check("документы: порядок, дата, размер, чем открывать",
                  [(x["filename"], x["when"], x["size"], x["view"], x["category"])
                   for x in d["documents"]],
                  [("trimitere.docx", _dmy(0), "0 KB", "ext", "trimitere"),
                   ("acord.pdf", _dmy(0), "0 KB", "pdf", "acord"),
                   ("rx.png", _dmy(0), "0 KB", "img", "radiografie")])
        hist = d["visits"]["history"]
        res.check("визиты: те же строки истории",
                  [(f"{v['when']} · {v['status_label']}", v["service"]) for v in hist],
                  [(w, sv) for w, sv, _t in _hist(page)])
        res.check("визиты: следующий, дневник и приглашение, диагноз, ссылка с возвратом",
                  [(v["is_next"], v["consult"], v["diag"]) for v in hist],
                  [(True, "", ""), (False, "invite", ""), (False, "", ""),
                   (False, "rec", "Pulpită 26")])
        res.check("визиты: адрес дневника — как на странице",
                  hist[3]["url"], f"/admin/visit/{sd['v_done']}?back=/admin/patient/{pid}")
        res.check("визиты: живые для списка за цифрой, всего",
                  (len(d["visits"]["live"]), d["visits"]["n_total"]), (3, 4))
        act = d["activity"]
        res.check("летопись: те же 29 строк в том же порядке",
                  [a["text"] for a in act["items"]], _acti(page))
        res.check("летопись: показ 10, без просмотров, автор и час",
                  (act["shown"], act["views"], act["items"][0]["who"],
                   len(act["items"][0]["hhmm"]), act["items"][0]["icon"]),
                  (10, False, "Director", 5, "clip"))
        an = d["anamneza"]
        res.check("анамнез: риски, галочки по порядку словаря, свободный текст, автор",
                  (an["state"], an["n_risk"], an["flags"], an["marked"], an["free"],
                   an["when"], an["author"], an["texts"]["alergii"]),
                  ("risk", 3, ["cardio", "diabet"],
                   ["Boli cardiovasculare / hipertensiune", "Diabet zaharat"],
                   [{"label": "Alergii (medicamente, materiale)", "text": "latex"}],
                   _dmy(0), "Director", "latex"))
        res.check("предупреждения: те же четыре",
                  [(a["kind"], a["label"], a["text"]) for a in d["alerts"]],
                  [("allergy", "Alergie", "Penicilină"), ("medication", "Medicație", "Anticoagulante"),
                   ("warning", "Atenție", "Leșină"), ("info", "Info", "Vorbește rusă")])
        pr = d["profile"]
        res.check("профиль: те же значения, дата рождения и пол по-человечески",
                  [pr["phone"], pr["birth"], pr["gender_label"], pr["idnp"], pr["email"],
                   pr["address"], pr["insurance"], pr["primary_doctor"], pr["created"]],
                  [v for _k, v in _frows(page)[:8]] + [_frows(page)[8][1]])
        res.check("профиль: пол сырым значением для формы", pr["gender"], "f")
        res.check("профиль: возраст, канал, дело, заметка, язык, год",
                  (pr["age"], pr["channel"], pr["file_no"], pr["notes"], pr["lang"], pr["year"]),
                  (41, "recepție", "D-5", "nota internă", "ro", _dmy(0)[-4:]))
        res.check("шапка: имя, инициалы, архив, ветка стирания",
                  (d["name"], d["initials"], d["archived"], d["erasure"]),
                  ("Pin Test", "PT", False, "anon"))
        res.check("окно записи: врачи по услуге и медик курант — как на странице",
                  (d["appoint"]["doctors"], d["appoint"]["primary"],
                   [x["id"] for x in d["appoint"]["services"]], d["appoint"]["today"]),
                  ({"consult": ["d2", "d3", "d4"], "pain": ["d2"], "hygiene": ["d3"],
                    "orphan": [], "long": ["d2"]}, "d2",
                   ["consult", "pain", "hygiene", "orphan", "long"], _d(0)))
        op = d["options"]
        res.check("справочники форм: виды, вопросы, категории, оплата, зубы",
                  (len(op["alert_kinds"]), len(op["anamneza_flags"]), len(op["anamneza_texts"]),
                   [x["id"] for x in op["doc_categories"]], [x["id"] for x in op["pay_methods"]],
                   op["teeth"][:3], op["milk"][:2], op["max_doc_mb"], op["doctors"]),
                  (4, 12, 4, ["radiografie", "acord", "trimitere", "alt"],
                   ["numerar", "card", "transfer"], [18, 17, 16], [55, 54], 25,
                   ["Dr. Arhivat Unu", "Dr. Activ Doi", "Dr. Activ Trei", "Dr. Activ Patru"]))

        # журнал доступа: открытие через API пишется, как открытие страницы
        n_before = len(_card(c, pid, views=True)["activity"]["items"])
        res.ok("?views=1 — в ленте просмотры", any(
            a["kind"] == "view" for a in _card(c, pid, views=True)["activity"]["items"]),
               "просмотров нет")
        res.ok("каждое открытие фиши записано (второй просмотр добавил строку)",
               len(_card(c, pid, views=True)["activity"]["items"]) > n_before, "не пишется")
        r = c.get(f"/api/patients/{pid}/activity?views=1")
        res.ok("лента отдельно — те же строки, без новой записи о просмотре",
               r.status == 200 and _j(r)["data"]["views"] is True
               and len(_j(r)["data"]["items"]) == len(_card(c, pid, views=True)["activity"]["items"]) - 1,
               r.body[:200])

        # одонтограмма — куском старой страницы (точка интеграции до C21)
        teeth = _j(c.get(f"/api/patients/{pid}/teeth"))["data"]["html"]
        res.ok("кусок одонтограммы — тот же, что на странице",
               teeth.startswith("<div class='fcard odo' id='odo'") and teeth in page
               and "function openTooth" in teeth, "кусок не совпал")

        # пустая фиша — те же пустые состояния
        c.post("/admin/patients/new", name="Gol Fără")
        bare = _pid(c, "Gol")
        d = _card(c, bare)
        res.check("пустая фиша: пилюля одна, KPI нули, план и сальдо пусты, анамнез не собран",
                  ([(pl["tone"], pl["text"]) for pl in d["hero"]["pills"]], d["kpi"],
                   d["hero"]["last"], d["hero"]["next"], d["hero"]["days_ago"],
                   d["plan"]["items"], d["plan"]["default_tab"], d["finance"]["sold"],
                   d["anamneza"]["state"], d["alerts"], d["documents"], d["visits"]["history"],
                   d["profile"]["phone"], d["erasure"]),
                  ([("green", "Pacient activ")],
                   {"visits": 0, "active": 0, "done": 0, "canc": 0}, None, None, None,
                   [], "act", None, "none", [], [], [], "", "delete"))


def _act(c: Client, pid: int, path: str, payload: dict | None = None) -> tuple:
    """(код HTTP, конверт) действия фиши."""
    r = c.post_json(f"/api/patients/{pid}{path}", payload or {})
    return r.status, _j(r)


def suite_actions(res: Result) -> None:
    """Действия фиши через JSON: те же коды, что у форм, отказ проверки 422 с
    полем, спор с состоянием 409, удача — свежая фиша."""
    with Server() as s:
        c = Client(s.url).login()
        c.post("/admin/patients/new", name="Act Test", phone="069555000")
        pid = _pid(c, "069555000")
        c.post("/admin/patients/new", name="Alt Om", phone="069555111")

        # ---- профиль ----
        st, j = _act(c, pid, "/profile", {"name": " ", "phone": "069555000"})
        res.check("профиль без имени — 422, поле name", (st, j["code"], j.get("field")),
                  (422, "bad_card", "name"))
        st, j = _act(c, pid, "/profile", {"name": "Act Test", "birth_date": "2222-01-01"})
        res.check("дата в будущем — 422 bad_bd, поле", (st, j["code"], j.get("field")),
                  (422, "bad_bd", "birth_date"))
        st, j = _act(c, pid, "/profile", {"name": "Act Test", "idnp": "12"})
        res.check("кривой IDNP — 422 bad_idnp", (st, j["code"], j.get("field")), (422, "bad_idnp", "idnp"))
        st, j = _act(c, pid, "/profile", {"name": "Act Test Nou", "phone": "069555000",
                                          "birth_date": "1990-05-06", "lang": "ru",
                                          "notes": "n", "insurance": "CNAM"})
        res.check("профиль сохранён — ok_card и свежая фиша",
                  (st, j["code"], j["data"]["name"], j["data"]["profile"]["birth"],
                   j["data"]["profile"]["lang"], j["data"]["profile"]["age"],
                   [(pl["tone"], pl["text"]) for pl in j["data"]["hero"]["pills"]]),
                  (200, "ok_card", "Act Test Nou", "06.05.1990", "ru", 36,
                   [("green", "Pacient activ"), ("green", "CNAM")]))
        res.ok("старая страница видит правку API", "Act Test Nou" in c.get(f"/admin/patient/{pid}").body,
               "не видит")
        st, j = _act(c, pid, "/profile", {"name": "Act Test Nou", "phone": "069 555 111"})
        res.check("чужой номер — сохранено, но названо вслух (warn)",
                  (st, j["code"], j["tone"]), (200, "ok_tel_dup", "warn"))
        res.check("повторное сохранение того же — тождественно",
                  _act(c, pid, "/profile", {"name": "Act Test Nou", "phone": "069 555 111"})[1]["code"],
                  "ok_tel_dup")

        # ---- архив ----
        st, j = _act(c, pid, "/archive", {"on": True})
        res.check("в архив — ok_arh, archived", (st, j["code"], j["data"]["archived"]), (200, "ok_arh", True))
        st, j = _act(c, pid, "/archive", {"on": False})
        res.check("из архива — ok_unarh", (st, j["code"], j["data"]["archived"]), (200, "ok_unarh", False))

        # ---- предупреждения ----
        st, j = _act(c, pid, "/alerts", {"kind": "zzz", "text": "x"})
        res.check("чужой вид — 422", (st, j["code"], j.get("field")), (422, "bad_card", "text"))
        st, j = _act(c, pid, "/alerts", {"kind": "allergy", "text": "  Latex  "})
        res.check("предупреждение добавлено, в шапке пилюля",
                  (st, j["code"], [(a["kind"], a["text"]) for a in j["data"]["alerts"]],
                   ("orange", "Latex") in [(pl["tone"], pl["text"]) for pl in j["data"]["hero"]["pills"]]),
                  (200, "ok_card", [("allergy", "Latex")], True))
        aid = j["data"]["alerts"][0]["id"]
        st, j = _act(c, pid, f"/alerts/{aid}/delete")
        res.check("удалено — тихий успех, список пуст", (st, j["code"], j["data"]["alerts"]), (200, "", []))

        # ---- анамнез ----
        st, j = _act(c, pid, "/anamneza", {"flags": [], "boli": "  "})
        res.check("пустой опросник на пустом — 422 bad_anam", (st, j["code"]), (422, "bad_anam"))
        st, j = _act(c, pid, "/anamneza", {"flags": ["hiv", "zzz"], "anestezie": "lipotimie"})
        res.check("анамнез сохранён: чужой флаг отброшен, риски посчитаны",
                  (st, j["code"], j["data"]["anamneza"]["flags"], j["data"]["anamneza"]["n_risk"],
                   j["data"]["anamneza"]["state"]), (200, "ok_anam", ["hiv"], 2, "risk"))
        st, j = _act(c, pid, "/anamneza", {"flags": []})
        res.check("пустое пересохранение существующего — законное снятие, ok_anam",
                  (st, j["code"], j["data"]["anamneza"]["state"]), (200, "ok_anam", "ok"))

        # ---- план ----
        st, j = _act(c, pid, "/plan", {"procedure": "  "})
        res.check("позиция без процедуры — 422, поле", (st, j["code"], j.get("field")),
                  (422, "bad_card", "procedure"))
        st, j = _act(c, pid, "/plan", {"procedure": "Plombă", "tooth": "99", "price": "5000000",
                                       "due_date": "cândva"})
        it = j["data"]["plan"]["items"][0]
        res.check("позиция добавлена: чужой зуб и кривой срок обнулены, цена срезана",
                  (st, j["code"], it["procedure"], it["tooth"], it["price"], it["due"],
                   it["status"], it["next"], it["deletable"], j["data"]["kpi"]["active"]),
                  (200, "ok_card", "Plombă", None, 1000000, "", "planificat", "in_lucru", True, 1))
        iid = it["id"]
        st, j = _act(c, pid, f"/plan/{iid}/status", {"to": "finalizat"})
        res.check("запрещённое ребро — 409 bad_card", (st, j["code"]), (409, "bad_card"))
        st, j = _act(c, pid, f"/plan/{iid}/status", {"to": "in_lucru"})
        res.check("Începe — тихий успех, статус и кнопки обновились",
                  (st, j["code"], j["data"]["plan"]["items"][0]["status"],
                   j["data"]["plan"]["items"][0]["next"]), (200, "", "in_lucru", "finalizat"))
        st, j = _act(c, pid, f"/plan/{iid}/delete")
        res.check("удалить начатую — 409 bad_pdel", (st, j["code"]), (409, "bad_pdel"))
        st, j = _act(c, pid, f"/plan/{iid}/status", {"to": "refuzat", "motiv": "  "})
        res.check("отказ без причины — 422 bad_refuz, поле motiv", (st, j["code"], j.get("field")),
                  (422, "bad_refuz", "motiv"))
        st, j = _act(c, pid, f"/plan/{iid}/status", {"to": "refuzat", "motiv": "nu vrea"})
        res.check("отказ с причиной — ok_refuz, вкладка отказов, прогресс 0/0",
                  (st, j["code"], j["data"]["plan"]["items"][0]["motiv"],
                   j["data"]["plan"]["default_tab"], j["data"]["plan"]["n_track"]),
                  (200, "ok_refuz", "nu vrea", "refuzat", 0))
        st, j = _act(c, pid, "/plan", {"procedure": "Coroană", "price": "700"})
        iid2 = j["data"]["plan"]["items"][0]["id"]
        st, j = _act(c, pid, f"/plan/{iid2}/delete")
        res.check("удалить нетронутую — можно, тихо", (st, j["code"], len(j["data"]["plan"]["items"])),
                  (200, "", 1))
        res.check("чужая позиция — 409", _act(c, pid, "/plan/9999/status", {"to": "in_lucru"})[0], 409)

        # ---- платежи ----
        st, j = _act(c, pid, "/payments", {"amount": "abc"})
        res.check("сумма не числом — 422, поле amount", (st, j["code"], j.get("field")),
                  (422, "bad_pay", "amount"))
        res.check("нулевая — 422", _act(c, pid, "/payments", {"amount": "0"})[1]["code"], "bad_pay")
        res.check("чужой метод — 422",
                  _act(c, pid, "/payments", {"amount": "10", "method": "crypto"})[1]["code"], "bad_pay")
        st, j = _act(c, pid, "/payments", {"amount": "250", "method": "card", "note": "avans"})
        res.check("платёж записан — ok_pay, аванс в сальдо и в шапке",
                  (st, j["code"], j["data"]["finance"]["sold"], j["data"]["finance"]["debt"],
                   j["data"]["finance"]["payments"][0]["amount"],
                   ("green", "Avans: 250 MDL") in [(pl["tone"], pl["text"]) for pl in j["data"]["hero"]["pills"]]),
                  (200, "ok_pay", {"kind": "plus", "amount": 250}, -250, 250, True))
        pay_id = j["data"]["finance"]["payments"][0]["id"]
        st, j = _act(c, pid, f"/payments/{pay_id}/delete")
        res.check("директор удаляет платёж — pay_del, след в летописи",
                  (st, j["code"], j["data"]["finance"]["payments"],
                   any("ștearsă" in a["text"] for a in j["data"]["activity"]["items"])),
                  (200, "pay_del", [], True))

        # ---- документы ----
        r = c.post_file(f"/api/patients/{pid}/documents", "file", "rx.png", PNG, mime="image/png",
                        category="radiografie")
        j = _j(r)
        res.check("документ загружен — ok_doc, картинка у себя",
                  (r.status, j["code"], [(x["filename"], x["view"], x["category"]) for x in j["data"]["documents"]]),
                  (200, "ok_doc", [("rx.png", "img", "radiografie")]))
        doc_id = j["data"]["documents"][0]["id"]
        res.ok("файл отдаётся старым маршрутом", c.get(f"/admin/doc/{doc_id}").status == 200, "нет")
        r = c.post_file(f"/api/patients/{pid}/documents", "file", "gol.txt", b"", category="alt")
        res.check("пустой файл — 422 bad_doc", (r.status, _j(r)["code"], _j(r).get("field")),
                  (422, "bad_doc", "file"))
        r = c.post_file(f"/api/patients/{pid}/documents", "file", "virus.exe", b"MZ" + b"x" * 10)
        exe_id = _j(r)["data"]["documents"][0]["id"]
        j = _j(c.post_json(f"/api/documents/{exe_id}/open", {}))
        res.check("открыть .exe программой нельзя — opened false, причина ext",
                  (j["ok"], j["data"]), (True, {"opened": False, "reason": "ext"}))
        j = _j(c.post_json("/api/documents/9999/open", {}))
        res.check("чужой документ — opened false, missing", j["data"]["reason"], "missing")
        st, j = _act(c, pid, f"/documents/{exe_id}/delete")
        res.check("документ удалён — тихо, остался один", (st, [x["id"] for x in j["data"]["documents"]]),
                  (200, [doc_id]))

        # ---- запись ----
        j = _j(c.get(f"/api/patients/{pid}/slots?date={_d(3)}&doctor=d2&service=consult"))
        res.ok("часы врача на дату — список HH:MM", j["ok"] and len(j["data"]["slots"]) > 5
               and re.fullmatch(r"\d\d:\d\d", j["data"]["slots"][0]), f"{j}")
        res.check("врач не по услуге — пусто",
                  _j(c.get(f"/api/patients/{pid}/slots?date={_d(3)}&doctor=d3&service=long"))["data"]["slots"], [])
        st, j = _act(c, pid, "/appoint", {"date": "x", "time": "09:00", "doctor": "d2", "service": "consult"})
        res.check("кривая дата — 422 bad", (st, j["code"], j.get("field")), (422, "bad", "time"))
        st, j = _act(c, pid, "/appoint", {"date": _d(-1), "time": "09:00", "doctor": "d2", "service": "consult"})
        res.check("прошедший час — 409 past", (st, j["code"]), (409, "past"))
        st, j = _act(c, pid, "/appoint", {"date": _d(3), "time": "09:00", "doctor": "d1", "service": "consult"})
        res.check("архивный врач — 409 bad_off", (st, j["code"]), (409, "bad_off"))
        st, j = _act(c, pid, "/appoint", {"date": _d(3), "time": "23:00", "doctor": "d2", "service": "consult"})
        res.check("вне часов клиники — 422 outside", (st, j["code"]), (422, "outside"))
        st, j = _act(c, pid, "/appoint", {"date": _d(3), "time": "09:00", "doctor": "d2", "service": "consult"})
        res.check("запись из фиши — ok, визит в истории и в KPI",
                  (st, j["code"], j["data"]["visits"]["n_total"], j["data"]["kpi"]["visits"],
                   j["data"]["hero"]["next"]["time"], j["data"]["visits"]["history"][0]["is_next"]),
                  (200, "ok", 1, 1, "09:00", True))
        st, j = _act(c, pid, "/appoint", {"date": _d(3), "time": "09:00", "doctor": "d3", "service": "consult"})
        res.check("тот же час у пациента — 409 dup", (st, j["code"]), (409, "dup"))
        res.ok("визит виден в журнале дня", "Act Test Nou" in c.get(f"/admin/all?date={_d(3)}").body, "нет")

        # ---- стирание ----
        st, j = _act(c, pid, "/erase", {"confirm": "nu"})
        res.check("без слова — 422 bad_erase, поле confirm", (st, j["code"], j.get("field")),
                  (422, "bad_erase", "confirm"))
        st, j = _act(c, pid, "/erase", {"confirm": "sterg"})
        res.check("фиша с лечением — обезличена, ok_anon",
                  (st, j["code"], j["data"]["profile"]["phone"], j["data"]["profile"]["idnp"]),
                  (200, "ok_anon", "", ""))
        c.post("/admin/patients/new", name="Doar Contact", phone="069555222")
        pid2 = _pid(c, "069555222")
        st, j = _act(c, pid2, "/erase", {"confirm": "STERG"})
        res.check("контакт без лечения — удалён, адрес списка",
                  (st, j["code"], j["data"]), (200, "ok_del", {"url": "/admin/search?msg=ok_del"}))
        res.check("фиши больше нет — 404", c.get(f"/api/patients/{pid2}").status, 404)

        # ---- охрана ----
        anon = Client(s.url)
        res.check("без входа действие — 401", anon.post_json(f"/api/patients/{pid}/alerts", {}).status, 401)
        res.check("чужой Origin — 403",
                  c.post_json(f"/api/patients/{pid}/alerts", {"kind": "info", "text": "x"},
                              headers={"Origin": "http://evil.example"}).status, 403)
        res.check("не JSON — 422", c.post(f"/api/patients/{pid}/profile", name="X").status, 422)

    # право удалять платёж — только у директора (ветка PIN-файла, как у клиники)
    s = Server(env={"ADMIN_KEY": ""})
    with s:
        boss = Client(s.url)
        boss.post("/admin/setup", pin1="1111", pin2="1111")
        boss.post("/admin/users/save", uid="ana", name="Ana", role="receptie", pin="2222")
        boss.post("/admin/patients/new", name="Bani Test", phone="069555333")
        pid = _pid(boss, "069555333")
        rec = Client(s.url)
        rec.post("/admin/login", password="2222", next="/admin")
        st, j = _act(rec, pid, "/payments", {"amount": "100", "method": "numerar"})
        res.check("регистратура записывает платёж", (st, j["code"], j["data"]["finance"]["can_delete"]),
                  (200, "ok_pay", False))
        # ⚠️ автор события — ИМЯ вошедшего и через JSON: движок опознаёт
        # человека на /api так же, как на /admin (main._identify); иначе
        # летопись подписывала бы действия API «recepție», и журнал по 195-му
        # называл бы не того, кто принял деньги
        res.check("летопись подписана именем вошедшего, а не «recepție»",
                  (j["data"]["activity"]["items"][0]["who"],
                   j["data"]["finance"]["payments"][0]["taken_by"]), ("Ana", "Ana"))
        pay_id = j["data"]["finance"]["payments"][0]["id"]
        st, j = _act(rec, pid, f"/payments/{pay_id}/delete")
        res.check("регистратура не удаляет — 403 no_access", (st, j["code"]), (403, "no_access"))
        st, j = _act(boss, pid, f"/payments/{pay_id}/delete")
        res.check("директор удаляет — pay_del", (st, j["code"], j["data"]["finance"]["can_delete"]),
                  (200, "pay_del", True))
        res.ok("регистратуре фиша открыта", _card(rec, pid)["name"] == "Bani Test", "закрыта")


def _server_with_flag(env: dict | None = None) -> Server:
    """Сервер, у которого фиша уже отдана React: флаг пишется в копию профиля
    ДО старта — так профиль читается, как у клиники."""
    s = Server(env=env)
    cfg = json.loads(s.clinic.read_text(encoding="utf-8"))
    cfg["ui"] = {"react": ["patient_card"]}
    s.clinic.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    return s


def suite_switch(res: Result) -> None:
    """Флаг patient_card: узел React с номером фиши и режимом ленты в той же
    рамке, ?ui=legacy возвращает старую фишу, старые формы при флаге живут и
    возвращают на React-страницу с плашкой сервера."""
    with Server() as s:
        c = Client(s.url).login()
        c.post("/admin/patients/new", name="Flag Card", phone="069777000")
        pid = _pid(c, "069777000")
        page = c.get(f"/admin/patient/{pid}").body
        res.ok("без флага — старая фиша", "class='hero'" in page and 'id="root"' not in page,
               "не старая")

    s = _server_with_flag()
    with s:
        c = Client(s.url).login()
        c.post("/admin/patients/new", name="Flag Card", phone="069777000")
        pid = _pid(c, "069777000")
        page = c.get(f"/admin/patient/{pid}").body
        res.ok("узел React в рамке фиши",
               '<div id="root" data-screen="patient_card"' in page
               and f"fișa pacientului · #{pid}" in page and "/static/js/bundle.js?v=" in page,
               "узла нет")
        params = json.loads(page.split("data-params=\"", 1)[1].split("\"", 1)[0]
                            .replace("&quot;", '"'))
        res.check("номер фиши — параметром узла, без режима ленты", params, {"pid": str(pid)})
        page_v = c.get(f"/admin/patient/{pid}?views=1").body
        params = json.loads(page_v.split("data-params=\"", 1)[1].split("\"", 1)[0]
                            .replace("&quot;", '"'))
        res.check("?views=1 — режим ленты параметром", params, {"pid": str(pid), "views": "1"})
        res.ok("старой разметки нет", "class='hero'" not in page and "id='plan'" not in page
               and "apptdlg" not in page, "две разметки")
        res.ok("не внутри #live", 'id="live"' not in page, "живой кусок")
        res.ok("?ui=legacy — старая фиша", "class='hero'" in c.get(f"/admin/patient/{pid}?ui=legacy").body,
               "не вернулась")
        res.ok("?msg= на React-странице — плашка сервера",
               "dp_toast" in c.get(f"/admin/patient/{pid}?msg=ok_card").body, "плашки нет")
        res.check("чужая фиша при флаге — на список", c.get("/admin/patient/9999").status, 303)
        # форма зуба из куска одонтограммы — старый маршрут, возврат сюда с ?msg=
        r = c.post(f"/admin/patient/{pid}/tooth", tooth="11", state="carie", doctor="Dr. Activ Doi")
        res.check("старая форма зуба при флаге работает и возвращает с плашкой",
                  (r.status, r.location), (303, f"/admin/patient/{pid}?msg=ok_card"))
        res.ok("зуб доехал до куска одонтограммы",
               "11" in _j(c.get(f"/api/patients/{pid}/teeth"))["data"]["html"]
               and '"state": "carie"' in _j(c.get(f"/api/patients/{pid}/teeth"))["data"]["html"],
               "не доехал")
        res.ok("флаг пережил правку профиля через API",
               _act(c, pid, "/profile", {"name": "Flag Card", "phone": "069777000"})[0] == 200
               and json.loads(s.clinic.read_text(encoding="utf-8")).get("ui") == {"react": ["patient_card"]},
               "флаг слетел")
        res.check("без входа React-страница закрыта", Client(s.url).get(f"/admin/patient/{pid}").status, 303)

    s = _server_with_flag(env={"ADMIN_KEY": ""})
    with s:
        boss = Client(s.url)
        boss.post("/admin/setup", pin1="1111", pin2="1111")
        boss.post("/admin/users/save", uid="ana", name="Ana", role="receptie", pin="2222")
        boss.post("/admin/patients/new", name="Flag Pin", phone="069777111")
        pid = _pid(boss, "069777111")
        rec = Client(s.url)
        rec.post("/admin/login", password="2222", next="/admin")
        res.ok("регистратуре фиша открыта и по PIN",
               'data-screen="patient_card"' in rec.get(f"/admin/patient/{pid}").body, "закрыта")
