"""Кабинет клиники по вкладкам (29.10.2026, вариант 1 Олега: «сейчас всё на одной странице, надо
сделать более организованно, по вкладкам»). Кадры и разбор — design/cont-tabs.

Что держит набор:
- пять вкладок в одном порядке: Licență și program · Abonament și plăți · Clinica · SMS · Documente;
  SMS — только когда пакет предложен; каждый блок прежней ленты — в своей вкладке;
- ⛔ ключ вкладки не равен ни одному id страницы (метка адреса прокрутила бы к элементу), прежние
  якоря #plati / #date ведут на вкладку; скрипт вкладок — тот же, что у карточки админки;
- счётчик «ждёт вас»: открытая нота — у Plăți, имя SMS без заявления — у SMS;
- несколько клиник: чипы под заголовком и список для телефона, «Clinicile mele» во вкладке Clinica;
- /cont/documente и /cont/acceptari отвечают; /cont/documente — кабинет с вкладкой «Documente» по
  умолчанию (адрес живёт в письмах и в акте), маршруты кабинета не менялись (test_contlink.ROUTES).
"""
import re
import sys

from harness import CLOUD, Client, Result, Server

sys.path.insert(0, str(CLOUD))
from app import views  # noqa: E402
from test_branches import BANK_ENV, DIRECTOR, _add, _enter, _register  # noqa: E402

ENV = {**BANK_ENV, "DP_TRIAL_MODE": "auto", "DP_SMS_OFFERED": "1", "DP_SMSMD_TOKEN": "t"}
KEYS = [k for k, _, _ in views.CONT_TABS]


def _tabs(body: str) -> list[str]:
    return re.findall(r"data-tab='(\w+)'", body)


def _panes(body: str) -> dict[str, str]:
    return dict(re.findall(r"<section class='pane' data-pane='(\w+)'>(.*?)</section>", body, re.S))


def _counts(body: str) -> dict[str, str]:
    """{ключ: счётчик} по полосе вкладок."""
    nav = body[body.index("<nav class='ctabs'"):body.index("</nav>")]
    return {k: n for k, n in re.findall(r"data-tab='(\w+)'[^<]*(?:<svg.*?</svg>)?<span>[^<]*</span>(?:<span class='n'>(\d+)</span>)?", nav)}


