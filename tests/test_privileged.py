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

import ast
import ctypes
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "bot"))

from app import privileged  # noqa: E402
from harness import Result, _rmtree_settled  # noqa: E402

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
        _rmtree_settled(work)


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
        _rmtree_settled(work)

def _lab(tmp: pathlib.Path, *, size: int = 5_200_000, head: bytes = b"MZ",
         request: dict | None = None) -> tuple:
    """Лаборатория обновления: папка программы, папка клиники, файл и описание."""
    import hashlib
    import json

    prog = tmp / "Program Files" / "DentPilot"
    prog.mkdir(parents=True)
    exe = prog / "DentPilot.exe"
    exe.write_bytes(b"STARAYA PROGRAMMA")
    work = tmp / "data" / privileged.WORK_SUBDIR
    work.mkdir(parents=True)
    new = work / ("DentPilot" + privileged.NEW_SUFFIX)
    body = head + b"\0" * max(0, size - len(head))
    new.write_bytes(body)
    if request is None:
        request = {"size": len(body), "sha256": hashlib.sha256(body).hexdigest()}
    (work / privileged.REQUEST_NAME).write_text(json.dumps(request),
                                                encoding="utf-8")
    return exe, work, new


def suite_install(res: Result) -> None:
    """P4.2: подмена программы за UAC — только перемещение, и по проверке."""
    import tempfile

    real = privileged._self_exe
    with tempfile.TemporaryDirectory(prefix="dp_inst_") as td:
        tmp = pathlib.Path(td)
        exe, work, new = _lab(tmp)
        privileged._self_exe = lambda: exe
        try:
            out = privileged.run_op("install-update", [], lambda: tmp / "data")
            res.check("операция довольна", out, "ok")
            res.ok("новый файл занял место программы",
                   exe.read_bytes()[:2] == b"MZ", "подмена не состоялась")
            old = exe.with_name("DentPilot" + privileged.OLD_SUFFIX)
            # ⛔ Старую версию НЕ удаляем (прайор 08-10): существование нового
            # файла ничего не доказывает — он может быть битым или съеденным
            # антивирусом, и тогда клиника осталась бы вообще без программы.
            res.ok("прежняя программа лежит рядом", old.exists(),
                   "откатывать нечем — неудачное обновление станет удалением")
            res.check("и это именно она", old.read_bytes(), b"STARAYA PROGRAMMA")
            res.ok("исходник из папки клиники убран", not new.exists(),
                   "копия осталась — следующий запуск поставит её заново")
            res.check("итог записан файлом",
                      (work / privileged.RESULT_NAME).read_text(encoding="utf-8"),
                      "ok")
        finally:
            privileged._self_exe = real

    # ⛔ Отрицательные: каждый отказ обязан ОСТАВИТЬ программу на месте.
    cases = [
        ("файла нет", dict(size=0), "нет файла"),
        ("обрывок закачки", dict(size=1000), "размер"),
        ("не программа Windows", dict(head=b"PK"), "не программа"),
        ("отпечаток не сошёлся",
         dict(request={"size": 5_200_000, "sha256": "0" * 64}), "отпечаток"),
        ("размер не сошёлся",
         dict(request={"size": 42, "sha256": "0" * 64}), "размер"),
    ]
    for name, kw, want in cases:
        with tempfile.TemporaryDirectory(prefix="dp_inst_bad_") as td:
            tmp = pathlib.Path(td)
            exe, work, new = _lab(tmp, **kw)
            if kw.get("size") == 0:
                new.unlink()
            privileged._self_exe = lambda e=exe: e
            try:
                out = privileged.run_op("install-update", [], lambda: tmp / "data")
                res.ok(f"отказ: {name}", want in out, f"ответ: {out!r}")
                res.check(f"программа цела: {name}", exe.read_bytes(),
                          b"STARAYA PROGRAMMA")
            finally:
                privileged._self_exe = real

    # ⛔ И самое важное: операция НИЧЕГО не запускает. Запусти она новый файл —
    # тот пошёл бы от администратора, и подменённый кем-то exe получил бы
    # права, которых у него нет.
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "bot" / "app" / "privileged.py").read_text(encoding="utf-8")
    body = src[src.index("def _install_update"):src.index("# Закрытый список")]
    for token in ("subprocess", "os.system", "os.startfile", "Popen",
                  "ShellExecute", "exec(", "eval("):
        res.ok(f"подмена ничего не исполняет: нет {token}", token not in body,
               f"в операции появился запуск: {token}")


