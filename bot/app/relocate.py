"""P2, шаги 1–3: Detect → Fingerprint → Decide. ⛔ НИ ОДНОГО ЗАПИСАННОГО БАЙТА.

Контракт целиком — `docs/dentpilot-2/migration-contract.md`. Здесь ровно первая
треть восьмёрки: решить, надо ли переезжать и можно ли. Копирование, проверка,
перезапись `stored_path` и переключение (шаги 4–8) живут отдельно и приходят
позже — до тех пор этот модуль безопасен по построению, а не по аккуратности.

⭐ **Почему `relocate`, а не `migrate`.** В продукте слово «миграция» уже занято
схемой базы (`db.py`, `schema_meta`), и второй смысл у того же имени — ровно та
ловушка, которую карта называет «одно состояние — одно имя». Здесь переезд
ПАПОК, к схеме отношения не имеющий.

⛔ **Источник не открывается никаким драйвером.** Ни `sqlite3`, ни `sqlcipher3`,
ни `dbkey.opens_with`: последний открывает файл на запись, а его закрытие делает
checkpoint — то есть тратит тот самый отпечаток, который мы снимаем. Всё, что
знает этот модуль, получено из метаданных файлов и первых 16 байт заголовка.

⚠️ Отсюда предел, названный вслух: **числа пациентов на экране раздвоения этот
слой дать не может.** Контракт хочет показать его человеку, но счёт живёт
внутри базы, а базу мы не открываем. Либо экран обходится файловыми фактами
(даты, размеры, кто назван в `install.json`), либо кто-то принимает отдельное
решение открыть источник `immutable=1` — это доказуемо не запись, но это ДРУГОЕ
решение, и принимать его молча здесь нельзя.

⚠️ «Программа запущена» — предусловие ШАГА 4, а не этого слоя: здесь мы ничего
не трогаем, поэтому запущенная программа ничему не мешает. ⛔ Но к копированию
она обязана быть проверена, и проверена положительным признаком, а не наличием
`-shm`: лаунчер заканчивает работу `os._exit(0)`, и `-shm` рядом с остывшей
базой — норма, а не признак жизни.

⚠️ Модуль предзагрузочного слоя: из проекта только `legacy` и `paths` — тот же
слой. Импорт чего-либо выше (`db`, `engine`, `core.*`) сделал бы решение о
раскладке зависимым от приложения, которого в этот момент ещё нет.
"""
from __future__ import annotations

import hashlib
import os
import pathlib

from . import legacy

# Заголовок незашифрованной базы. SQLCipher шифрует ПЕРВУЮ страницу целиком,
# поэтому отличить одно от другого можно не открывая файл.
SQLITE_MAGIC = b"SQLite format 3\x00"

DB_REL = os.path.join("data", "dental.db")

# ⛔ Приказы шифрования. Их наличие — причина отказа, а не деталь отчёта:
# переезд поверх незавершённого приказа разошёлся бы с печатным листом
# восстановления, который клинике уже отдан на руки.
ORDERS = (os.path.join("data", "db-key.pending"),
          os.path.join("data", "db-decrypt.request"))


def _stat(p: pathlib.Path) -> tuple[int, float] | None:
    try:
        st = p.stat()
    except OSError:
        return None
    return st.st_size, st.st_mtime


