"""Каркас страницы журнала: боковое меню, верхняя панель, баннеры сообщений,
подключение оформления — всё, что одинаково на КАЖДОМ экране админки.

Здесь же словарь MSG_BANNER: коды, которыми маршруты отвечают друг другу и
пользователю. Он общий намеренно — как только каждый модуль заведёт свои
тексты, «Programare adăugată ✔» начнёт звучать в трёх вариантах.
"""
from __future__ import annotations

import html
import re
import sys
import urllib.parse
from datetime import date, datetime

from .. import brand, db, paths
from .. import engine as eng
from .. import update as upd
from .auth import (PERM_MONEY, PERM_SETTINGS, ROLE_LABEL, _sec_warn, can,
                   request_user, tamper_alert)

FEEDBACK_EMAIL = "dentpilotpro@gmail.com"

# Единый диапазон часов для ВСЕХ выпадающих списков: часы клиники, обед,
# личное окно врача. Раньше их было три разных (0-23 / 6-21 / 7-23) — клиника
# видела в соседних полях разные наборы без всякой причины.
# 07:00 — самая ранняя разумная смена; потолок 21:00 намеренно выше вечерних
# 19-20, чтобы кабинет с поздним приёмом мог себя настроить.
HOUR_MIN, HOUR_MAX = 7, 21


# путь считается от корня пакета, а не от расположения ЭТОГО файла: main.py
# однажды разъедется по модулям, а статика останется на месте (см. paths.py)
STATIC = paths.resource("static")


_CSS_CACHE: dict[str, str] = {}


def _asset(*parts: str) -> str:
    """Текст файла из static/. В собранной программе читается один раз, при
    запуске из исходников — каждый раз: правка стилей видна по F5, без
    перезапуска сервера. Оформление правят чаще, чем код."""
    key = "/".join(parts)
    if paths.is_frozen() and key in _CSS_CACHE:
        return _CSS_CACHE[key]
    text = (STATIC.joinpath(*parts)).read_text(encoding="utf-8")
    _CSS_CACHE[key] = text
    return text


def _asset_ver(*parts: str) -> str:
    """Метка версии в адресе файла — ею сбрасывается кеш браузера.

    У клиники это версия программы: адрес меняется ровно тогда, когда приехало
    обновление. При запуске из исходников — время правки файла, иначе работа
    над оформлением превращается в борьбу с кешем: версия-то не менялась."""
    if paths.is_frozen():
        return eng.APP_VERSION
    try:
        return str(int(STATIC.joinpath(*parts).stat().st_mtime))
    except OSError:
        return eng.APP_VERSION


