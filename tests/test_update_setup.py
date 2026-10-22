"""Обновление установщиком — сторона ОБЫЧНОГО процесса (03.10, update.py › _update_by_setup).

Сторона за UAC (`install-setup`) — test_privileged.suite_install_setup. Здесь —
что программа делает до окна UAC и после: когда выбирает путь установщика,
что скачивает и проверяет, что заводит заранее (задачу-сторож перезапуска) и
как уходит. Код идёт в отдельном процессе с подменами: планировщик, окно UAC и
выход программы в прогоне настоящими быть не могут.

⭐ Главное, что держится: ни один отказ не показывает окно UAC ради заведомо
негодного файла, и программа просит оболочку закрыться ТОЛЬКО увидев «started»
от исполнителя — иначе она закрылась бы, а вернуть её было бы некому.
"""
import json
import os
import pathlib
import subprocess
import tempfile

from harness import BOT, PYTHON, Result

_CODE = r'''
import hashlib, json, os, pathlib, sys, zipfile
sys.path.insert(0, r"%s")
for k in ("DENTART_UPDATE_VIA", "DENTART_FAKE_UPDATE_URL", "DENTART_UPDATE_TOKEN"):
    os.environ.pop(k, None)
from app import update as upd
from app import privileged, sidecar

os.environ["DENTART_CHANNEL"] = ""              # клиника (stable): с 1.37.3 тоже установщиком
tmp = pathlib.Path(os.environ["DP_TEST_DIR"])
signed = pathlib.Path(os.environ["DP_SIGNED_SETUP"]) if os.environ.get("DP_SIGNED_SETUP") else None
out = {}
work = upd.work_dir()
result = work / privileged.RESULT_NAME
watch, asked, exits = [], [], []
upd.is_desktop = lambda: True
installed = {"found": True}
upd.uninstall_entry = lambda: {"found": installed["found"], "version": "1.0.0", "stale": False, "hive": "HKLM"}
upd._spawn_watch = lambda result, task, label, copy: (watch.append({"name": task, "result": str(result), "label": label, "copy": copy}), None)[1]
sidecar.request_quit = lambda reason: (exits.append(reason), True)[1]
uac = {"answer": "started", "shown": True}
def fake_request(name):
    asked.append(name)
    if uac["shown"] and uac["answer"]:
        result.write_text(uac["answer"], encoding="utf-8")
    return uac["shown"]
upd.privileged.request = fake_request

def zipped(entries):
    z = tmp / "src.zip"
    z.unlink(missing_ok=True)
    with zipfile.ZipFile(z, "w", zipfile.ZIP_STORED) as f:
        for name, data in entries.items():
            f.writestr(name, data)
    body = z.read_bytes()
    return z.as_uri(), len(body), "sha256:" + hashlib.sha256(body).hexdigest()

def attempt(name, entries, *, digest=None, size=None):
    url, sz, dg = zipped(entries)
    upd.STATE.update(latest="v99.0.0", setup_url=url,
                     setup_size=sz if size is None else size, setup_digest=dg if digest is None else digest)
    del watch[:], asked[:], exits[:]
    result.unlink(missing_ok=True)
    # удача оставляет замок одного запуска взятым (программа закрывается
    # сама, 17.10); здесь она не закрывается — следующий заход начинает заново
    if upd._RUN_LOCK.locked():
        upd._RUN_LOCK.release()
    err = upd.self_update()
    req = work / privileged.REQUEST_NAME
    out[name] = {"err": err, "asked": list(asked), "watch": list(watch), "exits": len(exits),
                 "result": result.read_text(encoding="utf-8") if result.exists() else "",
                 "new": (work / privileged.SETUP_NEW).exists(),
                 "request": json.loads(req.read_text(encoding="utf-8")) if req.exists() else None,
                 "zip_left": (work / "DentPilot-Setup.zip").exists()}

# --- когда путь установщика вообще выбирается ---
upd.STATE.update(latest="v99.0.0", setup_url="https://x/DentPilot-Setup-99.0.0.zip")
m = {"установлен установщиком": upd.installer_mode()}
# рычаг назад на подмену exe снят 22.10.2026: строка в dental.env ничего не значит
os.environ["DENTART_UPDATE_VIA"] = "exe"; m["рычаг DENTART_UPDATE_VIA=exe — без значения"] = upd.installer_mode()
os.environ.pop("DENTART_UPDATE_VIA")
installed["found"] = False; m["в реестре не числится (копия папки)"] = upd.installer_mode()
installed["found"] = True
upd.STATE["setup_url"] = ""; m["у выпуска нет установщика"] = upd.installer_mode()
upd.STATE["setup_url"] = "https://x/DentPilot-Setup-99.0.0.zip"
os.environ["DENTART_CHANNEL"] = "beta"; m["канарейка (beta) — тот же путь"] = upd.installer_mode()
os.environ["DENTART_CHANNEL"] = ""
out["mode"] = m

junk = b"MZ" + b"\0" * 6_000_000
want = "DentPilot-Setup-99.0.0.exe"
attempt("sha", {want: junk}, digest="sha256:" + "0" * 64)
attempt("short", {want: junk}, size=10_000_000)
attempt("two", {want: junk, "DentPilot.exe": junk})
attempt("name", {"DentPilot-Setup-1.0.0.exe": junk})
attempt("unsigned", {want: junk})
if signed is not None:
    good = signed.read_bytes()
    attempt("ok", {want: good})
    out["ok_sha"] = hashlib.sha256(good).hexdigest()
    out["ok_size"] = len(good)
    uac.update(shown=False)
    attempt("uac_hidden", {want: good})
    uac.update(shown=True, answer="установщик не новее стоящей программы")
    attempt("refused", {want: good})

out["signed"] = signed is not None
out["result_path"] = str(result)
print(json.dumps(out))
''' % str(BOT)


