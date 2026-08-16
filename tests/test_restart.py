"""Перезапуск программы после настройки, которую читает ЛАУНЧЕР.

Сетевой доступ (LAN), токен бота и шифрование картотеки применяются только при
следующем старте, поэтому все три маршрута кончаются одним и тем же:
перезапустить программу и сказать человеку, что дальше. Здесь проверяется ровно
эта общая часть — она молчаливая с обеих сторон:

- лишний запуск не виден вовсе: задача планировщика заводилась ДВАЖДЫ подряд
  (маршрут звал `restart_app()`, а страница звала его второй раз), и спасал
  только `/f` в `schtasks /create` — то есть вторая задача молча затирала первую;
- отказ планировщика (политика домена, урезанные права, отключённая служба)
  уезжал в баннер «Setări salvate»: настройка сохранена, программа жива и
  работает по-старому, а человеку никто не сказал, что её надо закрыть и
  открыть.

⚠️ Сервер здесь не поднимается. Ветка, которую надо проверить, — НАСТОЛЬНАЯ
(`is_desktop()` = собранный exe), а харнесс поднимает уvicorn из исходников и в
неё не попадает никогда. Поэтому маршруты зовутся напрямую в ОТДЕЛЬНОМ процессе
(как suite_update в test_review3_auth): подмены `is_desktop`, планировщика и
`_exit_soon` не переживают проверку и не задевают соседние наборы.
"""
import json
import os
import subprocess

from harness import BOT, PYTHON, Result

_TOKEN = "123456789:AAExampleTokenAAExampleTokenAAExampleT"

_CODE = r'''
import asyncio, json, os, pathlib, sys, tempfile
sys.path.insert(0, r"%s")

tmp = pathlib.Path(tempfile.mkdtemp(prefix="dp_restart_"))
(tmp / "dental.env").write_text("", encoding="utf-8")
os.environ["DENTART_ENV_FILE"] = str(tmp / "dental.env")
os.environ["DATABASE_URL"] = "sqlite:///" + str(tmp / "dental.db")
os.environ.pop("DENTART_NO_RESTART", None)   # иначе restart_app выйдет раньше

from app import update as upd
from app.modules.settings import routes as st

# exe, рядом с которым restart_app пишет свой bat
exe = tmp / "DentPilot.exe"
exe.write_bytes(b"x")
sys.executable = str(exe)

spawns, exits, fail = [], [], [None]
upd.is_desktop = lambda: True                # настольное издание
upd._exit_soon = lambda: exits.append(1)     # гасить свой же процесс не будем
upd._spawn_via_scheduler = lambda bat, task: (spawns.append(task), fail[0])[1]
st.require = lambda *a, **kw: None           # права проверяет свой набор

TOKEN = "%s"


def call(coro):
    """Ответ маршрута в сравнимом виде. Страница может прийти и голой строкой
    (response_class=HTMLResponse собирает её уже в FastAPI) — и это тоже ответ,
    а не поломка теста."""
    r = asyncio.run(coro)
    if isinstance(r, str):
        return {"status": 200, "loc": "", "body": r}
    return {"status": r.status_code, "loc": r.headers.get("location", ""),
            "body": getattr(r, "body", b"").decode("utf-8", "replace")}


MANUAL = "Închideți programul"     # «закройте программу и откройте снова»
out = {}

# --- 1. планировщик отработал: ОДИН запуск на сохранение ---
for key, coro in (("lan", lambda: st.admin_lan_save(None, mode="on")),
                  ("tok", lambda: st.admin_telegram_save(None, token=TOKEN))):
    spawns.clear(); exits.clear()
    r = call(coro())
    out[key + "_spawns"] = len(spawns)
    out[key + "_exits"] = len(exits)
    out[key + "_status"] = r["status"]
    out[key + "_manual"] = MANUAL in r["body"]

# --- 2. планировщик отказал: тот же один запуск, но экран говорит правду ---
fail[0] = "planificatorul Windows nu a putut porni programul (schtasks /create, cod 1)"
for key, coro in (("lan_bad", lambda: st.admin_lan_save(None, mode="on")),
                  ("tok_bad", lambda: st.admin_telegram_save(None, token=TOKEN))):
    spawns.clear(); exits.clear()
    r = call(coro())
    out[key + "_spawns"] = len(spawns)
    out[key + "_exits"] = len(exits)
    out[key + "_status"] = r["status"]
    out[key + "_loc"] = r["loc"]
    out[key + "_manual"] = MANUAL in r["body"]

# --- 3. обратная полярность: издания без перезапуска остаются на баннере ---
upd.is_desktop = lambda: False
for key, coro in (("lan_dev", lambda: st.admin_lan_save(None, mode="off")),
                  ("tok_dev", lambda: st.admin_telegram_save(None, token=TOKEN))):
    spawns.clear()
    r = call(coro())
    out[key + "_spawns"] = len(spawns)
    out[key + "_status"] = r["status"]
    out[key + "_loc"] = r["loc"]

print(json.dumps(out))
''' % (str(BOT), _TOKEN)