MSG_BANNER = {
    "ok": ("ok", "Programare adăugată ✔"),
    "conflict": ("err", "Intervalul este deja ocupat la acest medic"),
    "dup": ("err", "Pacientul are deja o programare la această oră"),
    "past": ("err", "Ora aleasă a trecut deja — reîmprospătați lista orelor libere"),
    "ok_past": ("warn", "Programare adăugată ✔ — atenție: este pe o zi trecută. "
                        "Verificați data dacă nu ați vrut asta"),
    "bad": ("err", "Date invalide — verificați câmpurile"),
    "bad_name": ("err", "Lipsește numele pacientului"),
    "bad_phone": ("err", "Telefonul are mai puțin de 8 cifre — verificați numărul"),
    "bad_off": ("err", "Medicul nu este activ (concediu sau arhivat) — "
                       "alegeți alt medic sau readuceți-l din concediu în Medici"),
    "bad_time": ("err", "Ora poate fi doar fixă sau la jumătate (ex. 10:00, 10:30)"),
    "ok_note": ("ok", "Notiță adăugată — slotul este blocat pentru bot ✔"),
    "ok_comment": ("ok", "Comentariu salvat ✔"),
    "ok_set": ("ok", "Setări salvate ✔ — botul folosește deja noile date"),
    "upd_err": ("err", "Actualizarea a eșuat — vezi detalii în pagina de setări / log"),
    "ok_pin": ("ok", "PIN schimbat ✔"),
    "bad_pin": ("err", "PIN-ul vechi e greșit sau cel nou nu are 4–6 cifre identice"),
    "lock_pin": ("warn", "Prea multe încercări greșite — așteptați câteva minute"),
    "bad_tok": ("err", "Token invalid — copiați exact tokenul de la @BotFather"),
    "ok_tok": ("ok", "Token salvat ✔ — reporniți programul pentru aplicare"),
    "part_note": ("ok", "Pauza a fost salvată parțial — unele ore erau deja ocupate"),
    "bad_set": ("err", "Setări invalide — verificați câmpurile (nume/telefon, ore, minim un medic și un serviciu)"),
    "outside": ("err", "Vizita nu încape în programul clinicii (închidere sau pauză)"),
    "ok_card": ("ok", "Fișa pacientului a fost actualizată ✔"),
    "ok_pay": ("ok", "Plata a fost înregistrată ✔"),
    "bad_pay": ("err", "Sumă sau metodă invalidă — verificați plata"),
    "pay_del": ("ok", "Plata a fost ștearsă — urma rămâne în istoricul fișei"),
    "bad_export": ("err", "Nu am putut pregăti arhiva cu datele pacientului — "
                          "verificați spațiul pe disc; detalii în data\\dentpilot.log"),
    "ok_del": ("ok", "Fișa pacientului a fost ștearsă definitiv ✔"),
    "ok_anon": ("ok", "Datele de identitate au fost șterse ✔ — înregistrările "
                      "medicale rămân sub numărul fișei"),
    "bad_erase": ("err", "Pentru ștergere scrieți STERG în câmpul de confirmare"),
    "bad_bkp_pass": ("err", "Parola arhivei trebuie să aibă cel puțin 10 caractere"),
    "bad_bkp": ("err", "Nu am putut crea arhiva de rezervă — verificați spațiul "
                       "pe disc; detalii în data\\dentpilot.log"),
    "bad_card": ("err", "Date invalide — verificați câmpurile fișei"),
    "new_pat": ("ok", "Pacient adăugat ✔ — completați fișa (dinți, plan, documente)"),
    "dup_pat": ("warn", "Există deja un pacient cu acest telefon — am deschis fișa lui. "
                        "Dacă este altă persoană (numărul familiei), adăugați-o cu alt "
                        "număr sau fără număr"),
    "bad_pat": ("err", "Lipsește numele pacientului"),
    "no_access": ("err", "Secțiunea este rezervată directorului clinicii. "
                         "Dacă aveți nevoie de acces, cereți-i să vă schimbe rolul "
                         "în Setări → Utilizatori"),
    "ok_user": ("ok", "Utilizator salvat ✔"),
    "bad_user": ("err", "Date invalide — verificați numele, rolul și parola (4–6 cifre)"),
    "dup_user": ("err", "Parola este deja folosită de alt utilizator — alegeți alta. "
                        "Intrarea se face doar cu parola, deci ea trebuie să fie unică"),
    "last_dir": ("err", "Trebuie să rămână cel puțin un director — altfel nimeni nu mai "
                        "poate deschide Setările și nu are cine să dea drepturi înapoi"),
    "self_user": ("err", "Nu vă puteți șterge propriul cont — cereți altui director"),
    "ok_doc": ("ok", "Document încărcat ✔ — rămâne local, în folderul programului"),
    "bad_doc": ("err", "Fișier gol sau prea mare (max 25 MB)"),
    "ok_med": ("ok", "Datele medicului au fost salvate ✔"),
    "bad_med": ("err", "Date invalide — verificați câmpurile medicului"),
    "new_med": ("ok", "Medic adăugat ✔ — completați fișa lui"),
    "dup_med": ("err", "Există deja un medic cu acest nume — numele trebuie să fie unic"),
    "ok_photo": ("ok", "Fotografia a fost salvată ✔ — rămâne local, lângă program"),
    "bad_photo": ("err", "Doar JPEG / PNG / WebP, până la 5 MB"),
    "ok_svc_med": ("ok", "Serviciile medicului au fost actualizate ✔"),
    "svc_empty": ("err", "Fiecare serviciu trebuie să rămână cu cel puțin un medic "
                         "ACTIV — altfel dispare din meniul botului. Bifați alt medic "
                         "(sau readuceți unul din concediu) înainte de a-l scoate pe acesta"),
    "save_err": ("err", "Nu am putut scrie fișierul clinicii (clinic.json) — datele NU "
                        "au fost salvate. Verificați spațiul pe disc și drepturile la "
                        "folderul programului; detalii în data\\dentpilot.log"),
    "arch_busy": ("err", "Medicul are programări viitoare — mutați-le la alt medic sau "
                         "alegeți «în concediu» în loc de arhivare"),
    "last_med": ("err", "Trebuie să rămână cel puțin un medic activ"),
}


