"""Служебные команды сервера.

    python -m app.tools hash-password            # спросит пароль, напечатает DP_ADMIN_HASH
    python -m app.tools keygen --kid 2026a --out /srv/dentpilot/keys/2026a.pem

`keygen` пишет приватный ключ с правами 0600 и печатает строку для таблицы
KEYS в bot/app/core/rsa_verify.py — единственное, что уезжает в программу.
⛔ Приватный ключ в репозиторий, в образ и в письмо не попадает никогда.
"""
from __future__ import annotations

import argparse
import getpass
import os
import pathlib
import sys

from . import auth, keys


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    h = sub.add_parser("hash-password")
    h.add_argument("password", nargs="?")
    g = sub.add_parser("keygen")
    g.add_argument("--kid", required=True, help="имя ключа, например 2026a")
    g.add_argument("--out", required=True, help="куда положить PEM")
    g.add_argument("--bits", type=int, default=3072)
    a = ap.parse_args(argv)
    if a.cmd == "hash-password":
        pw = a.password or getpass.getpass("Пароль администратора: ")
        print(auth.make_hash(pw))
        return 0
    pem, n, e = keys.generate(a.bits)
    out = pathlib.Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(pem)
    print(f"приватный ключ: {out} (0600)")
    print("строка для KEYS в bot/app/core/rsa_verify.py:")
    print(keys.public_snippet(a.kid, n, e))
    return 0


if __name__ == "__main__":
    sys.exit(main())
