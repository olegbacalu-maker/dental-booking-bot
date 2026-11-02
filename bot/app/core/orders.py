"""Подпись заказов лаунчеру: шифрование, расшифровка, восстановление (02.11).

Страница настроек только ЗАКАЗЫВАЕТ файлом в папке данных, а исполняет
лаунчер до старта приложения (`dbkey.apply_pending`, `restore.apply_pending`).
Папку данных (`ProgramData\\DentPilot\\data`) установщик открыл на запись
ВСЕМ учёткам Windows этого ПК — значит файл-заказ мог положить кто угодно, а
исполнил бы владелец при следующем запуске: расшифровал бы картотеку для
чужой учётки или подменил базу её копией (разбор коллеги 02.11, Б2).

Поэтому заказ подписан HMAC-SHA256 секретом, которого чужая учётка не видит
и не подложит: он лежит в `%LOCALAPPDATA%\\DentPilot` ЭТОЙ учётки
(`paths.user_dir`) и вдобавок под её DPAPI.
⛔ Не в папке данных даже под DPAPI: DPAPI с флагом LOCAL_MACHINE даёт
блоб, который прочтёт ЛЮБАЯ учётка этой машины, — чужая положила бы свой
секрет на место нашего, и `unprotect` владельца его отдал бы.

Подпись покрывает и то, ЧТО исполнится: заказ расшифровки — отпечаток
`db.key` (новое шифрование = новый ключ, старый заказ мёртв), заказ
шифрования — свой DPAPI-блоб, восстановление — отпечаток всей приёмки
(`restore-staging`). Повтор однажды исполненного (или снятого) заказа
ловит список израсходованных номеров рядом с секретом.

Неподписанный или чужой заказ не исполняется: файл отодвигается в сторону
(`<имя>.rejected-<дата>` — след для разбора), строка уходит в лог лаунчера,
и при старте приложения — в летопись и баннер директору (`report_done`).

⚠️ Секрет у каждой учётки свой. Заказ, сделанный под одной учёткой и
встреченный лаунчером другой, отвергается — шифрование при двух учётках и так
не поддерживается, а восстановление программа перезапускает сразу, той же
учёткой.
⚠️ Модуль зовёт ЛАУНЧЕР до сборки приложения: в шапке — только `paths`,
`dpapi` и стандартная библиотека (`test_structure`: «модули копий
импортируемы лаунчером»); `db` и `layout` — отложенно, в `report_done`.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import logging
import os
import pathlib
import secrets
import time
from datetime import datetime

from .. import dpapi, paths

SECRET_FILE = "orders.key"       # в paths.user_dir(), под DPAPI
USED_FILE = "orders.used"        # там же: израсходованные номера заказов
USED_KEEP = 200
DONE_FILE = "orders.done"        # в папке данных: что лаунчер сделал/отверг
REJECTED = "rejected"            # <заказ>.rejected-<дата>
SECRET_BYTES = 32

ENCRYPT, DECRYPT, RESTORE = "encrypt", "decrypt", "restore"
# Что отвергнуто — словами для летописи и баннера
WHAT_RO = {ENCRYPT: "pornirea criptării evidenței",
           DECRYPT: "oprirea criptării evidenței",
           RESTORE: "restaurarea evidenței dintr-o copie"}

log = logging.getLogger("orders")


# ---------- секрет ----------

def _secret_path() -> pathlib.Path | None:
    d = paths.user_dir()
    return d / SECRET_FILE if d is not None else None


def _seal(raw: bytes) -> str | None:
    text = base64.b64encode(raw).decode()
    if dpapi.available():
        return dpapi.protect(text)
    return text                      # не Windows: облако и CI, лаунчера там нет


def _unseal(stored: str) -> bytes | None:
    # ⚠️ None («не расшифровалось» — чужая учётка, перенесённый профиль) и ""
    # (пустой файл) — разные беды у `dpapi`, но для подписи обе значат одно:
    # секрета нет. Различать их обязан тот, кто СОЗДАЁТ: см. `_secret`.
    text = dpapi.unprotect(stored)
    if not text:
        return None
    try:
        raw = base64.b64decode(text, validate=True)
    except (ValueError, binascii.Error):
        return None
    return raw if len(raw) == SECRET_BYTES else None


def _secret(create: bool) -> bytes | None:
    """Секрет подписи. `create` — завести, если нет или не читается: зовут
    подписывающие (заказ страницы, событие лаунчера). Проверка заказа
    (`check`) не заводит никогда: свежий секрет посреди проверки скрыл бы,
    что прежний пропал."""
    p = _secret_path()
    if p is None:
        return None
    try:
        got = _unseal(p.read_text(encoding="utf-8").strip()) if p.exists() else None
    except OSError:
        got = None
    if got is not None or not create:
        return got
    # Нет или не читается (профиль перенесён с другой машины): секрет защищает
    # только заказы, данных за ним нет — заводим новый, старые заказы умрут.
    raw = secrets.token_bytes(SECRET_BYTES)
    blob = _seal(raw)
    if not blob:
        return None
    tmp = p.with_name(p.name + ".tmp")
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(blob)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
    except OSError:
        pathlib.Path(tmp).unlink(missing_ok=True)
        return None
    return raw


def _canon(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")


def _mac(secret: bytes, payload: dict) -> str:
    body = {k: v for k, v in payload.items() if k != "mac"}
    return hmac.new(secret, _canon(body), hashlib.sha256).hexdigest()


# ---------- отпечатки того, что исполнится ----------

def file_fp(p: pathlib.Path) -> str:
    """sha256 файла; '' — файла нет."""
    if not p.is_file():
        return ""
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def tree_fp(root: pathlib.Path, skip: tuple[str, ...] = ()) -> str:
    """Отпечаток папки: относительные пути и содержимое каждого файла.
    Подмена, добавление, удаление любого файла меняют его."""
    h = hashlib.sha256()
    if root.is_dir():
        for f in sorted(p for p in root.rglob("*") if p.is_file()):
            rel = f.relative_to(root).as_posix()
            if rel in skip:
                continue
            h.update(rel.encode("utf-8") + b"\0" + file_fp(f).encode() + b"\n")
    return h.hexdigest()


# ---------- заказ ----------

def sign(kind: str, **bound) -> dict | None:
    """Подписанный заказ: `kind`, номер, время и `bound` — то, к чему он
    привязан (отпечаток ключа, приёмки, блоба). None — подписать нечем
    (папки учётки нет, DPAPI отказал): заказ НЕ кладётся."""
    secret = _secret(create=True)
    if secret is None:
        return None
    order = {"v": 1, "kind": kind, "nonce": secrets.token_hex(16),
             "at": datetime.now().isoformat(timespec="seconds"), **bound}
    order["mac"] = _mac(secret, order)
    return order


def write(path: pathlib.Path, order: dict) -> None:
    """Заказ на диск атомарно: огрызок читался бы как чужой."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(order, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def read(path: pathlib.Path) -> dict | None:
    """Заказ с диска; None — не JSON-объект (в том числе пустой маркер и
    голый блоб прежних версий)."""
    try:
        got = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return got if isinstance(got, dict) else None