def _banner(msg: str, d: date) -> str:
    out = ""
    if msg in MSG_BANNER:
        cls, text = MSG_BANNER[msg]
        out += f"<div class='banner {cls}'>{text}</div>"
    if not eng.hours_for(d):
        out += "<div class='banner err'>Zi liberă — clinica este închisă (bot-ul nu oferă această zi)</div>"
    return out


_I = {  # компактные stroke-иконки сайдбара
    "home": "<path d='M3 10.5 12 3l9 7.5M5.5 9.5V21h13V9.5'/>",
    "cal": "<rect x='3.5' y='5' width='17' height='16' rx='2.5'/><path d='M3.5 10h17M8.5 3v4M15.5 3v4'/>",
    "pat": "<circle cx='12' cy='8' r='3.5'/><path d='M5 20.5c1.3-3.8 4-5.4 7-5.4s5.7 1.6 7 5.4'/>",
    "med": "<path d='M8 3v4a4 4 0 0 0 8 0V3'/><path d='M12 11v3a4.5 4.5 0 0 0 9 0v-1'/>"
           "<circle cx='20.5' cy='11' r='1.6'/>",
    "stat": "<path d='M4 20h16M8 20v-6M13 20V7M18 20v-9'/>",
    "set": "<circle cx='12' cy='12' r='3'/><path d='M12 3v3M12 18v3M3 12h3M18 12h3M6 6l2 2M16 16l2 2M18 6l-2 2M8 16l-2 2'/>",
    "bot": "<rect x='3.5' y='7.5' width='17' height='12' rx='3'/><path d='M12 7.5V4'/><circle cx='9' cy='13.5' r='1' fill='currentColor' stroke='none'/><circle cx='15' cy='13.5' r='1' fill='currentColor' stroke='none'/>",
    "qr": "<rect x='4' y='4' width='6.5' height='6.5' rx='1'/><rect x='13.5' y='4' width='6.5' height='6.5' rx='1'/><rect x='4' y='13.5' width='6.5' height='6.5' rx='1'/><path d='M13.5 13.5h6.5v6.5h-6.5z'/>",
    "search": "<circle cx='11' cy='11' r='7'/><path d='m20 20-3.6-3.6'/>",
    # якоря строк профиля пациента (макет 08-03)
    "phone": "<path d='M6.5 3.5h3l1.5 4-2 1.2a12 12 0 0 0 5.3 5.3l1.2-2 4 1.5v3a1.5 1.5 0 0 1-1.7 1.5C10.6 17.4 6.6 13.4 5 5.2A1.5 1.5 0 0 1 6.5 3.5z'/>",
    "mail": "<rect x='3' y='5.5' width='18' height='13' rx='2.5'/><path d='m3.8 7 8.2 6 8.2-6'/>",
    "pin": "<path d='M12 21s7-6.3 7-11a7 7 0 1 0-14 0c0 4.7 7 11 7 11z'/><circle cx='12' cy='10' r='2.6'/>",
    "id": "<rect x='2.8' y='5' width='18.4' height='14' rx='2.5'/><circle cx='9' cy='11' r='2'/>"
          "<path d='M5.6 16.2c.7-1.6 2-2.3 3.4-2.3s2.7.7 3.4 2.3M15 10h4M15 13.5h4'/>",
    "shield": "<path d='M12 3l7 3v5.5c0 4.3-3 7.6-7 9.5-4-1.9-7-5.2-7-9.5V6z'/>",
}


