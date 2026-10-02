"""Флот (шаг 3, 02.10): какие компьютеры с какой версией программы у каких клиник.

Идея Олега 08-20 — «видеть, кто обновился, никаких личных данных» — и первый
кирпич будущей админ-панели (слово 02.10: «заложи фундамент»). Программа в
каждом запросе к серверу (/v1/license раз в сутки, /v1/trial и /v1/verify при
активации) называет себя тремя заголовками: `X-DentPilot-Device` — личность
машины из `device.json` (P7), `X-DentPilot-Channel` — stable/beta/draft,
`X-DentPilot-OS` — Windows и сборка; версия программы — в User-Agent
`DentPilot/x.y.z`. Сервер держит по строке на компьютер: первый и последний
выход на связь, версия, канал, ОС, последний seq файла у программы. Никаких
данных пациентов и имён пользователей — политика сайта § 5.

⛔ Канал односторонний (plan-fleet-admin): сервер слушает и записывает,
программой не командует. «Отстаёт» — сравнение с последним выпуском GitHub
(download.latest), а не команда обновиться; «молчит» — давно не выходил на
связь, то есть выключен или без интернета, а не «сломан».

Отчёт `report()` — одна форма на страницу «Флот» и на `/admin/api/fleet`:
будущий интерфейс админки читает тот же JSON, что сегодня рисует views.py.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone

from . import db, download, license

DEVICE_RE = re.compile(r"^d_[0-9a-f]{12}$")
AGENT_RE = re.compile(r"^DentPilot/(\d+\.\d+\.\d+)")
CHANNELS = ("stable", "beta", "draft")
OS_MAX = 60
SILENT_DAYS = 7          # дольше без связи — «молчит» (программа ходит раз в сутки)
HEADER_DEVICE, HEADER_CHANNEL, HEADER_OS = "x-dentpilot-device", "x-dentpilot-channel", "x-dentpilot-os"


def from_request(request) -> dict | None:
    """Личность программы из заголовков или None — не программа или без device.
    Мусор в заголовках не пишется: чужой запрос не заведёт строку."""
    h = request.headers
    did = (h.get(HEADER_DEVICE) or "").strip()
    if not DEVICE_RE.match(did):
        return None
    m = AGENT_RE.match(h.get("user-agent") or "")
    ch = (h.get(HEADER_CHANNEL) or "").strip().lower()
    return {"id": did, "version": m.group(1) if m else "", "channel": ch if ch in CHANNELS else "",
            "os": " ".join((h.get(HEADER_OS) or "").split())[:OS_MAX]}


def touch(con: sqlite3.Connection, clinic_id: str, info: dict | None, seq: int | None = None) -> None:
    """Компьютер вышел на связь: строка заводится или обновляется. Клиника у
    компьютера одна — переезд файла к другой клинике переписывает привязку."""
    if not info:
        return
    now = db.now_iso()
    con.execute("""INSERT INTO devices(id, clinic_id, version, channel, os, first_seen_at, last_seen_at, last_seq)
                   VALUES(?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET clinic_id=excluded.clinic_id, version=excluded.version,
                       channel=excluded.channel, os=excluded.os, last_seen_at=excluded.last_seen_at,
                       last_seq=COALESCE(excluded.last_seq, devices.last_seq)""",
                (info["id"], clinic_id, info["version"], info["channel"], info["os"], now, now, seq))


def of_clinic(con: sqlite3.Connection, clinic_id: str) -> list:
    return con.execute("SELECT * FROM devices WHERE clinic_id=? ORDER BY last_seen_at DESC",
                       (clinic_id,)).fetchall()


def _ver(s: str) -> tuple:
    try:
        return tuple(int(x) for x in s.split("."))
    except ValueError:
        return ()


def behind(version: str, latest: str) -> bool:
    """Версия компьютера старее последнего выпуска. Неизвестное — не отстаёт:
    пустая версия или нет сведений о выпуске не красят флот."""
    v, lv = _ver(version), _ver(latest)
    return bool(v and lv and v < lv)


_ROWS = """SELECT d.*, c.name AS clinic, s.plan, s.valid_until, s.grace_days
           FROM devices d JOIN clinics c ON c.id = d.clinic_id
           LEFT JOIN subscriptions s ON s.clinic_id = c.id
           ORDER BY d.last_seen_at DESC"""


def report(con: sqlite3.Connection, now: datetime | None = None) -> dict:
    """Сводка: последний выпуск, компьютеры с состоянием подписки, кто отстал,
    кто молчит. Одна форма на страницу и на JSON."""
    now = now or datetime.now(timezone.utc)
    rel = download.latest()
    latest = rel.version if rel else ""
    items = []
    for r in con.execute(_ROWS).fetchall():
        seen = db.parse_ts(r["last_seen_at"])
        silent = (now - seen).days if seen else None
        items.append({
            "device": r["id"], "clinic_id": r["clinic_id"], "clinic": r["clinic"],
            "version": r["version"], "channel": r["channel"], "os": r["os"],
            "first_seen_at": r["first_seen_at"], "last_seen_at": r["last_seen_at"],
            "last_seq": r["last_seq"], "silent_days": silent,
            "behind": behind(r["version"], latest),
            "silent": silent is not None and silent > SILENT_DAYS,
            "plan": r["plan"] or "",
            "state": license.state(db.parse_ts(r["valid_until"]), r["grace_days"] or 0, now),
        })
    return {"latest": latest, "devices": items,
            "counts": {"devices": len(items), "clinics": len({i["clinic_id"] for i in items}),
                       "behind": sum(i["behind"] for i in items), "silent": sum(i["silent"] for i in items)}}
