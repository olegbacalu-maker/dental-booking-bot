"""Аналитика директора (C15): модель раздела и её JSON.

Главное, что стережётся, — цифры СЧИТАЮТСЯ ОДИН РАЗ. Старая страница и
React-экран собраны из одной `stats.model`, и подпись, которой нет на старой
странице, не может появиться в JSON. Второй экземпляр этой арифметики разошёлся
бы с первым молча: цифры выглядят правдоподобно всегда, и увидеть расхождение
можно, только открыв обе поверхности и сложив их в уме.

⚠️ «Сегодня» берётся у клиники (`harness.clinic_today`), а не у раннера: движок
считает день по Кишинёву, CI — по UTC, и между 21:00 и 24:00 UTC даты разные.
"""
import json

from harness import TG_ON, Client, Result, Server, clinic_today

FLAGS = ["stats"]


def _j(r) -> dict:
    return json.loads(r.body)


def _server_with_flags(env: dict | None = None) -> Server:
    s = Server(env=env)
    cfg = json.loads(s.clinic.read_text(encoding="utf-8"))
    cfg["ui"] = {"react": list(FLAGS)}
    s.clinic.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    return s


def _seed(c: Client) -> str:
    """Две записи на сегодня: разным врачам, чтобы в модели было что делить."""
    d = clinic_today().isoformat()
    c.post("/admin/add", adate=d, atime="09:00", adoctor="d2",
           aservice="consult", aname="Stat API Unu", aphone="069000021",
           back="/admin/all")
    c.post("/admin/add", adate=d, atime="11:00", adoctor="d3",
           aservice="consult", aname="Stat API Doi", aphone="069000022",
           back="/admin/all")
    return d


