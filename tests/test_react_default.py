# -*- coding: utf-8 -*-
"""Чистая установка открывается на React — контракт, а не намерение.

Решение Олега 21.09.2026: программы на целевой машине ещё нет, живых профилей
нет, сохранять нечего — значит и выката нет. **React становится частью готового
продукта**, а `REACT_SCREENS` остаётся списком РЕАЛИЗОВАННЫХ поверхностей, а не
механизмом поэтапного включения.

Отсюда ровно один вопрос, который надо закрыть до финального установщика:

    чистая установка → React ON → все реализованные поверхности React
                                → остальные страницы остаются серверными

⚠️ Профиль здесь — НАСТОЯЩИЙ `bot/app/clinic_new.json`, тот самый, который
лаунчер кладёт новой клинике. Своя фикстура проверяла бы свою выдумку: ключа
`ui` в ней нет, и именно его отсутствие и есть проверяемое условие.
⛔ Фикстура прогона (`clinic_test.json`) гасит React ЯВНО — там эталоном служит
старая страница. Поэтому набор берёт профиль новой клиники, а не общий.

⭐ Список экранов берётся из `parity_audit`, а он — из `REACT_SCREENS` разбором.
Рукописный список в наборе разошёлся бы с кодом молча: новая поверхность просто
не проверялась бы, а набор оставался зелёным.
"""
from __future__ import annotations

import json
import pathlib
import re
import shutil
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "bot"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

from app.core import auth  # noqa: E402
from harness import BOT, Client, Result, Server, clinic_today  # noqa: E402

PIN = "43219876"
MOUNT = 'data-screen="'


def _fresh(dir_: pathlib.Path) -> None:
    """Папка так, как её застаёт ПЕРВЫЙ запуск у новой клиники."""
    shutil.copy(BOT / "app" / "clinic_new.json", dir_ / "clinic.json")
    # Предусловия двух экранов: сеть живёт только у настольного издания,
    # безопасность — только там, где заведён `auth.json`. Без них они уводят
    # на хаб редиректом, и это не дефект (разбор — `scripts/mount_sweep.py`).
    (dir_ / "dental.env").write_text("TELEGRAM_TOKEN=\nADMIN_KEY=\n", encoding="utf-8")
    users = [{"id": "dir", "role": auth.ROLE_DIRECTOR, "name": "Director",
              **auth._secret_fields(PIN)}]
    (dir_ / "auth.json").write_text(
        json.dumps({"v": 2, "cookie_key": "fresh" * 12, "users": users}, indent=1),
        encoding="utf-8")


def _ids(c: Client, day: str) -> dict:
    c.post("/admin/add", adate=day, atime="09:00", adoctor="d1",
           aservice="consult", aname="Proba Noua", aphone="069000077",
           back="/admin/all")
    rows = json.loads(c.get("/api/patients?q=Proba").body)["data"]["rows"]
    today = json.loads(c.get("/api/doctors/d1").body)["data"]["today"]
    return {"pid": str(rows[0]["id"]) if rows else "",
            "dk": "d1",
            "appt_id": str(today[0]["id"]) if today else ""}


def _fill(path: str, ids: dict) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: ids.get(m.group(1), ""), path)


