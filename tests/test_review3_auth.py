"""Ревью-3, кластер «вход и обновление»: main.py и update.py.

Пять находок, каждая — молчаливая: программа отвечает успехом, лог чист, а
клиника получает не то. Общего у них ровно это, поэтому и набор один.

⚠️ Часть проверок поднимает сервер с ПУСТЫМ ADMIN_KEY (NO_KEY): вход по
PIN-файлу — это ветка настольного издания, и остальные наборы её не видят.
А одна проверка, наоборот, требует ЗАПОЛНЕННОГО ADMIN_KEY: битый auth.json не
имеет права запирать вход там, где вход идёт по ключу.

Проверки про `update.py` сервера не поднимают и в сеть не ходят: планировщик,
таймеры и закачка подменяются в ОТДЕЛЬНОМ процессе (как suite_pure в
test_admin) — иначе подмена subprocess.run и threading.Timer осталась бы жить
в прогоне и задела бы соседние наборы.
"""
import json
import os
import subprocess

from harness import BOT, PIN, PYTHON, Client, Result, Server

NO_KEY = {"ADMIN_KEY": ""}          # без него издание уходит веткой ADMIN_KEY

# так выглядит auth.json после обрыва питания посреди записи
BROKEN = '{"v": 2, "cookie_key": "abc", "users": [{"id": "cl'


def suite_pin_dup(res: Result) -> None:
    """Смена СВОЕГО PIN обязана спрашивать pin_free, как это делает users/save.

    Вход идёт по ОДНОМУ паролю без логина, и уникальность паролей — то, на чём
    он держится. Совпал новый PIN с чужим — verify_pin возвращает ПЕРВОГО
    совпавшего, а сменивший пароль ложится в конец списка, то есть проигрывает
    всегда именно он: директор со следующего входа получает куку регистратуры,
    теряет деньги и настройки и вернуть себе роль уже не может (для этого нужен
    PERM_USERS). Форма учёток это стережёт (dup_user), форма смены — нет.
    """
    with Server(env=NO_KEY) as s:
        boss = Client(s.url)
        boss.post("/admin/setup", pin1="1111", pin2="1111")
        res.check("регистратура заводится",
                  boss.post("/admin/users/save", uid="ana", name="Ana R",
                            role="receptie", pin="3333").msg, "ok_user")

        r = boss.post("/admin/pin/change", old_pin="1111", new1="3333",
                      new2="3333")
        res.check("смена своего PIN на ЧУЖОЙ отбита", r.msg, "dup_user")
        # файл не тронут: старый PIN директора работает, а 3333 — по-прежнему Ana
        again = Client(s.url)
        again.post("/admin/login", password="1111", next="/admin")
        res.ok("прежний PIN директора пускает",
               again.get("/admin").status == 200,
               "отказ смены всё-таки переписал PIN директора")
        ana = Client(s.url)
        ana.post("/admin/login", password="3333", next="/admin")
        res.ok("под чужим паролем входит его хозяин, а не директор",
               "Ana R" in ana.get("/admin").body,
               "3333 перестал быть паролем Ana — пароли разошлись")

        # ⭐ вторая половина правила: СВОЙ прежний пароль занятым не считается,
        # иначе форма отказала бы человеку сменить PIN «на всякий случай» на
        # тот же самый и выглядела бы сломанной
        r = again.post("/admin/pin/change", old_pin="1111", new1="1111",
                       new2="1111")
        res.check("свой прежний PIN не считается занятым", r.msg, "ok_pin")


