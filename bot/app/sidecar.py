"""Движок Tauri: разговор лаунчера с оболочкой `DentPilot.exe` (Т5, 18.10.2026).

Контракт — `docs/dentpilot-2/tauri-contract.md` § 2, здесь только его
исполнение. Предзагрузочный слой: зовёт `desktop.py` до сборки приложения,
поэтому импортов проекта нет и быть не может.

Оболочка запускает движок с `DENTART_SHELL=tauri` и трубами на stdin/stdout:
- движок → оболочка: строки `DP1 <json>` (`hello`, `stage`, `ready`, `busy`,
  `fatal`, `quit`) — и больше в эту трубу НИЧЕГО;
- оболочка → движок: строка `{"v":1,"cmd":"stop"}` или закрытый stdin —
  честно остановиться (это же и «оболочка исчезла»).

⛔ Трубы забираются у процесса целиком (`take`): на месте stdin/stdout остаётся
пустое устройство, и ни `print` библиотеки, ни дочерний PowerShell туда уже не
попадут. Причины две, и обе молчаливые:
- оболочка вправе перестать читать stdout после `ready` — тогда первый же
  длинный `print` заполнил бы буфер трубы, и движок встал бы на записи
  навсегда, с живым процессом и без строки в логе;
- дочерний процесс, получивший нашу трубу stdin по наследству (так делает
  `subprocess` с `capture_output` и без `stdin=`), мог бы прочесть строку
  `stop` вместо нас.
"""
from __future__ import annotations

import json
import os
import sys
import threading

ENV = "DENTART_SHELL"
MODE = "tauri"
TOKEN_ENV = "DENTART_SHELL_TOKEN"       # § 4: заголовок /shell/notices
# Имя собранного движка (§ 1). По нему лаунчер узнаёт раскладку «оболочка +
# engine\» и считает корень программы папкой оболочки, а не своей.
ENGINE_EXE = "DentPilot-Engine.exe"

V = 1
PREFIX = "DP1 "
EXIT_STOP, EXIT_FATAL, EXIT_BUSY = 0, 2, 3
QUIT_REASONS = ("update", "restart")

# Труба этого процесса к оболочке; None — оболочки нет (окно pywebview,
# браузерный режим, сервер). Ставит `take`, читают функции ниже.
_LINK: "Link | None" = None

# STD_INPUT/OUTPUT/ERROR_HANDLE — (DWORD)-10/-11/-12
_STD = {0: 0xFFFFFFF6, 1: 0xFFFFFFF5, 2: 0xFFFFFFF4}


def active(environ=None) -> bool:
    """Запущен ли процесс оболочкой. ⚠️ Решает окружение ПРОЦЕССА, спрошенное
    до слияния `dental.env`: строка в файле клиники режима не включает."""
    env = os.environ if environ is None else environ
    return env.get(ENV, "").strip().lower() == MODE


class Link:
    """Труба к оболочке. Падение записи (оболочка исчезла) движок не роняет:
    остановку принесёт закрытый stdin."""

    def __init__(self, out, inp=None) -> None:
        self._out = out
        self._in = inp
        self._lock = threading.Lock()
        # путь лога для `fatal`: лаунчер ставит, когда папка данных известна
        self.log = ""

    def send(self, event: str, **fields) -> bool:
        # ASCII: диакритика уезжает экранами \\uXXXX — строке всё равно, в
        # какой кодировке её прочтут на той стороне
        line = PREFIX + json.dumps({"v": V, "event": event, **fields},
                                   separators=(",", ":"))
        with self._lock:
            try:
                self._out.write(line + "\n")
                self._out.flush()
                return True
            except (OSError, ValueError):
                return False

    def listen(self, on_stop) -> threading.Thread | None:
        """Читать stdin в фоне: `stop` или конец трубы — `on_stop(причина)`
        («stop» / «eof»), один раз. Прочие строки пропускаются: новое слово
        оболочки, которого этот движок не знает, его не роняет."""
        if self._in is None:
            return None

        def run() -> None:
            why = "eof"
            try:
                for line in self._in:
                    if command(line) == "stop":
                        why = "stop"
                        break
            except (OSError, ValueError):
                pass                         # труба порвана = оболочки нет
            on_stop(why)

        t = threading.Thread(target=run, name="dp-shell-stdin", daemon=True)
        t.start()
        return t


