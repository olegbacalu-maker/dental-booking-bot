"""Ключ шифрования картотеки: где лежит, как переживает переезд, как читается.

Решение 08-09 (Олег, после разбора трёх вариантов): ключ СЛУЧАЙНЫЙ, лежит
рядом с базой под DPAPI, и у клиники на руках печатный лист восстановления.

Почему не иначе — обе отвергнутые ветки стоит помнить, их будут предлагать
снова:

⛔ **Ключ из PIN.** Соблазнительно («на диске ничего нет»), но: забытый PIN =
   картотека потеряна навсегда, а нынешний путь «забыл PIN → удалить
   auth.json» перестал бы работать. Плюс 4–6 цифр — это миллион вариантов,
   перебираемых по унесённому файлу оффлайн, то есть шифрование оказалось бы
   слабее, чем выглядит. И база не открывалась бы до входа человека —
   напоминания и бот не смогли бы работать с утра сами.
⛔ **Ключ просто файлом рядом.** Это ровно та ловушка, которую программа сама
   громко ругает у BitLocker кодом 8: «зашифровано, но ключ лежит рядом».
   Писать в своём коде то, за что ругаешь чужую настройку, нельзя.

⚠️ Что даёт выбранный вариант ЧЕСТНО: унесённый файл базы мёртв — на другой
   машине или под другой учёткой Windows DPAPI ключ не отдаст. Чего он НЕ
   даёт: защиты от того, кто сидит за этим же компьютером под этой же учёткой.
   Программа работает под ней, значит всё, что расшифровывает она, расшифрует
   и он. Это граница local-first, и клинике надо говорить именно так.

⭐ И главное следствие, из-за которого лист восстановления не украшение:
   DPAPI умирает вместе с учёткой. Переустановка Windows, новый ПК, замена
   диска — и ключ не прочитать. Без листа это означало бы потерю картотеки, то
   есть ровно ту беду, ради предотвращения которой отвергли ключ из PIN.
   Поэтому включение шифрования ТРЕБУЕТ подтверждения, что лист сохранён.
"""
from __future__ import annotations

import base64
import binascii
import os
import pathlib
import secrets

from .. import dpapi

# ⚠️ `storage` НЕ импортируется в шапке намеренно: он тянет за собой `db`, а
# этот модуль зовёт ЛАУНЧЕР (`desktop.py`) — до того, как приложение собрано, и
# ровно из тех же соображений, по которым в корне `app/` лежат paths/dpapi.
# Отсюда же необязательный `data_dir` во всех функциях: лаунчер знает папку сам
# и не должен ради этого поднимать половину программы.

KEY_FILE = "db.key"
KEY_BYTES = 32                      # 256 бит — размер ключа SQLCipher

# Состояния, которые обязан различать интерфейс. «Нет» и «не читается» — разные
# беды: первое значит «шифрование выключено», второе — «база есть, ключ от неё
# остался на прошлой машине», и подсказки у них противоположные.
OFF, OK, UNREADABLE = "off", "ok", "unreadable"


def key_path(data_dir: pathlib.Path | None = None) -> pathlib.Path | None:
    """Рядом с самой базой. У облачного издания файловой базы нет — там None,
    и весь модуль превращается в «шифрование недоступно»."""
    if data_dir is None:
        from .storage import _data_dir
        data_dir = _data_dir()
    return (data_dir / KEY_FILE) if data_dir else None


def enabled(data_dir: pathlib.Path | None = None) -> bool:
    """Шифрование включено, если ключ лежит на месте. Отдельного флага в
    настройках НЕТ намеренно: флаг и файл разошлись бы, и программа полезла бы
    открывать зашифрованную базу как обычную (или наоборот)."""
    p = key_path(data_dir)
    return bool(p and p.exists())


def state(data_dir: pathlib.Path | None = None) -> str:
    if not enabled(data_dir):
        return OFF
    return OK if load(data_dir) is not None else UNREADABLE


