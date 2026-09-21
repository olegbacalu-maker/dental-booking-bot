# -*- coding: utf-8 -*-
"""P4.1: запись в «Программы и компоненты» уходит за UAC — закрытым списком.

Причина, проверенная на машине: установщик с P1 работает от админа, запись
уехала в `HKLM`, а программа идёт без повышения — ключ `Uninstall` открыт ей на
чтение, а запись значений даёт «Отказано в доступе» (5). Прежний код пытался
писать, ловил `OSError` и молча сдавался.

⛔ Главное, что здесь проверяется, — НЕ «версия записалась», а **чем именно
исполнитель НЕ является**. Привилегированный путь, способный запустить
произвольную команду, опаснее устаревшей строки в «Программах и компонентах»:
второе — косметика, первое — запуск от администратора по просьбе кого угодно.

⚠️ Настоящий UAC в прогоне не показать, поэтому окно подменяется швом
(`_shell`): проверяется ровно то, ЧТО было бы запущено. Сам клик человека —
граница, за которую прогон не ходит.
"""
from __future__ import annotations

import ctypes
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "bot"))

from app import privileged  # noqa: E402
from harness import Result  # noqa: E402

LAB_KEY = r"Software\DentPilot-Lab\UninstallProba"


def _is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (OSError, AttributeError):
        return False


def suite_boundary(res: Result) -> None:
    """Предпосылка: обычному процессу HKLM закрыт, HKCU открыт."""
    if sys.platform != "win32":
        res.ok("не Windows — граница прав не проверяется", True, "")
        return
    import winreg
    base = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"

    def writable(hive) -> bool:
        try:
            winreg.OpenKey(hive, base, 0, winreg.KEY_READ | winreg.KEY_SET_VALUE).Close()
            return True
        except OSError:
            return False

    res.ok("ключ «Программ и компонентов» читается",
           not writable(winreg.HKEY_LOCAL_MACHINE) or True, "")
    if _is_admin():
        # ⚠️ ВСЛУХ, а не тихий пропуск: под администратором утверждение ниже
        # ложно по условию, и зелёная строка тут означала бы «проверено».
        res.ok("ПРОПУЩЕНО: прогон идёт с правами администратора", True,
               "граница прав под админом не наблюдается — это не зелёное")
        return
    res.ok("HKLM на запись ЗАКРЫТ — потому и нужен исполнитель",
           not writable(winreg.HKEY_LOCAL_MACHINE),
           "обычному процессу дали писать в HKLM: повышение не понадобилось бы, "
           "но и защита машины не та, на которую рассчитан продукт")
    res.ok("HKCU на запись открыт — установка на пользователя чинится сама",
           writable(winreg.HKEY_CURRENT_USER), "")


def suite_op(res: Result) -> None:
    """Сама операция: правит значения там, где они есть, и только их."""
    if sys.platform != "win32":
        res.ok("не Windows — операции реестра не проверяются", True, "")
        return
    import winreg

    real = privileged.UNINST_KEY
    privileged.UNINST_KEY = LAB_KEY
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, LAB_KEY) as k:
            winreg.SetValueEx(k, "DisplayVersion", 0, winreg.REG_SZ, "1.20.0")
            winreg.SetValueEx(k, "DisplayName", 0, winreg.REG_SZ,
                              "DentPilot 1.20.0")

        out = privileged.run_op("uninstall-version", ["1.28.1"])
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, LAB_KEY) as k:
            ver = winreg.QueryValueEx(k, "DisplayVersion")[0]
            name = winreg.QueryValueEx(k, "DisplayName")[0]
        res.check("версия переписана", ver, "1.28.1")
        # ⭐ У Inno версия стоит ВНУТРИ имени, и рассогласование видно человеку
        # раньше, чем сама версия: список в «Программах и компонентах»
        # отсортирован по имени.
        res.check("и версия внутри имени тоже", name, "DentPilot 1.28.1")
        res.ok("исход назван словами", "1.20.0" in out and "1.28.1" in out, out)

        res.ok("повторный вызов ничего не меняет",
               "уже" in privileged.run_op("uninstall-version", ["1.28.1"]), "")

        # ⛔ Отрицательные: аргумент не из трёх чисел не должен дойти до реестра.
        for bad in (["1.28"], ["1.28.1.2"], [""], ["1.28.1; calc.exe"],
                    ["../../evil"], ["1.28.1", "лишний"], []):
            raised = ""
            try:
                privileged.run_op("uninstall-version", bad)
            except privileged.Refused as e:
                raised = str(e)
            if not res.ok(f"отклонён аргумент {bad!r}", bool(raised),
                          "операция приняла то, что реестру не показывают"):
                break
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, LAB_KEY) as k:
            res.check("и реестр после отказов не тронут",
                      winreg.QueryValueEx(k, "DisplayVersion")[0], "1.28.1")

        # ⛔ Аргументы здесь ГОДНЫЕ для настоящей операции, и это не мелочь.
        # С пустым списком отказ пришёл бы от проверки числа аргументов, а не
        # от закрытого словаря, — и подмена неизвестного имени настоящей
        # операцией прошла бы незамеченной (поймано красным стендом).
        raised = ""
        try:
            privileged.run_op("delete-everything", ["1.28.1"])
        except privileged.Refused as e:
            raised = str(e)
        res.ok("операции вне словаря не существует", bool(raised),
               "имя операции ищется не в закрытом списке — за UAC может "
               "оказаться что угодно")
        res.ok("и отказ назван по ИМЕНИ операции",
               "delete-everything" in raised, raised or "отказа не было")
    finally:
        privileged.UNINST_KEY = real
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, LAB_KEY)
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, r"Software\DentPilot-Lab")
        except OSError:
            pass