def _sha256(p: pathlib.Path) -> str | None:
    h = hashlib.sha256()
    try:
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def fingerprint(root: pathlib.Path, digest: bool = False) -> dict:
    """Что известно о корне БЕЗ его открытия.

    `digest=False` по умолчанию, и это не экономия ради экономии: решение
    шага 3 хеша не требует, а считается он по всей базе. Снимать его на каждом
    запуске значило бы платить чтением всей картотеки за вопрос, на который
    отвечают размер и дата. Хеш нужен шагу 5 (Verify) — там и просить.

    Возвращает словарь, пригодный и для решения, и для показа человеку:
    `has_db`, `db_size`, `db_mtime`, `encrypted`, `wal`, `markers`, `orders`.
    """
    root = pathlib.Path(root)
    db = root / DB_REL
    st = _stat(db)
    wal = _stat(root / (DB_REL + "-wal"))
    head = b""
    if st is not None:
        try:
            with open(db, "rb") as f:
                head = f.read(len(SQLITE_MAGIC))
        except OSError:
            head = b""
    out = {
        "root": root,
        "has_db": st is not None,
        "db_size": st[0] if st else 0,
        "db_mtime": st[1] if st else None,
        # ⚠️ None, а не False, когда базы нет: «не зашифрована» и «её нет» —
        # разные ответы, и второй не должен выглядеть как первый.
        "encrypted": None if st is None else not head.startswith(SQLITE_MAGIC),
        "wal": wal[0] if wal else 0,
        "markers": legacy.confirm(root),
        "orders": [o for o in ORDERS if (root / o).exists()],
        "sha256": None,
    }
    if digest and st is not None:
        out["sha256"] = _sha256(db)
    return out


def carries_records(fp: dict) -> bool:
    """Есть ли в корне картотека — по файлам, а не по числу пациентов.

    ⛔ Признак «а есть ли там пациенты» для различения корней непригоден:
    клиника, успевшая внести неделю работы не в тот корень, не должна получить
    свою работу отодвинутой как «свежий профиль». Поэтому здесь ЛЮБОЙ маркер
    данных, а счёта записей этот слой и не знает — он не открывает базу.
    """
    return legacy.carries_data(fp["markers"])


def decide(det: dict, anchor: pathlib.Path, source_fp: dict | None = None,
           anchor_fp: dict | None = None) -> dict:
    """Шаг 3. Один из четырёх ответов, и «догадаться» среди них нет.

    | `outcome`     | что это                                   | `action` |
    |---------------|-------------------------------------------|----------|
    | `unique`      | назван один корень, назначение пусто      | migrate  |
    | `split`       | картотека в ОБОИХ корнях                  | stop     |
    | `unconfirmed` | источник назвал, данные не подтвердили    | stop     |
    | `no-origin`   | не назвал никто                           | stop     |

    ⚠️ `no-origin` — это «мы не знаем», а НЕ «чистая машина». Чистой машина
    считается по положительному признаку; иначе первый же сбой детекции
    выглядит как новая клиника, и программа заводит пустой журнал рядом с
    живой картотекой.

    ⛔ `blockers` перекрывает любой исход: незавершённый приказ шифрования
    останавливает переезд даже при идеальном `unique`. Исход при этом не
    подменяется — человек должен видеть И что нашли, И почему не поехали.

    ⭐ Порядок вызова важен и держится на одном: ПОКА лаунчер не создал в
    назначении свежую базу, `split` невозможен. Спрашивать этот модуль надо до
    первого старта приложения, а не после — иначе всякая миграция упирается в
    экран выбора, который сама же и создала.
    """
    anchor = pathlib.Path(anchor)
    a_fp = anchor_fp if anchor_fp is not None else fingerprint(anchor)
    blockers = [str(anchor / o) for o in a_fp["orders"]]

    if not det.get("found"):
        # ⚠️ `unconfirmed` — источник назвал и не подтвердилось; всё остальное
        # («не назвал никто», «назвали только назначение») — это «мы не знаем».
        # Точная причина не теряется: она едет рядом, в `reason`.
        outcome = "unconfirmed" if det.get("reason") == "unconfirmed" else "no-origin"
        return {"outcome": outcome, "action": "stop", "source": None,
                "anchor": a_fp, "blockers": blockers, "reason": det.get("reason"),
                "why": "источник ничего не подтвердил"}

    s_fp = source_fp if source_fp is not None else fingerprint(det["path"])
    blockers += [str(det["path"] / o) for o in s_fp["orders"]]

    if carries_records(a_fp):
        return {"outcome": "split", "action": "stop", "source": s_fp,
                "anchor": a_fp, "blockers": blockers, "reason": det.get("reason"),
                "why": "картотека в обоих корнях — выбирает человек"}

    return {"outcome": "unique",
            "action": "stop" if blockers else "migrate",
            "source": s_fp, "anchor": a_fp, "blockers": blockers,
            "reason": det.get("reason"),
            "why": "незавершённый приказ шифрования" if blockers
                   else "один корень, назначение пусто"}


