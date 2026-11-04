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
from . import license as lic
from . import sms_loop
from . import theme
from .auth import (PERM_DOCTORS, PERM_MONEY, PERM_RECALL, PERM_SCHEDULE_ALL, PERM_SETTINGS, PERM_SMS,
                   PIN_MAX, ROLE_LABEL, _pin_rec, can, request_user, schedule_scope)
from .icons import _ic
from .messages import MSG_BANNER, msg_banner, msg_json, msg_state, msg_text, msg_view
from .labels import (_age, _doc_hours_text, _DOC_STATE_RO, _DOW_FULL, _DOW_ORDER, _initials, ALERT_KINDS,
                     dmy, FEEDBACK_EMAIL, HOUR_MAX, HOUR_MIN, LIVE_STATUSES, SITE_URL, SOURCE_LABEL,
                     STATUS_LABEL, status_view, SUPPORT_PHONE)
from .pages import _asset, _asset_ver, fonts_css, pwa_head, standalone, STATIC
from .banners import (_backup_banner, _demo_banner, _lic_date, _lic_why, _license_banner, _license_until,
                      _mail_banner, _setup_hint, _slot_banner, _sms_alert, _split_banner, _tamper_banner,
                      _terms_banner, _update_banner, SETUP_HINT)


__all__ = (
    "_age", "_asset", "_doc_hours_text", "_DOC_STATE_RO", "_DOW_FULL",
    "_DOW_ORDER", "_ic", "_initials", "ALERT_KINDS", "data_folder",
    "dmy", "FEEDBACK_EMAIL", "fonts_css", "HOUR_MAX", "HOUR_MIN",
    "license_cont_page", "license_page", "license_pay_page", "LIVE_STATUSES", "msg_json",
    "msg_state", "msg_text", "msg_view", "react_shell", "SECTION_TITLE",
    "SETUP_HINT", "shell_model", "SOURCE_LABEL", "standalone", "STATIC",
    "STATUS_LABEL", "status_view", "SUPPORT_PHONE",
)


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


_RENEW_RO = {lic.RENEWED: "termen nou primit", lic.RENEW_SAME: "nu există termen mai nou",
             lic.RENEW_OFFLINE: "serverul nu a răspuns",
             lic.RENEW_REFUSED: "serverul nu a recunoscut licența",
             lic.RENEW_BAD: "răspunsul serverului nu a putut fi verificat"}


def _renew_line(director: bool) -> str:
    """Автообновление (L13): что программа делает сама, когда спрашивала последний
    раз, и кнопка «сейчас» — директору. Без `renew` в файле строки нет: обещать
    нечего. Слова — про срок лицензии: файла клиника не видит (02.10)."""
    if lic.renew_target() is None:
        return ""
    last = lic.last_renew()
    if last["at"] is None:
        when = "de la pornire încă nu a verificat"
    else:
        when = (f"ultima verificare {last['at'].astimezone(eng.TZ):%d.%m.%Y %H:%M} — "
                f"{_RENEW_RO.get(last['outcome'], last['outcome'])}")
    # Своя форма: у страницы их несколько (26.09), а вложенных HTML не знает
    btn = ("<form method='post' action='/admin/license/renew'><button>Verifică acum dacă "
           "există un termen nou</button></form>" if director else "")
    return (f"<p>Programul verifică zilnic pe serverul DentPilot dacă există un termen nou "
            f"al licenței și îl preia singur ({html.escape(when)}).</p>{btn}")


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
                           "settings_hours", "settings_services", "settings_theme",
                           "settings_security", "settings_backup",
                           "settings_crypt", "settings_system", "settings_sms", "stats",
                           "patients_search", "patient_card", "visit", "odontogram",
                           "perio", "schedule_week", "schedule_all",
                           "schedule_doctor",
                           "schedule_dash",
                           # Экран «у кресла» (26.09): старой страницы у него
                           # не было никогда.
                           "chair"})


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