def _used_path() -> pathlib.Path | None:
    d = paths.user_dir()
    return d / USED_FILE if d is not None else None


def _used() -> list[str]:
    p = _used_path()
    try:
        got = json.loads(p.read_text(encoding="utf-8")) if p and p.exists() else []
    except (OSError, ValueError):
        got = []
    return [str(x) for x in got] if isinstance(got, list) else []


def spend(order: dict | None) -> None:
    """Номер заказа израсходован: исполнен или снят. Повтор того же файла
    (копия, сохранённая чужой учёткой) дальше не пройдёт."""
    nonce = str((order or {}).get("nonce") or "")
    p = _used_path()
    if not nonce or p is None:
        return
    used = [n for n in _used() if n != nonce][-(USED_KEEP - 1):] + [nonce]
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps(used), encoding="utf-8")
        os.replace(tmp, p)
    except OSError as e:
        log.warning("номер %s не записан: %r", nonce, e)


def check(order: dict | None, kind: str, **bound) -> str | None:
    """Почему заказ НЕ исполнять (слова для лога) или None — исполнять.
    `bound` — что лаунчер видит на диске сейчас; обязано совпасть с тем,
    что подписано."""
    if order is None:
        return "nu este semnată (format vechi sau fișier străin)"
    if paths.user_dir() is None:        # Windows не отдала папку учётки: в лог — paths
        return "folderul contului Windows nu a fost găsit"
    secret = _secret(create=False)
    if secret is None:
        return "contul Windows nu are cheie de semnare"
    if not hmac.compare_digest(str(order.get("mac") or ""), _mac(secret, order)):
        return "semnătura nu corespunde acestui cont Windows"
    if order.get("kind") != kind:
        return f"comanda este pentru {order.get('kind')!r}"
    if str(order.get("nonce") or "") in _used():
        return "comanda a fost deja folosită"
    for k, v in bound.items():
        if order.get(k) != v:
            return f"conținutul s-a schimbat după comandă ({k})"
    return None


