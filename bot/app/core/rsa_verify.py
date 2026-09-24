"""Проверка файла лицензии: RSA PKCS#1 v1.5 поверх SHA-256, одной стандартной библиотекой.

Контракт — docs/dentpilot-2/cloud.md › «Файл лицензии»: конверт, claim, шесть
шагов проверки и три кода отказа. Здесь только математика и разбор текста:
ни диска, ни окружения, ни часов — это license.py (L3). Модуль не импортирует
ничего из проекта, чтобы его можно было прочитать и проверить в одиночку.

⭐ Блок EMSA-PKCS1-v1_5 программа СТРОИТ и сравнивает через
`hmac.compare_digest`, а не разбирает расшифрованный: разбор паддинга — тот
класс ошибок, из которого сделан Bleichenbacher. При e = 65537 проверка стоит
микросекунды, замер не нужен.

⛔ Канонизации нет намеренно: подпись стоит на байтах `payload`, какие пришли.
Второй сериализатор на стороне проверки однажды разошёлся бы с серверным, и
разошёлся бы молча — у клиники, а не в тесте.

⛔ Порядок шагов — часть контракта, а не деталь: код отказа говорит человеку,
ЧТО именно не так с файлом, и «подпись не сошлась» на файле с неизвестным
ключом послало бы его искать не там.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone

SIG_LEN = 384                       # RSA-3072; длина ключа в байтах = длина подписи
# DigestInfo для SHA-256 (RFC 8017 §9.2, прим. 1): SEQUENCE { AlgId sha256, NULL }, OCTET STRING(32)
DIGESTINFO_SHA256 = bytes.fromhex("3031300d060960864801650304020105000420")

MALFORMED = "license_malformed"          # не файл лицензии, или файл не по схеме
KEY_UNKNOWN = "license_key_unknown"      # выдан ключом, которого эта версия не знает
BAD_SIGNATURE = "license_bad_signature"  # подпись не сходится с содержимым

# Публичные ключи выдачи: kid -> (n, e). Первый боевой ключ ложится сюда с L7 —
# сервера ещё нет. ⛔ Тестовый ключ сюда не кладётся никогда: проверка получает
# таблицу АРГУМЕНТОМ, а в программе её собирает license.py (L3) — из этой
# константы и, только в незамороженном запуске, из DENTART_LICENSE_KEYS.
KEYS: dict[str, tuple[int, int]] = {}

_KID = re.compile(r"^[a-z0-9-]{1,16}$")
_B64U = re.compile(r"^[A-Za-z0-9_-]*$")       # алфавит base64url, без «=»
_CLINIC_ID = re.compile(r"^c_[0-9a-f]{12}$")
_IDNO = re.compile(r"^([0-9]{13})?$")
_COUNTRY = re.compile(r"^[A-Z]{2}$")
_TS = "%Y-%m-%dT%H:%M:%SZ"
_PLANS = ("trial", "standard")
_RENEW_TOKEN_MIN = 32


@dataclass(frozen=True)
class Claim:
    """Проверенное содержимое файла. Даты — aware, UTC."""
    clinic_id: str
    clinic: str
    idno: str
    plan: str
    country: str
    seq: int
    issued_at: datetime
    valid_until: datetime
    grace_until: datetime
    renew: dict | None          # {"url", "token"} с шага 2; None, пока поля нет


# ---------- математика ----------


def emsa_pkcs1_v15_sha256(data: bytes, k: int) -> bytes:
    """Ожидаемый блок для данных `data` при ключе длиной `k` байт."""
    t = DIGESTINFO_SHA256 + hashlib.sha256(data).digest()
    return b"\x00\x01" + b"\xff" * (k - 3 - len(t)) + b"\x00" + t


def verify(n: int, e: int, sig: bytes, data: bytes) -> bool:
    """Сходится ли подпись `sig` с `data` под ключом (n, e). Не бросает."""
    k = (n.bit_length() + 7) // 8
    if len(sig) != k:
        return False
    s = int.from_bytes(sig, "big")
    if s >= n:
        return False
    em = pow(s, e, n).to_bytes(k, "big")
    return hmac.compare_digest(em, emsa_pkcs1_v15_sha256(data, k))


# ---------- разбор ----------


def _unb64u(s: str) -> bytes | None:
    """base64url без «=» — строго: чужой знак или лишняя длина = None.

    ⚠️ `urlsafe_b64decode` сам по себе ПРОПУСКАЕТ чужие знаки молча, поэтому
    алфавит проверяется до него, а не им."""
    if not _B64U.match(s) or len(s) % 4 == 1:
        return None
    try:
        return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
    except (binascii.Error, ValueError):
        return None


def _ts(s: str) -> datetime | None:
    if len(s) != 20:
        return None
    try:
        return datetime.strptime(s, _TS).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def parse_claim(payload: bytes) -> Claim | None:
    """Шаг 6: байты claim -> Claim по таблице схемы; None = не по схеме.

    `type(x) is int`, а не isinstance: bool — подкласс int, и `seq: true`
    прошёл бы за число."""
    try:
        c = json.loads(payload.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(c, dict):
        return None
    for f in ("clinic_id", "clinic", "idno", "plan", "country",
              "issued_at", "valid_until", "grace_until"):
        if type(c.get(f)) is not str:
            return None
    if type(c.get("seq")) is not int or c["seq"] < 1:
        return None
    if (not _CLINIC_ID.match(c["clinic_id"]) or not 1 <= len(c["clinic"]) <= 120
            or not _IDNO.match(c["idno"]) or c["plan"] not in _PLANS
            or not _COUNTRY.match(c["country"])):
        return None
    if c["plan"] != "trial" and not c["idno"]:
        return None
    dates = [_ts(c[f]) for f in ("issued_at", "valid_until", "grace_until")]
    if None in dates or not dates[0] < dates[1] <= dates[2]:
        return None
    renew = c.get("renew")
    if renew is not None:
        if (not isinstance(renew, dict) or type(renew.get("url")) is not str
                or not renew["url"].startswith("https://")
                or type(renew.get("token")) is not str
                or len(renew["token"]) < _RENEW_TOKEN_MIN):
            return None
        renew = {"url": renew["url"], "token": renew["token"]}
    return Claim(c["clinic_id"], c["clinic"], c["idno"], c["plan"], c["country"],
                 c["seq"], dates[0], dates[1], dates[2], renew)


def open_envelope(text: str, keys: Mapping[str, tuple[int, int]]
                  ) -> tuple[str, Claim | None]:
    """Текст файла -> ("", Claim) или (код отказа, None). Шаги 1–6 контракта.

    `keys` — таблица `{kid: (n, e)}`, которой доверяет ВЫЗЫВАЮЩИЙ: тесты
    передают тестовый ключ, программа — то, что собрал license.py."""
    # 1. конверт
    try:
        env = json.loads(text)
    except (ValueError, TypeError):
        return MALFORMED, None
    if (not isinstance(env, dict) or type(env.get("v")) is not int or env["v"] != 1
            or type(env.get("kid")) is not str or not _KID.match(env["kid"])
            or type(env.get("payload")) is not str or type(env.get("sig")) is not str):
        return MALFORMED, None
    # 2. ключ
    key = keys.get(env["kid"])
    if key is None:
        return KEY_UNKNOWN, None
    # 3. раскодировать строго
    payload, sig = _unb64u(env["payload"]), _unb64u(env["sig"])
    if payload is None or sig is None or len(sig) != SIG_LEN:
        return MALFORMED, None
    # 4–5. подпись
    if not verify(key[0], key[1], sig, payload):
        return BAD_SIGNATURE, None
    # 6. только теперь — содержимое
    claim = parse_claim(payload)
    if claim is None:
        return MALFORMED, None
    return "", claim
