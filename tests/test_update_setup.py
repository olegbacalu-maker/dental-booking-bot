"""Обновление установщиком — сторона ОБЫЧНОГО процесса (03.10, update.py › _update_by_setup).

Сторона за UAC (`install-setup`) — test_privileged.suite_install_setup. Здесь —
что программа делает до окна UAC и после: когда выбирает путь установщика,
что скачивает и проверяет, что заводит заранее (задачу-сторож перезапуска) и
как уходит. Код идёт в отдельном процессе с подменами: планировщик, окно UAC и
выход программы в прогоне настоящими быть не могут.

⭐ Главное, что держится: ни один отказ не показывает окно UAC ради заведомо
негодного файла, и программа гасит себя ТОЛЬКО увидев «started» от исполнителя
— иначе она закрылась бы, а вернуть её было бы некому.
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
from app import privileged

os.environ["DENTART_CHANNEL"] = ""              # клиника (stable): с 1.37.3 тоже установщиком
tmp = pathlib.Path(os.environ["DP_TEST_DIR"])
signed = pathlib.Path(os.environ["DP_SIGNED_SETUP"]) if os.environ.get("DP_SIGNED_SETUP") else None
out = {}
work = upd.work_dir()
result = work / privileged.RESULT_NAME
watch, asked, exits = [], [], []
upd.is_desktop = lambda: True
upd.exe_dir_writable = lambda: False
installed = {"found": True}
upd.uninstall_entry = lambda: {"found": installed["found"], "version": "1.0.0", "stale": False, "hive": "HKLM"}
upd._spawn_via_scheduler = lambda bat, name: (watch.append({"name": name, "bat": pathlib.Path(bat).read_text()}), None)[1]
upd._exit_soon = lambda: exits.append(1)
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
    upd.STATE.update(latest="v99.0.0", asset_url="", setup_url=url,
                     setup_size=sz if size is None else size, setup_digest=dg if digest is None else digest)
    del watch[:], asked[:], exits[:]
    result.unlink(missing_ok=True)
    err = upd.self_update()
    req = work / privileged.REQUEST_NAME
    out[name] = {"err": err, "asked": list(asked), "watch": list(watch), "exits": len(exits),
                 "result": result.read_text(encoding="utf-8") if result.exists() else "",
                 "new": (work / privileged.SETUP_NEW).exists(),
                 "request": json.loads(req.read_text(encoding="utf-8")) if req.exists() else None,
                 "zip_left": (work / "DentPilot-Setup.zip").exists()}

# --- когда путь установщика вообще выбирается ---
upd.STATE.update(latest="v99.0.0", setup_url="https://x/DentPilot-Setup-99.0.0.zip")
m = {"установлен установщиком, Program Files": upd.installer_mode()}
os.environ["DENTART_UPDATE_VIA"] = "exe"; m["рычаг DENTART_UPDATE_VIA=exe"] = upd.installer_mode()
os.environ.pop("DENTART_UPDATE_VIA")
upd.exe_dir_writable = lambda: True; m["папка программы пишется (переносимая)"] = upd.installer_mode()
upd.exe_dir_writable = lambda: False
installed["found"] = False; m["в реестре не числится (копия exe)"] = upd.installer_mode()
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

# --- сторож узнаёт итог НАСТОЯЩИМ cmd: с переводом строки и без (канарейка 03.10:
# установщик пишет «ok» без перевода, и findstr /x его не видел — 9 минут ожидания) ---
if sys.platform == "win32":
    import subprocess
    probe = tmp / "probe.result"
    bat = tmp / "probe.bat"
    bat.write_text("@echo off\r\n" + upd._watch_match(probe)
                   + "echo none\r\nexit /b\r\n:start\r\necho start\r\nexit /b\r\n"
                   + ":done\r\necho done\r\nexit /b\r\n", encoding="ascii")
    cases = {"ok": b"ok", "ok+crlf": b"ok\r\n", "fail": b"fail", "cancelled": b"cancelled",
             "cancelled+crlf": b"cancelled\r\n", "okay": b"okay", "empty": b"", "missing": None,
             # исполнитель не запустил установщик после «started»: причина второй строкой
             "fail+reason": "fail\r\nустановщик не запустился: [WinError 5]".encode("utf-8"),
             "started": b"started"}
    match = {}
    for case, body in cases.items():
        probe.unlink(missing_ok=True)
        if body is not None:
            probe.write_bytes(body)
        r = subprocess.run(["cmd", "/c", str(bat)], capture_output=True, text=True)
        match[case] = r.stdout.strip()
    out["match"] = match
else:
    out["match"] = None

out["signed"] = signed is not None
out["result_path"] = str(result)
print(json.dumps(out))
''' % str(BOT)


def _signed_setup() -> pathlib.Path | None:
    root = pathlib.Path(__file__).resolve().parents[1]
    for d in (root / "dist", root.parent / "releases"):
        found = sorted(d.glob("DentPilot-Setup-*.exe"))
        if found:
            return found[-1]
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
    res.check("путь установщика: установлена установщиком в Program Files, установщик в выпуске — канал не важен",
              m, {"установлен установщиком, Program Files": True, "рычаг DENTART_UPDATE_VIA=exe": False,
                  "папка программы пишется (переносимая)": False, "в реестре не числится (копия exe)": False,
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

    # ⭐ Сторож перезапуска — живым cmd, а не по тексту скрипта: текст с
    # findstr /x выглядел верным, а «ok» без перевода строки не узнавал (03.10).
    if o["match"] is None:
        res.ok("сторож перезапуска: не Windows — живой cmd пропущен", True, "")
    else:
        res.check("сторож узнаёт итог настоящим cmd — и без перевода строки (канарейка 03.10)",
                  o["match"], {"ok": "start", "ok+crlf": "start", "fail": "start", "cancelled": "done",
                               "cancelled+crlf": "done", "okay": "none", "empty": "none",
                               "missing": "none", "fail+reason": "start", "started": "none"})

    if not o["signed"]:
        res.ok("подписанного установщика на машине нет (dist\\, releases\\) — путь до «started» пропущен",
               True, "")
        return
    ok = o["ok"]
    res.ok("подписанный установщик: окно UAC на install-setup, программа гасит себя по «started»",
           ok["err"] is None and ok["asked"] == ["install-setup"] and ok["exits"] == 1, repr(ok))
    res.ok("задача-сторож заведена ДО окна UAC и ждёт итога в файле",
           len(ok["watch"]) == 1 and ok["watch"][0]["name"] == "DentPilotUpdate"
           and o["result_path"] in ok["watch"][0]["bat"] and '"%r%"=="ok"' in ok["watch"][0]["bat"]
           and '"%r%"=="cancelled"' in ok["watch"][0]["bat"]
           and "findstr" not in ok["watch"][0]["bat"], repr(ok["watch"]))
    res.ok("описание для перепроверки за UAC — размер и sha256 самого установщика, архив убран",
           ok["request"] == {"size": o["ok_size"], "sha256": o["ok_sha"], "version": "v99.0.0"}
           and ok["new"] and not ok["zip_left"], repr(ok["request"]))
    for key, want, name in (("uac_hidden", "nu a afișat", "окно UAC не показано"),
                            ("refused", "не новее", "исполнитель отказал словами")):
        r = o[key]
        res.ok(f"{name}: программа жива, сторожу — «cancelled», установщик и описание убраны",
               r["err"] and want in r["err"] and r["exits"] == 0 and r["result"] == "cancelled"
               and not r["new"] and r["request"] is None, repr(r))