def _ic(name: str) -> str:
    return (f"<svg width='16' height='16' viewBox='0 0 24 24' fill='none' "
            f"stroke='currentColor' stroke-width='1.8' stroke-linecap='round' "
            f"stroke-linejoin='round'>{_I[name]}</svg>")


def _initials(name: str) -> str:
    words = [w for w in re.split(r"[\s.]+", name) if w and w.lower() not in ("dr", "dr.")]
    return "".join(w[0].upper() for w in words[:2]) or "?"


# Корень пакета приложения — «app», как бы глубоко ни лежал текущий модуль.
# ⚠️ Раньше здесь стояло f"{__package__}.telegram", и это работало ровно до
# переезда файла: из core/ строка стала искать app.core.telegram, из модуля
# настроек — app.modules.settings.telegram. Адаптер при этом жив и опрашивает
# Telegram, а интерфейс показывает бота выключенным — поломка, которую не видно
# ни в логе, ни в тестах, потому что HTTP-ответ остаётся успешным.
_APP_PKG = (__package__ or "app").split(".")[0]


def tg_status() -> dict:
    """Статус Telegram-адаптера БЕЗ импорта адаптера: `import aiogram` занимает
    секунды, а это горячий путь (сайдбар рисуется на каждой странице). Модуль
    уже импортирован в startup(), если токен задан — берём его из sys.modules."""
    mod = sys.modules.get(f"{_APP_PKG}.telegram")
    if mod is None:
        return {"running": False, "username": "", "error": ""}
    return dict(mod.STATUS)


def _tg_state() -> tuple[bool, str]:
    """Короткий ответ для сайдбара: (работает ли, username)."""
    st = tg_status()
    return bool(st["running"]), st.get("username", "")


def _update_banner() -> str:
    if upd.can_self_update():
        # в desktop-версии баннер ведёт к кнопке «Actualizează acum», не на GitHub
        return (f" · <a href='/admin/settings/system' "
                f"style='color:#e8710a;font-weight:600'>🔄 versiune nouă "
                f"{html.escape(upd.STATE['latest'])} — click pentru actualizare</a>")
    if upd.asset_pending() and upd.is_desktop():
        # релиз есть, файла в нём ещё нет — честно говорим и НЕ шлём на GitHub
        return (f" · <span style='color:var(--text3)'>🔄 {html.escape(upd.STATE['latest'])} "
                f"se pregătește…</span>")
    if upd.newer_available():
        return (f" · <a href='{html.escape(upd.STATE['url'])}' target='_blank' "
                f"style='color:#e8710a;font-weight:600'>🔄 versiune nouă "
                f"{html.escape(upd.STATE['latest'])}</a>")
    return ""


def _setup_hint() -> str:
    """Пока профиль клиники — нетронутый шаблон, об этом надо говорить прямо.
    Иначе «Clinica mea» и «Medic 1» тихо доживают до первого пациента, а бот
    называет их вслух."""
    if not eng.CONFIG.get("template"):
        return ""
    return ("<div class='banner err' style='margin-bottom:14px'>"
            "Programul încă are datele de exemplu. "
            "<a href='/admin/settings/clinic'><b>Completați datele clinicii</b></a> — "
            "denumire, telefon, medici, servicii și program de lucru. "
            "Până atunci botul le spune pacienților exact ce scrie aici.</div>")


def _tamper_banner() -> str:
    """Предупреждение «auth.json трогали вне программы» — только директору:
    остальные не могут ни оценить «это был техник», ни сменить PIN-ы, и для
    них баннер был бы просто страшилкой без кнопки действия."""
    txt = tamper_alert()
    if not txt:
        return ""
    me = request_user()
    if me is not None and not can(me, PERM_SETTINGS):
        return ""
    return (f"<div class='banner err' style='margin-bottom:14px'>🛡 {html.escape(txt)}. "
            "Dacă nu a fost o intervenție cunoscută (resetarea unui PIN uitat, "
            "tehnicianul clinicii), schimbați PIN-urile în Setări → Utilizatori "
            "și verificați jurnalul de acces."
            "<form method='post' action='/admin/security/ack' "
            "style='display:inline;margin-left:12px'>"
            "<button style='background:none;border:1px solid currentColor;"
            "border-radius:8px;padding:4px 12px;cursor:pointer;color:inherit;"
            "font-size:13px'>Am luat la cunoștință</button></form></div>")


