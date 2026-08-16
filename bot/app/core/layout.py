"""Каркас страницы журнала: боковое меню, верхняя панель, баннеры сообщений,
подключение оформления — всё, что одинаково на КАЖДОМ экране админки.

Здесь же словарь MSG_BANNER: коды, которыми маршруты отвечают друг другу и
пользователю. Он общий намеренно — как только каждый модуль заведёт свои
тексты, «Programare adăugată» начнёт звучать в трёх вариантах.
"""
from __future__ import annotations

import html
import json
import logging
import os
import re
import sys
import urllib.parse
from datetime import date, datetime

from .. import brand, db, dpapi, paths
from .. import engine as eng
from .. import update as upd
from . import theme
from .auth import (PERM_DOCTORS, PERM_MONEY, PERM_SETTINGS, PIN_MAX, PIN_MIN,
                   ROLE_LABEL, _sec_warn, can,
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


def js_json(obj) -> str:
    """JSON для вставки в <script>. ЕДИНСТВЕННЫЙ допустимый способ.

    ⭐ `json.dumps` безопасен для JavaScript, но не для HTML: строка
    `</script>` внутри значения закрывает тег, и всё, что за ней, браузер
    читает как разметку. `ensure_ascii` тут не спасает — он трогает только
    не-ASCII, а `<` и `/` пропускает.

    Помощник появился 08-10 после аудита: на одной странице четыре места
    экранировали правильно, а два — нет, и мимо прошло имя врача, то есть
    поле, которое правит регистратура. Тот же класс, что нашло ревью 08-08 в
    подсказке зуба. ⛔ Не писать `json.dumps` в f-строке со `<script` — пятое
    место забудут снова.
    """
    return json.dumps(obj, ensure_ascii=True).replace("</", "<\\/")


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


def fonts_css() -> str:
    """Правила @font-face для страниц СО СВОЕЙ вёрсткой — ТЕМ ЖЕ файлом,
    который панель подключает ссылкой.

    Журнал получает `fonts.css` ссылкой: он кешируется, адрес несёт версию, а
    страница журнала перезагружает себя раз в 12 секунд — возить текст шрифта
    в разметке было бы расточительно. Вход, установка PIN и восстановление
    берут его СОДЕРЖИМЫМ, внутрь своего <style>: подключать таблицу стилей им
    нельзя по замыслу (они обязаны открыться, даже если статика не отдалась), а
    лишний запрос на первом экране клиники — ровно то, чего они избегают.
    Источник при этом один, поэтому объявление не задваивается.

    Внутрь страницы едут ТОЛЬКО правила: пояснения из шапки файла — три
    четверти его веса, и на первом экране клиники им делать нечего. Заодно это
    убирает из разметки слово `__FONTS__`, которое в тех пояснениях помянуто:
    иначе заполнитель «оставался» бы в готовой странице и проверка на забытую
    подстановку не значила бы ничего.

    ⚠️ Пропажа файла не имеет права уронить вход: без правил страница
    нарисуется системным шрифтом — тем же, что до 08-11. Поэтому OSError здесь
    не поднимается, а остаётся строкой в логе."""
    try:
        return re.sub(r"/\*.*?\*/", "", _asset("css", "fonts.css"),
                      flags=re.S).strip()
    except OSError:
        logging.getLogger("layout").error(
            "не читается fonts.css — страница останется на системном шрифте")
        return ""


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
    "ok": ("ok", "Programare adăugată"),
    "conflict": ("err", "Intervalul este deja ocupat la acest medic"),
    "dup": ("err", "Pacientul are deja o programare la această oră"),
    "past": ("err", "Ora aleasă a trecut deja — reîmprospătați lista orelor libere"),
    "ok_past": ("warn", "Programare adăugată — atenție: este pe o zi trecută. "
                        "Verificați data dacă nu ați vrut asta"),
    "bad": ("err", "Date invalide — verificați câmpurile"),
    "bad_name": ("err", "Lipsește numele pacientului"),
    "bad_phone": ("err", "Numărul de telefon pare incomplet — sunt necesare "
                         "minim 6 cifre (numerele străine sunt acceptate)"),
    "bad_bd": ("err", "Data nașterii nu este validă — verificați ziua, luna și "
                      "anul (nu poate fi în viitor)"),
    "bad_idnp": ("err", "IDNP trebuie să aibă exact 13 cifre — verificați "
                        "câmpul evidențiat"),
    "bad_off": ("err", "Medicul nu este activ (concediu sau arhivat) — "
                       "alegeți alt medic sau readuceți-l din concediu în Medici"),
    "bad_time": ("err", "Ora poate fi doar fixă sau la jumătate (ex. 10:00, 10:30)"),
    "ok_note": ("ok", "Notiță adăugată — ora este blocată"),
    "ok_move": ("ok", "Programare mutată"),
    # ⚠️ Оба отказа переноса говорят, ЧТО делать дальше. Перетаскивают с
    # открытого журнала, а он живёт с автообновлением: пока тянули, соседняя
    # вкладка могла и отменить визит, и завершить его.
    "mv_gone": ("err", "Programarea nu mai există — reîmprospătați pagina"),
    "mv_closed": ("err", "Se mută doar programările active — cea finalizată, "
                         "anulată sau neprezentată rămâne pe loc (redeschideți-o "
                         "dacă chiar trebuie mutată)"),
    # ⚠️ Текст обязан сказать, ЧТО делать, а не только что случилось: иначе
    # регистратура прочтёт «добавлено» и пойдёт дальше, а визит останется в
    # чужой карточке.
    "ok_other": ("warn", "Programare adăugată — dar la fișa unui pacient care "
                         "există deja cu acest telefon și are alt nume. Dacă "
                         "este altă persoană (numărul familiei), deschideți "
                         "fișa și mutați programarea, sau adăugați pacientul "
                         "separat din Pacienți"),
    "ok_comment": ("ok", "Comentariu salvat"),
    "ok_set": ("ok", "Setări salvate"),
    "ok_theme": ("ok", "Aspectul clinicii a fost salvat"),
    "bad_crypt": ("err", "Nu am putut pregăti criptarea — cheia nu a fost salvată. "
                         "Detalii în data\\dentpilot.log"),
    "crypt_on": ("warn", "Criptarea este deja activă. Pentru a o reface, opriți-o "
                         "mai întâi — altfel foaia tipărită nu ar mai deschide baza"),
    "ok_logo": ("ok", "Logo actualizat — apare la intrare și pe documentele tipărite"),
    "no_logo": ("ok", "Logo șters"),
    # ⚠️ Текст называет ПРИЧИНУ отказа: «logo invalid» отправило бы директора
    # искать ошибку в картинке, которая на вид открывается — а отказали ей за
    # формат (SVG) или за размер.
    "bad_logo": ("err", "Logo neacceptat — doar PNG sau JPEG, cel mult 2 MB. "
                        "SVG nu se acceptă din motive de securitate."),
    "upd_err": ("err", "Actualizarea a eșuat — vezi detalii în pagina de setări / log"),
    "ok_pin": ("ok", "PIN schimbat"),
    # ⚠️ границы — из констант, не числами: «4–6» пережило подъём потолка до 8
    # (08-13) и отговаривало от разрешённых 7–8 цифр
    "bad_pin": ("err", f"PIN-ul vechi e greșit sau cel nou nu are "
                       f"{PIN_MIN}–{PIN_MAX} cifre identice"),
    "lock_pin": ("warn", "Prea multe încercări greșite — așteptați câteva minute"),
    "bad_tok": ("err", "Token invalid — copiați exact tokenul de la @BotFather"),
    # ⚠️ dental.env не удалось ПРОЧИТАТЬ (придержан антивирусом/OneDrive или
    # сохранён в нечитаемой кодировке) — запись отменена, файл не тронут.
    "bad_env": ("err", "Nu am putut salva: fișierul dental.env nu a putut fi "
                       "citit (poate fi blocat de alt program). Închideți "
                       "programele care îl folosesc și încercați din nou; "
                       "detalii în data\\dentpilot.log"),
    "ok_tok": ("ok", "Token salvat — reporniți programul pentru aplicare"),
    "part_note": ("ok", "Pauza a fost salvată parțial — unele ore erau deja ocupate"),
    "bad_set": ("err", "Setări invalide — verificați câmpurile (nume/telefon, ore, minim un medic și un serviciu)"),
    "outside": ("err", "Vizita nu încape în programul clinicii (închidere sau pauză)"),
    # клиника открыта, но у ЭТОГО врача график уже кончился (work_from/work_to)
    "outside_doc": ("err", "Medicul nu lucrează la ora aleasă — verificați "
                           "programul lui în pagina Medici sau alegeți alt medic"),
    # ⚠️ <input type=date> отдаёт и «0012-08-15» — промах по сегменту года
    # выглядит законной ISO-датой, а период из неё выходит в 735 000 дней.
    # Текст обязан назвать ПОЛЕ, иначе директор ищет ошибку не там.
    "bad_period": ("err", "Perioada aleasă nu este validă — verificați anul în "
                          "câmpurile de date; intervalul poate fi de cel mult "
                          "un an și nu mai vechi de anul 2000"),
    "ok_card": ("ok", "Fișa pacientului a fost actualizată"),
    # ⚠️ Архивация УБИРАЕТ пациента из списка, и общее «фиша обновлена» об этом
    # молчит: человек возвращается в список, никого там не находит и решает,
    # что запись пропала. Сообщение обязано назвать, где искать.
    "ok_arh": ("ok", "Pacient trecut în arhivă — nu mai apare în listă. "
                     "Îl găsiți prin filtrul de status «Arhivat» sau "
                     "căutându-l după nume"),
    "ok_unarh": ("ok", "Pacient scos din arhivă — apare din nou în listă"),
    "ok_pay": ("ok", "Plata a fost înregistrată"),
    "bad_pay": ("err", "Sumă sau metodă invalidă — verificați plata"),
    "pay_del": ("ok", "Plata a fost ștearsă — urma rămâne în istoricul fișei"),
    "bad_export": ("err", "Nu am putut pregăti arhiva cu datele pacientului — "
                          "verificați spațiul pe disc; detalii în data\\dentpilot.log"),
    "ok_del": ("ok", "Fișa pacientului a fost ștearsă definitiv"),
    "ok_anon": ("ok", "Datele de identitate au fost șterse — înregistrările "
                      "medicale rămân sub numărul fișei"),
    "bad_erase": ("err", "Pentru ștergere scrieți STERG în câmpul de confirmare"),
    "bad_bkp_pass": ("err", "Parola arhivei trebuie să aibă cel puțin 10 caractere"),
    "bad_bkp": ("err", "Nu am putut crea arhiva de rezervă — verificați spațiul "
                       "pe disc; detalii în data\\dentpilot.log"),
    "bad_card": ("err", "Date invalide — verificați câmpurile fișei"),
    # ⚠️ Отказ подтверждается ТЕКСТОМ, поэтому и сообщение говорит, что делать
    # дальше с бумагой: без подписи запись по ст.13(5) неполна, а регистратура
    # об этом не знает — «refuz înregistrat» она прочла бы как «готово»
    "ok_refuz": ("ok", "Refuzul a fost consemnat în fișă — tipăriți acordul "
                       "informat și dați-l la semnat pacientului și medicului"),
    "bad_refuz": ("err", "Scrieți motivul refuzului și consecințele explicate "
                         "pacientului — legea cere ca acestea să fie "
                         "consemnate, nu doar bifat refuzul"),
    # ⛔ Удаление позиции, которую уже начали, закончили или от которой пациент
    # отказался, — стирание меддокументации. Текст обязан назвать выход
    "bad_pdel": ("err", "Se poate șterge doar o poziție neîncepută. Procedura "
                        "începută, finalizată sau refuzată rămâne în fișă — "
                        "închideți-o prin statut"),
    "new_pat": ("ok", "Pacient adăugat — completați fișa (dinți, plan, documente)"),
    "dup_pat": ("warn", "Există deja un pacient cu acest telefon — am deschis fișa lui. "
                        "Dacă este altă persoană (numărul familiei), adăugați-o cu alt "
                        "număr sau fără număr"),
    "bad_pat": ("err", "Lipsește numele pacientului"),
    "no_access": ("err", "Secțiunea este rezervată directorului clinicii. "
                         "Dacă aveți nevoie de acces, cereți-i să vă schimbe rolul "
                         "în Setări › Utilizatori"),
    "ok_user": ("ok", "Utilizator salvat"),
    "bad_user": ("err", f"Date invalide — verificați numele, rolul și parola "
                        f"({PIN_MIN}–{PIN_MAX} cifre)"),
    "dup_user": ("err", "Parola este deja folosită de alt utilizator — alegeți alta. "
                        "Intrarea se face doar cu parola, deci ea trebuie să fie unică"),
    "last_dir": ("err", "Trebuie să rămână cel puțin un director — altfel nimeni nu mai "
                        "poate deschide Setările și nu are cine să dea drepturi înapoi"),
    "self_user": ("err", "Nu vă puteți șterge propriul cont — cereți altui director"),
    "ok_doc": ("ok", "Document încărcat — rămâne local, în folderul programului"),
    "bad_doc": ("err", "Fișier gol sau prea mare (max 25 MB)"),
    "ok_med": ("ok", "Datele medicului au fost salvate"),
    "bad_med": ("err", "Date invalide — verificați câmpurile medicului"),
    "new_med": ("ok", "Medic adăugat — completați fișa lui"),
    "dup_med": ("err", "Există deja un medic cu acest nume — numele trebuie să fie unic"),
    "ok_photo": ("ok", "Fotografia a fost salvată — rămâne local, lângă program"),
    "bad_photo": ("err", "Doar JPEG / PNG / WebP, până la 5 MB"),
    "ok_svc_med": ("ok", "Serviciile medicului au fost actualizate"),
    "svc_empty": ("err", "Fiecare serviciu trebuie să rămână cu cel puțin un medic "
                         "ACTIV — altfel nu mai poate fi ales la programare. Bifați alt medic "
                         "(sau readuceți unul din concediu) înainte de a-l scoate pe acesta"),
    "save_err": ("err", "Nu am putut scrie fișierul clinicii (clinic.json) — datele NU "
                        "au fost salvate. Verificați spațiul pe disc și drepturile la "
                        "folderul programului; detalii în data\\dentpilot.log"),
    "arch_busy": ("err", "Medicul are programări viitoare — mutați-le la alt medic sau "
                         "alegeți «în concediu» în loc de arhivare"),
    "last_med": ("err", "Trebuie să rămână cel puțin un medic activ"),
    "ok_anam": ("ok", "Anamneza a fost salvată"),
    "bad_anam": ("err", "Anamneza nu a fost salvată — bifați ce se potrivește "
                        "sau completați cel puțin un câmp"),
    "ok_visit": ("ok", "Consultația a fost salvată"),
    "bad_visit": ("err", "Consultația nu a fost salvată — completați cel puțin "
                         "un câmp"),
    "bad_vst": ("err", "Vizita anulată sau neprezentată nu poate avea "
                       "consultație — schimbați mai întâi statusul vizitei"),
}


