"""Выгрузка ВСЕХ данных одного пациента — право на доступ и переносимость.

Закон 195/2024 (в силе с 23.08.2026) даёт пациенту право получить копию своих
данных, а клинике — обязанность её выдать. До этого модуля выдавать было
нечем: данные одного человека разбросаны по семи таблицам и папке с файлами, и
собрать их вручную означало открыть базу SQL-клиентом.

В архиве ДВА представления одних и тех же данных, и это не дублирование:
  * `date-pacient.json` — машиночитаемое, для переноса в другую программу
    (переносимость требует «структурированный, общеупотребимый формат»);
  * `fisa-pacient.html` — читаемое человеком, для самого пациента.
Одного мало: JSON пациенту не объяснить, а HTML никуда не перенести.

⚠️ Сама выдача копии — тоже событие обработки, и при проверке спросят именно
её. Поэтому маршрут пишет `log_event`; здесь этого нет намеренно, чтобы сборку
архива можно было позвать из теста, ничего не записывая в летопись.
"""
from __future__ import annotations

import html
import json
import pathlib
import re
import unicodedata
import zipfile
from datetime import date, datetime

from ... import db
from ... import engine as eng
from ... import teeth_svg as tsvg
from ...core.layout import ALERT_KINDS, SOURCE_LABEL, STATUS_LABEL
from . import anamneza as panam
from . import fisa043 as pfisa

# Пределы выборок сняты намеренно. У карточки они есть и уместны (боковому
# предпросмотру хватает двадцати визитов), но копия с отрезанным хвостом не
# выполняет право на доступ, а молча его нарушает.
_ALL = 1_000_000

# НАШИ имена внутри архива — БЕЗ диакритики. Архив уезжает на чужой компьютер
# и открывается чем попало; ZIP хранит имена в UTF-8 только с выставленным
# флагом, и старые распаковщики показывают «fi?a-pacient».
# ⚠️ На имена ЗАГРУЖЕННЫХ документов это правило не распространяется (см.
# `_safe_name`): там выбор другой — либо чужой алфавит в имени, либо три
# разных документа под именами «_.jpg», «_2.jpg», «_3.jpg».
_README = "CITESTE-MA.txt"
_JSON = "date-pacient.json"
_HTML = "fisa-pacient.html"
_DOCDIR = "documente"


