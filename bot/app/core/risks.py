"""Предупреждения пациента одним списком: atenționări фиши и анамнез (22.10).

Карточка визита дня ОДНОГО врача (вариант A Олега) показывает их колонкой, и
одно и то же не должно стоять в ней дважды. На кадрах макета стояло:
«Anticoagulant: Xarelto 20 mg» (atenționare) рядом с «Xarelto 20 mg/zi»
(поле «Medicamente» анамнеза) и «Sarcină, trimestrul II» рядом с галочкой
«Sarcină / alăptare».
⛔ Правило сведения ОДНО — `merge` здесь; второго (в браузере, в экране)
не заводить: разойдутся молча, и врач увидит дубль на одном экране и
пропажу на другом.

Как сводится, от точного к общему:
1. atenționări фиши — все и первыми: их пишут руками, и они точнее всего;
2. свободные поля анамнеза режутся на части по запятой; часть пропадает,
   если её первое значимое слово уже есть в atenționare («Xarelto…» при
   «Anticoagulant: Xarelto 20 mg»), остальное остаётся («Concor 5 mg»);
   порядок полей — от опасного: аллергии, реакции на анестезию, лекарства,
   прочие болезни;
3. галочка анамнеза пропадает, если её корень есть в уже показанном тексте
   (`FLAG_ROOTS`: «Sarcină» при «Sarcină, trimestrul II», «Tulburări de
   coagulare» при «Anticoagulant…»).
Сравнение — по словам без диакритики и регистра.

Значки и тона atenționări — тоже здесь (`ALERT_ICON`, `ALERT_TONE`): их
берёт и фиша (`patients/card.py`), и журнал, а соседние модули друг друга не
импортируют.
"""
from __future__ import annotations

import re
import unicodedata

# Значки — ИМЕНАМИ из layout._I: клиент рисует <Icon>. Сами подписи видов
# (ALERT_KINDS) живут в core/layout.
ALERT_ICON = {"allergy": "sos", "medication": "pill", "warning": "alarm", "info": "info"}
ALERT_TONE = {"allergy": "orange", "medication": "orange", "warning": "red"}

# Свободные поля анамнеза — от опасного к общему; значок — по смыслу поля.
# Ключи — `anamneza.TEXTS`; сверяет набор прогона (список имён гниёт молча).
FREE_ORDER = ("alergii", "anestezie", "medicamente", "boli")
FREE_ICON = {"alergii": "sos", "anestezie": "alarm", "medicamente": "pill", "boli": "info"}

# Корни, по которым галочка анамнеза узнаёт себя в уже показанном тексте:
# слово, НАЧИНАЮЩЕЕСЯ с корня (без диакритики). Ключи — `anamneza.FLAGS`;
# сверяет набор прогона — новая галочка без корней дублировалась бы молча.
FLAG_ROOTS = {
    "cardio": ("cardi", "hipertens", "inim"),
    "diabet": ("diabet",),
    "coagulare": ("coagul", "anticoagul", "hemofil"),
    "hepatita": ("hepatit",),
    "hiv": ("hiv", "sida"),
    "tuberculoza": ("tubercul",),
    "epilepsie": ("epilep",),
    "astm": ("astm",),
    "renale": ("renal", "rinich"),
    "tiroida": ("tiroid",),
    "sarcina": ("sarcin", "gravid", "alapt"),
    "fumat": ("fumat", "fumeaz", "tutun"),
}

# Слова, которые ничего не называют: «alergie la penicilină» узнаётся по
# «penicilină», а не по «alergie» — иначе любая аллергия анамнеза пропадала
# бы при любой аллергии фиши.
_STOP = frozenset({"alergie", "alergic", "alergica", "alergii", "reactie", "reactii",
                   "intoleranta", "boala", "boli", "tratament", "medicament",
                   "medicamente", "pacient", "pacienta"})


def fold(s: str) -> str:
    """Без диакритики и регистра: «Sarcină» и «sarcina» — одно слово."""
    return "".join(ch for ch in unicodedata.normalize("NFKD", s or "")
                   if not unicodedata.combining(ch)).lower()


def _words(s: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", fold(s))


def _key(part: str) -> str:
    """Первое значимое слово части: четыре буквы и больше, не из `_STOP`."""
    return next((w for w in _words(part) if len(w) >= 4 and not w.isdigit()
                 and w not in _STOP), "")


def _same(a: str, b: str) -> bool:
    """Одно слово в разных формах: «penicilină» — «penicilina», «Xarelto» —
    «xarelto». Короче пяти букв — только целиком."""
    return a == b or (len(a) >= 5 and len(b) >= 5 and a[:5] == b[:5])


def merge(alerts: list, anam: dict | None) -> list[dict]:
    """Список строк колонки: {tone, icon, text, title}, сведённый без дублей.

    `alerts` — строки `patient_alerts` (kind, text) по порядку заведения;
    `anam` — строка анамнеза или None. Слово «не собран» здесь не печатается:
    его рисует экран по `state` анамнеза.
    """
    # ⚠️ Отложенный импорт: словарь анамнеза живёт в модуле фиши, а core
    # импортируется раньше модулей (как `db` берёт `perio`/`fisa043`).
    from ..modules.patients import anamneza as panam

    out: list[dict] = []
    seen: list[str] = []
    for a in alerts:
        text = (a.get("text") or "").strip()
        if not text:
            continue
        out.append({"tone": ALERT_TONE.get(a.get("kind"), "grey"),
                    "icon": ALERT_ICON.get(a.get("kind"), "info"),
                    "text": text, "title": text})
        seen += _words(text)
    if not anam:
        return out
    shown = list(seen)
    for k in FREE_ORDER:
        label = panam.TEXT_LABELS["ro"][k]
        for part in re.split(r"[,;\n]+", anam.get(k) or ""):
            part = part.strip()
            key = _key(part)
            if not part or (key and any(_same(key, w) for w in seen)):
                continue
            out.append({"tone": "amber", "icon": FREE_ICON[k], "text": part,
                        "title": f"{label}: {part}"})
            shown += _words(part)
    flags = set((anam.get("flags") or "").split(","))
    for k, full in panam.FLAGS["ro"].items():
        if k not in flags:
            continue
        if any(w.startswith(r) for w in shown for r in FLAG_ROOTS.get(k, ())):
            continue
        out.append({"tone": "amber", "icon": "", "text": full.split(" / ")[0], "title": full})
    return out