# ⚠️ Страницы со своей вёрсткой (эта и страницы входа в `modules/entry/pages.py`)
# НЕ подключают panel.css и не будут. Экран входа — первое, что видит клиника, и
# он обязан открыться, даже если статика не отдалась; экран установки PIN
# показывается там, где журнала ещё нет вовсе. Значит переменных CSS у них нет,
# и цвет клиники приезжает ГОТОВЫМИ значениями через standalone() —
# заполнителями __ACCENT__/__ON__/__RING__/__BG__/__LOGO__.
# ⛔ Оттуда же __FONTS__, и он обязателен для каждой страницы, просящей 'Inter':
# объявления шрифта у них своего нет, а panel.css, где оно живёт, не подключена.
# Забытый заполнитель = системный Segoe UI, и это невидимо даже разработчику
# (Inter не установлен ни у кого, страница выглядит «как всегда»).
#
# Страница активации лицензии (L5). Тот же класс, что у восстановления: своя
# вёрстка, открывается и без бандла, потому что обязана открыться тогда, когда
# программе больше нечего показать. В отличие от восстановления — не всегда
# стена: при льготе и режиме чтения на неё ведёт ссылка из баннера.
LICENSE_TMPL = """<!doctype html><html lang="ro"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">__REFRESH__
<title>__CLINIC__ — licență</title><style>__FONTS__
 body{font-family:'Inter','Segoe UI',system-ui,sans-serif;background:__BG__;display:flex;
      align-items:center;justify-content:center;min-height:100vh;margin:0;color:#162033;
      padding:16px;box-sizing:border-box}
 .box{background:#fff;padding:30px 32px;border-radius:18px;border:1px solid #E7EDF5;
      box-shadow:0 3px 6px rgba(15,23,42,.06),0 18px 40px rgba(15,23,42,.10);
      display:flex;flex-direction:column;gap:12px;width:min(600px,100%)}
 h1{font-size:19px;margin:0;font-weight:600;letter-spacing:-.02em}
 p{color:#5A6875;font-size:13.5px;margin:0;line-height:1.55}
 dl{display:grid;grid-template-columns:max-content 1fr;gap:4px 14px;margin:0;font-size:13.5px}
 dt{color:#5A6875}dd{margin:0;font-weight:600}
 input,textarea{font-family:ui-monospace,Consolas,monospace;font-size:13px;padding:10px 12px;
       border:1px solid #E7EDF5;border-radius:12px;outline:none;color:#162033;width:100%;
       box-sizing:border-box}
 textarea{min-height:96px;resize:vertical}
 input:focus,textarea:focus{border-color:__ACCENT__;box-shadow:0 0 0 3px __RING__}
 button{background:__ACCENT__;color:__ON__;border:none;border-radius:12px;height:44px;
        font-size:15px;font-weight:600;cursor:pointer}
 .err{color:#B91C1C;font-size:13px}
 .note{color:#065F46;font-size:13px}
 .state{padding:10px 12px;border-radius:10px;font-size:13.5px;line-height:1.5}
 .state.ok{background:#ECFDF5;color:#065F46}.state.warn{background:#FFFBEB;color:#B45309}
 .state.bad{background:#FEF2F2;color:#B91C1C}
 .contacts{font-size:13px}a{color:__ACCENT_D__}
 form{display:flex;flex-direction:column;gap:12px;margin:0}
 label{font-size:13px;color:#5A6875;margin-bottom:-6px}
 .req input{font-family:inherit;font-size:14px}
 .terms{display:flex;gap:10px;align-items:flex-start;font-size:13.5px;line-height:1.5;color:#162033;
        margin:0}
 .terms input{width:auto;margin:3px 0 0;padding:0;flex:none}
 details>summary{cursor:pointer;font-size:13.5px;color:#5A6875}
 details[open]>summary{margin-bottom:12px}
 a.pay{display:flex;align-items:center;justify-content:center;background:__ACCENT__;color:__ON__;
       border-radius:12px;height:44px;font-size:15px;font-weight:600;text-decoration:none}
 .mail{display:flex;flex-direction:column;gap:12px;padding:14px 16px;border-radius:12px;
       background:#FFFBEB;border:1px solid #FDE68A}
 .mail .t{color:#B45309;font-weight:600}
 button.alt{background:#fff;color:__ACCENT_D__;border:1px solid #E7EDF5}
 a.cont{display:flex;align-items:center;justify-content:center;gap:8px;border:1px solid #E7EDF5;
        color:__ACCENT_D__;border-radius:12px;height:42px;font-size:14.5px;font-weight:600;
        text-decoration:none}
</style></head><body>
<div class="box">
  <h1>__ICON__ __TITLE__</h1>
  <div class="state __TONE__">__TEXT__</div>
  __DETAILS__
  __ERR__
  __FORM__
  <p class="contacts">Întrebări despre licență sau abonament:
  <a href="mailto:__EMAIL__">__EMAIL__</a> · __PHONE__</p>
  __BACK__
</div></body></html>"""
LICENSE_TMPL = LICENSE_TMPL.replace("__ICON__", _ic("key"))