def _signed_setup() -> pathlib.Path | None:
    """Подписанный НАШИМ сертификатом мастер — тот же отбор, что у
    test_privileged (пробный мастер Т9 без подписи в dist\\ пропускается)."""
    import sys
    if str(BOT) not in sys.path:
        sys.path.insert(0, str(BOT))
    from app import authenticode, privileged

    root = pathlib.Path(__file__).resolve().parents[1]
    for d in (root / "dist", root.parent / "releases"):
        for f in sorted(d.glob("DentPilot-Setup-*.exe"), reverse=True):
            if authenticode.signer_thumbprint(f) in privileged.SIGNERS:
                return f
    return None


def suite_flow(res: Result) -> None:
    signed = _signed_setup()
    with tempfile.TemporaryDirectory(prefix="dp_updsetup_") as td:
        data = pathlib.Path(td) / "data"
        data.mkdir()
        env = {**os.environ, "DP_TEST_DIR": td, "DENTART_DATA_DIR": str(data),
               "DP_SIGNED_SETUP": str(signed) if signed else ""}
        p = subprocess.run([str(PYTHON), "-c", _CODE], cwd=str(BOT), text=True, capture_output=True, env=env)
    if p.returncode != 0:
        res.failed.append(("update._update_by_setup: запуск", p.stderr[-900:]))
        return
    o = json.loads(p.stdout.strip().splitlines()[-1])

    m = o["mode"]
    res.check("путь установщика: установлена установщиком, установщик в выпуске — канал не важен",
              m, {"установлен установщиком": True, "рычаг DENTART_UPDATE_VIA=exe — без значения": True,
                  "в реестре не числится (копия папки)": False,
                  "у выпуска нет установщика": False, "канарейка (beta) — тот же путь": True})

    for key, want, name in (("sha", "corupt", "sha256 архива не сошёлся"),
                            ("short", "incompletă", "архив не того размера"),
                            ("two", "nu conține", "в архиве два exe"),
                            ("name", "nu conține", "в архиве установщик другой версии"),
                            ("unsigned", "nu este semnat", "установщик без нашей подписи")):
        r = o[key]
        res.ok(f"отказ ДО окна UAC: {name}",
               r["err"] and want in r["err"] and r["asked"] == [] and r["watch"] == [] and r["exits"] == 0
               and not r["zip_left"] and not r["new"], repr(r))

    if not o["signed"]:
        res.ok("подписанного установщика на машине нет (dist\\, releases\\) — путь до «started» пропущен",
               True, "")
        return
    ok = o["ok"]
    res.ok("подписанный установщик: окно UAC на install-setup, по «started» — просьба оболочке закрыться",
           ok["err"] is None and ok["asked"] == ["install-setup"] and ok["exits"] == 1, repr(ok))
    res.ok("задача-сторож заведена ДО окна UAC и ждёт итога в файле — копией оболочки, с номером версии на заставке",
           len(ok["watch"]) == 1 and ok["watch"][0]["name"] == "DentPilotUpdate"
           and ok["watch"][0]["result"] == o["result_path"] and ok["watch"][0]["copy"] is True
           and ok["watch"][0]["label"].endswith("› 99.0.0"), repr(ok["watch"]))
    res.ok("описание для перепроверки за UAC — размер и sha256 самого установщика, архив убран",
           ok["request"] == {"size": o["ok_size"], "sha256": o["ok_sha"], "version": "v99.0.0"}
           and ok["new"] and not ok["zip_left"], repr(ok["request"]))
    for key, want, name in (("uac_hidden", "nu a afișat", "окно UAC не показано"),
                            ("refused", "не новее", "исполнитель отказал словами")):
        r = o[key]
        res.ok(f"{name}: программа жива, сторожу — «cancelled», установщик и описание убраны",
               r["err"] and want in r["err"] and r["exits"] == 0 and r["result"] == "cancelled"
               and not r["new"] and r["request"] is None, repr(r))


