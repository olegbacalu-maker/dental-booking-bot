"""Восстановление картотеки из копии: приёмка, проверка, заказ лаунчеру.

До 17.10 восстановление было ТЕКСТОМ: инструкция с 7-Zip внутри архива
(`backup._readme`) — семь шагов, из которых два («удалить -wal/-shm»,
«удалить db.key») при ошибке дают пустой журнал без единой ошибки. Теперь
это кнопка «Restaurează din copie» (Setări › Copie de rezervă), а инструкция
осталась запасным путём на случай, когда программы нет.

Устройство — в три шага, и граница между ними несущая:

1. **Приёмка** (`stage_archive` / `stage_local`, зовёт страница настроек):
   копия распаковывается в `data\\restore-staging\\`, база проверяется
   ОТКРЫТИЕМ (число пациентов, визитов, документов, версия схемы), сводка
   ложится в `summary.json`. Ничего живого не тронуто: человек видит, ЧТО
   именно вернётся, прежде чем подтвердить.
2. **Заказ** (`request`): файл `restore.request` рядом с базой. Как у
   `dbkey.apply_pending`: страница только ЗАКАЗЫВАЕТ.
3. **Исполнение** (`apply_pending`, зовёт ЛАУНЧЕР до старта приложения):
   живая база уходит В СТОРОНУ с датой (`dental.before-restore-<дата>.db`,
   вместе со своими -wal/-shm), на её место встаёт принятая. ⛔ Подменять
   файл под открытым соединением нельзя: рядом живут -wal/-shm, и подмена
   на ходу даёт порчу, которая всплывает часами позже (прайор dbkey).
   Старое НЕ удаляется никогда: откат восстановления — переименовать обратно.

⭐ Шифрование картотеки восстановление переживает само: база из архива
открытая, и если на машине включено шифрование, лаунчер переводит её под
действующий ключ (`dbkey.convert`) — шаг «удалите db.key» из старой
инструкции больше не нужен. Локальная копия (`data\\backups`) лежит под тем
же ключом и переводится не должна; копию под ЧУЖИМ ключом приёмка отвергает.

⚠️ Состав, который принимается из архива, — БЕЛЫЙ СПИСОК имён, тот же, что
кладёт `backup.write_encrypted`: архив мог собрать кто угодно, и имя записи
на диск не ложится без проверки (`..`, абсолютные пути, чужие файлы —
пропускаются). Логотип клиники назван здесь по именам: `theme.LOGO_NAMES`
тянет за собой engine, которого у лаунчера нет; что списки не разошлись,
держит `test_backup`.

⚠️ Модуль зовёт ЛАУНЧЕР (bot/desktop.py) до сборки приложения, поэтому
storage/db/engine здесь не импортируются — только dbkey, живущий по тем же
правилам (держит `test_structure`: «модули копий импортируемы лаунчером»).
"""
from __future__ import annotations

import fnmatch
import json
import os
import pathlib
import shutil
import sqlite3
import time
import zipfile
from datetime import datetime

from . import dbkey

REQUEST_FILE = "restore.request"      # JSON-заказ: лаунчер исполняет на старте
DONE_FILE = "restore.done"            # лаунчер исполнил: приложение запишет в ленту
STAGE_DIR = "restore-staging"         # распакованная и проверенная копия
SUMMARY = "summary.json"
LOCAL_GLOB = "dental_*.db"            # маска локальных копий (autobackup)
ASIDE = "before-restore"              # dental.before-restore-<дата>.db

# Записи архива, которые принимаются (backup.write_encrypted кладёт ровно их)
ARC_DB = "data/dental.db"
ARC_CLINIC = "clinic.json"
ARC_AUTH = "data/auth.json"
ARC_FILES = "data/files/"
LOGO_NAMES = ("clinic-logo.png", "clinic-logo.jpg")


