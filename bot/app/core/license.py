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

Автообновление (L13): если в принятом файле есть `renew`, программа раз в
сутки спрашивает `renew.url` (провод — license_renew.py) и заменяет файл
ТОЛЬКО на тот, чей `seq` выше принятого, проверив его тем же `open_envelope`,
что и файл из письма. Сервера нет — программа живёт как жила: по файлу на
диске и по памяти. Кнопка «Verifică acum» на странице лицензии делает тот же
запрос сейчас.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import pathlib
from datetime import datetime, timedelta, timezone

from .. import db, paths
from . import license_renew as rn
from . import license_state as st
from . import rsa_verify

log = logging.getLogger("license")

FILE_NAME = "license.json"
STATE_NAME = "license.state"
ENV_KEYS = "DENTART_LICENSE_KEYS"
META_FIRST, META_SEEN, META_ACCEPTED = "lic_first", "lic_seen", "lic_accepted"
STATE_WRITE_EVERY = timedelta(days=1)      # last_seen пишется на старте и раз в сутки
READONLY_CODE = "license_readonly"         # код отказа: в MSG_BANNER, в ?msg= и в JSON
MISSING_CODE = "license_missing"           # то же для стены: файла нет, картотека пуста
# Адреса, открытые и за стеной: сама активация и всё, что нужно, чтобы до неё дойти
WALL_FREE = ("/admin/license", "/admin/login", "/admin/logout", "/admin/setup",
             "/admin/recover")
RENEW_EVERY = timedelta(days=1)            # суточный запрос к renew.url (L13)
RENEW_TIMEOUT = rn.TIMEOUT
# Исходы запроса — и коды баннера кнопки «Verifică acum» (MSG_BANNER в layout)
RENEWED, RENEW_SAME, RENEW_OFFLINE, RENEW_REFUSED, RENEW_BAD, RENEW_NONE = (
    "renewed", "same", "offline", "refused", "bad", "none")
RENEW_CODES = {RENEWED: "license_renewed", RENEW_SAME: "license_renew_same",
               RENEW_OFFLINE: "license_renew_offline", RENEW_REFUSED: "license_renew_refused",
               RENEW_BAD: "license_renew_bad", RENEW_NONE: "license_renew_none"}

_dir: pathlib.Path | None = None
_result: tuple[str, object | None] | None = None
_mem = st.Memory()
_status: st.Status | None = None
_patients = False
_written: datetime | None = None
_keys_present = False
_renew: dict = {"at": None, "outcome": "", "seq": 0}   # последняя попытка этого процесса
_renew_task: asyncio.Task | None = None
_renew_lock: asyncio.Lock | None = None


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
    global _dir, _result, _mem, _status, _patients, _written, _keys_present
    d = folder()
    if d is None:
        log.warning("лицензия: папка клиники не определена, проверка не ведётся")
        return None
    text = _read_file(d / FILE_NAME)
    table = keys()
    _keys_present = bool(table)
    result = None if text is None else rsa_verify.open_envelope(text, table)
    mem = st.merge(st.load(d / STATE_NAME), await _meta_memory())
    patients = (await db.patients_total()) > 0
    status, mem = st.evaluate(result, _now(), mem, patients)
    st.save(d / STATE_NAME, mem)
    await _meta_save(mem)
    _dir, _result, _mem, _status, _patients, _written = d, result, mem, status, patients, status.now
    _log(status)
    return status


def applies() -> bool:
    """Применяется ли лицензия вообще: только когда есть хоть один ключ выдачи.

    ⭐ Без единого ключа (запуск из исходников, песочница `dev up`, exe до
    первого боевого ключа L7) нет ни стены, ни баннера, ни отказов: файл
    взять неоткуда, и стена заперла бы каждую свежую установку без двери.
    Проверять поведение можно всегда — тесты подкладывают ключ окружением."""
    return _keys_present


def refuses(path: str, method: str) -> str:
    """Ворота записи (L4): код отказа для ЭТОГО запроса, '' — пропустить.
    Зовёт шлюз в main.py до маршрутизации — иначе 422 разбора тела опередил бы
    отказ, и клиника читала бы «неверные данные» там, где кончился абонемент.

    Чтение открыто всегда; облако, демо без ключа и запуск без ключей выдачи
    (`applies()`) ворот не видят; белый список — `license_state.READONLY_ALLOW`.
    За стеной (L5) запись отказывает тем же списком, но своим кодом: у свежей
    установки не «кончился абонемент», у неё нет файла."""
    if not st.gated(path, method):
        return ""
    s = current()
    if s is None or not applies() or st.allowed(path):
        return ""
    if s.wall:
        return MISSING_CODE
    return READONLY_CODE if s.state == st.READONLY else ""


def walled(path: str, method: str = "GET") -> bool:
    """Стена активации (L5): пустая картотека без годного файла — каждый адрес
    журнала ведёт на /admin/license, кроме тех, без которых до неё не дойти.
    Класс экрана — как у режима восстановления (`main.py`, `_recovery_gate`).
    ⚠️ Только чтение: запись за стеной отвечает `refuses()` своим кодом, чтобы
    форма не уезжала на активацию без объяснения."""
    if (method not in st.READ_METHODS or not path.startswith("/admin")
            or path.startswith(WALL_FREE)):
        return False
    s = current()
    return s is not None and applies() and s.wall