def suite_stats(res: Result) -> None:
    with Server() as s:
        res.check("без входа — 401", Client(s.url).get("/api/stats").status, 401)
        c = Client(s.url).login()
        day = _seed(c)

        d = _j(c.get("/api/stats"))["data"]
        res.check("по умолчанию — семь дней", d["period"]["days"], 7)
        res.check("и они кончаются сегодня", d["period"]["to"], day)
        res.check("прошлый период назван по имени", d["compare"],
                  "față de săptămâna trecută")
        res.ok("выгрузка Excel — на тот же период",
               d["export_url"].endswith(f"from={d['period']['from']}&to={day}"),
               d["export_url"])
        res.ok("готовые периоды: сегодня, 7, месяц, 30",
               [p["key"] for p in d["presets"]] == ["azi", "d7", "luna", "d30"],
               f"{[p['key'] for p in d['presets']]}")

        # ⛔ Бот заморожен (08-08): плиток «Prin bot» и «Remindere» нет, и
        # кольца источников тоже — один источник это тавтология, а не разбивка.
        keys = [t["key"] for t in d["tiles"]]
        res.check("без бота плиток четыре", keys, ["total", "man", "done", "cancel"])
        res.check("кольца источников нет", d["sources"]["show"], False)

        by = {t["key"]: t for t in d["tiles"]}
        res.check("записи посчитаны", by["total"]["value"], 2)
        res.ok("у плитки свой ряд по дням, длиной в период",
               len(by["total"]["series"]) == 7 and sum(by["total"]["series"]) == 2,
               f"{by['total']['series']}")
        # ⛔ Рост отмен — плохой рост: стрелка вверх, а тон красный. Если тон
        # считать из знака числа, он позеленел бы ровно там, где всё плохо.
        res.check("у отмен рост помечен как плохой", by["cancel"]["bad"], True)
        res.ok("цвет — переменная темы, а не хекс",
               all(t["tone"].startswith("var(--") for t in d["tiles"]),
               f"{[t['tone'] for t in d['tiles']]}")

        # ⚠️ Прошлая неделя пуста: процентов от нуля не бывает, и тренд обязан
        # сказать это словом, а не «+∞%».
        tr = by["total"]["trend"]
        res.check("сравнение с пустым периодом — штуками", tr["value"], "+2")
        res.check("и вслух сказано, что тогда было ноль", tr["note"], " (atunci 0)")
        res.check("стрелки у такого сравнения нет", tr["icon"], "")
        res.check("неизменное — пустое направление, а не ноль процентов",
                  by["cancel"]["trend"]["dir"], "")

        ch = d["chart"]
        res.ok("график: по точке на день периода",
               len(ch["labels"]) == 7 and len(ch["values"]) == 7, f"{ch['labels']}")
        res.check("итог графика равен плитке", ch["total"], by["total"]["value"])
        res.ok("потери названы деньгами", ch["loss"].startswith("cca "), ch["loss"])
        res.ok("ожидание не измерялось — сказано, откуда оно берётся",
               ch["wait"]["text"] == "—" and "A venit" in ch["wait"]["sub"],
               f"{ch['wait']}")

        res.check("три денежные карточки",
                  [m["key"] for m in d["money"]], ["incasari", "estimat", "azi"])
        inc = d["money"][0]
        res.ok("настоящие деньги названы настоящими", "bani reali" in inc["sub"],
               inc["sub"])
        res.check("и ведут на лист кассы за СЕГОДНЯ", inc["link"]["href"], "/admin/casa")
        res.ok("оценка по прайсу названа оценкой",
               "nu e contabilitate" in d["money"][1]["note"][0]["t"],
               f"{d['money'][1]['note']}")
        res.ok("у денег есть и число, и строка, и суффикс",
               all(isinstance(m["value"], int) and m["text"] and m["suffix"] == " MDL"
                   for m in d["money"]), f"{d['money']}")

        res.ok("врачи отсортированы по загрузке",
               [x["pct"] for x in d["doctors"]] == sorted(
                   (x["pct"] for x in d["doctors"]), reverse=True),
               f"{[x['pct'] for x in d['doctors']]}")
        res.ok("услуга названа и посчитана",
               any(x["cnt"] == 2 for x in d["services"]), f"{d['services']}")
        res.ok("лента событий ведёт на фиши",
               all(x["patient_id"] is None or isinstance(x["patient_id"], int)
                   for x in d["activity"]) and d["activity"], f"{d['activity'][:2]}")

        # ⛔ Паритет: те же цифры и подписи на старой странице.
        page = c.get("/admin/stats").body
        res.ok("подписи плиток есть и на старой странице",
               all(t["label"] in page for t in d["tiles"]), "подписи разошлись")
        res.ok("значения плиток есть и на старой странице",
               all(f"data-count='{t['value']}'" in page for t in d["tiles"]),
               "значения разошлись")
        res.ok("имя прошлого периода есть и там", d["compare"] in page, "разошлось")
        res.ok("итоговая сумма денег есть и там",
               all(f"data-count='{m['value']}'" in page for m in d["money"]),
               "деньги разошлись")
        res.ok("загрузка есть и там", f">{d['occupancy']['pct']}%</text>" in page,
               "загрузка разошлась")

        # ⛔ Негодный период — ОТКАЗ, а не молча другой период. `<input
        # type=date>` отдаёт и «0012-09-15»: промах по сегменту года выглядит
        # законной ISO-датой, а период из неё выходит в 735 000 дней.
        r = c.get("/api/stats?from=0012-09-15&to=" + day)
        res.check("год мимо — 422", r.status, 422)
        res.check("и назван код", _j(r)["code"], "bad_period")
        res.check("и названо поле", _j(r)["field"], "from")
        res.check("период длиннее года — тоже отказ",
                  c.get(f"/api/stats?from=2024-01-01&to={day}").status, 422)
        # перевёрнутый период разворачивается, а не отвергается
        r = c.get(f"/api/stats?from={day}&to={day}")
        res.check("день — период в один день", _j(r)["data"]["period"]["days"], 1)
        res.check("и сравнивается со вчера", _j(r)["data"]["compare"],
                  "față de ziua precedentă")

    # клиника с настроенным ботом (grandfather): шесть плиток и кольцо
    with Server(env=TG_ON) as s:
        c = Client(s.url).login()
        _seed(c)
        d = _j(c.get("/api/stats"))["data"]
        res.check("с ботом плиток шесть", len(d["tiles"]), 6)
        res.check("и кольцо источников показывается", d["sources"]["show"], True)
        res.ok("доли источников сходятся в целое",
               sum(p["value"] for p in d["sources"]["parts"]) == d["sources"]["total"],
               f"{d['sources']}")


def suite_switch(res: Result) -> None:
    """Рубильник экрана и право PERM_MONEY."""
    s = _server_with_flags(env={"ADMIN_KEY": ""})
    with s:
        boss = Client(s.url)
        boss.post("/admin/setup", pin1="1111", pin2="1111")
        boss.post("/admin/users/save", uid="ana", name="Ana R", role="receptie", pin="3333")
        boss.post("/admin/users/save", uid="ion", name="Ion M", role="medic", pin="4444")
        page = boss.get("/admin/stats").body
        res.ok("узел React", 'data-screen="stats"' in page, "узла нет")
        res.ok("период уезжает параметрами узла", "data-params=" in page
               and "from" in page, "параметров нет")
        res.ok("старой разметки нет", "class='tiles'" not in page, "две разметки")
        res.ok("?ui=legacy: старая страница",
               "class='tiles'" in boss.get("/admin/stats?ui=legacy").body, "нет")

        # ⛔ Деньги закрыты не только в меню: адрес набирается руками.
        for who, pin in (("регистратуре", "3333"), ("врачу", "4444")):
            cl = Client(s.url)
            cl.post("/admin/login", password=pin, next="/admin")
            res.check(f"{who} JSON закрыт", cl.get("/api/stats").status, 403)
            r = cl.get("/admin/stats")
            res.ok(f"{who} закрыта и страница",
                   r.status == 303 and r.msg == "no_access", f"{r!r}")
