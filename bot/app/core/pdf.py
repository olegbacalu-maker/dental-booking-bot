"""HTML-лист → PDF печатью headless Edge (09.11.2026, подпись на экране).

Почему Edge, а не своя вёрстка PDF (разведка 09.11, сессия sign-pdf):
- лист один — тот же HTML, что идёт на принтер; PDF-библиотека потребовала
  бы ВТОРОЙ вёрстки каждого бланка, и она разошлась бы с печатью молча;
- Edge есть на любой Windows 10/11, новых зависимостей в exe нет (печать
  командной строкой `--print-to-pdf`, без CDP и websocket);
- WebView2 `PrintToPdf` через оболочку Tauri — правка оболочки и канал
  «движок просит окно», которого нет, и только при открытом окне.
Замер: ~1,1 с на лист (одноразовый профиль, file://), 56–82 КБ.

⛔ Лист с медданными и одноразовый профиль Edge живут в ПАПКЕ ДАННЫХ клиники
(`<db_dir>\\tmp\\pdf\\<случайное>`), а не в %TEMP%: у клиники с BitLocker или
SQLCipher %TEMP% может лежать вне защищённого места, а анкета — медзапись.
Папка снимается в `finally` при любом исходе (удача, падение Edge, таймаут);
хвосты прошлых падений (процесс погас посреди печати) подчищает следующий
вызов — всё старше `_STALE_S`.

Edge не ходит в движок: лист самодостаточный (картинки — `data:`), открыт как
file://, ни порта, ни куки. Ребёнок движка живёт в задании оболочки Tauri и
гаснет вместе с программой — для печати длиной в секунду это и нужно.

Серверный запуск (демо в Docker, не Windows) Edge не имеет: `available()` —
нет, и клиент прячет «Semnează» (`card.forms_view` › `sign`).
"""
from __future__ import annotations

import os
import pathlib
import secrets
import shutil
import subprocess
import sys
import time

from . import storage

# сколько ждать Edge. Лист печатается за ~1 с; 20 с — запас на холодный диск
# и антивирус, после — честный отказ, а не зависшее окно подписи
TIMEOUT_S = 20
# папка печати старше этого — хвост упавшего прошлого вызова
_STALE_S = 10 * 60
# потолок PDF: лист — десятки КБ; больше 10 МБ — не лист
_PDF_MAX = 10 * 1024 * 1024


class PdfError(Exception):
    """`code` — ключ MSG_BANNER: `pdf_none` (Edge нет), `pdf_err` (не вышло)."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def edge_path() -> str | None:
    """msedge.exe этой машины или None. `$DENTART_EDGE` перевешивает поиск
    (Edge в нестандартном месте; прогон проверяет ветку «Edge нет» путём в
    никуда) — названный путь не найден = Edge нет, без угадывания дальше."""
    forced = os.environ.get("DENTART_EDGE", "").strip().strip("\"'")
    if forced:
        return forced if os.path.isfile(forced) else None
    if sys.platform != "win32":
        return None
    cands = []
    for var in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
        base = os.environ.get(var)
        if base:
            cands.append(os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"))
    try:
        import winreg
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows\CurrentVersion"
                                          r"\App Paths\msedge.exe") as k:
                    cands.append(winreg.QueryValue(k, None))
            except OSError:
                pass
    except ImportError:                                  # pragma: no cover
        pass
    return next((c for c in cands if c and os.path.isfile(c)), None)


def available() -> bool:
    return edge_path() is not None


def _room() -> pathlib.Path:
    """Корень печати в папке данных (там же, где файлы пациентов)."""
    return (storage._data_dir() or pathlib.Path("data")) / "tmp" / "pdf"


def sweep(now: float | None = None) -> int:
    """Снять хвосты прошлых падений; живые соседи (моложе `_STALE_S`) целы."""
    root, n = _room(), 0
    now = time.time() if now is None else now
    try:
        entries = list(root.iterdir())
    except OSError:
        return 0
    for d in entries:
        try:
            if now - d.stat().st_mtime > _STALE_S:
                shutil.rmtree(d, ignore_errors=True)
                n += 1
        except OSError:
            pass
    return n


def leftovers() -> list[str]:
    """Что лежит в папке печати сейчас (прогон: после подписи — пусто)."""
    try:
        return sorted(p.name for p in _room().iterdir())
    except OSError:
        return []


def html_to_pdf(page: str) -> bytes:
    """Самодостаточный HTML → байты PDF. Блокирует ~1 с: звать в потоке."""
    edge = edge_path()
    if not edge:
        raise PdfError("pdf_none")
    sweep()
    work = _room() / secrets.token_hex(8)
    try:
        work.mkdir(parents=True)
        src, out = work / "sheet.html", work / "sheet.pdf"
        src.write_text(page, encoding="utf-8")
        args = [edge, "--headless", "--disable-gpu", "--no-first-run",
                "--no-default-browser-check", "--disable-extensions",
                "--disable-sync", "--no-pdf-header-footer",
                f"--user-data-dir={work / 'profile'}",
                f"--print-to-pdf={out}", src.as_uri()]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            subprocess.run(args, capture_output=True, timeout=TIMEOUT_S,
                           creationflags=flags, check=False)
        except (OSError, subprocess.TimeoutExpired):
            raise PdfError("pdf_err") from None
        try:
            data = out.read_bytes()
        except OSError:
            raise PdfError("pdf_err") from None
        if not data.startswith(b"%PDF-") or len(data) > _PDF_MAX:
            raise PdfError("pdf_err")
        return data
    finally:
        _drop(work)


def _drop(work: pathlib.Path) -> None:
    """Снять папку печати. Edge, убитый таймаутом, может ещё держать файлы
    профиля долю секунды — несколько попыток; не вышло — снимет `sweep`."""
    for _ in range(10):
        shutil.rmtree(work, ignore_errors=True)
        if not work.exists():
            return
        time.sleep(0.2)
