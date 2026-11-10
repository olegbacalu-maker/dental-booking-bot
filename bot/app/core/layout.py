"""Каркас страницы журнала: модель оболочки для React и голова документа — всё,
что одинаково на КАЖДОМ экране.

С 04.11.2026 layout.py разнесён снизу вверх, и каждый сосед ниже этого файла:
`icons` (значки) → `messages` (ответы на действие, MSG_BANNER) → `labels` (слова
статусов, даты, контакты) → `pages` (страницы со своей вёрсткой) → `banners`
(сигналы оболочки) → `license_pages` (активация лицензии).
Вызывающие по-прежнему берут имена отсюда: `__all__` перечисляет их все, и снимок
держит `tests/test_layout_names.py`. ⛔ Соседи ниже layout на уровне модуля его не
импортируют (держит `test_structure`): это замкнуло бы круг. Новое имя живёт у соседа.
"""
from __future__ import annotations

import html
import json
import urllib.parse
from datetime import datetime

from .. import brand, paths
from .. import engine as eng
from . import sms_loop
from . import theme
from .auth import (PERM_DOCTORS, PERM_MONEY, PERM_RECALL, PERM_SCHEDULE_ALL, PERM_SETTINGS, PERM_SMS,
                   PIN_MAX, ROLE_LABEL, _pin_rec, can, request_user, schedule_scope)
from .icons import _ic
from .messages import msg_banner, msg_json, msg_state, msg_text, msg_view
from .labels import (_age, _doc_hours_text, _DOC_STATE_RO, _DOW_FULL, _DOW_ORDER, _initials, ALERT_KINDS,
                     dmy, FEEDBACK_EMAIL, HOUR_MAX, HOUR_MIN, LIVE_STATUSES, SITE_URL, SOURCE_LABEL,
                     STATUS_LABEL, status_view, SUPPORT_PHONE)
from .pages import _asset, _asset_ver, fonts_css, pwa_head, standalone, STATIC
from .banners import (_backup_banner, _demo_banner, _license_banner, _license_until, _mail_banner,
                      _setup_hint, _slot_banner, _sms_alert, _split_banner, _tamper_banner, _terms_banner,
                      _update_banner, SETUP_HINT)
from .license_pages import license_cont_page, license_page, license_pay_page


__all__ = (
    "_age", "_asset", "_doc_hours_text", "_DOC_STATE_RO", "_DOW_FULL",
    "_DOW_ORDER", "_ic", "_initials", "ALERT_KINDS", "data_folder",
    "dmy", "FEEDBACK_EMAIL", "fonts_css", "HOUR_MAX", "HOUR_MIN",
    "license_cont_page", "license_page", "license_pay_page", "LIVE_STATUSES", "msg_json",
    "msg_state", "msg_text", "msg_view", "react_shell", "SECTION_TITLE",
    "SETUP_HINT", "shell_model", "SOURCE_LABEL", "standalone", "STATIC",
    "STATUS_LABEL", "status_view", "SUPPORT_PHONE",
)


def data_folder() -> str:
    """Настоящий путь к папке КЛИНИКИ — строкой, которую читает человек.
    Пусто, если раскладку никто не задавал (облако, запуск из исходников).

    ⭐ Показываем ФАКТ, а не пересказ раскладки. Папку данных выбирает
    лаунчер (`%ProgramData%\\DentPilot` или `DENTART_DATA_DIR` стенда), и
    текст, который раскладку ПЕРЕСКАЗЫВАЕТ, разойдётся с машиной на следующем
    же переезде (портативная раскладка `portable.flag` так и ушла, 22.10.2026).
    Строка, которую директор сверяет глазами с адресной строкой Проводника,
    не протухает: она приходит оттуда же, куда программа пишет.

    ⛔ Это ФОРМАТТЕР над `paths.data_root()`, а не второй вычислитель пути.
    Соблазн посчитать папку иначе (от `sys.executable`, от `config_path()`,
    от аргумента вызывающего) здесь особенно велик, потому что ответов
    несколько и на настольной машине они совпадают. Разойдутся они у клиники,
    и цена известна заранее: `config_path()` прямо пишет, что второе
    вычисление увезло бы файл в папку, в которую программа при следующем
    запуске не смотрит. Ср. `storage._data_dir()` — такой же делегат.
    """
    root = paths.data_root()
    return str(root) if root is not None else ""


# Экраны, которые сами печатают строку копий (`backup_loop.line()`): баннер
# копий каркаса на них её не дублирует (Олег 02.11, «убрать оба»).
BACKUP_LINE_SCREENS = ("settings_system", "settings_backup")


