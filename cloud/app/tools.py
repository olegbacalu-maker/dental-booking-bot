"""Служебные команды сервера — всё, что делается руками на машине, а не в админке.

    python -m app.tools hash-password                 # спросит пароль, напечатает DP_ADMIN_HASH
    python -m app.tools keygen --kid 2026a --out /srv/dentpilot/keys/2026a.pem
    python -m app.tools pubkey                        # ключ уже есть: его строка для KEYS ещё раз
    python -m app.tools check                         # окружение готово к работе? (код 1, если нет)
    python -m app.tools backup --dir /srv/data/backups --keep 30
    python -m app.tools verify-backup /srv/data/backups/cloud-20260924-060500.db
    python -m app.tools drill /srv/data/backups/cloud-20260924-060500.db   # учение по восстановлению

`keygen` пишет приватный ключ с правами 0600 и печатает строку для таблицы
KEYS в bot/app/core/rsa_verify.py — единственное, что уезжает в программу.
`pubkey` печатает ту же строку по ключу из DP_LICENSE_KEY — если ключ сделан
раньше, а строка не сохранилась; приватная часть файл не покидает.
⛔ Приватный ключ в репозиторий, в образ и в письмо не попадает никогда.

`backup` снимает согласованную копию живой базы (sqlite3 backup API, WAL не
мешает), проверяет её целостность и оставляет `--keep` последних.
`verify-backup` открывает копию только для чтения: целостность, версия
схемы, счётчики и подпись каждого выданного файла ключом из DP_LICENSE_KEY.
`drill` — учение: копия разворачивается в чистой временной папке, на ней
поднимается сервер на свободном порту, отвечает /health и страница входа.
То, что учение делает на сервере, тест cloud/tests/test_deploy.py делает
в CI на каждом прогоне.
"""
from __future__ import annotations

import argparse
import getpass
import os
import pathlib
import shutil
import smtplib
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timezone

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from . import auth, config, db, keys, license, mail, maib, trial

OK, WARN, BAD = "ok", "⚠", "✗"


# ---------- бэкап ----------


def backup(db_path: pathlib.Path, out_dir: pathlib.Path, keep: int = 30) -> pathlib.Path:
    """Согласованная копия живой базы в out_dir/cloud-ГГГГММДД-ЧЧММСС.db; старше keep штук — удаляются."""
    if not db_path.exists():
        raise FileNotFoundError(f"базы нет: {db_path}")
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    dst_path = out_dir / f"cloud-{stamp}.db"
    n = 1
    while dst_path.exists():                       # два бэкапа в одну секунду — редкость, но не ошибка
        dst_path = out_dir / f"cloud-{stamp}-{n}.db"
        n += 1
    src = sqlite3.connect(db_path, timeout=10)
    dst = sqlite3.connect(dst_path)
    try:
        src.backup(dst)
        dst.execute("PRAGMA journal_mode=DELETE")   # копия — один файл, без -wal/-shm рядом
    finally:
        dst.close()
        src.close()
    rep = verify_backup(dst_path, key=None)
    if rep["integrity"] != "ok":
        dst_path.unlink(missing_ok=True)
        raise RuntimeError(f"копия не прошла проверку целостности: {rep['integrity']}")
    if keep > 0:
        old = sorted(out_dir.glob("cloud-*.db"))[:-keep]
        for f in old:
            f.unlink()
    return dst_path


def _public(key: keys.Key | None):
    return rsa.RSAPublicNumbers(key.e, key.n).public_key() if key else None


