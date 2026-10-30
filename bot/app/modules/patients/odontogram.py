# -*- coding: utf-8 -*-
"""Одонтограмма: номера и поверхности, правила моста, подпись зуба и модель
для React (C21, docs/dentpilot-2/clinical-chart.md).

Модуль без маршрутов: маршруты живут в `routes.py` и `api.py` и зовут отсюда.
Обратной ссылки нет и быть не может (routes → odontogram), иначе круг.

Вынесен 08-16, когда рисунок зуба понадобился двум экранам старой фиши
(карточке и странице «Detaliat»): копия подписи разошлась бы первой — «11 ·
Carie · MO» на одном экране и «11 Carie» на другом, ровно болезнь STATUS_LABEL.
С 13.10 старых экранов нет (снятие старого интерфейса, шаг 4), и вывод модуля
один — `model()`: геометрия зуба — `teeth_svg`, подпись — `tooth_title`, а
клиенту остаётся собрать вид и обслужить интерактив.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from ... import db
from ... import engine as eng
from ... import teeth_svg as tsvg
from .visit import NO_FORM_STATUSES

FDI_UPPER = [18, 17, 16, 15, 14, 13, 12, 11, 21, 22, 23, 24, 25, 26, 27, 28]
FDI_LOWER = [48, 47, 46, 45, 44, 43, 42, 41, 31, 32, 33, 34, 35, 36, 37, 38]
# молочный прикус: те же квадранты, что и постоянный, но по пять зубов
FDI_MILK_UPPER = [55, 54, 53, 52, 51, 61, 62, 63, 64, 65]
FDI_MILK_LOWER = [85, 84, 83, 82, 81, 71, 72, 73, 74, 75]
FDI_ALL = FDI_UPPER + FDI_LOWER + FDI_MILK_UPPER + FDI_MILK_LOWER

# поверхности зуба: буква → румынское название. Порядок как в записи «MOD»,
# принятой в карте: медиальная, окклюзионная, дистальная, потом щёчная и нёбная
TOOTH_SURFACES = {"M": "mezial", "O": "ocluzal", "D": "distal",
                  "V": "vestibular", "L": "lingual"}


def bridge_norm(teeth: list) -> list | None:
    """Зубы моста в порядке дуги; None — мостом этот набор быть не может.

    Правила от врача пилота (08-21): одна дуга (верхняя ИЛИ нижняя — между
    челюстями мостов не бывает; через среднюю линию — бывают, фронтальные);
    зубы стоят ПОДРЯД без дырок (промежуток моста — это зуб конструкции с
    ролью corp, а не пропуск в списке); молочных мостов нет; минимум два зуба
    и хотя бы одна опора (консольный мост = опора + тело).
    ⚠️ Порядок нормализуется ЗДЕСЬ, по раскладке дуги: форма может прислать
    зубы в порядке кликов, а хранение и печать читают мост слева направо."""
    got = tsvg.parse_bridge(teeth) if not isinstance(teeth, list) else teeth
    if len(got) < 2 or len({n for n, _r in got}) != len(got):
        return None
    for arch in (FDI_UPPER, FDI_LOWER):
        if all(n in arch for n, _r in got):
            ordered = sorted(got, key=lambda t: arch.index(t[0]))
            idx = [arch.index(n) for n, _r in ordered]
            if idx != list(range(idx[0], idx[0] + len(idx))):
                return None                      # дырка в ряду
            if not any(r == "stalp" for _n, r in ordered):
                return None                      # мост без единой опоры
            return ordered
    return None                                  # смесь дуг или молочные

# Имя состояния берётся из `teeth_svg.STATE_RO` — там же, откуда его берёт
# летопись `db.set_tooth`. Своего словаря здесь нет НАМЕРЕННО.
STATES = tsvg.STATE_RO
# Отметки — второй вопрос о зубе («что с ним делают»), см. teeth_svg.TOOTH_MARKS.
# Словарь тот же по той же причине: имя состояния уже расходилось дважды.
MARKS = tsvg.MARK_RO


# Подъём середины дуги в виде СВЕРХУ. Сверху челюсть — подкова, и ряд по
# линейке читается как таблица, а не как челюсть. В лицевом виде изгиба нет
# НАМЕРЕННО: там зубы стоят фронтально, и дуга ушла бы в декорацию, которая
# вдобавок разъезжается с цифрами.
ARC_PERM, ARC_MILK = 22.0, 15.0


def arc_offset(i: int, count: int, *, lower: bool, milk: bool = False) -> float:
    """Смещение зуба по вертикали, px. Середина уходит ОТ разделителя, края
    остаются на месте — так изгиб не съедает межчелюстной зазор и не упирает
    моляры в разделительную линию."""
    a = ARC_MILK if milk else ARC_PERM
    half = (count - 1) / 2
    k = (i - half) / half if half else 0.0
    return (a if lower else -a) * (1 - k * k)


def sf_text(sfmap: dict, sf: str) -> str:
    """Поверхности ОДНОЙ подписью: «Carie (M), Obturație (O)».

    ⚠️ Смесь состояний разворачивается словами: голое «MO» рядом с одним
    названием состояния было бы неправдой — так же, как в бланке 043/e и в
    выгрузке по 195-му. Однородный зуб даёт прежние буквы и прежнюю подпись.
    ⭐ Одно место на ВСЕ подписи зуба (title кнопки и плавающая подсказка):
    два текста об одном разошлись бы, и это ровно болезнь STATUS_LABEL —
    подсказка уже говорила «Carie · MO» там, где title говорил правду.
    """
    parts = tsvg.surface_summary(sfmap)
    return (", ".join(f"{STATES[k]} ({v})" for k, v in parts)
            if len(parts) > 1 else sf)


def _bmap(bridges: list) -> dict:
    """{fdi: (роль, материал)} — для подписи зуба. Разбор строкой из базы —
    ТОЛЬКО через tsvg.parse_bridge: второй разбор разошёлся бы с печатью."""
    out: dict = {}
    for b in bridges or ():
        for n, r in tsvg.parse_bridge(b["teeth"]):
            out[n] = (r, b.get("material") or "")
    return out


def tooth_info(tmap: dict, tooth_acts: list) -> tuple[dict, dict]:
    """(данные зубов, история по зубам) словарями — для модели JSON API (C21).

    ⚠️ `jaw` и `mez` считает СЕРВЕР (`tsvg.is_upper`, `tsvg.mesial_right`).
    Правило «квадранты 1/4/5/8 лежат слева, значит их середина справа» обязано
    жить в одном месте: повтори его в JS — и подписи M/D у инспектора начнут
    расходиться с полями, залитыми на самом зубе, причём только у половины
    челюсти.
    """
    return {str(n): _info(n, tmap) for n in FDI_ALL}, _history(tooth_acts)


def _history(tooth_acts: list) -> dict:
    hist: dict[str, list] = {}
    for a in tooth_acts:
        at = a["at"].astimezone(eng.TZ) if hasattr(a["at"], "astimezone") else None
        hist.setdefault(str(a["tooth"]), []).append(
            {"at": at.strftime("%d.%m.%Y") if at else "", "text": a["text"]})
    return hist


def _info(n: int, tmap: dict) -> dict:
    """Данные зуба n (без рисунков) — см. `tooth_info`."""
    t = tmap.get(n)
    base = {"jaw": "sus" if tsvg.is_upper(n) else "jos",
            "mez": "right" if tsvg.mesial_right(n) else "left"}
    if not t:
        return {**base, "state": "ok", "note": "", "doctor": "", "at": "",
                "sf": "", "sfx": "", "sfst": {}, "mk": [], "mkx": ""}
    # состояние, карта, отметки, врач, заметка — та же выжимка строки, что
    # сверяет запись пачкой (`db.set_teeth`): «зуб не менялся» = «тот же вид»
    f = tsvg.tooth_fields(t)
    sfmap, mk = f["sfst"], f["mk"]
    return {**base, "state": f["state"], "note": f["note"],
            "doctor": f["doctor"], "sf": t["surfaces"] or "",
            "sfst": sfmap, "mk": mk,
            # готовая подпись отметок — по той же причине, что и `sfx`:
            # слова живут в MARK_RO, второй копии в JS быть не должно
            "mkx": ", ".join(MARKS[m] for m in mk),
            # ⚠️ Готовая подпись, а не голые буквы: плавающая подсказка
            # печатает её как есть. Собирает её СЕРВЕР (`sf_text`) — порядок
            # тяжести и слова живут в одном месте, второй копии в JS нет
            "sfx": sf_text(sfmap, t["surfaces"] or ""),
            "at": t["updated_at"].astimezone(eng.TZ).strftime("%d.%m.%Y")
                  if t["updated_at"] else ""}


# Анатомическое название по позиции в квадранте (последняя цифра FDI) и
# сторона пациента по квадранту — подпись панели зуба (08.10, макет «Stare
# dinți»). ⛔ Слово клиническое, значит живёт здесь, а не в браузере: второго
# словаря зубов у клиента нет (clinical-chart.md). Молочный ряд — пять позиций.
TOOTH_NAMES = ("Incisiv central", "Incisiv lateral", "Canin", "Premolar I",
               "Premolar II", "Molar I", "Molar II", "Molar III")
MILK_NAMES = ("Incisiv central", "Incisiv lateral", "Canin", "Molar I", "Molar II")


def tooth_name(n: int) -> str:
    q, p = divmod(n, 10)
    names = MILK_NAMES if q >= 5 else TOOTH_NAMES
    return names[p - 1] if 1 <= p <= len(names) else ""


def tooth_side(n: int) -> str:
    """«dreapta»/«stânga» — сторона ПАЦИЕНТА: квадранты 1, 4 (и молочные 5, 8)
    справа, 2, 3 (6, 7) слева."""
    return "dreapta" if n // 10 in (1, 4, 5, 8) else "stânga"


def tooth_title(n: int, tmap: dict, bmap: dict | None = None) -> str:
    """Подпись зуба словами: номер, состояние, отметки, мост с ролью и
    материалом, заметка, поверхности. Сырой текст для модели JSON API;
    экранирует тот, кто рисует."""
    t = tmap.get(n)
    st = t["state"] if t else "ok"
    note = t["note"] if t else ""
    sf = (t["surfaces"] if t else "") or ""
    sfmap = tsvg.surface_map(st, sf, (t["surface_states"] if t else "") or "")
    mk = tsvg.mark_list((t["marks"] if t else "") or "")
    # поверхности дописываются ПОСЛЕ заметки: подпись «11 · Carie · test»
    # читают и человек, и проверка, и её формат менять незачем.
    sf_txt = sf_text(sfmap, sf)
    # мост — в подписи зуба наравне с отметкой: скобка говорит «здесь мост»,
    # а title отвечает, КЕМ этот зуб в нём стоит (опора или тело)
    br = (bmap or {}).get(n)
    br_txt = (f" · Punte: {tsvg.BRIDGE_RO[br[0]]}"
              + (f" ({br[1]})" if br[1] else "") if br else "")
    return (f"{n} · {STATES.get(st, st)}"
            + "".join(f" · {MARKS[m]}" for m in mk)
            + br_txt
            + (f" · {note}" if note else "")
            + (f" · {sf_txt}" if sf_txt else ""))


# Материалы моста — пресеты диалога; «alt» = свободный текст.
BRIDGE_MATERIALS = (("metalo-ceramică", "Metalo-ceramică"), ("zirconiu", "Zirconiu"),
                    ("ceramică", "Ceramică"), ("metal", "Metal"),
                    ("acrilat", "Acrilat"), ("alt", "Alt material…"))


def legend_items(occ: bool) -> list[dict]:
    """Легенда данными: НАСТОЯЩИЙ зуб в каждом состоянии, а не цветной
    квадрат — так видно, чем «коронка» отличается от «пломбы», без словаря.

    ⚠️ Отметки идут тем же рядом, но на ЗДОРОВОМ зубе: иначе «în tratament»
    выглядело бы восьмым состоянием — ровно тем недоразумением, из-за
    которого кариес и лечение вытесняли друг друга (08-17)."""
    draw = ((lambda k, m=(): tsvg.occlusal_svg(36, k, width=26, marks=m)) if occ
            else (lambda k, m=(): tsvg.tooth_svg(36, k, width=20, marks=m)))
    return ([{"kind": "state", "key": k, "label": v, "svg": draw(k)}
             for k, v in STATES.items() if k != "ok"]
            + [{"kind": "mark", "key": k, "label": v, "svg": draw("ok", (k,))}
               for k, v in MARKS.items()])


# Режимы рабочего стола (Олег 24.10, макет B: вкладки шапки на месте «Stare
# dinți | Parodont»). Режим — ФИЛЬТР ЭКРАНА по уже записанным данным: гасит зубы
# не про него (тот же `setDim` и класс `dim`, что у легенды-фильтра) и ставит
# его пункты первыми в меню зуба. ⛔ Выбор режима живёт в экране: ни в запись
# зуба, ни в 043/e, ни в печать он не попадает — здесь только словарь.
# ⭐ Словарь ОДИН и здесь, ключи — те же, что у легенды (`STATE_RO`, `MARK_RO`):
# второго словаря состояний у клиента нет. Новое состояние или отметка без
# режима выпали бы из фильтра молча, поэтому `test_teeth` требует, чтобы каждое
# (кроме «ok») стояло хотя бы в одном режиме «keys» и чтобы режим называл только
# существующие ключи.
# kind: «all» — всё видно, ничего не гасится (Examinare); «keys» — зубы с этими
# состояниями (целиком или на поверхности) или отметками, при `bridges` ещё и
# зубы мостов; «perio» — слой последнего осмотра на десне, находки приглушены,
# зубы не гасятся (Parodonțiu = прежний режим «Parodont»).
# Ortodonție нет: данных ортодонтии программа не записывает (Олег 24.10).
# «În tratament» — в Endodonție: лечение в несколько визитов чаще всего каналы.
MODES = (
    {"key": "examinare", "label": "Examinare", "kind": "all", "keys": (), "bridges": False},
    {"key": "carii", "label": "Carii", "kind": "keys", "keys": ("carie",), "bridges": False},
    {"key": "restaurare", "label": "Restaurare", "kind": "keys", "keys": ("obturatie", "coroana"),
     "bridges": False},
    {"key": "endo", "label": "Endodonție", "kind": "keys", "keys": ("devital", "tratament"),
     "bridges": False},
    {"key": "paro", "label": "Parodonțiu", "kind": "perio", "keys": (), "bridges": False},
    {"key": "chirurgie", "label": "Chirurgie", "kind": "keys", "keys": ("extras", "lipsa"),
     "bridges": False},
    {"key": "implant", "label": "Implant", "kind": "keys", "keys": ("implant", "implant_fc"), "bridges": False},
    {"key": "proteza", "label": "Proteză", "kind": "keys", "keys": ("coroana",), "bridges": True},
)


def modes() -> list[dict]:
    """Словарь режимов для модели экрана — копия, список ключей списком (JSON)."""
    return [{**m, "keys": list(m["keys"])} for m in MODES]


# Позиции плана ЗУБА — вкладка «Tratament» панели зуба (24.10, макет B).
# Строка та же, что у плана фиши (`api._plan_item`: подпись статуса
# `card.PLAN_LABEL`, срок и просрочка, врач по правилу 043/e), здесь только
# раскладка по номеру. ⛔ Только ЧТЕНИЕ: переходы плана живут во вкладке фиши,
# поэтому `next`/`refusable`/`deletable` сюда не едут. Активная — ПЕРЕЧИСЛЕНИЕМ
# (`db.PLAN_ACTIVE`): правило «всё, кроме finalizat» с появлением отказа
# соврало шестью местами (08-11), и клиент своего правила не заводит.
PLAN_FIELDS = ("id", "procedure", "status", "label", "doctor", "price",
               "due", "overdue", "done", "motiv")


def tooth_plan(items: list) -> dict:
    """{fdi: [позиция, …]} в порядке плана фиши (`card.plan_key`: в работе,
    запланированное по сроку, законченное, отказы). Позиция без зуба (план
    «на весь рот») и с чужим номером в зуб не попадает."""
    out: dict[str, list] = {}
    for it in items:
        n = it.get("tooth")
        if n not in FDI_ALL:
            continue
        row = {k: it.get(k) for k in PLAN_FIELDS}
        row["active"] = it.get("status") in db.PLAN_ACTIVE
        out.setdefault(str(n), []).append(row)
    return out


def tooth_entry(n: int, tmap: dict, bmap: dict) -> dict:
    """Зуб модели экрана целиком: данные (`_info`), подписи, мост, размеры 3D
    и оба рисунка с целями поверхностей. Один построитель на модель и на
    предпросмотр черновика (`preview`)."""
    t = tmap.get(n)
    st = t["state"] if t else "ok"
    f = tsvg.tooth_fields(t)
    milk = n in FDI_MILK_UPPER or n in FDI_MILK_LOWER
    br = bmap.get(n)
    return {
        **_info(n, tmap), "milk": milk, "title": tooth_title(n, tmap, bmap),
        # подпись панели зуба (08.10): название и сторона — словами сервера
        "name": tooth_name(n), "side": tooth_side(n),
        "bridge": {"role": br[0], "material": br[1]} if br else None,
        # размеры для объёмного вида (B7): сервер владеет ими, клиент рендерит
        "geom": tsvg.tooth_geom(n),
        "svg": {
            "frontal": tsvg.tooth_svg(n, st, width=28 if milk else 38, interactive=True,
                                      surfaces=f["sfst"], marks=f["mk"], hit=True),
            "occlusal": tsvg.occlusal_svg(n, st, width=38 if milk else 52, interactive=True,
                                          surfaces=f["sfst"], marks=f["mk"], hit=True),
        },
    }


def preview(tmap: dict, bridges: list | None, teeth: list[int]) -> dict:
    """Зубы `teeth` по карте, которую ВЕРНУЛ БЫ запись черновика
    (`db.preview_teeth`, волна 2 одонтограммы, 25.10): экран рисует черновик
    в 3D и 2D до записи, и рисунок обязан быть тем же, что после неё, —
    поэтому строит его тот же `tooth_entry`, что и модель."""
    bmap = _bmap(bridges or [])
    return {str(n): tooth_entry(n, tmap, bmap) for n in teeth}


def model(tmap: dict, tooth_acts: list, bridges: list | None,
          plan: list | None = None) -> dict:
    """Одонтограмма данными для React (C21, docs/dentpilot-2/clinical-chart.md):
    зубы с рисунками обоих видов (с целями поверхностей `hit=True`), история,
    позиции плана по зубам, дуги и подъём вида сверху, мосты, легенда и
    словари. Всё считает сервер — у клиента нет ни геометрии, ни второго
    словаря состояний. `plan` — строки плана фиши (`api._plan_item`)."""
    hist = _history(tooth_acts)
    bmap = _bmap(bridges or [])
    teeth = {str(n): tooth_entry(n, tmap, bmap) for n in FDI_ALL}

    def arcs(row: list, *, lower: bool, milk: bool) -> list[int]:
        return [int(f"{arc_offset(i, len(row), lower=lower, milk=milk):.0f}")
                for i in range(len(row))]

    return {
        "teeth": teeth, "history": hist,
        # план ЗУБА — вкладка «Tratament» панели (24.10); у зуба без позиций ключа нет
        "plan": tooth_plan(plan or []),
        "arches": {"upper": list(FDI_UPPER), "lower": list(FDI_LOWER),
                   "milk_upper": list(FDI_MILK_UPPER), "milk_lower": list(FDI_MILK_LOWER)},
        "arc": {"upper": arcs(FDI_UPPER, lower=False, milk=False),
                "lower": arcs(FDI_LOWER, lower=True, milk=False),
                "milk_upper": arcs(FDI_MILK_UPPER, lower=False, milk=True),
                "milk_lower": arcs(FDI_MILK_LOWER, lower=True, milk=True)},
        # молочный прикус раскрывается сам, если по нему уже есть записи:
        # детская фиша не должна требовать лишнего клика, взрослая — видеть
        # лишний ряд
        "milk_open": any(n in tmap for n in FDI_MILK_UPPER + FDI_MILK_LOWER),
        "bridges": bridge_rows(bridges),
        "legend": {"frontal": legend_items(False), "occlusal": legend_items(True)},
        "states": dict(STATES), "marks": dict(MARKS),
        # состояния, сказанные про ВЕСЬ зуб (прототип кисти, 11.10): `carie` и
        # `obturatie` вводятся только по поверхностям; список — здесь, чтобы у
        # клиента не завёлся второй словарь состояний
        "tooth_states": {k: v for k, v in STATES.items() if k not in tsvg.SURFACE_STATES},
        # цвета состояний И отметок — те же, что у 2D и легенды; 3D красит
        # ими же (кольца отметок — цветом ореола и каналов, не своей копией)
        "palette": {**tsvg.COLORS, **tsvg.MARK_COLORS},
        "surfaces": dict(TOOTH_SURFACES), "surface_states": list(tsvg.SURFACE_STATES),
        "bridge_roles": dict(tsvg.BRIDGE_RO),
        "materials": [{"id": k, "label": v} for k, v in BRIDGE_MATERIALS],
        # режимы рабочего стола — статический словарь; выбор режима — экрана
        "modes": modes(),
    }



def bridge_rows(bridges: list | None) -> list[dict]:
    """Мосты для модели экрана: роли по зубам, материал, врач. Один вид на
    модель и на карту «на визит» (`compare`) — сцена рисует их одинаково."""
    rows = []
    for b in bridges or ():
        t = tsvg.parse_bridge(b["teeth"])
        if t:
            rows.append({"id": b["id"], "teeth": t, "material": b.get("material") or "",
                         "doctor": b.get("doctor") or ""})
    return rows


# ---------- сравнить с визитом (волна 2 одонтограммы, 25.10) ----------
# Врач выбирает прошлый визит и видит, какие зубы с тех пор изменились: было →
# стало, в 2D и 3D. Карту «на визит» строит СЕРВЕР из `teeth_history` тем же
# `tooth_entry`, что модель, — второго рисовальщика нет. Слой — свойство
# экрана: ни в запись, ни в 043/e, ни в печать. История копится с шага 6
# миграции (`db.teeth_hist_since`); визит раньше — «нет данных», а не
# догадка по словам летописи.

COMPARE_VISITS_MAX = 50


def visit_cutoff(starts_at: datetime) -> datetime:
    """Мгновение «на визит»: конец ДНЯ визита по часам клиники. Не конец
    приёма: врач заносит зубы и после пациента, и записанное в тот же день —
    работа этого визита, а не «изменилось после»."""
    day = starts_at.astimezone(eng.TZ).date() + timedelta(days=1)
    return datetime.combine(day, time(0), tzinfo=eng.TZ)


def compare_visits(visits: list, today: date, since: datetime | None) -> list[dict]:
    """Визиты для выбора: прошлые ДНИ (сегодняшний — та же карта, что
    сейчас), без отменённых и неявок — то же правило «визит состоялся», что у
    консультации (`visit.NO_FORM_STATUSES`) и у дня врача. `visits` — свежие
    первыми (`db.patient_appointments`). `known` — есть ли на тот день история
    (`since` — её начало, None — её нет)."""
    out: list[dict] = []
    for v in visits:
        if v["status"] in NO_FORM_STATUSES:
            continue
        local = v["starts_at"].astimezone(eng.TZ)
        if local.date() >= today:
            continue
        out.append({"id": v["id"], "date": local.strftime("%d.%m.%Y"),
                    "label": f"{local:%d.%m.%Y} · {v['service']} · {v['doctor']}",
                    "known": since is not None and visit_cutoff(v["starts_at"]) >= since})
        if len(out) >= COMPARE_VISITS_MAX:
            break
    return out


def records_after(rows: list) -> list[dict]:
    """Строки летописи после визита (`db.tooth_records_since`) для экрана:
    {n — номер зуба или None у моста, at — дата клиники, text — ДОСЛОВНО}.
    ⛔ Это факт ЗАПИСИ, не состояние зуба на ту дату: строку не разбираем и
    картинку «было» из неё не строим (обрезка 200 знаков, « · » общий у
    отметок, врача и заметки, слова менялись между версиями)."""
    out = []
    for r in rows:
        at = r["at"].astimezone(eng.TZ).strftime("%d.%m.%Y") if hasattr(r["at"], "astimezone") else ""
        out.append({"n": r["tooth"], "at": at, "text": r["text"]})
    return out


def _clinic_key(n: int, tmap: dict, bmap: dict) -> tuple:
    """Что считается ИЗМЕНЕНИЕМ зуба: состояние, карта поверхностей, отметки,
    роль в мосте. Заметка и врач — нет: это подпись записи, а не зуб."""
    f = tsvg.tooth_fields(tmap.get(n))
    return (f["state"], tuple(sorted((k, v) for k, v in f["sfst"].items() if v)),
            tuple(sorted(f["mk"])), bmap.get(n))


def tooth_words(n: int, tmap: dict, bmap: dict) -> str:
    """Зуб словами для строки «было → стало»: «Carie (M), Obturație (OD) · În
    tratament · Punte: Stâlp». Слова — те же словари, что у подписи зуба и
    летописи (`STATES`, `MARKS`, `sf_text`, `BRIDGE_RO`)."""
    t = tmap.get(n)
    f = tsvg.tooth_fields(t)
    sf = sf_text(f["sfst"], (t["surfaces"] or "") if t else "")
    txt = (sf if len(tsvg.surface_summary(f["sfst"])) > 1
           else STATES.get(f["state"], f["state"]) + (f" ({sf})" if sf else ""))
    txt += "".join(f" · {MARKS[m]}" for m in f["mk"])
    br = bmap.get(n)
    if br:
        txt += f" · Punte: {tsvg.BRIDGE_RO[br[0]]}"
    return txt


def compare(now_tmap: dict, now_bridges: list | None,
            was_tmap: dict, was_bridges: list | None) -> dict:
    """Разница карты «на визит» с нынешней: `changes` — изменившиеся зубы в
    порядке экрана со словами было → стало; `teeth` — эти зубы такими, какими
    были (тот же `tooth_entry`, что у модели: экран кладёт их поверх
    сохранённой модели, как предпросмотр черновика); `bridges` — мосты на ту
    дату (вид `model.bridges`); `milk_open` — молочный ряд нужен хоть одной
    из двух карт."""
    bnow, bwas = _bmap(now_bridges or []), _bmap(was_bridges or [])
    changes, teeth = [], {}
    for n in FDI_ALL:
        if _clinic_key(n, was_tmap, bwas) == _clinic_key(n, now_tmap, bnow):
            continue
        changes.append({"n": n, "was": tooth_words(n, was_tmap, bwas),
                        "now": tooth_words(n, now_tmap, bnow)})
        teeth[str(n)] = tooth_entry(n, was_tmap, bwas)
    milk = FDI_MILK_UPPER + FDI_MILK_LOWER
    return {"changes": changes, "teeth": teeth, "bridges": bridge_rows(was_bridges),
            "milk_open": any(n in was_tmap or n in now_tmap for n in milk)}
