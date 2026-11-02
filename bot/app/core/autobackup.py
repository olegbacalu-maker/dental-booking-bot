"""Автокопия базы — логика, вынесенная из лаунчера.

Копия dental.db при каждом запуске (через SQLite backup API — консистентно
даже после краха с WAL) в data/backups; хранение — ПО ДНЯМ (`doomed`). С 17.10 ту же
функцию раз в сутки зовёт и фоновый цикл приложения (`core/backup_loop`):
клиника, которая не выключает компьютер, неделями жила без свежей копии.
Отсюда PID в имени: копия лаунчера и копия цикла не пишут в один файл.

⭐ Если картотека зашифрована, копии тоже пишутся ПОД КЛЮЧОМ — в отличие от
вывозимого архива, который остаётся самодостаточным. Логика обратная той,
что была записана до шифрования («шифровать копии на месте — театр, они
лежат рядом с открытой базой»): теперь открытая копия рядом с зашифрованной
базой и есть дыра, ради которой всё затевалось. Роли разошлись: эти
файлы — откат на этой же машине, архив — переезд и беда.

⭐ Пишем во ВРЕМЕННОЕ имя и переименовываем только по успеху: упавший на
середине бэкап (диск полон, база залочена) оставлял частичный dental_*.db,
неотличимый по имени от настоящего, и ротация вытесняла им исправные
старые копии. В день, когда копия нужна, все они оказались бы мусором.
Имя-огрызок (.tmp) под маску ротации не попадает.

Хранение по дням (02.11, разбор коллеги перед первой клиникой): до того
держались 14 новейших ПО СЧЁТУ, а копия делается на каждый запуск и раз в
сутки — у клиники, которая включает программу 3–4 раза в день, история
кончалась на третьем-четвёртом дне, и испорченное в понедельник к четвергу
откатить было не на что. Теперь: новейшая копия каждого из KEEP_DAYS
последних дней, в которые копии были, плюс KEEP_RECENT новейших вообще.
Дни считаются по КОПИЯМ, а не по календарю: две недели отпуска не стирают
историю первым же запуском после него. Единственная копия дня из окна не
уходит, сколько бы запусков ни было потом.

⚠️ Модуль зовёт ЛАУНЧЕР (bot/desktop.py) до сборки приложения, поэтому
storage/db здесь не импортируются — только dbkey, живущий по тем же
правилам. Сам desktop.py тестами неимпортируем (его тело — запуск
программы), поэтому копирование живёт здесь, где его достаёт test_launcher.
"""
from __future__ import annotations

import os
import pathlib
import re
from datetime import datetime

from . import dbkey

KEEP_DAYS = 14          # по одной копии (новейшей) за столько дней с копиями
KEEP_RECENT = 3         # и столько новейших, какого бы дня они ни были
# Имя копии: dental_<ГГГГММДД>_<ЧЧММСС>_<PID>.db. Чужое имя по маске
# `dental_*.db` ротация не трогает: не её — не ей и удалять.
_NAME = re.compile(r"dental_(\d{8})_\d{6}_\d+\.db")


def doomed(names: list[str]) -> list[str]:
    """Какие копии снять: всё, кроме новейшей копии каждого из KEEP_DAYS
    последних дней и KEEP_RECENT новейших. Имена сортируются как время."""
    ours = sorted(n for n in names if _NAME.fullmatch(n))
    keep = set(ours[-KEEP_RECENT:])
    newest: dict[str, str] = {}
    for n in ours:                       # по возрастанию: последний — новейший дня
        newest[_NAME.fullmatch(n).group(1)] = n
    keep.update(newest[d] for d in sorted(newest)[-KEEP_DAYS:])
    return [n for n in ours if n not in keep]


def make_backup(data_dir: pathlib.Path) -> pathlib.Path | None:
    """Одна копия dental.db в data/backups + ротация по дням (`doomed`).

    Возвращает путь копии; None — базы ещё нет (первый запуск). Любой сбой —
    исключением наверх: решать, блокирует ли он старт, дело вызывающего.
    """
    src = data_dir / "dental.db"
    if not src.exists():
        return None
    import sqlite3
    bdir = data_dir / "backups"
    bdir.mkdir(exist_ok=True)
    # PID в имени: два одновременных старта не пишут в один файл бэкапа.
    # ⚠️ `datetime.now()`, не `time.strftime`: день копии решает ротация, и
    # его двигают поддельные часы прогона (`harness.Clock`), а `time` — нет.
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
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
    for name in doomed([f.name for f in bdir.glob("dental_*.db")]):
        (bdir / name).unlink(missing_ok=True)
    return dst_path
