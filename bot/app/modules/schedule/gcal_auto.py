"""Вкладка «Google Calendar»: перенос событий в журнал пачкой и автоматом.

Правило «переносится ли событие без человека» — `_static` и `plan`: дата и час, один узнанный врач,
пациент, выбранный без человека, свободное время. Перенос идёт тем же швом, что окно записи
(`gcal._journal_add`), под тем же замком (`gcal.move_lock`): второй копии правил записи нет.
Пачка — у всех тарифов (вкладка и файл); автоперенос — проход после опроса аккаунта Google, только
при праве `gcal` и не в режиме чтения. Запись, изменённая или отменённая в Google, сама не меняется:
решает человек кнопкой строки."""
from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import asdict, dataclass
from datetime import date as _date, datetime, timedelta

from ... import db
from ... import engine as eng
from ...core import book, gimport, sms_loop
from ...core import license as lic
from ...core import license_state as lst
from ...core.auth import request_user, set_request_user
from ...core.layout import msg_text
from . import gcal
from . import routes as sroutes

HOW_BATCH, HOW_AUTO = "batch", "auto"
# Подпись автопереноса в летописи: без неё фоновая запись подписалась бы «recepție».
SYSTEM = {"id": "sistem", "role": "", "name": "sistem", "doctor_id": ""}
META_MOVES = "gcal_moves"
META_SMS = "gcal_sms"
MOVES_MAX = 30
OK_PROBE = frozenset({"ok", "room_busy"})

# Почему событие не переносится само; слова печатает экран как есть.
REASONS = {
    "a_hand": "lăsat de dvs. pentru mutare manuală",
    "a_time": "fără dată sau oră",
    "a_doctor": "medicul nu se recunoaște în titlu",
    "a_doctors": "în eveniment sunt mai mulți medici",
    "a_doctor_off": "medicul nu mai lucrează în clinică",
    "a_family": "telefonul este al mai multor fișe",
    "a_other": "telefonul este al fișei {name}",
    "a_name": "numele pacientului nu e clar",
    "a_name_phone": "numele este al unei fișe cu alt telefon",
    "a_nobody": "fără telefon, iar numele nu este al unei singure fișe",
    "a_exists": "există deja în jurnal, la alt medic",
    "a_service": "nu este nicio procedură în agendă",
    "conflict": "ora este ocupată",
    "dup": "pacientul are deja o programare la această oră",
    "outside": "în afara programului clinicii",
    "outside_doc": "în afara programului medicului",
    "bad_off": "medicul nu mai lucrează în clinică",
    "bad_time": "ora nu este pe grila jurnalului",
    "bad_dur": "durata nu se poate pune în jurnal",
}


def reason(code: str, **kw) -> dict:
    text = REASONS.get(code) or msg_text(code) or code
    return {"code": code, "text": text.format(**kw) if kw else text}


@dataclass
class Pick:
    """Решение по одному событию: переносится (`ok`) — куда и кому; нет — почему."""
    eid: int
    stamp: str
    ok: bool = False
    why: str = ""
    text: str = ""
    doctor: str = ""
    pid: int | None = None
    fresh: bool = False
    who: str = ""
    name: str = ""
    phone: str = ""
    date: str = ""
    time: str = ""
    minutes: int = 0
    link: int | None = None

    def stay(self, code: str, text: str = "", **kw) -> "Pick":
        self.ok, self.why = False, code
        self.text = text or reason(code, **kw)["text"]
        return self


def _words(text: str) -> frozenset:
    return frozenset(gimport.fold(text).split())


def _service_words() -> frozenset:
    out: set = set()
    for k, v in eng.SERVICES.items():
        if eng.in_agenda(k):
            out |= _words(v["ro"])
    return frozenset(out)