def suite_login_uid_case(res: Result) -> None:
    """ID при входе — в нижний регистр, как его пишет users/save.

    Учётки заводятся ТОЛЬКО в нижнем регистре (`uid.strip().lower()`), а поле
    «ID (opțional)» на телефоне получает автозаглавную букву. Врач набирает
    верный пароль и верный по его памяти логин — и получает «PIN greșit», да
    ещё и накручивает счётчик блокировки: пятая попытка запрёт вход и с
    правильным вводом.
    """
    with Server(env=NO_KEY) as s:
        boss = Client(s.url)
        boss.post("/admin/setup", pin1="1111", pin2="1111")
        res.check("врач заводится",
                  boss.post("/admin/users/save", uid="dr-ion", name="Dr. Ion",
                            role="medic", pin="2222").msg, "ok_user")

        med = Client(s.url)
        r = med.post("/admin/login", password="2222", uid="DR-ION", next="/admin")
        res.ok("ID с телефона (заглавные) пускает",
               "err" not in r.location and med.get("/admin").status == 200,
               f"location {r.location!r} — верный пароль отбит из-за регистра")
        res.ok("и это тот самый врач", "Dr. Ion" in med.get("/admin").body,
               "вошёл кто-то другой")


def suite_broken_with_key(res: Result) -> None:
    """Битый auth.json запирает вход ровно там, где войти иначе нечем.

    В `_guard` проверка вложена в «секрета нет» + SQLite, а в POST /admin/login
    она стояла первой и БЕЗУСЛОВНОЙ. При заполненном ADMIN_KEY (так работают
    песочница `.\\dev up`, весь харнесс и клиника, которой ключ вписали руками)
    вход по ключу исправен — auth.json в нём не участвует ни одной строкой, —
    но случайно обрезанный файл запирал журнал наглухо, советуя восстановить
    копию, которая этой беде не помогает.
    """
    s = Server()                     # ADMIN_KEY заполнен (harness.PIN)
    (s.dir / "auth.json").write_text(BROKEN, encoding="utf-8")
    with s:
        c = Client(s.url)
        r = c.post("/admin/login", password=PIN, next="/admin")
        res.ok("ключ пускает при битом файле",
               r.status == 303 and "err" not in r.location,
               f"location {r.location!r} — вход по ADMIN_KEY заперт чужой бедой")
        res.ok("и журнал открывается", c.get("/admin").status == 200,
               "кука выдана, а страница не отдаётся")
        res.ok("экран входа не пугает битым файлом там, где вход по ключу",
               "deteriorat" not in c.get("/admin/login").body,
               "советует восстановить auth.json, который тут не при чём")
        res.ok("неверный ключ по-прежнему не пускает",
               "err=1" in Client(s.url).post("/admin/login", password="nope",
                                             next="/admin").location,
               "битый файл сделал вход открытым — это хуже запертого")

    # ⛔ обратная полярность: без ADMIN_KEY отказ ОБЯЗАН остаться. Иначе правка
    # открыла бы первичную установку PIN поверх живых учёток.
    s2 = Server(env=NO_KEY)
    (s2.dir / "auth.json").write_text(BROKEN, encoding="utf-8")
    with s2:
        c = Client(s2.url)
        res.ok("настольная ветка по-прежнему объясняет беду",
               "deteriorat" in c.get("/admin/login").body,
               "экран входа перестал объяснять битый файл")
        res.ok("и вход отбивается с честной причиной",
               "err=broken" in c.post("/admin/login", password="9999",
                                      next="/admin").location,
               "форма врёт про неверный PIN")


# ---------- update.py: планировщик, таймеры и версия ----------
# Всё это живёт вне HTTP: сеть, реестр задач Windows и цепочка таймеров. Код
# исполняется в отдельном процессе, поэтому подмены (subprocess.run,
# threading.Timer, urlopen) не переживают проверку и не задевают соседей.

