# -*- coding: utf-8 -*-
"""Тестовый ключ и фикстуры файла лицензии — `tests/fixtures/license/`.

    python scripts\\license_fixtures.py keygen   # новый ТЕСТОВЫЙ ключ; делается один раз
    python scripts\\license_fixtures.py build    # переписать фикстуры и сверить с openssl
    python scripts\\license_fixtures.py check    # ничего не писать: лежит ли то, что собрал бы build

Контракт — `docs/dentpilot-2/cloud.md` › «Файл лицензии». Здесь ОДНА
стандартная библиотека: простые числа, DER, PEM, подпись PKCS#1 v1.5 — всё
своё, чтобы фикстуры можно было пересобрать на любой машине без `pip`, как и
весь прогон тестов (`tests/harness.py`).

⭐ Своя подпись не судит сама себя: каждый правильно подписанный файл сверяется
с `openssl dgst -sha256 -verify`, каждый испорченный — им же отвергается.
Без openssl `build` и `check` отказывают; `--no-openssl` снимает сверку явно
и печатает об этом. Приватный PEM для openssl собирается во временную папку
и там же стирается — в репозитории приватный ключ лежит только числами
(`test-key.json`), чтобы ни один сканер секретов не принял ТЕСТОВЫЙ ключ за
настоящий.

⛔ Ключ `kid = test` — только для прогонов. В таблицу ключей собранной
программы он не попадает; как его подкладывают тесты — решение L2.

⚠️ `build` детерминирован при неизменном ключе: PKCS#1 v1.5 без случайности,
даты в claim зафиксированы. Поэтому `check` может сравнивать файлы побайтно
и красное у него значит «фикстуры разошлись со схемой или с генератором».
"""
import argparse
import base64
import hashlib
import json
import math
import os
import pathlib
import secrets
import shutil
import subprocess
import sys
import tempfile
import textwrap

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "license"
KEY_FILE = FIXTURES / "test-key.json"

KID = "test"
BITS = 3072
E = 65537
# DigestInfo для SHA-256 (RFC 8017, §9.2, примечание 1): SEQUENCE { AlgId sha256, NULL }, OCTET STRING(32)
DIGESTINFO_SHA256 = bytes.fromhex("3031300d060960864801650304020105000420")
OID_RSA = bytes.fromhex("06092a864886f70d010101")   # 1.2.840.113549.1.1.1 rsaEncryption

# ---------- base64url без «=» (RFC 4648 §5) ----------


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def unb64u(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


# ---------- простые числа и ключ ----------

_SMALL_PRIMES = [p for p in range(3, 2000, 2)
                 if all(p % q for q in range(3, int(p ** 0.5) + 1, 2))]


def _probable_prime(n: int, rounds: int = 32) -> bool:
    """Пробное деление, потом Миллер–Рабин со случайными основаниями."""
    if n < 2:
        return False
    for p in _SMALL_PRIMES:
        if n % p == 0:
            return n == p
    d, r = n - 1, 0
    while d % 2 == 0:
        d //= 2
        r += 1
    for _ in range(rounds):
        a = 2 + secrets.randbelow(n - 3)
        x = pow(a, d, n)
        if x in (1, n - 1):
            continue
        for _ in range(r - 1):
            x = pow(x, 2, n)
            if x == n - 1:
                break
        else:
            return False
    return True


def _gen_prime(bits: int) -> int:
    # два старших бита выставлены: произведение двух таких простых — ровно 2*bits бит
    while True:
        c = secrets.randbits(bits) | (1 << (bits - 1)) | (1 << (bits - 2)) | 1
        if _probable_prime(c):
            return c


def keygen(bits: int = BITS, e: int = E) -> dict:
    half = bits // 2
    while True:
        p, q = _gen_prime(half), _gen_prime(half)
        if p == q or math.gcd(e, p - 1) != 1 or math.gcd(e, q - 1) != 1:
            continue
        n = p * q
        if n.bit_length() != bits:
            continue
        lam = (p - 1) * (q - 1) // math.gcd(p - 1, q - 1)
        d = pow(e, -1, lam)
        return {"kid": KID, "bits": bits, "e": e,
                "n": format(n, "x"), "d": format(d, "x"),
                "p": format(p, "x"), "q": format(q, "x")}


def load_key() -> dict:
    k = json.loads(KEY_FILE.read_text(encoding="utf-8"))
    for f in ("n", "d", "p", "q"):
        k[f] = int(k[f], 16)
    return k


# ---------- DER и PEM (только то, что нужно openssl) ----------


def _der_len(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    b = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(b)]) + b