def _doctor(title: str, body: str, doctors: dict) -> tuple[str, str]:
    """(врач, код отказа). Название — подсказкой вкладки; описание — только строки, где фамилии
    предшествует «Dr./medic»: без метки фамилия врача там чаще пациент-однофамилец или «trimis de»."""
    dk, hits = gimport.doctor_hint(title, doctors)
    marked = ""
    for line in (body or "").splitlines():
        if not set(gimport._WORD.findall(gimport.fold(line))) & gimport._MARKS:
            continue
        got, _hits = gimport.doctor_hint(line, doctors)
        if got:
            marked = got
            break
    if dk and marked and dk != marked:
        return "", "a_doctors"
    dk = dk or marked
    if not dk:
        return "", "a_doctors" if len(hits) > 1 else "a_doctor"
    if not eng.DOCTOR_META.get(dk, {}).get("active", True):
        return "", "a_doctor_off"
    return dk, ""


def _phone(raw: str) -> str:
    return raw if raw.startswith("+") else "0" + raw


def _static(v: dict, people, service: str, drop: frozenset) -> Pick | None:
    """Правило без базы и без часов журнала; None — строка не из «De mutat»."""
    if v["state"] != db.GCAL_NEW:
        return None
    pk = Pick(eid=v["id"], stamp=v.get("stamp", ""))
    if v["by_hand"]:
        return pk.stay("a_hand")
    if v["why"]:
        return pk.stay("a_check", v["why"]["text"])
    p, hint = v["preset"], v["hint"]
    if not p or not p["date"] or not p["time"]:
        return pk.stay("a_time")
    if not service:
        return pk.stay("a_service")
    dk, code = _doctor(v["title"], v["body"], dict(eng.DOCTORS))
    if code:
        return pk.stay(code)
    pk.doctor, pk.date, pk.time = dk, p["date"], p["time"]
    pk.minutes = int(p["duration"] or 0)
    raw = [w for w in (hint["name"] or "").split() if gimport.fold(w) not in drop]
    ew = _words(" ".join(raw))
    phones = list(hint["phones"])
    if phones:
        cands, seen = [], set()
        for ph in phones:
            for c in people.by_phone.get(ph, ()):
                if c["id"] not in seen:
                    seen.add(c["id"])
                    cands.append(c)
        same = [c for c in cands if ew and _words(c["name"]) <= ew]
        if len(cands) == 1:
            c = cands[0]
            # имя в событии есть, а фиша номера — другой человек: ребёнок на телефоне мамы
            if len(ew) >= 2 and not same:
                return pk.stay("a_other", name=c["name"])
        elif len(cands) > 1:
            if len(same) != 1:
                return pk.stay("a_family")
            c = same[0]
        else:
            if len(ew) < 2:
                return pk.stay("a_name")
            if people.by_name.get(ew):
                return pk.stay("a_name_phone")
            pk.ok, pk.fresh = True, True
            pk.name, pk.phone = " ".join(raw), _phone(phones[0])
            pk.who = pk.name
            return pk
        pk.ok, pk.pid, pk.who = True, c["id"], c["name"]
        return pk
    cands = people.by_name.get(ew, []) if len(ew) >= 2 else []
    if len(cands) != 1:
        return pk.stay("a_nobody")
    pk.ok, pk.pid, pk.who = True, cands[0]["id"], cands[0]["name"]
    return pk


def _start(pk: Pick) -> datetime:
    d = _date.fromisoformat(pk.date)
    hh, mm = (int(x) for x in pk.time.split(":"))
    return datetime(d.year, d.month, d.day, hh, mm, tzinfo=eng.TZ)


async def service() -> str:
    """Процедура переноса без человека — процедура вкладки, иначе правило импорта Excel."""
    return book.default_service(await gcal.tab_service())


