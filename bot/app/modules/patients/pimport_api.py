"""Импорт пациентов из файла. Файл идёт телом запроса, не формой: форма
кладёт его во временный каталог открытым текстом, мимо шифрования картотеки."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from ... import db
from ... import engine as eng
from ...core import tabfile, xlsx
from ...core.api import api_require
from ...core.auth import PERM_IMPORT, local_only, remote_notice, require
from ...core.layout import msg_json, react_shell, shell_model
from . import pimport as pi

router = APIRouter()

_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_REFUSE = {"old_xls": "pi_old_xls", "not_table": "pi_not_table", "too_big": "pi_too_big",
           "too_many_rows": "pi_rows", "bad_xml": "pi_not_table", "empty": "pi_empty"}


async def _blob(request: Request) -> bytes | None:
    """None — больше потолка. Лишнее дочитывается: ответ посреди отправки
    браузер видит как обрыв сети, а не как отказ со словами."""
    buf, over = bytearray(), False
    async for chunk in request.stream():
        if not over:
            buf += chunk
            if len(buf) > tabfile.MAX_FILE:
                over = True
                buf.clear()
    return None if over else bytes(buf)


def _parse(blob: bytes, name: str, opts: dict):
    """Разбор или код отказа. Тяжёлая — зовётся в потоке, не в цикле событий."""
    try:
        table = tabfile.read(blob, name, enc=opts["enc"], delim=opts["delim"])
    except tabfile.Refuse as e:
        return _REFUSE[e.code]
    res = pi.resolve(table, opts)
    if res is None:
        return "pi_opts"
    recs, preview = pi.build(table, res, list(eng.DOCTORS.values()))
    if len(recs) > tabfile.MAX_ROWS:
        return "pi_rows"
    return table, res, recs, preview


async def _load(request: Request):
    """Общий вход маршрутов с файлом: отказ конвертом или разобранный файл."""
    q = request.query_params
    opts = pi.parse_opts(q.get("opts", ""))
    if opts is None:
        return msg_json(False, "pi_opts", status=422)
    blob = await _blob(request)
    if blob is None:
        return msg_json(False, "pi_too_big", status=413)
    name = q.get("name", "").strip()[:200]
    got = await asyncio.to_thread(_parse, blob, name, opts)
    if isinstance(got, str):
        return msg_json(False, got, status=422)
    return (blob, name, *got)


def _when(v) -> str:
    return v.astimezone(eng.TZ).strftime("%d.%m.%Y %H:%M") if hasattr(v, "astimezone") else ""


def _import_view(r: dict) -> dict:
    left = r["created"] - r["removed"]
    return {"id": r["id"], "at": _when(r["at"]), "actor": r["actor"], "file": r["file_name"],
            "rows": r["rows"], "created": r["created"], "filled": r["filled"],
            "skipped": r["skipped"], "removed": r["removed"],
            "undone": r["undone_at"] is not None, "can_undo": left > 0}


PAGE = "/admin/patients/import"
_CRUMBS = [{"href": "/admin/search", "icon": "chev-l", "label": "Pacienți"}]


@router.get(PAGE, response_class=HTMLResponse)
async def admin_pimport(request: Request):
    """В разделе «Pacienți», не в «Setări»: регистратура настроек не видит."""
    if (deny := require(request, PERM_IMPORT)) is not None:
        return deny
    return react_shell("patients_import", request.url.path,
                       shell_model("pat", "import din fișier Excel sau CSV", crumbs=_CRUMBS))


@router.get("/api/pimport")
async def api_pimport(request: Request):
    """Экран импорта: прошлые импорты, поля для выбора колонок, потолки."""
    if (deny := api_require(request, PERM_IMPORT)) is not None:
        return deny
    return msg_json(True, data={
        "imports": [_import_view(r) for r in await db.import_list()],
        "fields": [{"id": f, "label": label} for f, label in pi.FIELDS],
        "limits": {"bytes": tabfile.MAX_FILE, "rows": tabfile.MAX_ROWS, "batch": pi.BATCH},
        "encodings": list(tabfile.ENCODINGS), "delimiters": list(tabfile.DELIMITERS),
        "remote": remote_notice(request),
    })


@router.get("/api/pimport/model.xlsx")
async def api_pimport_model(request: Request):
    """Пустая книга с шапкой, которую импорт узнаёт сам."""
    if (deny := api_require(request, PERM_IMPORT)) is not None:
        return deny
    blob = xlsx.book(
        ["Nume și prenume", "Telefon", "Data nașterii", "IDNP", "Gen", "E-mail", "Adresă",
         "Asigurare", "Medic curant", "Nr. dosar", "Notițe"], [],
        widths=[28, 14, 13, 16, 6, 26, 30, 16, 22, 10, 40], sheet_name="Pacienti")
    return Response(blob, media_type=_XLSX, headers={
        "Content-Disposition": 'attachment; filename="model-import-pacienti.xlsx"'})


@router.post("/api/pimport/check")
async def api_pimport_check(request: Request):
    """Шаги «Coloane» и «Verificare»: что в файле и что с ним будет. Ничего
    не пишет."""
    if (deny := api_require(request, PERM_IMPORT)) is not None:
        return deny
    if (deny := local_only(request)) is not None:
        return deny
    got = await _load(request)
    if isinstance(got, Response):
        return got
    blob, name, table, res, recs, preview = got
    sheet = table.sheets[res["sheet"]]
    head = next((ln for rno, ln in sheet.rows if rno == res["header"]), [])
    width = max([len(head)] + [len(p["cells"]) for p in preview] + [max(res["cols"], default=-1) + 1])
    data = {
        "file": {"name": name, "kind": table.kind, "size": len(blob),
                 "sheets": [{"name": s.name, "rows": len(s.rows)} for s in table.sheets],
                 "enc": table.enc, "delim": table.delim},
        "opts": {**res, "cols": {str(k): v for k, v in res["cols"].items()}},
        "columns": [{"index": i, "letter": xlsx._col(i),
                     "title": pi._text(head[i]) if i < len(head) else "",
                     "field": res["cols"].get(i, "")} for i in range(width)],
        "preview": preview,
        "ready": pi.ready(res),
        "counts": None, "groups": [], "token": "",
    }
    if data["ready"]:
        pi.analyse(recs, await db.import_index(), res["force"])
        data["counts"], data["groups"] = pi.summary(recs)
        data["token"] = pi.token(blob, res)
        data["parts"] = -(-len(recs) // pi.BATCH)
    return msg_json(True, data=data)


@router.post("/api/pimport/run")
async def api_pimport_run(request: Request):
    """Порциями, чтобы запись тысяч фиш не останавливала журнал; повтор порции
    безвреден: заведённое узнаётся как «există deja»."""
    if (deny := api_require(request, PERM_IMPORT)) is not None:
        return deny
    if (deny := local_only(request)) is not None:
        return deny
    got = await _load(request)
    if isinstance(got, Response):
        return got
    blob, name, _table, res, recs, _preview = got
    q = request.query_params
    if not pi.ready(res):
        return msg_json(False, "pi_no_name", status=422)
    if not recs:
        return msg_json(False, "pi_empty", status=422)
    if q.get("token", "") != pi.token(blob, res):
        return msg_json(False, "pi_stale", status=409)
    try:
        part, iid = int(q.get("part", "0")), int(q.get("import", "0"))
    except ValueError:
        return msg_json(False, "pi_opts", status=422)
    parts = -(-len(recs) // pi.BATCH)
    if not 0 <= part < max(parts, 1):
        return msg_json(False, "pi_opts", status=422)
    if iid:
        run = await db.import_get(iid)
        if run is None or run["undone_at"] is not None:
            return msg_json(False, "pi_gone", status=409)
    else:
        iid = await db.import_open(name, len(recs))
    pi.analyse(recs, await db.import_index(), res["force"])
    created = filled = skipped = 0
    for rec in recs[part * pi.BATCH:(part + 1) * pi.BATCH]:
        if rec["act"] == "new":
            await pi.create(rec, iid, name)
            created += 1
        elif rec["act"] == "exists" and res["fill"] and rec["fill"] and await pi.fill(rec):
            filled += 1
        else:
            skipped += 1
    await db.import_count(iid, created, filled, skipped)
    run = await db.import_get(iid)
    done = part + 1 >= parts
    if done and not (run["created"] or run["filled"]):
        # повторный запуск того же файла: в списке импортов ему делать нечего
        await db.import_drop(iid)
    elif done:
        text = (f"Import pacienți: {run['created']} fișe noi, {run['skipped']} omise"
                + (f", {run['filled']} completate" if run["filled"] else "")
                + f" („{name[:60]}”)")
        await db.log_clinic_event("import", text, actor=run["actor"] or "sistem")
    return msg_json(True, "pi_done" if done else "", data={
        "import": iid, "part": part, "parts": parts, "done": done,
        "created": created, "filled": filled, "skipped": skipped,
        "total": _import_view(run)})


@router.post("/api/pimport/report")
async def api_pimport_report(request: Request):
    """`import` — номер импорта, чьи фиши считать вошедшими."""
    if (deny := api_require(request, PERM_IMPORT)) is not None:
        return deny
    if (deny := local_only(request)) is not None:
        return deny
    got = await _load(request)
    if isinstance(got, Response):
        return got
    _blob_, _name, _table, res, recs, _preview = got
    iid = request.query_params.get("import", "0")
    pi.analyse(recs, await db.import_index(), res["force"], int(iid) if iid.isdigit() else 0)
    blob = xlsx.book(
        ["Rând", "Nume", "Telefon", "Data nașterii", "IDNP", "Rezultat", "Observații"],
        pi.report_rows(recs), widths=[7, 28, 14, 13, 16, 24, 70], sheet_name="Import")
    return Response(blob, media_type=_XLSX, headers={
        "Content-Disposition": 'attachment; filename="raport-import-pacienti.xlsx"'})


@router.post("/api/pimport/undo")
async def api_pimport_undo(request: Request):
    """Убирает только фиши импорта, в которых с тех пор ничего не делали."""
    if (deny := api_require(request, PERM_IMPORT)) is not None:
        return deny
    if (deny := local_only(request)) is not None:
        return deny
    q = request.query_params
    try:
        iid, after = int(q.get("id", "0")), int(q.get("after", "0"))
    except ValueError:
        return msg_json(False, "pi_opts", status=422)
    run = await db.import_get(iid)
    if run is None:
        return msg_json(False, "pi_gone", status=404)
    pids = await db.import_pids(iid, after, pi.BATCH)
    removed = 0
    for pid in pids:
        if await db.erasure_kind(pid) == "delete" and await db.import_untouched(pid):
            await db.delete_patient_fully(pid)
            removed += 1
    done = len(pids) < pi.BATCH
    await db.import_undone(iid, removed, done)
    run = await db.import_get(iid)
    kept = run["created"] - run["removed"]
    if done:
        await db.log_clinic_event(
            "import", actor=db._actor_now(), text=f"Import anulat („{run['file_name'][:60]}”): {run['removed']} fișe "
                      f"șterse, {kept} păstrate")
    return msg_json(True, "pi_undone" if done else "", data={
        "done": done, "after": pids[-1] if pids else after, "removed": removed,
        "kept": kept, "total": _import_view(run)})