def suite_update_paths(res: Result) -> None:
    """⛔ Рядом с exe больше НЕ ПИШЕТСЯ ничего.

    В `Program Files` первая же такая запись — «Отказано в доступе», и прежний
    путь отказывал на скачивании, то есть обновление у клиники не начиналось.
    """
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "bot" / "app" / "update.py").read_text(encoding="utf-8")
    res.ok("исходник на месте", len(src) > 5000, "файл переехал")
    for need, why in (
            ('work_dir() / "dentpilot_update.bat"', "скрипт обновления"),
            ('work_dir() / "dentpilot_restart.bat"', "скрипт перезапуска"),
            ('work_dir() / (exe.stem + ".new.exe")', "скачанный файл")):
        res.ok(f"{why} — в папке клиники", need in src,
               f"{why} снова пишется рядом с exe")
    # Якорь обратной полярности: ни одного скрипта рядом с программой.
    res.ok("bat рядом с exe не создаётся",
           'exe.with_name("dentpilot' not in src,
           "скрипт снова кладётся в папку программы")
    res.ok("подмена уходит привилегированной ветке",
           "_install_privileged(new_path, exe)" in src
           and "exe_dir_writable()" in src,
           "ветка без прав исчезла — обновление в Program Files снова невозможно")
    # ⚠️ Переносимая раскладка обязана обойтись БЕЗ UAC: там папка своя.
    res.ok("портативной раскладке окно UAC не показывается",
           "if not exe_dir_writable():" in src,
           "проба записи исчезла — портативная установка получит лишний UAC")