def verify_backup(path: pathlib.Path, key: keys.Key | None) -> dict:
    """Отчёт о копии: integrity, version, счётчики, подписи (ok/bad/skipped)."""
    rep = {"integrity": "", "version": 0, "clinics": 0, "issues": 0, "payments": 0,
           "sig_ok": 0, "sig_bad": 0, "sig_skipped": 0}
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        rep["integrity"] = con.execute("PRAGMA integrity_check").fetchone()[0]
        if rep["integrity"] != "ok":
            return rep
        row = con.execute("SELECT value FROM schema_meta WHERE key='version'").fetchone()
        rep["version"] = int(row[0]) if row else 0
        for t in ("clinics", "issues", "payments"):
            rep[t] = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        pub = _public(key)
        for kid, payload, sig in con.execute("SELECT kid, payload, sig FROM issues"):
            if pub is None or key.kid != kid:
                rep["sig_skipped"] += 1
                continue
            try:
                pub.verify(_unb64u(sig), _unb64u(payload), padding.PKCS1v15(), hashes.SHA256())
                rep["sig_ok"] += 1
            except (InvalidSignature, ValueError):
                rep["sig_bad"] += 1
    except sqlite3.DatabaseError as e:
        rep["integrity"] = f"не база: {e}"
    finally:
        con.close()
    return rep


def _unb64u(s: str) -> bytes:
    import base64
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _key_or_none() -> keys.Key | None:
    if not config.LICENSE_KEY:
        return None
    return keys.load(config.LICENSE_KEY, config.LICENSE_KID)


def report_lines(rep: dict) -> list[str]:
    out = [f"целостность: {rep['integrity']}"]
    if rep["integrity"] == "ok":
        out.append(f"схема: версия {rep['version']} (у сервера {db.SCHEMA_VERSION})")
        out.append(f"клиник {rep['clinics']}, выдач {rep['issues']}, платежей {rep['payments']}")
        out.append(f"подписи выдач: ok {rep['sig_ok']}, битых {rep['sig_bad']}, без ключа {rep['sig_skipped']}")
    return out


def backup_ok(rep: dict) -> bool:
    return rep["integrity"] == "ok" and rep["sig_bad"] == 0 and rep["version"] <= db.SCHEMA_VERSION


# ---------- учение по восстановлению ----------


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def drill(backup_path: pathlib.Path, timeout: float = 40.0) -> tuple[bool, list[str]]:
    """Копия → чистая папка → сервер на свободном порту → /health и страница входа."""
    lines: list[str] = []
    rep = verify_backup(backup_path, _key_or_none())
    lines += report_lines(rep)
    if not backup_ok(rep):
        return False, lines + ["копия не годится — сервер на ней не поднимаем"]
    work = pathlib.Path(tempfile.mkdtemp(prefix="dp_drill_"))
    try:
        target = work / "cloud.db"
        shutil.copyfile(backup_path, target)
        port = _free_port()
        env = dict(os.environ)
        env.update({"DP_CLOUD_DB": str(target), "DP_SMTP_HOST": "", "DP_MAIL_OUTBOX": str(work / "outbox")})
        log = (work / "server.log").open("wb")
        proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port),
                                 "--log-level", "warning"],
                                cwd=str(pathlib.Path(__file__).resolve().parents[1]), env=env,
                                stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.time() + timeout
            health = None
            while time.time() < deadline and health is None:
                if proc.poll() is not None:
                    return False, lines + ["сервер упал при старте на копии — смотрите лог: " + str(work / "server.log")]
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as r:
                        health = r.status
                except Exception:  # noqa: BLE001 — ещё не поднялся
                    time.sleep(0.2)
            if health != 200:
                return False, lines + [f"сервер на копии не ответил на /health за {timeout:.0f} с"]
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/admin/login", timeout=5) as r:
                login = r.status
            lines.append(f"сервер поднялся на копии: /health {health}, страница входа {login}")
            return login == 200, lines
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
            log.close()
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ---------- проверка окружения ----------


