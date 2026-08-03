"""Обновления через GitHub Releases.
- Проверка при старте и каждые 6 часов (баннер в шапке + блок в настройках).
- self_update(): скачивает exe-ассет релиза, подменяет себя через bat-скрипт
  и перезапускается — «обновление в один клик» для desktop-издания.
Для теста механики без релиза: env DENTART_FAKE_UPDATE_URL=<url exe>."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import pathlib
import shutil
import subprocess
import sys
import threading
import time
import urllib.request

from . import engine as eng

log = logging.getLogger("update")

REPO = "olegbacalu-maker/dental-booking-bot"

# Имена ассетов, которые ЯВЛЯЮТСЯ самой программой. Рядом в релизе может лежать
# инсталлятор для новых клиник — его качать нельзя: bat подменил бы им работающую
# программу. Прежний отбор «первый .exe в списке» для этого и опасен: порядок
# assets в ответе GitHub ничем не гарантирован, а замеры на живых репозиториях
# дают сортировку по имени — то есть "DentPilot-Setup-*.exe" встаёт РАНЬШЕ
# "DentPilot.exe" ('-' = 0x2D < '.' = 0x2E) и выбрался бы именно инсталлятор.
# Поэтому имя фиксированное и сравнивается точно.
# (dentart.exe — историческое имя, релизы под ним могли выходить.)
APP_ASSETS = ("dentpilot.exe", "dentart.exe")

STATE = {"latest": "", "url": "", "asset_url": "", "asset_size": 0,
         "asset_digest": "", "checked": False, "error": ""}


def _ver(tag: str) -> tuple:
    parts = []
    for p in tag.lstrip("vV").split("."):
        digits = "".join(ch for ch in p if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    # Без выравнивания тег "v1.10" даёт (1, 10) < (1, 10, 0) = APP_VERSION
    # "1.10.0", и релиз становится невидимым для всех клиник разом.
    return tuple((parts + [0, 0, 0])[:3])


def newer_available() -> bool:
    return bool(STATE["latest"]) and _ver(STATE["latest"]) > _ver(eng.APP_VERSION)


def is_desktop() -> bool:
    return bool(getattr(sys, "frozen", False))


# GUID из installer/DentPilot.iss (AppId). Inno дописывает к нему «_is1».
# Ключ создаёт установщик; программа его только ПРАВИТ и никогда не создаёт —
# установка копированием exe в реестре не числится, и выдумывать её нельзя.
_UNINST_KEY = (r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
               r"\{B8836ACC-EA41-4B1C-9FEB-DC61ADD35754}_is1")


def sync_uninstall_version() -> None:
    """После обновления в один клик «Программы и компоненты» показывали версию,
    записанную установщиком, — то есть ту, с которой клинику давно сняли.
    А это единственное место, где версию видно НЕ открывая программу: по
    телефону спрашивают именно там. Приводим запись в соответствие с тем,
    что реально лежит на диске."""
    if not is_desktop() or sys.platform != "win32":
        return
    try:
        import winreg
    except ImportError:
        return
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, _UNINST_KEY, 0,
                                winreg.KEY_READ | winreg.KEY_WRITE) as k:
                cur, _ = winreg.QueryValueEx(k, "DisplayVersion")
                if str(cur) == eng.APP_VERSION:
                    return
                winreg.SetValueEx(k, "DisplayVersion", 0, winreg.REG_SZ,
                                  eng.APP_VERSION)
                # DisplayName у Inno = «DentPilot X.Y.Z», версия внутри строки
                try:
                    name, _ = winreg.QueryValueEx(k, "DisplayName")
                    if str(cur) and str(cur) in str(name):
                        winreg.SetValueEx(k, "DisplayName", 0, winreg.REG_SZ,
                                          str(name).replace(str(cur), eng.APP_VERSION))
                except OSError:
                    pass
                log.warning("uninstall entry: %s -> %s", cur, eng.APP_VERSION)
                return
        except FileNotFoundError:
            continue          # в этом улье записи нет — не наш случай
        except OSError as e:
            # HKLM без прав администратора: правка невозможна, но это косметика
            log.warning("uninstall entry not updated (%r)", e)
            return


def can_self_update() -> bool:
    return is_desktop() and newer_available() and bool(STATE["asset_url"])


def asset_pending() -> bool:
    """Новая версия видна, но файла в релизе нет — обновиться нечем."""
    return newer_available() and not STATE["asset_url"]


def _check() -> None:
    fake = os.environ.get("DENTART_FAKE_UPDATE_URL", "").strip()
    if fake:
        # тест-хук: размера и контрольной суммы нет — проверка их пропускает
        STATE.update(latest="v9.9.9", asset_url=fake, asset_size=0, asset_digest="",
                     url=f"https://github.com/{REPO}/releases", checked=True, error="")
        return
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{REPO}/releases/latest",
            headers={"User-Agent": "dentpilot-desktop"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.load(r)
        asset_url, asset_size, asset_digest = "", 0, ""
        for a in data.get("assets", []):
            if str(a.get("name", "")).strip().lower() not in APP_ASSETS:
                continue
            # ассет ещё заливается (или залился с ошибкой) — он нам не годится
            if str(a.get("state", "uploaded")) != "uploaded":
                continue
            asset_url = a.get("browser_download_url", "")
            asset_size = int(a.get("size") or 0)
            asset_digest = str(a.get("digest") or "")
            break
        STATE.update(latest=data.get("tag_name", ""), url=data.get("html_url", ""),
                     asset_url=asset_url, asset_size=asset_size,
                     asset_digest=asset_digest, checked=True, error="")
    except Exception as e:  # noqa: BLE001 — оффлайн/404 не должны ничего ломать
        STATE.update(checked=True, error=str(e))
    finally:
        # Релиз опубликован, но exe ещё не приложен (или как раз заливается,
        # 28 МБ) — перепроверяем через 5 минут, а не через 6 часов, иначе
        # клиника полдня видит «новая версия», которую нельзя поставить.
        delay = 300 if (newer_available() and not STATE["asset_url"]) else 6 * 3600
        t = threading.Timer(delay, _check)
        t.daemon = True
        t.start()


def check_now() -> None:
    """Принудительная проверка из настроек (кнопка «Verifică acum»)."""
    _check()


def check_async() -> None:
    threading.Thread(target=_check, daemon=True).start()


def _spawn_via_scheduler(bat: pathlib.Path, task_name: str) -> None:
    """Запускает bat сервисом планировщика — вне нашего Job-объекта."""
    no_win = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.run(
        ["schtasks", "/create", "/tn", task_name, "/tr", f'"{bat}"',
         "/sc", "once", "/st", "23:59", "/f"],
        creationflags=no_win, capture_output=True, check=False,
    )
    subprocess.run(["schtasks", "/run", "/tn", task_name],
                   creationflags=no_win, capture_output=True, check=False)


def _exit_soon() -> None:
    def _die() -> None:
        time.sleep(1.2)
        os._exit(0)

    threading.Thread(target=_die, daemon=True).start()


def restart_app() -> str | None:
    """Перезапуск программы (без замены exe) — для применения токена и т.п."""
    if not is_desktop():
        return "restart доступен только в desktop-версии"
    if os.environ.get("DENTART_NO_RESTART") == "1":  # тест-хук
        return None
    exe = pathlib.Path(sys.executable).resolve()
    bat = exe.with_name("dentpilot_restart.bat")
    bat.write_text(
        "@echo off\r\n"
        'cd /d "%~dp0"\r\n'
        "ping -n 3 127.0.0.1 >nul\r\n"
        f'start "" /D "%~dp0" "{exe.name}"\r\n'
        "schtasks /delete /tn DentPilotRestart /f >nul 2>&1\r\n"
        'del "%~f0"\r\n',
        encoding="ascii",
    )
    _spawn_via_scheduler(bat, "DentPilotRestart")
    _exit_soon()
    return None


def _verify_download(path: pathlib.Path) -> str | None:
    """Скачанный файл — точно тот, что описан в релизе? None = да, str = ошибка.

    Прежней проверки «больше 5 МБ» не хватало: оборванная на середине закачка
    (30 МБ по слабому каналу) не вызывает исключения в urllib — обрубок молча
    проходил в `move` и затирал рабочую программу неработающим файлом.
    """
    got = path.stat().st_size
    if got < 5_000_000:
        return "fișier descărcat invalid (prea mic)"
    want_size = STATE["asset_size"]
    if want_size and got != want_size:
        return f"descărcare incompletă ({got} din {want_size} baiți)"
    want = STATE["asset_digest"].split(":")[-1].strip().lower()
    if want:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        if h.hexdigest() != want:
            return "fișier descărcat corupt (sumă de control greșită)"
    return None


def self_update() -> str | None:
    """Скачивает новый exe и перезапускает программу. None = пошло, str = ошибка."""
    if not is_desktop():
        return "self-update доступен только в desktop-версии"
    if not STATE["asset_url"]:
        return "в релизе нет exe-файла"
    exe = pathlib.Path(sys.executable).resolve()
    # имя производное от текущего exe: у старых установок он DentArt.exe,
    # у новых DentPilot.exe — bat в обоих случаях кладёт новый файл на место
    new_path = exe.with_name(exe.stem + ".new.exe")
    try:
        req = urllib.request.Request(STATE["asset_url"],
                                     headers={"User-Agent": "dentpilot-desktop"})
        with urllib.request.urlopen(req, timeout=120) as r, open(new_path, "wb") as f:
            shutil.copyfileobj(r, f)
    except Exception as e:  # noqa: BLE001
        return f"descărcarea a eșuat: {e}"
    if err := _verify_download(new_path):
        new_path.unlink(missing_ok=True)
        return err
    old_path = exe.with_name(exe.stem + ".old.exe")
    bat = exe.with_name("dentpilot_update.bat")
    # ping вместо timeout (timeout требует консоль), CREATE_NO_WINDOW даёт cmd
    # скрытую консоль — start/ping работают, окна не мелькают.
    #
    # Порядок «сначала увести рабочий exe в .old, только потом класть новый»
    # обязателен: при прежнем прямом `move new -> exe` любой сбой ПОСЛЕ него
    # (антивирус съел новый файл) не оставлял на диске ни одной копии программы,
    # и все ярлыки вели в никуда. Теперь любая неудача возвращает старый exe и
    # запускает его: неудачное обновление должно быть отличимо от удаления.
    # Число попыток ограничено (~60 с): без предела bat крутился вечно и
    # программа просто не запускалась, пока клиника не перезагрузит компьютер.
    bat.write_text(
        "@echo off\r\n"
        f'cd /d "%~dp0"\r\n'
        "set n=0\r\n"
        ":try\r\n"
        "ping -n 2 127.0.0.1 >nul\r\n"
        "set /a n+=1\r\n"
        f'move /y "{exe.name}" "{old_path.name}" >nul 2>&1\r\n'
        f'if not exist "{exe.name}" goto swap\r\n'
        "if %n% lss 30 goto try\r\n"
        "goto fail\r\n"
        ":swap\r\n"
        f'move /y "{new_path.name}" "{exe.name}" >nul 2>&1\r\n'
        f'if not exist "{exe.name}" goto restore\r\n'
        f'del "{old_path.name}" >nul 2>&1\r\n'
        f'start "" /D "%~dp0" "{exe.name}"\r\n'
        "goto done\r\n"
        ":restore\r\n"
        f'move /y "{old_path.name}" "{exe.name}" >nul 2>&1\r\n'
        ":fail\r\n"
        f'if exist "{exe.name}" start "" /D "%~dp0" "{exe.name}"\r\n'
        ":done\r\n"
        "schtasks /delete /tn DentPilotUpdate /f >nul 2>&1\r\n"
        'del "%~f0"\r\n',
        encoding="ascii",
    )
    _spawn_via_scheduler(bat, "DentPilotUpdate")
    _exit_soon()
    return None
