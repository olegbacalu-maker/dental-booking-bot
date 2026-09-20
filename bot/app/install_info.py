"""Что решил УСТАНОВЩИК: режим развёртывания и канал обновления.

Файл `install.json` лежит в `INSTALL_ROOT` (рядом с программой) и пишется
установщиком один раз. Читают его лаунчер и приложение.

⛔ Почему НЕ в `clinic.json`. Профиль клиники целиком уезжает в бэкап и по
инструкции из самого архива кладётся рядом с программой на ЛЮБОЙ машине —
вместе с ним переехал бы чужой режим. Вдобавок `clinic.json` правит сама
клиника через настройки, а режим меняется только переустановкой.

⛔ Почему НЕ в `dental.env`. Тот лежит в `DATA_ROOT` и доступен на запись всем
учётным записям машины; строка в текстовом файле не должна менять топологию
клиники. Та же причина, по которой `$DENTART_DATA_DIR` не берётся оттуда
(`paths.data_root`).

⭐ Канал обновления здесь — НАМЕРЕНИЕ, а не рабочее состояние. Рабочее живёт в
`dental.env`, и писатель у того файла ровно один — лаунчер. Он берёт отсюда
значение, когда создаёт `dental.env` ВПЕРВЫЕ. Смысл: канареечная машина не
должна молча возвращаться на `stable` после переустановки, а это случалось
дважды.

⚠️ Модуль предзагрузочного слоя: импортов проекта тут нет и быть не может —
его зовут до того, как собрано приложение.
"""
from __future__ import annotations

import json
import pathlib

NAME = "install.json"

MODE_DEFAULT = "standalone"
CHANNEL_DEFAULT = "stable"

# Режимы развёртывания — перечисление, а не флаги (см. deployment-modes.md).
MODES = ("standalone", "shared_pc", "clinic_server", "clinic_client")
CHANNELS = ("stable", "beta", "draft")


class InstallInfoError(Exception):
    """`install.json` есть, но прочитать его нельзя.

    ⛔ Отдельный тип, а не возврат значений по умолчанию. Умолчание здесь —
    это тихий откат канареечной машины на `stable` и тихий выбор режима
    `standalone` там, где установщик записал другой: обе беды выглядят как
    исправно работающая программа.
    """


def path(install_root: pathlib.Path) -> pathlib.Path:
    return install_root / NAME


def read(install_root: pathlib.Path) -> dict | None:
    """`{"mode": ..., "channel": ...}`, либо None, если файла НЕТ.

    ⭐ «Нет файла» и «файл битый» — РАЗНЫЕ исхода, и путать их нельзя.
    Отсутствие законно: запуск из исходников, прогон, песочница — установщик
    там не работал никогда. Битый файл законным не бывает: значит установщик
    работал, но сказать, что он решил, невозможно — и молча подставить
    умолчание значит соврать про режим и канал сразу.
    """
    p = path(install_root)
    if not p.exists():
        return None
    try:
        # ⚠️ utf-8-sig, а не utf-8: установщик пишет файл без BOM, но чужой
        # редактор (Блокнот) добавит его молча, и разбор JSON упадёт на
        # первом символе. Терпимость на чтении дешевле, чем поломка запуска
        # из-за того, что файл кто-то открыл и сохранил.
        raw = json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as e:
        raise InstallInfoError(f"{p}: {e}") from e
    if not isinstance(raw, dict):
        raise InstallInfoError(f"{p}: ожидался объект, получен {type(raw).__name__}")

    mode = raw.get("mode", MODE_DEFAULT)
    channel = raw.get("channel", CHANNEL_DEFAULT)
    # ⚠️ Неизвестное значение — тоже отказ, а не «возьмём умолчание». Опечатка
    # в `chanel` или `beta ` с пробелом обязана быть видна сразу, а не через
    # неделю вопросом «почему канарейка не обновляется».
    if mode not in MODES:
        raise InstallInfoError(f"{p}: режим {mode!r} не из {MODES}")
    if channel not in CHANNELS:
        raise InstallInfoError(f"{p}: канал {channel!r} не из {CHANNELS}")
    return {"mode": mode, "channel": channel}


def channel_line(info: dict | None) -> str:
    """Что дописать в ТОЛЬКО ЧТО созданный `dental.env`.

    ⭐ Отдельная чистая функция, а не три строки внутри лаунчера: тело
    `desktop.py` тестами неимпортируемо (харнесс поднимает `app.main` напрямую
    и лаунчер не исполняет ни строкой), и решение про канал осталось бы
    непроверяемым до самой установки.

    `stable` не пишем НАМЕРЕННО: это умолчание продукта, и строка о нём в файле
    клиники — лишний повод её править. Пустая строка означает «оставить как
    есть», а не «поставить stable».
    """
    if not info or info.get("channel", CHANNEL_DEFAULT) == CHANNEL_DEFAULT:
        return ""
    return ("# Canal de actualizare (pus de instalator):\n"
            f"DENTART_CHANNEL={info['channel']}\n")