# Галочка условий — перед кнопкой: активация и есть принятие договора (п. 1
# условий), а летопись пишет, кто её поставил. Ссылка с target=_blank уходит
# в системный браузер (окно программы так отдаёт «новые окна»), и программа
# остаётся на месте. Заявке нужна и политика: сервер берёт согласие с обеими.
def _terms_box(privacy: bool = False) -> str:
    pol = (" și <a href='https://dentpilot.md/privacy.html' target='_blank' rel='noopener'>"
           "Politica de confidențialitate</a>") if privacy else ""
    return (f"<label class='terms'><input type='checkbox' name='terms' value='1' required>"
            f"<span>Am citit și accept <a href='{lic.TERMS_URL}' target='_blank' rel='noopener'>"
            f"Termenii și condițiile</a> DentPilot (versiunea din {lic.TERMS_VERSION}){pol}</span>"
            f"</label>")


# Формы импорта файла на странице НЕТ (решение Олега 02.10: клиник без интернета
# нет, файл клиника не видит). Маршрут POST /admin/license остаётся — инструмент
# поддержки и предмет tests/test_license_page.py.
def _request_form(v: dict) -> str:
    """Активация без файла (26.09): заявка на пробный. Поля и правила — формы /proba
    сервера (проверяет сервер, отказ приходит его словами); подсказки длины — те же."""
    def val(k: str) -> str:
        return html.escape(v.get(k) or "", quote=True)
    return (f"<form class='req' method='post' action='/admin/license/request'>"
            f"<p><b>Activare automată.</b> Completați datele clinicii: cererea pleacă la DentPilot, "
            f"iar programul se activează singur. Prima lună este gratuită.</p>"
            f"<p>Clinica lucrează deja cu DentPilot pe alt calculator? Completați aceleași date "
            f"(IDNO sau e-mail): trimitem un cod de activare pe e-mailul clinicii.</p>"
            f"<label for='r-name'>Denumirea clinicii *</label>"
            f"<input id='r-name' name='name' value='{val('name')}' required maxlength='120'>"
            f"<label for='r-idno'>IDNO (13 cifre, opțional pentru perioada de probă)</label>"
            f"<input id='r-idno' name='idno' value='{val('idno')}' maxlength='13' inputmode='numeric'>"
            f"<label for='r-contact'>Persoana de contact</label>"
            f"<input id='r-contact' name='contact_name' value='{val('contact_name')}' maxlength='80'>"
            f"<label for='r-email'>E-mail *</label>"
            f"<input id='r-email' name='email' type='email' value='{val('email')}' required maxlength='120'>"
            f"<label for='r-phone'>Telefon</label>"
            f"<input id='r-phone' name='phone' value='{val('phone')}' maxlength='40'>"
            f"{_terms_box(privacy=True)}"
            f"<button>Trimite cererea și activează programul</button></form>")


