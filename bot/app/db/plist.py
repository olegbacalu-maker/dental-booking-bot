"""Список «Pacienți» (`/api/patients`, книга patients.xlsx) — одной выборкой."""
from __future__ import annotations

from datetime import datetime

from .conn import _fetch, _fetchval, _iso
from .slots import _ACT_SQL


_PLIST_COLS = ("id, name, phone, email, session_key, birth_year, birth_date, "
               "gender, insurance, primary_doctor, file_no, notes, created_at, "
               "archived")


async def all_patients() -> list:
    """Живые (не архивные) пациенты клиники строками — для рабочих списков
    стойки на главной (`schedule/desk`), которые сводят их с `patients_visits`
    и `patients_debt` сами. Список «Pacienți» отбирает в SQL (`patients_rows`)."""
    return await _fetch(
        f"""SELECT {_PLIST_COLS} FROM patients
            WHERE COALESCE(archived, 0) = 0 ORDER BY id""")


async def patients_visits(now: datetime) -> list:
    """По пациенту: последний прошедший визит, ближайший будущий и сколько
    всего (отменённые не в счёт). Один проход по таблице вместо запроса на
    каждую строку списка — иначе страница пациентов стоила бы сотню запросов.
    Заметки-блокировки сюда не попадают: у них patient_id = NULL."""
    return await _fetch(
        f"""SELECT patient_id,
                   MAX(CASE WHEN starts_at <= ? THEN starts_at END) AS last_at,
                   MIN(CASE WHEN starts_at > ? AND status IN {_ACT_SQL}
                            THEN starts_at END) AS next_at,
                   COUNT(*) AS n_visits
              FROM appointments
             WHERE patient_id IS NOT NULL AND status <> 'cancelled'
             GROUP BY patient_id""",
        _iso(now), _iso(now),
    )


async def patients_debt() -> dict:
    """Долг каждого пациента: финализированный план − оплачено. Минус = аванс.

    Та же формула, что в `patient_finance`, но на всю картотеку двумя запросами
    вместо двух НА ПАЦИЕНТА (рабочие списки стойки зовут это раз на главную).
    Полного внешнего соединения в SQLite нет, поэтому две выборки сводятся в
    Python — заодно не приходится писать двум диалектам разный SQL.
    """
    chg = ("SELECT patient_id, COALESCE(SUM(price_mdl), 0) AS n FROM plan_items "
           "WHERE status = 'finalizat' GROUP BY patient_id")
    pay = ("SELECT patient_id, COALESCE(SUM(amount_mdl), 0) AS n FROM payments "
           "GROUP BY patient_id")
    out: dict[int, int] = {}
    for r in await _fetch(chg):
        out[r["patient_id"]] = int(r["n"] or 0)
    for r in await _fetch(pay):
        out[r["patient_id"]] = out.get(r["patient_id"], 0) - int(r["n"] or 0)
    return out


# врач последнего визита (включая будущий): подзапрос по индексу patient_id,
# а не оконная функция по всей таблице — на 20 000 записей она стоила ~50 мс
# на КАЖДЫЙ запрос списка, а нужна двадцати строкам страницы (и всем — только
# под фильтром по врачу)
_PL_LAST_DOC_OF = ("(SELECT a.doctor FROM appointments a WHERE a.patient_id = p.id "
                   "AND a.status <> 'cancelled' ORDER BY a.starts_at DESC LIMIT 1)")
# врач строки: медик курант из фиши, а если его не проставили — тот, кто вёл
# последний визит (так его показывают экран и книга Excel): `primary_doctor`
# проставляют руками, и без запасного колонка «Medic» пустовала бы почти у
# всех, хотя врач у пациента фактически есть — тот, к кому он ходит
_PL_DOCTOR = f"COALESCE(NULLIF(p.primary_doctor, ''), {_PL_LAST_DOC_OF}, '')"
# долг = финализированный план − оплачено; минус — аванс (как `patients_debt`)
_PL_DEBT = "(COALESCE(chg.n, 0) - COALESCE(pay.n, 0))"
# канал по префиксу ключа — как `_pl_canal`; substr, а не LIKE: у LIKE в SQLite
# регистр не в счёт, а ключи сравниваются буква в букву
_PL_CANAL = ("CASE WHEN substr(p.session_key, 1, 3) = 'tg:' THEN 'tg' "
             "WHEN substr(p.session_key, 1, 7) = 'manual:' THEN 'manual' "
             "ELSE 'web' END")