def suite_fresh(res: Result) -> None:
    """Новая клиника видит React везде, где он реализован."""
    import parity_audit
    import screen_map

    rows = [r for r in parity_audit.audit() if r["path"]]
    res.ok("аудит дал экраны", len(rows) >= 20,
           f"экранов {len(rows)} — список пуст, проверки ниже ничего не значат")

    with tempfile.TemporaryDirectory(prefix="dp_fresh_") as td:
        dir_ = pathlib.Path(td)
        _fresh(dir_)
        day = clinic_today().isoformat()
        with Server(dir_=dir_,
                    env={"DENTART_ENV_FILE": str(dir_ / "dental.env")}) as s:
            c = Client(s.url).login(PIN)
            res.check("вход ПИНом состоялся", c.get("/admin").status, 200)
            ids = _ids(c, day)

            bad = []
            for r in rows:
                path = _fill(r["path"], ids)
                got = c.get(path)
                if got.status != 200:
                    bad.append(f"{r['screen']}: HTTP {got.status} на {path}")
                elif f'{MOUNT}{r["screen"]}"' not in got.body:
                    m = re.search(r'data-screen="([^"]+)"', got.body)
                    bad.append(f"{r['screen']}: отдана поверхность "
                               f"{m.group(1) if m else 'старая страница'}")
            res.ok(f"все {len(rows)} реализованных поверхностей — React", not bad,
                   "; ".join(bad[:6]))

            # ⭐ И обратная половина, без которой первая ничего не стоит: экран,
            # которого в React НЕТ, обязан остаться серверным. Печатные листы и
            # аварийные страницы живут вне бандла ПО ЗАМЫСЛУ — страница, которая
            # обязана открыться без бандла, в бандле жить не может.
            react_paths = {r["path"] for r in rows}
            checked, wrong = 0, []
            for route in screen_map.routes()[0]:
                if (route["method"] != "GET" or route["kind"] != "HTML"
                        or route["path"] in react_paths):
                    continue
                path = _fill(route["path"], ids)
                if "{" in path or not path.startswith("/admin"):
                    continue
                got = c.get(path)
                if got.status != 200:
                    continue        # 303/404 — своё предусловие, не наш вопрос
                checked += 1
                if MOUNT in got.body:
                    wrong.append(route["path"])
            res.ok("серверные страницы проверены", checked >= 5,
                   f"проверено {checked} — обход ничего не нашёл")
            res.ok("нереализованные экраны остались серверными", not wrong,
                   "узел React там, где экрана нет: " + ", ".join(wrong))

            # ⚠️ Выход для регистратуры обязан работать и в продукте: один
            # запрос старой страницы без правки профиля.
            legacy = c.get("/admin/settings/clinic?ui=legacy")
            res.ok("?ui=legacy возвращает старую страницу на один запрос",
                   legacy.status == 200 and MOUNT not in legacy.body,
                   f"HTTP {legacy.status}, узел React {'есть' if MOUNT in legacy.body else 'нет'}")


def suite_switch_off(res: Result) -> None:
    """Аварийный выключатель: пустой список гасит React везде.

    ⛔ Это НЕ выкат и не канарейка. Это ответ на вопрос «что делать, если у
    клиники новый интерфейс подвёл, а поддержка на телефоне»: одна строка в
    профиле, без сборки и без обновления.
    """
    with tempfile.TemporaryDirectory(prefix="dp_off_") as td:
        dir_ = pathlib.Path(td)
        _fresh(dir_)
        cfg = json.loads((dir_ / "clinic.json").read_text(encoding="utf-8"))
        cfg["ui"] = {"react": []}
        (dir_ / "clinic.json").write_text(json.dumps(cfg, ensure_ascii=False),
                                          encoding="utf-8")
        with Server(dir_=dir_) as s:
            c = Client(s.url).login(PIN)
            got = c.get("/admin/settings/clinic")
            res.ok("пустой список гасит React", MOUNT not in got.body,
                   "узел React остался при явно выключенном интерфейсе")

        cfg["ui"] = {"react": False}
        (dir_ / "clinic.json").write_text(json.dumps(cfg, ensure_ascii=False),
                                          encoding="utf-8")
        with Server(dir_=dir_) as s:
            c = Client(s.url).login(PIN)
            got = c.get("/admin/settings/clinic")
            # ⚠️ `false` — понятная человеку запись, и падать на ней нельзя:
            # `screen in False` был бы отказом всей админки у клиники.
            res.check("«react: false» не роняет админку", got.status, 200)
            res.ok("и тоже гасит React", MOUNT not in got.body,
                   "булев выключатель не сработал")
