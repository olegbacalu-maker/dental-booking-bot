"""Ключ выдачи: приватный — только здесь, публичный — в программе (rsa_verify.KEYS).

Два формата на входе: PEM (боевой ключ, сделан `python -m app.tools keygen`)
и JSON с числами (тестовый ключ из tests/fixtures/license/test-key.json —
тот же, которым собраны фикстуры и который знают тесты движка). У JSON kid
лежит в файле, у PEM — в DP_LICENSE_KID.
"""
from __future__ import annotations

import json
import pathlib

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


class Key:
    def __init__(self, kid: str, private, n: int, e: int):
        self.kid, self.private, self.n, self.e = kid, private, n, e


def load(path: str, kid: str = "") -> Key:
    p = pathlib.Path(path)
    if p.suffix == ".json":
        k = json.loads(p.read_text(encoding="utf-8"))
        n, e, d = int(k["n"], 16), int(k["e"]), int(k["d"], 16)
        pp, q = int(k["p"], 16), int(k["q"], 16)
        priv = rsa.RSAPrivateNumbers(pp, q, d, d % (pp - 1), d % (q - 1), pow(q, -1, pp),
                                     rsa.RSAPublicNumbers(e, n)).private_key()
        return Key(str(k["kid"]), priv, n, e)
    priv = serialization.load_pem_private_key(p.read_bytes(), password=None)
    pub = priv.public_key().public_numbers()
    if not kid:
        raise ValueError("DP_LICENSE_KID пуст: у PEM-ключа kid задаётся окружением")
    return Key(kid, priv, pub.n, pub.e)


def generate(bits: int = 3072) -> tuple[bytes, int, int]:
    """Новый ключ: PEM (PKCS#8, без пароля — права 0600 на файле) и публичные числа."""
    priv = rsa.generate_private_key(public_exponent=65537, key_size=bits)
    pem = priv.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption())
    pub = priv.public_key().public_numbers()
    return pem, pub.n, pub.e


def public_snippet(kid: str, n: int, e: int) -> str:
    """Строка для таблицы KEYS в bot/app/core/rsa_verify.py."""
    return f'    "{kid}": (int("{n:x}", 16), {e}),'
