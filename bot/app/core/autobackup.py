"""Автокопия базы при старте — логика, вынесенная из лаунчера.

Копия dental.db при каждом запуске (через SQLite backup API — консистентно
даже после краха с WAL), храним последние 14 в data/backups.

⭐ Если картотека зашифрована, копии тоже пишутся ПОД КЛЮЧОМ — в отличие от
вывозимого архива, который остаётся самодостаточным. Логика обратная той,
что была записана до шифрования («шифровать копии на месте — театр, они
лежат рядом с открытой базой»): теперь открытая копия рядом с зашифрованной
базой и есть дыра, ради которой всё затевалось. Роли разошлись: эти 14
файлов — откат на этой же машине, архив — переезд и беда.

⭐ Пишем во ВРЕМЕННОЕ имя и переименовываем только по успеху: упавший на
середине бэкап (диск полон, база залочена) оставлял частичный dental_*.db,
неотличимый по имени от настоящего, и ротация «14 новейших» вытесняла им
исправные старые копии. В день, когда копия нужна, все 14 оказались бы
мусором. Имя-огрызок (.tmp) под маску ротации не попадает.

⚠️ Модуль зовёт ЛАУНЧЕР (bot/desktop.py) до сборки приложения, поэтому
storage/db здесь не импортируются — только dbkey, живущий по тем же
правилам. Сам desktop.py тестами неимпортируем (его тело — запуск
программы), поэтому копирование живёт здесь, где его достаёт test_launcher.
"""
from __future__ import annotations

import os
import pathlib
import time

from . import dbkey

KEEP = 14


def make_backup(data_dir: pathlib.Path) -> pathlib.Path | None:
    """Одна копия dental.db в data/backups + ротация до KEEP файлов.

    Возвращает путь копии; None — базы ещё нет (первый запуск). Любой сбой —
    исключением наверх: решать, блокирует ли он старт, дело вызывающего.
    """
    src = data_dir / "dental.db"
    if not src.exists():
        return None
    import sqlite3
    bdir = data_dir / "backups"
    bdir.mkdir(exist_ok=True)
    # PID в имени: два одновременных старта не пишут в один файл бэкапа
    stamp = time.strftime("%Y%m%d_%H%M%S")
    dst_path = bdir / f"dental_{stamp}_{os.getpid()}.db"
    tmp_path = dst_path.with_name(dst_path.name + ".tmp")
    key = dbkey.load(data_dir) if dbkey.enabled(data_dir) else None
    if dbkey.enabled(data_dir) and key is None:
        # ключ не читается — копия штатным sqlite3 сделала бы мусорный
        # файл, который выглядит как бэкап. Лучше громко ничего не сделать.
        raise RuntimeError("cheia bazei nu poate fi citită")
    try:
        if key is not None:
            import sqlcipher3.dbapi2 as sqlcipher
            pragma = dbkey.pragma_value(key)
            src_c = sqlcipher.connect(str(src))
            try:
                src_c.execute(f"PRAGMA key = {pragma}")
                src_c.execute(f"ATTACH DATABASE ? AS bk KEY {pragma}",
                              (str(tmp_path),))
                src_c.execute("SELECT sqlcipher_export('bk')")
                src_c.execute("DETACH DATABASE bk")
            finally:
                src_c.close()
        else:
            src_c = sqlite3.connect(str(src))
            dst_c = sqlite3.connect(str(tmp_path))
            try:
                with dst_c:
                    src_c.backup(dst_c)
            finally:
                src_c.close()
                dst_c.close()
        os.replace(tmp_path, dst_path)
    except BaseException:
        # соединения уже закрыты (finally выше) — огрызок можно снять
        tmp_path.unlink(missing_ok=True)
        raise
    for f in sorted(bdir.glob("dental_*.db"))[:-KEEP]:
        f.unlink(missing_ok=True)
    return dst_path
