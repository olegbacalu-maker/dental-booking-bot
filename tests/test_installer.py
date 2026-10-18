# -*- coding: utf-8 -*-
"""P3-min ступень 2: контракт установщика как ИСХОДНИКА.

⛔ Граница ступени: проверяется текст `DentPilot.iss` и факт его
компилируемости. Поведение готового `installer.exe` — установка, права,
переезд данных — это ступени 3 и 4, и здесь их нет намеренно.

⚠️ Установщик до 20.09 не был покрыт ничем вообще: правка в нём доезжала до
клиники, не встретив ни одной проверки.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import tempfile

from harness import BOT, Result, _rmtree_settled  # noqa: E402

ISS = BOT.parent / "installer" / "DentPilot.iss"
SHELL_CONF = BOT.parent / "shell" / "tauri.conf.json"
# Папка программы так, как её собирает Build-Installer.ps1 и кладёт мастер
# (контракт Tauri § 1): оболочка + движок папкой.
PROG = BOT.parent / "dist" / "DentPilot"


def _src() -> str:
    return ISS.read_text(encoding="utf-8-sig")


def suite_contract(res: Result) -> None:
    """Директивы, без которых раскладка P3-min не получается."""
    # сторож за сторожом: не нашли файл — падаем здесь, а не зеленеем ниже
    if not res.ok("DentPilot.iss на месте", ISS.exists(),
                  f"нет {ISS} — все проверки ниже стали бы бессмысленны"):
        return
    s = _src()

    res.ok("установка per-machine", "PrivilegesRequired=admin" in s,
           "без admin не создать ни Program Files, ни прав на папку данных")
    # ⛔ Не давать обычному пользователю продавить установку «под себя»:
    # установка — разовое действие того, у кого права есть.
    res.ok("понижение прав не разрешено",
           "PrivilegesRequiredOverridesAllowed" not in s,
           "появился override — установка съедет обратно в профиль пользователя")
    res.ok("папка программы — Program Files",
           "DefaultDirName={commonpf}\\{#AppName}" in s,
           "целевая папка не константа Program Files")
    # ⛔ AppId — по нему Windows опознаёт обновление поверх старой версии
    res.ok("AppId не менялся",
           "{{B8836ACC-EA41-4B1C-9FEB-DC61ADD35754}" in s,
           "смена AppId = вторая установка рядом, а не обновление")
    res.ok("DefaultInstallDir удалён",
           "function DefaultInstallDir" not in s,
           "старый выбор папки жив — предложит раскладку «данные рядом с exe»")

    # ⛔ Запрет Program Files снят вместе с причиной, по которой он стоял
    res.ok("запрет Program Files снят", "PfWarnText" not in s,
           "мастер отвергнет собственную папку по умолчанию")

    # ⭐ Допущение, на котором стоит детекция. `app/legacy.py` ищет ярлык в
    # ОБЩИХ папках потому, что `{auto*}` при PrivilegesRequired=admin — это
    # `{common*}`. Смени здесь `{auto` на `{user`, и детекция начнёт искать
    # там, куда никто не пишет: ни падения, ни красноты, просто «не нашли».
    icons = [ln for ln in s.splitlines()
             if ln.lstrip().startswith("Name:") and "{#AppExeName}" in ln]
    res.ok("ярлыки создаются (иначе проверка ниже пуста)", len(icons) >= 2,
           f"в [Icons] найдено {len(icons)} строк")
    res.ok("ярлыки идут через {auto…} — значит в ОБЩИЕ папки",
           all("{auto" in ln for ln in icons),
           "ярлык уехал в профиль пользователя, а legacy.shortcut_paths() "
           "ищет общие: пути разошлись молча")


def dirs_comment(s: str) -> str:
    """Комментарий над [Dirs] — там живёт аудит писателей папки данных."""
    return s[s.index("[Dirs]"):s.index("[Files]")]


def suite_acl(res: Result) -> None:
    """Права на папку данных: кому, чем и как проверено."""
    s = _src()
    dirs = s[s.index("[Dirs]"):s.index("[Files]")]
    for sub in ("", "\\data", "\\data\\backups", "\\data\\files"):
        line = f'Name: "{{commonappdata}}\\{{#AppName}}{sub}"'
        res.ok(f"папка данных объявлена: …{sub or ' (корень)'}", line in dirs,
               "без [Dirs] права придётся выдавать вслепую")
    res.check("у всех папок данных — users-modify",
              dirs.count("Permissions: users-modify"), 4)

    # ⛔ Папке ПРОГРАММЫ прав на запись не выдаём никогда: с приходом
    # привилегированного обновлятора (P4) это означало бы, что любой
    # пользователь подменяет бинарник, исполняемый от LocalSystem.
    app_perm = [ln for ln in s.splitlines()
                if "Permissions:" in ln and "{app}" in ln]
    res.ok("у папки программы прав на запись НЕТ", not app_perm,
           "найдено: " + " | ".join(app_perm))

    # ⛔ По SID, а не по имени: на румынской Windows группа зовётся Utilizatori
    res.ok("права выдаются по SID", "*S-1-5-32-545" in s,
           "/grant по имени группы на румынской Windows не найдёт ничего")
    # ⚠️ Строка САМОЙ команды, а не первая с «/grant»: до 12.10 ею оказывалась
    # строка комментария («/grant Users: не найдёт…»), и проверка смотрела мимо
    # команды — зелёная при любом ключе. Отсюда и «нашлась».
    grant = next((ln for ln in s.splitlines()
                  if "/grant *S-1-5-32-545" in ln and "'" in ln), "")
    res.ok("строка команды icacls нашлась", bool(grant),
           "проверка ключей смотрела бы в пустоту")
    res.ok("у icacls нет /C", bool(grant) and "/C" not in grant,
           "/C велит продолжать после ошибок — код возврата перестаёт значить")
    res.ok("результат icacls проверяется", "(RC = 0)" in s,
           "код возврата не читается — тихо неверные права")

    # Канарейка 1.41.0 (12.10): тихое обновление встало на окне о правах —
    # обычный MsgBox ключ /SUPPRESSMSGBOXES не гасит. Окно о правах — только
    # SuppressibleMsgBox; и текст не обещает остановку: шаг идёт ПОСЛЕ установки.
    acl_box = re.findall(r"(\w*MsgBox)\(FmtMessage\(CustomMessage\('AclText'\)", s)
    res.ok("окно о правах гасится тихим режимом",
           acl_box == ["SuppressibleMsgBox"],
           f"найдено: {acl_box} — тихое обновление встанет на окне до нажатия OK")
    acl_text = next((ln for ln in s.splitlines() if ln.startswith("ro.AclText=")), "")
    res.ok("текст о правах не обещает остановку установки",
           bool(acl_text) and "a fost oprită" not in acl_text,
           "шаг прав идёт после установки — «oprită» неправда")
    # Файлы данных пишет САМА программа от обычной учётки (auth.json при
    # входе, clinic.json при сохранении настроек, dental.env при переключении
    # сети): admin-only запись сломала бы их у неадмина. Атаку «удалил
    # auth.json — поставил свой PIN» закрывает программа (auth-reset за UAC).
    narrowed = [ln.strip()[:70] for ln in s.splitlines()
                if "icacls" in ln and not ln.lstrip().startswith((";", "//", "{"))
                and any(f in ln for f in ("dental.env", "auth.json", "clinic.json"))]
    res.ok("файлы, которые пишет программа, icacls не сужает", not narrowed,
           "admin-only запись = программа у неадмина перестаёт сохранять: "
           + " | ".join(narrowed))
    res.ok("причина записана в самом скрипте, у [Dirs]",
           "auth-reset" in dirs_comment(s), "следующий сузит права и сломает вход")
    res.ok("отказ icacls пишется в журнал и повторяется",
           "ExecAndLogOutput(" in s and "for Attempt := 1 to 3" in s,
           "вывод icacls выбрасывается — отказ не назовёт файл")


def suite_first_run(res: Result) -> None:
    """Первый запуск и блокировка поверх старой раскладки."""
    s = _src()
    run = [ln for ln in s.splitlines() if "{cm:LaunchProgram" in ln]
    res.ok("строка запуска программы найдена", bool(run), "")
    if run:
        tail = s[s.index(run[0]):s.index(run[0]) + 400]
        res.ok("первый запуск — от ВОШЕДШЕГО, не от админа",
               "runasoriginaluser" in tail,
               "без флага db.key завернётся под DPAPI администратора")

    res.ok("установка поверх старой раскладки заблокирована",
           "function PrepareToInstall" in s and "LegacyText" in s,
           "нет блокировки — клиника получит две картотеки сразу")

    # ⛔ 12.10, канарейка 1.41.2 (обновление встало со второго раза): тихое
    # обновление ждёт, пока DentPilot.exe не отпустит никто, ДО проверки
    # Restart Manager. Иначе тот ловит загрузчик onefile на выходе (~0,5 с
    # после программы) и проигрывает гонку: событие 10006, Abort, «fail».
    # Ждать — только при /RESULT=: в мастере вручную это выглядело бы зависанием.
    prep = s[s.index("function PrepareToInstall"):] if "function PrepareToInstall" in s else ""
    prep = prep[:prep.find("\nend;")]
    res.ok("тихое обновление ждёт выхода программы до Restart Manager",
           "{param:RESULT|}" in prep and "WaitAppExit()" in prep
           and prep.find("WaitAppExit()") < prep.find("LegacyDir()"),
           "PrepareToInstall не ждёт — RM снова застанет выходящий процесс")
    res.ok("ждём по пути exe программы",
           "ExecutablePath = " in s and "{app}\\{#AppExeName}" in s,
           "по имени попались бы чужие копии DentPilot.exe")
    res.ok("намерение установщика записывается",
           "install.json" in s and "procedure WriteInstallJson" in s, "")
    res.ok("канал берётся параметром, а не угадывается",
           "{param:CHANNEL|stable}" in s,
           "канареечная машина молча вернётся на stable")
    res.ok("свой файл убираем за собой",
           'Type: files; Name: "{app}\\install.json"' in s, "")

    # ⛔ P3-final, в этой ступени его быть не должно.
    # ⚠️ Ищем СОЗДАНИЕ ярлыка, а не упоминание константы: `{userstartup}`
    # законно стоит в детекции старой установки, где ярлык ЧИТАЕТСЯ. Правило,
    # запрещающее само слово, краснело бы на исправном коде — и его бы
    # ослабили.
    res.ok("автозапуск отложен до P3-final",
           'Name: "{userstartup}' not in s and "Tasks: autostart" not in s,
           "ярлык автозапуска уехал бы в Startup администратора")


def suite_pascal_comments(res: Result) -> None:
    """⛔ Комментарий Pascal не может содержать константу Inno.

    Наступлено 20.09: в `{ … }` стояло `{app}`, первая же закрывающая скобка
    закрыла комментарий, а остаток пояснения стал кодом — `ISCC` упал
    «Syntax error» на строке, где синтаксис был ни при чём. Тот же класс, что
    «комментарий в комментарии» из карты.
    """
    s = _src()
    code = s[s.index("[Code]"):]
    bad = [m.group(0).replace("\n", " ")[:70]
           for m in re.finditer(r"\{[^{}]*\{", code)]
    res.ok("в комментариях Pascal нет вложенных скобок", not bad,
           "комментарий оборвётся на константе: " + " | ".join(bad))

    # ⛔ Путь, собранный через «..», доезжает до экрана как есть:
    # «C:\Users\Public\Documents\..\DentPilot». Клинике его не прочитать,
    # поддержке по телефону не спросить, а P2 получит такой же корень переезда.
    # Поймано живым прогоном 21.09 — компиляция и разбор текста молчали.
    # ⚠️ Только [Code]: в [Files] «..\dist\...» законен, это путь СБОРКИ.
    dots = [ln.strip()[:70] for ln in code.splitlines()
            if "\\..\\" in ln and not ln.strip().startswith("//")]
    res.ok("в [Code] пути не собираются через «..»", not dots,
           "ненормализованный путь уедет на экран и в миграцию: "
           + " | ".join(dots))


def section(s: str, name: str) -> str:
    """Секция `.iss` от СТРОКИ-заголовка `[name]` до следующего заголовка.
    ⚠️ Не `s.index("[Run]")`: имя секции стоит и в комментариях (7ec26d7
    упомянул «[Run]» выше `[Icons]`, и срез ярлыков стал пустым)."""
    m = re.search(rf"^\[{re.escape(name)}\][ \t]*$", s, flags=re.M)
    if not m:
        return ""
    nxt = re.search(r"^\[[A-Za-z]+\][ \t]*$", s[m.end():], flags=re.M)
    return s[m.start():m.end() + nxt.start()] if nxt else s[m.start():]


def tauri_layout_problems(s: str, conf: dict) -> list[str]:
    """Нарушения раскладки Tauri в тексте `.iss` (Т9, контракт § 1) словами.
    `conf` — `shell/tauri.conf.json` оболочки.

    Текст, а не файл: та же функция проверяется на испорченных копиях."""
    bad = []
    aumid = conf.get("identifier", "")
    files = section(s, "Files")
    if 'Source: "..\\dist\\DentPilot\\{#AppExeName}"; DestDir: "{app}"' not in files:
        bad.append("оболочка DentPilot.exe не кладётся в корень программы из dist\\DentPilot")
    eng = next((ln for ln in files.splitlines()
                if 'Source: "..\\dist\\DentPilot\\{#EngineDir}\\*"' in ln), "")
    tail = files[files.find(eng):files.find(eng) + 300] if eng else ""
    if not eng or 'DestDir: "{app}\\{#EngineDir}"' not in tail or "recursesubdirs" not in tail:
        bad.append("движок не кладётся папкой engine\\ целиком (recursesubdirs)")
    if not re.search(r'#define EngineDir\s+"engine"', s) or \
            not re.search(r'#define EngineExe\s+"DentPilot-Engine.exe"', s):
        bad.append("имя папки или exe движка не то, что ищет оболочка (engine\\DentPilot-Engine.exe)")
    block = section(s, "Icons")
    icons = [ln for ln in block.splitlines() if ln.lstrip().startswith("Name:")]
    if not icons or block.count('AppUserModelID: "{#AppUserModelID}"') != len(icons):
        bad.append("не у каждого ярлыка паспорт AppUserModelID — Windows не покажет уведомления")
    m = re.search(r'#define AppUserModelID\s+"([^"]+)"', s)
    if not m or m.group(1) != aumid:
        bad.append(f"паспорт ярлыка {m.group(1) if m else None!r} не равен identifier оболочки "
                   f"{aumid!r} (shell/tauri.conf.json) — уведомления не свяжутся с ярлыком")
    inst = section(s, "InstallDelete")
    if 'Type: filesandordirs; Name: "{app}\\{#EngineDir}"' not in inst:
        bad.append("старый движок не убирается перед установкой — лишние файлы прошлой версии останутся в _internal\\")
    uninst = section(s, "UninstallDelete")
    if 'Type: filesandordirs; Name: "{app}\\{#EngineDir}"' not in uninst:
        bad.append("удаление программы не убирает папку движка")
    count = s[s.find("function AppProcessCount"):]
    count = count[:count.find("\nend;")]
    if "{#EngineDir}\\{#EngineExe}" not in count or " OR ExecutablePath = " not in count:
        bad.append("тихое обновление ждёт только оболочку — движок держит файлы engine\\ дольше")
    if "WebView2Missing()" not in s[s.find("procedure CurStepChanged"):]:
        bad.append("после [Run] нет проверки WebView2 — без него окно оболочки не создаётся, а клиника не узнает")
    # Требования Т10 (обновление, 18.10). AppMutex: в тихом режиме найденный
    # мьютекс = отказ установки, а старая оболочка гаснет ~1 с после «started».
    if re.search(r"^\s*AppMutex\s*=", s, flags=re.M):
        bad.append("AppMutex в [Setup] — тихое обновление откажет, пока старая оболочка гаснет")
    # [InstallDelete] — только engine\: в {app}\updates лежит копия РАБОТАЮЩЕГО
    # мастера (privileged install-setup), а {app} целиком — чужие файлы человека.
    extra = [ln.strip() for ln in inst.splitlines() if ln.strip().startswith("Type:")
             and ln.strip() != 'Type: filesandordirs; Name: "{app}\\{#EngineDir}"']
    if extra:
        bad.append("[InstallDelete] трогает не только engine\\: " + " | ".join(extra))
    # удаление от администратора не лезет в профили учёток и в данные клиники
    if re.search(r"\{(localappdata|userappdata|commonappdata|userprofile)\}", uninst):
        bad.append("[UninstallDelete] трогает профиль учётки или данные клиники")
    # издатель оболочки — тот же, что у мастера (а он сверен с exe движка
    # `sync_version --check`): иначе «Свойства» DentPilot.exe и «Установленные
    # приложения» назовут поставщика по-разному
    pub = re.search(r'#define AppPublisher\s+"([^"]+)"', s)
    if not pub or (conf.get("bundle") or {}).get("publisher") != pub.group(1):
        bad.append(f"издатель оболочки {(conf.get('bundle') or {}).get('publisher')!r} не равен "
                   f"издателю мастера {pub.group(1) if pub else None!r} (shell/tauri.conf.json)")
    return bad


def suite_tauri_layout(res: Result) -> None:
    """Мастер ставит раскладку Tauri (Т9, 18.10): `{app}\\DentPilot.exe` — оболочка,
    `{app}\\engine\\` — движок; ярлыки несут паспорт `md.dentpilot.app`.

    ⚠️ Все нарушения тихие: мастер собирается, ставится, ярлык открывает окно —
    просто уведомлений нет (паспорт), или у клиники копится мусор прошлых
    движков, или тихое обновление проигрывает гонку движку, ещё держащему
    файлы. Поэтому правило здесь, а его порчи — рядом."""
    if not res.ok("tauri.conf.json оболочки на месте", SHELL_CONF.exists(),
                  "сверять паспорт ярлыка не с чем"):
        return
    conf = json.loads(SHELL_CONF.read_text(encoding="utf-8"))
    s = _src()
    res.check("сегодня раскладка Tauri в мастере верна", tauri_layout_problems(s, conf), [])
    for label, broken, want in (
        ("ярлык рабочего стола без паспорта",
         s.replace('AppUserModelID: "{#AppUserModelID}"; Tasks: desktopicon', "Tasks: desktopicon"),
         "паспорт"),
        ("паспорт разошёлся с оболочкой", s.replace('"md.dentpilot.app"', '"md.dentpilot"'), "identifier"),
        ("движок без подпапок", s.replace("recursesubdirs createallsubdirs", "createallsubdirs"),
         "recursesubdirs"),
        ("старый движок не убирается",
         s.replace('Type: filesandordirs; Name: "{app}\\{#EngineDir}"\n\n[Files]', '\n[Files]'),
         "перед установкой"),
        ("ждём только оболочку", s.replace(" OR ExecutablePath = ", " AND ExecutablePath = "),
         "ждёт только оболочку"),
        ("AppMutex", s.replace("CloseApplications=yes", "CloseApplications=yes\nAppMutex=DentPilotShell"),
         "AppMutex"),
        ("[InstallDelete] чистит updates\\",
         s.replace('Type: filesandordirs; Name: "{app}\\{#EngineDir}"\n\n[Files]',
                   'Type: filesandordirs; Name: "{app}\\{#EngineDir}"\n'
                   'Type: filesandordirs; Name: "{app}\\updates"\n\n[Files]'), "не только engine"),
        ("удаление чистит профиль учётки",
         s.replace("[UninstallDelete]\n", '[UninstallDelete]\nType: filesandordirs; Name: "{localappdata}\\DentPilot"\n'),
         "профиль учётки"),
        ("издатель оболочки другой", s.replace('#define AppPublisher "A.I. Oleg Bacalu"',
                                               '#define AppPublisher "Oleg Bacalu"'), "издатель оболочки"),
    ):
        got = tauri_layout_problems(broken, conf)
        res.ok(f"порча «{label}» — находка", broken != s and any(want in b for b in got),
               f"находки: {got}" if broken != s else "порча не применилась — якорь устарел")


def suite_compiles(res: Result) -> None:
    """Компилируется ли скрипт. ⚠️ Пропуск печатается ВСЛУХ.

    Нужны `ISCC.exe` и собранная папка программы `dist\\DentPilot` (оболочка +
    `engine\\`, её требует [Files]; собирает Build-Installer.ps1). Молчаливый
    пропуск был бы ложным зелёным: «проверок нет» выглядело бы как «всё хорошо».
    """
    iscc = next((p for p in (
        pathlib.Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
        pathlib.Path(os.environ.get("ProgramFiles(x86)", "")) / "Inno Setup 6" / "ISCC.exe",
        pathlib.Path(os.environ.get("ProgramFiles", "")) / "Inno Setup 6" / "ISCC.exe",
    ) if p.exists()), None)
    if iscc is None:
        res.ok("ISCC.exe не установлен — компиляция пропущена", True, "")
        return
    if not ((PROG / "DentPilot.exe").exists()
            and (PROG / "engine" / "DentPilot-Engine.exe").exists()):
        res.ok("dist\\DentPilot (оболочка + engine\\) не собрана — компиляция пропущена", True, "")
        return
    out = tempfile.mkdtemp(prefix="dp_iss_")
    try:
        p = subprocess.run([str(iscc), "/DAppVersion=0.0.0", f"/O{out}", str(ISS)],
                           capture_output=True, text=True, timeout=300)
        res.ok("скрипт установщика компилируется", p.returncode == 0,
               (p.stdout or "")[-400:] + (p.stderr or "")[-200:])
    finally:
        _rmtree_settled(out)
