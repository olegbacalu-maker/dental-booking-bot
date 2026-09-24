"""Лицензия в программе: обвязка машины состояний (L3).

`license.json` и память `license.state` лежат в папке `clinic.json` — там же,
где логотип (`theme.logo_dir`) и будущий `device.json` (P7): переживают
переустановку, в архив не уезжают (белый список бэкапа их не знает). Зеркало
памяти — в `schema_meta`: файл памяти стереть проще, чем базу, а архив,
восстановленный на новой машине, приносит с собой и то, что программа уже
приняла.

Только настольное издание: у облака и демо без ключа файла нет и ворот (L4)
нет. `current()` там отвечает None, и вызывающий обязан читать это как
«лицензия не применяется», а не как «лицензии нет».

⚠️ Пустота картотеки берётся на старте и при `refresh()`, не на каждом
вопросе: стена активации (L5) держит пустую картотеку пустой, а импорт файла
идёт через `refresh()`.
"""
from __future__ import annotations

import json
import logging
import os
import pathlib
from datetime import datetime, timedelta, timezone

from .. import db, paths
from . import license_state as st
from . import rsa_verify

log = logging.getLogger("license")

FILE_NAME = "license.json"
STATE_NAME = "license.state"
ENV_KEYS = "DENTART_LICENSE_KEYS"
META_FIRST, META_SEEN, META_ACCEPTED = "lic_first", "lic_seen", "lic_accepted"
STATE_WRITE_EVERY = timedelta(days=1)      # last_seen пишется на старте и раз в сутки

_dir: pathlib.Path | None = None
_result: tuple[str, object | None] | None = None
_mem = st.Memory()
_status: st.Status | None = None
_patients = False
_written: datetime | None = None


def folder() -> pathlib.Path | None:
    """Папка `clinic.json`. Считает `eng.config_path()` — единственный
    вычислитель этого места, второй запрещён его же докстрингом."""
    from .. import engine as eng   # на уровне модуля замкнул бы круг engine -> core
    try:
        return eng.config_path().parent
    except (RuntimeError, KeyError, OSError):
        return None


def keys() -> dict:
    return st.keys_from(rsa_verify.KEYS, os.environ.get(ENV_KEYS, ""), paths.is_frozen())


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _read_file(p: pathlib.Path) -> str | None:
    """None — файла нет; '' — есть, но не читается (это «не годен», не «нет»)."""
    try:
        return p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as e:
        log.warning("лицензия: %s не читается: %r", p.name, e)
        return ""


async def _meta_memory() -> st.Memory:
    d = {"first_start": await db.get_meta(META_FIRST),
         "last_seen": await db.get_meta(META_SEEN)}
    try:
        d.update(json.loads(await db.get_meta(META_ACCEPTED) or "{}"))
    except ValueError:
        pass
    return st.from_dict(d)


async def _meta_save(mem: st.Memory) -> None:
    d = st.to_dict(mem)
    if d["first_start"]:
        await db.set_meta(META_FIRST, d["first_start"])
    if d["last_seen"]:
        await db.set_meta(META_SEEN, d["last_seen"])
    if mem.accepted_seq:
        await db.set_meta(META_ACCEPTED, json.dumps(
            {k: d[k] for k in ("accepted_seq", "valid_until", "grace_until")}))


def _log(s: st.Status) -> None:
    say = log.info if s.state == st.ACTIVE else log.warning
    # ⚠️ Строка ASCII намеренно: stderr сервера на Windows пишет в файл в кодовой
    # странице консоли, и кириллица в нём превращается в \uXXXX — тест, ищущий
    # состояние в логе, не нашёл бы его на раннере CI.
    say("license: state=%s code=%s seq=%d valid_until=%s grace_until=%s",
        s.state, s.code or "-", _mem.accepted_seq,
        st.fmt(s.valid_until) if s.valid_until else "-",
        st.fmt(s.grace_until) if s.grace_until else "-")


async def startup() -> None:
    """Из хука старта main.py, после db.init: облако и демо без ключа — no-op."""
    if not db.IS_SQLITE:
        return
    await refresh()


async def refresh() -> st.Status | None:
    """Перечитать файл и память, пересчитать, записать память. Старт и импорт (L5)."""
    global _dir, _result, _mem, _status, _patients, _written
    d = folder()
    if d is None:
        log.warning("лицензия: папка клиники не определена, проверка не ведётся")
        return None
    text = _read_file(d / FILE_NAME)
    result = None if text is None else rsa_verify.open_envelope(text, keys())
    mem = st.merge(st.load(d / STATE_NAME), await _meta_memory())
    patients = (await db.patients_total()) > 0
    status, mem = st.evaluate(result, _now(), mem, patients)
    st.save(d / STATE_NAME, mem)
    await _meta_save(mem)
    _dir, _result, _mem, _status, _patients, _written = d, result, mem, status, patients, status.now
    _log(status)
    return status


def current() -> st.Status | None:
    """Состояние в момент вопроса — для ворот (L4) и баннера (L5).

    Считается от кэша старта и НАСТОЯЩИХ часов, без диска: полночь, на
    которой кончился срок, видна первому же запросу. Память на диск уходит
    раз в сутки, чтобы пол часов рос и без перезапуска."""
    global _mem, _status, _written
    if _status is None or _dir is None:
        return None
    status, mem = st.evaluate(_result, _now(), _mem, _patients)
    _mem, _status = mem, status
    if _written is None or status.now - _written >= STATE_WRITE_EVERY:
        st.save(_dir / STATE_NAME, mem)
        _written = status.now
    return status
