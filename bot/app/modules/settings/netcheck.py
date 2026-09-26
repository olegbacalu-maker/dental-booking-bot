"""Что из сети клиники ДЕЙСТВИТЕЛЬНО доходит до этой программы.

Два вопроса, на которые страница «Acces din rețea» раньше отвечала описанием,
а не фактом:

1. **Пустит ли Windows входящее соединение к ЭТОМУ exe.** До 26.09 состояние
   спрашивалось по ИМЕНИ правила (`netsh … show rule name=DentPilot`, код
   возврата), а имя программу не называет. После переезда в `Program Files`
   (P1) проверка врала в сторону «всё в порядке»:
   * правило «DentPilot» от старой раскладки (`C:\\Users\\Public\\DentPilot`)
     на месте, а новому exe не разрешено ничего — и кнопки на странице нет,
     потому что «правило есть»;
   * netsh сравнивает имена без учёта регистра, так что правило «dentpilot»,
     которое сама Windows завела СТАРОМУ exe по своему окну «Разрешить
     доступ», тоже засчитывалось (машина Олега, 26.09);
   * запрет, который Windows ставит, пока её окно ждёт ответа, и оставляет
     после «Отмена», не был виден вовсе — а запрет в брандмауэре сильнее
     любого разрешения (журнал брандмауэра Олега 26.09: 14:12:57 блок,
     14:13:03 разрешение — шесть секунд до щелчка).
   Теперь спрашиваем правила по ПУТИ программы и по действию и сравниваем с
   типом той сети, в которой живёт адрес для телефона.

2. **Дошёл ли до программы хоть один запрос из сети.** Единственная проверка,
   которая отвечает на «телефон не открывает» без гадания: пусто здесь —
   запрос не доходит до этого компьютера (другой Wi-Fi, гостевая сеть,
   брандмауэр, изоляция на роутере); есть строка — сеть в порядке, и искать
   надо на самом телефоне. Сам компьютер себе этого не докажет: соединение
   к своему же адресу брандмауэр не фильтрует.

⚠️ Текст `netsh` локализован и НЕ разбирается (прайор lan.py). Здесь —
COM-объект брандмауэра через PowerShell: числа и имена перечислений, а не
фразы. Путь к exe уходит в PowerShell ПЕРЕМЕННОЙ ОКРУЖЕНИЯ, а не склейкой
строки: скрипт — константа.
⚠️ Модуль без импортов проекта: его разбирает прогон без сервера.
"""
from __future__ import annotations

import ipaddress
import json
import os
import socket
import subprocess
import time

# Биты профилей брандмауэра (NET_FW_PROFILE2_*) и имя категории сети, которым
# их называет Get-NetConnectionProfile. Порядок в `on`/`shut` скрипта — этот же.
PROFILE_BIT = {"DomainAuthenticated": 1, "Private": 2, "Public": 4}
_ORDER = (1, 2, 4)
ALLOW, BLOCK = 1, 0          # NET_FW_ACTION_*
_TCP_OR_ANY = (6, 256)       # NET_FW_IP_PROTOCOL_TCP / _ANY

# ⛔ Скрипт — КОНСТАНТА. Всё переменное приходит окружением (DP_FW_EXE,
# DP_FW_IP): ни путь, ни адрес не становятся частью текста команды.
PS_SCRIPT = r"""
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$ErrorActionPreference = 'Stop'
$exe = [Environment]::ExpandEnvironmentVariables($env:DP_FW_EXE)
$fw = New-Object -ComObject HNetCfg.FwPolicy2
$rules = @()
foreach ($r in $fw.Rules) {
  if ($r.Direction -ne 1) { continue }
  $app = $r.ApplicationName
  if (-not $app) { continue }
  if ([Environment]::ExpandEnvironmentVariables($app) -ne $exe) { continue }
  $rules += [pscustomobject]@{ a = [int]$r.Action; p = [int]$r.Profiles; e = [bool]$r.Enabled; t = [int]$r.Protocol }
}
$cat = ''; $name = ''
if ($env:DP_FW_IP) {
  $ip = Get-NetIPAddress -IPAddress $env:DP_FW_IP -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($ip) {
    $cp = Get-NetConnectionProfile -InterfaceIndex $ip.InterfaceIndex -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($cp) { $cat = [string]$cp.NetworkCategory; $name = [string]$cp.Name }
  }
}
$on = @(1, 2, 4 | ForEach-Object { [bool]$fw.FirewallEnabled($_) })
$shut = @(1, 2, 4 | ForEach-Object { [bool]$fw.BlockAllInboundTraffic($_) })
[pscustomobject]@{ rules = $rules; category = $cat; network = $name; on = $on; shut = $shut } | ConvertTo-Json -Compress -Depth 3
"""


def probe(exe: str, ip: str = "", timeout: float = 12.0) -> dict | None:
    """Правила брандмауэра для `exe` и тип сети адреса `ip`. None — спросить
    нечем (не Windows, PowerShell не ответил, ответ не разобрался).
    ⚠️ Секунда-две: PowerShell холодный. Звать из потока, не из цикла событий."""
    if os.name != "nt":
        return None
    env = dict(os.environ, DP_FW_EXE=exe, DP_FW_IP=ip or "")
    try:
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-Command", PS_SCRIPT],
            capture_output=True, timeout=timeout, env=env,
            # noconsole-сборка: без флага у клиники мигало бы чёрное окно
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    try:
        d = json.loads(r.stdout.decode("utf-8", "replace").strip() or "null")
    except ValueError:
        return None
    if not isinstance(d, dict):
        return None
    rules = d.get("rules") or []
    if isinstance(rules, dict):      # PowerShell 5.1 разворачивает массив из одного
        rules = [rules]
    return {"rules": [x for x in rules if isinstance(x, dict)],
            "category": str(d.get("category") or ""),
            "network": str(d.get("network") or ""),
            "on": list(d.get("on") or []), "shut": list(d.get("shut") or [])}


