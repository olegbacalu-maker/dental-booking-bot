"""«Registre» (10.11.2026): санитарные регистры 257/e, 502/e, 501/e — страницы.

Экран раздела и каталог в настройках — оболочка React (`react_shell`), данные —
`api.py`. Здесь же печатный лист за период (`sheet.py`) и выгрузка Excel.
Формы: 257/e (автоклав, Ordin MS 828/2011), 502/e (генеральная уборка) и 501/e
(УФ-лампы, Ordin MS 630/2016); регистр «fizic sau electronic» — HG 4/2026 п.141.
Пишут все вошедшие; каталог — директор (`PERM_SETTINGS`).
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from ... import db
from ...core import registre as reg
from ...core import xlsx
from ...core.auth import PERM_SETTINGS, _guard, require
from ...core.layout import react_shell, shell_model
from . import sheet

router = APIRouter()


@router.get("/admin/registre", response_class=HTMLResponse)
async def admin_registre(request: Request):
    # пишут все вошедшие: права нет, но вход — обязателен
    if (deny := _guard(request)) is not None:
        return deny
    return react_shell("registre", request.url.path, shell_model("reg", ""))


@router.get("/admin/settings/registre", response_class=HTMLResponse)
async def admin_settings_registre(request: Request):
    if (deny := require(request, PERM_SETTINGS)) is not None:
        return deny
    return react_shell("settings_registre", request.url.path, shell_model("set", ""))


def _form(form: str) -> str | None:
    return form if form in reg.REGS else None


@router.get("/admin/registre/tipar/{form}", response_class=HTMLResponse)
async def admin_registre_print(request: Request, form: str, month: str = "", to: str = ""):
    if (deny := _guard(request)) is not None:
        return deny
    if _form(form) is None:
        return HTMLResponse("Registru necunoscut", status_code=404)
    frm = request.query_params.get("from", "")
    d1, d2 = reg.period(month, frm, to)
    rows = await reg.rows(form, d1, d2)
    norms, lamps = "", []
    if form == "257":
        have = await db.san_items("norms")
        norms = (have[0]["data"].get("text") or "") if have else ""
    if form == "501":
        ids = {r["lamp_id"] for r in rows}
        for lp in (await reg.catalog())["items"]["lamp"]:
            if lp["active"] or lp["id"] in ids:
                lamps.append(lp)
    printed = reg.stamp(datetime.now(timezone.utc))
    return HTMLResponse(sheet.render(form, rows, d1, d2, printed, norms, lamps,
                                     back=f"/admin/registre?v=istoric&r={form}&m={d1.strftime('%Y-%m')}"))


@router.get("/admin/registre/excel/{form}")
async def admin_registre_excel(request: Request, form: str, month: str = "", to: str = ""):
    if (deny := _guard(request)) is not None:
        return deny
    if _form(form) is None:
        return Response("Registru necunoscut", status_code=404)
    d1, d2 = reg.period(month, request.query_params.get("from", ""), to)
    head, rows, widths = sheet.excel_rows(form, await reg.rows(form, d1, d2))
    blob = xlsx.book(head, rows, widths=widths, sheet_name=f"Registru {form}e")
    fname = f"registru_{form}e_{d1.isoformat()}.xlsx"
    return Response(blob, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})