async def plan(rows: list, *, probe: bool) -> list[Pick]:
    """Решения по строкам вкладки (`gcal._view`). `probe` — сверить ещё и час журнала (`book.probe`):
    так делают предпросмотр, пачка и проход опроса; список вкладки — только правило без журнала."""
    people = gcal._People(await db.gcal_patients())
    svc = await service()
    drop = _service_words()
    out = []
    # пересечения внутри самой пачки: проба видит только журнал, а не соседние строки
    taken: dict = {}
    for v in rows:
        pk = _static(v, people, svc, drop)
        if pk is None:
            continue
        if pk.ok and (ex := (v["hint"] or {}).get("exists")):
            a = await db.appointment_brief(ex["appt_id"])
            if a is not None and a["patient_id"] == pk.pid and a["doctor_id"] == pk.doctor:
                pk.link = ex["appt_id"]
            else:
                pk.stay("a_exists")
        if pk.ok and probe and pk.link is None:
            code = await book.probe(pk.pid, pk.doctor, _start(pk), svc, minutes=pk.minutes or None)
            if code not in OK_PROBE:
                pk.stay(code)
            else:
                _clash(pk, taken, svc)
        out.append(pk)
    return out


def _clash(pk: Pick, taken: dict, svc: str) -> None:
    """Строка пачки, которой место уже занято другой строкой той же пачки: у врача — столько
    одновременных, сколько у него кабинетов; у пациента — ни одной на тот же час."""
    begin = _start(pk)
    end = begin + timedelta(minutes=pk.minutes or eng.svc_duration(svc))
    lanes = max(1, len(eng.room_plan(pk.doctor).get("own") or ()))
    who = f"p{pk.pid}" if pk.pid else f"t{pk.phone}"

    def over(key: str) -> int:
        return sum(1 for b, e in taken.get(key, ()) if b < end and begin < e)
    if over(who):
        pk.stay("dup")
    elif over(pk.doctor) >= lanes:
        pk.stay("conflict")
    else:
        taken.setdefault(pk.doctor, []).append((begin, end))
        taken.setdefault(who, []).append((begin, end))


