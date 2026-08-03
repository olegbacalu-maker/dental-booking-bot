"""Проверка ОПУБЛИКОВАННОГО релиза глазами установленной клиники.

Запускать сразу после публикации:  python scripts/check_release.py 1.11.0

Смысл: между «я нажал Publish» и «30 клиник качают обновление» нет ни одной
автоматической проверки, а цена ошибки — затёртая программа у клиники. Скрипт
спрашивает у GitHub ровно то же, что спрашивает update.py, и проверяет
инварианты, нарушение которых ломает клиники молча.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request

# вывод целиком на русском, а консоль Windows по умолчанию не UTF-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = "olegbacalu-maker/dental-booking-bot"
APP_ASSET = "dentpilot.exe"          # имя обязано быть ровно таким (см. update.py)
API = f"https://api.github.com/repos/{REPO}/releases"

# ⚠️ Черновики GitHub отдаёт ТОЛЬКО тому, у кого есть push-доступ. Без токена
# их не видно ни в /releases/latest (он их пропускает by design), ни в списке —
# поэтому «релиз не найден» и «релиз в черновике» анонимно неразличимы, и
# скрипт обязан говорить об этом прямо, а не выдумывать причину.
TOKEN = (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "").strip()

problems: list[str] = []
notes: list[str] = []


def bad(msg: str) -> None:
    problems.append(msg)


def api(path: str):
    req = urllib.request.Request(API + path,
                                 headers={"User-Agent": "dentpilot-release-check"})
    if TOKEN:
        req.add_header("Authorization", f"Bearer {TOKEN}")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def ver(tag: str) -> tuple:
    """Точная копия _ver() из update.py — сравнивать надо ТЕМ ЖЕ правилом."""
    parts = []
    for p in tag.lstrip("vV").split("."):
        digits = "".join(ch for ch in p if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple((parts + [0, 0, 0])[:3])


def main(expect: str | None) -> int:
    # latest = ровно то, что видит установленная клиника: не черновик, не pre-release
    rel = api("/latest")
    tag = rel.get("tag_name", "")
    print(f"latest = {tag}   ({rel.get('html_url','')})")
    print("доступ:", "с токеном (черновики видны)" if TOKEN
          else "анонимный (черновики НЕ видны)")

    if not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
        bad(f"тег {tag!r} — нужен строго vX.Y.Z (иначе сравнение версий у клиник врёт)")

    if expect:
        want = f"v{expect}"
        if tag != want:
            # Раньше здесь была проверка rel["draft"], но /releases/latest
            # черновики НЕ возвращает — она не срабатывала никогда, а сообщение
            # про «тег не совпадает» уводило от настоящей причины: забыли нажать
            # Publish. Ищем нужный тег в списке и называем состояние.
            found = next((r for r in api("?per_page=20")
                          if r.get("tag_name") == want), None)
            if found is None:
                if TOKEN:
                    bad(f"релиза {want} нет вообще — ни опубликованного, ни черновика")
                else:
                    bad(f"релиза {want} нет среди опубликованных. Скорее всего он "
                        f"ЧЕРНОВИК — анонимно API черновики не показывает. "
                        f"Нажмите Publish (или задайте GITHUB_TOKEN, чтобы скрипт "
                        f"мог это различить). Клиники сейчас видят {tag}")
            elif found.get("draft"):
                bad(f"релиз {want} существует, но он ЧЕРНОВИК — клиники его не "
                    f"видят вообще и продолжают сидеть на {tag}. Нажмите Publish")
            elif found.get("prerelease"):
                bad(f"релиз {want} помечен pre-release — /releases/latest его не "
                    f"возвращает, для клиник он невидим. Снимите отметку")
            else:
                bad(f"релиз {want} опубликован, но latest = {tag}. Метка latest "
                    f"считается по дате: скорее всего поверх выпущен более новый "
                    f"или у {want} более старая дата")
        elif ver(tag) != ver(expect):
            bad(f"по правилу сравнения тег {tag} != версия exe {expect}")

    assets = rel.get("assets", [])
    print(f"ассетов: {len(assets)}")
    for a in assets:
        print(f"   {a.get('name')}  {a.get('size')} б  state={a.get('state')}")

    exes = [a for a in assets if str(a.get("name", "")).lower().endswith(".exe")]
    if len(exes) != 1:
        bad(f"в релизе {len(exes)} файлов .exe, а должен быть РОВНО ОДИН. "
            "Уже установленные клиники выбирают ассет из списка и могут скачать "
            "не программу, а инсталлятор, затерев им себя. Инсталлятор кладите .zip")
    elif str(exes[0].get("name", "")).lower() != APP_ASSET:
        bad(f"единственный .exe называется {exes[0].get('name')!r}, а должен быть "
            f"ровно {APP_ASSET!r} — иначе обновление не найдёт файл и клиника "
            "застрянет на «версия объявлена, файла нет»")
    else:
        app = exes[0]
        if str(app.get("state", "")) != "uploaded":
            bad(f"ассет в состоянии {app.get('state')!r} — заливка не завершена")
        if int(app.get("size") or 0) < 20_000_000:
            bad(f"ассет всего {app.get('size')} байт — похоже, залился не целиком")
        if not app.get("digest"):
            notes.append("у ассета нет digest — клиент не сможет сверить контрольную сумму")
        else:
            print(f"digest: {app['digest']}")

    if not problems:
        print("\nOK — релиз выглядит так, как его ждёт установленная клиника.")
        if expect:
            print(f"     клиника на версии ниже {expect} увидит обновление; "
                  f"на {expect} и выше — нет.")
    else:
        print(f"\nПРОБЛЕМЫ ({len(problems)}):")
        for p in problems:
            print(f"  - {p}")
    for n in notes:
        print(f"  (!) {n}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else None))