# pl — «в лечении»: активные статусы ПОИМЁННО (те же, что PLAN_ACTIVE), а не
# «<> finalizat»: отказанная позиция закрыта, и пациент с одним отказом не
# находится в лечении
_PL_FROM = f"""
      FROM patients p
      LEFT JOIN (SELECT patient_id,
                        MAX(CASE WHEN starts_at <= {{now1}} THEN starts_at END) AS last_at,
                        MIN(CASE WHEN starts_at > {{now2}} AND status IN {_ACT_SQL}
                                 THEN starts_at END) AS next_at,
                        COUNT(*) AS n_visits
                   FROM appointments
                  WHERE patient_id IS NOT NULL AND status <> 'cancelled'
                  GROUP BY patient_id) v ON v.patient_id = p.id
      LEFT JOIN (SELECT patient_id, COUNT(*) AS n FROM patient_alerts
                  GROUP BY patient_id) al ON al.patient_id = p.id
      LEFT JOIN (SELECT patient_id, COUNT(*) AS n FROM plan_items
                  WHERE status IN ('planificat', 'in_lucru')
                  GROUP BY patient_id) pl ON pl.patient_id = p.id
      LEFT JOIN (SELECT patient_id, COALESCE(SUM(price_mdl), 0) AS n FROM plan_items
                  WHERE status = 'finalizat' GROUP BY patient_id) chg ON chg.patient_id = p.id
      LEFT JOIN (SELECT patient_id, COALESCE(SUM(amount_mdl), 0) AS n FROM payments
                  GROUP BY patient_id) pay ON pay.patient_id = p.id"""
_PL_COLS = ("p.id, p.name, p.phone, p.email, p.session_key, p.birth_year, p.birth_date, "
            "p.gender, p.primary_doctor, p.file_no, p.notes, p.created_at, p.archived, "
            "v.last_at, v.next_at, COALESCE(v.n_visits, 0) AS n_visits, "
            "COALESCE(al.n, 0) AS n_alerts, COALESCE(pl.n, 0) AS n_plan, "
            f"{_PL_LAST_DOC_OF} AS last_doctor, {_PL_DEBT} AS debt, "
            # счёт всего отбора той же выборкой: второй проход по агрегатам
            # ради COUNT(*) стоил столько же, сколько сама страница
            "COUNT(*) OVER () AS total")
_PL_ORDER = {
    "name": "{fold_name}, p.id",
    "new": "p.created_at DESC, p.id",
    "debt": _PL_DEBT + " DESC, p.id",
    # по последнему визиту; кто ещё не был — в конце, в порядке заведения
    "last": "(v.last_at IS NULL), v.last_at DESC, p.id",
}


# Как пишутся куски отбора: архив (0/1), свёртка диакритики и «только цифры»
# (функции dp_fold/dp_digits, регистрирует init), «содержит», заполнитель и
# вид даты.
_PL_DIALECT = {"arch": "COALESCE(p.archived, 0) <> 0",
               "fold": lambda col: f"dp_fold({col})",
               "digits": lambda col: f"dp_digits({col})",
               "has": lambda hay, needle: f"instr({hay}, {needle}) > 0",
               "ph": lambda n: "?", "dt": _iso}


class _PlQuery:
    """Текст запроса списка и его аргументы по порядку.

    `f` — отбор словарём (см. `patients_count`): q/terms, med, st, ch, dat,
    show_archived, stale_cut, now. Каждое значение добавляется ровно там, где
    стоит его заполнитель в тексте.
    """

    def __init__(self, f: dict):
        self.d = _PL_DIALECT
        self.args: list = []
        d = self.d
        self.base = _PL_FROM.format(now1=self.arg(f["now"], dt=True),
                                    now2=self.arg(f["now"], dt=True))
        conds = []
        if not f.get("show_archived"):
            conds.append(f"NOT ({d['arch']})")
        if f.get("q"):
            t = f.get("terms") or {}
            alts = []
            if t.get("fold"):
                for col in ("p.name", "p.email", "p.file_no"):
                    alts.append(d["has"](d["fold"](col), self.arg(t["fold"])))
            if t.get("birth"):
                alts.append(f"substr(COALESCE(p.birth_date, ''), 1, 10) = "
                            f"{self.arg(t['birth'])}")
            if t.get("digits"):
                # notes — номер второго человека на семейном телефоне (решение
                # 08-18). ⚠️ РАЗДЕЛЬНО от телефона, не общей строкой: на стыке
                # «конец телефона + начало заметки» находились бы номера,
                # которых нет
                for col in ("p.phone", "p.notes"):
                    alts.append(d["has"](d["digits"](col), self.arg(t["digits"])))
            # запрос без единого пригодного куска (одна буква) не находит
            # никого
            conds.append("(" + " OR ".join(alts) + ")" if alts else "1 = 0")
        med = f.get("med") or ""
        if med == "-":
            conds.append(f"{_PL_DOCTOR} = ''")
        elif med:
            conds.append(f"{_PL_DOCTOR} = {self.arg(med)}")
        st = f.get("st") or ""
        if st == "arhivat":
            conds.append(d["arch"])
        elif st == "atentie":
            conds.append("COALESCE(al.n, 0) > 0")
        elif st == "tratament":
            conds.append("COALESCE(pl.n, 0) > 0")
        elif st == "inactiv":
            conds.append(f"(v.last_at IS NULL OR v.last_at <= "
                         f"{self.arg(f['stale_cut'], dt=True)})")
        elif st == "activ":
            conds.append(f"(v.last_at IS NOT NULL AND v.last_at > "
                         f"{self.arg(f['stale_cut'], dt=True)})")
        if f.get("ch"):
            conds.append(f"{_PL_CANAL} = {self.arg(f['ch'])}")
        if f.get("imp"):
            conds.append(f"p.import_id = {self.arg(int(f['imp']))}")
        # ноль — ни в долг, ни в аванс: рассчитавшийся пациент не должен
        # всплывать в списке, который регистратура открывает, чтобы звонить
        if f.get("dat") == "da":
            conds.append(f"{_PL_DEBT} > 0")
        elif f.get("dat") == "avans":
            conds.append(f"{_PL_DEBT} < 0")
        if conds:
            self.base += "\n     WHERE " + "\n       AND ".join(conds)

    def arg(self, value, *, dt: bool = False) -> str:
        self.args.append(self.d["dt"](value) if dt else value)
        return self.d["ph"](len(self.args))

    def page_sql(self, sort: str, limit: int | None, offset: int) -> str:
        order = _PL_ORDER.get(sort, _PL_ORDER["last"]).format(
            fold_name=self.d["fold"]("p.name"))
        sql = f"SELECT {_PL_COLS}{self.base}\n     ORDER BY {order}"
        if limit is None:          # книга Excel: вся выборка, а не страница
            return sql
        return sql + f"\n     LIMIT {self.arg(limit)} OFFSET {self.arg(offset)}"