# Код из письма (новый компьютер той же клиники): галочки нет — код бывает только
# у заявки, а заявку без галочки маршрут не отправит; договор принят ею
_CODE_FORM = ("<form class='req' method='post' action='/admin/license/verify'>"
              "<p><b>Codul de activare.</b> Introduceți codul din 6 cifre primit pe adresa de "
              "e-mail a clinicii, înregistrată la DentPilot.</p>"
              "<label for='v-code'>Codul din e-mail</label>"
              "<input id='v-code' name='code' required maxlength='7' inputmode='numeric' "
              "autocomplete='one-time-code' autofocus>"
              "<button>Activează programul</button></form>")
_PENDING_CHECK = ("<form method='post' action='/admin/license/renew'><button>Verifică acum dacă "
                  "cererea a fost aprobată</button></form>")


def _pending_text(p: dict) -> str:
    """Состояние страницы, пока заявка ждёт файла: когда, для кого, что дальше."""
    at = lic.st.parse(p.get("at"))
    when = f" la {at.astimezone(eng.TZ):%d.%m.%Y %H:%M}" if at else ""
    return (f"Cererea de perioadă de probă a fost trimisă{when} pentru "
            f"„{html.escape(p.get('clinic') or '')}” ({html.escape(p.get('email') or '')}). "
            f"Programul se activează singur imediat ce o aprobăm — de obicei în aceeași zi "
            f"lucrătoare; pagina se actualizează singură.")


def _email_block(director: bool) -> str:
    """E-mail клиники (27.10, план В): пока сервер не подтвердил ящик — напоминание директору и три
    действия: код из письма, «Retrimite», «Schimbă adresa». Подтверждён — одна строка. ⛔ Ничего не
    запирает: программа работает и с неподтверждённым ящиком."""
    box = lic.mailbox()
    if box is None or not director:
        return ""
    email = html.escape(box["email"])
    if box["confirmed"]:
        return f"<p>Adresa de e-mail a clinicii la DentPilot: <b>{email}</b> — confirmată.</p>"
    return (f"<div class='mail'><p class='t'>E-mail neconfirmat: {email}</p>"
            f"<p>Pe această adresă vin codul pentru un calculator nou, intrarea în contul clinicii și "
            f"notele de plată. Deschideți e-mailul de la DentPilot și apăsați „Confirmă adresa” sau "
            f"introduceți aici codul din 6 cifre. Programul funcționează și fără confirmare.</p>"
            f"<form class='req' method='post' action='/admin/license/email/confirm'>"
            f"<label for='m-code'>Codul din e-mail</label>"
            f"<input id='m-code' name='code' required maxlength='7' inputmode='numeric' "
            f"autocomplete='one-time-code'><button>Confirmă adresa</button></form>"
            f"<form method='post' action='/admin/license/email/code'><button class='alt'>Retrimite "
            f"e-mailul</button></form>"
            f"<details><summary>Adresa este greșită? Schimbă adresa</summary>"
            f"<form class='req' method='post' action='/admin/license/email/change'>"
            f"<label for='m-email'>Adresa corectă de e-mail a clinicii</label>"
            f"<input id='m-email' name='email' type='email' required maxlength='120'>"
            f"<button class='alt'>Schimbă adresa și trimite codul</button></form></details></div>")