# ---- React-экраны (DentPilot 2.0, 09-17; интерфейс продукта с 21.09) ----
# ⭐ **REACT_SCREENS — это список РЕАЛИЗОВАННЫХ поверхностей, а не механизм
# выката.** Решение Олега 21.09: программы на целевой машине ещё нет, живых
# профилей нет, сохранять нечего — значит и выката нет. Поверхность, здесь
# названная, отдаётся React ПО УМОЛЧАНИЮ.
# ⛔ Не заводить обратно ни канареечных списков, ни поэтапного включения, ни
# rollout-флагов: сложность, которая обслуживает несуществующих пользователей.
#
# ⚠️ Старого интерфейса у этих экранов больше НЕТ (снят по разделам 12–13.10,
# docs/dentpilot-2/legacy-removal.md; журнал — последним, 13.10): каждый из них
# React при любом профиле. Вместе с журналом ушёл и сам рубильник — `react_on`
# / `react_flag`, читавшие ключ `ui.react` профиля и `?ui=legacy` в адресе:
# спрашивать их стало некому. Ключ в профилях и ссылки «varianta clasică»
# ушли шагом 6 (13.10).
# Имена остаются здесь как список реализованных поверхностей (карта экранов,
# `parity_audit`, стенд монтажа `mount_sweep`).
REACT_SCREENS = frozenset({"recall", "settings_clinic", "doctors_list", "doctor_card",
                           "settings_hub", "settings_lan", "settings_faq",
                           "settings_hours", "settings_services", "settings_templates",
                           "settings_theme",
                           "settings_security", "settings_backup",
                           "settings_crypt", "settings_system", "settings_sms", "stats",
                           "patients_search", "patient_card", "visit", "odontogram",
                           "perio", "schedule_week", "schedule_all",
                           "schedule_doctor",
                           "schedule_dash",
                           # Экран «у кресла» (26.09): старой страницы у него
                           # не было никогда.
                           "chair",
                           # «Registre» (МАКЕТ 10.11, san-registers): регистры
                           # 257/e, 502/e, 501/e и каталог оборудования
                           "registre", "settings_registre"})


# Метка узла React в готовой странице (её печатает `react_shell`).
REACT_MOUNT_MARK = '<div id="root" data-screen="'


# ⭐ Списка «кому отдать ширину окна» здесь БОЛЬШЕ НЕТ (08-16). Он был — два
# ключа, дневные виды, — и остальные разделы оставались с потолком 1500px без
# центрирования: на 27" замер давал 844px пустоты одним куском справа у
# пациентов, врачей, статистики и настроек. Список снят, а не дополнен: ширина
# теперь у самой `.content` (panel.css), потому что ключ ставится в модуле, и
# следующая страница молча родилась бы узкой — а увидел бы это только клиент с
# большим монитором, на 1366 потолок не срабатывает вовсе.
# ⚠️ Ограничение, из-за которого это не однострочник, никуда не делось: ширина
# окна хороша ТАБЛИЦАМ и вредна СПЛОШНОМУ ТЕКСТУ. Потолок переехал к самому
# тексту — переменная `--measure` в panel.css (.hint, .banner, карточка FAQ).
# Новый абзац на новой странице берёт его же, а не заводит своё число.


# Подмножества Inter, которые голова просит заранее (03.10): те два, без
# которых не обходится ни один экран румынского интерфейса. Кириллицу браузер
# просит сам, когда на экране есть русские имена; предзагружать её на каждой
# странице значило бы почти всегда качать лишний файл.
FONT_PRELOAD = ("latin", "latin-ext")