def suite_tabs(res: Result) -> None:
    src = (CLOUD / "app" / "views.py").read_text(encoding="utf-8")
    res.check("пять вкладок в порядке Олега", KEYS, ["licenta", "plati", "clinica", "sms", "documente"])
    res.ok("⛔ в разметке кабинета нет id с именем вкладки (метка адреса прокрутила бы страницу)",
           not any(f"id='{k}'" in src or f'id="{k}"' in src for k in KEYS))
    res.ok("скрипт вкладок общий с админкой и знает вкладку по умолчанию",
           "data-default" in views._TABS_JS and "closest('[data-pane]')" in views._TABS_JS)

    with Server(env=ENV) as s:
        c = _enter(s, DIRECTOR)
        main = _register(s, c)
        home = c.get("/cont")
        panes = _panes(home.body)
        res.check("одна клиника: вкладки на странице", _tabs(home.body), KEYS)
        res.check("разделы — те же ключи", list(panes), KEYS)
        res.ok("ни одного id, равного ключу вкладки, в живой странице",
               not any(f"id='{k}'" in home.body for k in KEYS))
        res.ok("Licență și program: лицензия, программа, компьютеры, учётная запись",
               "Perioada de probă este valabilă" in panes["licenta"] and "Descarcă DentPilot" in panes["licenta"]
               and "Calculatoare cu DentPilot" in panes["licenta"] and "action='/cont/iesire'" in panes["licenta"]
               and "Clinica are și alte sedii?" not in panes["licenta"], panes["licenta"][-1500:])
        res.ok("Abonament și plăți: форма варианта и нот", "name='months'" in panes["plati"]
               and "Abonament și plăți" in panes["plati"])
        res.ok("Clinica: реквизиты и «Filiale» с «Adaugă clinică» (одна клиника)",
               "action='/cont/date'" in panes["clinica"] and "Clinica are și alte sedii?" in panes["clinica"]
               and "href='/cont/clinica-noua'" in panes["clinica"] and "Clinicile mele" not in panes["clinica"])
        res.ok("SMS: имя отправителя", "numele expeditorului" in panes["sms"] and "action='/cont/sms/nume'" in panes["sms"])
        res.ok("Documente: PDF поставщика, акты, загрузка экземпляра — целиком во вкладке",
               "Documentele furnizorului" in panes["documente"] and "Acceptarea termenilor" in panes["documente"]
               and "action='/cont/documente/incarca'" in panes["documente"])
        res.ok("на /cont вкладка по умолчанию не задана — первая", "data-default" not in home.body.split("<script>")[0])
        res.check("счётчиков нет: ноты нет, имя SMS не запрошено", _counts(home.body), {k: "" for k in KEYS})

        res.check("нота выставлена из кабинета", c.post("/cont/nota", tier="plus", months="1", terms="1").status, 303)
        res.check("имя SMS запрошено", c.post("/cont/sms/nume", name="Zambet").location, "/cont?msg=sms_requested")
        home = c.get("/cont")
        res.check("счётчик «ждёт вас»: 1 у Plăți (нота) и 1 у SMS (заявление не загружено)",
                  _counts(home.body), {"licenta": "", "plati": "1", "clinica": "", "sms": "1", "documente": ""})
        res.ok("ссылка «Vezi nota de plată» и «datele clinicii» ведут на вкладки, не на id",
               "href='#plati'" in home.body and "href='#date'" not in home.body
               and ("href='#clinica'" in home.body or "datele clinicii" not in home.body), home.body[-3000:])

        docs = c.get("/cont/documente")
        res.ok("/cont/documente — тот же кабинет, вкладка «Documente» по умолчанию",
               docs.status == 200 and "data-default='documente'" in docs.body and _tabs(docs.body) == KEYS
               and "Documentele furnizorului" in docs.body, docs.body[:2000])
        res.check("/cont/acceptari отвечает", c.get("/cont/acceptari").status, 200)
        res.check("без входа /cont/documente — на вход", Client(s.url).get("/cont/documente").location, "/cont/login")

        # вторая клиника: чипы под заголовком, список для телефона, «Clinicile mele» во вкладке Clinica
        r, _code = _add(c, main)
        res.check("филиал добавлен", r.status, 200)
        home = c.get(f"/cont?c={main}")
        panes = _panes(home.body)
        head = home.body[:home.body.index("<div class='tabbed'")]
        res.ok("чипы клиник под заголовком: обе клиники, открытая выделена, «Adaugă clinică»",
               "<div class='cpick'>" in head and f"class='on' href='/cont?c={main}'" in head
               and "Zambet Botanica" in head and f"href='/cont/clinica-noua?c={main}'" in head, head[-1500:])
        res.ok("список для телефона: те же клиники, открытая выбрана",
               "<div class='cpick-sel'>" in head and f"<option value='/cont?c={main}' selected>" in head)
        res.ok("«Clinicile mele» — во вкладке Clinica, не над вкладками",
               "Clinicile mele" in panes["clinica"] and "Clinicile mele" not in head
               and "deschisă acum" in panes["clinica"] and "Notă comună" in panes["clinica"])
        res.ok("формы вкладок несут клинику (?c=)",
               f"action='/cont/date?c={main}'" in panes["clinica"] and f"action='/cont/nota?c={main}'" in panes["plati"]
               and f"action='/cont/documente/incarca?c={main}'" in panes["documente"])

    with Server(env={**BANK_ENV, "DP_TRIAL_MODE": "auto"}) as s:
        c = _enter(s, DIRECTOR)
        _register(s, c)
        home = c.get("/cont")
        res.check("пакет SMS не предложен — вкладки SMS нет", _tabs(home.body), [k for k in KEYS if k != "sms"])
        res.ok("без пакета раздела SMS нет и в разметке", "numele expeditorului" not in home.body)