def _der(tag: int, body: bytes) -> bytes:
    return bytes([tag]) + _der_len(len(body)) + body


def _der_int(x: int) -> bytes:
    b = x.to_bytes(max(1, (x.bit_length() + 7) // 8), "big")
    if b[0] & 0x80:
        b = b"\x00" + b
    return _der(0x02, b)


def _der_seq(*items: bytes) -> bytes:
    return _der(0x30, b"".join(items))


def _pem(label: str, der: bytes) -> str:
    body = "\n".join(textwrap.wrap(base64.b64encode(der).decode("ascii"), 64))
    return f"-----BEGIN {label}-----\n{body}\n-----END {label}-----\n"


def private_pem(k: dict) -> str:
    """PKCS#1 RSAPrivateKey — то, что openssl читает как «RSA PRIVATE KEY»."""
    p, q, d = k["p"], k["q"], k["d"]
    return _pem("RSA PRIVATE KEY", _der_seq(
        _der_int(0), _der_int(k["n"]), _der_int(k["e"]), _der_int(d),
        _der_int(p), _der_int(q), _der_int(d % (p - 1)), _der_int(d % (q - 1)),
        _der_int(pow(q, -1, p))))


def public_pem(n: int, e: int) -> str:
    """SubjectPublicKeyInfo — «PUBLIC KEY» для `openssl dgst -verify`."""
    return _pem("PUBLIC KEY", _der_seq(
        _der_seq(OID_RSA, b"\x05\x00"),
        _der(0x03, b"\x00" + _der_seq(_der_int(n), _der_int(e)))))


# ---------- подпись ----------


def emsa_pkcs1_v15(digest: bytes, k: int) -> bytes:
    """Блок EMSA-PKCS1-v1_5 (RFC 8017 §9.2) для SHA-256; k — длина ключа в байтах.

    ⭐ Тот же блок СТРОИТ и программа при проверке (L2): сравнение с построенным,
    а не разбор расшифрованного — так у проверки нет паддинг-оракула.
    """
    t = DIGESTINFO_SHA256 + digest
    return b"\x00\x01" + b"\xff" * (k - 3 - len(t)) + b"\x00" + t


def sign(payload: bytes, k: dict) -> bytes:
    size = (k["n"].bit_length() + 7) // 8
    m = int.from_bytes(emsa_pkcs1_v15(hashlib.sha256(payload).digest(), size), "big")
    return pow(m, k["d"], k["n"]).to_bytes(size, "big")


def claim_bytes(claim: dict) -> bytes:
    """Как сервер ПИШЕТ claim. Программа этим правилом не пользуется: она
    проверяет байты, какие пришли (cloud.md › «Схема»)."""
    return json.dumps(claim, ensure_ascii=False, separators=(",", ":"),
                      sort_keys=True).encode("utf-8")


def envelope(payload: bytes, sig: bytes, kid: str = KID) -> str:
    return json.dumps({"v": 1, "kid": kid, "payload": b64u(payload),
                       "sig": b64u(sig)}, ensure_ascii=False, indent=2) + "\n"


# ---------- фикстуры ----------

CLINIC = {"clinic_id": "c_0123456789ab", "clinic": "Clinica Exemplu",
          "idno": "1234567890123", "country": "MD"}

# Даты ЗАФИКСИРОВАНЫ, а не «сегодня + N»: файл, который меняется при каждой
# сборке, нельзя ни сравнить побайтно, ни положить в отчёт об ошибке.
CLAIMS = {
    # единственный файл, годный и по настоящим часам — для дымовых проверок
    "valid": dict(CLINIC, plan="standard", seq=3,
                  issued_at="2026-09-24T12:00:00Z",
                  valid_until="2099-01-01T00:00:00Z",
                  grace_until="2099-01-15T00:00:00Z"),
    # срок и льгота прошли: readonly по настоящим часам
    "expired": dict(CLINIC, plan="standard", seq=2,
                    issued_at="2026-01-01T12:00:00Z",
                    valid_until="2026-02-01T00:00:00Z",
                    grace_until="2026-02-15T00:00:00Z"),
    # пробный: 14 дней + 3 дня льготы (решение 24.09), IDNO ещё не назван
    "trial": dict(CLINIC, idno="", plan="trial", seq=1,
                  issued_at="2026-09-24T12:00:00Z",
                  valid_until="2026-10-08T12:00:00Z",
                  grace_until="2026-10-11T12:00:00Z"),
}


def build_files(k: dict) -> dict[str, str]:
    """Имя файла → текст. Порождённые файлы считаются от `valid`."""
    out = {}
    signed = {}
    for name, claim in CLAIMS.items():
        payload = claim_bytes(claim)
        sig = sign(payload, k)
        signed[name] = (payload, sig)
        out[f"{name}.json"] = envelope(payload, sig)
    payload, sig = signed["valid"]
    # последний байт, а не первый: ±1 не выведет число за n, первый байт мог бы
    bad = sig[:-1] + bytes([sig[-1] ^ 0x01])
    out["bad-sig.json"] = envelope(payload, bad)
    # одна буква названия — JSON остаётся разборчивым, подпись перестаёт сходиться
    tampered = payload.replace(b"Clinica Exemplu", b"Clinica Exemplv", 1)
    assert tampered != payload and len(tampered) == len(payload)
    out["tampered.json"] = envelope(tampered, sig)
    out["unknown-kid.json"] = envelope(payload, sig, kid="nope")
    return out


# ---------- openssl как второй судья ----------


def find_openssl() -> str | None:
    if (p := shutil.which("openssl")):
        return p
    # Git for Windows несёт openssl, но не кладёт его в PATH
    for c in (r"C:\Program Files\Git\usr\bin\openssl.exe",
              r"C:\Program Files\Git\mingw64\bin\openssl.exe"):
        if os.path.exists(c):
            return c
    return None


def openssl_verify(openssl: str, pub_pem: pathlib.Path, payload: bytes,
                   sig: bytes, tmp: pathlib.Path) -> bool:
    (tmp / "payload.bin").write_bytes(payload)
    (tmp / "sig.bin").write_bytes(sig)
    r = subprocess.run([openssl, "dgst", "-sha256", "-verify", str(pub_pem),
                        "-signature", str(tmp / "sig.bin"), str(tmp / "payload.bin")],
                       capture_output=True, text=True)
    return r.returncode == 0 and "Verified OK" in r.stdout


# сверка: (файл, должен ли openssl принять подпись над ЕГО payload)
EXPECT = {"valid.json": True, "expired.json": True, "trial.json": True,
          "bad-sig.json": False, "tampered.json": False,
          "unknown-kid.json": True}   # подпись верна, неверен только kid — это отказ L2, не openssl


def cross_check(files: dict[str, str], k: dict, openssl: str) -> list[str]:
    bad = []
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="dp_lic_"))
    try:
        pub = tmp / "test-key.pub.pem"
        pub.write_text(public_pem(k["n"], k["e"]), encoding="ascii")
        for name, want in EXPECT.items():
            env = json.loads(files[name])
            got = openssl_verify(openssl, pub, unb64u(env["payload"]),
                                 unb64u(env["sig"]), tmp)
            mark = "принял" if got else "отверг"
            print(f"  openssl {mark:7} {name}" + ("" if got == want else "   ← НЕ ТО"))
            if got != want:
                bad.append(name)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return bad


