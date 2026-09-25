"""Выдача файла лицензии: claim по схеме → подпись → seq+1 → строка в issues.

Контракт — docs/dentpilot-2/cloud.md › «Файл лицензии». Сервер пишет claim
ОДНИМ способом (канонический JSON), подписывает PKCS#1 v1.5 / SHA-256 через
`cryptography`; программа проверяет байты, какие пришли. Что подпись здесь и
подпись генератора фикстур — одно и то же, проверяет тест: файл `valid.json`
подписывается заново и сходится байт в байт.

Состояние подписки не хранится — выводится из дат тем же правилом, что в
программе (license_state.by_dates): active / grace / readonly.

Автообновление (L13): в claim едет `renew` — адрес `/v1/license` этого сервера
и токен клиники. Токен рождается с первой выдачей и дальше один и тот же:
сменить его значит оставить без обновления все файлы, что уже у клиники.
"""
from __future__ import annotations

import base64
import json
import logging
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

from . import config, db, keys, mail

log = logging.getLogger("cloud.license")

TRIAL_DAYS = 14
TRIAL_GRACE_DAYS = 3
GRACE_DAYS = 14
PLANS = ("trial", "standard")
RENEW_PATH = "/v1/license"
RENEW_TOKEN_BYTES = 32          # token_urlsafe(32) — 43 знака; программа требует ≥ 32
# То же правило, что у программы (rsa_verify._RENEW_URL): https — всегда, http —
# только loopback. Адрес, который программа отвергла бы, в файл не пишется.
_RENEW_URL = re.compile(
    r"^(?:https://.|http://(?:127\.0\.0\.1|localhost|\[::1\])(?::\d{1,5})?(?:/|$))")

_key: keys.Key | None = None


