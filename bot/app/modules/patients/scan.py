"""Сканер (01.10): «Scanează» во вкладке «Documente» — подписанный бланк
попадает в фишу PDF-ом с нужной категорией, без «сохранить в папку → найти →
загрузить». Слово Олега 28.09: «с телефона такие документы не очень серьёзно
снимать» — нужен скан, не фото.

WIA (Windows Image Acquisition) через PowerShell и COM — так же, как
`settings/netcheck` спрашивает брандмауэр: скрипт-константа, всё переменное
окружением. ⛔ Без диалогов: `WIA.CommonDialog` показал бы окно на СЕРВЕРЕ,
которого с планшета не видно, и запрос висел бы до таймаута. Берётся первый
сканер, 200 dpi, оттенки серого, лист с планшета; страницы копятся в сессии
в памяти процесса (по пациенту), «Salvează» склеивает их в PDF (Pillow — он
уже в сборке ради миниатюр).

⚠️ Сканер — на ПК с программой. Второе рабочее место (браузер по сети)
нажмёт кнопку, а лист должен лежать в сканере сервера: МФУ стоит у стойки,
где и программа, — это по замыслу, не ограничение.
⚠️ Живого сканера у разработчика нет (28.09 WIA видит 0 устройств), поэтому
подмена `DENTART_SCAN_FAKE=<картинка>` отдаёт файл вместо сканера — на ней
живут проверки; настоящий драйвер — на МФУ клиники, при подключении.
"""
from __future__ import annotations

import base64
import io
import os
import subprocess
import tempfile
import threading
import time

# Тип устройства WIA: 1 = сканер (ScannerDeviceType); камера 2, видео 3.
# Свойства листа (WIA_IPS_*): 6146 намерение (2 = оттенки серого),
# 6147/6148 — dpi по осям. BMP — формат, который отдаёт любой драйвер;
# в PDF лист всё равно пересобирается здесь.
_PS_LIST = r"""
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$ErrorActionPreference = 'Stop'
$dm = New-Object -ComObject WIA.DeviceManager
$out = @()
foreach ($d in $dm.DeviceInfos) { if ($d.Type -eq 1) { $out += [string]$d.Properties.Item('Name').Value } }
ConvertTo-Json -Compress @($out)
"""

_PS_SCAN = r"""
$ErrorActionPreference = 'Stop'
$dm = New-Object -ComObject WIA.DeviceManager
$info = $null
foreach ($d in $dm.DeviceInfos) { if ($d.Type -eq 1) { $info = $d; break } }
if (-not $info) { exit 3 }
$dev = $info.Connect()
$item = $dev.Items.Item(1)
foreach ($p in $item.Properties) {
  try {
    switch ([int]$p.PropertyID) {
      6146 { $p.Value = 2 }
      6147 { $p.Value = [int]$env:DP_SCAN_DPI }
      6148 { $p.Value = [int]$env:DP_SCAN_DPI }
    }
  } catch {}
}
$img = $item.Transfer('{B96B3CAB-0728-11D3-9D7B-0000F81EF32E}')
$img.SaveFile($env:DP_SCAN_OUT)
"""

DPI = 200
NO_SCANNER_EXIT = 3
LIST_TIMEOUT = 20.0
SCAN_TIMEOUT = 180.0
STATUS_TTL = 60.0        # список устройств — секунда-две PowerShell, не чаще
MAX_PAGES = 30
PREVIEW_PX = 240


