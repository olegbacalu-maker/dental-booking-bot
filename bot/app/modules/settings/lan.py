"""Доступ из сети клиники: второй компьютер и телефон (PWA, слой 2).

Задумывалось как «журнал на телефоне врача», но первый же вопрос директора
(08-13) был про ДВА РАБОЧИХ МЕСТА — кабинет и регистратура. Механизм тот же
самый, поэтому раздел зовётся «Acces din rețea», а телефон в нём — частный
случай: иначе директор ищет несуществующую настройку про второй компьютер и
делает единственное, что кажется очевидным, — ставит exe и туда (см. ниже).

⛔ Главное, что обязана сказать эта страница, — что программа остаётся в ОДНОМ
экземпляре. Вторая установка заводит СВОЮ базу рядом со своим exe, и клиника
получает два журнала, каждый из которых работает исправно: запись, сделанная
на регистратуре, просто не видна в кабинете. Ни ошибки, ни признака поломки —
поэтому предупреждение стоит в обоих состояниях страницы, до включения тоже.

Программа всю жизнь слушала только 127.0.0.1 — сетевого доступа не давали
даже роли (CLAUDE.md). Доступ по сети — первый шаг наружу, и он сделан
намеренно минимальным:

- включается ЯВНО директором, по умолчанию выключен; хранится как
  DENTART_LAN=1 в dental.env, потому что bind выбирает ЛАУНЧЕР
  (bot/desktop.py) до старта приложения — отсюда и перезапуск программы
  при переключении, тем же путём, что смена токена бота;
- работает только в настольном издании (SQLite + dental.env): облако
  публикуется туннелем, ему этот переключатель не нужен;
- открывает HTTP без TLS — страница честно требует «только Wi-Fi клиники,
  не гостевая сеть». HTTPS и доступ из дома — слой 3 (туннель), отдельный
  шаг с отдельным разговором по закону 195.

Правило брандмауэра создаёт САМА программа по кнопке — через ShellExecute
«runas»: Windows показывает UAC, директор подтверждает, netsh выполняется с
правами администратора. Это работает и у давно установленных копий, которым
установщик больше не запускают (self-update установщик не прогоняет).
⚠️ Прежний довод «установщик не может — он lowest» устарел с P1: установщик
теперь от администратора и мог бы ставить правило сам (не сделано). Кнопка
нужна и тогда: она же ЧИНИТ — правило на прежний путь exe, запрет от окна
Windows, сеть, которую Windows назвала «Public».

Чтение статуса — `netcheck.probe`: правила по ПУТИ exe и тип сети адреса для
телефона. ⛔ До 26.09 статус спрашивали по ИМЕНИ правила, и после переезда в
`Program Files` страница говорила «всё в порядке» при закрытом входе (разбор —
в `netcheck.py`). Текст `netsh` локализован и по-прежнему не разбирается.

Текст страницы собран КУСКАМИ (`intro_html`, `status_html`, `firewall_html`,
`tips_html`): JSON API отдаёт их React-экрану, который рисует кнопки сам
(старая серверная страница снята 12.10). Прозу здесь не дублируют — она одна.
"""
from __future__ import annotations

import html
import os
import socket
import sys
import time
import urllib.parse

from ...core import auth
from ...core.layout import _ic
from . import netcheck

FIREWALL_RULE = "DentPilot"

# Кто приходил из сети с запуска программы: адрес → (когда, что за
# устройство). Только в памяти процесса: это проверка связи, а не журнал
# доступа — тот ведётся отдельно и по людям, а не по адресам.
_PEERS: dict[str, tuple[float, str]] = {}
# Свои адреса — раз в минуту, а не на каждый запрос: getaddrinfo спрашивает
# систему, а зовут нас на каждом /admin и /api всех рабочих мест.
# ⚠️ Первый раз — всегда (None), а не «прошло больше минуты с нуля»: часы
# monotonic идут от загрузки Windows, и у программы из автозапуска в первую
# минуту свои адреса не исключались бы.
_OWN: list = [None, set()]


def _own() -> set[str]:
    now = time.monotonic()
    if _OWN[0] is None or now - _OWN[0] > 60:
        _OWN[:] = [now, netcheck.own_addresses() | {lan_ip()}]
    return _OWN[1]


def note_peer(request) -> None:
    """Зовёт промежуточный слой main на каждый /admin и /api. Запрос с
    другого устройства сети становится строкой на странице «Acces din rețea»
    — ответом на «телефон не открывает», который иначе ищут наугад. Сам этот
    компьютер не записывается и по своему адресу в сети (`netcheck.note`)."""
    host = request.client.host if request.client else ""
    if not netcheck.is_network_peer(host):
        return                      # петля — мимо, не спрашивая свои адреса
    netcheck.note(_PEERS, host, request.headers.get("user-agent", ""), own=_own())


