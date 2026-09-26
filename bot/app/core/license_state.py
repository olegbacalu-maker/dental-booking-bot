"""Машина состояний лицензии (L3): пол часов, три состояния, память.

Контракт — docs/dentpilot-2/cloud.md › «Три состояния программы» и «Пол
часов». Здесь только чистые функции и файл памяти: ни базы, ни окружения,
ни настоящих часов — время приходит аргументом, поэтому каждая граница
проверяется подставной датой (tests/test_license_state.py). Обвязка с папкой
клиники, базой и таблицей ключей — license.py.

⭐ Состояние не хранится — выводится из дат и часов при каждом вопросе.
Хранится только ПАМЯТЬ: когда впервые запущена версия с лицензией, какое
время программа уже видела, какой файл приняла последним и до каких дат он
действовал.

⛔ Стирание файла не дарит льготу заново: клиника, чей файл уже был принят,
живёт по запомненным датам, пока не импортирует файл. Отсчёт «14 дней от
первого запуска» — только для картотеки, у которой файла НЕ БЫЛО никогда
(клиника, обновившаяся до версии с лицензией), и его нет у пустой
картотеки: там стена активации (L5).

⛔ Часам верят с полом: не раньше `issued_at` файла и не раньше последнего
виденного времени. Перевод часов назад ничего не оживляет. Это защита от
случайного и ленивого, не DRM.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

ACTIVE = "active"
GRACE = "grace"
READONLY = "readonly"
MISSING = "missing"
INVALID = "invalid"
OLDER = "license_older"                 # файл старее принятого ранее (seq)
NO_FILE_GRACE = timedelta(days=14)      # обновившаяся клиника без файла
_TS = "%Y-%m-%dT%H:%M:%SZ"


@dataclass(frozen=True)
class Memory:
    """Что программа помнит между запусками. Все даты — aware, UTC."""
    first_start: datetime | None = None   # первый запуск версии с лицензией
    last_seen: datetime | None = None     # последнее виденное время — пол часов
    accepted_seq: int = 0                 # seq последнего принятого файла; 0 — не было
    valid_until: datetime | None = None   # даты последнего принятого файла
    grace_until: datetime | None = None


@dataclass(frozen=True)
class Status:
    """Состояние в момент вопроса."""
    state: str                    # active | grace | readonly | missing | invalid
    code: str                     # почему файл не годен; '' — годен или его нет
    claim: object | None          # rsa_verify.Claim принятого файла
    valid_until: datetime | None  # действующие даты: файла, памяти или отсчёта
    grace_until: datetime | None
    now: datetime                 # часы после пола
    wall: bool                    # стена активации: файла нет и картотека пуста


# ---------- время ----------


def fmt(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime(_TS)


def parse(s: object) -> datetime | None:
    if not isinstance(s, str) or len(s) != 20:
        return None
    try:
        return datetime.strptime(s, _TS).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def clock(now_wall: datetime, mem: Memory, claim: object | None) -> datetime:
    """Часы с полом: не раньше виденного и не раньше выдачи файла."""
    floor = [now_wall]
    if mem.last_seen is not None:
        floor.append(mem.last_seen)
    if claim is not None:
        floor.append(claim.issued_at)
    return max(floor)


def by_dates(now: datetime, valid_until: datetime, grace_until: datetime) -> str:
    if now < valid_until:
        return ACTIVE
    return GRACE if now < grace_until else READONLY


# ---------- состояние ----------


def evaluate(result: tuple[str, object | None] | None, now_wall: datetime,
             mem: Memory, has_patients: bool) -> tuple[Status, Memory]:
    """`result` — ответ rsa_verify.open_envelope или None, когда файла нет.

    Возвращает состояние и ОБНОВЛЁННУЮ память: вызывающий её сохраняет.
    """
    code, claim = ("", None) if result is None else result
    if claim is not None and mem.accepted_seq and claim.seq < mem.accepted_seq:
        # чужой или старый файл поверх принятого: replay не проходит
        code, claim = OLDER, None
    now = clock(now_wall, mem, claim)
    first = now if mem.first_start is None else min(mem.first_start, now)
    new = replace(mem, first_start=first, last_seen=now)

    if claim is not None:
        vu, gu = claim.valid_until, claim.grace_until
        new = replace(new, accepted_seq=claim.seq, valid_until=vu, grace_until=gu)
        return Status(by_dates(now, vu, gu), "", claim, vu, gu, now, False), new

    if mem.valid_until is not None and mem.grace_until is not None:
        # файл уже принимался: живём по его датам, но без файла ACTIVE не бывает
        state = GRACE if now < mem.grace_until else READONLY
        return Status(state, code, None, mem.valid_until, mem.grace_until, now, False), new

    if has_patients:
        # картотека есть, файла не было никогда: 14 дней от первого запуска
        until = first + NO_FILE_GRACE
        state = GRACE if now < until else READONLY
        return Status(state, code, None, first, until, now, False), new

    return Status(MISSING if result is None else INVALID, code, None, None, None, now, True), new


# ---------- память: файл и слияние ----------


def merge(a: Memory, b: Memory) -> Memory:
    """Две памяти — файл и зеркало в базе — в одну, строгую по каждому полю."""
    firsts = [x for x in (a.first_start, b.first_start) if x is not None]
    seens = [x for x in (a.last_seen, b.last_seen) if x is not None]
    acc = b if b.accepted_seq > a.accepted_seq else a
    return Memory(min(firsts) if firsts else None, max(seens) if seens else None,
                  acc.accepted_seq, acc.valid_until, acc.grace_until)


def to_dict(mem: Memory) -> dict:
    return {"first_start": fmt(mem.first_start) if mem.first_start else None,
            "last_seen": fmt(mem.last_seen) if mem.last_seen else None,
            "accepted_seq": mem.accepted_seq,
            "valid_until": fmt(mem.valid_until) if mem.valid_until else None,
            "grace_until": fmt(mem.grace_until) if mem.grace_until else None}


def from_dict(d: object) -> Memory:
    """Терпимо к мусору: битая память = пустая память, а не отказ старта."""
    if not isinstance(d, dict):
        return Memory()
    seq = d.get("accepted_seq")
    seq = seq if type(seq) is int and seq >= 0 else 0
    vu, gu = parse(d.get("valid_until")), parse(d.get("grace_until"))
    if vu is None or gu is None:
        vu = gu = None
    return Memory(parse(d.get("first_start")), parse(d.get("last_seen")), seq, vu, gu)


def load(path: pathlib.Path) -> Memory:
    try:
        return from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, UnicodeDecodeError):
        return Memory()


def save(path: pathlib.Path, mem: Memory) -> None:
    """Атомарно, тем же приёмом, что auth.json: tmp рядом и os.replace.
    Сбой записи не роняет старт — прежняя память при этом цела."""
    tmp = path.with_name(path.name + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(json.dumps(to_dict(mem)))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except OSError:
        pass


# ---------- ворота записи (L4) ----------

# Маршруты, которым запись нужна и в `readonly`, — шаблонами ровно как в
# декораторах. Три рода: доступ (вход, PIN, учётки, сигнализация, лицензия —
# её импорт и запрос нового файла с сервера, L13: именно в readonly он и
# нужен; заявка на пробный из программы — за стеной у свежей установки),
# права клиники на свои данные (бэкап, выгрузка пациента, право на
# стирание, открыть документ, шифрование картотеки) и обслуживание программы
# (обновление, сеть, раскладка). Всё, что трогает картотеку, расписание,
# врачей, прайс и профиль клиники, здесь не значится — и потому отказывает.
# ⛔ Список — константа, а не флаг у маршрута: сторож проверяет, что каждый
# пишущий маршрут либо здесь, либо отказывает (tests/test_license_gate.py).
READONLY_ALLOW = (
    "/admin/login", "/admin/setup", "/admin/license", "/admin/recover",
    "/admin/pin/change", "/admin/license/renew", "/admin/license/request", "/admin/license/verify",
    "/admin/security/ack", "/admin/users/save", "/admin/users/delete",
    "/admin/backup/export",
    "/admin/settings/crypt/prepare", "/admin/settings/crypt/confirm",
    "/admin/settings/crypt/off",
    "/admin/update/check", "/admin/update/run",
    "/admin/lan/save", "/admin/lan/firewall", "/admin/migration/confirm",
    "/api/settings/pin", "/api/settings/users", "/api/settings/users/{uid}/delete",
    "/api/settings/crypt/prepare", "/api/settings/crypt/off",
    "/api/settings/system/check", "/api/settings/system/uninstall-sync",
    "/api/settings/lan", "/api/settings/lan/firewall",
    "/api/patients/{pid}/archive", "/api/patients/{pid}/erase",
    "/api/documents/{doc_id}/open",
)
GATED_PREFIXES = ("/admin", "/api/")           # где ворота вообще стоят
READ_METHODS = ("GET", "HEAD", "OPTIONS")
_ALLOW_RX: dict[tuple, list] = {}


def _rx(template: str):
    return re.compile("^" + re.sub(r"\{[^}/]+\}", "[^/]+", re.escape(template)
                                   .replace("\\{", "{").replace("\\}", "}")) + "$")


def allowed(path: str, templates: tuple = READONLY_ALLOW) -> bool:
    """Подходит ли путь под один из шаблонов белого списка."""
    rxs = _ALLOW_RX.get(templates)
    if rxs is None:
        rxs = _ALLOW_RX[templates] = [_rx(t) for t in templates]
    return any(r.match(path) for r in rxs)


def gated(path: str, method: str) -> bool:
    """Стоят ли ворота на этом запросе вообще: пишущий метод под /admin или /api/."""
    return method not in READ_METHODS and path.startswith(GATED_PREFIXES)


# ---------- таблица ключей ----------


def keys_from(base: dict, env_value: str, frozen: bool) -> dict:
    """`base` плюс, только вне собранного exe, ключи из файла по пути `env_value`.

    ⛔ В exe переменная не читается вовсе: `sys.frozen` ставит PyInstaller,
    и снять его из `dental.env` нельзя. Битый или отсутствующий файл — молча
    только `base`: тесты, которым нужен ключ, заметят это первой же проверкой.
    """
    table = dict(base)
    path = (env_value or "").strip().strip("\"'")
    if frozen or not path:
        return table
    try:
        raw = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return table
    for item in raw if isinstance(raw, list) else [raw]:
        try:
            kid, n, e = item["kid"], int(item["n"], 16), int(item["e"])
        except (KeyError, TypeError, ValueError):
            continue
        if isinstance(kid, str) and n > 0 and e > 0:
            table[kid] = (n, e)
    return table