async def patients_count(f: dict) -> int:
    """Сколько строк проходит отбор `f` — знаменатель страниц.

    Отбор: `q` с разобранными кусками `terms` (fold / birth / digits — что
    именно ищется, решает модуль, `_pl_terms`), `med` (имя врача или «-» =
    без врача), `st` (arhivat / atentie / tratament / inactiv / activ,
    включающий), `ch` (tg / manual / web), `dat` (da / avans),
    `show_archived`, `stale_cut` (последний визит не позже — неактивен),
    `now` (граница прошлого и будущего визита).
    """
    q = _PlQuery(f)
    n = await _fetchval(f"SELECT COUNT(*){q.base}", *q.args)
    return int(n or 0)


async def patients_rows(f: dict, sort: str, limit: int | None, offset: int) -> list:
    """Страница списка: строки с агрегатами (`last_at`, `next_at`, `n_visits`,
    `n_alerts`, `n_plan`, `last_doctor`, `debt`) в порядке `sort`
    (last / name / new / debt) и с `total` — счётом всего отбора в каждой
    строке (окно). Пустая страница счёта не несёт: тогда `patients_count`.
    `limit=None` — вся выборка (книга Excel). Статус строки выводит модуль
    (`_pl_status`)."""
    q = _PlQuery(f)
    sql = q.page_sql(sort, limit, offset)
    return await _fetch(sql, *q.args)


async def patients_doctors() -> list[str]:
    """Врачи, по которым список можно отобрать: тот же вывод, что у колонки
    «Medic» (медик курант, иначе врач последнего визита)."""
    sql = f"SELECT DISTINCT {_PL_DOCTOR} AS doctor FROM patients p"
    return sorted(r["doctor"] for r in await _fetch(sql) if r["doctor"])


async def patients_archived() -> int:
    """Сколько фиш в архиве — для подсказки «N arhivați» под списком."""
    return int(await _fetchval(
        "SELECT COUNT(*) FROM patients WHERE COALESCE(archived, 0) <> 0") or 0)


async def patients_have_tg() -> bool:
    """Есть ли пациенты из бота — фильтр канала «Telegram» идёт ПО ДАННЫМ."""
    sql = "SELECT COUNT(*) FROM patients WHERE substr(session_key, 1, 3) = 'tg:'"
    return bool(await _fetchval(sql))


async def patients_counts(month_start: datetime, prev_start: datetime) -> dict:
    """Числа над списком: живых, в архиве, новых за этот месяц и за прошлый.
    Новые считаются по всей картотеке, включая архив, — как на странице."""
    lt = """SELECT SUM(CASE WHEN COALESCE(archived, 0) <> 0 THEN 0 ELSE 1 END) AS n_total,
                   SUM(CASE WHEN COALESCE(archived, 0) <> 0 THEN 1 ELSE 0 END) AS n_arh,
                   SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END) AS n_new,
                   SUM(CASE WHEN created_at >= ? AND created_at < ?
                            THEN 1 ELSE 0 END) AS n_new_prev
              FROM patients"""
    rows = await _fetch(lt, _iso(month_start), _iso(prev_start), _iso(month_start))
    r = rows[0] if rows else {}
    return {k: int(r.get(k) or 0) for k in ("n_total", "n_arh", "n_new", "n_new_prev")}