_MEASURED: list = []          # один прогон подпроцесса на все наборы файла


def _run_code(res: Result) -> dict | None:
    """Все три набора читают ОДИН замер: подпроцесс поднимает приложение целиком
    (~секунда), а спрашиваем мы у него одно и то же."""
    if _MEASURED:
        return _MEASURED[0]
    p = subprocess.run([str(PYTHON), "-c", _CODE], cwd=str(BOT), text=True,
                       capture_output=True, env=dict(os.environ))
    if p.returncode != 0:
        res.failed.append(("перезапуск: запуск проверок", p.stderr[-600:]))
        _MEASURED.append(None)
        return None
    _MEASURED.append(json.loads(p.stdout.strip().splitlines()[-1]))
    return _MEASURED[0]


def suite_once(res: Result) -> None:
    """Сохранение = ОДИН заказ планировщику, а не два подряд."""
    v = _run_code(res)
    if v is None:
        return
    for key, what in (("lan", "доступ из сети"), ("tok", "токен бота")):
        res.check(f"{what}: задача планировщика заводится один раз",
                  v[key + "_spawns"], 1)
        res.check(f"{what}: программа гасится один раз", v[key + "_exits"], 1)
        res.check(f"{what}: человек получает экран перезапуска",
                  v[key + "_status"], 200)
        res.ok(f"{what}: и экран обещает автоматический перезапуск",
               not v[key + "_manual"],
               "перезапуск удался, а экран советует закрыть программу руками")


def suite_failed(res: Result) -> None:
    """Планировщик отказал — это видно на экране, а не только в логе.

    Настройка сохранена, программа жива и работает по-старому: применится она
    только после закрытия и открытия. Прежде маршрут отвечал баннером
    «Setări salvate» (и «Token salvat …» — этот хотя бы просил перезапустить),
    то есть человек уходил уверенный, что доступ из сети уже включён.
    """
    v = _run_code(res)
    if v is None:
        return
    for key, what in (("lan_bad", "доступ из сети"), ("tok_bad", "токен бота")):
        res.check(f"{what}: отказ не добавляет второй попытки",
                  v[key + "_spawns"], 1)
        res.check(f"{what}: программа не гасится", v[key + "_exits"], 0)
        res.check(f"{what}: отвечает экран, а не баннер «сохранено»",
                  v[key + "_status"], 200)
        res.ok(f"{what}: и он просит закрыть и открыть программу вручную",
               v[key + "_manual"],
               f"ответ {v[key + '_status']} {v[key + '_loc']!r} — отказ "
               f"планировщика потерялся по дороге к экрану")


def suite_dev_banner(res: Result) -> None:
    """Обратная полярность: там, где перезапуска нет ПО УСТРОЙСТВУ (запуск из
    исходников, облако), экран «закройте программу» врал бы — остаётся баннер."""
    v = _run_code(res)
    if v is None:
        return
    for key, what, msg in (("lan_dev", "доступ из сети", "ok_set"),
                           ("tok_dev", "токен бота", "ok_tok")):
        res.check(f"{what}: без настольного издания — редирект", v[key + "_status"], 303)
        res.ok(f"{what}: с баннером {msg}", f"msg={msg}" in v[key + "_loc"],
               f"location {v[key + '_loc']!r}")
        res.check(f"{what}: и планировщик не трогается", v[key + "_spawns"], 0)