# ---------- оболочка Tauri (Т10, 18.10) ----------

_SHELL_CODE = r'''
import hashlib, json, os, pathlib, sys, zipfile
sys.path.insert(0, r"%s")
for k in ("DENTART_UPDATE_VIA", "DENTART_FAKE_UPDATE_URL", "DENTART_UPDATE_TOKEN", "DENTART_CHANNEL"):
    os.environ.pop(k, None)
from app import update as upd
from app import privileged, sidecar, authenticode

tmp = pathlib.Path(os.environ["DP_TEST_DIR"])
app_dir = tmp / "Program Files" / "DentPilot"
app_dir.mkdir(parents=True)
shell = app_dir / "DentPilot.exe"
shell.write_bytes(b"OBOLOCHKA")
out = {}
work = upd.work_dir()
result = work / privileged.RESULT_NAME

# оболочку не знаем (движок из исходников) — запускать нечего
out["no_shell_cmd"] = upd._program_cmd()
# движок оболочки: путь оболочки даёт лаунчер (sidecar.shell_exe)
sidecar.shell_exe = lambda: shell
quits, asked, watch = [], [], []
answer = {"quit": True}
sidecar.request_quit = lambda reason: (quits.append(reason), answer["quit"])[1]
upd.is_desktop = lambda: True
upd.uninstall_entry = lambda: {"found": True, "version": "1.0.0", "stale": False, "hive": "HKLM"}
out["program_cmd"] = upd._program_cmd()
out["watch_pid_is_parent"] = upd._watch_pid() == os.getppid()

def state(**kw):
    base = dict(latest="v99.0.0", setup_url="", setup_size=0, setup_digest="")
    base.update(kw)
    upd.STATE.update(base)

def modes():
    return {"installer": upd.installer_mode(), "can": upd.can_self_update(),
            "pending": upd.asset_pending()}

state(setup_url="https://x/DentPilot-Setup-99.0.0.zip")
out["installed"] = modes()
# в выпуске нет установщика (заливается): обновляться нечем, ждём
state()
out["no_setup"] = modes()
out["no_setup_run"] = upd.self_update()
if upd._RUN_LOCK.locked():
    upd._RUN_LOCK.release()
out["no_setup_left"] = sorted(p.name for p in work.iterdir())
out["state_keys"] = sorted(upd.STATE)

# установщиком: сторож заведён, окно UAC, «started» — и ОБОЛОЧКУ просят закрыться
upd._spawn_watch = lambda result, task, label, copy: (watch.append({"task": task, "copy": copy}), None)[1]
def fake_request(name):
    asked.append(name)
    result.write_text("started", encoding="utf-8")
    return True
upd.privileged.request = fake_request
authenticode.signer_thumbprint = lambda p: next(iter(privileged.SIGNERS))   # учебный файл
z = tmp / "setup.zip"
with zipfile.ZipFile(z, "w", zipfile.ZIP_STORED) as f:
    f.writestr("DentPilot-Setup-99.0.0.exe", b"MZ" + b"\0" * 6_000_000)
body = z.read_bytes()
for key, q in (("setup", True), ("setup_no_shell_pipe", False)):
    answer["quit"] = q
    del quits[:], asked[:], watch[:]
    state(setup_url=z.as_uri(), setup_size=len(body),
          setup_digest="sha256:" + hashlib.sha256(body).hexdigest())
    if upd._RUN_LOCK.locked():
        upd._RUN_LOCK.release()
    err = upd.self_update()
    out[key] = {"err": err, "quits": list(quits), "asked": list(asked), "watch": list(watch)}
print(json.dumps(out))
''' % str(BOT)