def openssl_key_ok(k: dict, openssl: str) -> bool:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="dp_lic_"))
    try:
        priv = tmp / "test-key.pem"
        priv.write_text(private_pem(k), encoding="ascii")
        r = subprocess.run([openssl, "rsa", "-in", str(priv), "-check", "-noout"],
                           capture_output=True, text=True)
        return r.returncode == 0 and "RSA key ok" in r.stdout
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------- команды ----------


def _need_openssl(args) -> str | None:
    if args.no_openssl:
        print("⚠️ --no-openssl: подписи НЕ сверены вторым судьёй")
        return None
    if (o := find_openssl()) is None:
        sys.exit("openssl не найден: поставьте его (в Git for Windows он есть) "
                 "или снимите сверку ключом --no-openssl")
    return o


def cmd_keygen(args) -> int:
    if KEY_FILE.exists() and not args.force:
        sys.exit(f"{KEY_FILE} уже есть; новый ключ = все фикстуры заново "
                 f"и таблица ключей в тестах движка. Нужно — --force")
    openssl = _need_openssl(args)
    print(f"генерирую тестовый ключ RSA-{BITS}…")
    k = keygen()
    kk = dict(k, n=int(k["n"], 16), d=int(k["d"], 16), p=int(k["p"], 16), q=int(k["q"], 16))
    if openssl and not openssl_key_ok(kk, openssl):
        sys.exit("openssl не принял собранный PEM — DER-кодировщик или ключ неверны")
    FIXTURES.mkdir(parents=True, exist_ok=True)
    k["note"] = ("ТЕСТОВЫЙ ключ для прогонов, не секрет. В таблицу ключей собранной "
                 "программы не попадает. Пересобрать: scripts/license_fixtures.py keygen --force")
    KEY_FILE.write_text(json.dumps(k, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"записан {KEY_FILE.relative_to(ROOT)}" + (" — openssl: RSA key ok" if openssl else ""))
    return 0


def cmd_build(args) -> int:
    openssl = _need_openssl(args)
    k = load_key()
    files = build_files(k)
    if openssl and (bad := cross_check(files, k, openssl)):
        sys.exit(f"сверка с openssl не сошлась: {', '.join(bad)} — ничего не записано")
    for name, text in files.items():
        (FIXTURES / name).write_text(text, encoding="utf-8")
    print(f"записано {len(files)} файлов в {FIXTURES.relative_to(ROOT)}")
    return 0


def cmd_check(args) -> int:
    openssl = _need_openssl(args)
    k = load_key()
    files = build_files(k)
    drift = [n for n, t in files.items()
             if not (FIXTURES / n).exists()
             or (FIXTURES / n).read_text(encoding="utf-8") != t]
    for n in drift:
        print(f"  разошёлся с генератором: {n}")
    bad = cross_check(files, k, openssl) if openssl else []
    if drift or bad:
        print("КРАСНОЕ: фикстуры надо пересобрать (build) или чинить генератор")
        return 1
    print("фикстуры совпадают с генератором" + (", подписи сверены с openssl" if openssl else ""))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--no-openssl", action="store_true", help="не сверять со вторым судьёй")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("keygen", help="новый тестовый ключ")
    g.add_argument("--force", action="store_true")
    sub.add_parser("build", help="переписать фикстуры")
    sub.add_parser("check", help="сверить то, что лежит")
    args = ap.parse_args(argv)
    return {"keygen": cmd_keygen, "build": cmd_build, "check": cmd_check}[args.cmd](args)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