async def _put(text: str) -> st.Status | None:
    """Записать файл рядом с clinic.json атомарно и перечитать. None — не записан.
    Одна запись на оба пути — импорт со страницы и файл с сервера (L13)."""
    d = folder()
    if d is None:
        return None
    p = d / FILE_NAME
    tmp = p.with_name(p.name + ".tmp")
    try:
        tmp.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
        os.replace(tmp, p)
    except OSError as e:
        log.warning("лицензия: %s не записан: %r", p.name, e)
        return None
    return await refresh()


async def install(text: str) -> str:
    """Импорт файла со страницы активации: проверить, записать, перечитать.
    Возвращает код отказа или '' — файл лежит и принят."""
    if folder() is None:
        return rsa_verify.MALFORMED
    code, claim = rsa_verify.open_envelope(text, keys())
    if code:
        return code
    if _mem.accepted_seq and claim.seq < _mem.accepted_seq:
        return st.OLDER
    s = await _put(text)
    if s is None:
        return rsa_verify.MALFORMED
    if s.claim is not None:
        await db.log_clinic_event(
            "license", f"Licența a fost activată: valabilă până la "
                       f"{s.claim.valid_until.strftime('%d.%m.%Y')} (fișier {s.claim.seq})")
    return ""


# ---------- автообновление (L13) ----------


def renew_target() -> tuple[str, str] | None:
    """(url, token) из файла на диске или None: файла нет, или в нём нет `renew`.

    Берётся из результата проверки, а не из состояния: файл, отвергнутый как
    старее принятого, всё равно знает адрес, по которому лежит новый."""
    claim = _result[1] if _result is not None else None
    if claim is None or claim.renew is None:
        return None
    return claim.renew["url"], claim.renew["token"]


def last_renew() -> dict:
    """Последняя попытка автообновления в этом процессе: страница и /api/license."""
    return dict(_renew)


def _agent() -> str:
    from .. import engine as eng   # как в folder(): на уровне модуля замкнул бы круг
    return f"DentPilot/{eng.APP_VERSION}"


async def renew_once() -> str:
    """Один запрос к renew.url: исход из RENEW_*; RENEW_NONE — спрашивать некого.

    Файл заменяется ТОЛЬКО на seq выше принятого: ответ сервера проходит тот
    же `open_envelope` и то же правило, что файл из письма. Всё, что не «новый
    годный файл», оставляет диск и состояние как были — программа живёт по
    файлу, который у неё есть, и без сервера (cloud.md › «Пять запретов»).
    Сеть — в потоке, чтобы не держать цикл событий; замок — чтобы суточный
    запрос и кнопка не писали файл наперегонки."""
    global _renew_lock
    target = renew_target()
    if target is None or not applies():
        return RENEW_NONE
    if _renew_lock is None:
        _renew_lock = asyncio.Lock()
    async with _renew_lock:
        url, token = target
        had = _mem.accepted_seq
        outcome, text = await asyncio.to_thread(rn.fetch, url, token, had, RENEW_TIMEOUT, _agent())
        result = {rn.SAME: RENEW_SAME, rn.REFUSED: RENEW_REFUSED}.get(outcome, RENEW_OFFLINE)
        if outcome == rn.NEWER:
            code, claim = rsa_verify.open_envelope(text, keys())
            if code:
                result = RENEW_BAD
            elif claim.seq <= had:
                result = RENEW_SAME          # сервер прислал не новее: диск не трогаем
            else:
                s = await _put(text)
                if s is None or s.claim is None:
                    result = RENEW_BAD
                else:
                    result = RENEWED
                    await db.log_clinic_event(
                        "license", f"Licența a fost reînnoită automat: valabilă până la "
                                   f"{s.claim.valid_until.strftime('%d.%m.%Y')} (fișier {s.claim.seq})")
        _renew.update(at=_now(), outcome=result, seq=_mem.accepted_seq)
        # ⚠️ ASCII, как в _log: строку ищет тест в логе сервера на Windows.
        # «Новее нет» — суточная рутина, info; замена файла и всякий отказ —
        # warning, как состояния кроме active: сервер пишет лог с warning.
        (log.info if result == RENEW_SAME else log.warning)(
            "license: renew=%s seq=%d had=%d", result, _mem.accepted_seq, had)
        return result


async def _renew_loop() -> None:
    while True:
        try:
            await renew_once()
        except Exception as e:  # noqa: BLE001 — фон не имеет права умереть
            log.warning("license: renew failed: %r", e)
        await asyncio.sleep(RENEW_EVERY.total_seconds())


def renew_async() -> None:
    """Из хука старта main.py, после startup(): суточный запрос в фоне — тот же
    приём, что update.check_async: старт не ждёт, таймаут есть, отказ молчит
    (строкой в лог). Облако и демо без ключа — no-op."""
    global _renew_task
    if not db.IS_SQLITE or _renew_task is not None:
        return
    _renew_task = asyncio.get_running_loop().create_task(_renew_loop())


def as_json() -> dict:
    """Состояние для /api/license: клиенту и тестам."""
    s = current()
    if s is None or not applies():
        return {"applies": False}
    c = s.claim
    renew = None
    if renew_target() is not None:
        renew = {"at": st.fmt(_renew["at"]) if _renew["at"] else None,
                 "outcome": _renew["outcome"], "seq": _renew["seq"]}
    return {"applies": True, "state": s.state, "code": s.code, "wall": s.wall,
            "valid_until": st.fmt(s.valid_until) if s.valid_until else None,
            "grace_until": st.fmt(s.grace_until) if s.grace_until else None,
            "clinic": c.clinic if c else "", "plan": c.plan if c else "",
            "seq": _mem.accepted_seq, "renew": renew}


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