def suite_shell(res: Result) -> None:
    r"""Т10: у движка оболочки Tauri программа — ПАПКА (`DentPilot.exe` + `engine\`).

    Обновляется только установщиком (подмена одного exe снята 22.10.2026);
    уходит движок не `os._exit`, а просьбой к оболочке (`quit`) — она прячет
    окно и останавливает движок честно. Труба к оболочке порвана — движок себя
    не гасит: остановку принесёт закрытый stdin."""
    with tempfile.TemporaryDirectory(prefix="dp_updshell_") as td:
        data = pathlib.Path(td) / "data"
        data.mkdir()
        env = {**os.environ, "DP_TEST_DIR": td, "DENTART_DATA_DIR": str(data)}
        p = subprocess.run([str(PYTHON), "-c", _SHELL_CODE], cwd=str(BOT), text=True,
                           capture_output=True, env=env, encoding="utf-8")
    if p.returncode != 0:
        res.failed.append(("update у оболочки: запуск", p.stderr[-900:]))
        return
    o = json.loads(p.stdout.strip().splitlines()[-1])
    res.check("оболочки не знаем — запускать нечего (не свой exe)", o["no_shell_cmd"], [])
    res.check("программа у движка — оболочка DentPilot.exe",
              o["program_cmd"], [str(pathlib.Path(td) / "Program Files" / "DentPilot" / "DentPilot.exe")])
    res.ok("сторож ждёт выхода ОБОЛОЧКИ (родителя движка)", o["watch_pid_is_parent"], "")
    res.check("установлена мастером — путь установщика", o["installed"],
              {"installer": True, "can": True, "pending": False})
    res.check("в выпуске нет установщика — обновляться нечем, ждём его", o["no_setup"],
              {"installer": False, "can": False, "pending": True})
    res.ok("без установщика: отказ словами, ничего не скачано",
           o["no_setup_run"] and "обновляться нечем" in o["no_setup_run"] and o["no_setup_left"] == [],
           repr((o["no_setup_run"], o["no_setup_left"])))
    res.ok("в состоянии нет полей файла программы (asset_*)",
           not [k for k in o["state_keys"] if k.startswith("asset_")], repr(o["state_keys"]))
    s = o["setup"]
    res.ok("установщиком: сторож (копия) до окна UAC, по «started» — просьба оболочке, без os._exit",
           s["err"] is None and s["asked"] == ["install-setup"] and s["quits"] == ["update"]
           and s["watch"] == [{"task": "DentPilotUpdate", "copy": True}], repr(s))
    s = o["setup_no_shell_pipe"]
    res.ok("труба к оболочке порвана — движок себя не гасит, обновление пошло",
           s["err"] is None and s["quits"] == ["update"], repr(s))
