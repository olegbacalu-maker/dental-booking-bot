"""Сторож перезапуска — логика без окна (11.10.2026).

До 11.10 перезапуск после обновления и после «применить настройки» делал
bat-файл, который планировщик Windows запускал в сеансе пользователя: чёрное
окно cmd висело на экране всё время тихой установки, и регистратура хотела
его закрыть (слово Олега: «появляется чёрное окошко и пару секунд ничего не
происходит»). Теперь планировщик запускает САМУ программу в режиме `--watch`:
окна консоли у неё нет (сборка console=False), а вместо пустоты она показывает
заставку «Se instalează actualizarea…» (`desktop._watch_mode`).

Здесь — то, что можно проверить прогоном без окна: разбор аргументов, чтение
итога установщика и ожидание. Окно, запуск программы и планировщик — в
`desktop.py` и `app/update.py`.

⚠️ Предзагрузочный слой: модуль зовёт лаунчер ДО сборки приложения, импортов
проекта здесь нет (держит `test_structure`, список `_PRELOAD`).

⛔ Сторож — ДРУГОЙ файл, чем программа в `Program Files`. Установщик закрывает
всё, что держит заменяемые файлы (`/CLOSEAPPLICATIONS`), а запущенный exe
держит собственный образ: сторож из `Program Files\\DentPilot.exe` установщик
убил бы вместе с программой, и перезапускать её стало бы некому. Поэтому
`update._watch_command` запускает КОПИЮ exe из папки клиники (bat этой
ловушки не знал: cmd ничего из папки программы не держит).

Итог установщика в файле (`privileged.RESULT_NAME`): «started» пишет
операция за UAC, когда установщик уже запущен (с 2.0.2; до того — перед
запуском, и у оболочки Tauri он не запускался вовсе), «ok»/«fail …» — сам установщик
(`/RESULT=`), «cancelled» — программа, когда отказалась от обновления сама.
Слова те же, что узнавал bat (`"%r%"=="ok"` и т.д., канарейка 03.10: «ok» без
перевода строки — тоже «ok»).

⭐ С оболочкой Tauri (Т10, 18.10) сторож — НЕ этот модуль: в движке нет
pywebview, поэтому сторожем идёт копия оболочки `DentPilot.exe --watch …`
(`shell/src/watch.rs`) с теми же аргументами (`argv_for`), словами итога и
текстами заставки. ⛔ Тексты ниже — в константах, и `test_restart` сверяет их
с `watch.rs`: сторожей два до снятия окна pywebview (Т11), и разошедшийся
текст не краснеет ничем другим. В режиме оболочки `pid` — оболочка (родитель
движка): она гасит движок сама и выходит последней.
"""
from __future__ import annotations

import os
import pathlib
import time
from dataclasses import dataclass, field

FLAG = "--watch"
# Сколько ждать итога установщика: задача планировщика живёт не больше 10 минут
WAIT_S = 9 * 60
# После «ok»/«fail» — пока ПРЕЖНИЙ процесс не выйдет: иначе новый лаунчер
# застанет мьютекс занятым и уйдёт «фокусировать первое окно», которого нет
EXIT_WAIT_S = 60.0
NO_RESULT = "-"

# Слова заставки сторожа — те же в `shell/src/watch.rs` (сверяет test_restart)
TEXT_INSTALL = "Se instalează actualizarea…"
TEXT_RESTART = "Se repornește DentPilot…"
TEXT_CLOSING = "Se închide versiunea curentă…"
TEXT_NEW = "Se pornește versiunea nouă…"
TEXT_ROLLBACK = "Actualizarea nu s-a instalat — se pornește versiunea curentă…"


@dataclass
class Plan:
    """Что сторожу делать. Все пути АБСОЛЮТНЫЕ: задача планировщика стартует
    в system32, окружения лаунчера у неё нет."""
    proof: pathlib.Path          # метка «сторож пошёл» — её ждёт `update._spawn_watch`
    task: str                    # имя задачи планировщика — снять за собой
    result: pathlib.Path | None  # итог установщика; None — простой перезапуск
    pid: int                     # прежний процесс, чей выход ждём (0 — не ждать)
    label: str                   # что написать на заставке: «1.40.2 › 1.40.3»
    primary: str                 # цвет темы клиники (#RRGGBB) — фон заставки
    profile: pathlib.Path        # свой профиль WebView2: профиль программы занят ею же
    launch: list[str] = field(default_factory=list)   # команда запуска программы