def _doc_head() -> str:
    """<head> страницы журнала (печатает `react_shell`).

    ⭐ Порядок `panel.css` → `<style>` темы и положение скрипта `anim` в шапке
    ломаются без единой ошибки на экране — менять осторожно. (Второй
    отправитель головы, серверный каркас `_shell`, снят 03.11.2026 вместе со
    страницами Telegram-бота.)
    """
    th = theme.current()
    th_css = theme.vars_css()
    th_bg = theme.STYLES[th["style"]]["--bg"]
    # ⭐ Шрифт просится ВМЕСТЕ со стилями (03.10). Иначе браузер узнаёт о файле,
    # только когда раскладка встретит текст, — уже после бандла, — и на быстром
    # экране ответ данных обгоняет шрифт: кадр содержимого раскладывался
    # запасным шрифтом и перекладывался по приезде файла (стенд shift_sweep,
    # «Securitate»). Гарантию на медленной сети держит ожидание у загрузчика
    # экрана — frontend/src/services/fonts.ts; здесь — чтобы ждать было нечего.
    # ⚠️ crossorigin обязателен: @font-face грузит файл в режиме CORS, и
    # предзагрузка без него с запросом не совпала бы — шрифт скачался бы дважды.
    # Адреса — те же, что в src у fonts.css (сверяет test_admin). Системному
    # шрифту темы файлы не нужны вовсе.
    pre = "".join(f'\n<link rel="preload" href="/static/fonts/inter-{s}.woff2" '
                  'as="font" type="font/woff2" crossorigin>'
                  for s in FONT_PRELOAD) if th["font"] == "inter" else ""
    return f"""<!doctype html><html lang="ro" data-style="{th['style']}" data-card="{th['card']}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="{th_bg}">
<link rel="icon" type="image/svg+xml" href="/favicon.ico">{pwa_head()}
<title>{html.escape(eng.CLINIC_NAME)} — registru</title>
<link rel="stylesheet" href="/static/css/fonts.css?v={_asset_ver('css', 'fonts.css')}">{pre}
<link rel="stylesheet" href="/static/css/panel.css?v={_asset_ver('css', 'panel.css')}">
<style>{th_css}</style>
<script>/* Класс `anim` — входные анимации цифр и полос при открытии страницы.
ВАЖНО: скрипт обязан стоять В ШАПКЕ — класс нужен ДО первой отрисовки, иначе виден
кадр с конечным состоянием, и анимация выглядит рывком назад. Всё оформление
привязано к `.anim`, поэтому без JS страница просто статична — не пуста.
(Флаг `dp_auto`, которым panel.js гасил анимацию на 303-повторе, ушёл вместе с
panel.js 03.11.2026: React-экраны перезагрузок не делают.) */
document.documentElement.classList.add('anim');
</script></head>"""


# Подписи разделов — ОДИН словарь для пунктов меню и для заголовка страницы
# (B5, шаг 10): разойдись они, меню звало бы раздел одним словом, а страница —
# другим. Ключи — значения `active`; страница вне меню (например, у роли без
# этого пункта) получает имя программы.
# «Panoul principal», не «Dashboard» — слово Олега 26.09 при показе заголовков.
SECTION_TITLE = {"dash": "Panoul principal", "prog": "Programări", "pat": "Pacienți",
                 "med": "Medici", "stat": "Statistici", "set": "Setări",
                 # «Rechemări» (29.10): список отзыва пациентов, сразу после «Pacienți»
                 "rec": "Rechemări",
                 # «Registre» (МАКЕТ 10.11): санитарные регистры — у ВСЕХ вошедших
                 "reg": "Registre",
                 # SMS-пакет (S6): пункт секции «Sincronizări», когда сервер предлагает пакет
                 "sms": "SMS pacienți"}


def section_title(active: str) -> str:
    return SECTION_TITLE.get(active, "DentPilot")


