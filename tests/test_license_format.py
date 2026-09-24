"""Файл лицензии: фикстуры держатся схемы (L1, docs/dentpilot-2/cloud.md).

Сервера нет и подписи здесь не проверяются — это L2. Набор пинит ФОРМАТ:
поля, типы, регулярки, порядок дат, каноничность байтов claim и родство
файлов между собой (у `bad-sig` тот же claim, что у `valid`, и ровно один
другой байт подписи). Читателей у фикстур два — этот прогон и прогон сервера
(L7), и красное здесь значит «фикстуры и схема разошлись», а не «подпись
плохая».
"""
import base64
import json
import math
import re
from datetime import datetime, timedelta, timezone

from harness import ROOT, Result

FIX = ROOT / "tests" / "fixtures" / "license"
KEY = FIX / "test-key.json"
FILES = ("valid", "expired", "trial", "bad-sig", "tampered", "unknown-kid")
B64U = re.compile(r"^[A-Za-z0-9_-]+$")
KID = re.compile(r"^[a-z0-9-]{1,16}$")
CLINIC_ID = re.compile(r"^c_[0-9a-f]{12}$")
IDNO = re.compile(r"^(\d{13})?$")
COUNTRY = re.compile(r"^[A-Z]{2}$")
TS = "%Y-%m-%dT%H:%M:%SZ"
SIG_LEN = 384                      # RSA-3072
REQUIRED = {"clinic_id": str, "clinic": str, "idno": str, "plan": str,
            "country": str, "seq": int, "issued_at": str, "valid_until": str,
            "grace_until": str}
DAY = timedelta(days=1)


def _unb64u(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _ts(s: str) -> datetime:
    return datetime.strptime(s, TS).replace(tzinfo=timezone.utc)


def _env(name: str) -> dict:
    return json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))


def _canon(claim: dict) -> bytes:
    return json.dumps(claim, ensure_ascii=False, separators=(",", ":"),
                      sort_keys=True).encode("utf-8")


def _diff_bytes(a: bytes, b: bytes) -> int:
    return -1 if len(a) != len(b) else sum(x != y for x, y in zip(a, b))


def _check_envelope(res: Result, name: str) -> tuple[dict, bytes, bytes] | None:
    raw = (FIX / f"{name}.json").read_bytes()
    res.ok(f"{name}: без BOM и с переводом строки в конце",
           not raw.startswith(b"\xef\xbb\xbf") and raw.endswith(b"\n"))
    env = json.loads(raw.decode("utf-8"))
    if not res.check(f"{name}: конверт — ровно четыре поля",
                     set(env), {"v", "kid", "payload", "sig"}):
        return None
    res.check(f"{name}: v", env["v"], 1)
    res.ok(f"{name}: kid по регулярке", isinstance(env["kid"], str) and bool(KID.match(env["kid"])),
           repr(env.get("kid")))
    for f in ("payload", "sig"):
        res.ok(f"{name}: {f} — base64url без «=»",
               isinstance(env[f], str) and bool(B64U.match(env[f])), repr(env[f])[:40])
    payload, sig = _unb64u(env["payload"]), _unb64u(env["sig"])
    res.check(f"{name}: длина подписи = длине ключа", len(sig), SIG_LEN)
    return env, payload, sig


