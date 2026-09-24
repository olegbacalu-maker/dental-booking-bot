"""Сервер отдельный: ни одного импорта из движка, версии FastAPI и uvicorn одни."""
import ast
import re

from harness import CLOUD, ROOT, Result

ALLOWED = {"argparse", "base64", "calendar", "contextlib", "dataclasses", "datetime", "getpass", "hashlib",
           "hmac", "html",
           "json", "logging", "os", "pathlib", "re", "secrets", "smtplib", "sqlite3", "sys",
           "time", "email", "urllib", "fastapi", "cryptography", "__future__"}


def suite(res: Result) -> None:
    bad = []
    for f in sorted((CLOUD / "app").glob("*.py")):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names = [node.module or ""]
            for n in names:
                if n.split(".")[0] not in ALLOWED:
                    bad.append(f"{f.name}: {n}")
    res.check("cloud/app импортирует только stdlib, fastapi и cryptography", bad, [])
    res.ok("cloud/app не знает про bot/",
           not any("bot" in n or "engine" in n for n in bad))
    want = {}
    for line in (ROOT / "bot" / "requirements-desktop.txt").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^(fastapi|uvicorn)==(\S+)", line.strip())
        if m:
            want[m.group(1)] = m.group(2)
    got = {}
    for line in (CLOUD / "requirements.txt").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^(fastapi|uvicorn)==(\S+)", line.strip())
        if m:
            got[m.group(1)] = m.group(2)
    res.check("fastapi и uvicorn — те же версии, что у движка", got, want)