def shell_model(active: str, sub: str, rail: bool = False,
                msg: str = "",
                crumbs: list | None = None, title: str = "") -> dict:
    """Оболочка ДАННЫМИ — модель, по которой React рисует каркас (B1).

    ⭐ Живёт в layout, а не в своём модуле: ей нужны `auth`, `theme`,
    `brand` и сами баннеры, и вынос замкнул бы круг импортов.

    ⛔ Права приезжают РАЗРЕШЁННЫМИ (`can.money`), а не таблицей `PERMS`:
    таблица приглашает клиента вычислять право самому, булев ответ — не
    приглашает. И скрытый пункт меню — по-прежнему УДОБСТВО, а не защита:
    отказ выдаёт `require()` в самом маршруте, потому что адрес набирается
    руками, а роль читается из файла по id, чтобы понижение действовало сразу.

    ⚠️ Текст сигналов остаётся серверной прозой (идиома `lan.py`, `crypt.py`):
    доказуемо значением здесь УСЛОВИЕ (`shown`), а не формулировка. Условия —
    `tamper_alert()`, `slot_guard()`, `split_pending()`, `CONFIG['template']`;
    их и сверяет сторож, а тексты живут один раз.
    """
    me = request_user()
    show_money = can(me, PERM_MONEY) or me is None
    show_set = can(me, PERM_SETTINGS) or me is None
    show_docs = can(me, PERM_DOCTORS) or me is None
    # права врача (22.10): журнал всех врачей и SMS — по праву; врачу без
    # полного права клиент узнаёт СВОЕГО врача (`doctor`), чтобы не рисовать
    # «Programare nouă» учётке, которой записывать некуда
    show_sched = can(me, PERM_SCHEDULE_ALL) or me is None
    show_sms = can(me, PERM_SMS) or me is None
    # «Rechemări» (29.10): стойка и директор; врачу пункта нет (В1 = А)
    show_recall = can(me, PERM_RECALL) or me is None
    th = theme.current()

    items = [{"key": "dash", "href": "/admin", "icon": "home", "label": SECTION_TITLE["dash"]},
             {"key": "prog", "href": "/admin/all", "icon": "cal", "label": SECTION_TITLE["prog"]},
             {"key": "pat", "href": "/admin/search", "icon": "pat", "label": SECTION_TITLE["pat"]}]
    if show_recall:
        items.append({"key": "rec", "href": "/admin/rechemari", "icon": "refresh",
                      "label": SECTION_TITLE["rec"]})
    # «Registre» (МАКЕТ 10.11): пишут все вошедшие — ассистентка у кресла тоже
    items.append({"key": "reg", "href": "/admin/registre", "icon": "shield",
                  "label": SECTION_TITLE["reg"]})
    if show_docs:
        items.append({"key": "med", "href": "/admin/medici", "icon": "med",
                      "label": SECTION_TITLE["med"]})
    if show_money:
        items.append({"key": "stat", "href": "/admin/stats", "icon": "stat",
                      "label": SECTION_TITLE["stat"]})
    if show_set:
        items.append({"key": "set", "href": "/admin/settings", "icon": "set",
                      "label": SECTION_TITLE["set"]})
    # Секция «Sincronizări» (сегодня в ней только SMS-пакет; Telegram-бот и QR
    # для пациентов ушли 03.11.2026). Пустой список = секции нет вовсе.
    sync = []
    # SMS-пакет (S6): пункт у ВСЕХ ролей, когда сервер предлагает пакет
    # (видимость — выключателем на сервере, S0 › 7); регистратура меняет
    # переключатели, директор платит — решает API, не меню
    # Врачу пункта нет (Олег 22.10: SMS врач не видит) — то же право, что у
    # галочки окна записи и у страницы `/admin/settings/sms` (`PERM_SMS`).
    if sms_loop.offered() and show_sms:
        item = {"key": "sms", "href": "/admin/settings/sms", "icon": "chat",
                "label": SECTION_TITLE["sms"], "dot": "ok" if sms_loop.active() else "off"}
        # остаток на считанные дни — треугольник с подсказкой вместо точки
        if (alert := _sms_alert()):
            item["alert"] = alert
        sync.append(item)

    def _sig(html_: str) -> dict:
        return {"shown": bool(html_), "html": html_}

    return {
        "identity": ({"name": me["name"], "role": me["role"],
                      "role_label": ROLE_LABEL.get(me["role"], me["role"]),
                      "initials": _initials(me["name"]),
                      "can": {"money": show_money, "settings": show_set,
                              "doctors": show_docs, "schedule_all": show_sched,
                              "recall": show_recall},
                      # ключ СВОЕГО врача у журнала, суженного до него
                      # (`auth.schedule_scope`); пусто — журнал всех или ничей
                      "doctor": schedule_scope(me, eng.DOCTORS) or ""} if me else None),
        # ⚠️ Знак и адрес обратной связи едут СТРОКАМИ сервера, как проза
        # баннеров: рисовать фирменный знак второй раз в TSX значило бы завести
        # второго владельца одной картинки.
        "clinic": {"name": eng.CLINIC_NAME,
                   "mark": brand.mark_svg(28, "logo", flat=True),
                   "logo_topbar": (theme.logo_url() or "") if th.get("logo_topbar") else "",
                   # логотип карточки входа (экран PIN клиента, B4.4) — как у
                   # страницы входа: если клиника его загрузила, без галочки
                   "logo": theme.logo_url() or ""},
        "runtime": {"version": eng.APP_VERSION, "tz": eng.TZ.key},
        # Окно «Despre DentPilot» (Tauri, Т7) — ФАКТЫ, а не пересказ: папка из
        # того же места, куда программа пишет (`data_folder`), срок — «Valabil
        # până la» файла, как на странице лицензии. Пусто — не рисуется.
        "about": {"data": data_folder(), "license_until": _license_until()},
        # Дверь (B4.4): клиент меняет человека без перезагрузки ТОЛЬКО там, где
        # вход по PIN-файлу. Без него (облако, демо, ADMIN_KEY) «Ieșire din
        # cont» остаётся ссылкой на `/admin/logout`: шлюз демо на этом адресе
        # отдаёт слот посетителя, и JSON-выход мимо него слот бы не вернул.
        # Фон — тот же, что у страниц входа (`_backdrop`): слово Олега «окно
        # с PIN-кодом оставить на том же фоне»; строкой сервера, как знак.
        "entry": {"pin": _pin_rec() is not None, "pin_max": PIN_MAX,
                  "backdrop": brand.backdrop_svg()},
        "nav": {"active": active, "items": items, "sync": sync},
        # ⛔ React-оболочка рисует РОВНО этот список баннеров: баннер, забытый
        # здесь, не виден нигде (серверного каркаса `_shell` с 03.11.2026 нет).
        "signals": {"license": _sig(_license_banner() + _mail_banner() + _terms_banner()),
                    "tamper": _sig(_tamper_banner()), "split": _sig(_split_banner()),
                    "slot": _sig(_slot_banner()), "setup": _sig(_setup_hint()),
                    "demo": _sig(_demo_banner()), "backup": _sig(_backup_banner())},
        # `title` — страница с собственным именем (фиша: имя пациента, 09.10 по
        # разбору: H1 «Pacienți» дублировал крошку); пустой — имя раздела
        "frame": {"title": title or section_title(active), "sub": sub, "rail": rail,
                  "update": _update_banner().removeprefix(" · "),
                  "msg": msg_banner(msg) if msg else "",
                  # ⭐ Навигация раздела (сегодня её печатает `_sec_page`, одну
                  # и ту же на всех 22 вызовах). СТРУКТУРОЙ, а не разметкой:
                  # условие «когда показывать» остаётся на сервере, где его и
                  # принимают, а React только рисует. HTML-строкой это утащило
                  # бы в модель вёрстку, а решение «по active === set» на
                  # клиенте развело бы одно условие по двум местам.
                  "crumbs": crumbs or [],
                  # Уголок: знак со словом «DentPilot» — ссылка на сайт. Знак
                  # строкой сервера, как `clinic.mark`, и с СВОЕЙ приставкой id
                  # (`bcmark`): два знака на странице не делят маску.
                  "site": {"href": SITE_URL,
                           "mark": brand.mark_svg(18, "bcmark", flat=True)},
                  "feedback": {
                      "email": FEEDBACK_EMAIL,
                      "href": (f"mailto:{FEEDBACK_EMAIL}?subject="
                               + urllib.parse.quote(f"Feedback DentPilot — "
                                                    f"{eng.CLINIC_NAME} (v{eng.APP_VERSION})")
                               + "&body="
                               + urllib.parse.quote("Ideea / problema mea:\n\n"))},
                  "today": datetime.now(eng.TZ).date().isoformat()},
    }