def _check_claim(res: Result, name: str, payload: bytes) -> dict | None:
    try:
        claim = json.loads(payload.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        res.ok(f"{name}: claim — JSON", False, repr(e))
        return None
    if not res.ok(f"{name}: claim — объект", isinstance(claim, dict)):
        return None
    for field, typ in REQUIRED.items():
        v = claim.get(field)
        # bool — подкласс int; seq=true не должен пройти как число
        res.ok(f"{name}: {field} есть и типа {typ.__name__}",
               type(v) is typ, f"{field}={v!r}")
    if any(type(claim.get(f)) is not t for f, t in REQUIRED.items()):
        return claim
    res.ok(f"{name}: clinic_id по регулярке", bool(CLINIC_ID.match(claim["clinic_id"])),
           claim["clinic_id"])
    res.ok(f"{name}: clinic 1–120 знаков", 1 <= len(claim["clinic"]) <= 120)
    res.ok(f"{name}: idno — 13 цифр или пусто", bool(IDNO.match(claim["idno"])), claim["idno"])
    res.ok(f"{name}: plan из двух", claim["plan"] in ("trial", "standard"), claim["plan"])
    res.ok(f"{name}: idno обязателен вне trial",
           claim["plan"] == "trial" or claim["idno"] != "")
    res.ok(f"{name}: country — две заглавные", bool(COUNTRY.match(claim["country"])))
    res.ok(f"{name}: seq ≥ 1", claim["seq"] >= 1, str(claim["seq"]))
    try:
        i, v, g = (_ts(claim[f]) for f in ("issued_at", "valid_until", "grace_until"))
    except ValueError as e:
        res.ok(f"{name}: даты в формате {TS}", False, repr(e))
        return claim
    res.ok(f"{name}: даты в формате {TS}", True)
    res.ok(f"{name}: issued_at < valid_until ≤ grace_until", i < v <= g,
           f"{claim['issued_at']} {claim['valid_until']} {claim['grace_until']}")
    res.check(f"{name}: байты claim канонические (сервер пишет одним способом)",
              _canon(claim), payload)
    if "renew" in claim:
        r = claim["renew"]
        res.ok(f"{name}: renew — https-адрес и токен ≥ 32 знаков",
               isinstance(r, dict) and str(r.get("url", "")).startswith("https://")
               and isinstance(r.get("token"), str) and len(r["token"]) >= 32)
    return claim


def suite(res: Result) -> None:
    if not res.ok("папка фикстур на месте", FIX.is_dir(), str(FIX)):
        return
    missing = [n for n in FILES if not (FIX / f"{n}.json").exists()]
    res.check("все шесть файлов на месте", missing, [])
    res.ok("test-key.json на месте", KEY.exists())
    if missing or not KEY.exists():
        return

    k = json.loads(KEY.read_text(encoding="utf-8"))
    n, e, d, p, q = int(k["n"], 16), k["e"], int(k["d"], 16), int(k["p"], 16), int(k["q"], 16)
    res.check("ключ: kid", k["kid"], "test")
    res.check("ключ: e", e, 65537)
    res.check("ключ: 3072 бита", n.bit_length(), 3072)
    res.ok("ключ: n = p·q", p * q == n)
    lam = (p - 1) * (q - 1) // math.gcd(p - 1, q - 1)
    res.ok("ключ: d·e ≡ 1 (mod λ)", (d * e) % lam == 1)
    res.ok("ключ: помечен тестовым", "ТЕСТОВЫЙ" in k.get("note", ""))

    parsed = {}
    for name in FILES:
        got = _check_envelope(res, name)
        if got is None:
            continue
        env, payload, sig = got
        claim = _check_claim(res, name, payload)
        parsed[name] = (env, payload, sig, claim)

    if set(parsed) != set(FILES):
        return
    valid, expired, trial = parsed["valid"], parsed["expired"], parsed["trial"]
    bad, tamp, nokid = parsed["bad-sig"], parsed["tampered"], parsed["unknown-kid"]

    res.ok("kid = test у всех, кроме unknown-kid",
           all(parsed[x][0]["kid"] == "test" for x in FILES if x != "unknown-kid"))
    res.ok("unknown-kid: kid чужой", nokid[0]["kid"] != "test", nokid[0]["kid"])
    res.check("unknown-kid: claim и подпись — как у valid",
              (nokid[1], nokid[2]), (valid[1], valid[2]))
    res.check("bad-sig: claim — как у valid", bad[1], valid[1])
    res.check("bad-sig: ровно один другой байт подписи", _diff_bytes(bad[2], valid[2]), 1)
    res.check("tampered: подпись — как у valid", tamp[2], valid[2])
    res.check("tampered: ровно один другой байт claim", _diff_bytes(tamp[1], valid[1]), 1)

    now = datetime.now(timezone.utc)
    res.ok("valid: действует по настоящим часам", _ts(valid[3]["valid_until"]) > now)
    res.ok("expired: льгота прошла по настоящим часам", _ts(expired[3]["grace_until"]) < now)
    for name, c in (("valid", valid[3]), ("expired", expired[3])):
        res.check(f"{name}: standard — льгота 14 дней",
                  _ts(c["grace_until"]) - _ts(c["valid_until"]), 14 * DAY)
        res.check(f"{name}: plan", c["plan"], "standard")
    res.check("trial: plan", trial[3]["plan"], "trial")
    res.check("trial: idno ещё не назван", trial[3]["idno"], "")
    res.check("trial: 14 дней", _ts(trial[3]["valid_until"]) - _ts(trial[3]["issued_at"]), 14 * DAY)
    res.check("trial: льгота 3 дня (решение 24.09)",
              _ts(trial[3]["grace_until"]) - _ts(trial[3]["valid_until"]), 3 * DAY)
    res.ok("одна клиника во всех файлах",
           len({parsed[x][3]["clinic_id"] for x in FILES}) == 1)
    res.check("seq растёт: trial < expired < valid",
              [trial[3]["seq"], expired[3]["seq"], valid[3]["seq"]], [1, 2, 3])
