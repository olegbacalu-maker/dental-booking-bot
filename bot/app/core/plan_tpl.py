"""Шаблоны плана лечения клиники (`clinic.json › plan_templates`).

Шаблон — сохранённый набор позиций плана: имя, заметка и строки по порядку
лечения. Строка — процедура (услуга прайса по `service_id` или свободный
текст), признак «нужен зуб» и цена (None — из прайса на день вставки).
Вставленный в план пациента набор — КОПИЯ строк, ссылки на шаблон в плане
нет: правка шаблона меняет только будущие вставки.

В шаблоне нет ничего о пациенте — ни зуба, ни врача, ни срока: каталог
клиники уезжает в копию и на другой ПК вместе с профилем.

Живёт в `core`: шаблон читают два модуля (settings — экран правки,
patients — вставка в план), а сосед не импортирует соседа. Хранимый вид
строки тот же, что у `eng.PLAN_TEMPLATES`, — все четыре ключа всегда.
"""
from __future__ import annotations

import re

from .. import engine as eng
from . import prices

NAME_MAX = 60
NOTE_MAX = 120
# текст процедуры — как у позиции плана фиши; потолок цены у шаблона и у
# позиции один: строка шаблона становится позицией как есть
PROC_MAX = 120
PRICE_MAX = prices.PRICE_MAX
ROWS_MAX = 40
TPL_MAX = 100
FIELDS = ("name", "note", "rows")
SEQ = "plan_tpl"
_ID_RE = re.compile(r"pt(\d+)")


def _text(raw, limit: int, field: str) -> str:
    if not isinstance(raw, str):
        raise ValueError(field)
    return " ".join(raw.split())[:limit]


def _row(raw) -> dict:
    """Строка шаблона из тела запроса. Услуга прайса называется текущим именем
    прайса; услуги с таким id нет — строка остаётся свободным текстом без
    ключа. Цена — целое число леев или пусто."""
    if not isinstance(raw, dict):
        raise ValueError("rows")
    sid = raw.get("service_id") or ""
    if not isinstance(sid, str):
        raise ValueError("rows")
    svc = eng.SERVICES.get(sid.strip())
    proc = svc["ro"] if svc else _text(raw.get("procedure", ""), PROC_MAX, "rows")
    if not proc:
        raise ValueError("rows")
    tooth = raw.get("tooth", True)
    if not isinstance(tooth, bool):
        raise ValueError("rows")
    price = raw.get("price")
    if isinstance(price, str):
        if not price.strip():
            price = None
        elif price.strip().isdecimal():
            price = int(price)
    if price is not None and (type(price) is not int or not 0 <= price <= PRICE_MAX):
        raise ValueError("price")
    return {"procedure": proc, "service_id": sid.strip() if svc else "",
            "tooth": tooth, "price": price}


def _field(key: str, raw):
    if key == "name":
        if not (name := _text(raw, NAME_MAX, "name")):
            raise ValueError("name")
        return name
    if key == "note":
        return _text(raw, NOTE_MAX, "note")
    if not isinstance(raw, list) or not raw or len(raw) > ROWS_MAX:
        raise ValueError("rows")
    return [_row(r) for r in raw]


def clean(raw) -> dict:
    """Новый шаблон из тела запроса: имя и хотя бы одна строка обязательны.
    Отказ — ValueError с именем виновного поля (`name` / `note` / `rows` /
    `price`)."""
    if not isinstance(raw, dict):
        raise ValueError("rows")
    return {"name": _field("name", raw.get("name", "")),
            "note": _field("note", raw.get("note", "")),
            "rows": _field("rows", raw.get("rows"))}


def merge(prev: dict, raw) -> dict:
    """Правка шаблона по ТРОНУТЫМ полям: поле, которого нет в теле, остаётся
    как лежит в профиле, без повторного разбора; строки — одно поле, они
    приходят списком целиком."""
    if not isinstance(raw, dict):
        raise ValueError("rows")
    out = dict(prev)
    for k in FIELDS:
        if k in raw:
            out[k] = _field(k, raw[k])
    return out


def _stored() -> list:
    """Записи шаблонов, как они лежат в профиле (файл правят и руками)."""
    raw = eng.CONFIG.get("plan_templates")
    return raw if isinstance(raw, list) else []


def _next_seq() -> int:
    """Счётчик id только растёт и переживает удаление шаблона: вкладка,
    открытая до удаления, не должна своей правкой попасть в чужой новый
    шаблон с тем же id."""
    n = int((eng.CONFIG.get("seq") or {}).get(SEQ) or 0)
    for t in _stored():
        m = _ID_RE.fullmatch(str(t.get("id") or "")) if isinstance(t, dict) else None
        if m:
            n = max(n, int(m.group(1)))
    return n


def apply(body: dict) -> tuple[list[dict], dict, list[str]]:
    """Тело записи → (новый `plan_templates`, новый `seq`, id созданных).

    `templates: {id: {тронутые поля}}` — правка; шаблон, удалённый в другой
    вкладке, молча пропускается. `new: [{name, note, rows}]` — новые, в конец.
    `deleted: [id]` — удалить. Нетронутые шаблоны переезжают как лежат.
    Одинаковых имён быть не может — ValueError("dup")."""
    edits = body.get("templates", {})
    new = body.get("new", [])
    gone = body.get("deleted", [])
    if not isinstance(edits, dict) or not isinstance(new, list) or not isinstance(gone, list):
        raise ValueError("rows")
    known = {t["id"] for t in eng.PLAN_TEMPLATES}
    out, seen = [], set()
    for t in _stored():
        tid = str(t.get("id") or "") if isinstance(t, dict) else ""
        if tid not in known or tid in seen or tid in gone:
            continue
        seen.add(tid)
        out.append(merge(t, edits[tid]) if tid in edits else t)
    seqs = dict(eng.CONFIG.get("seq") or {})
    n = _next_seq()
    created = []
    for raw in new:
        n += 1
        created.append(f"pt{n}")
        out.append({"id": created[-1], **clean(raw)})
    if created:
        seqs[SEQ] = n
    if len(out) > TPL_MAX:
        raise ValueError("rows")
    names = [str(t.get("name") or "").casefold() for t in out]
    if len(set(names)) != len(names):
        raise ValueError("dup")
    return out, seqs, created


def store(body: dict) -> tuple[str | None, list[str]]:
    """Записать правку шаблонов в профиль клиники: (текст ошибки записи или
    None, id созданных). Отказ разбора — ValueError, как у `apply`.

    Одна дверь на экран настроек и на «сохранить план как шаблон» фиши.
    Профиль собирается из копии нынешнего — прочие разделы переезжают как
    есть; счётчик id пишется, только когда шаблон создан."""
    templates, seqs, created = apply(body)
    cfg = dict(eng.CONFIG)
    cfg["plan_templates"] = templates
    if created:
        cfg["seq"] = seqs
    return eng.save_config(cfg), created


def rows_now(t: dict) -> list[dict]:
    """Строки шаблона на сегодня: услуга прайса — под нынешним именем прайса;
    услуга, убранная из прайса, — прежним текстом и без ключа."""
    out = []
    for r in t["rows"]:
        svc = eng.SERVICES.get(r["service_id"])
        out.append({**r, "procedure": svc["ro"] if svc else r["procedure"],
                    "service_id": r["service_id"] if svc else ""})
    return out


def catalog() -> list[dict]:
    """Шаблоны клиники для экрана правки и окна вставки, по порядку профиля."""
    return [{"id": t["id"], "name": t["name"], "note": t["note"], "rows": rows_now(t)}
            for t in eng.PLAN_TEMPLATES]