def check() -> list[tuple[str, str]]:
    """Готовность окружения: (уровень, строка). Уровень ✗ — работать нельзя, ⚠ — можно, но с оговоркой."""
    out: list[tuple[str, str]] = []
    dbp = config.DB_PATH
    try:
        dbp.parent.mkdir(parents=True, exist_ok=True)
        probe = dbp.parent / ".dp_write_probe"
        probe.write_bytes(b"1")
        probe.unlink()
        if dbp.exists():
            integrity = _integrity(dbp)
            out.append((OK if integrity == "ok" else BAD, f"база {dbp}: целостность {integrity}"))
        else:
            out.append((OK, f"базы {dbp} ещё нет — создастся при старте"))
        free = shutil.disk_usage(dbp.parent).free // (1024 * 1024)
        out.append((OK if free >= 500 else WARN, f"свободно на диске: {free} МБ"))
    except OSError as e:
        out.append((BAD, f"папка базы {dbp.parent} недоступна для записи: {e}"))
    if not config.LICENSE_KEY:
        out.append((BAD, "DP_LICENSE_KEY пуст: файлы выдавать нечем (python -m app.tools keygen)"))
    else:
        try:
            k = keys.load(config.LICENSE_KEY, config.LICENSE_KID)
            mode = ""
            if os.name == "posix":
                bits = os.stat(config.LICENSE_KEY).st_mode & 0o777
                mode = f", права {bits:o}" + ("" if bits & 0o077 == 0 else " — должны быть 0600")
            out.append((OK if "должны" not in mode else WARN,
                        f"ключ выдачи kid={k.kid}, {k.n.bit_length()} бит{mode}"))
            if pathlib.Path(config.LICENSE_KEY).suffix == ".json":
                out.append((WARN, "ключ в JSON — это тестовый формат; боевой ключ делает keygen в PEM"))
        except (OSError, ValueError, KeyError) as e:
            out.append((BAD, f"ключ выдачи не прочитан: {e!r}"))
    if not config.ADMIN_HASH:
        out.append((BAD, "DP_ADMIN_HASH пуст: вход невозможен (python -m app.tools hash-password)"))
    elif config.ADMIN_HASH.count("$") != 3 or not config.ADMIN_HASH.startswith("pbkdf2-sha256$"):
        out.append((BAD, "DP_ADMIN_HASH не похож на pbkdf2-sha256$iters$salt$hex"))
    elif auth.check_password("", config.ADMIN_HASH):
        out.append((BAD, "DP_ADMIN_HASH — хеш ПУСТОГО пароля"))
    else:
        out.append((OK, f"администратор {config.ADMIN_USER}, хеш pbkdf2-sha256"))
    out.append((OK, "DP_SECRET задан: сессии переживут рестарт") if config.SECRET
               else (WARN, "DP_SECRET пуст: после рестарта сервера всех разлогинит"))
    if config.BASE_URL.startswith("https://") and not config.SECURE_COOKIES:
        out.append((WARN, "DP_SECURE_COOKIES не 1, а адрес https — кука пойдёт и по http"))
    if license.renew_offered():
        out.append((OK, f"автообновление: программы спрашивают {license.renew_url()}"))
    else:
        out.append((WARN, f"DP_BASE_URL={config.BASE_URL}: не https и не loopback — поле renew в файлы "
                          "не пишется, программы клиник не обновятся сами"))
    if maib.enabled():
        try:
            maib.token()
            out.append((OK, f"maib: токен получен, оплата картой включена ({config.MAIB_BASE_URL}); "
                            f"callback {config.BASE_URL.rstrip('/')}{maib.CALLBACK_PATH}"))
        except maib.MaibError as e:
            out.append((BAD, f"maib не отвечает: {e}"))
    else:
        out.append((WARN, "DP_MAIB_* пусты: оплата картой выключена, платежи только переводом"))
    # оба режима — законный выбор (боевой с 26.09 — auto): предупреждать не о чем
    out.append((OK,
                f"форма пробного {config.BASE_URL.rstrip('/')}/proba: режим {trial.mode()} "
                f"({'заявка ждёт админа' if trial.mode() == trial.MODE_APPROVE else 'файл уходит сразу'}), "
                f"уведомления на {config.TRIAL_NOTIFY}"))
    if config.SMTP_HOST:
        try:
            with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=10) as s:
                s.starttls()
            out.append((OK, f"почта: {config.SMTP_HOST}:{config.SMTP_PORT}, STARTTLS отвечает"))
        except (OSError, smtplib.SMTPException) as e:
            out.append((BAD, f"почта {config.SMTP_HOST}:{config.SMTP_PORT} не отвечает: {e!r}"))
    elif config.MAIL_OUTBOX:
        out.append((WARN, f"почта: сухой прогон, письма ложатся в {config.MAIL_OUTBOX}"))
    else:
        out.append((BAD, "ни DP_SMTP_HOST, ни DP_MAIL_OUTBOX: письма отправлять некуда"))
    b = config.BANK
    out.append((OK, f"реквизиты: {b['beneficiary']}, IBAN {b['iban']}") if b["iban"] and b["beneficiary"]
               else (WARN, "DP_BANK_* пусты: письма о платеже уйдут без реквизитов"))
    if not config.DECLARATION:
        out.append((WARN, "DP_DECLARATION пуст: письма с файлом лицензии уйдут без декларации "
                          "поставщика (Legea 195)"))
    elif mail.declaration() is None:
        out.append((WARN, f"DP_DECLARATION={config.DECLARATION}: файла нет или это не PDF — "
                          "письма с файлом лицензии уйдут без декларации"))
    else:
        out.append((OK, f"декларация поставщика {config.DECLARATION} едет в каждое письмо с файлом"))
    return out