def _plain(value):
    """datetime → ISO. Без этого json.dumps падает на колонках-датах: `_fetch`
    возвращает их объектами (см. `_DT_COLS` в db.py), а не строками."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f"не умею сериализовать {type(value).__name__}")


async def collect(pid: int) -> dict | None:
    """Все данные пациента из ВСЕХ таблиц, где он упомянут.

    ⚠️ Состав этого словаря обязан совпадать с тем, что вычищает удаление
    пациента: обе функции отвечают на один вопрос «где в базе лежит этот
    человек». Разойдясь, они дадут либо неполную выдачу, либо неполное
    удаление — и то и другое нарушение, а заметить его неоткуда.
    """
    p = await db.get_patient(pid)
    if not p:
        return None
    teeth = await db.teeth_map(pid)
    return {
        "generat_la": datetime.now(eng.TZ).isoformat(timespec="seconds"),
        # кто оператор данных — первое, что должно быть видно в копии
        "clinica": {"nume": eng.CLINIC_NAME, "telefon": eng.CLINIC_PHONE,
                    "adresa": (eng.CONFIG or {}).get("address", {})},
        "pacient": p,
        "programari": await db.patient_appointments(pid, _ALL),
        "atentionari": await db.patient_alerts(pid),
        "dinti": [teeth[t] for t in sorted(teeth)],
        "plan_tratament": await db.plan_items(pid),
        "anamneza": await db.anamneza(pid),
        "consultatii": await db.patient_visit_records(pid),
        "plati": await db.payments(pid),
        "documente": await db.documents_with_paths(pid),
        # include_views: в КОПИЮ входят и просмотры — «кто открывал карту»
        # такая же обработка данных, как «кто менял», и пациент вправе её видеть
        "istoric": await db.patient_activity(pid, _ALL, include_views=True),
    }


# ---------- читаемое человеком представление ----------

def _dt(value, with_time: bool = True) -> str:
    if not value:
        return "—"
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return html.escape(value)
    # ⚠️ в базе время в UTC, а читает копию пациент — в своём местном. Без
    # перевода визит, назначенный на 09:00, печатается как 06:00, и ошибка
    # ничем себя не выдаёт: дата правильная, формат правильный, час чужой.
    # Проверять tzinfo обязательно: due_date — голая дата без пояса, и
    # astimezone на наивном значении подставил бы пояс машины и сдвинул день.
    if getattr(value, "tzinfo", None) is not None:
        value = value.astimezone(eng.TZ)
    return value.strftime("%d.%m.%Y %H:%M" if with_time else "%d.%m.%Y")


def _esc(value) -> str:
    return html.escape("" if value is None else str(value))


def _word(labels: dict, code) -> str:
    """Код базы — словом. ⚠️ Словари здесь НЕ заводятся: статус визита живёт в
    core.layout.STATUS_LABEL, статус позиции плана — в fisa043.PLAN_RO. Копия
    по 195-му обязана быть «в понятной форме», а второе имя того же состояния
    — это ровно то, из-за чего словарь статусов и стал единственным."""
    return _esc(labels.get(code, code)) or "—"


_PROFILE_RO = [
    ("name", "Nume"), ("phone", "Telefon"), ("email", "E-mail"),
    ("birth_date", "Data nașterii"), ("gender", "Sex"), ("idnp", "IDNP"),
    ("address", "Adresa"), ("insurance", "Asigurare"),
    ("primary_doctor", "Medic curant"), ("file_no", "Nr. fișă"),
    ("notes", "Note"), ("session_key", "Identificator canal"),
]


def _table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return "<p class='gol'>— nu există înregistrări —</p>"
    head = "".join(f"<th>{h}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>"
                   for r in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def render_html(data: dict) -> str:
    """Страница для самого пациента. Самодостаточная: открывается двойным
    кликом на любом компьютере, без интернета и без нашей программы."""
    p = data["pacient"]
    cl = data["clinica"]
    addr = cl["adresa"]
    addr = addr.get("ro") or next(iter(addr.values()), "") if isinstance(addr, dict) else addr

    def _field(key: str) -> str:
        # дата рождения человеку — dd.mm.yyyy, как остальные даты этого листа
        if key == "birth_date":
            return _dt(p.get(key), with_time=False)
        return _esc(p.get(key)) or "—"

    profil = _table(["Câmp", "Valoare"],
                    [[_esc(lbl), _field(key)] for key, lbl in _PROFILE_RO])
    programari = _table(
        ["Data", "Serviciu", "Medic", "Stare", "Sursa", "Comentariu"],
        [[_dt(v["starts_at"]), _esc(v["service"]), _esc(v["doctor"]),
          _word(STATUS_LABEL, v["status"]), _word(SOURCE_LABEL, v["source"]),
          _esc(v["comment"]) or "—"]
         for v in data["programari"]])
    atentionari = _table(
        ["Tip", "Text"],
        [[_word(ALERT_KINDS, a["kind"]), _esc(a["text"])]
         for a in data["atentionari"]])
    def _surfaces_ro(t: dict) -> str:
        """Поверхности для ЧЕЛОВЕКА: буквы, а при разных состояниях — словами.

        Право на доступ по 195-му означает увидеть то, что клиника хранит, а
        хранит она теперь состояние КАЖДОЙ поверхности. Голое «MO» рядом с
        колонкой «Stare: Carie» скрыло бы пломбу, которая там же и записана.
        (Машинная копия в date-pacient.json несёт колонку `surface_states` как
        есть — она уходит из строки таблицы `teeth` целиком.)"""
        sf = t.get("surfaces") or ""
        parts = tsvg.surface_summary(tsvg.surface_map(
            t.get("state", "ok"), sf, t.get("surface_states") or ""))
        if len(parts) > 1:
            return " · ".join(f"{ls}: {tsvg.STATE_RO[st]}" for st, ls in parts)
        return sf

    dinti = _table(
        ["Dinte", "Stare", "Suprafețe", "Medic", "Notă", "Actualizat"],
        # ⚠️ Состояние зуба — СЛОВОМ, как и всё остальное в этой копии: «lipsa»
        # рядом с колонкой, развёрнутой в «M: Carie», это второе имя одного
        # состояния в одном документе (та же болезнь, что STATUS_LABEL)
        [[_esc(t["tooth"]), _word(tsvg.STATE_RO, t["state"]),
          _esc(_surfaces_ro(t)) or "—",
          _esc(t["doctor"]) or "—",
          _esc(t["note"]) or "—", _dt(t["updated_at"])] for t in data["dinti"]])
    # ⚠️ Причина отказа входит в копию по 195-му наравне с остальным: это
    # данные о пациенте, которые клиника о нём хранит, и «право на доступ»
    # означает в том числе увидеть, как записан собственный отказ
    plan = _table(
        ["Dinte", "Procedură", "Medic", "Stare", "Preț (MDL)", "Termen",
         "Motivul refuzului"],
        [[_esc(i["tooth"]) or "—", _esc(i["procedure"]), _esc(i["doctor"]),
          _word(pfisa.PLAN_RO, i["status"]), _esc(i["price_mdl"]) or "—",
          _dt(i["due_date"], with_time=False),
          _esc(i.get("refuz_motiv")) or "—"] for i in data["plan_tratament"]])
    # ⚠️ Колонка «În arhivă» — не украшение: без неё строку таблицы не с чем
    # сопоставить в папке `documente/` (имена там обезврежены), а потерянный
    # на диске файл выглядит выданным. Заполняется она в write_archive, ДО
    # рендера этой страницы, — иначе пометка доехала бы только до JSON.
    documente = _table(
        ["Fișier", "Categorie", "Mărime", "Încărcat", "În arhivă"],
        [[_esc(d["filename"]), _esc(d["category"]),
          f"{round((d['size'] or 0) / 1024)} KB", _dt(d["uploaded_at"]),
          _esc(d.get("fisier_in_arhiva") or d.get("eroare")) or "—"]
         for d in data["documente"]])
    plati = _table(
        ["Data", "Suma (MDL)", "Metoda", "Notă", "Încasat de"],
        [[_dt(pl["at"]), _esc(pl["amount_mdl"]), _esc(pl["method"]),
          _esc(pl["note"]) or "—", _esc(pl["taken_by"]) or "—"]
         for pl in data["plati"]])

    an = dict(data.get("anamneza") or {})
    # ⚠️ копия по 195-му обязана быть В ПОНЯТНОЙ ФОРМЕ: слаги «coagulare,
    # tiroida» этого не дают. В JSON ключи остаются как есть (машинный формат),
    # а в читаемой фише разворачиваются в вопросы
    if an:
        an["flags"] = ", ".join(panam.marked(an.get("flags") or ""))
    anamneza = _table(
        ["Câmp", "Valoare"],
        [[_esc(lbl), _esc(an.get(key)) or "—"] for key, lbl in (
            ("flags", "Afecțiuni bifate"),
            ("boli", "Alte boli"),
            ("medicamente", "Medicamente"),
            ("alergii", "Alergii"),
            ("anestezie", "Reacții la anestezice"),
        )] + [["Completată", _dt(an.get("updated_at") or an.get("created_at"))],
              ["Înregistrată de", _esc(an.get("author")) or "—"]]
    ) if an else "<p class='gol'>— nu există înregistrări —</p>"

    # четыре текстовых графы дневника — одной ячейкой: девять колонок
    # в 960px нечитаемы, а пустые графы просто не печатаются
    def _consemnari(c: dict) -> str:
        parts = [f"<b>{lbl}:</b> {_esc(c[key])}"
                 for key, lbl in (("acuze", "Acuze"), ("examen", "Examen"),
                                  ("tratament", "Tratament"),
                                  ("recomandari", "Recomandări"))
                 if (c.get(key) or "").strip()]
        return "<br>".join(parts) or "—"

    consultatii = _table(
        ["Data vizitei", "Serviciu", "Medic", "Diagnostic", "Consemnări"],
        [[_dt(c["starts_at"]), _esc(c["service"]), _esc(c["doctor"]) or "—",
          _esc(c["diagnostic"]) or "—", _consemnari(c)]
         for c in data["consultatii"]])
    istoric = _table(
        ["Data", "Autor", "Eveniment"],
        [[_dt(e["at"]), _esc(e["actor"]), _esc(e["text"])]
         for e in data["istoric"]])

    return f"""<!doctype html><html lang="ro"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Date personale — {_esc(p.get('name'))}</title><style>
 body{{font-family:'Segoe UI',system-ui,sans-serif;margin:0;padding:32px;
      background:#F6FBF8;color:#162033;line-height:1.5}}
 .wrap{{max-width:960px;margin:0 auto}}
 h1{{font-size:22px;margin:0 0 4px}}
 h2{{font-size:16px;margin:28px 0 8px;padding-top:14px;border-top:1px solid #E7EDF5}}
 .sub{{color:#7E8B9C;font-size:13px;margin:0 0 6px}}
 table{{border-collapse:collapse;width:100%;font-size:14px;background:#fff;
       border:1px solid #E7EDF5;border-radius:10px;overflow:hidden}}
 th,td{{text-align:left;padding:8px 10px;border-bottom:1px solid #EEF3F8;
       vertical-align:top}}
 th{{background:#F2F7FB;font-weight:600;font-size:13px}}
 tr:last-child td{{border-bottom:none}}
 .gol{{color:#7E8B9C;font-size:14px;margin:4px 0}}
 .nota{{background:#fff;border:1px solid #E7EDF5;border-radius:10px;
       padding:14px 16px;font-size:13px;color:#4A5768;margin-top:28px}}
</style></head><body><div class="wrap">
<h1>Date cu caracter personal</h1>
<p class="sub">Operator: <b>{_esc(cl['nume'])}</b>{f' · {_esc(addr)}' if addr else ''}
{f' · {_esc(cl["telefon"])}' if cl.get('telefon') else ''}</p>
<p class="sub">Copie generată la {_dt(data['generat_la'])}</p>

<h2>Fișa pacientului</h2>{profil}
<h2>Programări ({len(data['programari'])})</h2>{programari}
<h2>Atenționări medicale ({len(data['atentionari'])})</h2>{atentionari}
<h2>Anamneză</h2>{anamneza}
<h2>Starea dinților ({len(data['dinti'])})</h2>{dinti}
<h2>Plan de tratament ({len(data['plan_tratament'])})</h2>{plan}
<h2>Consultații ({len(data['consultatii'])})</h2>{consultatii}
<h2>Plăți ({len(data['plati'])})</h2>{plati}
<h2>Documente ({len(data['documente'])})</h2>{documente}
<h2>Istoricul fișei ({len(data['istoric'])})</h2>{istoric}

<div class="nota">Acest fișier conține <b>date despre sănătate</b> — o categorie
specială de date personale. Păstrați-l într-un loc sigur și nu îl transmiteți
persoanelor neautorizate. Fișierele atașate se află în folderul
<code>{_DOCDIR}/</code>, iar aceleași date în format prelucrabil — în
<code>{_JSON}</code>.</div>
</div></body></html>"""


# ---------- упаковка ----------

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")

# Что в имени файла ОПАСНО — и ничего сверх того: разделители путей, знаки,
# которые Windows в имени не заводит, управляющие символы и пробелы.
# ⚠️ Прежде здесь стоял `_SAFE`, то есть «всё, кроме латиницы», — и от
# кириллического имени не оставалось ни одного знака: «снимок.jpg» ложился в
# архив как «_.jpg», а три таких документа — как «_.jpg», «_2.jpg», «_3.jpg».
# Половина регистратур в Молдове называет файлы по-русски, и связать строку
# таблицы «Documente» с папкой архива было уже нечем.
_UNSAFE = re.compile(r'[\x00-\x1f\x7f<>:"/\\|?*\s]+')
# имена, которые Windows не заводит НИ С КАКИМ расширением
_WIN_RESERVED = ({"CON", "PRN", "AUX", "NUL"}
                 | {f"COM{i}" for i in range(1, 10)}
                 | {f"LPT{i}" for i in range(1, 10)})


def _deaccent(text: str) -> str:
    """Снять диакритику там, где под ней латиница: «fișă» → «fisa».

    Архив уезжает на чужой компьютер, и румынские надстрочные там читаются
    как повезёт — поэтому имена без них. ⛔ Другие письменности НЕ трогать:
    «й» разложилось бы в «и», и два разных имени слиплись бы в одно.
    """
    out = []
    for ch in text:
        if ch.isascii():
            out.append(ch)
            continue
        bare = "".join(c for c in unicodedata.normalize("NFKD", ch)
                       if not unicodedata.combining(c))
        out.append(bare if bare and bare.isascii() else ch)
    return "".join(out)


def _safe_name(filename: str, used: set[str]) -> str:
    """Имя файла, безопасное ВНУТРИ архива — и по-прежнему узнаваемое.

    Имя пришло от пользователя при загрузке, то есть может содержать `..`,
    слэши и что угодно ещё. Распаковщик, честно повторяющий такой путь, пишет
    файл мимо папки назначения (zip-slip) — поэтому от исходного имени берётся
    только основа, а всё небезопасное заменяется. Совпадения разводятся
    номером: два «radiografie.jpg» иначе затрут друг друга при распаковке.
    ⭐ «Безопасно» не значит «неразличимо»: вычищается опасное, а не всё
    незнакомое (нелатинские имена ZIP хранит в UTF-8 с выставленным флагом).
    Расширение остаётся строго латинским — по нему файл открывают, и белый
    список `_OPEN_EXT` в фише тоже латинский.
    """
    base = pathlib.PurePosixPath(filename.replace("\\", "/")).name or "fisier"
    stem, dot, ext = base.rpartition(".")
    stem = _UNSAFE.sub("_", _deaccent(stem or base)).strip(" ._")[:60] or "fisier"
    if stem.upper() in _WIN_RESERVED:
        stem = "_" + stem
    ext = _SAFE.sub("", _deaccent(ext))[:10] if dot else ""
    name = f"{stem}.{ext}" if ext else stem
    n = 2
    while name.lower() in used:
        name = f"{stem}_{n}.{ext}" if ext else f"{stem}_{n}"
        n += 1
    used.add(name.lower())
    return name


def _readme(data: dict) -> str:
    p = data["pacient"]
    return (
        "DATE CU CARACTER PERSONAL\r\n"
        "=========================\r\n\r\n"
        f"Pacient: {p.get('name') or '—'} (fisa nr. {p.get('id')})\r\n"
        f"Operator: {data['clinica']['nume']}\r\n"
        f"Copie generata la: {_dt(data['generat_la'])}\r\n\r\n"
        "Ce contine arhiva:\r\n"
        f"  {_HTML}  - toate datele intr-o forma citibila (deschideti in browser)\r\n"
        f"  {_JSON}  - aceleasi date in format prelucrabil, pentru transfer\r\n"
        f"  {_DOCDIR}/ - fisierele atasate fisei (radiografii, acorduri, alte documente)\r\n\r\n"
        "ATENTIE: arhiva contine date despre sanatate - o categorie speciala de\r\n"
        "date personale. Pastrati-o intr-un loc sigur.\r\n")


async def write_archive(pid: int, dest: pathlib.Path) -> dict | None:
    """Собрать архив по пути `dest`. Возвращает собранные данные (для журнала
    и имени файла) или None, если пациента нет."""
    data = await collect(pid)
    if data is None:
        return None
    used: set[str] = set()
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(_README, _readme(data))
        # ⚠️ Сначала СУДЬБА документов, и только потом читаемая страница: она
        # печатает и имя файла в архиве, и пометку о потерянном. Пока порядок
        # был обратным, «выдать не смогли» доезжало только до машинного JSON —
        # то есть до файла, который пациенту как раз и не предлагают открывать,
        # а в fisa-pacient.html пропавший документ выглядел обычным.
        for d in data["documente"]:
            src = pathlib.Path(d["stored_path"])
            inner = _safe_name(d["filename"], used)
            # имя внутри архива уходит и в JSON: иначе список документов
            # ссылается на файлы, которых под такими именами в архиве нет
            d["fisier_in_arhiva"] = f"{_DOCDIR}/{inner}"
            if src.is_file():
                z.write(src, f"{_DOCDIR}/{inner}")
            else:
                # файл потерян на диске — молчать нельзя: в копии обязано быть
                # видно, что документ существовал, но выдать его не смогли
                d["fisier_in_arhiva"] = None
                d["eroare"] = "fisierul lipseste pe disc"
        # stored_path наружу не отдаём: это раскладка компьютера клиники,
        # к данным пациента она не относится
        for d in data["documente"]:
            d.pop("stored_path", None)
        z.writestr(_HTML, render_html(data))
        z.writestr(_JSON, json.dumps(data, ensure_ascii=False, indent=1,
                                     default=_plain))
    return data


def archive_name(data: dict) -> str:
    """Имя файла для скачивания: узнаваемое и без диакритики."""
    p = data["pacient"]
    who = _SAFE.sub("_", (p.get("name") or "pacient").strip())[:40].strip("_")
    stamp = datetime.now(eng.TZ).strftime("%Y%m%d")
    return f"date-{who or 'pacient'}-{p.get('id')}-{stamp}.zip"