def _terms_block(director: bool) -> str:
    """Условия на странице лицензии (29.10): какую версию клиника приняла; версия программы новее —
    директору галочка и «Accept» (возврат на эту же страницу, `back=license`). Без квитанций и слова
    сервера — «înregistrată local la activare»: активация до 29.10, акт тогда на сервер не уходил."""
    t = lic.terms_state()
    acc = t["accepted"]
    link = f"<a href='{lic.TERMS_URL}' target='_blank' rel='noopener'>Termenii și condițiile</a>"
    if not t["due"]:
        if acc:
            where = " · actul este la DentPilot" if t["receipt_id"] else ""
            return f"<p>{link}: versiunea din <b>{html.escape(acc)}</b> este acceptată{where}.</p>"
        return (f"<p>{link}: acceptarea a fost înregistrată local, la activare (versiunea actuală "
                f"{html.escape(lic.TERMS_VERSION)}).</p>")
    if not director:
        return (f"<p>{link} s-au actualizat ({html.escape(lic.TERMS_VERSION)}) — versiunea nouă o acceptă "
                f"directorul clinicii.</p>")
    was = f" Clinica a acceptat versiunea din {html.escape(acc)}." if acc else ""
    return (f"<div class='mail'><p class='t'>Termenii și condițiile s-au actualizat ({html.escape(lic.TERMS_VERSION)})</p>"
            f"<p>{link} DentPilot au o versiune nouă.{was} Programul funcționează și fără acceptare; "
            f"citiți versiunea nouă și confirmați.</p>"
            f"<form method='post' action='/admin/license/terms'><input type='hidden' name='back' value='license'>"
            f"<label class='terms'><input type='checkbox' name='terms' value='1' required>"
            f"<span>Am citit și accept Termenii și condițiile DentPilot (versiunea din "
            f"{html.escape(lic.TERMS_VERSION)})</span></label><button>Accept</button></form></div>")


def _pay_block() -> str:
    """«Plătește acum» на странице лицензии (02.10): ссылка в системный браузер
    (target=_blank), где у программы нет входа, — поэтому с ключом
    (`lic.pay_ticket`). Пока после нажатия идёт частый запрос файла — строка об
    этом, а страница обновляется сама: новый срок появится без кнопок."""
    if not lic.pay_available():
        return ""
    watch = lic.paying()
    note = (f"<p>Programul verifică plata la fiecare minut până la "
            f"{watch.astimezone(eng.TZ):%H:%M}; noul termen apare aici singur.</p>" if watch else
            "<p>Pagina de plată se deschide în browser, cu datele clinicii deja completate: "
            "alegeți perioada (o lună sau un an) și modul de plată.</p>")
    return (f"<a class='pay' href='/plata/{lic.pay_ticket()}' target='_blank' rel='noopener'>"
            f"Plătește acum</a>{note}")


def _cont_block() -> str:
    """«Deschide contul clinicii» на странице лицензии (27.10, сервер — cloud/app/contlink.py):
    кабинет СВОЕЙ клиники в системном браузере без кода — тот же ключ, что у «Plătește acum»
    (`lic.pay_ticket`), маршрут /cont/<ключ>. Только директору (зовёт license_page)."""
    if not lic.cont_available():
        return ""
    return (f"<a class='cont' href='/cont/{lic.pay_ticket()}' target='_blank' rel='noopener'>"
            f"{_ic('user')} Deschide contul clinicii</a>"
            "<p>Contul clinicii DentPilot se deschide în browser, fără cod: abonamentul, notele și "
            "contul de plată, calculatoarele și datele acestei clinici.</p>")


# Страница-ответ маршрута /cont, когда до кабинета дойти не вышло: как у /plata, системный
# браузер без входа программы — что случилось и что сделать в окне программы.
_CONT_FAIL = {
    "ticket": ("Linkul a expirat",
               "Apăsați din nou «Deschide contul clinicii» în program, pe pagina Licență."),
    lic.PAY_NONE: ("Contul clinicii nu se deschide din program",
                   "Licența de pe acest calculator nu are un server DentPilot. Intrați în contul clinicii "
                   "de pe dentpilot.md, cu Google sau cu codul pe e-mail."),
    lic.PAY_OFFLINE: ("Serverul DentPilot nu a răspuns",
                      "Verificați conexiunea la internet și apăsați din nou «Deschide contul clinicii» "
                      "în program. Dacă se repetă, așteptați câteva minute."),
    lic.PAY_REFUSED: ("Serverul DentPilot nu a recunoscut licența",
                      "Licența acestui calculator nu este recunoscută de serverul DentPilot. Scrieți-ne."),
}