def load(data_dir: pathlib.Path | None = None) -> bytes | None:
    """Ключ в открытом виде. None — файл есть, но не расшифровывается.

    ⚠️ Отличать «нет файла» от «не читается» обязан вызывающий: тихо вернуть
    None в обоих случаях значит показать «шифрование выключено» клинике,
    у которой на диске лежит зашифрованная база, — и она пойдёт включать его
    заново поверх."""
    p = key_path(data_dir)
    if not p or not p.exists():
        return None
    try:
        stored = p.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    raw = dpapi.unprotect(stored)
    if not raw:                     # None (чужая учётка) либо "" (пустой файл)
        return None
    try:
        key = base64.b64decode(raw, validate=True)
    except (ValueError, binascii.Error):
        return None
    return key if len(key) == KEY_BYTES else None


def store(key: bytes, data_dir: pathlib.Path | None = None) -> bool:
    """Записать ключ под DPAPI. Запись атомарная — оборванная на середине
    оставила бы огрызок, а это неотличимо от «ключ не читается»."""
    p = key_path(data_dir)
    if not p or len(key) != KEY_BYTES:
        return False
    blob = dpapi.protect(base64.b64encode(key).decode())
    if not blob:
        return False               # не Windows или DPAPI отказал
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
        return False
    return True


def generate() -> bytes:
    return secrets.token_bytes(KEY_BYTES)


# ---------- лист восстановления ----------

# Base32 без набивки. Ценно тут не отсутствие букв O и I — они как раз есть, —
# а отсутствие ЦИФР 0, 1, 8 и 9: именно поэтому «O» в коде можно прочитать
# только как букву, а «1» не с чем спутать, потому что единицы там не бывает.
# 32 байта дают 52 знака; режем по 6, как в листе BitLocker: этот вид клиника
# уже видела и знает, что его надо убрать в папку, а не в ящик стола.
_GROUP = 6


def format_recovery(key: bytes) -> str:
    s = base64.b32encode(key).decode().rstrip("=")
    return "-".join(s[i:i + _GROUP] for i in range(0, len(s), _GROUP))


def parse_recovery(text: str) -> bytes | None:
    """Код с бумаги -> ключ. None, если это вообще не код.

    Пробелы, переносы, дефисы и регистр прощаются: человек переписывает вручную
    и почти наверняка введёт иначе, чем напечатано. А вот подставлять похожие
    буквы (0→O) НЕ надо: в алфавите base32 их нет, и «исправление» превратило
    бы опечатку в другой валидный ключ, который откроет базу пустой ошибкой
    вместо честного «код неверный»."""
    cleaned = "".join(ch for ch in (text or "").upper()
                      if ch.isalnum())
    if not cleaned:
        return None
    pad = "=" * (-len(cleaned) % 8)
    try:
        key = base64.b32decode(cleaned + pad, casefold=False)
    except (ValueError, binascii.Error):
        return None
    return key if len(key) == KEY_BYTES else None


# ---------- как ключ попадает в SQLCipher ----------

def _tables(con) -> list[str]:
    return [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()]


def _counts(con) -> dict[str, int]:
    return {t: con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            for t in _tables(con)}