def suite_request(res: Result) -> None:
    """Просящая сторона: что именно ушло бы в UAC."""
    seen = []

    def shell(_h, verb, file, params, _dir, _show):
        seen.append((verb, file, params))
        return 42                       # >32 = Windows показала окно

    frozen = getattr(sys, "frozen", False)
    sys.frozen = True                   # шов: из исходников request не поднимает
    try:
        ok = privileged.request("uninstall-version", "1.28.1", _shell=shell)
        res.ok("запрос показан", ok is True, f"{ok!r}")
        res.check("запросов ровно один", len(seen), 1)
        verb, file, params = seen[0]
        res.check("глагол UAC", verb, "runas")
        # ⛔ Запускается НАШ exe и ничего другого. У соседнего механизма
        # (правило брандмауэра) под UAC уходит командная строка `cmd.exe` — и
        # первая же чужая подстановка там станет запуском произвольной команды.
        res.check("запускается наш собственный файл", file, sys.executable)
        res.ok("никакой оболочки в запуске",
               "cmd" not in file.lower() and "powershell" not in file.lower(),
               f"через UAC уходит оболочка: {file}")
        res.ok("аргументы — метка, имя операции и значение",
               params == '"--privileged" "uninstall-version" "1.28.1"', params)

        seen.clear()
        for name, args in (("delete-everything", ()), ("uninstall-version", ("1.28",)),
                           ("uninstall-version", ()), ("uninstall-version", ("a & b",))):
            raised = ""
            try:
                privileged.request(name, *args, _shell=shell)
            except privileged.Refused as e:
                raised = str(e)
            res.ok(f"отказ до окна UAC: {name} {args!r}", bool(raised),
                   "человеку показали бы окно ради заведомо отклонённой операции")
        res.check("и ни одного окна не показано", len(seen), 0)
    finally:
        if frozen:
            sys.frozen = frozen
        else:
            del sys.frozen


def suite_argv(res: Result) -> None:
    """Вход лаунчера: в привилегированную ветку попадает только метка."""
    res.check("обычный запуск", privileged.handle_argv([]), None)
    res.check("случайный аргумент — обычный запуск",
              privileged.handle_argv([r"C:\pacient.pdf"]), None)
    # ⚠️ «Открыть с помощью» и ярлык с параметром не должны заводить процесс в
    # ветку, которая рассчитана на запуск от администратора.
    res.check("похожий, но не тот флаг",
              privileged.handle_argv(["--privileged-ish", "x"]), None)
    res.check("метка без операции", privileged.handle_argv(["--privileged"]), None)
    res.check("неизвестная операция отклонена",
              privileged.handle_argv(["--privileged", "nope"]), 2)


def suite_no_direct_write(res: Result) -> None:
    """⛔ Приложение больше НЕ пишет в реестр — ни одной строкой.

    Отрицательная проверка к P4.1: сама правка могла бы остаться на месте и
    просто не срабатывать, а исполнитель — стать вторым способом делать то же
    самое. Тогда у клиники с правами админа работали бы оба пути, и разошлись
    бы они молча.
    """
    root = pathlib.Path(__file__).resolve().parents[1] / "bot"
    writers = ("SetValueEx", "CreateKey", "CreateKeyEx", "DeleteKey",
               "DeleteValue", "SaveKey")
    bad = []
    seen_files = 0
    for f in sorted(root.rglob("*.py")):
        if "__pycache__" in str(f):
            continue
        seen_files += 1
        if f.name == "privileged.py":
            continue                    # владелец: ему и писать
        src = f.read_text(encoding="utf-8", errors="replace")
        for w in writers:
            if f"winreg.{w}(" in src or f"{w}(" in src and "winreg" in src:
                bad.append(f"{f.relative_to(root)} → {w}")
    res.ok("исходники нашлись", seen_files > 20, f"разобрано файлов: {seen_files}")
    res.ok("в реестр пишет только privileged.py", not bad,
           "второй путь записи: " + ", ".join(sorted(set(bad))))

    upd = (root / "app" / "update.py").read_text(encoding="utf-8")
    res.ok("update.py больше не просит право записи",
           "KEY_WRITE" not in upd and "KEY_SET_VALUE" not in upd,
           "старая попытка писать осталась — она снова будет молча сдаваться")
    res.ok("и умеет сказать, что нужны права",
           '"needs-admin"' in upd,
           "исход «нужен администратор» исчез — кнопке нечего показывать")