def _sidebar(active: str) -> str:
    # Пункт, которого человеку нельзя, не рисуется. ⚠️ Это удобство, а НЕ
    # защита: отказ выдаёт require() в самом маршруте, потому что адрес
    # набирается руками, а форма отправляется откуда угодно.
    me = request_user()
    show_money = can(me, PERM_MONEY) or me is None
    show_set = can(me, PERM_SETTINGS) or me is None

    def item(key: str, href: str, icon: str, label: str, extra: str = "") -> str:
        on = " on" if key == active else ""
        # href='' — строка без ссылки: так «Telegram Bot» остаётся у того, кому
        # настройки закрыты. Точка «бот жив» нужна и регистратуре (перестал
        # работать — перестали приходить записи), а вот сама страница ей
        # запрещена, и кнопка в отказ хуже, чем просто индикатор.
        link = f" href='{href}'" if href else ""
        return (f"<a class='{on.strip()}'{link} title='{label}'>{_ic(icon)}"
                f"<span>{label}</span>{extra}</a>")

    tg_on, tg_user = _tg_state()
    tg_dot = "<span class='dot ok'></span>" if tg_on else "<span class='dot off'></span>"
    tg_title = f"@{tg_user}" if tg_on else "neconectat"
    return f"""<aside class="side">
  <div class="brand">{brand.mark_svg(34, 'logo')}
    <div class="txt"><b>DentPilot</b><small title="{html.escape(eng.CLINIC_NAME)}">{html.escape(eng.CLINIC_NAME)}</small></div>
  </div>
  <nav>
    <div class="sec">Meniu</div>
    {item('dash', '/admin', 'home', 'Dashboard')}
    {item('prog', '/admin/all', 'cal', 'Programări')}
    {item('pat', '/admin/search', 'pat', 'Pacienți')}
    {item('med', '/admin/medici', 'med', 'Medici')}
    {item('stat', '/admin/stats', 'stat', 'Statistici') if show_money else ''}
    {item('set', '/admin/settings', 'set', 'Setări') if show_set else ''}
    <div class="sec">Sincronizări</div>
    {item('tg', '/admin/settings/telegram' if show_set else '', 'bot', 'Telegram Bot', tg_dot)}
    {item('qr', '/admin/qr-print', 'qr', 'QR pacienți')}
  </nav>
  <div class="sfoot" title="Telegram: {html.escape(tg_title)}">v{eng.APP_VERSION} · <span id="sf_clock"></span></div>
</aside>"""


def _topbar(bell: int | None) -> str:
    bell_html = ""
    if bell is not None:
        badge = f"<span class='n'>{bell}</span>" if bell else ""
        # ведёт к блоку «Programări noi din bot» (по created_at) — а не к дневному
        # фильтру: бронь на неделю вперёд должна быть в одном клике (урок демо 07-31)
        bell_html = (f"<a class='bell' href='/admin#botnew' "
                     f"title='Programări noi din bot'>🔔{badge}</a>")
    today = datetime.now(eng.TZ).date().isoformat()
    return f"""<div class="top">
  <form class="searchf" method="get" action="/admin/search">
    <input id="topq" name="q" placeholder="Caută pacient, telefon…" autocomplete="off">
    <span class="kbd">Ctrl K</span><button>🔍</button>
  </form>
  <div style="flex:1"></div>
  <span style="font-size:12px;color:var(--text3)">{_update_banner().removeprefix(' · ')}</span>
  {bell_html}
  <a class="newbtn" href="/admin/all?date={today}#addform"><span class="plus">+</span>Programare nouă</a>
  {_who_chip()}
</div>"""


