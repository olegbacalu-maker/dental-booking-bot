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

Firewall-правило НЕ может завести установщик: он намеренно
PrivilegesRequired=lowest (per-user установка в Public — архитектурное
решение, менять модель прав ради опциональной фичи нельзя). Поэтому правило
создаёт САМА программа по кнопке — через ShellExecute «runas»: Windows
показывает UAC, директор подтверждает, netsh выполняется с правами
администратора. Это работает и у давно установленных копий, которым
установщик больше не запускают (self-update установщик не прогоняет).

Чтение статуса — `netsh ... show rule`: смотреть только КОД возврата
(0 — правило есть, 1 — нет); текст вывода локализован Windows-ом и потому
не разбирается (та же грабля, что с текстами ошибок SQLite).
"""
from __future__ import annotations

import html
import os
import socket
import subprocess
import sys
import urllib.parse

from ...core.layout import _ic

FIREWALL_RULE = "DentPilot"


def enabled() -> bool:
    """Текущий ПРОЦЕСС запущен с сетевым доступом? (env приезжает из
    dental.env при старте; после переключения программа перезапускается,
    поэтому файл и окружение расходятся только в dev-режиме)."""
    return os.environ.get("DENTART_LAN", "").strip() == "1"


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


def firewall_rule_ok() -> bool | None:
    """None = проверить нечем (не Windows / netsh недоступен, dev-режим)."""
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # noconsole-сборка:
        # без флага у клиники на долю секунды мигало бы чёрное окно
        r = subprocess.run(
            ["netsh", "advfirewall", "firewall", "show", "rule",
             f"name={FIREWALL_RULE}"],
            capture_output=True, timeout=4, creationflags=flags)
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return None


def request_firewall_rule() -> bool:
    """Создать правило через UAC (ShellExecute «runas»). True = запрос Windows
    показан (не «правило создано»: итог UAC отсюда не виден — страница после
    обновления перечитает статус). Пересоздание delete+add одним cmd-вызовом:
    один UAC вместо двух, и правило со старым путём к exe (после переезда
    папки) не остаётся дублем."""
    exe = sys.executable
    args = (f'/c netsh advfirewall firewall delete rule '
            f'name="{FIREWALL_RULE}" >nul 2>&1 & '
            f'netsh advfirewall firewall add rule name="{FIREWALL_RULE}" '
            f'dir=in action=allow program="{exe}" profile=private enable=yes')
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


def render() -> str:
    on = enabled()
    p_num = port()
    body = [f"<h2>{_ic('wifi')} Acces din rețea</h2>",
            "<p class='hint' style='margin-top:0;max-width:640px'>"
            "Registrul se deschide și pe al doilea calculator al clinicii "
            "(cabinet, recepție) sau pe telefonul medicului — în aceeași "
            "rețea. Fiecare intră cu parola lui; drepturile și jurnalul de "
            "acces funcționează ca de obicei.</p>",
            f"<div {_WARN}>{_ic('monitor')} <b>Un program, o singură "
            f"evidență.</b> Programul rămâne instalat pe <b>un singur "
            f"calculator</b> — acesta. Celelalte doar <b>deschid adresa lui</b> "
            f"în browser și lucrează în aceeași evidență, în același timp."
            f"<br><br>{_ic('ban')} <b>Nu instalați programul și pe al doilea "
            f"calculator.</b> Acolo ar porni cu evidența lui, goală și cu totul "
            f"separată: ce se scrie la recepție nu s-ar vedea în cabinet, deși "
            f"ambele programe par că funcționează corect.</div>"]

    if on:
        ip = lan_ip()
        if ip:
            url = f"http://{ip}:{p_num}/admin"
            q = urllib.parse.quote(url, safe="")
            body.append(
                f"<div {_WARN}><b style='color:var(--green-t)'>{_ic('check')} Activ.</b> "
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
                f"style='width:180px;height:180px'></div>")
        else:
            body.append(
                f"<div {_WARN}>{_ic('sos')} Accesul e pornit, dar calculatorul nu pare "
                f"conectat la vreo rețea — verificați conexiunea și "
                f"redeschideți pagina.</div>")
        fw = firewall_rule_ok()
        if fw is False:
            body.append(
                f"<div {_WARN}>{_ic('sos')} <b>Regula de firewall lipsește</b> — "
                f"al doilea calculator și telefonul nu vor putea intra. "
                f"Apăsați butonul și confirmați "
                f"în fereastra Windows (UAC):"
                f"<form method='post' action='/admin/lan/firewall' "
                f"style='margin:10px 0 0'>"
                f"<button style='background:var(--teal);color:var(--on-teal);"
                f"border:none;border-radius:var(--r-ctl);height:40px;"
                f"padding:0 18px;font-size:13.5px;font-weight:600;"
                f"cursor:pointer'>{_ic('shield')} Creează regula de firewall</button>"
                f"</form>"
                f"<small style='color:var(--text3)'>Fereastra de confirmare "
                f"apare pe ecranul acestui calculator. După confirmare, "
                f"redeschideți pagina — starea se actualizează.</small></div>")
        body.append(
            f"<div {_WARN}>De știut:<br>"
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
            f"· dacă nu se conectează: rețeaua Windows a acestui "
            f"calculator trebuie să fie «Private», nu «Public».</div>")
        btn_label, mode = "Dezactivează accesul", "off"
        tone, ink = "var(--red-t)", "#fff"  # красный — цвет смысла, теме не отдан
    else:
        body.append(
            f"<div {_WARN}>Accesul este <b>oprit</b> — programul răspunde "
            f"doar pe acest calculator (127.0.0.1), ca până acum. După "
            f"activare, registrul va putea fi deschis de pe al doilea "
            f"calculator al clinicii sau de pe telefoane, cu parola "
            f"fiecărui utilizator.</div>")
        btn_label, mode = "Activează accesul", "on"
        tone, ink = "var(--teal)", "var(--on-teal)"

    body.append(
        f"<form method='post' action='/admin/lan/save' "
        f"onsubmit=\"return confirm('Programul se va reporni pentru "
        f"aplicare. Continuați?')\">"
        f"<input type='hidden' name='mode' value='{mode}'>"
        f"<button style='background:{tone};color:{ink};border:none;"
        f"border-radius:var(--r-ctl);height:44px;padding:0 22px;"
        f"font-size:14px;font-weight:600;cursor:pointer'>"
        f"{btn_label}</button></form>")
    return "".join(body)