def command(line: str) -> str:
    """Слово оболочки из строки stdin; не команда — пустая строка.
    ⚠️ `v` не сверяется намеренно: остановка безопасна при любой версии, а
    отказ на ней оставил бы движок до снятия задания через 10 с."""
    try:
        msg = json.loads(line)
    except ValueError:
        return ""
    cmd = msg.get("cmd") if isinstance(msg, dict) else None
    return cmd if isinstance(cmd, str) else ""


def take() -> Link | None:
    """Забрать у процесса настоящие stdin и stdout — для оболочки, — а на их
    место положить пустое устройство (почему — в шапке модуля). Ручки трубы
    остаются только у нас: `os.dup` отдаёт ненаследуемый дескриптор.
    Нет stdout (нечем говорить) — None, и лаунчер пойдёт без протокола."""
    global _LINK
    out = _reopen(1, "w")
    if out is None:
        return None
    inp = _reopen(0, "r")
    _blank(0, os.O_RDONLY)
    _blank(1, os.O_WRONLY)
    sys.stdin = open(os.devnull, encoding="utf-8")            # noqa: SIM115
    sys.stdout = open(os.devnull, "w", encoding="utf-8")       # noqa: SIM115
    _LINK = Link(out, inp)
    return _LINK


def stderr_to(path) -> None:
    """stderr процесса — в файл (`dentpilot.err.log`), и на уровне Python, и
    дескриптором 2: трейсбек нативного кода и дочерний процесс без `stderr=`
    тоже уходят туда, а не в трубу оболочки, которую никто не обязан читать."""
    f = open(path, "a", encoding="utf-8")                      # noqa: SIM115
    try:
        os.dup2(f.fileno(), 2)
        _set_std(2)
    except OSError:
        pass
    sys.stderr = f


def request_quit(reason: str) -> bool:
    """Попросить оболочку закрыться СЕЙЧАС, без вопроса (§ 2, `quit`): сейчас
    пойдёт установщик (`update`) или сторож перезапуска (`restart`). Зовёт код
    обновления (Т10) прямо перед запуском. Оболочки нет — False, и звавший
    поступает как прежде."""
    if reason not in QUIT_REASONS:
        raise ValueError(f"quit: {reason!r}")
    link = _LINK
    return link.send("quit", reason=reason) if link is not None else False


def linked() -> bool:
    """Говорит ли этот процесс с оболочкой. ⛔ Спрашивать ЭТО, а не окружение:
    `DENTART_SHELL` в окружении может оказаться и без оболочки."""
    return _LINK is not None


def _reopen(fd: int, mode: str):
    try:
        dup = os.dup(fd)
    except OSError:
        return None                          # дескриптора нет: сборка без консоли
    try:
        if mode == "w":
            return os.fdopen(dup, "w", encoding="utf-8", newline="\n")
        return os.fdopen(dup, "r", encoding="utf-8", errors="replace")
    except OSError:
        os.close(dup)
        return None


def _blank(fd: int, flags: int) -> None:
    try:
        nul = os.open(os.devnull, flags)
    except OSError:
        return
    try:
        os.dup2(nul, fd)
        _set_std(fd)
    except OSError:
        pass
    finally:
        os.close(nul)


def _set_std(fd: int) -> None:
    """Стандартная ручка Windows — на дескриптор `fd`. `subprocess` берёт
    наследуемые ручки ребёнку ОТСЮДА (GetStdHandle), а не из дескрипторов CRT."""
    if os.name != "nt":
        return
    try:
        import ctypes
        import msvcrt
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.SetStdHandle.argtypes = [wintypes.DWORD, wintypes.HANDLE]
        k32.SetStdHandle(_STD[fd], msvcrt.get_osfhandle(fd))
    except (OSError, AttributeError, ImportError):
        pass