def msg_banner(msg: str) -> str:
    """Ответ на действие (?msg=… из 303) — плавающей плашкой поверх окна.

    Жалоба клиники (08-14): форма записи стоит ВНИЗУ страницы, редирект
    открывает её заново с нулевой прокруткой, и баннер в потоке оставался за
    кадром — регистратура прочла «ничего не произошло» там, где журнал ответил
    «интервал занят». Плашка позиционируется фиксированно (panel.css,
    .toastbox), поэтому видна с любой прокрутки; panel.js вешает крестик,
    автозакрытие успеха и убирает msg из адреса, чтобы F5 и автообновление
    не показывали тот же ответ заново.

    ⭐ Единственное место, где код из MSG_BANNER становится разметкой (держит
    test_structure): модуль, собравший баннер сам, вернул бы сообщение в поток
    — и на коротких страницах разработчика это невидимо. Баннеры-СОСТОЯНИЯ
    («Zi liberă», шаблонные данные, сигнализация auth.json) остаются в потоке
    намеренно: они описывают страницу, а не отвечают на действие, и висеть
    поверх расписания весь день им нельзя.
    """
    if msg not in MSG_BANNER:
        return ""
    cls, text = MSG_BANNER[msg]
    # err — role=alert: экранный диктор объявляет отказ сразу, остальное — status
    role = "alert" if cls == "err" else "status"
    return (f"<div class='toastbox' id='dp_toast' data-kind='{cls}' role='{role}'>"
            f"<div class='banner {cls}'>{text}"
            f"<button class='t-x' type='button' aria-label='Închide'>"
            f"{_ic('close')}</button></div></div>")