class ScanError(Exception):
    """`code` — код плашки: scan_none (сканера нет) / scan_err (не вышло)."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _fake() -> str:
    return os.environ.get("DENTART_SCAN_FAKE", "")


def _ps(script: str, env: dict, timeout: float) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive",
         "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True, timeout=timeout, env=env,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


_status: dict = {"at": 0.0, "ok": False, "name": ""}
_status_lock = threading.Lock()


def status(force: bool = False) -> dict:
    """{ok, name}: есть ли сканер. Кэш на STATUS_TTL — страница спрашивает
    при каждом открытии вкладки. Звать из потока: PowerShell холодный."""
    if _fake():
        return {"ok": os.path.isfile(_fake()), "name": "Scaner de test"}
    with _status_lock:
        if not force and time.monotonic() - _status["at"] < STATUS_TTL:
            return {"ok": _status["ok"], "name": _status["name"]}
    ok, name = False, ""
    if os.name == "nt":
        try:
            r = _ps(_PS_LIST, dict(os.environ), LIST_TIMEOUT)
            if r.returncode == 0:
                import json
                names = json.loads(r.stdout.decode("utf-8", "replace").strip() or "[]")
                if isinstance(names, str):
                    names = [names]
                names = [str(n) for n in names if n]
                ok, name = bool(names), (names[0] if names else "")
        except (OSError, subprocess.TimeoutExpired, ValueError):
            ok, name = False, ""
    with _status_lock:
        _status.update(at=time.monotonic(), ok=ok, name=name)
    return {"ok": ok, "name": name}


def acquire() -> bytes:
    """Один лист со сканера — байты картинки (BMP у драйвера, что угодно у
    подмены). Блокирует на время сканирования: звать из потока."""
    if _fake():
        try:
            with open(_fake(), "rb") as f:
                return f.read()
        except OSError as e:
            raise ScanError("scan_err") from e
    if os.name != "nt":
        raise ScanError("scan_none")
    fd, out = tempfile.mkstemp(prefix="dp_scan_", suffix=".bmp")
    os.close(fd)
    os.unlink(out)                       # WIA отказывается писать поверх файла
    env = dict(os.environ, DP_SCAN_OUT=out, DP_SCAN_DPI=str(DPI))
    try:
        r = _ps(_PS_SCAN, env, SCAN_TIMEOUT)
    except subprocess.TimeoutExpired as e:
        raise ScanError("scan_err") from e
    except OSError as e:
        raise ScanError("scan_err") from e
    if r.returncode == NO_SCANNER_EXIT:
        with _status_lock:
            _status.update(at=time.monotonic(), ok=False, name="")
        raise ScanError("scan_none")
    try:
        if r.returncode != 0 or not os.path.isfile(out):
            raise ScanError("scan_err")
        with open(out, "rb") as f:
            return f.read()
    finally:
        try:
            os.unlink(out)
        except OSError:
            pass


# ---------- сессия сканирования: страницы одного документа ----------

_sessions: dict[int, list[bytes]] = {}
_sess_lock = threading.Lock()


def _image(data: bytes):
    from PIL import Image
    im = Image.open(io.BytesIO(data))
    im.load()
    return im


def preview(data: bytes) -> str:
    """Маленький PNG строкой data: — карточке на экране, не файлом."""
    im = _image(data).convert("L")
    im.thumbnail((PREVIEW_PX, PREVIEW_PX))
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def add_page(pid: int, data: bytes) -> list[str]:
    """Положить лист в сессию пациента; возвращает превью всех страниц.
    Битая картинка — scan_err, лист не кладётся."""
    try:
        pv = preview(data)
    except Exception as e:                   # noqa: BLE001 — не картинка / экзотика
        raise ScanError("scan_err") from e
    with _sess_lock:
        pages = _sessions.setdefault(pid, [])
        if len(pages) >= MAX_PAGES:
            raise ScanError("scan_err")
        pages.append(data)
        pages_now = list(pages)
    return [preview(p) for p in pages_now]


def pages(pid: int) -> int:
    with _sess_lock:
        return len(_sessions.get(pid, ()))


def cancel(pid: int) -> None:
    with _sess_lock:
        _sessions.pop(pid, None)


def finish(pid: int) -> bytes | None:
    """Склеить страницы сессии в PDF и закрыть её. None — сессии нет."""
    with _sess_lock:
        pages_now = _sessions.pop(pid, None)
    if not pages_now:
        return None
    return to_pdf(pages_now)


def to_pdf(images: list[bytes]) -> bytes:
    """Многостраничный PDF: оттенки серого, 200 dpi — читается как оригинал,
    ~100–300 КБ на лист. Pillow пишет страницы JPEG-ом внутри PDF."""
    ims = [_image(d).convert("L") for d in images]
    buf = io.BytesIO()
    first, rest = ims[0], ims[1:]
    first.save(buf, "PDF", save_all=bool(rest), append_images=rest,
               resolution=float(DPI), quality=80)
    return buf.getvalue()
