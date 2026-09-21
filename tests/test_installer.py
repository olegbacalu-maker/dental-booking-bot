# -*- coding: utf-8 -*-
"""P3-min ступень 2: контракт установщика как ИСХОДНИКА.

⛔ Граница ступени: проверяется текст `DentPilot.iss` и факт его
компилируемости. Поведение готового `installer.exe` — установка, права,
переезд данных — это ступени 3 и 4, и здесь их нет намеренно.

⚠️ Установщик до 20.09 не был покрыт ничем вообще: правка в нём доезжала до
клиники, не встретив ни одной проверки.
"""
from __future__ import annotations

import os
import pathlib
import re
import shutil
import subprocess
import tempfile

from harness import BOT, Result  # noqa: E402

ISS = BOT.parent / "installer" / "DentPilot.iss"


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
    grant = next((ln for ln in s.splitlines() if "/grant" in ln), "")
    res.ok("у icacls нет /C", "/C" not in grant,
           "/C велит продолжать после ошибок — код возврата перестаёт значить")
    res.ok("результат icacls проверяется", "(RC = 0)" in s,
           "код возврата не читается — тихо неверные права")


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


def suite_compiles(res: Result) -> None:
    """Компилируется ли скрипт. ⚠️ Пропуск печатается ВСЛУХ.

    Нужны `ISCC.exe` и собранный `dist\\DentPilot.exe` (его требует [Files]).
    Молчаливый пропуск был бы ложным зелёным: «проверок нет» выглядело бы как
    «всё хорошо».
    """
    iscc = next((p for p in (
        pathlib.Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
        pathlib.Path(os.environ.get("ProgramFiles(x86)", "")) / "Inno Setup 6" / "ISCC.exe",
        pathlib.Path(os.environ.get("ProgramFiles", "")) / "Inno Setup 6" / "ISCC.exe",
    ) if p.exists()), None)
    if iscc is None:
        res.ok("ISCC.exe не установлен — компиляция пропущена", True, "")
        return
    if not (BOT.parent / "dist" / "DentPilot.exe").exists():
        res.ok("dist\\DentPilot.exe не собран — компиляция пропущена", True, "")
        return
    out = tempfile.mkdtemp(prefix="dp_iss_")
    try:
        p = subprocess.run([str(iscc), "/DAppVersion=0.0.0", f"/O{out}", str(ISS)],
                           capture_output=True, text=True, timeout=300)
        res.ok("скрипт установщика компилируется", p.returncode == 0,
               (p.stdout or "")[-400:] + (p.stderr or "")[-200:])
    finally:
        shutil.rmtree(out, ignore_errors=True)