class RestoreError(Exception):
    """`code` — код MSG_BANNER (bad_rst_pass / bad_rst_file / bad_rst_src);
    `detail` — слова для лога, не для экрана."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


def stage_dir(data_dir: pathlib.Path) -> pathlib.Path:
    return data_dir / STAGE_DIR


def _reset_stage(data_dir: pathlib.Path) -> pathlib.Path:
    st = stage_dir(data_dir)
    if st.exists():
        shutil.rmtree(st)
    (st / "data").mkdir(parents=True)
    return st


def _safe_member(name: str) -> str | None:
    """Имя записи архива → путь внутри приёмки, или None (не наше / опасное)."""
    n = name.replace("\\", "/")
    parts = n.split("/")
    if n.startswith("/") or ".." in parts or ":" in n or not n:
        return None
    if n in (ARC_DB, ARC_CLINIC, ARC_AUTH) or n in LOGO_NAMES:
        return n
    if n.startswith(ARC_FILES) and not n.endswith("/") and len(parts) >= 3:
        return n
    return None


def inspect_db(path: pathlib.Path, key: bytes | None = None) -> dict:
    """Что внутри базы: пациенты, визиты, документы, версия схемы.

    Сигнатура проверяется ОТКРЫТИЕМ, не только заголовком: у копии под ключом
    заголовок — шифр, а «SQLite format 3» без таблицы `patients` — чужая
    база. Любой отказ — `RestoreError("bad_rst_file")`.
    """
    if key is None:
        try:
            with open(path, "rb") as f:
                head = f.read(16)
        except OSError as e:
            raise RestoreError("bad_rst_file", f"nu se citește: {e}") from e
        if not head.startswith(b"SQLite format 3"):
            raise RestoreError("bad_rst_file", "nu este o bază SQLite")
        con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    else:
        import sqlcipher3.dbapi2 as sqlcipher
        con = sqlcipher.connect(str(path))
        con.execute(f"PRAGMA key = {dbkey.pragma_value(key)}")
    out: dict = {}
    try:
        for t in ("patients", "appointments", "documents"):
            try:
                out[t] = int(con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0])
            except Exception as e:                       # noqa: BLE001 — любой драйвер
                raise RestoreError("bad_rst_file", f"lipsește tabelul {t}: {e}") from e
        try:
            v = con.execute("SELECT value FROM schema_meta WHERE key = 'version'").fetchone()
            out["schema"] = int(v[0]) if v and str(v[0]).isdigit() else 0
        except Exception:                                # noqa: BLE001
            out["schema"] = 0
    finally:
        con.close()
    return out


def _clinic_name(path: pathlib.Path) -> str:
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
        return str(cfg.get("name") or "")
    except (OSError, ValueError, AttributeError):
        return ""


def _write_summary(data_dir: pathlib.Path, summary: dict) -> dict:
    (stage_dir(data_dir) / SUMMARY).write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    return summary


def stage_archive(data_dir: pathlib.Path, zip_path: pathlib.Path, password: str) -> dict:
    """Принять вывозной архив (`backup.write_encrypted`): распаковать белый
    список в приёмку и прочитать базу. Возвращает сводку (она же ложится в
    `summary.json`). Неверный пароль — `bad_rst_pass`, не архив или не наша
    база — `bad_rst_file`, файла нет — `bad_rst_src`."""
    import pyzipper

    zip_path = pathlib.Path(zip_path)
    if not zip_path.is_file():
        raise RestoreError("bad_rst_src", f"nu există: {zip_path}")
    st = _reset_stage(data_dir)
    n_files = 0
    made = ""
    try:
        try:
            with pyzipper.AESZipFile(str(zip_path)) as z:
                z.setpassword(password.encode("utf-8"))
                names = z.namelist()
                if ARC_DB not in names:
                    raise RestoreError("bad_rst_file", "arhiva nu conține data/dental.db")
                dt = z.getinfo(ARC_DB).date_time
                made = datetime(*dt).strftime("%Y-%m-%d %H:%M")
                for name in names:
                    rel = _safe_member(name)
                    if rel is None:
                        continue
                    dst = st / rel
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        with z.open(name) as src, open(dst, "wb") as out:
                            shutil.copyfileobj(src, out)
                    except RuntimeError as e:          # pyzipper: Bad password
                        raise RestoreError("bad_rst_pass", str(e)) from e
                    if rel.startswith(ARC_FILES):
                        n_files += 1
        except zipfile.BadZipFile as e:
            raise RestoreError("bad_rst_file", f"nu este o arhivă ZIP: {e}") from e
        counts = inspect_db(st / ARC_DB, None)
    except BaseException:
        shutil.rmtree(st, ignore_errors=True)
        raise
    return _write_summary(data_dir, {
        "kind": "archive", "source": str(zip_path), "name": zip_path.name,
        "made": made, "files": n_files, "encrypted": False,
        "clinic": _clinic_name(st / ARC_CLINIC) if (st / ARC_CLINIC).exists() else "",
        **counts,
    })


def local_copies(data_dir: pathlib.Path) -> list[dict]:
    """Локальные копии `data\\backups` новейшими вперёд: имя, время, размер."""
    out = []
    bdir = data_dir / "backups"
    if not bdir.is_dir():
        return out
    for p in sorted(bdir.glob(LOCAL_GLOB), reverse=True):
        try:
            stt = p.stat()
        except OSError:
            continue
        made = _made_of(p.name, stt.st_mtime)
        out.append({"name": p.name, "made": made, "day": made[:10],
                    "size": stt.st_size})
    return out


def _made_of(name: str, mtime: float) -> str:
    """`dental_20261017_093000_1234.db` → «17.10.2026 09:30»; иначе mtime.
    Формат — как у дат клиники везде; `day` экрана — первые 10 знаков
    (история копий группируется по дням, 17.10 вечером)."""
    try:
        stamp = name.split("_", 2)[1] + name.split("_", 3)[2]
        return datetime.strptime(stamp, "%Y%m%d%H%M%S").strftime("%d.%m.%Y %H:%M")
    except (IndexError, ValueError):
        return datetime.fromtimestamp(mtime).strftime("%d.%m.%Y %H:%M")


def stage_local(data_dir: pathlib.Path, name: str, key: bytes | None) -> dict:
    """Принять локальную копию из `data\\backups`. `key` — действующий ключ
    картотеки (None — шифрования нет): копия обязана открываться им, иначе
    это копия с другой машины или под другим ключом — `bad_rst_file`."""
    if "/" in name or "\\" in name or not fnmatch.fnmatch(name, LOCAL_GLOB):
        raise RestoreError("bad_rst_src", f"nume nepermis: {name!r}")
    src = data_dir / "backups" / name
    if not src.is_file():
        raise RestoreError("bad_rst_src", f"nu există: {src}")
    st = _reset_stage(data_dir)
    try:
        shutil.copy2(src, st / ARC_DB)
        used = key
        if key is not None:
            if not dbkey.opens_with(st / ARC_DB, key):
                if not dbkey.opens_with(st / ARC_DB, None):
                    raise RestoreError("bad_rst_file",
                                       "copia nu se deschide cu cheia acestui calculator")
                used = None               # копия до включения шифрования — открытая
        counts = inspect_db(st / ARC_DB, used)
    except BaseException:
        shutil.rmtree(st, ignore_errors=True)
        raise
    return _write_summary(data_dir, {
        "kind": "local", "source": str(src), "name": name,
        "made": _made_of(name, src.stat().st_mtime), "files": 0,
        "encrypted": used is not None, "clinic": "", **counts,
    })


def summary(data_dir: pathlib.Path) -> dict | None:
    """Принятая копия, ждущая подтверждения (или уже заказанная)."""
    st = stage_dir(data_dir)
    if not (st / SUMMARY).exists() or not (st / ARC_DB).exists():
        return None
    try:
        return json.loads((st / SUMMARY).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def pending(data_dir: pathlib.Path) -> bool:
    return (data_dir / REQUEST_FILE).exists()


def request(data_dir: pathlib.Path) -> bool:
    """Заказать восстановление принятой копии. False — принимать нечего."""
    s = summary(data_dir)
    if s is None:
        return False
    (data_dir / REQUEST_FILE).write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")
    return True


def cancel(data_dir: pathlib.Path) -> None:
    """Снять заказ и выбросить принятое."""
    (data_dir / REQUEST_FILE).unlink(missing_ok=True)
    st = stage_dir(data_dir)
    if st.exists():
        shutil.rmtree(st)


def _opens_plain(path: pathlib.Path) -> bool:
    try:
        con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            con.execute("SELECT count(*) FROM sqlite_master").fetchone()
            return True
        finally:
            con.close()
    except sqlite3.Error:
        return False


def _forget_auth_fp(db_path: pathlib.Path, key: bytes | None) -> None:
    """Снять из восстановленной базы отпечаток auth.json: база помнит файл
    ТОГО момента, а на диске может лежать другой (локальная копия без
    auth.json, PIN сменён позже) — и первый старт поднял бы ложную тревогу
    «auth.json трогали вне программы». Без отпечатка старт запоминает файл
    заново молча (`entry.check_auth_file`). Отказ — не беда: самое худшее,
    тревога один раз, и директор её гасит."""
    try:
        if key is None:
            con = sqlite3.connect(str(db_path))
        else:
            import sqlcipher3.dbapi2 as sqlcipher
            con = sqlcipher.connect(str(db_path))
            con.execute(f"PRAGMA key = {dbkey.pragma_value(key)}")
        try:
            con.execute("DELETE FROM schema_meta WHERE key = 'auth_fp'")
            con.commit()
        finally:
            con.close()
    except Exception:                                    # noqa: BLE001
        pass


def _relink_documents(db_path: pathlib.Path, key: bytes | None, data_dir: pathlib.Path) -> int:
    """Документы пациентов лежат в базе АБСОЛЮТНЫМ путём (`stored_path`,
    patients/routes), то есть путём ТОЙ машины. Восстановленная в другую папку
    (новый ПК, другая раскладка) база называла бы файлы, которых здесь нет, и
    фиша показывала бы «lipsește pe disc» при целых файлах в `files\\` — так
    терялись документы и у ручной инструкции с 7-Zip. Путь перевязывается по
    хвосту после `files`: `…\\files\\<nr>\\<hex>` → `<data_dir>\\files\\<nr>\\<hex>`,
    и только там, где старого пути нет, а новый есть. Возвращает число
    перевязанных; отказ — ноль (документы останутся потерянными, не база)."""
    try:
        if key is None:
            con = sqlite3.connect(str(db_path))
        else:
            import sqlcipher3.dbapi2 as sqlcipher
            con = sqlcipher.connect(str(db_path))
            con.execute(f"PRAGMA key = {dbkey.pragma_value(key)}")
        n = 0
        try:
            rows = con.execute("SELECT id, stored_path FROM documents").fetchall()
            for doc_id, old in rows:
                old = str(old or "")
                if not old or pathlib.Path(old).exists():
                    continue
                parts = old.replace("\\", "/").split("/")
                if "files" not in parts:
                    continue
                tail = parts[len(parts) - 1 - parts[::-1].index("files") + 1:]
                new = data_dir.joinpath("files", *tail)
                if new.exists():
                    con.execute("UPDATE documents SET stored_path = ? WHERE id = ?",
                                (str(new), doc_id))
                    n += 1
            con.commit()
        finally:
            con.close()
        return n
    except Exception:                                    # noqa: BLE001
        return 0


def apply_pending(data_dir: pathlib.Path, clinic_root: pathlib.Path | None = None,
                  db_name: str = "dental.db") -> str | None:
    """Исполнить заказ (зовёт лаунчер ДО старта приложения и ДО автокопии).
    Возвращает, что сделано, или None — заказа нет.

    ⭐ Смотрит на СОСТОЯНИЕ файлов, а не только на флаг (как dbkey): заказ без
    принятой базы — уже исполнен (обрыв после подмены) или приёмку снесли
    руками; тогда заказ снимается, а не исполняется наполовину.
    """
    req = data_dir / REQUEST_FILE
    if not req.exists():
        return None
    st = stage_dir(data_dir)
    staged = st / ARC_DB
    if not staged.exists():
        req.unlink(missing_ok=True)
        shutil.rmtree(st, ignore_errors=True)
        return "restore-nothing"
    try:
        s = json.loads(req.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        s = {}

    key = None
    if dbkey.enabled(data_dir):
        key = dbkey.load(data_dir)
        if key is None:
            # ключ не читается на этой учётке — режим восстановления объяснит;
            # заказ ждёт, принятая копия остаётся
            return "restore-key-unreadable"
        if not dbkey.opens_with(staged, key):
            if not dbkey.opens_with(staged, None):
                cancel(data_dir)
                return "restore-bad-db"
            dbkey.convert(staged, key)        # архив открытым текстом → под ключ
    elif not _opens_plain(staged):
        cancel(data_dir)
        return "restore-bad-db"

    stamp = time.strftime("%Y%m%d_%H%M%S")
    live = data_dir / db_name
    aside = f"dental.{ASIDE}-{stamp}.db"
    if live.exists():
        os.replace(live, data_dir / aside)
    # -wal/-shm принадлежат СТАРОЙ базе: оставленные рядом, они «докатились» бы
    # поверх восстановленной — уезжают вместе с ней, под её новым именем
    for suf in ("-wal", "-shm"):
        w = data_dir / (db_name + suf)
        if w.exists():
            os.replace(w, data_dir / (aside + suf))
    os.replace(staged, live)
    _forget_auth_fp(live, key)

    sa = st / ARC_AUTH
    if sa.exists():
        la = data_dir / "auth.json"
        if la.exists():
            os.replace(la, data_dir / f"auth.{ASIDE}-{stamp}.json")
        os.replace(sa, la)
    sf = st / "data" / "files"
    if sf.is_dir():
        for f in sorted(sf.rglob("*")):
            if f.is_file():
                dst = data_dir / "files" / f.relative_to(sf)
                dst.parent.mkdir(parents=True, exist_ok=True)
                os.replace(f, dst)
    relinked = _relink_documents(live, key, data_dir)
    if clinic_root is not None:
        sc = st / ARC_CLINIC
        if sc.exists():
            lc = clinic_root / "clinic.json"
            if lc.exists():
                os.replace(lc, clinic_root / f"clinic.{ASIDE}-{stamp}.json")
            os.replace(sc, lc)
        for n in LOGO_NAMES:
            if (st / n).exists():
                os.replace(st / n, clinic_root / n)

    req.unlink(missing_ok=True)
    shutil.rmtree(st, ignore_errors=True)
    done = {**s, "aside": aside, "relinked": relinked,
            "at": datetime.now().isoformat(timespec="seconds")}
    try:
        (data_dir / DONE_FILE).write_text(json.dumps(done, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return f"restored {s.get('name', '?')} ({s.get('patients', '?')} pacienți; vechea bază: {aside})"


def take_done(data_dir: pathlib.Path | None) -> dict | None:
    """Отчёт лаунчера об исполненном восстановлении — ОДИН раз (файл
    снимается): приложение переписывает его в ленту клиники."""
    if data_dir is None:
        return None
    p = data_dir / DONE_FILE
    if not p.exists():
        return None
    try:
        out = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        out = {}
    p.unlink(missing_ok=True)
    return out if isinstance(out, dict) else {}
