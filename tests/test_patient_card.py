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