def root_for(anchor: pathlib.Path,
             self_root: pathlib.Path | None = None,
             shortcuts: list[pathlib.Path] | None = None) -> tuple[pathlib.Path, dict]:
    """Из какого корня РАБОТАТЬ этому запуску, пока шаги 4–8 не написаны.

    Возвращает `(корень, вердикт)`. Зовёт лаунчер — до того, как приложение
    откроет хоть один файл.

    ⭐ **`unique` → работаем в СТАРОМ корне, и это не миграция.** Это начальное
    значение самого контракта: авторитетным объявлен старый корень, и он
    остаётся им, пока переключение не зафиксировано. Копирования здесь нет,
    записи здесь нет — есть отказ заводить пустой журнал рядом с настоящим.
    ⛔ Ровно этот случай и есть дыра одноклик-обновления: exe подменён на
    месте, перезапущен планировщиком, `$DENTART_DATA_DIR` пуст, картотека
    осталась рядом со старым exe. Раньше клиника увидела бы пустой журнал без
    единой ошибки.

    ⚠️ `blockers` (незавершённый приказ шифрования) работу в старом корне НЕ
    отменяют. Они запрещают КОПИРОВАТЬ, а здесь копирования нет; запретить же
    работать значило бы вместо пустого журнала показать закрытую программу —
    хуже, а не лучше. Приказ выполнит лаунчер там же, где выполнил бы и до
    обновления.

    ⛔ **`unconfirmed` стартом НЕ распоряжается**, хотя и выглядит тревожно.
    Это НОРМАЛЬНОЕ состояние здоровой установки в `Program Files`: общий ярлык
    (и сам процесс) называют папку программы, а данных там нет и быть не
    должно. Останавливать по нему запуск значило бы не пускать в программу
    каждую правильно установленную клинику. Защиту, которую от этой ветки ждут,
    даёт `unique` — и даёт положительным признаком, а не тревогой.

    ⛔ **`split` стартует в НАЗНАЧЕНИИ**, а не отказывает. Программа, не
    открывшаяся из-за спорной находки, закрыла бы клинику на день; контракт
    требует экран выбора того же класса, что режим восстановления. Экран —
    следующая работа, и пока его нет, `split` ведёт себя как сегодня: журнал
    назначения открывается, вердикт уходит в лог.
    """
    verdict = survey(anchor=anchor, self_root=self_root, shortcuts=shortcuts)
    if verdict["outcome"] == "unique":
        return verdict["source"]["root"], verdict
    return pathlib.Path(anchor), verdict


def survey(named: str | pathlib.Path | None = None,
           anchor: pathlib.Path | None = None,
           self_root: pathlib.Path | None = None,
           shortcuts: list[pathlib.Path] | None = None) -> dict:
    """Шаги 1–3 одним вызовом: что нашли и что из этого следует.

    ⚠️ `anchor=None` — спросить `paths.data_root()`. Нет и его (облако, прогон,
    запуск из исходников) — решать нечего и не о чем: возвращается `no-anchor`,
    и это не ошибка, а отсутствие вопроса.
    ⚠️ `shortcuts` передают тесты: без этого шва набор читает НАСТОЯЩИЕ ярлыки
    машины, и временная папка герметичным его не делает — на машине
    разработчика DentPilot установлен, и «чистая машина» оказывалась
    `unconfirmed`. В продукте параметр не передаётся никогда.
    """
    root = pathlib.Path(anchor) if anchor is not None else None
    if root is None:
        roots = legacy.anchor_roots()
        if not roots:
            return {"outcome": "no-anchor", "action": "stop", "source": None,
                    "anchor": None, "blockers": [], "reason": None,
                    "why": "папка назначения не названа — переезжать некуда"}
        root = roots[0]
    det = legacy.detect(shortcuts, named=named, exclude=[root],
                        self_root=self_root)
    return decide(det, root)
