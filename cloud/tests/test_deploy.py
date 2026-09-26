"""Прод (L10): копия базы, её проверка, учение по восстановлению, проверка окружения, файлы развёртывания.

Учение здесь — то же, что на чистой машине по DEPLOY.md: копия живой базы под
работающим сервером, проверка копии (целостность, схема, подписи выдач),
сервер на копии в чистой папке, и главное — файл лицензии из копии байт в
байт тот же, что выдавал живой сервер.
"""
import os
import pathlib
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile

from harness import CLOUD, ROOT, Client, Result, Server, cid_from, free_port

sys.path.insert(0, str(CLOUD))
from app.auth import make_hash  # noqa: E402

DEPLOY = CLOUD / "deploy"


def _tools(s: Server, *args, env: dict | None = None) -> tuple[int, str]:
    p = subprocess.run([sys.executable, "-m", "app.tools", *args], cwd=str(CLOUD), env=env or s.env,
                       capture_output=True, text=True, encoding="utf-8", timeout=120)
    return p.returncode, p.stdout + p.stderr


def suite_backup(res: Result) -> None:
    keep = pathlib.Path(tempfile.mkdtemp(prefix="dp_restore_"))
    try:
        with Server() as s:
            c = Client(s.url).login()
            cid = cid_from(c.post("/admin/clinics", name="Clinica Backup", idno="1234567890123",
                                  email="backup@example.md").location)
            c.post(f"/admin/clinics/{cid}/issue", kind="trial")
            original = c.get(f"/admin/clinics/{cid}/issues/1/license.json").body
            bdir = s.dir / "backups"
            rc, out = _tools(s, "backup", "--dir", str(bdir), "--keep", "30")
            res.ok("копия живой базы под работающим сервером: код 0", rc == 0 and "копия:" in out, out[-300:])
            files = sorted(bdir.glob("cloud-*.db"))
            res.check("одна копия, один файл — без -wal/-shm рядом", [p.suffix for p in bdir.iterdir()], [".db"])
            rc, out = _tools(s, "verify-backup", str(files[0]))
            res.ok("проверка копии: целостность, схема, счётчики, подпись выдачи",
                   rc == 0 and "целостность: ok" in out and "клиник 1, выдач 1, платежей 0" in out
                   and "ok 1, битых 0" in out and "копия годится" in out, out)
            bad = s.dir / "bad.db"
            shutil.copyfile(files[0], bad)
            con = sqlite3.connect(bad)
            con.execute("UPDATE issues SET sig = substr(sig, 1, 10) || 'AAAA' || substr(sig, 15)")
            con.commit()
            con.close()
            rc, out = _tools(s, "verify-backup", str(bad))
            res.ok("подпись выдачи подменена — копия не годится", rc == 1 and "битых 1" in out and "НЕ годится" in out, out)
            trunc = s.dir / "trunc.db"
            trunc.write_bytes(files[0].read_bytes()[:1000])
            rc, out = _tools(s, "verify-backup", str(trunc))
            res.ok("обрезанный файл — не годится", rc == 1 and "НЕ годится" in out, out)
            rc, out = _tools(s, "verify-backup", str(s.dir / "нет-такого.db"))
            res.check("нет файла — код 1", rc, 1)
            for _ in range(3):
                _tools(s, "backup", "--dir", str(bdir), "--keep", "2")
            res.check("--keep 2: остались две последние", len(list(bdir.glob("cloud-*.db"))), 2)
            last = sorted(bdir.glob("cloud-*.db"))[-1]
            rc, out = _tools(s, "drill", str(last))
            res.ok("учение командой: сервер поднялся на копии, /health и вход",
                   rc == 0 and "учение: OK" in out and "/health 200" in out and "страница входа 200" in out, out)
            rc, out = _tools(s, "drill", str(bad))
            res.ok("учение на негодной копии — провал словами", rc == 1 and "не годится" in out, out)
            shutil.copyfile(last, keep / "cloud.db")
        # «чистая машина»: новый сервер, другая папка, та же копия
        with Server(env={"DP_CLOUD_DB": str(keep / "cloud.db")}) as s2:
            c2 = Client(s2.url).login()
            res.ok("восстановленный сервер: клиника на месте", "Clinica Backup" in c2.get("/admin").body)
            res.check("файл лицензии из копии — байт в байт",
                      c2.get(f"/admin/clinics/{cid}/issues/1/license.json").body, original)
            r = c2.post(f"/admin/clinics/{cid}/issue", kind="trial", reason="после восстановления")
            res.check("выдача продолжается с seq 2", r.location, f"/admin/clinics/{cid}?msg=issued")
            res.check("второй файл на месте", c2.get(f"/admin/clinics/{cid}/issues/2/license.json").status, 200)
    finally:
        shutil.rmtree(keep, ignore_errors=True)