def react_shell(screen: str, path: str, model: dict,
                params: dict | None = None) -> str:
    """Документ, в котором оболочку рисует React (B1).

    ⛔ Сервер печатает ТОЛЬКО голову и узел монтирования. Ни сайдбара, ни
    верхней панели, ни `<h1>`, ни подписи раздела, ни баннеров: их рисует
    React по модели `shell_model`.

    ⭐ Модель едет ИНЛАЙНОМ, атрибутом, тем же экранированием, что и
    `data-params`. Оболочка, ждущая `fetch`, рисовала бы пустой сайдбар на
    первом кадре — ровно то мигание, ради устранения которого B1 и делается.
    """
    e = html.escape
    if screen in BACKUP_LINE_SCREENS and "signals" in model:
        model = {**model, "signals": {**model["signals"], "backup": {"shown": False, "html": ""}}}
    attrs = (f' data-params="{e(json.dumps(params, ensure_ascii=False), quote=True)}"'
             if params else "")
    return _doc_head() + f'''<body data-v="{eng.APP_VERSION}">
<link rel="stylesheet" href="/static/css/bundle.css?v={_asset_ver("css", "bundle.css")}">
{REACT_MOUNT_MARK}{e(screen)}"{attrs}
 data-shell="{e(json.dumps(model, ensure_ascii=False), quote=True)}">
<p class="hint">Interfața nu s-a încărcat.
<a href="{e(path)}">Reîncărcați pagina</a>.</p></div>
<script type="module" src="/static/js/bundle.js?v={_asset_ver("js", "bundle.js")}"></script>
</body></html>'''