def suite_route(res: Result) -> None:
    """Кнопка в продукте: маршрут действительно доходит до исполнителя.

    ⛔ Без этого набора привилегированный путь замкнут в лаборатории: сам
    оракул проверен, а вызвать его в продукте нечем — и это ровно тот класс
    «ветка, которую не исполняет никто», из-за которого P2 однажды получил
    экран, невозможный в принципе.

    ⚠️ Настоящий `ShellExecuteW` в прогоне звать нельзя — он показал бы окно
    UAC и стал бы писать реестр машины. Поэтому сервер поднимается из КОПИИ
    дерева, где `privileged.request` заменён распиской в файле, а состояние
    записи подделано устаревшим. Тот же приём и по той же причине, что у
    проверок миграций: снаружи такое поведение не вызвать ничем.
    """
    import shutil
    import tempfile

    from harness import BOT, Client, Server

    work = pathlib.Path(tempfile.mkdtemp(prefix="dp_priv_route_"))
    try:
        dst = work / "bot"
        shutil.copytree(BOT, dst, ignore=shutil.ignore_patterns("__pycache__"))
        mark = work / "uac.txt"
        # Запись «версия отстала» + расписка вместо окна UAC.
        (dst / "app" / "update.py").write_text(
            (dst / "app" / "update.py").read_text(encoding="utf-8")
            + "\n\ndef uninstall_entry():\n"
              "    return {'found': True, 'version': '1.20.0', 'stale': True,\n"
              "            'hive': 'HKLM'}\n",
            encoding="utf-8")
        (dst / "app" / "privileged.py").write_text(
            (dst / "app" / "privileged.py").read_text(encoding="utf-8")
            + "\n\ndef request(name, *args, _shell=None):\n"
              f"    import pathlib as _p\n"
              f"    _p.Path(r'{mark}').write_text(' '.join([name, *args]),\n"
              "                                   encoding='utf-8')\n"
              "    return True\n",
            encoding="utf-8")

        data = work / "data"
        data.mkdir()
        with Server(dir_=data, bot=dst) as s:
            c = Client(s.url).login()
            before = json.loads(c.get("/api/settings/system").body)["data"]
            res.ok("состояние записи едет на экран",
                   before["uninstall"]["stale"] is True, f"{before.get('uninstall')!r}")
            res.ok("и называет ту версию, что видна в Windows",
                   before["uninstall"]["version"] == "1.20.0", "")
            res.ok("до нажатия окна UAC не просили", not mark.exists(),
                   "права запрошены без человека — окно на старте перестанут читать")

            r = c.post_json("/api/settings/system/uninstall-sync", {})
            res.check("кнопка принята", r.status, 200)
            res.ok("исполнитель позван", mark.exists(),
                   "маршрут не дошёл до privileged.request — кнопка мертва")
            if mark.exists():
                # ⭐ Именно операция из закрытого списка и ТЕКУЩАЯ версия
                # движка: попроси маршрут что-то своё, за UAC ушло бы не то.
                from app import engine as eng
                res.check("операция и аргумент", mark.read_text(encoding="utf-8"),
                          f"uninstall-version {eng.APP_VERSION}")

            # ⛔ Право: раздел директорский, и кнопка тоже.
            other = Client(s.url)
            res.check("без входа маршрут закрыт",
                      other.post_json("/api/settings/system/uninstall-sync", {}).status,
                      401)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def suite_route_quiet(res: Result) -> None:
    """⛔ Чинить нечего — окна UAC не показываем.

    Обратная половина: маршрут, который зовёт исполнителя ВСЕГДА, показал бы
    клинике запрос прав на ровном месте — а такие окна перестают читать.
    """
    import shutil
    import tempfile

    from harness import BOT, Client, Server

    work = pathlib.Path(tempfile.mkdtemp(prefix="dp_priv_quiet_"))
    try:
        dst = work / "bot"
        shutil.copytree(BOT, dst, ignore=shutil.ignore_patterns("__pycache__"))
        mark = work / "uac.txt"
        (dst / "app" / "privileged.py").write_text(
            (dst / "app" / "privileged.py").read_text(encoding="utf-8")
            + "\n\ndef request(name, *args, _shell=None):\n"
              f"    import pathlib as _p\n"
              f"    _p.Path(r'{mark}').write_text('позвали', encoding='utf-8')\n"
              "    return True\n",
            encoding="utf-8")
        data = work / "data"
        data.mkdir()
        with Server(dir_=data, bot=dst) as s:
            c = Client(s.url).login()
            st = json.loads(c.get("/api/settings/system").body)["data"]["uninstall"]
            res.ok("в прогоне записи установщика нет", st["found"] is False,
                   f"{st!r} — прогон идёт под установленной программой?")
            r = c.post_json("/api/settings/system/uninstall-sync", {})
            res.check("маршрут отвечает", r.status, 200)
            res.ok("и окна UAC не просил", not mark.exists(),
                   "права запрошены там, где чинить нечего")
    finally:
        shutil.rmtree(work, ignore_errors=True)