def reject(data_dir: pathlib.Path, path: pathlib.Path, kind: str, why: str,
           also: tuple[pathlib.Path, ...] = ()) -> str:
    """Не исполнять: файл заказа и `also` (приёмка восстановления) — В
    СТОРОНУ, `<имя>.rejected-<дата>`, строка — в лог лаунчера, событие — для
    летописи и баннера. Возвращает строку для лога.
    ⛔ Ничего не удаляется: отвергнутым может оказаться и СВОЙ заказ
    (сделанный до 2.8.0, другой учёткой), а в нём ключ под DPAPI или
    принятая копия. Не отодвинулось (файл держат) — остаётся на месте:
    следующий старт отвергнет его снова, но не уничтожит."""
    stamp = time.strftime("%Y%m%d_%H%M%S")
    for p in (path, *also):
        try:
            if p.exists():
                os.replace(p, p.with_name(f"{p.name}.{REJECTED}-{stamp}"))
        except OSError as e:
            log.error("%s respinsă, dar %s nu s-a mutat deoparte: %r", kind, p.name, e)
    log.warning("%s respinsă: %s", kind, why)
    note(data_dir, kind, "rejected", why)
    return f"{kind}-rejected ({why})"


# ---------- что сделано: лаунчер → приложение ----------

def note(data_dir: pathlib.Path, kind: str, outcome: str, detail: str = "",
         nonce: str = "") -> None:
    """Событие для `report_done`: исполнено («done») или отвергнуто
    («rejected»). Подписано тем же секретом: папка общая, и поддельное
    «отвергнуто» рисовало бы директору тревогу на ровном месте.
    ⚠️ Секрет заводится и здесь: чужой заказ на машине, где владелец ещё
    ничего не заказывал, иначе отвергся бы молча, без баннера."""
    secret = _secret(create=True)
    if secret is None:
        return
    ev = {"kind": kind, "outcome": outcome, "detail": detail[:160],
          "nonce": nonce or secrets.token_hex(8),
          "at": datetime.now().isoformat(timespec="seconds")}
    ev["mac"] = _mac(secret, ev)
    p = data_dir / DONE_FILE
    got = read_events(p)
    if any(e.get("nonce") == ev["nonce"] for e in got):
        return                       # повторный проход после обрыва
    try:
        write(p, {"events": [*got, ev]})
    except OSError as e:
        log.warning("событие %s/%s не записано: %r", kind, outcome, e)


def read_events(p: pathlib.Path) -> list[dict]:
    got = read(p) or {}
    evs = got.get("events")
    return [e for e in evs if isinstance(e, dict)] if isinstance(evs, list) else []


def take_events(data_dir: pathlib.Path | None) -> list[dict]:
    """События лаунчера с ВЕРНОЙ подписью, один раз (файл снимается)."""
    if data_dir is None:
        return []
    p = data_dir / DONE_FILE
    if not p.exists():
        return []
    evs = read_events(p)
    p.unlink(missing_ok=True)
    secret = _secret(create=False)
    if secret is None:
        return []
    return [e for e in evs
            if hmac.compare_digest(str(e.get("mac") or ""), _mac(secret, e))]


def event_text(ev: dict, hint: bool = False) -> str:
    """Готовая строка летописи и баннера (летопись хранит строку навсегда).
    `hint` — у отказа подсказка «повторите» (только баннер: летопись
    отвечает «что было», и потолок у неё 200 знаков)."""
    from .layout import msg_text
    try:
        when = datetime.fromisoformat(str(ev.get("at"))).strftime("%d.%m.%Y %H:%M")
    except ValueError:
        when = "?"
    what = WHAT_RO.get(str(ev.get("kind")), str(ev.get("kind")))
    code = {("decrypt", "done"): "ord_decrypted",
            ("restore", "done"): "ord_restored"}.get(
        (str(ev.get("kind")), str(ev.get("outcome"))), "ord_rejected")
    base = msg_text(code)
    if code == "ord_rejected":
        line = f"{base}: {what} — {ev.get('detail') or '?'} ({when})"
        return f"{line}. {msg_text('ord_repeat')}" if hint else line
    if ev.get("detail"):
        return f"{base}: {ev.get('detail')} ({when})"
    return f"{base} ({when})"


async def report_done() -> None:
    """Старт приложения: события лаунчера — в летопись и баннер директору
    (канал «auth.json трогали»: висит до «Am luat la cunoștință»).
    Восстановление в летопись пишет `backup_loop.startup` (`restore.done`) —
    здесь от него только баннер."""
    from .. import db
    from . import auth
    from .storage import _data_dir
    evs = take_events(_data_dir())
    if not evs:
        return
    lines = []
    for ev in evs:
        text = event_text(ev)
        lines.append(event_text(ev, hint=True))
        if not (ev.get("kind") == RESTORE and ev.get("outcome") == "done"):
            await db.log_clinic_event(f"order_{ev.get('outcome')}", text)
    prev = await db.get_meta("auth_alert")
    alert = "; ".join([*([prev] if prev else []), *lines])
    await db.set_meta("auth_alert", alert)
    auth.set_tamper_alert(alert)
