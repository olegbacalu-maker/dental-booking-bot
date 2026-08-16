"""Летопись фиши: событие записывается СЛОВОМ, а не внутренним кодом.

`db.log_event` хранит готовую строку, и переписать её потом нельзя — летопись
отвечает на вопрос «кто что сделал», а не «как это выглядит сегодня». Значит
единственный момент, когда код можно развернуть в слово, — сам момент события;
промах здесь чинится только новыми строками, старые остаются машинными
навсегда.

Ту же строку читают ДВОЕ: лента фиши (регистратура, каждый день) и выгрузка по
Legea 195 (пациент, «в понятной форме»). В таблицах выгрузки коды развернули
08-15, а лента осталась с «Plan: Plombă › in_lucru», «Dinte 26: obturatie» и
«Vizită neprezentare» — то есть право на понятную копию исполнялось наполовину.

⚠️ Проверка смотрит в МАШИННУЮ копию (`date-pacient.json`), а не в страницу:
там лежит ровно тот текст, что записан в базу, и совпадение подстроки нельзя
списать на слово, дорисованное разметкой рядом.
"""
import io
import json
import re
import zipfile
from datetime import date, timedelta

from harness import Client, Result, Server

# Знаки, которые рисует система (те же диапазоны, что стережёт
# test_structure._SYSGLYPH): в тексте события им не место так же, как на экране,
# — летопись уезжает и в ленту фиши, и в печатную копию по 195-му.
_SYSGLYPH = re.compile("[🀀-🫿←-⇿∀-⋿⌀-⏿"
                       "■-➿⬀-⯿]")


def _d(offset: int) -> str:
    return (date.today() + timedelta(days=offset)).isoformat()


def _pid(c: Client, phone: str) -> str:
    return c.get(f"/admin/search?q={phone}").body.split(
        "/admin/patient/", 1)[1].split("'")[0].split('"')[0].split("?")[0]


def _istoric(c: Client, pid: str) -> list[str]:
    """Тексты событий фиши — из машинной копии выгрузки по 195-му."""
    z = zipfile.ZipFile(io.BytesIO(c.get(f"/admin/patient/{pid}/export").raw))
    data = json.loads(z.read("date-pacient.json").decode("utf-8"))
    return [e["text"] for e in data["istoric"]]


def suite_words(res: Result) -> None:
    with Server() as s:
        c = Client(s.url).login()
        c.post("/admin/add", adate=_d(1), atime="09:00", adoctor="d2",
               aservice="consult", aname="Cronica Test", aphone="022919191",
               back="/admin/all")
        pid = _pid(c, "022919191")

        # позиция плана: «planificat» не годится — у него код и слово совпадают,
        # и проверка на нём ничего бы не доказала
        c.post(f"/admin/patient/{pid}/plan", procedure="Obturație 26",
               tooth="26", price="600", doctor="Dr. Ana")
        c.post(f"/admin/patient/{pid}/plan", procedure="Detartraj",
               price="500", doctor="Dr. Ana")
        page = c.get(f"/admin/patient/{pid}").body
        iids = []
        for m in re.findall(r"/plan/(\d+)/status", page):
            if m not in iids:
                iids.append(m)
        res.ok("две позиции плана заведены", len(iids) >= 2,
               f"позиций на странице: {len(iids)}")
        c.post(f"/admin/patient/{pid}/plan/{iids[0]}/status", to="in_lucru")
        c.post(f"/admin/patient/{pid}/plan/{iids[1]}/del")

        c.post(f"/admin/patient/{pid}/tooth", tooth="26", state="obturatie",
               doctor="d2")

        aid = c.get(f"/admin/all?date={_d(1)}").body.split(
            "/admin/status/", 1)[1].split("'")[0]
        c.post(f"/admin/status/{aid}", to="noshow", back="/admin/all")

        acts = _istoric(c, pid)

        res.ok("статус позиции плана записан словом",
               any("› în lucru" in t for t in acts)
               and not any("in_lucru" in t for t in acts),
               f"в летописи остался код позиции плана: {acts}")

        res.ok("состояние зуба записано словом",
               any("Dinte 26: Obturație" in t for t in acts)
               and not any("obturatie" in t for t in acts),
               f"в летописи остался ключ одонтограммы: {acts}")

        # ⚠️ «словом» мало: собственный словарь db звал этот статус
        # «neprezentare», а кнопка, которую нажала регистратура, — «nu a venit».
        # Одно состояние, два имени на соседних экранах.
        res.ok("статус визита назван словом ЖУРНАЛА",
               any("Vizită nu a venit" in t for t in acts)
               and not any("noshow" in t or "neprezentare" in t for t in acts),
               f"летопись зовёт статус по-своему: {acts}")

        bad = [t for t in acts if _SYSGLYPH.search(t)]
        res.ok("в текстах событий нет знаков от Windows", not bad,
               f"знак вне подмножеств вшитого Inter: {bad}")

        # та же строка на самом экране — лента фиши читает её как есть
        page = c.get(f"/admin/patient/{pid}").body
        res.ok("лента фиши показывает те же слова",
               "Vizită nu a venit" in page and "› în lucru" in page,
               "на экране лента расходится с записанным текстом")