def argv_for(plan: Plan) -> list[str]:
    """Аргументы `--watch …` из плана; `parse` — обратная операция."""
    return [FLAG, str(plan.proof), plan.task, str(plan.result) if plan.result else NO_RESULT,
            str(plan.pid), plan.label, plan.primary, str(plan.profile), *plan.launch]


def parse(argv: list[str]) -> Plan | None:
    """`None` — обычный запуск. ⛔ Своя метка, а не позиционный аргумент:
    путь из «Открыть с помощью» не должен попадать в эту ветку."""
    if not argv or argv[0] != FLAG:
        return None
    if len(argv) < 9:
        raise ValueError(f"{FLAG}: нужно 8 аргументов и команда запуска, получено {len(argv) - 1}")
    _, proof, task, result, pid, label, primary, profile, *launch = argv
    try:
        pid_n = int(pid)
    except ValueError as e:
        raise ValueError(f"{FLAG}: pid не число: {pid!r}") from e
    return Plan(proof=pathlib.Path(proof), task=task,
                result=None if result == NO_RESULT else pathlib.Path(result),
                pid=pid_n, label=label, primary=primary, profile=pathlib.Path(profile),
                launch=list(launch))


def decide(text: str | None) -> str:
    """Что говорит файл итога: «start» — запускать программу (ok ИЛИ fail:
    после отката на диске снова старая версия), «done» — программа жива сама
    («cancelled»), «wait» — ещё нет («started», пусто, нет файла, чужое слово).
    ⚠️ Без перевода строки и с ним — одинаково (канарейка 03.10)."""
    if text is None:
        return "wait"
    t = text.strip()
    if t == "cancelled":
        return "done"
    if t == "ok" or t.startswith("fail"):
        return "start"
    return "wait"


def read_result(result: pathlib.Path | None) -> str | None:
    if result is None:
        return "ok"                      # простой перезапуск: ждать нечего
    try:
        return result.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def pid_alive(pid: int) -> bool:
    """Жив ли прежний процесс. Не Windows / нет pid — считаем, что вышел."""
    if pid <= 0 or os.name != "nt":
        return False
    try:
        import ctypes
        SYNCHRONIZE = 0x00100000
        h = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if not h:
            return False
        try:
            # WAIT_TIMEOUT (258) — ещё работает; WAIT_OBJECT_0 (0) — вышел
            return ctypes.windll.kernel32.WaitForSingleObject(h, 0) == 258
        finally:
            ctypes.windll.kernel32.CloseHandle(h)
    except Exception:  # noqa: BLE001 — без kernel32 ждать нечего
        return False


def wait_for(plan: Plan, stage=None, step: float = 0.5, timeout: float = WAIT_S,
             exit_wait: float = EXIT_WAIT_S, clock=time.monotonic, sleep=time.sleep) -> str:
    """Дождаться итога и выхода прежнего процесса. Возвращает «start» или «done».
    `stage(text, pct, upto)` — заставке; ⚠️ не дождались за `timeout` — «start»:
    лучше программа, чем пустой экран (так же вёл себя bat)."""
    say = stage or (lambda *a: None)
    t0 = clock()
    verdict = "start"
    while clock() - t0 < timeout:
        v = decide(read_result(plan.result))
        if v != "wait":
            verdict = v
            break
        sleep(step)
    if verdict == "done":
        return "done"
    t1 = clock()
    while plan.pid and pid_alive(plan.pid) and clock() - t1 < exit_wait:
        say(TEXT_CLOSING, 80, 92)
        sleep(step)
    return "start"


def outcome_text(result_text: str | None) -> str:
    """Слово для заставки по итогу: установилось — «se pornește versiunea
    nouă», откатилось — честно сказать, что осталась прежняя."""
    t = (result_text or "").strip()
    if t.startswith("fail"):
        return TEXT_ROLLBACK
    return TEXT_NEW