def _banner(msg: str, d: date) -> str:
    out = msg_banner(msg)
    if not eng.hours_for(d):
        # у клиники без бота упоминание бота в баннере — загадка, не подсказка
        tail = " (bot-ul nu oferă această zi)" if tg_configured() else ""
        out += f"<div class='banner err'>Zi liberă — clinica este închisă{tail}</div>"
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
    # Плитки настроек (08-10). До этого там стояли эмодзи, и они — главный
    # признак «непремиального» интерфейса после шрифта: рисует их Windows, на
    # 10 и 11 по-разному, всегда цветными посреди строгого экрана и всегда не в
    # том весе. ⭐ Эти же иконки наследуют currentColor, то есть перекрашиваются
    # темой клиники сами; эмодзи оставались зелёными на фиолетовой теме.
    "info": "<circle cx='12' cy='12' r='9'/><path d='M12 11v5.5'/>"
            "<circle cx='12' cy='7.8' r='1' fill='currentColor' stroke='none'/>",
    "clinic": "<path d='M4 20.5V9l8-5 8 5v11.5'/><path d='M3 20.5h18'/>"
              "<path d='M12 8.5v4M10 10.5h4'/><path d='M9.5 20.5v-4.5h5v4.5'/>",
    "palette": "<path d='M12 3a9 9 0 1 0 0 18c1 0 1.7-.8 1.7-1.7 0-.5-.2-.9-.5-1.2-.3-.3-.5-.7-.5-1.1 0-.9.8-1.7 1.7-1.7H16a5 5 0 0 0 5-5c0-4-4-7.3-9-7.3z'/>"
               "<circle cx='7.5' cy='11' r='1.1' fill='currentColor' stroke='none'/>"
               "<circle cx='11' cy='7.5' r='1.1' fill='currentColor' stroke='none'/>"
               "<circle cx='15.5' cy='8.5' r='1.1' fill='currentColor' stroke='none'/>",
    "clock": "<circle cx='12' cy='12' r='9'/><path d='M12 7v5.3l3.4 2'/>",
    "tooth": "<path d='M12 3.2c-1.6 0-2.4.8-4 .8-2.2 0-3.8 1.6-3.8 4.2 0 2 .7 3.2 1.2 5 .5 1.9.5 3.3.9 5.3.3 1.5.9 2.3 1.8 2.3 1.1 0 1.4-1.1 1.7-2.8.3-1.7.5-3.5 2.2-3.5s1.9 1.8 2.2 3.5c.3 1.7.6 2.8 1.7 2.8.9 0 1.5-.8 1.8-2.3.4-2 .4-3.4.9-5.3.5-1.8 1.2-3 1.2-5 0-2.6-1.6-4.2-3.8-4.2-1.6 0-2.4-.8-4-.8z'/>",
    "wifi": "<path d='M4.5 9.5a12 12 0 0 1 15 0M7.5 13a7.5 7.5 0 0 1 9 0'/>"
            "<circle cx='12' cy='17.5' r='1.3' fill='currentColor' stroke='none'/>",
    "save": "<path d='M5 3.5h11L20.5 8v12.5a1 1 0 0 1-1 1h-14a1 1 0 0 1-1-1v-16a1 1 0 0 1 1-1z'/>"
            "<path d='M8 3.5v6h8v-6M8 21.5V15h8v6.5'/>",
    "lock": "<rect x='4.5' y='10.5' width='15' height='10' rx='2.5'/>"
            "<path d='M8 10.5V7.8a4 4 0 0 1 8 0v2.7'/>",
    "help": "<circle cx='12' cy='12' r='9'/>"
            "<path d='M9.6 9.4A2.5 2.5 0 0 1 14.5 10c0 1.7-2.5 2-2.5 3.8'/>"
            "<circle cx='12' cy='17' r='1' fill='currentColor' stroke='none'/>",
    "users": "<circle cx='9.5' cy='8.5' r='3.2'/>"
             "<path d='M3.5 20c1-3.2 3.4-4.6 6-4.6s5 1.4 6 4.6'/>"
             "<path d='M16.5 6.2a3.2 3.2 0 0 1 0 6M17.5 15.8c1.6.7 2.7 2 3.3 4.2'/>",
    # заголовки FAQ (08-10)
    "box": "<path d='M3.5 7.5 12 3.5l8.5 4v9L12 20.5l-8.5-4z'/>"
           "<path d='M3.5 7.5 12 11.6l8.5-4.1M12 11.6v8.9'/>",
    "refresh": "<path d='M20 12a8 8 0 1 1-2.4-5.7'/><path d='M20.5 3.5v4h-4'/>",
    "key": "<circle cx='8' cy='12' r='4.2'/><path d='M12.2 12H21M18 12v3.2M15.2 12v2.4'/>",
    "scales": "<path d='M12 4v16M7 20h10M12 6.5 5 9M12 6.5 19 9'/>"
              "<path d='M2.5 13.2 5 8.6l2.5 4.6a2.6 2.6 0 0 1-5 0z'/>"
              "<path d='M16.5 13.2 19 8.6l2.5 4.6a2.6 2.6 0 0 1-5 0z'/>",
    "folder": "<path d='M3.5 6.5a1.5 1.5 0 0 1 1.5-1.5h4l2 2.5h8a1.5 1.5 0 0 1 1.5 1.5v9a1.5 1.5 0 0 1-1.5 1.5H5a1.5 1.5 0 0 1-1.5-1.5z'/>",
    # Плитки сводки и статистики (08-11). Раньше тут стояли эмодзи, а их рисует
    # САМА Windows: своим шрифтом, по-разному на 10 и 11, всегда цветными и мимо
    # выбранного клиникой цвета. Подложка плитки уже задаёт `color`, поэтому
    # stroke-иконка на currentColor окрашивается сама — эмодзи так не умел.
    "headset": "<path d='M4 14v-2.5a8 8 0 0 1 16 0V14'/>"
               "<rect x='2.5' y='13' width='4.5' height='6.5' rx='2.2'/>"
               "<rect x='17' y='13' width='4.5' height='6.5' rx='2.2'/>",
    "alarm": "<circle cx='12' cy='13.5' r='7.5'/><path d='M12 9.5v4l2.5 1.5'/>"
             "<path d='M5 4.5 2.5 7M19 4.5 21.5 7'/>",
    "ban": "<circle cx='12' cy='12' r='8.5'/><path d='m6 6 12 12'/>",
    "trend": "<path d='M3.5 16.5 9 11l3.5 3.5 8-8'/><path d='M15.5 6.5h5v5'/>",
    "bell": "<path d='M18 16.5V11a6 6 0 1 0-12 0v5.5L4.5 19h15z'/>"
            "<path d='M10 19.5a2 2 0 0 0 4 0'/>",
    "checkin": "<circle cx='12' cy='12' r='8.5'/><path d='m8 12 2.8 2.8L16.2 9.4'/>",
    "power": "<path d='M12 3.5v8'/><path d='M7.2 6.6a8 8 0 1 0 9.6 0'/>",
    "chat": "<path d='M20.5 12.2c0 3.9-3.8 7-8.5 7-1 0-2-.15-2.9-.42L4 20.5l1.4-3.7"
            "A6.6 6.6 0 0 1 3.5 12.2c0-3.9 3.8-7 8.5-7s8.5 3.1 8.5 7z'/>",
    # ◀ ▶ ▲ ▼ навигации и трендов: те же системные знаки, что и эмодзи —
    # U+25B2…25C0 не входят ни в одно вшитое подмножество Inter.
    "chev-l": "<path d='m14.5 5.5-7 6.5 7 6.5'/>",
    "chev-r": "<path d='m9.5 5.5 7 6.5-7 6.5'/>",
    "chevs-l": "<path d='m11 6-6 6 6 6M18.5 6l-6 6 6 6'/>",
    "chevs-r": "<path d='m13 6 6 6-6 6M5.5 6l6 6-6 6'/>",
    "caret-u": "<path d='m5.5 15 6.5-7 6.5 7' fill='currentColor'/>",
    "caret-d": "<path d='m5.5 9 6.5 7 6.5-7' fill='currentColor'/>",
    # маркеры записей в сетке журнала и подписи под ней
    "note": "<path d='M4.5 4.5h11l4 4v11h-15z'/><path d='M15 4.5v4.5h4.5M8 13h8M8 16.5h5'/>",
    "pen": "<path d='M4 20h4L19.2 8.8a2.1 2.1 0 0 0-3-3L5 17v3z'/><path d='M14.8 6.2l3 3'/>",
    "sos": "<path d='M12 3.2 21 19.4H3z'/><path d='M12 9.4v4.2M12 16.6h.01'/>",
    "hourglass": "<path d='M7 3.5h10M7 20.5h10'/><path d='M8 3.5c0 4 4 5.2 4 8.5s-4 4.5-4 8.5'/>"
                 "<path d='M16 3.5c0 4-4 5.2-4 8.5s4 4.5 4 8.5'/>",
    "excl": "<path d='M12 5.5v9'/><path d='M12 18.5h.01'/>",
    "user": "<circle cx='12' cy='8' r='3.5'/><path d='M5 20.5c1.3-3.8 4-5.4 7-5.4s5.7 1.6 7 5.4'/>",
    "download": "<path d='M12 3.5v11'/><path d='m7.5 10.5 4.5 4.5 4.5-4.5'/><path d='M4.5 20h15'/>",
    "clipboard": "<rect x='5' y='4.5' width='14' height='16' rx='2.5'/>"
                 "<path d='M9 4.5V3.2h6v1.3'/><path d='M8.5 11h7M8.5 15h5'/>",
    "close": "<path d='m6 6 12 12M18 6 6 18'/>",
    "check": "<path d='M20 6 9 17l-5-5'/>",
    "pill": "<rect x='2.6' y='8.6' width='18.8' height='6.8' rx='3.4' transform='rotate(-45 12 12)'/><path d='m9.2 9.2 5.6 5.6'/>",
    "file": "<path d='M6 3.5h7.5L19 9v11.5H6z'/><path d='M13.5 3.5V9H19'/>",
    "xray": "<rect x='4' y='3.5' width='16' height='17' rx='2.5'/><path d='M12 7v10M8.5 9.5c2 1 5 1 7 0M8.5 14.5c2-1 5-1 7 0'/>",
    # летопись карточки пациента: у каждого рода события свой значок
    "plus": "<path d='M12 5v14M5 12h14'/>",
    "minus": "<path d='M5 12h14'/>",
    "clip": "<path d='M20 11.5 12.4 19a4.6 4.6 0 0 1-6.5-6.5l7.8-7.8a3 3 0 0 1 4.3 4.3"
            "l-7.8 7.8a1.5 1.5 0 0 1-2.1-2.1l7.1-7.1'/>",
    "trash": "<path d='M4.5 6.5h15M9.5 6.5V4.2h5v2.3'/>"
             "<path d='M6.5 6.5 7.5 20h9l1-13.5'/><path d='M10.5 10v6M13.5 10v6'/>",
    "eye": "<path d='M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z'/>"
           "<circle cx='12' cy='12' r='3'/>",
    "print": "<path d='M7 8.5V3.5h10v5'/><rect x='3.5' y='8.5' width='17' height='8' rx='2'/>"
             "<path d='M7 14h10v6.5H7z'/>",
    "erase": "<path d='m9 20.5-5-5a1.8 1.8 0 0 1 0-2.6l8-8a1.8 1.8 0 0 1 2.6 0l5 5"
             "a1.8 1.8 0 0 1 0 2.6l-8 8z'/><path d='M9 20.5h11M7 12.5l7 7'/>",
    # карточка пациента: деньги, документы, действия плана
    "money": "<circle cx='12' cy='12' r='8.5'/><path d='M12 7.5v9M14.4 9.8c-.5-.8-1.4-1.2"
             "-2.4-1.2-1.4 0-2.4.8-2.4 1.9s1 1.6 2.4 1.9 2.4.8 2.4 1.9-1 1.9-2.4 1.9"
             "c-1 0-1.9-.4-2.4-1.2'/>",
    "cash": "<rect x='2.5' y='6' width='19' height='12' rx='2'/><circle cx='12' cy='12' r='2.6'/>"
            "<path d='M6 9.5v5M18 9.5v5'/>",
    "card": "<rect x='2.5' y='5.5' width='19' height='13' rx='2.5'/><path d='M2.5 10h19'/>"
            "<path d='M6 14.5h3'/>",
    "bank": "<path d='M3.5 9.5 12 4l8.5 5.5'/><path d='M5.5 9.5v8M10 9.5v8M14 9.5v8M18.5 9.5v8'/>"
            "<path d='M3.5 20.5h17'/>",
    "camera": "<rect x='3' y='7' width='18' height='13' rx='2.5'/><circle cx='12' cy='13.5' r='3.4'/>"
              "<path d='M8.5 7 10 4.5h4L15.5 7'/>",
    "monitor": "<rect x='2.8' y='4' width='18.4' height='12.5' rx='2'/>"
               "<path d='M9 20.5h6M12 16.5v4'/>",
    "upload": "<path d='M12 20.5v-11'/><path d='m7.5 13.5 4.5-4.5 4.5 4.5'/><path d='M4.5 4h15'/>",
    "play": "<path d='M8 5.5 18.5 12 8 18.5z'/>",
    "undo": "<path d='M4 9.5h10a5 5 0 0 1 0 10h-4'/><path d='m8 5.5-4 4 4 4'/>",
    # молочный прикус: бутылочка — тот же знак, что был эмодзи 🍼
    "door": "<path d='M6 3.5h12v17H6z'/><circle cx='14.5' cy='12' r='1' fill='currentColor' stroke='none'/>",
    "out": "<path d='M14 4.5h5.5V10'/><path d='m19.5 4.5-8 8'/>"
           "<path d='M18 14v5.5H4.5V6H10'/>",
    "milk": "<path d='M8.5 8.5h7l.8 11a1.8 1.8 0 0 1-1.8 2h-5a1.8 1.8 0 0 1-1.8-2z'/>"
            "<path d='M9.5 5.5h5l-.5 3h-4z'/><path d='M8.8 13h6.4'/>",
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