def key() -> keys.Key | None:
    global _key
    if _key is None and config.LICENSE_KEY:
        _key = keys.load(config.LICENSE_KEY, config.LICENSE_KID)
    return _key


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def claim_bytes(claim: dict) -> bytes:
    return json.dumps(claim, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def sign(payload: bytes) -> bytes:
    k = key()
    if k is None:
        raise RuntimeError("DP_LICENSE_KEY не задан: выдавать нечем")
    return k.private.sign(payload, padding.PKCS1v15(), hashes.SHA256())


def envelope(payload: bytes, sig: bytes, kid: str) -> str:
    return json.dumps({"v": 1, "kid": kid, "payload": b64u(payload), "sig": b64u(sig)},
                      ensure_ascii=False, indent=2) + "\n"


def state(valid_until: datetime | None, grace_days: int, now: datetime | None = None) -> str:
    """active / grace / readonly / none — тем же правилом, что в программе."""
    if valid_until is None:
        return "none"
    now = now or datetime.now(timezone.utc)
    if now < valid_until:
        return "active"
    return "grace" if now < valid_until + timedelta(days=grace_days) else "readonly"


def renew_url() -> str:
    """Адрес, который программа спрашивает раз в сутки."""
    return config.BASE_URL.rstrip("/") + RENEW_PATH


def renew_offered() -> bool:
    """Пишется ли `renew` в файлы: только адрес, который примет программа. На ПК
    с Windows за http://127.0.0.1 поле есть, но до программы клиники не
    достанет — автообновление требует публичного адреса (DEPLOY.md § 9)."""
    return _RENEW_URL.match(renew_url()) is not None


def renew_token(con: sqlite3.Connection, clinic: sqlite3.Row) -> str:
    """Токен клиники: рождается с первой выдачей, дальше один и тот же."""
    token = clinic["renew_token"] if "renew_token" in clinic.keys() else ""
    if not token:
        token = secrets.token_urlsafe(RENEW_TOKEN_BYTES)
        con.execute("UPDATE clinics SET renew_token=? WHERE id=?", (token, clinic["id"]))
    return token


def issue(con: sqlite3.Connection, clinic: sqlite3.Row, plan: str, valid_until: datetime,
          grace_until: datetime, reason: str, who: str) -> tuple[int, str]:
    """Выпустить файл клинике. Возвращает (seq, текст файла). Подписка
    приводится к выданным датам: файл и есть истина о сроке."""
    if plan not in PLANS:
        raise ValueError("plan")
    if plan != "trial" and len(clinic["idno"]) != 13:
        raise ValueError("idno")
    k = key()
    if k is None:
        raise RuntimeError("DP_LICENSE_KEY не задан: выдавать нечем")
    now = datetime.now(timezone.utc).replace(microsecond=0)
    last = con.execute("SELECT COALESCE(MAX(seq), 0) FROM issues WHERE clinic_id=?",
                       (clinic["id"],)).fetchone()[0]
    seq = int(last) + 1
    claim = {"clinic_id": clinic["id"], "clinic": clinic["name"], "idno": clinic["idno"],
             "plan": plan, "country": clinic["country"] or "MD", "seq": seq,
             "issued_at": now.strftime(db.TS), "valid_until": valid_until.strftime(db.TS),
             "grace_until": grace_until.strftime(db.TS)}
    if renew_offered():
        claim["renew"] = {"url": renew_url(), "token": renew_token(con, clinic)}
    payload = claim_bytes(claim)
    sig = sign(payload)
    con.execute("""INSERT INTO issues(clinic_id, seq, kid, payload, sig, issued_at, valid_until,
                                      grace_until, reason) VALUES(?,?,?,?,?,?,?,?,?)""",
                (clinic["id"], seq, k.kid, b64u(payload), b64u(sig), claim["issued_at"],
                 claim["valid_until"], claim["grace_until"], reason))
    grace_days = max(0, (grace_until - valid_until).days)
    con.execute("""INSERT INTO subscriptions(clinic_id, plan, valid_until, grace_days, updated_at)
                   VALUES(?,?,?,?,?)
                   ON CONFLICT(clinic_id) DO UPDATE SET plan=excluded.plan,
                       valid_until=excluded.valid_until, grace_days=excluded.grace_days,
                       updated_at=excluded.updated_at""",
                (clinic["id"], plan, claim["valid_until"], grace_days, db.now_iso()))
    db.audit(con, who, "issue", clinic["id"],
             f"seq {seq}, {plan}, до {claim['valid_until']}, льгота до {claim['grace_until']}: {reason}")
    return seq, envelope(payload, sig, k.kid)


def issue_text(row: sqlite3.Row) -> str:
    """Текст файла из строки issues — то же, что было выдано."""
    return json.dumps({"v": 1, "kid": row["kid"], "payload": row["payload"], "sig": row["sig"]},
                      ensure_ascii=False, indent=2) + "\n"


def mail_latest(con: sqlite3.Connection, clinic: sqlite3.Row, who: str) -> str:
    """Последний выданный файл письмом: админка, callback maib и ежедневная задача —
    одной функцией. Возвращает код для ?msg= или '' — ушло."""
    row = con.execute("SELECT * FROM issues WHERE clinic_id=? ORDER BY seq DESC LIMIT 1",
                      (clinic["id"],)).fetchone()
    if row is None:
        return "no_issue"
    if not clinic["email"]:
        return "bad_email"
    plan = con.execute("SELECT plan FROM subscriptions WHERE clinic_id=?", (clinic["id"],)).fetchone()
    subject, body = mail.license_letter(clinic["name"], row["valid_until"],
                                        plan["plan"] if plan else "standard", renew=renew_offered())
    try:
        where = mail.send(clinic["email"], subject, body, ("license.json", issue_text(row).encode("utf-8")))
    except (RuntimeError, OSError, ValueError) as e:
        log.error("письмо клинике %s не отправлено: %r", clinic["id"], e)
        return "mail_failed"
    db.audit(con, who, "mail", clinic["id"], f"seq {row['seq']} на {clinic['email']} ({where})")
    return ""


def trial_dates(now: datetime | None = None) -> tuple[datetime, datetime]:
    now = (now or datetime.now(timezone.utc)).replace(microsecond=0)
    valid = now + timedelta(days=TRIAL_DAYS)
    return valid, valid + timedelta(days=TRIAL_GRACE_DAYS)
