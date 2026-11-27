"""Ответ пациента ссылкой из SMS (Premium, волна 2а): коды, забор ответов, закрытие.

Пациент получает в напоминании «Cu o zi înainte» строку `Confirmare/anulare:
v.dentpilot.md/K7Q2MX` и на странице нашего сервера жмёт «Vin» или «Nu pot veni».
Ответ ложится в окно визита отметкой звонка вторым каналом («Confirmat · SMS» /
«Nu poate veni · SMS»). Программа сама ничего не отменяет и не переносит.

Три чистых соседа: `plink` (провод), `sms_plan` (текст со ссылкой — хвост, не
подстановка), `sms_rule`. Здесь — связка с базой, лицензией и часами:

1. Коды — `links(rows)`: цикл SMS спрашивает их ДО постановки строки в очередь
   (текст собирается при постановке). Один код на визит и его НАЧАЛО: перенос —
   новый код, прежний закрывается. Нет кода (сервер молчит) — нет строки: визит
   ждёт следующего тика; сервер снял право (`link_plan`) — обычный текст без ссылки.
2. Забор — `tick()` раз в TICK, пока есть живые коды: перемены после
   `schema_meta › plink_seq`; повторная доставка безвредна (`db.plink_answer`
   применяет только более новую перемену). Отметку в журнале ставит крючок
   `attach(apply=…)` — `modules/schedule/plink.py`: core журнал не импортирует.
3. Закрытие — тем же проходом: перенос, отмена, «Fără SMS», архив
   (`db.plink_stale`) и стирание (`schema_meta › plink_close`).

Право спрашивает фон сам (`allowed()`): ворота 423 стоят только на запросах.
Закрывать коды можно и без права — убрать ссылку пациента можно всегда.
Код и адрес ссылки в лог не попадают: по коду открывается страница ответа.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

from .. import db
from .. import engine as eng
from . import license as lic
from . import plink as wire
from . import rsa_verify
from . import sms_plan as plan

log = logging.getLogger("plink")

GATE = "sms_link"                           # право в файле лицензии (множество Premium в облаке)
TICK = 20.0                                 # забор ответов, пока есть живые коды
TICK_ENV = "DENTART_PLINK_TICK_S"           # стенд: секунды вместо двадцати
META_SEQ = "plink_seq"                      # последняя принятая перемена сервера
META_HOST = "plink_host"                    # адрес страницы ответа из последней выдачи
DEFAULT_HOST = "v.dentpilot.md"             # только для предпросмотра, пока кодов не выдавали
SAMPLE_CODE = "K7Q2MX"                      # код предпросмотра экрана: настоящий код — только в SMS
LATE = timedelta(hours=1)                   # ответ, нажатый перед самым началом, ещё забираем
CANT_WINDOW = timedelta(hours=12)           # уведомление у часов — про недавний «Nu pot veni»

# исходы выдачи кодов для цикла SMS
LINKS = "links"                             # коды есть: текст со ссылкой
PLAIN = "plain"                             # ссылки не будет: обычный текст
WAIT = "wait"                               # сервер молчит: строку не ставить, ждать тика

_hook: dict = {"apply": None}
_task: asyncio.Task | None = None
_wake: asyncio.Event | None = None
_lock: asyncio.Lock | None = None
_last: dict = {"at": None, "outcome": "", "error": "", "applied": 0}
_cant: dict = {"seq": 0}                    # последний «Nu pot veni» за CANT_WINDOW — уведомлению у часов


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _agent() -> str:
    return f"DentPilot/{eng.APP_VERSION}"


def attach(*, apply) -> None:
    """Крючок журнала при старте: корутина `apply(link, state, at) -> bool` ставит отметку
    визита по ответу пациента. Повторный вызов заменяет; None — ответы только копятся."""
    _hook["apply"] = apply


# ---------- куда, можно ли ----------


def target() -> tuple[str, str] | None:
    """(база /v1/link/, токен) из принятого файла лицензии — как у SMS."""
    if not lic.applies():
        return None
    t = lic.renew_target()
    if t is None:
        return None
    base = wire.base_of(t[0])
    return (base, t[1]) if base and rsa_verify.renew_url_ok(base) else None


def allowed() -> bool:
    """Право `sms_link` в принятом файле (в нём уже ACTIVE/GRACE и режим чтения)."""
    return lic.feature_until(GATE) is not None


def right_until() -> str:
    u = lic.feature_until(GATE)
    return u.astimezone(eng.TZ).strftime("%d.%m.%Y") if u is not None else ""


def settings() -> dict:
    return plan.settings((eng.CONFIG or {}).get("sms"))


def link_on(s: dict | None = None) -> bool:
    """Ссылка уходит в напоминание накануне: право есть и галочка клиники стоит."""
    return allowed() and plan.link_confirm(s if s is not None else settings())


def _label() -> str:
    """Подпись клиники теми же словами, что в SMS (`{clinica}` румынского текста)."""
    return plan.fold(plan.clinic_label(eng.CLINIC_NAME, "ro"))


def starts_key(starts_at: datetime) -> str:
    """Начало визита строкой ключа повтора SMS (`sms_plan.idem`): к нему привязан код."""
    return starts_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def _host() -> str:
    h = await db.get_meta(META_HOST) or ""
    return h if wire.HOST_RE.match(h) else ""


# ---------- коды для напоминания ----------


async def links(rows: list[dict]) -> tuple[str, dict]:
    """Ссылки для строк очереди накануне: (LINKS, {appt_id: адрес}) | (PLAIN, {}) |
    (WAIT, {}). Строка — визит из `db.sms_candidates`. Живой код визита при нынешнем
    начале берётся прежний (тик, на котором очередь не приняла строку, не множит
    коды); недостающие сервер выдаёт одним запросом."""
    t = target()
    if t is None or not link_on():
        return PLAIN, {}
    ids = [r["id"] for r in rows]
    have = await db.plink_codes_for(ids)
    host = await _host()
    # адрес страницы забыт (картотека из копии) — живые коды без него не напечатать: новые
    need = [r for r in rows if r["id"] not in have] if host else list(rows)
    if not host:
        have = {}
    # срок кода — начало СВОЕГО визита: запрос на каждое начало (накануне их десяток-другой)
    groups: dict[str, list] = {}
    for r in need:
        groups.setdefault(starts_key(r["starts_at"]), []).append(r)
    for until, group in groups.items():
        group = group[:wire.NEW_MAX]
        langs = [(r.get("lang") if r.get("lang") in plan.LANGS else "ro") for r in group]
        outcome, body = await asyncio.to_thread(
            wire.new, t[0], t[1], until, langs, _label(), (eng.CLINIC_PHONE or "").strip(),
            wire.TIMEOUT, _agent(), lic.identity())
        if outcome == wire.DENIED:
            why = str(body.get("code") or "")
            _last["error"] = why
            log.warning("plink: codes refused: %s", why)
            return PLAIN, {}
        if outcome != wire.OK:
            _last["error"] = outcome
            log.warning("plink: codes not issued: %s", outcome)
            return WAIT, {}
        host = body["host"]
        await db.set_meta(META_HOST, host)
        for r, code in zip(group, body["codes"]):
            await db.plink_add(code, wire.CONFIRM, r["id"], r["patient_id"], until, r["starts_at"])
            have[r["id"]] = code
        log.info("plink: issued %d codes", len(body["codes"]))
    if need and len(have) < len(rows):
        return WAIT, {}
    if not host:
        return WAIT, {}
    out = {}
    for aid, code in have.items():
        url = wire.url(host, code)
        if plan.link_ok(url):
            out[aid] = url
    if len(out) < len(have):
        log.warning("plink: link address too long or malformed — plain text")
        return PLAIN, {}
    return LINKS, out


# ---------- забор ответов и закрытие ----------


async def _close_list() -> list[str]:
    raw = await db.get_meta(db.PLINK_CLOSE_META) or ""
    return [c for c in raw.split(",") if wire.code_ok(c)]


async def _close(base: str, token: str) -> int:
    """Закрыть на сервере: устаревшие коды живых визитов и коды стёртых пациентов."""
    stale = await db.plink_stale()
    if stale:
        await db.plink_mark_closed(stale)
    local = await db.plink_unshut(wire.NEW_MAX)
    erased = await _close_list()
    send = list(dict.fromkeys(local + erased))[:wire.NEW_MAX]
    if not send:
        return 0
    outcome, body = await asyncio.to_thread(wire.close, base, token, send, wire.TIMEOUT, _agent(),
                                            lic.identity())
    if outcome not in (wire.OK, wire.DENIED):
        return 0
    if outcome == wire.DENIED:
        # отказ по существу повторять незачем: код умрёт сроком на сервере
        why = str(body.get("code") or "")
        log.warning("plink: close refused: %s", why)
    await db.plink_shut([c for c in local if c in send])
    left = [c for c in await _close_list() if c not in send]
    await db.set_meta(db.PLINK_CLOSE_META, ",".join(left))
    return len(send)


def _parse_at(raw: str) -> datetime | None:
    try:
        at = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return at if at.tzinfo is not None else None


async def _apply(it: dict) -> bool:
    """Одна перемена сервера → строка кода и (через крючок) отметка журнала."""
    row = await db.plink_get(it["code"])
    if row is None:
        return False                        # код стёртого пациента или чужой
    at = _parse_at(it["at"])
    if at is None:
        return False
    if it["state"] == db.LINK_CLOSED:
        await db.plink_mark_closed([row["code"]])
        await db.plink_shut([row["code"]])
        return False
    if not await db.plink_answer(row["code"], it["state"], it["seq"], at):
        return False
    fn = _hook["apply"]
    if fn is None:
        return False
    return bool(await fn(row, it["state"], at))


async def _pull(base: str, token: str, now: datetime) -> int:
    if await db.plink_live_count(now - LATE) == 0:
        return 0
    after = int(await db.get_meta(META_SEQ) or 0)
    outcome, body = await asyncio.to_thread(wire.inbox, base, token, after, wire.TIMEOUT, _agent(),
                                            lic.identity())
    if outcome != wire.OK:
        _last["error"] = str(body.get("code") or outcome) if outcome == wire.DENIED else outcome
        return 0
    n = 0
    for it in body["items"]:
        if it["seq"] <= after:
            continue
        if await _apply(it):
            n += 1
            if it["state"] == db.LINK_NO:
                _cant["seq"] = max(_cant["seq"], it["seq"])
    if body["seq"] > after:
        await db.set_meta(META_SEQ, str(body["seq"]))
    return n


async def tick() -> str:
    """Один проход: закрыть устаревшее, забрать ответы. Исход — слово для лога и экрана."""
    global _lock
    now = _now()
    t = target()
    if t is None:
        _last.update(at=now, outcome="none")
        return "none"
    if _lock is None:
        _lock = asyncio.Lock()
    async with _lock:
        closed = await _close(*t)
        applied = 0
        if allowed():
            _last["error"] = ""
            applied = await _pull(t[0], t[1], now)
        outcome = "applied" if applied else ("on" if allowed() else "off")
        _last.update(at=now, outcome=outcome, applied=applied)
        if applied or closed:
            log.warning("plink: tick applied=%d closed=%d", applied, closed)
        return outcome


async def startup() -> None:
    """Последний «Nu pot veni» за CANT_WINDOW — уведомлению у часов после перезапуска."""
    _cant["seq"] = await db.plink_last_no(_now() - CANT_WINDOW)


def _tick_seconds() -> float:
    try:
        s = float(os.environ.get(TICK_ENV, "") or 0)
    except ValueError:
        s = 0
    return s if s > 0 else TICK


async def _loop() -> None:
    global _wake
    _wake = asyncio.Event()
    while True:
        try:
            await tick()
        except Exception as e:  # noqa: BLE001 — фон не имеет права умереть
            log.warning("plink: tick failed: %r", e)
        _wake.clear()
        try:
            await asyncio.wait_for(_wake.wait(), timeout=_tick_seconds())
        except asyncio.TimeoutError:
            pass


def start_async() -> None:
    """Из хука старта main.py: цикл в фоне, старт его не ждёт; без файла с `renew` — пустой проход."""
    global _task
    if _task is not None:
        return
    _task = asyncio.get_running_loop().create_task(_loop())


def wake() -> None:
    if _wake is not None:
        _wake.set()


# ---------- экрану и часам ----------


CANT_TITLE = "Pacientul nu poate veni"
CANT_TEXT = ("Un pacient a apăsat „Nu pot veni” în linkul din SMS. Sunați-l — îl vedeți primul "
             "în „De confirmat”, în Panoul principal.")


def cant_item() -> dict | None:
    """Уведомление у часов на «Nu pot veni»: `id` — номер перемены, без имени пациента
    (уведомление видно на экране без входа)."""
    if not _cant["seq"] or not allowed():
        return None
    return {"id": f"plink:no:{_cant['seq']}", "title": CANT_TITLE, "body": CANT_TEXT, "open": "/admin"}


def preview_url() -> str:
    return f"{DEFAULT_HOST}/{SAMPLE_CODE}"


def screen() -> dict:
    """Блок «Răspunsul pacientului» экрана SMS: есть ли право, стоит ли галочка, работает ли."""
    s = settings()
    return {"allowed": allowed(), "until": right_until(), "confirm": plan.link_confirm(s),
            "on": link_on(s), "event": plan.LINK_EVENT, "variant": plan.DETALIAT,
            "parts": plan.LINK_PARTS,
            "last": {"at": _last["at"].strftime("%Y-%m-%dT%H:%M:%SZ") if _last["at"] else None,
                     "outcome": _last["outcome"], "error": _last["error"]}}