def _integrity(dbp: pathlib.Path) -> str:
    """integrity_check живой базы обычным соединением: WAL и открытый сервер не мешают."""
    try:
        con = sqlite3.connect(dbp, timeout=10)
        try:
            return con.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            con.close()
    except sqlite3.DatabaseError as e:
        return f"не база: {e}"


# ---------- командная строка ----------


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    h = sub.add_parser("hash-password")
    h.add_argument("password", nargs="?")
    g = sub.add_parser("keygen")
    g.add_argument("--kid", required=True, help="имя ключа, например 2026a")
    g.add_argument("--out", required=True, help="куда положить PEM")
    g.add_argument("--bits", type=int, default=3072)
    sub.add_parser("pubkey", help="строка для KEYS программы — по ключу DP_LICENSE_KEY")
    sub.add_parser("check", help="окружение готово к работе?")
    b = sub.add_parser("backup", help="согласованная копия базы")
    b.add_argument("--dir", required=True, help="папка копий")
    b.add_argument("--keep", type=int, default=30, help="сколько последних копий оставить (0 — все)")
    v = sub.add_parser("verify-backup", help="проверить копию: целостность, схема, подписи")
    v.add_argument("file")
    d = sub.add_parser("drill", help="учение: поднять сервер на копии в чистой папке")
    d.add_argument("file")
    a = ap.parse_args(argv)

    if a.cmd == "hash-password":
        pw = a.password or getpass.getpass("Пароль администратора: ")
        print(auth.make_hash(pw))
        return 0
    if a.cmd == "keygen":
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
    if a.cmd == "pubkey":
        if not config.LICENSE_KEY:
            print("DP_LICENSE_KEY пуст: ключа нет (python -m app.tools keygen)")
            return 1
        try:
            k = keys.load(config.LICENSE_KEY, config.LICENSE_KID)
        except (OSError, ValueError, KeyError) as e:
            print(f"ключ выдачи не прочитан: {e!r}")
            return 1
        print("строка для KEYS в bot/app/core/rsa_verify.py:")
        print(keys.public_snippet(k.kid, k.n, k.e))
        return 0
    if a.cmd == "check":
        rows = check()
        for level, line in rows:
            print(f"{level:>2} {line}")
        bad = sum(1 for level, _ in rows if level == BAD)
        print("готово к работе" if not bad else f"не готово: {bad} препятств.")
        return 1 if bad else 0
    if a.cmd == "backup":
        try:
            p = backup(config.DB_PATH, pathlib.Path(a.dir), a.keep)
        except (OSError, RuntimeError, sqlite3.Error) as e:
            print(f"бэкап не сделан: {e}")
            return 1
        print(f"копия: {p} ({p.stat().st_size} байт)")
        return 0
    if a.cmd == "verify-backup":
        rep = verify_backup(pathlib.Path(a.file), _key_or_none())
        for line in report_lines(rep):
            print(line)
        ok = backup_ok(rep)
        print("копия годится" if ok else "копия НЕ годится")
        return 0 if ok else 1
    if a.cmd == "drill":
        ok, lines = drill(pathlib.Path(a.file))
        for line in lines:
            print(line)
        print("учение: OK" if ok else "учение: ПРОВАЛ")
        return 0 if ok else 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