def convert(src: pathlib.Path, key: bytes | None,
            was: bytes | None = None) -> dict[str, int]:
    """Перевести базу на месте: открытую → под ключ (`key`) или обратно (None).

    Возвращает число строк по таблицам — вызывающий обязан на них посмотреть.

    ⚠️ Порядок шагов здесь — единственное, что стоит между клиникой и потерей
    картотеки, поэтому он именно такой:
      1. пишем в ОТДЕЛЬНЫЙ файл, оригинал не трогаем вообще;
      2. закрываем, открываем НОВЫЙ файл заново и пересчитываем строки во всех
         таблицах — «экспорт не упал» и «данные на месте» это разные
         утверждения, и верить надо второму;
      3. только теперь os.replace — атомарная замена: на диске в любой момент
         лежит либо целый старый файл, либо целый новый.
    ⚠️ Вызывать, когда базу НИКТО не держит открытой: рядом живут -wal и -shm,
    и подмена файла под работающим соединением даёт повреждение, которое
    всплывёт часы спустя. Отсюда же — переезд делает лаунчер до старта
    приложения, а не страница настроек на ходу.
    """
    import sqlcipher3.dbapi2 as sqlcipher

    tmp = src.with_name(src.name + ".convert.tmp")
    tmp.unlink(missing_ok=True)
    con = sqlcipher.connect(str(src))
    try:
        if was is not None:
            con.execute(f"PRAGMA key = {pragma_value(was)}")
        before = _counts(con)
        target = pragma_value(key) if key is not None else "''"
        con.execute(f"ATTACH DATABASE ? AS conv KEY {target}", (str(tmp),))
        con.execute("SELECT sqlcipher_export('conv')")
        con.execute("DETACH DATABASE conv")
    finally:
        con.close()

    check = sqlcipher.connect(str(tmp))
    try:
        if key is not None:
            check.execute(f"PRAGMA key = {pragma_value(key)}")
        after = _counts(check)
    finally:
        check.close()
    if after != before:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"conversia bazei nu se confirmă: {before} -> {after}")

    # WAL прежнего файла к новому отношения не имеет: он описывает страницы,
    # которых там больше нет. Оставленный рядом, он при первом же открытии
    # «докатится» поверх и испортит базу.
    for suffix in ("-wal", "-shm"):
        src.with_name(src.name + suffix).unlink(missing_ok=True)
    os.replace(tmp, src)
    return after


# Отложенный переезд. Базу нельзя переводить под открытым соединением: рядом
# живут -wal и -shm, и подмена файла на ходу даёт повреждение, которое всплывёт
# часами позже. Поэтому страница настроек только ЗАКАЗЫВАЕТ переезд, а делает
# его лаунчер до старта приложения — тем же приёмом, что уже работает для
# токена бота и сетевого доступа.
PENDING_FILE = "db-key.pending"      # новый ключ ждёт применения = «включить»
DECRYPT_FILE = "db-decrypt.request"  # пустой маркер = «выключить»


def opens_with(src: pathlib.Path, key: bytes | None) -> bool:
    """Открывается ли база этим ключом (None — как обычная, без шифрования).

    Нужна не для красоты: по ней `apply_pending` понимает, ЧТО уже сделано, и
    переживает обрыв питания на любом шаге."""
    import sqlcipher3.dbapi2 as sqlcipher
    if not src.exists():
        return False
    con = sqlcipher.connect(str(src))
    try:
        if key is not None:
            con.execute(f"PRAGMA key = {pragma_value(key)}")
        con.execute("SELECT count(*) FROM sqlite_master").fetchone()
        return True
    except Exception:                                    # noqa: BLE001
        return False
    finally:
        con.close()


