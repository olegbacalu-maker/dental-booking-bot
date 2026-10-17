"""Копии картотеки по расписанию: локальная раз в сутки, внешняя раз в сутки.

До 17.10 копия делалась ТОЛЬКО при старте лаунчера (`desktop._auto_backup`),
то есть у клиники, которая не выключает компьютер, свежей копии не было
неделями, а о неудаче знал один лог. Посторонний разбор 17.10 назвал это
риском №1. Отсюда три решения этого модуля:

1. **Раз в сутки, пока программа запущена** — фоновая задача приложения по
   образцу `sms_loop`: тик раз в минуту, сама работа — в потоке
   (`asyncio.to_thread`), старт её не ждёт. Локальная копия — тем же
   `autobackup.make_backup`, что у лаунчера (`data\\backups`, 14 штук, под
   ключом картотеки). Внешняя — тем же `backup.write_encrypted`, что у кнопки
   «Exportă arhiva»: зашифрованный ZIP в папку, которую назвала клиника
   (второй диск, флешка, облачная папка), с ротацией по своему префиксу
   `dentpilot-auto-*` — ручные архивы в той же папке не трогаются.
2. **Неудача — не только в лог.** Строка в ленту клиники
   (`db.log_clinic_event`, ОДНА на полосу одинаковых отказов, не на каждый
   тик) и янтарный баннер директору (`layout._backup_banner`) — пока копия
   не удастся. Повтор после отказа — через полчаса, не через сутки: флешку
   вставят, папку подключат.
3. **Программа помнит дату последней удачной внешней копии** (`schema_meta`,
   `backup_ext_ok_at`) и показывает её ФАКТОМ в Setări › Copie de rezervă и в
   Stare sistem. Старше STALE_DAYS или не удалась — баннер.

Пароль внешней копии живёт в `dental.env` под DPAPI (как токен бота):
`password()` отличает «не задан» («») от «не читается на этой машине»
(None) — второе значит переустановку Windows или другую учётку, и экран
просит ввести пароль заново, а не молчит. Папка — в `clinic.json › backup`.

⚠️ Время — `datetime.now(timezone.utc)`: так его двигают поддельные часы
прогона (`harness.Clock`), и «сутки прошли» проверяется без ожидания.
⚠️ Отчёт лаунчера о выполненном восстановлении (`restore.take_done`) тоже
переписывается в ленту здесь, при старте: у лаунчера базы нет.
"""
from __future__ import annotations

import asyncio
import logging
import os
import pathlib
from datetime import datetime, timedelta, timezone

from .. import dpapi, envfile
from .. import engine as eng
from .. import db
from . import autobackup
from . import backup as bkp
from . import restore
from .storage import _data_dir

log = logging.getLogger("backup")

TICK = 60.0                                   # секунд между проходами
TICK_ENV = "DENTART_BACKUP_TICK_S"            # стенд: секунды вместо минуты
LOCAL_EVERY = timedelta(hours=24)
EXT_EVERY = timedelta(hours=24)
RETRY = timedelta(minutes=30)                 # после отказа — не ждать сутки
STALE_DAYS = 3                                # внешняя копия старше — баннер
KEEP_EXT = 7                                  # архивов в папке назначения
PASS_KEY = "DENTART_BACKUP_PASS"              # dental.env, под DPAPI
AUTO_PREFIX = "dentpilot-auto-"               # ротация трогает только свои
META_LOCAL = "backup_local_at"
META_LOCAL_ERR = "backup_local_err"
META_EXT_OK = "backup_ext_ok_at"
META_EXT_ERR = "backup_ext_err"
EVENT_FAIL = "backup_fail"                    # вид события ленты (card.ACT_ICON)
EVENT_RESTORE = "restore"

_task: asyncio.Task | None = None
_wake: asyncio.Event | None = None
_lock: asyncio.Lock | None = None
_s: dict = {"local_at": None, "local_err": "", "ext_ok_at": None, "ext_err": "",
            "ext_try_at": None, "local_try_at": None}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime | None) -> str:
    return d.isoformat(timespec="seconds") if d else ""