def tg_refresh_meta() -> None:
    """Пнуть визитку бота (описание в профиле Telegram) после сохранения
    настроек — имя/телефон/орар должны догнать clinic.json. Тот же принцип,
    что tg_status: без импорта адаптера; бот не запущен — no-op."""
    mod = sys.modules.get(f"{_APP_PKG}.telegram")
    if mod is not None:
        mod.refresh_meta()


def _tg_state() -> tuple[bool, str]:
    """Короткий ответ для сайдбара: (работает ли, username)."""
    st = tg_status()
    return bool(st["running"]), st.get("username", "")


def tg_configured() -> bool:
    """Telegram ЗАМОРОЖЕН (08-08, фидбек клиник: «QR на двери = запись для
    любого» — канал не продаёт; курс на SMS-пакет). Интерфейс бота видят
    только клиники, у которых токен УЖЕ настроен: работающее не отнимаем,
    новым не предлагаем. UNREADABLE-флаг тоже считается «настроен» — после
    переезда на другой ПК клиника должна ВИДЕТЬ раздел, чтобы ввести токен
    заново, а не гадать, куда он делся."""
    return bool(os.environ.get("TELEGRAM_TOKEN", "").strip()) \
        or dpapi.UNREADABLE_FLAG in os.environ


def _update_banner() -> str:
    if upd.can_self_update():
        # в desktop-версии баннер ведёт к кнопке «Actualizează acum», не на GitHub
        return (f" · <a href='/admin/settings/system' "
                f"style='color:#e8710a;font-weight:600'>{_ic('refresh')} versiune nouă "
                f"{html.escape(upd.STATE['latest'])} — click pentru actualizare</a>")
    if upd.asset_pending() and upd.is_desktop():
        # релиз есть, файла в нём ещё нет — честно говорим и НЕ шлём на GitHub
        return (f" · <span style='color:var(--text3)'>{_ic('refresh')} {html.escape(upd.STATE['latest'])} "
                f"se pregătește…</span>")
    if upd.newer_available():
        return (f" · <a href='{html.escape(upd.STATE['url'])}' target='_blank' "
                f"style='color:#e8710a;font-weight:600'>{_ic('refresh')} versiune nouă "
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
            "Ele apar în programul de lucru, în formulare și pe documentele tipărite.</div>")


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
    return (f"<div class='banner err' style='margin-bottom:14px'>{_ic('shield')} {html.escape(txt)}. "
            "Dacă nu a fost o intervenție cunoscută (resetarea unui PIN uitat, "
            "tehnicianul clinicii), schimbați PIN-urile în Setări › Utilizatori "
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
    show_docs = can(me, PERM_DOCTORS) or me is None

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
    # Секция «Sincronizări» — только у клиник с уже настроенным ботом
    # (grandfather): Telegram заморожен, см. tg_configured. Прямой адрес
    # /admin/settings/telegram остаётся живым — включить бота вручную можно.
    sync = ""
    foot_title = ""
    if tg_configured():
        sync = ('<div class="sec">Sincronizări</div>'
                + item('tg', '/admin/settings/telegram' if show_set else '',
                       'bot', 'Telegram Bot', tg_dot)
                + item('qr', '/admin/qr-print', 'qr', 'QR pacienți'))
        foot_title = f' title="Telegram: {html.escape(tg_title)}"'
    return f"""<aside class="side">
  <div class="brand">{brand.mark_svg(32, 'logo', flat=True)}
    <div class="txt"><b title="{html.escape(eng.CLINIC_NAME)}">{html.escape(eng.CLINIC_NAME)}</b><small>DentPilot</small></div>
  </div>
  <nav>
    <div class="sec">Meniu</div>
    {item('dash', '/admin', 'home', 'Dashboard')}
    {item('prog', '/admin/all', 'cal', 'Programări')}
    {item('pat', '/admin/search', 'pat', 'Pacienți')}
    {item('med', '/admin/medici', 'med', 'Medici') if show_docs else ''}
    {item('stat', '/admin/stats', 'stat', 'Statistici') if show_money else ''}
    {item('set', '/admin/settings', 'set', 'Setări') if show_set else ''}
    {sync}
  </nav>
  <div class="sfoot"{foot_title}>v{eng.APP_VERSION} · <span id="sf_clock" data-tz="{eng.TZ.key}"></span></div>
</aside>"""


def _topbar(bell: int | None) -> str:
    bell_html = ""
    if bell is not None:
        badge = f"<span class='n'>{bell}</span>" if bell else ""
        # ведёт к блоку «Programări noi din bot» (по created_at) — а не к дневному
        # фильтру: бронь на неделю вперёд должна быть в одном клике (урок демо 07-31)
        bell_html = (f"<a class='bell' href='/admin#botnew' "
                     f"title='Programări noi din bot'>{_ic('bell')}{badge}</a>")
    today = datetime.now(eng.TZ).date().isoformat()
    return f"""<div class="top">
  <form class="searchf" method="get" action="/admin/search">
    <input id="topq" name="q" placeholder="Caută pacient, telefon…" autocomplete="off">
    <span class="kbd">Ctrl K</span><button>{_ic('search')}</button>
  </form>
  <div style="flex:1"></div>
  <span style="font-size:12px;color:var(--text3)">{_update_banner().removeprefix(' · ')}</span>
  {bell_html}
  <a class="newbtn" href="/admin/all?date={today}#addform"><span class="plus">+</span><span class="nb-t">Programare nouă</span></a>
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
            f"<a class='who-out' href='/admin/logout' title='Ieșire din cont'>{_ic('power')}</a>"
            f"</div>")


# Кто перезагружает себя сам — СЕКУНДЫ в data-reload на <body>, panel.js
# слушается атрибута. Живым обязано быть только расписание (панель, день,
# неделя, день врача): бронь из бота должна появиться, пока журнал висит
# открытым на стойке. Остальным страницам перезагрузка не даёт НИЧЕГО и
# отнимает состояние — раскрытые <details> FAQ, позицию прокрутки (находка
# Олега 08-07: «вкладка закрывается сама» — третий случай одной болезни после
# предпросмотра 1.13.2 и анимаций). Новая страница расписания = её active сюда.
LIVE_RELOAD = {"dash", "prog"}

# Страницы, которым отдаётся ВСЯ ширина окна (08-12, просьба Олега на четырёх
# врачах). `.content` ограничена 1500px — на широком мониторе это оставляло
# ~200px пустыми справа, и они уходили не абы куда, а из колонки врача: сетка
# делит остаток между врачами, поэтому четвёртый врач сузил все четыре.
# ⚠️ Снимать потолок ВЕЗДЕ нельзя: на странице текста (настройки, FAQ, фиша)
# строка в 1700px не читается — 1500 стоит там ровно за этим.
# ⛔ Набор совпадает с LIVE_RELOAD случайно, а не по правилу: одно про «страница
# живая», другое про «странице нужна ширина». Сливать их нельзя — новая живая
# страница молча стала бы широкой.
WIDE_PAGES = {"dash", "prog"}


def _shell(body: str, sub: str, active: str = "dash", bell: int | None = None) -> str:
    fb_subject = urllib.parse.quote(
        f"Feedback DentPilot — {eng.CLINIC_NAME} (v{eng.APP_VERSION})")
    fb_body = urllib.parse.quote("Ideea / problema mea:\n\n")
    reload_attr = ' data-reload="12"' if active in LIVE_RELOAD else ""
    # Тема клиники приезжает СТРОКОЙ в шапке, а не переписывает panel.css:
    # таблица вшита в exe (только чтение), отдаётся с вечным кешем и одна на
    # все клиники. Порядок обязателен — <style> ПОСЛЕ ссылки, иначе он не
    # перебьёт :root. Цвет полосы браузера берётся из того же стиля: на
    # телефоне врача она занимает верх экрана и осталась бы от прежней темы.
    th = theme.current()
    th_css = theme.vars_css()
    th_bg = theme.STYLES[th["style"]]["--bg"]
    # ⚠️ В <h1> имени клиники НЕТ намеренно (08-09): оно и так на экране дважды —
    # в подписи сайдбара и в чипе вошедшего («роль · клиника»), а строка
    # «Clinica mea — registrul clinicii» съедала ширину ради третьего повтора.
    # Заголовок один на ВСЕ страницы (имя раздела живёт в .sub, см. _sec_page),
    # поэтому он называет ПРОГРАММУ, а не страницу — и обязан быть коротким.
    # В <title> окна имя клиники остаётся: там оно различает установки в панели
    # задач, а не повторяет соседний элемент.
    return f"""<!doctype html><html lang="ro" data-style="{th['style']}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="{th_bg}">
<link rel="icon" type="image/svg+xml" href="/favicon.ico">{pwa_head()}
<title>{html.escape(eng.CLINIC_NAME)} — registru</title>
<link rel="stylesheet" href="/static/css/fonts.css?v={_asset_ver('css', 'fonts.css')}">
<link rel="stylesheet" href="/static/css/panel.css?v={_asset_ver('css', 'panel.css')}">
<style>{th_css}</style>
<script>/* Оживлять цифры и полосы можно только при ОСМЫСЛЕННОМ открытии страницы.
Журнал перезагружает себя каждые 12 секунд (panel.js), и без этого выключателя
KPI пересчитывались бы на глазах весь рабочий день, а регистратура читала бы
бегущие цифры вместо расписания. panel.js перед автоперезагрузкой ставит флаг,
здесь он снимается — и класс `anim` не выдаётся.
ВАЖНО: скрипт обязан стоять В ШАПКЕ — класс нужен ДО первой отрисовки, иначе виден
кадр с конечным состоянием, и анимация выглядит рывком назад. Всё оформление
привязано к `.anim`, поэтому без JS страница просто статична — не пуста. */
try{{if(sessionStorage.getItem('dp_auto')==='1'){{sessionStorage.removeItem('dp_auto');}}
else{{document.documentElement.classList.add('anim');}}}}catch(e){{document.documentElement.classList.add('anim');}}
</script></head><body{reload_attr}>
{_sidebar(active)}
<div class="main">
{_topbar(bell)}
<div class="content{' wide' if active in WIDE_PAGES else ''}">
<h1><a href="/admin">Registrul Clinicii</a></h1>
<div class="sub">{sub}{_sec_warn()} · v{eng.APP_VERSION}</div>
{_tamper_banner()}{_setup_hint()}
{body}
</div></div>
<div class="brandcorner">{_ic('tooth')} <b>DentPilot</b> ·
<a href="mailto:{FEEDBACK_EMAIL}?subject={fb_subject}&body={fb_body}"
   title="{FEEDBACK_EMAIL}">{_ic('chat')} Feedback</a></div>
<script src="/static/js/panel.js?v={_asset_ver('js', 'panel.js')}"></script>
</body></html>"""


# ⭐ Плашка обязана называть статус ТЕМ ЖЕ словом, что и кнопка, которая его
# ставит. До 08-12 «Finalizat» переводил запись в «a venit» — это словарь
# СТАТИСТИКИ, где «Au venit» = пришли и считаются done ВМЕСТЕ с arrived. В
# журнале он отвечал не на тот вопрос: рядом с нажатой кнопкой «Finalizat»
# стояло «a venit», в повестке та же запись звалась «Finalizat», а в летописи
# пациента (db._STATUS_RO) — «finalizată». Одно состояние, три имени.
# ⭐ 08-16 своего словаря у db не осталось вовсе: он расходился и дальше —
# кнопка ставила «nu a venit», а летопись писала «neprezentare». Теперь
# `db.set_status` берёт слово ОТСЮДА отложенным импортом (на уровне модуля был
# бы круг: layout импортирует db). Новый статус называется здесь и нигде более.
# ⚠️ Отсюда же берёт текст повестка дня (_AG_CLS в schedule/routes.py): новый
# статус называется ЗДЕСЬ и нигде больше.
STATUS_LABEL = {
    "confirmed": "confirmată",
    # 08-13, вопрос Олега: «a sosit» ставили в момент ПРИХОДА, а называлось
    # это «în cabinet» — статус десять минут утверждал то, чего ещё нет.
    # Теперь конвейер честный: пришёл (waiting) → в кабинете (arrived).
    # ⚠️ «a venit» и «nu a venit» — соседи-близнецы: слово нигде не выводится
    # без цвета/иконки (waiting — фиолетовый, noshow — красный).
    "waiting": "a venit",
    "arrived": "în cabinet",
    "done": "finalizată",
    "noshow": "nu a venit",
    "cancelled": "anulată",
}


# статусы, при которых слот занят — единый источник правды в db.py
LIVE_STATUSES = db.ACTIVE_STATUSES


# Тот же приём, что у STATUS_LABEL, для остальных кодов, которые видит человек.
# Оба словаря переехали сюда из modules/patients/routes.py, когда выгрузке по
# 195-му понадобились те же слова: копия данных обязана быть «в понятной
# форме», а импортировать routes.py она не может — routes.py импортирует её.
# ⚠️ Новый вид предупреждения или новый источник записи называется ЗДЕСЬ.
ALERT_KINDS = {"allergy": "Alergie", "medication": "Medicație",
               "warning": "Atenție", "info": "Info"}
# источник визита: рецепция завела руками или пациент записался сам
SOURCE_LABEL = {"manual": "recepție", "bot": "online", "note": "notă"}


def dmy(value) -> str:
    """Дата человеку — dd.mm.yyyy, а не сырой ISO из базы.

    ⚠️ Переводится в пояс клиники только значение С поясом: `birth_date` и
    `due_date` лежат ГОЛЫМИ датами (текст «1990-05-06»), и astimezone на
    наивном значении подставил бы пояс машины и сдвинул ДЕНЬ.
    Пустое остаётся пустым: печатные листы рисуют на этом месте жёлтый
    пропуск под ручку, а таблицы — прочерк, и решают это они, не эта функция.
    """
    if not value:
        return ""
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(eng.TZ)
        return value.strftime("%d.%m.%Y")
    try:
        return date.fromisoformat(str(value)[:10]).strftime("%d.%m.%Y")
    except ValueError:
        return str(value)


def _age(birth_year) -> int | None:
    if not birth_year:
        return None
    return datetime.now(eng.TZ).year - int(birth_year)


# ⚠️ Страницы ниже НЕ подключают panel.css и не будут. Экран входа — первое,
# что видит клиника, и он обязан открыться, даже если статика не отдалась;
# экран установки PIN показывается там, где журнала ещё нет вовсе. Значит
# переменных CSS у них нет, и цвет клиники приезжает сюда ГОТОВЫМИ значениями
# через standalone() — заполнителями __ACCENT__/__ON__/__RING__/__BG__/__LOGO__.
# ⛔ Оттуда же __FONTS__, и он обязателен для каждой страницы, просящей 'Inter':
# объявления шрифта у них своего нет, а panel.css, где оно живёт, не подключена.
# Забытый заполнитель = системный Segoe UI, и это невидимо даже разработчику
# (Inter не установлен ни у кого, страница выглядит «как всегда»).
#
# ⛔ На входе НЕ пишем, как сбросить забытый PIN (было до 08-11: «закройте
# программу и удалите data\\auth.json»). Совет расходился с FAQ, и расходился в
# опасную сторону: FAQ отвечает «пусть второй директор задаст новый пароль, а
# если директор один — напишите нам», а удаление файла сносит ВСЕ учётки и роли
# разом и вдобавок поднимает сигнализацию подмены auth.json — директор получает
# баннер о взломе за то, что выполнил инструкцию с нашего же экрана. Ответ
# живёт в одном месте: Setări → FAQ, «Am uitat parola de intrare».
#
# Заголовок входа — имя клиники и больше ничего. «— registrul clinicii» было
# третьим повтором одного и того же: то же слово стоит в заголовке окна, а над
# формой уже висит знак. Ровно от этого повтора избавились в шапке журнала (см.
# комментарий у топбара выше), здесь он просто дожил дольше.

LOGIN_TMPL = """<!doctype html><html lang="ro"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__CLINIC__ — acces</title><style>__FONTS__
 body{font-family:'Inter','Segoe UI',system-ui,sans-serif;background:__BG__;display:flex;
      align-items:center;justify-content:center;min-height:100vh;margin:0;color:#162033;
      padding:16px;box-sizing:border-box}
 form{background:#fff;padding:30px 32px;border-radius:18px;border:1px solid #E7EDF5;
      /* двухслойная, как --sh3 в panel.css: экран входа — первое, что видит
         клиника, а своей таблицы стилей у него нет (он обязан открываться,
         даже если статика не отдалась) */
      box-shadow:0 3px 6px rgba(15,23,42,.06),0 18px 40px rgba(15,23,42,.10);
      display:flex;flex-direction:column;gap:12px;width:min(340px,100%)}
 /* ВАЖНО: цвет заголовка — __ACCENT_D__, не __ACCENT__: чистый фирменный даёт на
    белой карточке 3.3:1 даже у зелёного по умолчанию, а при светлом выборе
    клиники (жёлтый, голубой) заголовок пропал бы вовсе. Тёмный оттенок
    дотемняется циклом до 4.5 к фону страницы, а карточка ещё светлее фона —
    значит порог выдержан тем более. */
 h1{font-size:19px;color:__ACCENT_D__;margin:0 0 4px;font-weight:600;letter-spacing:-.02em}
 /* логотип клиники — только если она его загрузила; высота ограничена здесь,
    потому что разбирать картинку нечем (Pillow в сборку не едет) */
 .clogo{align-self:center;max-height:64px;max-width:220px;object-fit:contain;margin-bottom:4px}
 /* 16px — не «дизайн», а защита: поле мельче 16px iOS зумит при фокусе */
 input{height:44px;padding:0 14px;border:1px solid #E7EDF5;border-radius:12px;font-size:16px;
       outline:none;color:#162033}
 input:focus{border-color:__ACCENT__;box-shadow:0 0 0 3px __RING__}
 button{background:__ACCENT__;color:__ON__;border:none;border-radius:12px;height:44px;
        font-size:15px;font-weight:600;cursor:pointer;transition:background-color .2s ease}
 button:hover{background:__ACCENT_D__}
 .err{color:#B91C1C;font-size:13px}
</style></head><body>
<form method="post" action="/admin/login">
  __LOGO__
  <h1>__CLINIC__</h1>
  __ERR__
  <input type="hidden" name="next" value="__NEXT__">
  __INPUT__
  <button>Intră</button>
</form></body></html>"""


SETUP_TMPL = """<!doctype html><html lang="ro"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__CLINIC__ — PIN</title><style>__FONTS__
 body{font-family:'Inter','Segoe UI',system-ui,sans-serif;background:__ACCENT__;display:flex;
      align-items:center;justify-content:center;height:100vh;margin:0}
 form{background:#fff;padding:30px 32px;border-radius:18px;
      box-shadow:0 4px 8px rgba(15,23,42,.12),0 22px 50px rgba(15,23,42,.26);
      display:flex;flex-direction:column;gap:12px;width:min(340px,100%)}
 h1{font-size:19px;color:#162033;margin:0;font-weight:600;letter-spacing:-.02em}
 p{color:#7E8B9C;font-size:13px;margin:0;line-height:1.5}
 .clogo{align-self:center;max-height:64px;max-width:220px;object-fit:contain}
 input{padding:12px;border:1px solid #E7EDF5;border-radius:12px;font-size:26px;
       text-align:center;letter-spacing:12px;outline:none;color:#162033}
 input:focus{border-color:__ACCENT__;box-shadow:0 0 0 3px __RING__}
 button{background:__ACCENT__;color:__ON__;border:none;border-radius:12px;height:48px;
        font-size:15px;font-weight:600;cursor:pointer;transition:background-color .2s ease}
 button:hover{background:__ACCENT_D__}
 .err{color:#B91C1C;font-size:13px}
</style></head><body>
<form method="post" action="/admin/setup">
  __LOGO__
  <h1>__CLINIC__</h1>
  <p>Prima pornire: setați un PIN pentru registrul clinicii (4–8 cifre).</p>
  __ERR__
  <input type="password" name="pin1" placeholder="PIN" inputmode="numeric"
         pattern="[0-9]*" maxlength="8" autofocus required>
  <input type="password" name="pin2" placeholder="repetați PIN" inputmode="numeric"
         pattern="[0-9]*" maxlength="8" required>
  <button>Setează PIN</button>
</form></body></html>"""


RECOVER_TMPL = """<!doctype html><html lang="ro"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__CLINIC__ — recuperare</title><style>__FONTS__
 body{font-family:'Inter','Segoe UI',system-ui,sans-serif;background:__BG__;display:flex;
      align-items:center;justify-content:center;min-height:100vh;margin:0;color:#162033;
      padding:16px;box-sizing:border-box}
 form{background:#fff;padding:30px 32px;border-radius:18px;border:1px solid #E7EDF5;
      box-shadow:0 3px 6px rgba(15,23,42,.06),0 18px 40px rgba(15,23,42,.10);
      display:flex;flex-direction:column;gap:12px;width:min(560px,100%)}
 h1{font-size:19px;margin:0;font-weight:600;letter-spacing:-.02em}
 p{color:#5A6875;font-size:13.5px;margin:0;line-height:1.55}
 /* моноширинный и крупный: код переписывают с бумаги, и группы должны
    читаться так же, как они там напечатаны */
 input{font-family:ui-monospace,Consolas,monospace;font-size:16px;letter-spacing:.06em;
       padding:12px 14px;border:1px solid #E7EDF5;border-radius:12px;outline:none;color:#162033}
 input:focus{border-color:__ACCENT__;box-shadow:0 0 0 3px __RING__}
 button{background:__ACCENT__;color:__ON__;border:none;border-radius:12px;height:44px;
        font-size:15px;font-weight:600;cursor:pointer}
 .err{color:#B91C1C;font-size:13px}
 .warn{background:#FFFBEB;color:#B45309;font-size:13px;padding:10px 12px;border-radius:10px}
</style></head><body>
<form method="post" action="/admin/recover">
  <h1>__ICON__ Recuperarea evidenței</h1>
  <p>Baza de date a clinicii este criptată, iar cheia de pe acest calculator nu
  poate fi citită. Se întâmplă după reinstalarea Windows, la schimbarea
  calculatorului sau când programul este pornit de pe alt cont Windows.</p>
  <p><b>Introduceți codul de pe foaia de recuperare</b> — cea tipărită la
  activarea criptării (o găsiți în mapa „Legea 195”, lângă actul BitLocker).</p>
  __ERR__
  <input name="code" placeholder="XXXXXX-XXXXXX-XXXXXX-…" autofocus required
         autocomplete="off" spellcheck="false">
  <button>Deblochează evidența</button>
  <div class="warn">Datele nu au fost modificate. Fără acest cod evidența nu
  poate fi deschisă de nimeni — nici de noi.</div>
</form></body></html>"""
# Иконка подставляется ЗДЕСЬ, а не в шаблоне: у страницы своя вёрстка, поэтому
# шаблон — обычная строка с __ЗАПОЛНИТЕЛЯМИ__, и f-строкой её не сделать (в CSS
# выше фигурных скобок больше, чем текста). `standalone` для этого не годится:
# он общий на три страницы, а ключ нужен одной.
RECOVER_TMPL = RECOVER_TMPL.replace("__ICON__", _ic("key"))


_PWA_ANCHOR = '<meta charset="utf-8">'


def pwa_head() -> str:
    """Теги, которые превращают страницу в «приложение» на телефоне.

    ⚠️ Что здесь правда и что нет, чтобы не обещать лишнего в интерфейсе:
    на iPhone `apple-mobile-web-app-capable` даёт настоящий полноэкранный
    запуск с домашнего экрана и работает ПО HTTP — то есть в сети клиники уже
    сегодня. На Android полноценная установка (WebAPK) требует service worker,
    а тот живёт только в защищённом контексте (https или localhost); в сети
    клиники у нас голый http НАМЕРЕННО, поэтому там значок остаётся ярлыком —
    но с нашим именем и знаком, а не с обрезанным снимком страницы. На
    настольном браузере «установить как приложение» работает независимо от
    всего этого. ⭐ Появится https (туннель, слой 3) — Android доберёт своё
    без единой правки здесь.
    """
    name = html.escape(eng.CLINIC_NAME)
    return ('<link rel="manifest" href="/manifest.webmanifest">'
            '<link rel="apple-touch-icon" href="/icon-180.png">'
            '<meta name="apple-mobile-web-app-capable" content="yes">'
            '<meta name="apple-mobile-web-app-status-bar-style" content="default">'
            f'<meta name="apple-mobile-web-app-title" content="{name}">')


def standalone(tmpl: str) -> str:
    """Подставить в страницу СО СВОЕЙ вёрсткой имя клиники, её цвет, логотип и
    объявление шрифта.

    Одна точка на все такие страницы намеренно: их четыре (вход, установка
    PIN, обновление, перезапуск), они разбросаны по двум модулям, и стоит
    завести подстановку по месту — очередной экран забудут перекрасить, а
    заметит это клиника, у которой единственная зелёная страница посреди
    синей программы. С 08-11 через ту же точку приезжает и `__FONTS__`: ровно
    так эти страницы и разошлись с журналом — шрифт объявлен в panel.css,
    которую они не подключают, и экран входа рисовался системным Segoe UI.

    ⚠️ `__FONTS__` подставляется ПОСЛЕДНИМ: это чужой текст (файл со стилями),
    и попади в него однажды `__ACCENT__`, он не должен быть истолкован."""
    th = theme.current()
    pal = theme.palette(th["primary"], th["style"])
    logo = theme.logo_url()
    # ⚠️ Теги приложения вставляются ПОСЛЕ объявления кодировки, а не в начало
    # <head>: в них едет имя клиники, а браузер обязан узнать кодировку раньше,
    # чем встретит первую не-ASCII букву. Вставка по якорю, а не заполнителем:
    # заполнитель в новом экране просто забудут — ровно то, о чём docstring.
    tmpl = tmpl.replace(_PWA_ANCHOR, _PWA_ANCHOR + pwa_head(), 1)
    return (tmpl.replace("__CLINIC__", html.escape(eng.CLINIC_NAME))
            .replace("__ACCENT_D__", pal["--teal-d"])
            .replace("__ACCENT__", pal["--teal"])
            .replace("__RING__", pal["--teal-ring"])
            .replace("__ON__", pal["--on-teal"])
            .replace("__BG__", theme.STYLES[th["style"]]["--bg"])
            .replace("__LOGO__",
                     f"<img class='clogo' src='{logo}' alt=''>" if logo else "")
            .replace("__FONTS__", fonts_css()))


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