def license_cont_page(code: str) -> str:
    title, text = _CONT_FAIL.get(code, _CONT_FAIL[lic.PAY_OFFLINE])
    return (standalone(LICENSE_TMPL)
            .replace("__REFRESH__", "").replace("__TITLE__", title).replace("__TONE__", "bad")
            .replace("__TEXT__", text).replace("__DETAILS__", "").replace("__ERR__", "")
            .replace("__FORM__", "<p>Puteți închide această filă.</p>").replace("__BACK__", "")
            .replace("__EMAIL__", FEEDBACK_EMAIL).replace("__PHONE__", SUPPORT_PHONE))


# Страница-ответ маршрута /plata, когда до страницы оплаты дойти не вышло. Её
# видит СИСТЕМНЫЙ браузер, где у программы нет входа, — поэтому ни ссылки «в
# журнал», ни кнопок: что случилось и что сделать в окне программы.
_PAY_FAIL = {
    "ticket": ("Linkul de plată a expirat",
               "Deschideți din nou «Plătește acum» în program: pe pagina Licență sau în bannerul de sus."),
    lic.PAY_NONE: ("Plata din program nu este disponibilă",
                   "Licența de pe acest calculator nu are un server de reînnoire. Scrieți-ne — "
                   "vă trimitem nota de plată."),
    lic.PAY_OFFLINE: ("Serverul DentPilot nu a răspuns",
                      "Verificați conexiunea la internet și apăsați din nou «Plătește acum» în program."),
    lic.PAY_REFUSED: ("Serverul DentPilot nu a recunoscut licența",
                      "Licența acestui calculator nu este recunoscută de serverul DentPilot. "
                      "Scrieți-ne — vă ajutăm să achitați abonamentul."),
}


def license_pay_page(code: str) -> str:
    title, text = _PAY_FAIL.get(code, _PAY_FAIL[lic.PAY_OFFLINE])
    return (standalone(LICENSE_TMPL)
            .replace("__REFRESH__", "").replace("__TITLE__", title).replace("__TONE__", "bad")
            .replace("__TEXT__", text).replace("__DETAILS__", "").replace("__ERR__", "")
            .replace("__FORM__", "<p>Puteți închide această filă.</p>").replace("__BACK__", "")
            .replace("__EMAIL__", FEEDBACK_EMAIL).replace("__PHONE__", SUPPORT_PHONE))