def _who_chip() -> str:
    """Кто сидит за журналом — правый верхний угол.

    Появился только вместе с настоящими учётками (08-06). До них аватар с
    должностью был бы витриной: за ним не стояло ни одного пользователя, и
    «Director» на экране означал ровно ничего.
    """
    me = request_user()
    if not me:
        return ""
    role = ROLE_LABEL.get(me["role"], me["role"])
    # вторая строка: роль · клиника. Точки «Online» тут НЕТ намеренно — в
    # локальной программе нет системы присутствия, и зелёная точка обещала бы
    # то, чего не существует; живой индикатор есть у бота, где он настоящий
    return (f"<div class='who' title='{html.escape(me['name'])} · {role}'>"
            f"<span class='who-av'>{html.escape(_initials(me['name']))}</span>"
            f"<div class='who-n'><b>{html.escape(me['name'])}</b>"
            f"<small>{role} · {html.escape(eng.CLINIC_NAME)}</small></div>"
            f"<a class='who-out' href='/admin/logout' title='Ieșire din cont'>⏻</a>"
            f"</div>")


def _shell(body: str, sub: str, active: str = "dash", bell: int | None = None) -> str:
    fb_subject = urllib.parse.quote(
        f"Feedback DentPilot — {eng.CLINIC_NAME} (v{eng.APP_VERSION})")
    fb_body = urllib.parse.quote("Ideea / problema mea:\n\n")
    return f"""<!doctype html><html lang="ro"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" type="image/svg+xml" href="/favicon.ico">
<title>{html.escape(eng.CLINIC_NAME)} — registru</title>
<link rel="stylesheet" href="/static/css/panel.css?v={_asset_ver('css', 'panel.css')}">
<script>/* Оживлять цифры и полосы можно только при ОСМЫСЛЕННОМ открытии страницы.
Журнал перезагружает себя каждые 12 секунд (panel.js), и без этого выключателя
KPI пересчитывались бы на глазах весь рабочий день, а регистратура читала бы
бегущие цифры вместо расписания. panel.js перед автоперезагрузкой ставит флаг,
здесь он снимается — и класс `anim` не выдаётся.
⚠️ Скрипт обязан стоять В ШАПКЕ: класс нужен ДО первой отрисовки, иначе виден
кадр с конечным состоянием, и анимация выглядит рывком назад. Всё оформление
привязано к `.anim`, поэтому без JS страница просто статична — не пуста. */
try{{if(sessionStorage.getItem('dp_auto')==='1'){{sessionStorage.removeItem('dp_auto');}}
else{{document.documentElement.classList.add('anim');}}}}catch(e){{document.documentElement.classList.add('anim');}}
</script></head><body>
{_sidebar(active)}
<div class="main">
{_topbar(bell)}
<div class="content">
<h1><a href="/admin">{html.escape(eng.CLINIC_NAME)} — registrul clinicii</a></h1>
<div class="sub">{sub}{_sec_warn()} · v{eng.APP_VERSION}</div>
{_tamper_banner()}{_setup_hint()}
{body}
</div></div>
<div class="brandcorner">🦷 <b>DentPilot</b> ·
<a href="mailto:{FEEDBACK_EMAIL}?subject={fb_subject}&body={fb_body}"
   title="{FEEDBACK_EMAIL}">💬 Feedback</a></div>
<script src="/static/js/panel.js?v={_asset_ver('js', 'panel.js')}"></script>
</body></html>"""


STATUS_LABEL = {
    "confirmed": "✅ confirmată",
    "arrived": "🟢 în cabinet",
    "done": "🟦 a venit",
    "noshow": "🟥 nu a venit",
    "cancelled": "❌ anulată",
}


# статусы, при которых слот занят — единый источник правды в db.py
LIVE_STATUSES = db.ACTIVE_STATUSES


def _age(birth_year) -> int | None:
    if not birth_year:
        return None
    return datetime.now(eng.TZ).year - int(birth_year)