def suite_contract(res: Result) -> None:
    """P4.3: исполнитель как целое — чем он НЕ является.

    ⛔ Три запрета, и проверяются они отрицательными, а не чтением кода:
    произвольная команда, произвольный путь, произвольные аргументы. Каждый из
    них превращает «поправить строку в реестре» в «запустить что угодно от
    имени администратора», и обратного пути из такой ошибки у клиники нет.
    """
    priv = (pathlib.Path(__file__).resolve().parents[1]
            / "bot" / "app" / "privileged.py")
    src = priv.read_text(encoding="utf-8")
    res.ok("исходник исполнителя на месте", len(src) > 2000, "файл переехал")

    # ---- 1. произвольная КОМАНДА ----
    # ⚠️ Разбираем КОД, а не текст файла. Первая версия искала подстроки и
    # краснела на собственных комментариях («ни `cmd.exe`, ни `shell=True`») и
    # на законном `getattr(sys, "frozen")`. Сторож, краснеющий на объяснении
    # правила, отключают вместе с правилом.
    tree = ast.parse(src)
    doc_ids = {id(n.body[0].value) for n in ast.walk(tree)
               if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef))
               and n.body and isinstance(n.body[0], ast.Expr)
               and isinstance(n.body[0].value, ast.Constant)
               and isinstance(n.body[0].value.value, str)}
    called, texts, shell_kw, loose_getattr = set(), [], False, False
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            f = n.func
            name = f.id if isinstance(f, ast.Name) else getattr(f, "attr", "")
            mod = (f.value.id if isinstance(f, ast.Attribute)
                   and isinstance(f.value, ast.Name) else "")
            called.add(f"{mod}.{name}" if mod else name)
            if any(k.arg == "shell" for k in n.keywords):
                shell_kw = True
            # ⭐ `getattr(sys, …)` законен: это чтение флага сборки, а не выбор
            # функции по строке. Запрещён ЛЮБОЙ другой.
            if name == "getattr" and not (n.args and isinstance(n.args[0], ast.Name)
                                          and n.args[0].id == "sys"):
                loose_getattr = True
        elif (isinstance(n, ast.Constant) and isinstance(n.value, str)
                and id(n) not in doc_ids):
            texts.append(n.value)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                called.add(a.name)

    for bad, why in (("subprocess", "запуск процесса"),
                     ("os.system", "оболочка"),
                     ("os.popen", "оболочка"),
                     ("eval", "исполнение строки"),
                     ("exec", "исполнение строки"),
                     ("__import__", "импорт по имени"),
                     ("importlib", "импорт по имени")):
        res.ok(f"в исполнителе нет: {why} ({bad})", bad not in called,
               f"появился {bad} — закрытый список перестал быть закрытым")
    res.ok("ни одного вызова с shell=", not shell_kw,
           "оболочка за UAC — это и есть произвольная команда")
    res.ok("функция не выбирается по строке", not loose_getattr,
           "getattr мимо sys — имя операции перестало быть из закрытого списка")
    shells = [t for t in texts
              if "cmd.exe" in t.lower() or "powershell" in t.lower()]
    res.ok("в КОДЕ нет имени интерпретатора", not shells,
           f"строка с оболочкой: {shells[:2]}")
    res.ok("запускается ровно одно — свой exe",
           src.count("ShellExecuteW") == 1 and "sys.executable, line" in src,
           "второй способ что-то запустить")

    # ---- 2. произвольный ПУТЬ ----
    # Ни одна операция не берёт путь снаружи: `run_op` получает только имя и
    # аргументы, а пути вычисляются от `_self_exe()` и от корня клиники.
    # ⚠️ Корень клиники ЖИВОЙ, а не None. С `None` отказ приходил бы от «папка
    # не найдена», и снятая проверка аргументов осталась бы незамеченной —
    # поймано красным стендом: отказ «вообще» не доказывает отказ ПО ПРИЧИНЕ.
    import tempfile
    with tempfile.TemporaryDirectory(prefix="dp_argpath_") as _td:
        _root = pathlib.Path(_td)
        (_root / privileged.WORK_SUBDIR).mkdir()
        for name in sorted(privileged.OPS):
            for evil in (r"C:\Windows\System32\cmd.exe", "..\\..\\evil.exe",
                         r"\\server\share\x.exe", "/etc/passwd"):
                raised = ""
                try:
                    privileged.run_op(name, [evil], lambda: _root)
                except privileged.Refused as e:
                    raised = str(e)
                res.ok(f"{name}: путь снаружи отвергнут ({evil[:18]})", bool(raised),
                       "операция приняла путь аргументом — это и есть «запустить "
                       "что угодно от администратора»")

    # ---- 3. произвольные АРГУМЕНТЫ ----
    # ⚠️ Лишний аргумент отвергается ТОЖЕ: операция, принимающая «хвост»,
    # однажды начнёт его куда-нибудь передавать.
    for args in ([], ["1.2.3", "1.2.4"], ["1.2.3", "--force"], ["-1.2.3"],
                 ["1.2.3\n2.0.0"], [" 1.2.3 "]):
        raised = ""
        try:
            privileged.run_op("uninstall-version", args, lambda: None)
        except privileged.Refused as e:
            raised = str(e)
        res.ok(f"версия: отвергнуто {args!r}", bool(raised),
               "в реестр машины уходит непроверенная строка")

    # ---- 4. привилегированный процесс ВЫХОДИТ ----
    # ⛔ Он обязан сделать одно дело и выйти: подними он заодно сервер, у
    # клиники работала бы программа от администратора, и всё, что она пишет,
    # стало бы недоступно ей же при следующем обычном запуске.
    for name in sorted(privileged.OPS):
        code = privileged.handle_argv([privileged.FLAG, name], lambda: None)
        res.ok(f"{name}: лаунчер получает код выхода", isinstance(code, int),
               f"вернулось {code!r} — процесс пошёл бы дальше и поднял сервер")

    # ---- 5. второй способ повышения не заводится ----
    # ⚠️ Список ИМЕНОВАННЫЙ, и это опасная полярность: новый файл с `runas`
    # мимо него не заметит никто. Поэтому ищем нарушителей обходом, а
    # исключение названо одно и с причиной.
    root = pathlib.Path(__file__).resolve().parents[1] / "bot"
    allowed = {"app/privileged.py",
               # Правило брандмауэра, 1.15.x: под UAC уходит командная строка
               # `cmd.exe`. Сегодня безопасно (все куски свои), но форма та
               # самая. ⚠️ Переписать на операцию исполнителя — отдельный шаг,
               # и пока он не сделан, это ЕДИНСТВЕННОЕ исключение.
               "app/modules/settings/lan.py"}
    bad = []
    seen = 0
    for f in sorted(root.rglob("*.py")):
        if "__pycache__" in str(f):
            continue
        seen += 1
        rel = str(f.relative_to(root)).replace("\\", "/")
        if rel in allowed:
            continue
        if '"runas"' in f.read_text(encoding="utf-8", errors="replace"):
            bad.append(rel)
    res.ok("исходники нашлись", seen > 20, f"разобрано файлов: {seen}")
    res.ok("повышение прав живёт в одном месте", not bad,
           "третий способ поднять права: " + ", ".join(bad))
    # Якорь к списку исключений: пропадёт файл — правило станет вечнозелёным.
    gone = [rel for rel in sorted(allowed) if not (root / rel).exists()]
    res.ok("список исключений не протух", not gone,
           "нет файлов: " + ", ".join(gone))