def apply_pending(data_dir: pathlib.Path, db_name: str = "dental.db") -> str | None:
    """Выполнить заказанный переезд. Возвращает что сделано или None.

    ⭐ Идемпотентна и смотрит на СОСТОЯНИЕ ФАЙЛА, а не на флаг. Если питание
    пропало между «база уже зашифрована» и «ключ уложен на место», следующий
    запуск обязан доделать, а не пытаться зашифровать зашифрованное — второй
    проход по флагу убил бы картотеку. Отсюда порядок: сначала смотрим, чем
    база открывается СЕЙЧАС, и делаем только недостающий шаг.
    """
    src = data_dir / db_name
    pending, decrypt = data_dir / PENDING_FILE, data_dir / DECRYPT_FILE

    if pending.exists():
        blob = pending.read_text(encoding="utf-8").strip()
        raw = dpapi.unprotect(blob)
        key = None
        if raw:
            try:
                cand = base64.b64decode(raw, validate=True)
                key = cand if len(cand) == KEY_BYTES else None
            except (ValueError, binascii.Error):
                key = None
        if key is None:
            pending.unlink(missing_ok=True)
            return "pending-unreadable"
        if not opens_with(src, key):          # ещё не переезжали
            convert(src, key)
        # ⛔ Прежние ежедневные копии — это ПОЛНАЯ картотека открытым текстом,
        # и лежат они рядом с только что зашифрованной базой. Оставить их —
        # ровно тот театр, за который программа ругает BitLocker кодом 8, да
        # ещё и экран настроек утверждает, что копии зашифрованы. Переводим их
        # тем же ключом, а не удаляем: это откат клиники на вчера, терять его
        # ради чистоты нельзя. Не переехавшую копию оставляем и говорим о ней.
        stale = []
        for old in sorted((data_dir / "backups").glob("dental_*.db")):
            if opens_with(old, key):
                continue
            try:
                convert(old, key)
            except Exception:                            # noqa: BLE001
                stale.append(old.name)
        os.replace(pending, data_dir / KEY_FILE)
        decrypt.unlink(missing_ok=True)
        return "encrypted" + (f" (копии не переехали: {', '.join(stale)})"
                              if stale else "")

    if decrypt.exists():
        key = load(data_dir)
        if key is not None and not opens_with(src, None):
            convert(src, None, was=key)
        # ⛔ Ключ удаляем ТОЛЬКО убедившись, что база и правда открытая.
        # Безусловный unlink здесь был дырой на потерю картотеки (найдено
        # враждебным ревью 08-09): если DPAPI перестал отдавать ключ — сброс
        # пароля Windows, другой ПК, — расшифровка не происходит, а файл ключа
        # исчезал. Дальше `enabled()` говорит «шифрования нет», программа лезет
        # в зашифрованный файл штатным sqlite3, падает на старте, и экран
        # восстановления недостижим: его включает как раз наличие db.key.
        # Клиника с ПРАВИЛЬНЫМ листом на руках оставалась без входа.
        if opens_with(src, None):
            (data_dir / KEY_FILE).unlink(missing_ok=True)
            decrypt.unlink(missing_ok=True)
            return "decrypted"
        decrypt.unlink(missing_ok=True)
        return "decrypt-failed"
    return None


def load_pending(data_dir: pathlib.Path) -> bytes | None:
    """Ключ, ждущий применения, — чтобы напечатать лист ДО переезда."""
    p = data_dir / PENDING_FILE
    if not p.exists():
        return None
    raw = dpapi.unprotect(p.read_text(encoding="utf-8").strip())
    if not raw:
        return None
    try:
        key = base64.b64decode(raw, validate=True)
    except (ValueError, binascii.Error):
        return None
    return key if len(key) == KEY_BYTES else None


def request_encrypt(data_dir: pathlib.Path, key: bytes) -> bool:
    """Положить новый ключ в ожидание. Отдельный файл, а не сразу `db.key`:
    пока база ещё открытая, живой `db.key` заставил бы программу при следующем
    старте читать её как зашифрованную — и она не открылась бы вовсе."""
    p = data_dir / PENDING_FILE
    blob = dpapi.protect(base64.b64encode(key).decode())
    if not blob:
        return False
    try:
        p.write_text(blob, encoding="utf-8")
    except OSError:
        return False
    return True


def request_decrypt(data_dir: pathlib.Path) -> None:
    (data_dir / DECRYPT_FILE).write_text("", encoding="utf-8")


def pragma_value(key: bytes) -> str:
    """Значение для `PRAGMA key` и для `ATTACH … KEY`.

    Форма `x'<64 hex>'` — СЫРОЙ ключ: SQLCipher берёт эти байты как есть и не
    гоняет PBKDF2. Так и надо: ключ уже случайный на все 256 бит, а вывод из
    пароля нужен ровно тогда, когда энтропии не хватает.

    ⚠️ Наружные кавычки ДВОЙНЫЕ и обязательны. Без них `x'…'` — это блоб-литерал
    SQL: `PRAGMA key` его ещё проглотит, а `ATTACH … KEY` ответит «syntax
    error», и переезд базы упадёт на середине. Ключ должен приехать СТРОКОЙ,
    внутри которой написано `x'…'`, — по ней SQLCipher и опознаёт сырой ключ.
    Экранировать при этом нечего: внутри только шестнадцатеричные цифры."""
    return '"x\'' + key.hex() + '\'"'