def license_page(msg: str = "", *, director: bool, walled: bool) -> str:
    """Страница активации по текущему состоянию. `msg` — код из MSG_BANNER после
    303 (отказ импорта или заявки); текст берётся оттуда же, как у всех отказов.

    Без годного файла главный путь — заявка на пробный (26.09): программа
    активируется сама; пока заявка ждёт — её состояние и самообновление
    страницы. Файла клиника не видит (02.10): ни формы импорта, ни слова
    «fișier» — только «licența» и её срок."""
    s = lic.current()
    applies = s is not None and lic.applies()
    details = ""
    pend = None
    activate = False                 # файла нет: заявка (или ожидание по ней) — главный путь
    if s is None or not applies:
        title, tone, text = ("Licența programului", "warn",
                             "Această versiune a programului nu verifică licența: nu are nicio "
                             "cheie de emitere.")
    elif s.claim is not None:
        c = s.claim
        pay = _pay_block() if director else ""
        pay += _cont_block() if director else ""      # кабинет клиники — после оплаты (27.10)
        details = (f"<dl><dt>Clinica</dt><dd>{html.escape(c.clinic)}</dd>"
                   f"<dt>Abonament</dt><dd>{html.escape(c.plan)}</dd>"
                   f"<dt>Valabil până la</dt><dd>{_lic_date(c.valid_until)}</dd>"
                   f"<dt>Licența</dt><dd>nr. {c.seq}</dd></dl>" + _renew_line(director))
        # при льготе и чтении оплата — главное действие страницы, при активной —
        # продление заранее, после срока и «Verifică acum»
        details = (pay + details) if s.state != lic.st.ACTIVE else (details + pay)
        details += _email_block(director)          # e-mail клиники (27.10) — последним блоком
        details += _terms_block(director)          # условия: принятая версия, повторный акцепт (29.10)
        if s.state == lic.st.ACTIVE:
            title, tone, text = "Licența programului", "ok", "Abonamentul este activ."
        elif s.state == lic.st.GRACE:
            title, tone = "Abonamentul a expirat", "warn"
            text = (f"Abonamentul a expirat la {_lic_date(s.valid_until)}. Programul funcționează "
                    f"încă până la {_lic_date(s.grace_until)}; după această dată trece în regim de citire.")
        else:
            title, tone = "Programul este în regim de citire", "bad"
            text = (f"Abonamentul a expirat la {_lic_date(s.valid_until)}, iar perioada de plată s-a "
                    f"încheiat la {_lic_date(s.grace_until)}. Datele se pot consulta, tipări și "
                    f"exporta; după plată programul preia singur noul termen.")
    else:
        title = "Activarea programului"
        activate = True
        pend = lic.pending()
        reason = _lic_why(s.code)
        if pend is not None:
            tone, text = "ok", _pending_text(pend)
        elif s.wall:
            tone, text = "warn", ((f"Licența {reason}. " if s.code else "")
                                  + "Programul nu este încă activat.")
        elif s.state == lic.st.GRACE:
            tone, text = "warn", (f"Licența {reason}. Programul funcționează încă până la "
                                  f"{_lic_date(s.grace_until)}; după această dată trece în regim de citire.")
        else:
            tone, text = "bad", (f"Licența {reason}. Programul este în regim de citire din "
                                 f"{_lic_date(s.grace_until)}: datele se pot consulta, tipări și exporta.")
    # Тон — из MSG_BANNER: «новее нет» и «заявка отправлена» — не красным
    msg_tone, err = MSG_BANNER.get(msg, ("", "")) if msg else ("", "")
    req = lic.last_request()
    if msg == lic.REQUEST_SENT and pend is not None:
        err = ""                               # то же говорит состояние страницы выше
    elif msg == lic.REQUEST_REFUSED and req["text"]:
        err = f"{err}: {req['text']}"          # словами сервера: поле, повтор, лимит
    elif msg in (lic.REQUEST_CODE, lic.CODE_BAD) and req["text"]:
        err = req["text"]                      # словами сервера: срок кода, попытки
    elif msg == lic.EMAIL_REFUSED and (lic.mailbox() or {}).get("text"):
        err = lic.mailbox()["text"]            # словами сервера: код, лимит, ящик занят
    elif not msg and activate and pend is None and req["declined"]:
        err = MSG_BANNER[lic.REQUEST_DECLINED][1]
    if not director:
        form = "<p>Programul îl poate activa directorul clinicii.</p>"
    elif activate and pend is not None:
        form = _PENDING_CHECK
    elif activate and req["verify_id"]:
        form = (_CODE_FORM + "<details><summary>Nu a venit codul? Trimiteți din nou cererea</summary>"
                + _request_form(req["fields"]) + "</details>")
    elif activate:
        form = _request_form(req["fields"])
    else:
        form = ""                      # лицензия есть: срок и кнопка «Verifică acum» — в _renew_line
    back = "" if walled else "<p><a href='/admin'>Înapoi la registru</a></p>"
    # самообновление — пока ждёт заявка или после «Plătește acum» идёт частый
    # запрос файла: новый срок появится на странице без кнопок
    refresh = ("<meta http-equiv='refresh' content='30'>"
               if pend is not None or lic.paying() is not None else "")
    return (standalone(LICENSE_TMPL)
            .replace("__REFRESH__", refresh)
            .replace("__TITLE__", title).replace("__TONE__", tone)
            .replace("__TEXT__", text).replace("__DETAILS__", details)
            .replace("__ERR__", f"<div class='{'note' if msg_tone == 'ok' else 'err'}'>"
                                f"{html.escape(err)}</div>" if err else "")
            .replace("__FORM__", form).replace("__BACK__", back)
            .replace("__EMAIL__", FEEDBACK_EMAIL).replace("__PHONE__", SUPPORT_PHONE))
