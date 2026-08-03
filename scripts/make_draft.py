"""Создаёт ЧЕРНОВИК релиза и заливает в него программу — без веб-формы.

    python scripts/make_draft.py v1.10.4

Зачем: форма на сайте молча не сохраняла черновик, и понять причину по ней
нельзя. Здесь каждый шаг отвечает кодом, и любая ошибка называется вслух.

Черновик виден только тому, у кого есть доступ на запись, — клиники его не
получат. Это и есть песочница: обновление сначала приезжает на свою машину.

Скрипт можно запускать повторно: существующий черновик и уже залитый файл
он находит и переиспользует, второй раз ничего не создаётся.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import urllib.error
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = "olegbacalu-maker/dental-booking-bot"
API = f"https://api.github.com/repos/{REPO}"
ROOT = pathlib.Path(__file__).resolve().parents[1]
ASSET = ROOT / "dist" / "DentPilot.exe"   # ровно это имя ищет программа

CANDIDATES = [
    pathlib.Path(r"C:\Users\Public\DentPilot"),
    pathlib.Path(r"C:\DentPilot"),
    pathlib.Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "DentPilot",
]


def find_token() -> str:
    env = (os.environ.get("DENTART_UPDATE_TOKEN") or "").strip().strip("\"'")
    if env:
        return env
    for d in CANDIDATES:
        f = d / "dental.env"
        if not f.exists():
            continue
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            s = line.strip()
            if s.startswith("DENTART_UPDATE_TOKEN=") and not s.startswith("#"):
                val = s.split("=", 1)[1].strip().strip("\"'")
                if val:
                    return val
    return ""


TOKEN = find_token()


def scrub(text: str) -> str:
    """Токен не должен попасть ни в вывод, ни в текст ошибки."""
    return text.replace(TOKEN, "***") if TOKEN else text


def call(url: str, method: str = "GET", body: bytes | None = None,
         ctype: str = "application/json"):
    req = urllib.request.Request(url, data=body, method=method, headers={
        "User-Agent": "dentpilot-make-draft",
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {TOKEN}",
    })
    if body is not None:
        req.add_header("Content-Type", ctype)
    with urllib.request.urlopen(req, timeout=300) as r:
        raw = r.read()
        return json.loads(raw) if raw else {}


def find_draft(tag: str) -> dict | None:
    """Ищем через GraphQL: REST-список на этом репозитории теряет релизы."""
    q = ('{ repository(owner:"%s", name:"%s") { releases(first:100, '
         'orderBy:{field:CREATED_AT, direction:DESC}) { nodes '
         '{ databaseId tagName isDraft } } } }' % tuple(REPO.split("/")))
    req = urllib.request.Request(
        "https://api.github.com/graphql", data=json.dumps({"query": q}).encode(),
        headers={"User-Agent": "dentpilot-make-draft",
                 "Content-Type": "application/json",
                 "Authorization": f"Bearer {TOKEN}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    if data.get("errors"):
        return None
    for n in data["data"]["repository"]["releases"]["nodes"]:
        if n["tagName"] == tag and n["isDraft"]:
            return call(f"{API}/releases/{n['databaseId']}")
    return None


def main(tag: str) -> int:
    if not TOKEN:
        print("✗ Токен не найден. Он нужен, чтобы создать черновик.")
        print("  Ожидается строка DENTART_UPDATE_TOKEN=... в dental.env "
              "установленной программы.")
        return 1
    if not ASSET.exists():
        print(f"✗ Нет файла {ASSET}")
        print("  Сначала соберите программу: .\\Build-Installer.ps1")
        return 1

    try:
        call(f"{API}/git/ref/tags/{tag}")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f"✗ Тега {tag} нет на GitHub. Сначала: git push origin {tag}")
            return 1
        raise

    rel = find_draft(tag)
    if rel:
        print(f"Черновик {tag} уже есть (id {rel['id']}) — дополняю его.")
    else:
        print(f"Создаю черновик {tag} …")
        rel = call(f"{API}/releases", "POST", json.dumps({
            "tag_name": tag, "name": tag, "draft": True, "prerelease": False,
            "body": "Черновик для проверки обновления. Клиникам не виден.",
        }).encode())
        print(f"  создан, id {rel['id']}")

    # файл с таким именем мог остаться от прошлой попытки — он не перезапишется
    for a in rel.get("assets", []):
        if a["name"].lower() == ASSET.name.lower():
            if a.get("state") == "uploaded" and a.get("size") == ASSET.stat().st_size:
                print(f"  {ASSET.name} уже залит и совпадает по размеру — пропускаю")
                break
            print(f"  удаляю прошлый {a['name']} ({a.get('state')})")
            call(f"{API}/releases/assets/{a['id']}", "DELETE")
    else:
        size = ASSET.stat().st_size
        print(f"Заливаю {ASSET.name} ({size / 1024 / 1024:.1f} MB) — это небыстро …")
        up = rel["upload_url"].split("{")[0] + f"?name={ASSET.name}"
        a = call(up, "POST", ASSET.read_bytes(), "application/octet-stream")
        print(f"  залит: {a.get('name')} состояние {a.get('state')}")

    got = find_draft(tag)
    if not got:
        print("\n✗ Черновик создан, но обратно не читается. Это уже сторона GitHub.")
        return 1
    names = [(x["name"], x.get("state")) for x in got.get("assets", [])]
    ok = any(n.lower() == ASSET.name.lower() and st == "uploaded" for n, st in names)
    print(f"\n{'✓' if ok else '✗'} Черновик {tag}: файлы {names or 'нет'}")
    if ok:
        print("  Программа на этой машине увидит обновление при следующей проверке.")
        print("  Клиникам он не виден — у них нет токена.")
    return 0 if ok else 1


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Укажите тег, например:  python scripts/make_draft.py v1.10.4")
        sys.exit(2)
    try:
        sys.exit(main(sys.argv[1].strip()))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = scrub(e.read().decode("utf-8", "replace"))[:400]
        except Exception:  # noqa: BLE001
            pass
        print(f"\n✗ GitHub отказал: HTTP {e.code}\n{detail}")
        sys.exit(1)
    except Exception as e:  # noqa: BLE001
        print(f"\n✗ Не получилось: {scrub(repr(e))}")
        sys.exit(1)
