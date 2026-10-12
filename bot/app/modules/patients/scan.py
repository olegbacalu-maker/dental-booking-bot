"""Сканер (01.10): «Scanează» во вкладке «Documente» — подписанный бланк
попадает в фишу PDF-ом с нужной категорией, без «сохранить в папку → найти →
загрузить». Слово Олега 28.09: «с телефона такие документы не очень серьёзно
снимать» — нужен скан, не фото.

WIA (Windows Image Acquisition) через PowerShell и COM — так же, как
`settings/netcheck` спрашивает брандмауэр: скрипт-константа, всё переменное
окружением. ⛔ Без диалогов: `WIA.CommonDialog` показал бы окно на СЕРВЕРЕ,
которого с планшета не видно, и запрос висел бы до таймаута. Берётся первый
сканер, оттенки серого, лист с планшета, разрешение — наименьшее из тех, что
драйвер принимает, но не ниже 200 dpi (`_PS_PICK_DPI`); страницы копятся в
сессии в памяти процесса (по пациенту), «Salvează» склеивает их в PDF (Pillow
— он уже в сборке ради миниатюр).

⚠️ Размер листа в PDF = пиксели ÷ разрешение, с которым лист СНЯЛИ, а не
которое просили (12.10.2026, первый живой скан у Олега): Canon TS3400 через
WIA принимает только 150/300/600, прежний скрипт ставил 200 молча мимо, лист
приходил в 150 dpi, а PDF считал его двухсотым — страница 16×22 см вместо
21,6×29,7, при печати «в натуральную величину» на четверть меньше листа.
Скрипт теперь читает принятое разрешение обратно и отдаёт строкой `DPI x y`.

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
import re
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

# Выбор разрешения: свойство 6147 описывает допустимое СПИСКОМ (SubType 2) или
# ДИАПАЗОНОМ (SubType 1), а значение вне них драйвер отвергает. Берётся
# наименьшее допустимое не ниже просимого (Canon TS3400: 150/300/600 → 300),
# а если выше просимого ничего нет — наибольшее. ⚠️ Отдельной константой, а
# не внутри `_PS_SCAN`: её же исполняет тест на поддельных свойствах —
# настоящего WIA в прогоне нет.
_PS_PICK_DPI = r"""
function Pick-Dpi($p, [int]$want) {
  try {
    if ($p.SubType -eq 2) {
      $vals = @($p.SubTypeValues | ForEach-Object { [int]$_ } | Sort-Object)
      $up = @($vals | Where-Object { $_ -ge $want })
      if ($up.Count -gt 0) { return $up[0] }
      if ($vals.Count -gt 0) { return $vals[-1] }
    } elseif ($p.SubType -eq 1) {
      $min = [int]$p.SubTypeMin
      $max = [int]$p.SubTypeMax
      $step = [int]$p.SubTypeStep
      $v = [Math]::Max($want, $min)
      if ($step -gt 0) { $v = $min + [int][Math]::Ceiling(($v - $min) / $step) * $step }
      return [int][Math]::Min($v, $max)
    }
  } catch {}
  return $want
}
"""

# После установки свойства читаются ОБРАТНО: в PDF идёт то, что драйвер
# принял, — строкой `DPI x y` в конце вывода (`_parse_dpi`).
_PS_SCAN = r"""
$ErrorActionPreference = 'Stop'
""" + _PS_PICK_DPI + r"""
$dm = New-Object -ComObject WIA.DeviceManager
$info = $null
foreach ($d in $dm.DeviceInfos) { if ($d.Type -eq 1) { $info = $d; break } }
if (-not $info) { exit 3 }
$dev = $info.Connect()
$item = $dev.Items.Item(1)
$want = [int]$env:DP_SCAN_DPI
$dpi = $want
foreach ($p in $item.Properties) { if ([int]$p.PropertyID -eq 6147) { $dpi = Pick-Dpi $p $want } }
foreach ($p in $item.Properties) {
  try {
    switch ([int]$p.PropertyID) {
      6146 { $p.Value = 2 }
      6147 { $p.Value = $dpi }
      6148 { $p.Value = $dpi }
    }
  } catch {}
}
$x = 0
$y = 0
foreach ($p in $item.Properties) {
  switch ([int]$p.PropertyID) {
    6147 { $x = [int]$p.Value }
    6148 { $y = [int]$p.Value }
  }
}
$img = $item.Transfer('{B96B3CAB-0728-11D3-9D7B-0000F81EF32E}')
$img.SaveFile($env:DP_SCAN_OUT)
Write-Output "DPI $x $y"
"""

DPI = 200                # не ниже этого; выше — если драйвер иначе не умеет
MIN_SANE_DPI = 50        # меньше — не разрешение, а пустое поле заголовка
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


Dpi = tuple[float, float]


def _parse_dpi(out: bytes | None) -> Dpi | None:
    """`DPI x y` из вывода `_PS_SCAN` — разрешение, которое драйвер ПРИНЯЛ.
    Строки нет или там нули — None: тогда разрешение скажет сама картинка
    (`_dpi_of`)."""
    m = re.search(rb"DPI\s+(\d+)\s+(\d+)", out or b"")
    if not m:
        return None
    x, y = int(m.group(1)), int(m.group(2))
    if x < MIN_SANE_DPI or y < MIN_SANE_DPI:
        return None
    return float(x), float(y)


def acquire() -> tuple[bytes, Dpi | None]:
    """Один лист со сканера: байты картинки (BMP у драйвера, что угодно у
    подмены) и разрешение, с которым драйвер его снял (None — неизвестно).
    Блокирует на время сканирования: звать из потока."""
    if _fake():
        try:
            with open(_fake(), "rb") as f:
                return f.read(), None
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
            return f.read(), _parse_dpi(r.stdout)
    finally:
        try:
            os.unlink(out)
        except OSError:
            pass


# ---------- сессия сканирования: страницы одного документа ----------

# Страница сессии: серый PNG (без потерь, разрешение внутри), её разрешение и
# готовое превью. ⚠️ Не сырой BMP драйвера: при 300 dpi лист A4 — 9–27 МБ, и
# тридцать таких висели бы в памяти программы до «Salvează»; серый PNG того же
# листа в разы меньше, а качество то же. Превью считается один раз, а не на
# каждый новый лист заново.
_sessions: dict[int, list[tuple[bytes, Dpi, str]]] = {}
_sess_lock = threading.Lock()


def _image(data: bytes):
    from PIL import Image
    im = Image.open(io.BytesIO(data))
    im.load()
    return im


def _dpi_of(im, given: Dpi | None) -> Dpi:
    """Разрешение листа: что сказал драйвер → что записано в самой картинке
    (BMP и PNG его несут) → DPI. ⛔ Не «что просили»: просьбу драйвер мог
    не принять — ровно так страница и стала 75 % (12.10)."""
    for cand in (given, im.info.get("dpi")):
        try:
            x, y = float(cand[0]), float(cand[1])
        except (TypeError, ValueError, IndexError):
            continue
        if x >= MIN_SANE_DPI and y >= MIN_SANE_DPI:
            return x, y
    return float(DPI), float(DPI)


def _preview_of(im) -> str:
    """Маленький PNG строкой data: — карточке на экране, не файлом."""
    im = im.copy()
    im.thumbnail((PREVIEW_PX, PREVIEW_PX))
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _page(data: bytes, dpi: Dpi | None) -> tuple[bytes, Dpi, str]:
    """Лист драйвера → страница сессии (серый PNG, разрешение, превью)."""
    im = _image(data)
    d = _dpi_of(im, dpi)
    gray = im.convert("L")
    buf = io.BytesIO()
    gray.save(buf, "PNG", dpi=d, compress_level=3)
    return buf.getvalue(), d, _preview_of(gray)


def add_page(pid: int, data: bytes, dpi: Dpi | None = None) -> list[str]:
    """Положить лист в сессию пациента; возвращает превью всех страниц.
    Битая картинка — scan_err, лист не кладётся."""
    try:
        page = _page(data, dpi)
    except Exception as e:                   # noqa: BLE001 — не картинка / экзотика
        raise ScanError("scan_err") from e
    with _sess_lock:
        pages_now = _sessions.setdefault(pid, [])
        if len(pages_now) >= MAX_PAGES:
            raise ScanError("scan_err")
        pages_now.append(page)
        return [pv for _, _, pv in pages_now]


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
    return to_pdf([(png, d) for png, d, _ in pages_now])


def to_pdf(pages_in: list) -> bytes:
    """Многостраничный PDF: оттенки серого, JPEG внутри, ~100–300 КБ на лист
    при 200 dpi. Страница — ИСТИННЫЙ размер листа: пиксели ÷ разрешение, с
    которым лист сняли. Элемент — байты картинки или пара (байты, разрешение).
    ⚠️ Pillow пишет одно разрешение на весь файл — от первой страницы;
    страница с другим разрешением пересчитывается к нему, иначе её размер
    соврал бы (в одной сессии одного сканера так не бывает, но правда о
    размере листа важнее этой уверенности)."""
    from PIL import Image
    items = [p if isinstance(p, tuple) else (p, None) for p in pages_in]
    ims, dpis = [], []
    for data, given in items:
        im = _image(data)
        dpis.append(_dpi_of(im, given))
        ims.append(im.convert("L"))
    base = dpis[0]
    for i in range(1, len(ims)):
        dx, dy = dpis[i]
        if (dx, dy) != base:
            ims[i] = ims[i].resize((max(1, round(ims[i].width * base[0] / dx)),
                                    max(1, round(ims[i].height * base[1] / dy))),
                                   Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    first, rest = ims[0], ims[1:]
    first.save(buf, "PDF", save_all=bool(rest), append_images=rest,
               dpi=base, quality=80)
    return buf.getvalue()
