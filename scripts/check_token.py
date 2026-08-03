"""Проверка канала «черновик» — работает ли токен и видит ли машина черновики.

    python scripts/check_token.py

Токен НЕ печатается и никуда не отправляется, кроме api.github.com. Скрипт
ищет его сам: сначала в переменной окружения, потом в dental.env установленной
программы. Нужен, чтобы не выяснять «а почему обновление не приходит» уже во
время выпуска.
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

# где программа может стоять: общая папка (с v1.10.0), старый путь, профиль
CANDIDATES = [
    pathlib.Path(r"C:\Users\Public\DentPilot"),
    pathlib.Path(r"C:\DentPilot"),
    pathlib.Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "DentPilot",
]


def find_token() -> tuple[str, str]:
    """(токен, откуда взят). Пустой токен = канал stable."""
    env = (os.environ.get("DENTART_UPDATE_TOKEN") or "").strip()
    if env:
        return env, "переменная окружения DENTART_UPDATE_TOKEN"
    for d in CANDIDATES:
        f = d / "dental.env"
        if not f.exists():
            continue
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line.startswith("DENTART_UPDATE_TOKEN=") and not line.startswith("#"):
                val = line.split("=", 1)[1].strip().strip("\"'")
                if val:
                    return val, str(f)
    return "", ""


def bad_chars(token: str) -> str:
    """Токен правят руками — кавычки и случайная кириллица тут обычное дело."""
    if not token.isascii():
        return "в токене есть не-латинские символы"
    if not token.isprintable():
        return "в токене есть непечатные символы (перенос строки, табуляция?)"
    return ""


def api(path: str, token: str):
    req = urllib.request.Request(
        API + path,
        headers={"User-Agent": "dentpilot-token-check",
                 "Accept": "application/vnd.github+json"},
    )
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def main() -> int:
    token, where = find_token()
    if not token:
        print("Токен не найден — машина работает в обычном канале (как клиника).")
        print("Проверенные места:")
        print("  · переменная окружения DENTART_UPDATE_TOKEN")
        for d in CANDIDATES:
            print(f"  · {d / 'dental.env'}" + ("" if (d / "dental.env").exists()
                                               else "   (файла нет)"))
        print("\nЭто НЕ ошибка: без токена программа обновляется только с "
              "опубликованных релизов.")
        return 0

    print(f"Токен найден: {where}")
    print(f"  длина {len(token)} симв., начинается на {token[:7]}…  (целиком не печатаем)")

    if (why := bad_chars(token)):
        print(f"\n✗ Токен не годится: {why}.")
        print("  Скорее всего он скопирован не целиком или вместе с кавычками.")
        print("  Строка должна быть ровно такой:  DENTART_UPDATE_TOKEN=github_pat_...")
        return 1

    try:
        rels = api("/releases?per_page=20", token)
    except urllib.error.HTTPError as e:
        print(f"\n✗ GitHub отказал: HTTP {e.code}")
        if e.code == 401:
            print("  Токен недействителен или отозван — создайте новый.")
        elif e.code == 403:
            print("  Токен есть, но прав не хватает. Нужно Contents: Read "
                  "для репозитория dental-booking-bot.")
        elif e.code == 404:
            print("  Репозиторий не виден этим токеном. В fine-grained проверьте, "
                  "что в «Only select repositories» выбран dental-booking-bot.")
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"\n✗ Не удалось обратиться к GitHub: {e}")
        return 1

    drafts = [r for r in rels if r.get("draft")]
    public = [r for r in rels if not r.get("draft")]
    print(f"\n✓ Доступ есть. Видно релизов: {len(rels)} "
          f"(опубликованных {len(public)}, черновиков {len(drafts)})")

    if drafts:
        for r in drafts:
            assets = [a.get("name") for a in r.get("assets", [])]
            print(f"  🧪 черновик {r.get('tag_name')} — файлы: "
                  f"{', '.join(assets) if assets else 'НЕТ (обновляться нечем)'}")
        print("\nМашина увидит черновик как обновление раньше клиник — "
              "это и есть песочница.")
    else:
        print("  Черновиков сейчас нет. Сделайте черновик релиза — и он появится "
              "здесь, а у клиник нет.")

    # контрольный вопрос: а без токена этот же черновик виден?
    try:
        anon = api("/releases?per_page=20", "")
        if drafts and not [r for r in anon if r.get("draft")]:
            print("\n✓ Проверено с другой стороны: без токена черновики не видны — "
                  "клиники их не получат.")
    except Exception:  # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
