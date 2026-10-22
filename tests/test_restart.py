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
просьбы к оболочке (`sidecar.request_quit`) не переживают проверку и не задевают
соседние наборы.
"""
import json
import os
import subprocess
import tempfile

from harness import BOT, PYTHON, Result

_TOKEN = "123456789:AAExampleTokenAAExampleTokenAAExampleT"

_CODE = r'''
import asyncio, json, os, pathlib, sys
sys.path.insert(0, r"%s")

tmp = pathlib.Path(os.environ["DP_TEST_DIR"])   # папку заводит и сносит родитель
(tmp / "dental.env").write_text("", encoding="utf-8")
os.environ["DENTART_ENV_FILE"] = str(tmp / "dental.env")
os.environ["DATABASE_URL"] = "sqlite:///" + str(tmp / "dental.db")
os.environ.pop("DENTART_NO_RESTART", None)   # иначе restart_app выйдет раньше

from app import sidecar
from app import update as upd
from app.modules.settings import routes as st
from app.modules.settings import api as sapi
_real_spawn = upd._spawn_watch               # набор 4 зовёт настоящий

# оболочка, которую сторож поднимет обратно
exe = tmp / "DentPilot.exe"
exe.write_bytes(b"x")

spawns, exits, fail = [], [], [None]
upd.is_desktop = lambda: True                # настольное издание
# движок себя не гасит — просит оболочку закрыться; здесь просьбу считаем
sidecar.request_quit = lambda reason: (exits.append(reason), True)[1]
upd._spawn_watch = lambda result, task, label, copy: (spawns.append(task), fail[0])[1]
st.require = lambda *a, **kw: None           # права проверяет свой набор
sapi.api_require = lambda *a, **kw: None
_LAN = {}


async def _lan_body(_request):
    return dict(_LAN)


sapi.api_body = _lan_body


def lan_save(mode):
    """Сохранение сети — JSON API (старая форма /admin/lan/save снята 12.10).
    Тот же `_set_lan` и тот же `restart_app`; ответ — JSON с текстом."""
    _LAN["mode"] = mode
    return sapi.api_lan_save(None)


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
for key, coro in (("lan", lambda: lan_save("on")),
                  ("tok", lambda: st.admin_telegram_save(None, token=TOKEN))):
    spawns.clear(); exits.clear()
    r = call(coro())
    out[key + "_spawns"] = len(spawns)
    out[key + "_exits"] = len(exits)
    out[key + "_status"] = r["status"]
    out[key + "_manual"] = MANUAL in r["body"]

# --- 2. планировщик отказал: тот же один запуск, но экран говорит правду ---
fail[0] = "planificatorul Windows nu a putut porni programul (schtasks /create, cod 1)"
for key, coro in (("lan_bad", lambda: lan_save("on")),
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
for key, coro in (("lan_dev", lambda: lan_save("off")),
                  ("tok_dev", lambda: st.admin_telegram_save(None, token=TOKEN))):
    spawns.clear()
    r = call(coro())
    out[key + "_spawns"] = len(spawns)
    out[key + "_status"] = r["status"]
    out[key + "_loc"] = r["loc"]
    out[key + "_manual"] = MANUAL in r["body"]
    try:
        out[key + "_code"] = json.loads(r["body"]).get("code", "")
    except ValueError:
        out[key + "_code"] = ""

# --- 4. профиль заставки сторожа (12.10, 1.41.1): путь даёт лаунчер, и он не
# в папке данных; старый профиль в папке данных сносится при запуске сторожа ---
from app import restartwatch as rw
os.environ.pop("DENTART_WATCH_PROFILE", None)
out["watch_default"] = str(upd.watch_profile())
own = tmp / "local" / "DentPilot" / "webview-watch"
os.environ["DENTART_WATCH_PROFILE"] = str(own)
out["watch_launcher"] = str(upd.watch_profile())
out["watch_own"] = str(own)
out["work_dir"] = str(upd.work_dir())
old = upd.work_dir() / "watch-profile"
(old / "EBWebView").mkdir(parents=True, exist_ok=True)
(old / "EBWebView" / "Local State").write_text("{}", encoding="utf-8")
seen = {}


def fake_schtasks(task, command, arguments, proof, wait):
    seen["args"] = arguments
    return None


sidecar.shell_exe = lambda: exe
upd._watch_command = lambda copy: [str(exe)]
upd._schtasks_run = fake_schtasks
out["spawn"] = _real_spawn(None, "DentPilotRestart", "x", False)
out["old_gone"] = not old.exists()
# [метка, proof, task, итог, pid, label, цвет, профиль, команда…] — rw.argv_for
args = seen.get("args", [])
out["plan_profile"] = args[7] if len(args) > 7 and args[0] == rw.FLAG else ""

print(json.dumps(out))
''' % (str(BOT), _TOKEN)


_MEASURED: list = []          # один прогон подпроцесса на все наборы файла


def _run_code(res: Result) -> dict | None:
    """Все три набора читают ОДИН замер: подпроцесс поднимает приложение целиком
    (~секунда), а спрашиваем мы у него одно и то же."""
    if _MEASURED:
        return _MEASURED[0]
    # ⛔ Папку заводит и сносит РОДИТЕЛЬ: подпроцесс за собой не прибирал, и
    # каждый прогон оставлял в %TEMP% свою `dp_restart_*` (48 штук к 26.09).
    with tempfile.TemporaryDirectory(prefix="dp_restart_") as work:
        p = subprocess.run([str(PYTHON), "-c", _CODE], cwd=str(BOT), text=True,
                           capture_output=True,
                           env={**os.environ, "DP_TEST_DIR": work})
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
        res.check(f"{what}: оболочку просят закрыться один раз", v[key + "_exits"], 1)
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
        res.check(f"{what}: оболочку закрыться не просят", v[key + "_exits"], 0)
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
    # Токен — форма своей серверной страницы: редирект с баннером.
    res.check("токен бота: без настольного издания — редирект", v["tok_dev_status"], 303)
    res.ok("токен бота: с баннером ok_tok", "msg=ok_tok" in v["tok_dev_loc"],
           f"location {v['tok_dev_loc']!r}")
    res.check("токен бота: и планировщик не трогается", v["tok_dev_spawns"], 0)
    # Сеть — JSON API (старая форма снята 12.10): тот же смысл ответом.
    res.check("доступ из сети: без настольного издания — ответ «сохранено»",
              (v["lan_dev_status"], v["lan_dev_code"]), (200, "ok_set"))
    res.ok("доступ из сети: без экрана «закройте программу»",
           not v["lan_dev_manual"], "текст о ручном перезапуске там, где перезапуска нет")
    res.check("доступ из сети: и планировщик не трогается", v["lan_dev_spawns"], 0)


def suite_watch(res: Result) -> None:
    """Сторож перезапуска — договор движка с оболочкой (`app/restartwatch.py`):
    план и его аргументы `--watch`. Ждёт итога и поднимает программу сторож
    `shell/src/watch.rs` (сверка слов — `suite_watch_shell`, поведение —
    `cargo test` › `watch::tests`). Python-сторож снят 22.10.2026 с окном
    pywebview."""
    import pathlib
    import tempfile
    from app import restartwatch as rw

    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        plan = rw.Plan(proof=tmp / "DentPilotUpdate.run", task="DentPilotUpdate",
                       result=tmp / "install.result", pid=0, label="1.40.2 › 1.40.3",
                       primary="#0E9F8A", profile=tmp / "watch-profile",
                       launch=[str(tmp / "DentPilot.exe")])
        # ⚠️ Порядок полей — тот, что разбирает `watch.rs::parse` (его
        # `parses_python_argv` строит строку тем же порядком)
        res.check("аргументы --watch: метка, семь полей плана, команда запуска",
                  rw.argv_for(plan),
                  [rw.FLAG, str(plan.proof), "DentPilotUpdate", str(plan.result), "0",
                   "1.40.2 › 1.40.3", "#0E9F8A", str(plan.profile), str(tmp / "DentPilot.exe")])
        res.check("без итога (простой перезапуск) — `-`",
                  rw.argv_for(rw.Plan(plan.proof, plan.task, None, 7, "x", "#000000", plan.profile, ["a"]))[3],
                  rw.NO_RESULT)
        res.ok("Python-сторожа нет: разбора и ожидания в restartwatch не осталось",
               not any(hasattr(rw, n) for n in ("parse", "decide", "wait_for", "read_result",
                                                "pid_alive", "outcome_text")),
               "вернулась половина второго сторожа — она разойдётся с watch.rs молча")


    # Профиль заставки (12.10, 1.41.1): установщик выдаёт права `icacls /T` на
    # всю папку данных, и WebView2 заставки, писавший в ней же, ронял этот шаг
    # (канарейка 1.41.0). Подпроцесс — общий с наборами выше.
    m = _run_code(res)
    if m:
        res.check("без лаунчера — прежнее место (исходники, прогон)",
                  m["watch_default"], str(pathlib.Path(m["work_dir"]) / "watch-profile"))
        res.check("с лаунчером — его путь, а не папка данных",
                  m["watch_launcher"], m["watch_own"])
        res.ok("папка данных не содержит профиль сторожа",
               not m["watch_launcher"].startswith(m["work_dir"]), m["watch_launcher"])
        res.check("запуск сторожа прошёл", m["spawn"], None)
        res.check("сторож получил профиль лаунчера", m["plan_profile"], m["watch_own"])
        res.ok("старый профиль в папке данных снесён при запуске сторожа",
               m["old_gone"], "остался — icacls установщика снова обойдёт чужой кэш")


# ---------- оболочка Tauri (Т10, 18.10) ----------

_SHELL_CODE = r'''
import json, os, pathlib, sys
sys.path.insert(0, r"%s")
os.environ.pop("DENTART_NO_RESTART", None)
from app import update as upd
from app import paths, restartwatch as rw, sidecar

tmp = pathlib.Path(os.environ["DP_TEST_DIR"])
app_dir = tmp / "Program Files" / "DentPilot"
app_dir.mkdir(parents=True)
shell = app_dir / "DentPilot.exe"
shell.write_bytes(b"OBOLOCHKA")
where = {"shell": shell}
sidecar.shell_exe = lambda: where["shell"]
quits, runs = [], []
answer = {"quit": True}
sidecar.request_quit = lambda reason: (quits.append(reason), answer["quit"])[1]
upd.is_desktop = lambda: True
paths.is_frozen = lambda: True               # собранный движок: сторож — копия

def fake_schtasks(task, command, arguments, proof, wait):
    runs.append({"task": task, "command": command, "args": list(arguments)})
    return None
upd._schtasks_run = fake_schtasks
out = {}

def plan_of(r):
    # [метка, proof, task, итог, pid, label, цвет, профиль, команда…] — rw.argv_for
    a = r["args"]
    return {"task": r["task"], "command": r["command"], "flag": a[0], "launch": a[8:],
            "pid": int(a[4]), "result": None if a[3] == rw.NO_RESULT else a[3]}

# --- перезапуск: сторож — сама оболочка, уход — просьба оболочке ---
out["restart"] = upd.restart_app()
out["restart_runs"] = [plan_of(r) for r in runs]
out["restart_quits"] = list(quits)
del runs[:], quits[:]
answer["quit"] = False
out["restart_nopipe"] = upd.restart_app()
out["restart_nopipe_quits"] = list(quits)
answer["quit"] = True
del runs[:], quits[:]

# --- обновление: сторож — КОПИЯ оболочки в папке клиники ---
upd.STATE["latest"] = "v99.0.0"
res_file = upd.work_dir() / "install.result"
out["update_watch"] = upd._arm_restart_watch(res_file)
out["update_runs"] = [plan_of(r) for r in runs]
copy = upd.work_dir() / upd._WATCH_EXE
out["copy_is_shell"] = copy.exists() and copy.read_bytes() == b"OBOLOCHKA"
out["copy_path"] = str(copy)
del runs[:]

# --- оболочку не знаем (движок из исходников) — сторожа нет, программа жива ---
where["shell"] = None
out["no_shell"] = upd.restart_app()
out["no_shell_runs"], out["no_shell_quits"] = len(runs), list(quits)
out["parent"] = os.getppid()
out["shell_path"] = str(shell)
print(json.dumps(out))
''' % str(BOT)


def suite_watch_shell(res: Result) -> None:
    r"""Т10: сторож — сама оболочка `DentPilot.exe --watch`.

    Перезапуск — `{app}\DentPilot.exe --watch`, обновление — её КОПИЯ в папке
    клиники (мастер закрыл бы сторожа из `{app}`); ждёт сторож выхода
    ОБОЛОЧКИ (родителя движка), поднимает оболочку. Движок не гасит себя сам —
    просит оболочку (`quit`). ⛔ Слова заставки, итога и потолки — договор
    движка (`restartwatch`) и сторожа (`shell/src/watch.rs`): сверяются здесь."""
    import pathlib

    from app import restartwatch as rw

    with tempfile.TemporaryDirectory(prefix="dp_watchshell_") as td:
        data = pathlib.Path(td) / "data"
        data.mkdir()
        p = subprocess.run([str(PYTHON), "-c", _SHELL_CODE], cwd=str(BOT), text=True,
                           capture_output=True, encoding="utf-8",
                           env={**os.environ, "DP_TEST_DIR": td, "DENTART_DATA_DIR": str(data)})
    if p.returncode != 0:
        res.failed.append(("сторож у оболочки: запуск", p.stderr[-900:]))
    else:
        o = json.loads(p.stdout.strip().splitlines()[-1])
        shell = o["shell_path"]
        res.check("перезапуск у оболочки: пошёл", o["restart"], None)
        res.check("сторож перезапуска — сама оболочка, поднимает оболочку, ждёт оболочку",
                  o["restart_runs"], [{"task": "DentPilotRestart", "command": shell, "flag": rw.FLAG,
                                       "launch": [shell], "pid": o["parent"], "result": None}])
        res.check("уход — просьбой к оболочке, не os._exit", o["restart_quits"], ["restart"])
        res.ok("трубы к оболочке нет — движок себя не гасит (остановку принесёт закрытый stdin)",
               o["restart_nopipe"] is None and o["restart_nopipe_quits"] == ["restart"], repr(o))
        u = o["update_runs"]
        res.ok("сторож обновления — КОПИЯ оболочки в папке клиники, ждёт итог мастера",
               o["update_watch"] is None and o["copy_is_shell"] and len(u) == 1
               and u[0]["command"] == o["copy_path"] and u[0]["launch"] == [shell]
               and u[0]["pid"] == o["parent"] and u[0]["result"].endswith("install.result")
               and "Program Files" not in o["copy_path"], repr((u, o["copy_path"])))
        res.ok("оболочка не найдена — отказ словами, программа жива, оболочку не просят",
               o["no_shell"] and "DentPilot.exe" in o["no_shell"] and o["no_shell_runs"] == 0
               and o["no_shell_quits"] == [], repr(o))

    # ---- договор движка и сторожа: одни слова ----
    src = (pathlib.Path(__file__).resolve().parents[1] / "shell" / "src" / "watch.rs")
    rs = src.read_text(encoding="utf-8") if src.exists() else ""
    res.ok("сторож оболочки на месте", "fn decide" in rs, f"{src} не найден или переписан")
    for name in ("TEXT_INSTALL", "TEXT_RESTART", "TEXT_CLOSING", "TEXT_NEW", "TEXT_ROLLBACK"):
        text = getattr(rw, name)
        res.ok(f"текст заставки — тот же у движка и сторожа: {name}",
               f'const {name}: &str = "{text}";' in rs, f"в watch.rs нет «{text}»")
    # слова итога пишут операция за UAC и мастер; сторож их узнаёт
    for word, line in (("ok", 't == "ok"'), ("fail…", 't.starts_with("fail")'),
                       ("cancelled", 't == "cancelled"')):
        res.ok(f"сторож узнаёт слово итога: {word}", line in rs, f"в watch.rs нет `{line}`")
    for what, line in (("метка режима", f'pub const FLAG: &str = "{rw.FLAG}";'),
                       ("«без итога»", f'const NO_RESULT: &str = "{rw.NO_RESULT}";'),
                       ("потолок ожидания итога", f"Duration::from_secs({rw.WAIT_S // 60} * 60)"),
                       ("потолок ожидания выхода", f"Duration::from_secs({int(rw.EXIT_WAIT_S)})")):
        res.ok(f"движок и сторож согласны: {what}", line in rs, f"в watch.rs нет `{line}`")
    # 18.10 (2.0.2): «started» без живого мастера — сторож оболочки не ждёт 9 минут.
    # Мастер он узнаёт по имени копии, которую запускает операция за UAC: другое
    # имя — и сторож поднимал бы прежнюю программу посреди идущей установки.
    from app import privileged
    stem = privileged.SETUP_NAME.rsplit(".", 1)[0]
    for what, line in (("имя мастера — копия за UAC и распаковка Inno",
                        f'const SETUP_NAMES: [&str; 2] = ["{privileged.SETUP_NAME}", "{stem}.tmp"];'),
                       ("слово «started»", f'const STARTED: &str = "{privileged.STARTED}";'),
                       ("журнал мастера", f'const SETUP_LOG: &str = "{privileged.SETUP_LOG}";')):
        res.ok(f"сторож оболочки узнаёт мастер: {what}", line in rs, f"в watch.rs нет `{line}`")
    main_rs = src.with_name("main.rs").read_text(encoding="utf-8") if src.exists() else ""
    res.ok("оболочка уходит в сторожа раньше замка «один экземпляр»",
           0 < main_rs.find("watch::is_watch(&args)") < main_rs.find("tauri_plugin_single_instance::init"),
           "запущенная сторожем программа нашла бы «первый экземпляр» в нём и закрылась")