def enabled() -> bool:
    """Текущий ПРОЦЕСС запущен с сетевым доступом? (env приезжает из
    dental.env при старте; после переключения программа перезапускается,
    поэтому файл и окружение расходятся только в dev-режиме).
    Читает `auth.lan_on` — одно место: от флага зависит и минимум PIN."""
    return auth.lan_on()


def port() -> int:
    return int(os.environ.get("DENTART_PORT", "8088"))


def lan_ip() -> str:
    """Адрес этого ПК в сети клиники. UDP-connect не шлёт ни одного пакета —
    ОС просто выбирает исходящий интерфейс; интернет для этого не нужен."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("192.0.2.1", 9))  # TEST-NET-1: адрес заведомо «наружу»
            ip = s.getsockname()[0]
        finally:
            s.close()
        return "" if ip.startswith("127.") else ip
    except OSError:
        return ""


def firewall_state() -> dict | None:
    """Пустит ли Windows входящее к ЭТОМУ exe в сети адреса для телефона:
    `netcheck.probe` + `verdict`. None — спросить нечем (не Windows).
    ⚠️ Секунда-две (PowerShell): звать через `asyncio.to_thread`, иначе на это
    время замрёт журнал у всех рабочих мест разом."""
    st = netcheck.probe(sys.executable, lan_ip())
    if st is not None:
        st["verdict"] = netcheck.verdict(st)
    return st


def firewall_ok(st: dict | None) -> bool | None:
    """Для JSON: True — пустят, False — нет, None — проверить нечем."""
    return None if st is None else st["verdict"] == "ok"


def firewall_fixable(st: dict | None) -> bool:
    """Кнопка лечит отсутствующее разрешение и запрет на exe. «Все входящие
    закрыты» — настройка профиля сети, её кнопка не трогает (tips_html)."""
    return st is not None and st["verdict"] in ("missing", "blocked")


def request_firewall_rule(st: dict | None = None) -> bool:
    """Создать правило через UAC (ShellExecute «runas»). True = запрос Windows
    показан (не «правило создано»: итог UAC отсюда не виден — страница после
    обновления перечитает статус).

    Одним cmd-вызовом, то есть одним UAC:
      1. снять правила с НАШИМ именем — на любой путь (прежняя раскладка
         оставляла «DentPilot» на `C:\\Users\\Public\\…`);
      2. снять ВСЕ входящие правила этого exe — среди них запрет, который
         Windows ставит, пока её окно ждёт ответа, и оставляет после
         «Отмена»; запрет сильнее разрешения, и без этого шаг 3 не помог бы;
      3. одно разрешение этому exe в профилях `netcheck.profiles_for`.
    """
    exe = sys.executable
    prof = netcheck.profiles_for((st or {}).get("category", ""))
    args = (f'/c netsh advfirewall firewall delete rule '
            f'name="{FIREWALL_RULE}" >nul 2>&1 & '
            f'netsh advfirewall firewall delete rule name=all dir=in '
            f'program="{exe}" >nul 2>&1 & '
            f'netsh advfirewall firewall add rule name="{FIREWALL_RULE}" '
            f'dir=in action=allow program="{exe}" profile={prof} enable=yes')
    try:
        import ctypes
        # >32 = запуск удался (сам netsh отработает уже за UAC-ом)
        return ctypes.windll.shell32.ShellExecuteW(
            None, "runas", "cmd.exe", args, None, 0) > 32
    except (OSError, AttributeError):  # не Windows — кнопки это не касается
        return False


_WARN = ("style='border:1px solid var(--line);border-radius:var(--r-card);"
         "background:var(--panel);padding:14px 16px;margin:12px 0;"
         "font-size:13px;line-height:1.6;color:var(--text2);max-width:640px'")


def address(on: bool) -> tuple[str, str]:
    """(ip, адрес журнала в сети) — пустые, пока доступ выключен или сети нет."""
    ip = lan_ip() if on else ""
    return ip, (f"http://{ip}:{port()}/admin" if ip else "")


def intro_html() -> str:
    """Что такое доступ из сети и главное предупреждение — в обоих состояниях."""
    return ("<p class='hint' style='margin-top:0;max-width:640px'>"
            "Registrul se deschide și pe al doilea calculator al clinicii "
            "(cabinet, recepție) sau pe telefonul medicului — în aceeași "
            "rețea. Fiecare intră cu parola lui; drepturile și jurnalul de "
            "acces funcționează ca de obicei.</p>"
            f"<div {_WARN}>{_ic('monitor')} <b>Un program, o singură "
            f"evidență.</b> Programul rămâne instalat pe <b>un singur "
            f"calculator</b> — acesta. Celelalte doar <b>deschid adresa lui</b> "
            f"în browser și lucrează în aceeași evidență, în același timp."
            f"<br><br>{_ic('ban')} <b>Nu instalați programul și pe al doilea "
            f"calculator.</b> Acolo ar porni cu evidența lui, goală și cu totul "
            f"separată: ce se scrie la recepție nu s-ar vedea în cabinet, deși "
            f"ambele programe par că funcționează corect.</div>")


_CATEGORY_RO = {"Public": "publică", "Private": "privată",
                "DomainAuthenticated": "de domeniu"}


def _net_name(st: dict | None) -> str:
    """«rețeaua «Orange…» (publică)» — имя и тип сети словами Windows."""
    st = st or {}
    kind = _CATEGORY_RO.get(st.get("category", ""), "")
    name = html.escape(st.get("network", ""))
    return (f"rețeaua «{name}»" if name else "această rețea") + (f" ({kind})" if kind else "")


def seen_html(st: dict | None = None) -> str:
    """Проверка связи: разрешает ли Windows и кто УЖЕ дошёл из сети. Второе —
    единственный ответ на «телефон не открывает» без гадания: сам компьютер
    себе этого не докажет, соединение к своему адресу брандмауэр не видит."""
    head = f"<b>{_ic('wifi')} Verificarea legăturii</b><br>"
    fw = ""
    if st is not None and st.get("verdict") == "ok":
        fw = (f"{_ic('check')} Windows lasă dispozitivele din {_net_name(st)} "
              f"să intre în DentPilot.<br>")
    seen = netcheck.lines(_PEERS)
    if seen:
        who = ("Au intrat din rețea de la pornirea programului:<br>"
               + "<br>".join(f"· {html.escape(s)}" for s in seen))
    else:
        who = ("Încă niciun dispozitiv din rețea de la pornirea programului. "
               "Deschideți adresa pe telefon sau pe al doilea calculator și "
               "reîncărcați această pagină: dacă aici nu apare nimic, cererea "
               "nu ajunge la acest calculator — alt Wi-Fi (poate cel pentru "
               "oaspeți), routerul izolează dispozitivele sau le oprește "
               "Windows.")
    return f"<div {_WARN}>{head}{fw}{who}</div>"


def status_html(on: bool, ip: str, url: str, st: dict | None = None) -> str:
    """Состояние: выключено / включено с адресом и QR / включено без сети.
    Включённое — с проверкой связи под адресом (`seen_html`)."""
    if not on:
        return (f"<div {_WARN}>Accesul este <b>oprit</b> — programul răspunde "
                f"doar pe acest calculator (127.0.0.1), ca până acum. După "
                f"activare, registrul va putea fi deschis de pe al doilea "
                f"calculator al clinicii sau de pe telefoane, cu parola "
                f"fiecărui utilizator.</div>")
    if not ip:
        return (f"<div {_WARN}>{_ic('sos')} Accesul e pornit, dar calculatorul nu pare "
                f"conectat la vreo rețea — verificați conexiunea și "
                f"redeschideți pagina.</div>")
    q = urllib.parse.quote(url, safe="")
    return (f"<div {_WARN}><b style='color:var(--green-t)'>{_ic('check')} Activ.</b> "
            f"Adresa registrului în rețeaua clinicii:"
            f"<div style='font-size:17px;font-weight:600;color:var(--text);"
            f"margin:8px 0 12px'>{html.escape(url)}</div>"
            f"<b>Pe al doilea calculator:</b> deschideți adresa în browser "
            f"(Chrome sau Edge) și salvați-o la favorite. În Edge: meniul "
            f"browserului › «Aplicații» › «Instalează acest site ca "
            f"aplicație» — registrul se deschide ca un program obișnuit, "
            f"fără bara de adrese."
            f"<div style='margin:12px 0 4px'><b>Pe telefon:</b> scanați "
            f"codul (telefonul — pe Wi-Fi-ul clinicii), apoi meniul "
            f"browserului › «Adaugă pe ecranul principal». Pe iPhone "
            f"registrul se deschide apoi ca aplicație, pe tot ecranul; pe "
            f"Android rămâne o scurtătură către browser.</div>"
            f"<img src='/qr?data={q}' "
            f"style='width:180px;height:180px'></div>" + seen_html(st))


def pins_html(short: list[dict], unknown: list[dict], on: bool) -> str:
    """Учётки, с которыми сеть не включается (17.10): PIN короче
    `auth.PIN_MIN_LAN` и записи, чью длину программа ещё не знает (человек не
    входил после обновления). Выключено — это причина, по которой кнопка
    закрыта; включено (флаг пережил обновление) — предупреждение. Пусто, когда
    все готовы. Без ссылок: страница раздела называется словами."""
    if not (short or unknown):
        return ""
    n = auth.PIN_MIN_LAN
    rows = ""
    for u in short:
        rows += (f"<br>· <b>{html.escape(u['name'])}</b> — PIN sub {n} cifre: "
                 f"setați-i unul nou în Setări › Securitate și utilizatori")
    for u in unknown:
        rows += (f"<br>· <b>{html.escape(u['name'])}</b> — lungimea PIN-ului nu e "
                 f"cunoscută: persoana să intre o dată în program (pe acest "
                 f"calculator) sau setați-i un PIN nou")
    if on:
        head = (f"<b>{_ic('sos')} PIN-uri prea scurte pentru rețea.</b> În rețea "
                f"PIN-ul poate fi încercat de pe orice telefon din Wi-Fi; de aceea, "
                f"cu accesul pornit, PIN-urile au cel puțin {n} cifre.")
    else:
        head = (f"<b>{_ic('sos')} Înainte de pornire: PIN-uri de cel puțin {n} "
                f"cifre.</b> În rețea PIN-ul poate fi încercat de pe orice telefon "
                f"din Wi-Fi, iar 4 cifre înseamnă doar 10 000 de variante. Accesul "
                f"se pornește după ce toți utilizatorii de mai jos au un PIN potrivit:")
    return f"<div {_WARN}>{head}{rows}</div>"


def firewall_html(st: dict | None = None) -> str:
    """Windows не пустит: разрешения для этой сети нет или exe запрещён.
    Кнопку рисует React-экран. Звать только при `firewall_fixable(st)`."""
    v = (st or {}).get("verdict", "missing")
    if v == "blocked":
        what = (f"<b>Windows blochează programul</b> — în fereastra lui de "
                f"confirmare s-a apăsat «Anulează» sau nu s-a răspuns. "
                f"Blocarea e mai puternică decât orice permisiune: al doilea "
                f"calculator și telefonul nu intră. Apăsați butonul și "
                f"confirmați în fereastra Windows (UAC) — blocarea se șterge, "
                f"iar DentPilot primește permisiunea:")
    elif (st or {}).get("category") == "Public":
        what = (f"<b>DentPilot nu are încă permisiune în {_net_name(st)}</b> — "
                f"așa marchează Windows orice Wi-Fi nou, iar al doilea "
                f"calculator și telefonul nu vor putea intra. Apăsați butonul "
                f"și confirmați în fereastra Windows (UAC): permisiunea se dă "
                f"doar programului DentPilot, nu întregii rețele.")
    else:
        what = (f"<b>Regula de firewall lipsește</b> — al doilea calculator și "
                f"telefonul nu vor putea intra. Apăsați butonul și confirmați "
                f"în fereastra Windows (UAC):")
    return (f"<div {_WARN}>{_ic('sos')} {what}"
            f"<small style='color:var(--text3)'>Fereastra de confirmare "
            f"apare pe ecranul acestui calculator. După confirmare, "
            f"redeschideți pagina — starea se actualizează.</small></div>")


def tips_html(st: dict | None = None) -> str:
    """Советы; сверху — закрытый для ВСЕХ входящих профиль сети: это настройка
    Windows, а не правило, и кнопка брандмауэра её не лечит."""
    shut = ""
    if st is not None and st.get("verdict") == "shut":
        shut = (f"<div {_WARN}>{_ic('sos')} <b>Windows respinge toate "
                f"conexiunile de intrare</b> în {_net_name(st)} — e bifată "
                f"setarea «Blochează toate conexiunile de intrare» (Securitate "
                f"Windows › Firewall și protecție rețea). Cât e bifată, nicio "
                f"permisiune nu ajută: debifați-o sau cereți ajutorul "
                f"administratorului.</div>")
    return shut + (f"<div {_WARN}>De știut:<br>"
            f"· calculatorul acesta trebuie să fie <b>pornit</b> — cât timp "
            f"doarme sau e oprit, în cabinet nu se deschide nimic (opriți-i "
            f"modul «Sleep»);<br>"
            f"· copiile de rezervă se fac tot aici — al doilea calculator nu "
            f"păstrează nimic;<br>"
            f"· adresa se poate schimba după repornirea routerului — dacă nu "
            f"se mai deschide, reveniți la această pagină și citiți adresa "
            f"nouă (sau cereți administratorului rețelei o adresă fixă);<br>"
            f"· doar în <b>rețeaua protejată a clinicii</b> — nu în cea "
            f"pentru pacienți/oaspeți;<br>"
            f"· conexiunea în rețea e necriptată (http) — de aceea accesul "
            f"e limitat la rețeaua locală, nu la internet;<br>"
            f"· de acasă NU funcționează — asta e o protecție, nu un "
            f"defect;<br>"
            f"· dacă nu se conectează: priviți mai sus «Verificarea "
            f"legăturii» — ea arată dacă cererea ajunge până la acest "
            f"calculator.</div>")