_CODE = r'''
import io, json, os, pathlib, subprocess, sys, tempfile, threading, urllib.request
sys.path.insert(0, r"%s")
os.environ.pop("DENTART_FAKE_UPDATE_URL", None)   # иначе _check уходит тест-веткой
os.environ.pop("DENTART_NO_RESTART", None)        # иначе restart_app выйдет раньше
from app import engine as eng
from app import update as upd

out = {}

# --- 1. одна цепочка проверок на процесс ---
# Таймер заводился в finally БЕЗУСЛОВНО: каждое нажатие «Verifică acum»
# добавляло вечную вторую цепочку. В режиме ожидания файла (5 минут) десяток
# нажатий за день выедает лимит GitHub 60/час — и клиника перестаёт видеть
# обновления вовсе, молча.
made = []
class FakeTimer:
    def __init__(self, delay, fn):
        self.delay, self.fn, self.alive = delay, fn, True
        made.append(self)
    def start(self): pass
    def cancel(self): self.alive = False
upd._api = lambda path: (_ for _ in ()).throw(RuntimeError("сети нет"))
upd._web_fallback = lambda ch: None
real_timer = threading.Timer
threading.Timer = FakeTimer
try:
    for _ in range(3):
        upd.check_now()
finally:
    threading.Timer = real_timer
out["timers_made"] = len(made)
out["timers_alive"] = sum(1 for t in made if t.alive)

# --- 2. провал планировщика виден, и программа остаётся жива ---
tmp = pathlib.Path(tempfile.mkdtemp(prefix="dp_upd_"))
exe = tmp / "DentPilot.exe"
exe.write_bytes(b"x")
real_exec, real_run, real_open = sys.executable, subprocess.run, urllib.request.urlopen
exits = []
upd.is_desktop = lambda: True
upd._exit_soon = lambda: exits.append(1)

class Failed:
    returncode, stdout, stderr = 1, b"", b"ERROR: Access is denied."

try:
    sys.executable = str(exe)
    subprocess.run = lambda *a, **kw: Failed()
    out["restart_err"] = upd.restart_app()
    out["restart_exits"] = len(exits)

    upd.STATE.update(latest="v99.9.9", asset_url="https://example/DentPilot.exe",
                     asset_size=0, asset_digest="")
    urllib.request.urlopen = lambda *a, **kw: io.BytesIO(b"0" * 32)
    upd._verify_download = lambda p: None
    out["update_err"] = upd.self_update()
    out["update_exits"] = len(exits)

    # --- 3. обновляться некуда: версия в релизе не новее текущей ---
    got = []
    urllib.request.urlopen = lambda *a, **kw: (got.append(1), io.BytesIO(b"0" * 32))[1]
    upd.STATE.update(latest="v" + eng.APP_VERSION)
    out["same_err"] = upd.self_update()
    out["same_downloads"] = len(got)
    out["same_exits"] = len(exits)
finally:
    sys.executable, subprocess.run = real_exec, real_run
    urllib.request.urlopen = real_open

print(json.dumps(out))
''' % str(BOT)


def _run_code(res: Result) -> dict | None:
    env = dict(os.environ)
    p = subprocess.run([str(PYTHON), "-c", _CODE], cwd=str(BOT), text=True,
                       capture_output=True, env=env)
    if p.returncode != 0:
        res.failed.append(("update.py: запуск проверок", p.stderr[-600:]))
        return None
    return json.loads(p.stdout)


def suite_update(res: Result) -> None:
    v = _run_code(res)
    if v is None:
        return
    res.check("проверок заведено столько, сколько запрошено",
              v["timers_made"], 3)
    res.check("а живая цепочка остаётся ОДНА", v["timers_alive"], 1)

    res.ok("провал планировщика возвращается ошибкой",
           isinstance(v["restart_err"], str) and v["restart_err"],
           f"restart_app() вернул {v['restart_err']!r} — экран пообещает "
           f"перезапуск, которого не будет")
    res.check("и программа не гасится", v["restart_exits"], 0)
    res.ok("провал планировщика при обновлении — тоже ошибка",
           isinstance(v["update_err"], str) and v["update_err"],
           f"self_update() вернул {v['update_err']!r} — программа закрылась бы "
           f"навсегда, а экран обещает, что она вернётся")
    res.check("и обновление не гасит программу", v["update_exits"], 0)

    res.ok("та же версия не качается заново",
           isinstance(v["same_err"], str) and v["same_err"],
           f"self_update() вернул {v['same_err']!r} на версии, которая не "
           f"новее установленной")
    res.check("и файл не скачивается", v["same_downloads"], 0)
    res.check("и журнал клиники не закрывается", v["same_exits"], 0)