def token(picks: list[Pick], svc: str, sms: bool, auto: bool) -> str:
    """Отпечаток предпросмотра: переносится ровно то, что видели."""
    raw = json.dumps([[asdict(p) for p in picks], svc, sms, auto], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


async def sms_on() -> bool:
    return (await db.get_meta(META_SMS)) == "1"


async def set_sms(on: bool) -> str:
    await db.set_meta(META_SMS, "1" if on else "0")
    return "gc_a_sms_on" if on else "gc_a_sms_off"


def _when(iso: str) -> str:
    return db._parse_dt(iso).astimezone(eng.TZ).strftime("%d.%m.%Y %H:%M") if iso else ""


async def moves() -> list[dict]:
    try:
        got = json.loads(await db.get_meta(META_MOVES) or "[]")
    except ValueError:
        return []
    return got if isinstance(got, list) else []


async def _save_moves(recs: list) -> None:
    await db.set_meta(META_MOVES, json.dumps(recs[:MOVES_MAX], ensure_ascii=False))


async def _apply(picks: list[Pick], how: str, svc: str, sms: bool) -> dict:
    """Перенос решений `ok`; зовётся под `gcal.move_lock`. Событие перечитывается: перенесённое
    соседом, изменённое опросом или решённое человеком после предпросмотра не трогается."""
    # две мутации в одну секунду (пачка и опрос) не делят ключ: отмена одной не снимет другую
    key = f"{how}:{db._utcnow_iso()}:{secrets.token_hex(3)}"
    actor = gcal._actor()
    moved, fresh, refused, updates = 0, 0, [], []
    for pk in picks:
        if not pk.ok:
            continue
        row = await db.gcal_event(pk.eid)
        if row is None or row["state"] != db.GCAL_NEW or row["by_hand"] or row["stamp"] != pk.stamp:
            continue
        if pk.link is not None:
            a = await db.appointment_brief(pk.link)
            if a is None or a["patient_id"] != pk.pid:
                continue
            if not (a["comment"] or "").strip():
                await db.set_comment(pk.link, gcal._comment(row))
            if await db.gcal_mark_moved(pk.eid, pk.link, actor, how=how, key=key):
                moved += 1
            continue
        body = {"date": pk.date, "time": pk.time, "doctor": pk.doctor, "service": svc,
                "duration": str(pk.minutes) if pk.minutes else "", "name": pk.name, "phone": pk.phone,
                "nophone": False}
        digits = "".join(ch for ch in pk.phone if ch.isdigit())
        before = set(await db._patient_ids_by_digits(digits)) if pk.fresh else set()
        with db.booked_by(actor):
            code, aid = await gcal._journal_add(body, pk.pid)
        if code not in gcal.OK_CODES or aid is None:
            refused.append(pk.stay(code))
            updates.append((pk.eid, {"auto_why": _journal_why(pk)}))
            continue
        await db.set_comment(aid, gcal._comment(row))
        a = await db.appointment_brief(aid)
        new_pid = a["patient_id"] if pk.fresh and a and a["patient_id"] not in before else None
        await db.gcal_mark_moved(pk.eid, aid, actor, how=how, key=key, new_pid=new_pid, sms_skip=not sms)
        moved += 1
        fresh += new_pid is not None
    if updates:
        await db.gcal_write([], updates, [])
    if moved:
        recs = await moves()
        recs.insert(0, {"key": key, "at": db._utcnow_iso(), "by": actor, "how": how, "n": moved,
                        "fresh": fresh, "undone": None})
        await _save_moves(recs)
        what = "automat" if how == HOW_AUTO else "din listă"
        await db.log_clinic_event(
            "gcal", f"Google Calendar: {moved} evenimente mutate în jurnal ({what})", actor)
    return {"key": key if moved else "", "n": moved, "fresh": fresh, "refused": len(refused)}


def _journal_why(pk: Pick) -> str:
    """Причина, которую даёт журнал, а не само событие: занятый час, часы клиники, запись у другого
    врача. Её список вкладки сам не пересчитывает — она лежит у строки до следующей проверки."""
    return pk.why if not pk.ok and (pk.why == "a_exists" or not pk.why.startswith("a_")) else ""


async def _remember(picks: list[Pick], rows: list) -> None:
    was = {v["id"]: v.get("auto_why", "") for v in rows}
    updates = []
    for pk in picks:
        now = _journal_why(pk)
        if was.get(pk.eid, "") != now:
            updates.append((pk.eid, {"auto_why": now}))
    if updates:
        await db.gcal_write([], updates, [])


def _rows(data: dict) -> list:
    return [v for d in data["days"] for v in d["rows"]] + list(data["undated"])


async def preview(f_q: str, f_day: str, auto: bool) -> dict:
    """«Mută în jurnal toate cu medic» и включение автопереноса: что перенесётся из показанного
    списка «De mutat», а что останется и почему. Ничего не переносит."""
    data = await gcal.listing(gcal.F_NEW, f_q, f_day, "")
    rows = _rows(data)
    picks = await plan(rows, probe=True)
    await _remember(picks, rows)
    svc = await service()
    sms = await sms_on()
    by_id = {v["id"]: v for v in rows}

    def item(pk: Pick) -> dict:
        v = by_id[pk.eid]
        out = {"id": pk.eid, "date": v["date"], "time": (v["round"] or {}).get("to", "") or v["time"],
               "title": v["title"]}
        if pk.ok:
            out.update(doctor=eng.DOCTORS.get(pk.doctor, ""), patient=pk.who, fresh=pk.fresh,
                       phone=pk.phone if pk.fresh else "", link=pk.link is not None)
        else:
            out["why"] = {"code": pk.why, "text": pk.text}
        return out
    go = [item(p) for p in picks if p.ok]
    return {"go": go, "stay": [item(p) for p in picks if not p.ok],
            "counts": {"go": len(go), "fresh": sum(1 for p in picks if p.ok and p.fresh),
                       "stay": sum(1 for p in picks if not p.ok), "all": len(picks)},
            "service": svc, "sms": {"show": sms_loop.active(), "on": sms},
            "auto": auto, "token": token(picks, svc, sms, auto)}


async def run(f_q: str, f_day: str, tok: str, auto: bool) -> tuple[str, dict | None]:
    """Перенос того, что показал предпросмотр с тем же отпечатком; иначе `gc_a_stale`."""
    async with gcal.move_lock():
        data = await gcal.listing(gcal.F_NEW, f_q, f_day, "")
        rows = _rows(data)
        picks = await plan(rows, probe=True)
        svc = await service()
        sms = await sms_on()
        if token(picks, svc, sms, auto) != tok:
            return "gc_a_stale", None
        got = await _apply(picks, HOW_BATCH, svc, sms)
    return ("gc_a_moved" if got["n"] else "gc_a_none"), got


def allowed() -> bool:
    """Автопереносу нужны право `gcal` и рабочая лицензия: режим чтения ворота запросов закрывают
    сами, а проход опроса идёт без запроса."""
    s = lic.current()
    return lic.feature_until("gcal") is not None and s is not None and s.state in (lst.ACTIVE, lst.GRACE)


async def auto_pass(source_id: int) -> dict | None:
    """Проход после опроса календаря аккаунта: переносит годные события этого календаря."""
    if not allowed():
        return None
    prev = request_user()
    set_request_user(SYSTEM)
    try:
        async with gcal.move_lock():
            data = await gcal.listing(gcal.F_NEW, "", "", "")
            rows = [v for v in _rows(data) if v["src"] == source_id]
            picks = await plan(rows, probe=True)
            await _remember(picks, rows)
            got = await _apply(picks, HOW_AUTO, await service(), await sms_on())
    finally:
        set_request_user(prev)
    return got


async def undo(key: str) -> tuple[str, dict | None]:
    """Отмена мутации: снимаются нетронутые записи без детей и пустые фиши, заведённые ею."""
    async with gcal.move_lock():
        recs = await moves()
        rec = next((r for r in recs if r.get("key") == key), None)
        if rec is None or rec.get("undone"):
            return "gc_a_undo_gone", None
        rows = [r for r in await db.gcal_rows() if r.get("move_key") == key and r["appt_id"]]
        removed, kept, pids = 0, 0, set()
        for r in rows:
            if await db.gcal_unmove(r["id"], r["appt_id"]):
                removed += 1
                if r.get("move_pid"):
                    pids.add(int(r["move_pid"]))
            else:
                kept += 1
        cards = 0
        for pid in sorted(pids):
            if await db.erasure_kind(pid) == "delete" and await db.import_untouched(pid):
                await db.delete_patient_fully(pid)
                cards += 1
        # событие, чья дата прошла, в список не попадает — его запись остаётся
        kept = max(kept, int(rec.get("n") or 0) - removed)
        rec["undone"] = {"at": db._utcnow_iso(), "removed": removed, "kept": kept, "cards": cards}
        await _save_moves(recs)
        await db.log_clinic_event(
            "gcal", f"Google Calendar: mutarea din {_when(rec['at'])} anulată — {removed} programări "
                    f"șterse, {kept} rămase", gcal._actor())
    return "gc_a_undone", rec["undone"]


async def _changed_row(eid: int) -> tuple[dict | None, dict | None, str]:
    row = await db.gcal_event(eid)
    if row is None or row["state"] != db.GCAL_MOVED or not row["appt_id"]:
        return None, None, "gc_gone"
    if not gcal.changed(row):
        return None, None, "gc_a_nochange"
    a = await db.appointment_brief(row["appt_id"])
    if a is None:
        return None, None, "gc_appt"
    return row, a, ""


def touched(row: dict, appt: dict) -> bool:
    """Запись уже меняли в DentPilot: не «programată» или стоит не там, куда её поставил перенос."""
    slot = gcal.stamp_slot(row["stamp_moved"])
    if slot is None or appt["status"] != "confirmed":
        return True
    begin, _mins = gimport.round_slot(*slot)
    return appt["starts_at"].astimezone(eng.TZ) != begin.astimezone(eng.TZ)


async def _ack(row: dict) -> None:
    await db.gcal_write([], [(row["id"], {"stamp_moved": row["stamp"], "ack": row["gstatus"]})], [])


async def keep(eid: int) -> str:
    """«Lasă cum e»: изменение в Google принято, запись журнала не трогается."""
    async with gcal.move_lock():
        row, _a, code = await _changed_row(eid)
        if code:
            return code
        await _ack(row)
    return "gc_a_kept"


async def follow(eid: int) -> str:
    """«Mută și programarea»: запись идёт за Google правилом перетаскивания; метку «без SMS»
    перенос за Google не снимает — это не решение регистратора о новом часе."""
    async with gcal.move_lock():
        row, a, code = await _changed_row(eid)
        if code:
            return code
        if row["gstatus"] or touched(row, a):
            return "gc_a_touched"
        slot = gcal.stamp_slot(row["stamp"])
        if slot is None:
            return "gc_a_touched"
        begin, mins = gimport.round_slot(*slot)
        loc = begin.astimezone(eng.TZ)
        code = await sroutes._move_appt(row["appt_id"], loc.date().isoformat(), f"{loc:%H:%M}",
                                        a["doctor_id"], keep_sms_skip=True)
        if code not in ("ok_move", "room_busy"):
            return code
        if mins != int(a["duration_min"] or 0):
            dur = await sroutes._set_duration(row["appt_id"], str(mins))
            if dur not in ("ok_dur", ""):
                return dur
        await _ack(row)
    return "gc_a_followed" if code == "ok_move" else code


async def cancel_appt(eid: int) -> str:
    """«Anulează programarea» у события, отменённого или пропавшего в Google."""
    async with gcal.move_lock():
        row, a, code = await _changed_row(eid)
        if code:
            return code
        if not row["gstatus"] or touched(row, a):
            return "gc_a_touched"
        code = await sroutes._set_status(row["appt_id"], "cancelled")
        if code:
            return code
        await _ack(row)
    return "gc_a_cancelled"


async def annotate(data: dict, *, link_auto: dict | None) -> None:
    """Список вкладки: у строки «De mutat» — почему она сама не переносится, у перенесённой — как,
    у изменённой в Google — какие кнопки; над списком — полоса пачки и история мутаций."""
    rows = _rows(data)
    people = gcal._People(await db.gcal_patients()) if any(v["state"] == db.GCAL_NEW for v in rows) else None
    svc = await service()
    drop = _service_words()
    go = total = 0
    for v in rows:
        v["auto"] = {"why": None, "how": v["moved_how"], "dp": False}
        v["can"].update(follow=False, cancel_appt=False, keep=False)
        if v["state"] == db.GCAL_NEW and people is not None:
            pk = _static(v, people, svc, drop)
            total += 1
            if pk is not None and not pk.ok:
                if pk.why != "a_check":
                    v["auto"]["why"] = {"code": pk.why, "text": pk.text}
            elif v["auto_why"]:
                v["auto"]["why"] = reason(v["auto_why"])
            else:
                go += 1
        elif v["changed"] and v["appt"]:
            dp = (v["appt"]["status"]["code"] != "confirmed"
                  or v["placed"] is None or v["appt"]["when"] != v["placed"]["when"])
            v["auto"]["dp"] = dp
            v["can"].update(keep=True, follow=not dp and not v["gstatus"],
                            cancel_appt=not dp and bool(v["gstatus"]))
    recs = await moves()
    last = next((r for r in recs if r.get("how") == HOW_AUTO and not r.get("undone")), None)
    data["automove"] = {
        "batch": {"go": go, "all": total},
        "sms": {"show": sms_loop.active(), "on": await sms_on()},
        "auto": link_auto,
        "last": {"when": _when(last["at"]), "n": last["n"]} if last else None,
        "moves": [{"key": r["key"], "when": _when(r["at"]), "how": r["how"], "by": r.get("by", ""),
                   "n": r["n"], "fresh": r.get("fresh", 0),
                   "undone": ({**r["undone"], "when": _when(r["undone"]["at"])} if r.get("undone") else None)}
                  for r in recs[:10]],
    }
