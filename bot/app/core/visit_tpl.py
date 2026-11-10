"""Шаблоны дневника визита по услуге (10.11.2026, волна «амбулаторка за 15 с»).

Шаблон живёт у УСЛУГИ прайса клиники (`clinic.json › services[].tpl =
{acuze, examen, diagnostic, tratament, recomandari}`), как срок отзыва
`recall` (29.10): таблицы услуг нет по решению, каталог клиники — профиль.
Тексты пишет КЛИНИКА в «Setări › Șabloane consultație»; программа своих
медицинских текстов в них не кладёт — пустой старт и заглушка `EXAMPLE` с
пометкой «Exemplu, editați». ⛔ Слов «conform protocoalelor» / «по протоколам
МЗ» в текстах программы нет: это тексты клиники, не протокол.

Правило «Din șablon» (`compose`, чистая функция — один вычислитель на прогон
и на экран):
1. Источники — услуга ВИЗИТА и услуги ОТМЕЧЕННЫХ позиций плана («efectuate la
   această vizită»), в этом порядке, каждая услуга один раз. Позиция плана
   хранит процедуру свободным текстом (service_id у неё нет), поэтому услуга
   позиции — `match_service` по подписи прайса.
2. `{dinte}` — зубы отмеченных позиций ЭТОЙ услуги через запятую; нет зуба —
   «__» (видно, что вписать: так же метят встроенные заготовки visit.py).
   `{data}` — дата визита в поясе клиники.
3. Несколько услуг — графы склеиваются построчно, одинаковые строки не
   повторяются; пустая графа шаблона ничего не добавляет.
4. Заполняются ТОЛЬКО пустые графы — это делает клиент (клик не должен стереть
   вписанное руками), здесь только тексты.

Живёт в `core`: шаблон читают два модуля (patients — дневник, settings —
экран правки), а сосед не импортирует соседа.
"""
from __future__ import annotations

from .. import db
from .. import engine as eng

FIELDS = db.VISIT_FIELDS
# (name, подпись, строк textarea, placeholder) — графы дневника 043/e в
# порядке бланка; дневник (patients/visit.py) и экран шаблонов берут их отсюда
FORM = (
    ("acuze", "Acuze / motivul prezentării", 2, "Ce acuză pacientul…"),
    ("examen", "Examen obiectiv", 3, "Statusul local, rezultatul examinării…"),
    ("diagnostic", "Diagnostic", 2, "Diagnosticul stabilit…"),
    ("tratament", "Tratament efectuat", 3, "Ce s-a efectuat la această vizită…"),
    ("recomandari", "Recomandări", 2, "Recomandări pentru pacient…"),
)
MAX_LEN = 2000            # как maxLength графы дневника
TOOTH = "{dinte}"
DATE = "{data}"
NO_TOOTH = "__"

# Заглушка для пустого шаблона: кнопка «Exemplu» экрана настроек вставляет её
# в пустые графы. Медицинского содержания в ней нет намеренно — только где
# что писать и как работают метки.
EXAMPLE = {
    "acuze": "",
    "examen": "",
    "diagnostic": "Exemplu, editați: diagnosticul, dintele {dinte}.",
    "tratament": "Exemplu, editați: ce s-a efectuat la dintele {dinte} pe {data}.",
    "recomandari": "Exemplu, editați: recomandările pentru pacient.",
}


def clean(raw) -> dict:
    """Шаблон из тела запроса: только графы дневника, строки, обрезка по
    `MAX_LEN`; пустые графы не хранятся. Не словарь — ValueError (отказ, а не
    молчаливое «пусто»)."""
    if not isinstance(raw, dict):
        raise ValueError("tpl")
    out = {}
    for k in FIELDS:
        v = raw.get(k, "")
        if not isinstance(v, str):
            raise ValueError("tpl")
        v = v.replace("\r\n", "\n").strip()[:MAX_LEN]
        if v:
            out[k] = v
    return out


def merge(prev: dict | None, raw) -> dict:
    """Правка шаблона по ТРОНУТЫМ графам: графа, которой нет в теле, остаётся
    прежней (прайор 08-16 — отсутствие поля значит «не сообщали»), присланная
    пустой — стирается."""
    if not isinstance(raw, dict):
        raise ValueError("tpl")
    sent = clean({k: raw[k] for k in FIELDS if k in raw})
    keep = {k: v for k, v in (prev or {}).items() if k in FIELDS and k not in raw}
    return {k: v for k in FIELDS if (v := sent.get(k) or keep.get(k))}


def of(sid: str) -> dict:
    """Шаблон услуги из применённого конфига; нет — пустой словарь."""
    return dict((eng.SERVICES.get(sid or "") or {}).get("tpl") or {})


def match_service(procedure: str) -> str:
    """Услуга прайса по тексту позиции плана: подпись RO или RU целиком или
    началом («Obturație 26» → Obturație), без регистра; из нескольких — самая
    длинная подпись. Нет — пустая строка."""
    text = " ".join((procedure or "").split()).casefold()
    best, best_len = "", 0
    for sid, s in eng.SERVICES.items():
        for lab in {s.get("ro") or "", s.get("ru") or ""}:
            lab = " ".join(lab.split()).casefold()
            if not lab or len(lab) <= best_len:
                continue
            if text == lab or (text.startswith(lab) and not text[len(lab)].isalnum()):
                best, best_len = sid, len(lab)
    return best


def compose(visit_sid: str, marked: list[dict], day: str) -> dict:
    """Тексты «Din șablon»: `marked` — отмеченные позиции плана
    (`{procedure, tooth}`), `day` — дата визита строкой. Ответ — пять граф
    (пустая строка там, где шаблонам сказать нечего)."""
    order: list[str] = []
    teeth: dict[str, list[str]] = {}
    for sid in [visit_sid or "", *(match_service(it.get("procedure") or "") for it in marked)]:
        if sid and of(sid) and sid not in order:
            order.append(sid)
            teeth[sid] = []
    for it in marked:
        sid = match_service(it.get("procedure") or "")
        t = str(it.get("tooth") or "")
        if sid in teeth and t and t not in teeth[sid]:
            teeth[sid].append(t)
    out = {}
    for k in FIELDS:
        lines: list[str] = []
        for sid in order:
            text = of(sid).get(k, "")
            if not text:
                continue
            text = (text.replace(TOOTH, ", ".join(teeth[sid]) or NO_TOOTH)
                        .replace(DATE, day))
            for line in text.split("\n"):
                if line not in lines:
                    lines.append(line)
        out[k] = "\n".join(lines).strip()
    return out