def _parse(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        d = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


# ---------- настройки ----------


def folder() -> str:
    """Папка назначения из clinic.json › backup.folder; пусто — не задана."""
    sec = (eng.CONFIG or {}).get("backup")
    return str((sec or {}).get("folder") or "").strip() if isinstance(sec, dict) else ""


def _env_file() -> pathlib.Path | None:
    p = os.environ.get("DENTART_ENV_FILE", "").strip()
    return pathlib.Path(p) if p else None


def password() -> str | None:
    """Пароль внешней копии: "" — не задан, None — есть, но не читается на
    этой машине (DPAPI другой учётки), иначе сам пароль."""
    raw = os.environ.get(PASS_KEY, "").strip()
    if not raw and (p := _env_file()) is not None and p.exists():
        try:
            raw = envfile.read_all(p).get(PASS_KEY, "").strip()
        except OSError:
            raw = ""
    if not raw:
        return ""
    return dpapi.unprotect(raw)


def set_password(pw: str) -> None:
    """В файл — шифротекст (dpapi), в окружение — открытый пароль: им дальше
    пользуется цикл. Без DPAPI (не Windows) — как есть, иначе у разработчика
    настройка не работала бы вовсе. OSError — файл не пишется."""
    p = _env_file()
    if p is None:
        raise OSError("DENTART_ENV_FILE nu este setat")
    envfile.set_value(p, PASS_KEY, (dpapi.protect(pw) or pw) if pw else "")
    os.environ[PASS_KEY] = pw


def configured() -> bool:
    return bool(folder()) and bool(password())


# ---------- состояние ----------


async def startup() -> None:
    """До первого тика: что программа помнила, и отчёт лаунчера о
    восстановлении — в ленту."""
    _s["local_at"] = _parse(await db.get_meta(META_LOCAL))
    _s["local_err"] = (await db.get_meta(META_LOCAL_ERR)) or ""
    _s["ext_ok_at"] = _parse(await db.get_meta(META_EXT_OK))
    _s["ext_err"] = (await db.get_meta(META_EXT_ERR)) or ""
    done = restore.take_done(_data_dir())
    if done is not None:
        await db.log_clinic_event(
            EVENT_RESTORE,
            f"Evidența a fost restaurată din copia {done.get('name') or '?'} "
            f"({done.get('patients', '?')} pacienți, {done.get('appointments', '?')} programări); "
            f"baza anterioară a rămas în folderul cu date: {done.get('aside') or '?'}")
        log.warning("restored from %s; previous db: %s", done.get("name"), done.get("aside"))


async def _remember(key: str, value: str) -> None:
    try:
        await db.set_meta(key, value)
    except Exception as e:                      # noqa: BLE001 — память не роняет цикл
        log.warning("backup: meta %s not saved: %r", key, e)


async def _fail(scope: str, text: str) -> None:
    """Отказ копии: лог, лента (одна строка на полосу одинаковых отказов),
    память — баннер живёт до первой удачи."""
    key = "local_err" if scope == "local" else "ext_err"
    log.warning("backup %s FAILED: %s", scope, text)
    if _s[key] != text:
        what = "Copia de rezervă zilnică" if scope == "local" else "Copia de rezervă externă"
        await db.log_clinic_event(EVENT_FAIL, f"{what} nu s-a făcut: {text}")
    _s[key] = text
    await _remember(META_LOCAL_ERR if scope == "local" else META_EXT_ERR, text)


def _local_last() -> datetime | None:
    """Когда была последняя локальная копия: память программы или новейший
    файл в `data\\backups` (копию при старте делает лаунчер, у него базы нет)."""
    best = _s["local_at"]
    d = _data_dir()
    if d is not None:
        for p in (d / "backups").glob(restore.LOCAL_GLOB) if (d / "backups").is_dir() else ():
            try:
                m = datetime.fromtimestamp(p.stat().st_mtime, timezone.utc)
            except OSError:
                continue
            if best is None or m > best:
                best = m
    return best


def _due(last: datetime | None, every: timedelta, tried: datetime | None, now: datetime) -> bool:
    if tried is not None and now - tried < RETRY:
        return False
    return last is None or now - last >= every


async def run_local() -> str | None:
    """Локальная копия сейчас. Возвращает текст отказа или None."""
    d = _data_dir()
    if d is None:
        return None
    _s["local_try_at"] = _now()
    try:
        made = await asyncio.to_thread(autobackup.make_backup, d)
    except Exception as e:                      # noqa: BLE001 — любой драйвер, диск
        text = str(e) or repr(e)
        await _fail("local", text)
        return text
    _s["local_at"] = _now()
    _s["local_err"] = ""
    await _remember(META_LOCAL, _iso(_s["local_at"]))
    await _remember(META_LOCAL_ERR, "")
    if made is not None:
        log.warning("backup local: %s", made.name)
    return None


def _write_external(d: pathlib.Path, dest_dir: pathlib.Path, pw: str) -> pathlib.Path:
    """Архив в папку назначения: временное имя, замена по успеху, ротация
    своих. Любой сбой — исключением наверх."""
    if not dest_dir.is_dir():
        raise OSError(f"folderul nu există sau nu este accesibil: {dest_dir}")
    stamp = datetime.now(eng.TZ).strftime("%Y%m%d_%H%M")
    final = dest_dir / f"{AUTO_PREFIX}{stamp}.zip"
    tmp = final.with_name(final.name + ".tmp")
    clinic = eng.config_path()
    try:
        bkp.write_encrypted(d, clinic if clinic.exists() else None, pw, tmp)
        os.replace(tmp, final)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    for old in sorted(dest_dir.glob(f"{AUTO_PREFIX}*.zip"))[:-KEEP_EXT]:
        old.unlink(missing_ok=True)
    return final


async def run_external() -> str | None:
    """Внешняя копия сейчас. Возвращает текст отказа или None (удача либо
    копия не настроена)."""
    d = _data_dir()
    dest = folder()
    if d is None or not dest:
        return None
    pw = password()
    _s["ext_try_at"] = _now()
    if pw is None:
        text = "parola arhivei nu poate fi citită pe acest calculator — reintroduceți-o"
        await _fail("ext", text)
        return text
    if not pw:
        text = "parola arhivei nu este setată"
        await _fail("ext", text)
        return text
    try:
        made = await asyncio.to_thread(_write_external, d, pathlib.Path(dest), pw)
    except Exception as e:                      # noqa: BLE001 — диск, папка, драйвер
        text = str(e) or repr(e)
        await _fail("ext", text)
        return text
    _s["ext_ok_at"] = _now()
    _s["ext_err"] = ""
    await _remember(META_EXT_OK, _iso(_s["ext_ok_at"]))
    await _remember(META_EXT_ERR, "")
    log.warning("backup external: %s", made)
    return None


async def tick() -> None:
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    async with _lock:
        now = _now()
        if _due(_local_last(), LOCAL_EVERY, _s["local_try_at"], now):
            await run_local()
        if folder() and _due(_s["ext_ok_at"], EXT_EVERY, _s["ext_try_at"], now):
            await run_external()


def _tick_seconds() -> float:
    try:
        return max(0.05, float(os.environ.get(TICK_ENV, "") or TICK))
    except ValueError:
        return TICK


async def _loop() -> None:
    global _wake
    _wake = asyncio.Event()
    while True:
        try:
            await tick()
        except Exception as e:                  # noqa: BLE001 — фон не имеет права умереть
            log.warning("backup: tick failed: %r", e)
        _wake.clear()
        try:
            await asyncio.wait_for(_wake.wait(), timeout=_tick_seconds())
        except asyncio.TimeoutError:
            pass


def start_async() -> None:
    """Из хука старта main.py, после `startup()`: цикл в фоне, как `sms_loop`."""
    global _task
    if _task is not None:
        return
    _task = asyncio.get_running_loop().create_task(_loop())


def wake() -> None:
    """Разбудить цикл: настройки сохранены — не ждать минуту."""
    if _wake is not None:
        _wake.set()


# ---------- экрану и баннеру ----------


def _fmt(d: datetime | None) -> str:
    return d.astimezone(eng.TZ).strftime("%d.%m.%Y %H:%M") if d else ""


def ext_stale(now: datetime | None = None) -> bool:
    """Внешняя копия настроена, но её нет или она старше STALE_DAYS."""
    if not folder():
        return False
    ok = _s["ext_ok_at"]
    return ok is None or ((now or _now()) - ok) >= timedelta(days=STALE_DAYS)


def alert() -> str:
    """Текст янтарной строки директору; пусто — всё в порядке."""
    if _s["local_err"]:
        return f"Copia de rezervă zilnică nu s-a făcut: {_s['local_err']}"
    if not folder():
        return ""
    if _s["ext_err"]:
        return f"Copia de rezervă externă nu s-a făcut: {_s['ext_err']}"
    if ext_stale():
        ok = _s["ext_ok_at"]
        if ok is None:
            return "Copia de rezervă externă încă nu s-a făcut"
        days = (_now() - ok).days
        return f"Ultima copie de rezervă externă are {days} zile ({_fmt(ok)})"
    return ""


def state() -> dict:
    """Что показать: папка, пароль, даты, отказы — ФАКТЫ, не описание."""
    pw = password()
    local_last = _local_last()
    return {
        "folder": folder(),
        "has_pass": bool(pw),
        "pass_unreadable": pw is None,
        "local_at": _fmt(local_last),
        "local_error": _s["local_err"],
        "ext_at": _fmt(_s["ext_ok_at"]),
        "ext_error": _s["ext_err"],
        "ext_stale": ext_stale(),
        "stale_days": STALE_DAYS,
        "keep": KEEP_EXT,
        "alert": alert(),
    }