LOGIN_TMPL = """<!doctype html><html lang="ro"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__CLINIC__ — acces</title><style>
 body{font-family:'Inter','Segoe UI',system-ui,sans-serif;background:#F6FBF8;display:flex;
      align-items:center;justify-content:center;height:100vh;margin:0;color:#162033}
 form{background:#fff;padding:30px 32px;border-radius:18px;border:1px solid #E7EDF5;
      /* двухслойная, как --sh3 в panel.css: экран входа — первое, что видит
         клиника, а своей таблицы стилей у него нет (он обязан открываться,
         даже если статика не отдалась) */
      box-shadow:0 3px 6px rgba(15,23,42,.06),0 18px 40px rgba(15,23,42,.10);
      display:flex;flex-direction:column;gap:12px;width:340px}
 h1{font-size:19px;color:#162033;margin:0 0 4px;font-weight:600;letter-spacing:-.02em}
 input{height:44px;padding:0 14px;border:1px solid #E7EDF5;border-radius:12px;font-size:15px;
       outline:none;color:#162033}
 input:focus{border-color:#0E9F8A;box-shadow:0 0 0 3px rgba(14,159,138,.12)}
 button{background:#0E9F8A;color:#fff;border:none;border-radius:12px;height:44px;
        font-size:15px;font-weight:600;cursor:pointer;transition:background-color .2s ease}
 button:hover{background:#0B7E6D}
 .err{color:#B91C1C;font-size:13px}
</style></head><body>
<form method="post" action="/admin/login">
  <h1>🦷 __CLINIC__ — registrul clinicii</h1>
  __ERR__
  <input type="hidden" name="next" value="__NEXT__">
  __INPUT__
  <button>Intră</button>
  __HINT__
</form></body></html>"""


SETUP_TMPL = """<!doctype html><html lang="ro"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__CLINIC__ — PIN</title><style>
 body{font-family:'Inter','Segoe UI',system-ui,sans-serif;background:#0E9F8A;display:flex;
      align-items:center;justify-content:center;height:100vh;margin:0}
 form{background:#fff;padding:30px 32px;border-radius:18px;
      box-shadow:0 4px 8px rgba(15,23,42,.12),0 22px 50px rgba(15,23,42,.26);
      display:flex;flex-direction:column;gap:12px;width:340px}
 h1{font-size:19px;color:#162033;margin:0;font-weight:600;letter-spacing:-.02em}
 p{color:#7E8B9C;font-size:13px;margin:0;line-height:1.5}
 input{padding:12px;border:1px solid #E7EDF5;border-radius:12px;font-size:26px;
       text-align:center;letter-spacing:12px;outline:none;color:#162033}
 input:focus{border-color:#0E9F8A;box-shadow:0 0 0 3px rgba(14,159,138,.12)}
 button{background:#0E9F8A;color:#fff;border:none;border-radius:12px;height:48px;
        font-size:15px;font-weight:600;cursor:pointer;transition:background-color .2s ease}
 button:hover{background:#0B7E6D}
 .err{color:#B91C1C;font-size:13px}
</style></head><body>
<form method="post" action="/admin/setup">
  <h1>🦷 __CLINIC__</h1>
  <p>Prima pornire: setați un PIN pentru registrul clinicii (4–6 cifre).</p>
  __ERR__
  <input type="password" name="pin1" placeholder="PIN" inputmode="numeric"
         pattern="[0-9]*" maxlength="6" autofocus required>
  <input type="password" name="pin2" placeholder="repetați PIN" inputmode="numeric"
         pattern="[0-9]*" maxlength="6" required>
  <button>Setează PIN</button>
</form></body></html>"""


_DOW_ORDER = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


_DOW_FULL = {"mon": "Luni", "tue": "Marți", "wed": "Miercuri", "thu": "Joi",
             "fri": "Vineri", "sat": "Sâmbătă", "sun": "Duminică"}


_DOC_STATE_RO = {"activ": "Activ", "concediu": "În concediu", "arhivat": "Arhivat"}


def _doc_hours_text(dk: str) -> str:
    meta = eng.DOCTOR_META.get(dk, {})
    wf, wt = meta.get("work_from"), meta.get("work_to")
    if wf is None and wt is None:
        return "ca clinica"
    a = f"{int(wf):02d}:00" if wf is not None else "deschidere"
    b = f"{int(wt):02d}:00" if wt is not None else "închidere"
    return f"{a}–{b}"