def verdict(st: dict) -> str:
    """'ok' — входящее к exe пропустят; 'missing' — разрешения для этой сети
    нет (Windows отбросит); 'blocked' — есть запрет на exe (сильнее любого
    разрешения); 'shut' — профиль сети закрыт для ВСЕХ входящих («Блокировать
    все входящие подключения»): это не правило, кнопкой не лечится.

    Тип сети неизвестен — разрешение засчитывается в любом профиле: лучше
    промолчать, чем послать директора чинить исправное.
    """
    bit = PROFILE_BIT.get(st.get("category") or "")
    if bit is not None:
        i = _ORDER.index(bit)
        on, shut = st.get("on") or [], st.get("shut") or []
        if len(on) == 3 and not on[i]:
            return "ok"              # брандмауэр для этой сети выключен
        if len(shut) == 3 and shut[i]:
            return "shut"

    def hits(r: dict) -> bool:
        return (bool(r.get("e")) and r.get("t") in _TCP_OR_ANY
                and (bit is None or bool(int(r.get("p", 0)) & bit)))

    rules = [r for r in st.get("rules") or [] if hits(r)]
    if any(r.get("a") == BLOCK for r in rules):
        return "blocked"
    if any(r.get("a") == ALLOW for r in rules):
        return "ok"
    return "missing"


def profiles_for(category: str) -> str:
    """Профили для НАШЕГО правила: частная и доменная сеть всегда, публичная —
    только если сеть клиники Windows сама называет «Public». Её так называет
    Windows по умолчанию для любого нового Wi-Fi, а её собственное окно
    «Разрешить доступ» разрешает ровно текущий тип сети. Директор включает
    доступ в ЭТОЙ сети; перевести всю сеть в «Private» было бы шире: вместе с
    DentPilot открылось бы всё, что Windows разрешает частным сетям."""
    return "private,domain,public" if category == "Public" else "private,domain"


# ---------- кто пришёл из сети ----------

_KEEP = 12  # строк достаточно для клиники; больше — это уже журнал, а не проверка


def is_network_peer(host: str) -> bool:
    """Адрес пира — не этот компьютер. Пустой/непонятный — не считаем:
    неоткуда не значит «из сети»."""
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    mapped = getattr(addr, "ipv4_mapped", None)
    return not (mapped or addr).is_loopback


def device_of(ua: str) -> str:
    """Словом, что это за устройство — по User-Agent, грубо и честно.
    ⚠️ iPad в Safari по умолчанию представляется компьютером Mac."""
    u = ua or ""
    if "iPad" in u:
        return "iPad"
    if "iPhone" in u:
        return "iPhone"
    if "Android" in u:
        # у телефонов в строке есть «Mobile», у планшетов — нет
        return "telefon Android" if "Mobile" in u else "tabletă Android"
    if "Windows" in u:
        return "calculator Windows"
    if "Macintosh" in u:
        return "Mac sau iPad"
    return "alt dispozitiv"


def own_addresses() -> set[str]:
    """Адреса ЭТОГО компьютера в сетях. Нужны, чтобы не засчитать сам сервер:
    браузер на нём, открытый по адресу для телефона (`http://192.168.x.y`),
    приходит НЕ с петли, но брандмауэр такое соединение не фильтрует — и
    строка «пришёл из сети» соврала бы, что второе устройство пройдёт."""
    out: set[str] = set()
    try:
        for *_x, sa in socket.getaddrinfo(socket.gethostname(), None):
            out.add(str(sa[0]).split("%")[0])
    except OSError:
        pass
    return out


def note(peers: dict, host: str, ua: str, now: float | None = None,
         own: set[str] | frozenset = frozenset()) -> None:
    """Запомнить приход из сети: адрес → (когда, что за устройство). Свой
    компьютер не записывается — ни с петли, ни по своему адресу в сети
    (`own`); держим последние `_KEEP` адресов."""
    if not is_network_peer(host) or host in own:
        return
    peers[host] = (time.time() if now is None else now, device_of(ua))
    if len(peers) > _KEEP:
        for old in sorted(peers, key=lambda k: peers[k][0])[:len(peers) - _KEEP]:
            del peers[old]


def ago(sec: float) -> str:
    s = max(0, int(sec))
    if s < 60:
        return f"acum {s} s"
    if s < 3600:
        return f"acum {s // 60} min"
    return f"acum {s // 3600} h"


def lines(peers: dict, now: float | None = None) -> list[str]:
    """Строки для страницы, свежие сверху: «192.168.0.23 — tabletă Android,
    acum 12 s». Без HTML: оформление — дело страницы."""
    t = time.time() if now is None else now
    return [f"{ip} — {dev}, {ago(t - at)}"
            for ip, (at, dev) in sorted(peers.items(), key=lambda kv: -kv[1][0])]