def suite_check(res: Result) -> None:
    with Server() as s:
        rc, out = _tools(s, "check")
        res.ok("тестовое окружение: готово; ключ JSON и сухой прогон — предупреждениями",
               rc == 0 and "готово к работе" in out and "ключ в JSON" in out and "сухой прогон" in out
               and "целостность ok" in out, out)
        env = dict(s.env)
        env.update({"DP_ADMIN_HASH": "", "DP_LICENSE_KEY": "", "DP_MAIL_OUTBOX": "", "DP_SECRET": ""})
        rc, out = _tools(s, "check", env=env)
        res.ok("пустое окружение: три препятствия названы, секрет — предупреждением",
               rc == 1 and "не готово: 3" in out and "DP_LICENSE_KEY пуст" in out
               and "DP_ADMIN_HASH пуст" in out and "отправлять некуда" in out and "DP_SECRET пуст" in out, out)
        env = dict(s.env)
        env["DP_ADMIN_HASH"] = make_hash("", iters=1000)
        rc, out = _tools(s, "check", env=env)
        res.ok("хеш пустого пароля — препятствие", rc == 1 and "ПУСТОГО" in out, out)
        env = dict(s.env)
        env["DP_ADMIN_HASH"] = "md5$abc"
        rc, out = _tools(s, "check", env=env)
        res.ok("чужой формат хеша — препятствие", rc == 1 and "не похож" in out, out)
        env = dict(s.env)
        env.update({"DP_SMTP_HOST": "127.0.0.1", "DP_SMTP_PORT": str(free_port())})
        rc, out = _tools(s, "check", env=env)
        res.ok("SMTP не отвечает — препятствие", rc == 1 and "не отвечает" in out, out)
        env = dict(s.env)
        env.update({"DP_BASE_URL": "https://cloud.dentpilot.md", "DP_SECURE_COOKIES": "0"})
        rc, out = _tools(s, "check", env=env)
        res.ok("https без secure-куки — предупреждение, не препятствие", rc == 0 and "DP_SECURE_COOKIES" in out, out)
        env = dict(s.env)
        env["DP_LICENSE_KEY"] = str(s.dir / "нет.pem")
        rc, out = _tools(s, "check", env=env)
        res.ok("ключ не читается — препятствие", rc == 1 and "не прочитан" in out, out)


def suite_files(res: Result) -> None:
    config = (CLOUD / "app" / "config.py").read_text(encoding="utf-8")
    example = (DEPLOY / "cloud.env.example").read_text(encoding="utf-8")
    compose = (DEPLOY / "docker-compose.yml").read_text(encoding="utf-8")
    caddy = (DEPLOY / "Caddyfile").read_text(encoding="utf-8")
    unit = (DEPLOY / "dentpilot-cloud.service").read_text(encoding="utf-8")
    cron = (DEPLOY / "cron.example").read_text(encoding="utf-8")
    dockerfile = (CLOUD / "Dockerfile").read_text(encoding="utf-8")
    deploy_md = (CLOUD / "DEPLOY.md").read_text(encoding="utf-8")
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    ps1 = (DEPLOY / "run-windows.ps1").read_text(encoding="utf-8")

    in_config = set(re.findall(r'env\("(DP_[A-Z_]+)"', config))
    in_example = set(re.findall(r"^(DP_[A-Z_]+)=", example, re.M))
    res.check("cloud.env.example: каждая переменная config.py и ничего лишнего", in_example, in_config)
    res.ok("пример без значений секретов",
           all(re.search(rf"^{n}=\s*$", example, re.M) for n in ("DP_ADMIN_HASH", "DP_SECRET", "DP_SMTP_PASS")))
    res.ok("пример без комментариев после значения (env_file их не срезает)",
           not re.search(r"^DP_[A-Z_]+=.*#", example, re.M))
    res.ok("compose: секреты только через env_file",
           "env_file: cloud.env" in compose and not re.search(r"DP_(ADMIN_HASH|SECRET|SMTP_PASS)", compose))
    res.ok("compose: порт сервера не публикуется, ключ только для чтения",
           not re.search(r'"?8090:8090"?', compose) and ":/srv/keys:ro" in compose)
    port = re.search(r'"--port", "(\d+)"', dockerfile).group(1)
    res.ok("Dockerfile, compose и Caddyfile — один порт",
           f'"--port", "{port}"' in compose and f"reverse_proxy cloud:{port}" in caddy
           and f"127.0.0.1:{port}" in unit)
    host = re.search(r'"DP_BASE_URL", "https://([^"]+)"', config).group(1)
    res.ok("Caddyfile: домен из умолчания DP_BASE_URL", host in caddy and host in example)
    res.ok("Caddy: X-Forwarded-For принимается только за прокси",
           '"--proxy-headers", "--forwarded-allow-ips", "*"' in compose and "8090" not in compose.split("ports:")[1].split("volumes:")[0])
    res.ok("контейнер назван так, как зовёт cron",
           "container_name: dentpilot-cloud" in compose and "docker exec dentpilot-cloud" in cron)
    res.ok("cron: задача, копия и вывоз копии", "app.jobs daily" in cron and "app.tools backup" in cron and "backup.sh" in cron)
    res.ok("unit systemd: окружение из файла, не в юните", "EnvironmentFile=" in unit and "DP_ADMIN_HASH" not in unit)
    res.ok(".gitignore: cloud.env и backups", "cloud/deploy/cloud.env" in gitignore and "cloud/backups/" in gitignore)
    res.ok("DEPLOY.md называет каждую команду",
           all(cmd in deploy_md for cmd in ("keygen", "hash-password", "app.tools check", "app.tools backup",
                                            "verify-backup", "drill", "app.jobs daily")))
    res.ok("DEPLOY.md: три вещи для восстановления и вариант на Windows",
           "Три вещи" in deploy_md and "run-windows.ps1" in deploy_md and "Планировщик" in deploy_md)
    res.ok("run-windows.ps1: те же команды", all(x in ps1 for x in ("app.tools check", "app.tools backup", "app.jobs", "uvicorn")))
    # Бит исполняемости живёт в git (100755) — его и получает VPS при clone. У
    # Windows прав на исполнение в файловой системе нет вовсе, поэтому там
    # спрашиваем индекс git, а не диск.
    if os.name == "nt":
        mode = subprocess.run(["git", "ls-files", "-s", "deploy/backup.sh"], cwd=str(CLOUD),
                              capture_output=True, text=True).stdout.split(" ")[0]
        res.check("backup.sh исполняемый (режим в git)", mode, "100755")
    else:
        res.ok("backup.sh исполняемый", (DEPLOY / "backup.sh").stat().st_mode & 0o111 != 0)
