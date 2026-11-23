"""Правила раскладки кода из карты проекта — синтаксисом, а не прозой.

Единственный набор, который НЕ поднимает сервер: он читает исходники модулем
`ast`. Проверяет то, чего не видит ни один HTTP-запрос: где лежит файл, кто
кого импортирует, кто забыл позвать соседа. Такие поломки молчаливы — запрос
успешен, лог чист, а собранная у клиники программа либо не стартует, либо
показывает не то (грабли `__file__` 08-04 и `__package__` 08-05).

Каждое правило здесь уже записано прозой в CLAUDE.md и уже соблюдается. Набор
ничего не чинит: он не даёт правилу тихо отмереть при следующем переезде файла.
"""
import ast
import importlib.util
import pathlib
import re

from harness import BOT, ROOT, Result

# Исходники клиента. Как и BOT, перевешивается мутацией на копию дерева.
FRONTEND = ROOT / "frontend" / "src"
# Скрипт мастера установки — тоже текст, который клиника читает, и тоже
# перевешивается мутацией (правило про папку данных).
INSTALLER = ROOT / "installer"
# Файлы СБОРКИ, которым положено знать имена статики клиента (07.10): конфиг
# vite её пишет, образ демо копирует поимённо, оба игнора прячут. Корень тот же
# ROOT, но под своим именем: мутация перевешивает его на копию, как FRONTEND и
# INSTALLER, и копирует ровно эти четыре файла.
BUILD = ROOT
_VITE_CONFIG = "frontend/vite.config.ts"
_DEMO_IMAGE = "demo/Dockerfile"
_IGNORES = (".gitignore", ".dockerignore")
BUILD_FILES = (_VITE_CONFIG, _DEMO_IMAGE, *_IGNORES)

# Где ссылка между экранами обязана быть `AppLink` (B4): всё, что рисуется
# внутри дерева роутера. `app/` (корень и таблица маршрутов), `hooks/`,
# `services/`, `utils/` разметки ссылок не держат.
_LINK_DIRS = ("features", "components", "layouts")
# Голый `<a href>` законен ровно в двух файлах: сам `AppLink` (его запасная
# ветка для адресов вне карты) и быстрый поиск — он смонтирован РЯДОМ с
# роутером, а не внутри, и `Link` там бросит. Список включающий: якорь ниже
# проверяет, что оба файла ещё существуют.
_RAW_ANCHOR_OK = {"components/AppLink.tsx", "features/quickfind/QuickFind.tsx"}


def _raw_anchors(text: str) -> list[int]:
    """Строки, где в разметке стоит `<a … href=…>`. Комментарии `/* */`
    (в JSX — `{/* */}`) не считаются; скобки в атрибутах (`onClick={(e) => …}`)
    не обрывают тег на своём `>`."""
    # Комментарий гасится пробелами, но его переводы строк остаются: иначе
    # каждая строка многострочного `/* */` выше ссылки сдвигала бы номер в
    # сообщении сторожа (в OdontogramWorkbench.tsx он называл 135 вместо 149).
    text = re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group(0)),
                  text, flags=re.S)
    out, i = [], 0
    while (m := re.compile(r"<a(?=[\s>/])").search(text, i)) is not None:
        j, depth = m.end(), 0
        while j < len(text):
            ch = text[j]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            elif ch == ">" and depth == 0:
                break
            j += 1
        if "href=" in text[m.start():j]:
            out.append(text.count("\n", 0, m.start()) + 1)
        i = j + 1
    return out

# Файлы, которые `desktop.py` зовёт ДО того, как собрано приложение: импортов
# проекта в них нет и быть не может, и лежать они обязаны в корне app/.
# Переезд любого из них в подпапку ломает запуск у клиники, не тронув запуск
# из исходников — то есть ни один прогон этого не заметит.
_PRELOAD = ("app/paths.py", "app/dpapi.py", "app/envfile.py",
            "app/install_info.py", "app/legacy.py",
            # знак и шрифт заставки (05.10): их берёт сборка оболочки Tauri
            # (`shell/assets.py`) без приложения, а знак — и сам движок до
            # сборки приложения (цвет заставки в `hello`). (`restartwatch.py`
            # ушёл из слоя 22.10.2026: Python-сторожа `--watch` больше нет, план
            # сторожа строит приложение — `update._spawn_watch`.)
            "app/brand.py", "app/splash.py",
            # версия: её читают текстом сборка и скрипты, а движок — импортом
            "app/version.py")

# Друг друга им знать можно — это один слой, живущий до сборки приложения
# (dpapi правит токен в dental.env, то есть зовёт envfile). Нельзя всё
# остальное: db, engine, core, модули — любой из них тянет за собой FastAPI.
_PRELOAD_MOD = {p.rsplit("/", 1)[-1][:-3] for p in _PRELOAD}

# Модули копий картотеки, которые лаунчер зовёт в `_prepare` до сборки
# приложения (17.10): им можно знать друг друга и предзагрузочный слой.
_LAUNCHER_COPY = ("app/core/autobackup.py", "app/core/restore.py", "app/core/dbkey.py",
                  "app/core/orders.py")
_LAUNCHER_COPY_OK = _PRELOAD_MOD | {p.rsplit("/", 1)[-1][:-3] for p in _LAUNCHER_COPY}

# Провод Google — чистые модули: вход не знает проекта вовсе, чтение знает только ics, чтобы
# событие API шло путём файла. Импорт базы или соседа утянул бы в провод состояние программы.
_GWIRE = {"app/core/gauth.py": set(), "app/core/gapi.py": {"ics"}, "app/core/gwrite.py": set()}
# Тело события в календаре врача — белым списком: поле записи сверх этих (телефон, заметка, диагноз)
# уехало бы в Google на всех уровнях подробности.
_GWRITE = "app/core/gwrite.py"
_GWRITE_APPT = {"id", "start", "minutes", "room", "patient", "file_no", "service"}
_GWRITE_KEYS = {"id", "summary", "description", "start", "end", "status", "reminders", "transparency",
                "visibility", "extendedProperties"}
_GWRITE_PRIVATE = {"dp", "dp_appt"}
# Дверь к Google врачей: файл связи, токены, замок врача. Кто входит в неё или ходит к Google по
# её ключу — и обязан спросить право сам, до сети (подключение и сверка добавят свои функции).
_GDOC = "app/core/gdoc.py"
_GDOC_GATE = "gcal_doctor"
_GDOC_GATED = {_GDOC: ("access",)}
_GDOC_NET = {"refresh", "exchange", "consent_url", "calendar_get", "calendar_insert", "calendar_patch",
             "calendar_delete", "event_insert", "event_update", "event_delete", "events_ours", "_open",
             "_renew"}
# Отзыв у Google проектный: он оборвал бы календари всех врачей аккаунта и связь клиники.
_GDOC_NO_REVOKE = (_GDOC,)
# Кто держит токен врача в руках — ни в лог, ни в базу.
_GDOC_TOKEN_FILES = (_GDOC,)
# Пишет в календари врачей только тот, кто знает их ключи через дверь: dpapi и клиент сборки — у
# двери; вход Google — у двери и у подключения врача.
_GWRITE_KEYS_OK = {_GDOC}
_GWRITE_GAUTH_OK = {_GDOC}
# Запись файла связи и уход врача — под замком врача; подключение и сверка добавят свои функции.
_GDOC_LOCKED = {_GDOC: ("access", "report", "done", "bump_epoch", "calendar_named", "store", "leave")}
# Константу клиента Google PyInstaller кладёт в exe только по статическому импорту: импорт по строке
# он не видит, и exe молча остался бы «не настроено» — дымовой тест exe этого не заметит.
_GCLIENT = "app/core/gclient.py"
# Связь вкладки с аккаунтом Google: вход, возврат из браузера, опрос, файл токена.
_GLINK = "app/modules/schedule/gcal_link.py"
_GLINK_API = "app/modules/schedule/gcal_api.py"
# Кто начинает связь или ходит к Google по ней — и обязан спросить право в файле лицензии сам,
# до сети: право гаснет в полночь конца срока, а новый файл приходит суточным запросом.
_GLINK_GATED = ("start", "finish", "choose", "_pass", "tick")
_GLINK_NET = {"consent_url", "exchange", "events", "calendars", "_access_token", "_pass"}
# Имена, под которыми в связке ходят токен, код входа и секрет клиента.
_GLINK_SECRETS = {"token", "refresh_token", "access", "grant", "verifier", "auth_code", "secret",
                  "protected", "refresh"}
# Модули копий картотеки: файл связи — ключ к календарю под DPAPI этой машины, в копию не едет.
_GLINK_NO_COPY = ("app/core/backup.py", "app/core/restore.py", "app/core/autobackup.py")

# `__file__` законен ровно там, где кто-то обязан знать, где лежит он сам:
# paths.py — единственный, кто знает раскладку; desktop.py — лаунчер, который
# зовут раньше paths. Везде ещё «путь рядом с собой» переживёт переезд файла
# в исходниках и умрёт внутри exe, где раскладка другая.
_FILE_OK = {"app/paths.py", "desktop.py"}

# Пакет db (с 03.11.2026; до того — один `app/db.py`): правила ниже смотрят в
# модуль-ВЛАДЕЛЕЦ своего якоря, а не в пакет целиком. ⚠️ Переедет якорь в
# соседний модуль — правило покраснеет «якорь пропал», а не ослепнет: каждое
# ищет своё имя только в названном файле.
_DB_STATE = "app/db/__init__.py"     # _CONN, _SQ, ACTOR_HOOK — переприсваиваемое
_DB_SCHEMA = "app/db/schema.py"      # SCHEMA_VERSION, MIGRATIONS, SQLITE_SCHEMA
_DB_SLOTS = "app/db/slots.py"        # _slot_lock, _BOOK_LOCK, _uq_slot_sql
# Слотовые индексы врача (кабинет в ключе) и все имена, под которыми слотовый
# индекс бывал в базе: прежние два — без кабинета, их кладёт старая версия.
_UQ_DOCTOR = ("uq_doc_room_slot", "uq_docid_room_slot")
_UQ_NAMES = (*_UQ_DOCTOR, "uq_patient_slot", "uq_doctor_slot")
_DB_DAY = "app/db/schedule.py"       # day_appointments: выборка дня
# Кто принимает длительность снаружи и обязан спросить `eng.dur_ok`.
_DUR_ASKERS = ("app/modules/schedule/routes.py", "app/modules/settings/routes.py",
               "app/core/book.py")
# Кто показывает или принимает услугу АГЕНДЫ (окно записи журнала и фиши, смена
# процедуры визита, Google, услуги врача, Rechemări) и обязан спросить место у
# `eng.in_agenda` (или собрать список через `prices.options(eng.WHERE_AGENDA)`):
# иначе строка «только прайс» плана уехала бы в окно записи типом визита.
# ⭐ Список ВКЛЮЧАЕТ требование — поэтому каждое имя обязано найтись.
_AGENDA_READERS = (
    ("app/modules/schedule/day.py", "services_list"),
    ("app/core/visits.py", "service_refusal"),
    ("app/modules/schedule/routes.py", "_book_appt"),
    ("app/modules/patients/routes.py", "_free_slots"),
    ("app/modules/patients/routes.py", "_appoint"),
    ("app/modules/patients/card.py", "appoint_view"),
    ("app/modules/patients/api.py", "_agenda_options"),
    ("app/core/book.py", "refusal"),
    ("app/modules/schedule/gcal.py", "_form"),
    ("app/modules/schedule/gcal.py", "set_service"),
    ("app/modules/doctors/routes.py", "_service_rows"),
    ("app/modules/doctors/routes.py", "_orphan_services"),
    ("app/modules/doctors/routes.py", "_set_services"),
    ("app/core/recall.py", "services"),
)
_DB_TEXTS = "app/db/plans.py"        # тексты летописи пациента («Plan: …»)
_DB_SAN = "app/db/registre.py"       # журналы san_*: единственное место UPDATE (замок IS NULL)
_DB_LAB = "app/db/lab.py"            # заказы в лабораторию: история только дописывается
_DB_STOCK = "app/db/stock.py"        # журнал склада: только INSERT, и только здесь
_DB_ORIGIN = "app/db/plist.py"       # ORIGIN_SQL: откуда пациент — одно правило
_LAY_LABELS = "app/core/labels.py"   # ORIGIN_LABEL: подписи каналов пациента
# Разделы с меню слева, которые обязаны найтись правилу «раздел с меню слева берёт данные загрузчиком».
_SIDE_MENU_KNOWN = {"patient_card", "lab", "stock", "tarife"}
# Якоря бывшего layout.py (разнос 04.11): переезд имени = правка одной строки.
_LAY_SHELL = "app/core/layout.py"     # shell_model, REACT_SCREENS, SECTION_TITLE
_LAY_ICONS = "app/core/icons.py"      # _I, _ic
_LAY_MSG = "app/core/messages.py"     # MSG_BANNER и его читатели (msg_*)
# Кому можно читать MSG_BANNER прямо; остальным — msg_text / msg_view / msg_json.
_LAY_BANNERS = "app/core/banners.py"  # баннеры-сигналы оболочки, _sms_alert
_LAY_LICENSE = "app/core/license_pages.py"  # страницы лицензии
_MSG_READERS = (_LAY_MSG, _LAY_BANNERS, _LAY_LICENSE)
_LAY_BELOW = (_LAY_ICONS, _LAY_MSG, "app/core/labels.py", "app/core/pages.py",
              _LAY_BANNERS, _LAY_LICENSE)

# Все, кто в итоге зовёт `_save_users`, то есть переписывает auth.json.
# verify_pin здесь не по недосмотру: при входе он молча мигрирует файл v1→v2.
# Забытый рядом remember_auth_file() = ложный «взлом» при следующем старте, а
# это хуже настоящего — клиника перестанет верить баннеру.
_AUTH_WRITERS = {"save_user", "delete_user", "_write_pin", "verify_pin"}

# Кто зовёт `eng.save_config`, то есть переписывает `clinic.json` ЦЕЛИКОМ.
# Раздел профиля, который писатель не трогает, обязан пережить его запись
# (шаблоны плана, логотип в теме, счётчики id) — это проверяется поведением:
# `test_plan_tpl.suite_writers` идёт по этому же списку и на каждого писателя
# требует действие. Новый писатель сюда = новое действие там.
_CFG_WRITERS = {
    "app/modules/settings/api.py:api_clinic_save", "app/modules/settings/api.py:api_hours_save",
    "app/modules/settings/api.py:api_services_save", "app/modules/settings/api.py:api_templates_save",
    "app/core/plan_tpl.py:store", "app/modules/settings/api.py:api_theme_save",
    "app/modules/settings/api.py:api_backup_auto", "app/modules/settings/api.py:api_sms_save",
    "app/modules/settings/routes.py:_logo_action",
    "app/modules/doctors/routes.py:_save_cfg", "app/modules/doctors/routes.py:_save_doctor",
    "app/core/tarife.py:store",
}

# Кто ставит визит фише по номеру (`db.add_visit_for_patient`). Правило «можно ли поставить»
# повторено ровно один раз — `core/book.book_visit` (перенос из Google, импорт с записями);
# писатель мимо него — третья копия порядка проверок окна записи, которая разойдётся молча.
# Запись из фиши (`_appoint`) старше и со своим набором кодов (`past`, `bad` на минуту не по сетке).
_VISIT_BY_ID = {"app/core/book.py:book_visit", "app/modules/patients/routes.py:_appoint"}

# Импорт пациентов с записями ставит визиты ТОЛЬКО через `core/book`: проба на шаге проверки —
# `book.probe`, запись — `book.book_visit`. Любой другой путь записи в журнал из импорта — своя
# копия порядка проверок окна записи (сетка, часы, занятость, кабинет), которая разойдётся молча.
_PIMPORT = ("app/modules/patients/pimport.py", "app/modules/patients/pimport_api.py")
_APPT_WRITERS = {"admin_add", "create_appointment", "_book", "_book_locked", "add_visit_for_patient",
                 "add_note", "_insert_note", "set_status", "move_appointment", "_add_appt", "_book_appt",
                 "_journal_add", "set_appt_room"}

# Перенос из Google Calendar пачкой и автоматом (`modules/schedule/gcal_auto.py`).
_GAUTO = "app/modules/schedule/gcal_auto.py"
_GCAL = "app/modules/schedule/gcal.py"
_DB_GCAL = "app/db/gcal.py"
# Что пишет журнал или связь события с записью из вкладки: зовущий обязан быть под замком переноса
# сам или зваться только из-под него. Окно регистратора и проход опроса иначе поставили бы событие дважды.
_GCAL_WRITES = {"_journal_add", "gcal_mark_moved", "gcal_unmove", "_move_appt", "_set_status"}
# Двери, которые берут замок сами (включающий список: пропавшее имя выключило бы правило молча).
_GCAL_LOCKED = {f"{_GCAL}:move", f"{_GCAL}:link", f"{_GAUTO}:run", f"{_GAUTO}:auto_pass", f"{_GAUTO}:undo",
                f"{_GAUTO}:keep", f"{_GAUTO}:follow", f"{_GAUTO}:cancel_appt"}

# Оракул ВХОДА В ЖУРНАЛ. Все шестеро привязаны к папке, В КОТОРОЙ ИДЁТ
# ПРОГРАММА, и все пишут в неё. Против чужого корня (экран раздвоения, P2) они
# непригодны вовсе — там `verify_source_pin`, читающий по явному пути.
# `try_login` (16.10) — обёртка над пятью для формы и JSON-двери: зовёт их,
# значит привязан так же.
_LOGIN_ORACLE = {"verify_pin", "note_fail", "note_ok", "lock_left", "fail_count",
                 "try_login"}
# Где вход законен: сам модуль-владелец, форма входа в журнал (до 14.10 она
# жила в main.py; переезд в modules/entry покраснел здесь, как и задумано) и
# JSON-дверь смены человека рядом с ней (B4.4, 16.10).
_LOGIN_OK = {"app/core/auth.py", "app/modules/entry/routes.py",
             "app/modules/entry/api.py"}

# Двери под `/api/`: маршруты, у которых куки ещё НЕТ, — охрана заперла бы
# вход изнутри. Их защищает сверка Origin (`same_origin_post`), как у формы:
# иначе чужой сайт в браузере клиники перебирал бы PIN-ы и накручивал счётчик.
# ⚠️ Полярность опасная: список ВКЛЮЧАЕТ исключение — переименованная дверь
# выпала бы из него и покраснела общим правилом (это хорошо), а строка под
# несуществующий адрес зеленела бы молча (это ловит якорь ниже).
_API_OPEN = {"/api/auth/login"}

# Подтверждение ИСТОЧНИКА: функция и её счётчик. Оба имени — якорь правил ниже.
_SRC_VERIFY = "verify_source_pin"
_SRC_OWNS = {_SRC_VERIFY, "SourcePinAttempts", "source_auth_file"}
# Чем в чужом корне можно наследить. ⛔ Список про ЛЮБУЮ запись, а не только
# про auth.json: copy-only нарушает и .tmp, и пустая папка.
_SRC_WRITES = {"write_text", "write_bytes", "_write_pin", "_save_users",
               "_fail_save", "_state_write", "remember_auth_file", "replace",
               "rename", "unlink", "mkdir", "touch", "copy", "copy2",
               "copyfile", "copytree", "fsync"}

# Арифметика PIN: соль, хеш, разбор учёток. Один модуль на всю программу.
_PIN_MATH = {"_derive", "_secret_fields", "_users"}

# Роль — НАБОР ПРАВ в таблице PERMS, а не строка, которую сравнивают по месту.
# Ловим и литерал, и константу: `role == "director"` и `role == ROLE_DIRECTOR`.
_ROLES = {"director", "receptie", "medic"}

# Законные сравнения роли: код, который ролями УПРАВЛЯЕТ, а не который решает
# по роли, что человеку можно. Экран учёток обязан знать, что такое директор,
# и через PERMS этого не выразить:
#   _apply_user  — «последний директор снимает с себя роль» запер бы настройки
#                  навсегда: вернуть право станет некому.
# (До 12.10 здесь стоял и `_users_block` — старая страница учёток, снята.)
# Список именной, а не по файлу: settings/routes.py длиной под тысячу строк, и
# разрешение на весь файл спрятало бы в нём будущую проверку доступа по роли.
# Переименуют функцию — набор покраснеет, и это правильно: повод посмотреть.
_ROLE_OK = {"app/modules/settings/routes.py": {"_apply_user"}}

# Владелец правила: внутри него сравнивать роли и переписывать auth.json можно,
# на то он и один на всю программу.
_AUTH_MODULE = "app/core/auth.py"

# Цвет врача: своя формула на один экран расходится с другими молча — цвета
# обе берут из одной палитры, и на демо-профиле, где показаны все врачи, они
# ещё и совпадают. Владелец один: `_doc_hue`, а палитра — его внутренность.
_HUE_MODULE = "app/core/visits.py"
_HUE_PALETTE = "_DOC_HUES"


# Страница со своей вёрсткой, просящая 'Inter', обязана его и ОБЪЯВИТЬ: либо
# заполнителем __FONTS__ (его заполняет layout.standalone текстом fonts.css),
# либо своими @font-face. Правило нужно ровно потому, что нарушение невидимо:
# такая страница цела, просто нарисована системным шрифтом, — а Inter не
# установлен и у разработчика, поэтому «выглядит как всегда» и у него. Так
# экран входа полгода жил в Segoe UI, пока panel.css показывала задуманный вид.
# Знаки, которые рисует система: эмодзи, стрелки, дингбаты, геометрия и
# математика. ⭐ Блок математических операторов (U+2200..U+22FF) дописан 08-16:
# «−» U+2212 и «≈» U+2248 не эмодзи и глаз их не выделяет, но во вшитый Inter
# они не входят ровно так же, как стрелка, — то есть рисует их Windows. Правило
# берёт БЛОК, а не два знака: «всё, кроме перечисленного» живёт до первого
# нового знака и ломается молча (тот же урок, что у PLAN_ACTIVE).
_SYSGLYPH = re.compile("[🀀-🫿←-⇿∀-⋿⌀-⏿"
                       "■-➿⬀-⯿]")

# ⚠️ С B5 такая страница может просить не 'Inter', а заполнитель __FAMILY__
# (выбор шрифта клиники, подставляет layout.standalone) — объявление ей нужно
# ровно так же: Inter — один из двух ответов.
_INTER = re.compile(r"font-family\s*:\s*(?:['\"]?Inter|__FAMILY__)")
_DECLARED = ("__FONTS__", "@font-face")

# ---- место данных не пересказывают словами (P1 21.09; клиент и мастер 27.09) ----
# Как тексты называли место данных до P1: «în folderul programului» и «lângă
# program». С P1 обе фразы врут: папку данных назначает лаунчер
# (`paths.data_root`), у установленной программы это `%ProgramData%\DentPilot`.
# ⚠️ Между словами — ЛЮБОЙ пробел, перенос строки тоже: подсказка документов
# старой фиши переносилась ровно между «folderul» и «programului», и поиск
# подстроки не видел её с самого P1.
# ⚠️ «program» — целым словом: «lângă programare» (рядом с записью) и «lângă
# programul de lucru» — обычные слова журнала, а не адрес.
# «langa» без диакритики — та же фраза: так пишется CITESTE-MA.txt в архиве.
_DATA_PLACE = re.compile(r"folderul\s+programului|l[âaî]ng[ăa]\s+program\b",
                         re.I)
# Где фраза ПРАВДИВА: она описывает СТАРУЮ раскладку — ту, от которой клиника
# переезжает, а не ту, в которой программа работает. Прощается кусок текста, а
# не файл: вторая такая фраза в том же файле была бы уже про новую раскладку.
# ⚠️ Прощение, которому больше нечего прощать, — красное: текст переписали, а
# строка здесь молча простила бы ту же фразу, вернись она в файл по новой.
_OLD_LAYOUT_OK = {
    # экран «Două fișe de pacienți» (P2): карточка найденной старой установки
    "app/modules/migration/routes.py": ("Fișa de lângă program",),
    # отказ мастера ставиться поверх установки, где данные лежат у exe
    "installer/DentPilot.iss": (
        "o instalare mai veche a DentPilot, cu datele clinicii lângă program",),
}

# Как клиент называет поверхность: в адресе (`…?screen=panel`) и ключом
# объекта (`new URLSearchParams({ screen: 'panel' })`). Вторая форма нужна:
# панель строит запрос именно так, и правило, знающее только первую, не
# увидело бы её вовсе.
# ⚠️ У ключевой формы кавычки ОБЯЗАТЕЛЬНЫ — иначе правило поймало бы
# объявление типа `screen: string` и сочло бы поверхностью слово «string».
_SURF_URL = re.compile(r"screen=([a-z_]+)")
_SURF_KEY = re.compile(r"""\bscreen\b\s*:\s*['"]([a-z_]+)['"]""")


def _ui_texts(tree: ast.Module) -> list[tuple[int, str]]:
    """Строковые литералы модуля БЕЗ docstring'ов, каждый одним куском.

    Пояснения в проекте написаны со знаками ⚠/⭐/⛔ по стилю, и до экрана они
    не доезжают — запрещать их незачем, а с ними правило краснело бы всегда.
    Отсев по САМОМУ узлу, а не по номеру строки: у многострочного литерала
    номер зависит от версии Python, и сверка номеров тихо перестала бы ловить.
    Три обхода дерева на вызов, а зовут его пять правил на каждый модуль —
    поэтому ответ считается один раз и лежит на самом дереве
    (`tree._ui_texts_cache`), как интервалы у `_enclosing`: не в словаре по
    `id(tree)`, потому что мутация и `test_guards` гонят набор по новым
    деревьям в одном процессе. Список отдаётся тот же — правила его только
    читают."""
    cached = getattr(tree, "_ui_texts_cache", None)
    if cached is not None:
        return cached
    inner = {id(x) for n in _walk(tree) if isinstance(n, ast.JoinedStr)
             for x in _walk(n) if x is not n}
    docs = set()
    for n in _walk(tree):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                          ast.ClassDef)) and n.body:
            first = n.body[0]
            if (isinstance(first, ast.Expr)
                    and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                docs.add(id(first.value))
    out = []
    for n in _walk(tree):
        if id(n) in inner or id(n) in docs:
            continue
        if isinstance(n, ast.JoinedStr):
            out.append((n.lineno, "".join(v.value for v in _walk(n)
                                          if isinstance(v, ast.Constant)
                                          and isinstance(v.value, str))))
        elif isinstance(n, ast.Constant) and isinstance(n.value, str):
            out.append((n.lineno, n.value))
    tree._ui_texts_cache = out
    return out


def _client_code(text: str) -> str:
    """Исходник клиента без комментариев — всё, что может доехать до экрана:
    строки, шаблоны и текст JSX между тегами (он тоже экран, хотя строкой не
    является). Комментарии гасятся пробелами, переводы строк остаются — номер
    строки в сообщении сторожа совпадает с файлом."""
    text = re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group(0)),
                  text, flags=re.S)
    return re.sub(r"(?<![:\w'\"])//[^\n]*", "", text)


# Комментарий Pascal (`//…`, `{…}`, `(*…*)`) или строка в апострофах — одним
# выражением: что встретилось раньше, то и есть. Поэтому `{` внутри строки
# (`S[0] := '{';`) комментария не открывает, а апостроф в комментарии — строки.
_PASCAL = re.compile(r"//[^\n]*|\{[^}]*\}|\(\*.*?\*\)|'((?:[^'\n]|'')*)'", re.S)


def _iss_texts(text: str) -> list[tuple[int, str]]:
    """Что из скрипта установщика доезжает до экрана: (строка, текст).

    До `[Code]` — каждая строка, кроме комментариев `;`: сообщения мастера,
    описания задач, директивы. В `[Code]` — только строки в апострофах: всё
    остальное там код и комментарии Pascal."""
    m = re.search(r"^\[code\]", text, re.M | re.I)
    cut = m.start() if m else len(text)
    out = [(i, ln) for i, ln in enumerate(text[:cut].splitlines(), 1)
           if not ln.lstrip().startswith(";")]
    out += [(text.count("\n", 0, s.start()) + 1, s.group(1))
            for s in _PASCAL.finditer(text, cut) if s.group(1) is not None]
    return out


# ---- выход сборки клиента (vite.config.ts) ----
# Путь от статики движка (`bot/app/static`): `js/three.js`. Свои файлы rollup
# называет литералом (`entryFileNames: 'js/bundle.js'`, `return
# 'css/bundle.css'`), плагины копий — `writeFileSync(resolve(ПАПКА, 'имя'), …)`,
# где ПАПКА — константа `resolve(ENGINE_STATIC, 'js')` или сама ENGINE_STATIC.
_VITE_NAMED = re.compile(r"""(['"`])((?:js|css)/[a-z0-9_-]+\.(?:js|css))\1""")
_VITE_DIR = re.compile(
    r"""const\s+(\w+)\s*=\s*resolve\(\s*ENGINE_STATIC\s*,\s*['"]([a-z]+)['"]\s*\)""")
_VITE_WRITE = re.compile(
    r"""writeFileSync\(\s*resolve\(\s*(\w+)\s*,\s*['"]([^'"]+)['"]\s*\)""")
# Любая запись файла в конфиге. Каждая обязана разобраться формой выше: имена —
# список ВКЛЮЧАЮЩИЙ, и копия, переписанная через переменную, выпала бы из
# сверки молча — а с ней и правило для её файла.
_VITE_ANY_WRITE = re.compile(
    r"\b(?:writeFileSync|writeFile|copyFileSync|copyFile|cpSync|createWriteStream)\(")


def _vite_outputs(code: str) -> tuple[set[str], list[str]]:
    """Что сборка клиента кладёт в статику движка — и записи, которых разбор не
    понял. `code` — конфиг без комментариев (`_client_code`): имя в пояснении
    файлом сборки не становится."""
    dirs = {"ENGINE_STATIC": "", **dict(_VITE_DIR.findall(code))}
    names = {m.group(2) for m in _VITE_NAMED.finditer(code)}
    blind = []
    for m in _VITE_ANY_WRITE.finditer(code):
        where = f"{_VITE_CONFIG}:{code.count(chr(10), 0, m.start()) + 1}"
        w = _VITE_WRITE.match(code, m.start())
        if w is None:
            blind.append(f"{where}: запись не вида writeFileSync(resolve(ПАПКА, "
                         "'имя')) — её файл выпал из сверки")
        elif w.group(1) not in dirs:
            blind.append(f"{where}: папка {w.group(1)} — не resolve(ENGINE_STATIC, "
                         "…), куда идёт файл, правило не знает")
        else:
            names.add(f"{dirs[w.group(1)]}/{w.group(2)}".lstrip("/"))
    return names, blind


def _docker_copies(text: str) -> list[tuple[list[str], str]]:
    """`COPY --from=…` образа: (источники, назначение).

    Комментарий в Dockerfile — только строка, НАЧАТАЯ `#` (в середине строки
    это обычный знак), и вырезается он и внутри продолжения `\\`.
    Закомментированная копия — не копия, а поиск подстроки засчитал бы и её."""
    out, cur = [], []
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        cur.append(line.rstrip().removesuffix("\\"))
        if line.rstrip().endswith("\\"):
            continue
        words, cur = " ".join(cur).split(), []
        args = [w for w in words[1:] if not w.startswith("--")]
        if (words and words[0].upper() == "COPY" and len(args) >= 2
                and any(w.startswith("--from=") for w in words[1:])):
            out.append((args[:-1], args[-1]))
    return out


def _copied_to(copies: list[tuple[list[str], str]], path: str) -> list[str]:
    """Куда образ кладёт `static/<path>` из стадии сборки — назначения COPY."""
    return [dst for srcs, dst in copies for src in srcs
            if src.endswith(f"/static/{path}")]


def _ignore_entries(text: str) -> set[str]:
    """Шаблоны .gitignore/.dockerignore — без комментариев, пустых строк и
    ведущего `/` (шаблон со `/` внутри оба и так читают от корня).
    Закомментированная строка ничего не прячет."""
    return {ln.strip().lstrip("/") for ln in text.splitlines()
            if ln.strip() and not ln.strip().startswith("#")}


def _walk(node: ast.AST) -> tuple:
    """`ast.walk(node)` один раз на узел: обход кладётся кортежем на сам узел.

    Правила обходят одни и те же деревья заново — каждое своё, на каждый
    модуль, и вложенные узлы ещё раз внутри обхода дерева; без кэша это
    четыре пятых времени набора, а мутация гоняет набор на каждое правило.
    На узле, а не в словаре по `id()`: `mutate.py` и `test_guards` гонят suite
    по НОВЫМ деревьям в одном процессе. Словарь либо держал бы в памяти все
    деревья всех прогонов, либо, отпустив их, отдал бы обход умершего дерева
    новому узлу с тем же id — правило читало бы старое дерево, и мутация в
    копии прошла бы незамеченной. Кэш умирает вместе с деревом: `_sources()`
    разбирает файлы заново на каждый прогон. Правила узлы не правят, поэтому
    обход, снятый один раз, верен до конца жизни дерева."""
    nodes = getattr(node, "_walked", None)
    if nodes is None:
        nodes = node._walked = tuple(ast.walk(node))
    return nodes


def _sources() -> list[tuple[str, ast.Module]]:
    """Все модули программы: (путь от bot/ через `/`, разобранное дерево)."""
    out = []
    for p in sorted(BOT.rglob("*.py")):
        rel = p.relative_to(BOT).as_posix()
        out.append((rel, ast.parse(p.read_text(encoding="utf-8"), filename=rel)))
    return out


def _calls(node: ast.AST) -> set[str]:
    """Имена функций, вызванных внутри узла. `await f()` тоже считается: Await
    оборачивает Call, а walk доходит до него.

    ⚠️ Последнее имя берётся и у вызова ЧЕРЕЗ МОДУЛЬ (`auth.save_user(...)` —
    это ast.Attribute, у него нет `.id`). Правило про отпечаток auth.json
    включающее: не увидев вызова, оно молчит, а не краснеет, — то есть чужой
    стиль импорта выключал бы его целиком. А модулем-объектом здесь ходят
    почти все (`from ...core import theme`), и сегодня правило работает лишь
    потому, что писателей auth.json импортируют поимённо."""
    return {n.func.id if isinstance(n.func, ast.Name) else n.func.attr
            for n in _walk(node) if isinstance(n, ast.Call)
            and isinstance(n.func, (ast.Name, ast.Attribute))}


def _enclosing(tree: ast.Module, lineno: int) -> set[str]:
    """Имена всех функций, внутри которых лежит строка (вложенные — тоже).

    Один обход на дерево: интервалы всех def'ов (начало, конец, имя) считаются
    при первом вызове и кладутся на САМО дерево (`tree._def_spans`), дальше —
    перебор интервалов. До 23.10 каждый вызов обходил дерево целиком: две
    тысячи вызовов за набор — 17,6 млн узлов и половина времени набора, а
    мутация, гоняющая набор на каждое правило, шла под час.
    Кэш на дереве, а не в словаре по `id(tree)`: `mutate.py` и `test_guards`
    гонят suite много раз по НОВЫМ деревьям в одном процессе, и id() умершего
    дерева достаётся новому — словарь отдал бы функции чужого файла."""
    spans = getattr(tree, "_def_spans", None)
    if spans is None:
        spans = tree._def_spans = [
            (fn.lineno, fn.end_lineno or fn.lineno, fn.name)
            for fn in _walk(tree)
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))]
    return {name for lo, hi, name in spans if lo <= lineno <= hi}


def _templates(tree: ast.Module) -> list[tuple[int, str]]:
    """Строковые литералы модуля — каждый ОДНИМ куском: (строка, текст).

    f-строка разобрана на части, и заполнитель вполне может лежать в другой
    части, чем `font-family` (`<style>__FONTS__ … {color}` — уже две). Поэтому
    части одного литерала склеиваются, а вложенные в него узлы вторым разом не
    разбираются: иначе один шаблон дал бы десяток «нарушителей»."""
    inner = {id(x) for n in _walk(tree) if isinstance(n, ast.JoinedStr)
             for x in _walk(n) if x is not n}
    out = []
    for n in _walk(tree):
        if id(n) in inner:
            continue
        if isinstance(n, ast.JoinedStr):
            text = "".join(v.value for v in _walk(n)
                           if isinstance(v, ast.Constant)
                           and isinstance(v.value, str))
        elif isinstance(n, ast.Constant) and isinstance(n.value, str):
            text = n.value
        else:
            continue
        out.append((n.lineno, text))
    return out


def _imported(node: ast.AST) -> list[str]:
    """Что импортирует один узел import/from-import — модуль и имена вместе."""
    if isinstance(node, ast.ImportFrom):
        return [node.module or ""] + [a.name for a in node.names]
    if isinstance(node, ast.Import):
        return [a.name for a in node.names]
    return []


def suite(res: Result) -> None:
    src = _sources()
    by_path = dict(src)

    # Сторож за сторожами. Все проверки ниже устроены как «нарушителей не
    # нашлось», и пустой список файлов делает их все зелёными разом. Если
    # раскладка репозитория однажды переедет, упасть должно здесь, а не
    # притвориться успехом.
    res.ok("исходники нашлись", len(src) > 20,
           f"под {BOT} разобрано файлов: {len(src)}")

    bad = [f"{rel}:{n.lineno}" for rel, tree in src if rel not in _FILE_OK
           for n in _walk(tree)
           if isinstance(n, ast.Name) and n.id == "__file__"]
    res.ok("__file__ только в paths.py и desktop.py", not bad,
           "путь «рядом с собой» вне разрешённых мест: " + ", ".join(bad))

    # ⭐ Парное правило к предыдущему, и появилось оно вместе с разделением
    # «папка программы» ≠ «папка клиники» (P1). `__file__` отвечает на вопрос
    # «где лежу я», `$DATABASE_URL` — на вопрос «где лежит картотека», и второй
    # разбирался РУКАМИ в трёх местах. Пока раскладка была одна, три одинаковые
    # строки были безобидны. Теперь любая, разойдясь с остальными, откроет
    # другой файл — а для SQLite «другой файл» это не ошибка, а пустая новая
    # база: программа стартует, журнал чист, и виновата на вид миграция.
    bad = [f"{rel}:{n.lineno}" for rel, tree in src if rel != "app/paths.py"
           for n in _walk(tree)
           if isinstance(n, ast.Constant) and n.value == "///"]
    res.ok("$DATABASE_URL разбирает только paths.py", not bad,
           "второй разборщик адреса базы: " + ", ".join(bad))

    # Правильно — `(__package__ or "app").split(".")[0]`. Голый __package__ в
    # имени модуля после переезда файла в подпапку начинает означать другое, и
    # никакой ошибки при этом не всплывает: статус живого бота показывался
    # выключенным при чистом логе и успешном запросе.
    bad = []
    for rel, tree in src:
        safe = set()
        for n in _walk(tree):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "split"):
                safe.update(id(x) for x in _walk(n)
                            if isinstance(x, ast.Name) and x.id == "__package__")
        bad += [f"{rel}:{n.lineno}" for n in _walk(tree)
                if isinstance(n, ast.Name) and n.id == "__package__"
                and id(n) not in safe]
    res.ok("__package__ только через .split('.')[0]", not bad,
           "имя модуля считается от __package__ целиком: " + ", ".join(bad))

    bad = []
    for rel, tree in src:
        if rel == _AUTH_MODULE:
            continue
        allowed = _ROLE_OK.get(rel, set())
        for n in _walk(tree):
            if not isinstance(n, ast.Compare):
                continue
            if not all(isinstance(o, (ast.Eq, ast.NotEq)) for o in n.ops):
                continue        # `in ("director", …)` — это проверка ввода
            for side in [n.left, *n.comparators]:
                lit = isinstance(side, ast.Constant) and side.value in _ROLES
                const = isinstance(side, ast.Name) and side.id.startswith("ROLE_")
                # белый список спрашиваем ПОСЛЕ совпадения: у _enclosing с
                # 23.10 кэш интервалов на дереве, но звать его на каждое
                # сравнение подряд всё равно незачем
                if (lit or const) and not allowed & _enclosing(tree, n.lineno):
                    bad.append(f"{rel}:{n.lineno}")
                    break
    res.ok("роль не сравнивается по месту", not bad,
           "доступ решается сравнением роли, а не PERMS: " + ", ".join(bad))

    # Якорь к правилу выше. `_ROLES` — список ВКЛЮЧАЮЩИЙ: четвёртая роль в
    # PERMS выключила бы правило для себя молча, потому что её литерала в
    # списке нет (ветка `ROLE_*` спасает только тех, кто пишет сравнение
    # константой). Источник истины один — ключи PERMS; расхождение в ЛЮБУЮ
    # сторону красное: лишнее имя тут так же слепо, как недостающее.
    auth_mod = by_path.get(_AUTH_MODULE) or ast.Module(body=[], type_ignores=[])
    role_const = {n.targets[0].id: n.value.value for n in _walk(auth_mod)
                  if isinstance(n, ast.Assign) and len(n.targets) == 1
                  and isinstance(n.targets[0], ast.Name)
                  and n.targets[0].id.startswith("ROLE_")
                  and isinstance(n.value, ast.Constant)}
    perms_keys = None
    for n in _walk(auth_mod):
        if (isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "PERMS"
                        for t in n.targets)
                and isinstance(n.value, ast.Dict)):
            perms_keys = {k.value if isinstance(k, ast.Constant)
                          else role_const.get(k.id) if isinstance(k, ast.Name)
                          else None for k in n.value.keys}
    res.ok("список ролей совпадает с PERMS", perms_keys == _ROLES,
           f"_ROLES={sorted(_ROLES)}, ключи PERMS="
           f"{sorted(map(str, perms_keys)) if perms_keys is not None else None}"
           f" — правило ловит сравнение по месту только для перечисленных имён")

    # Полярность правила ниже опасная: `_AUTH_WRITERS` — список имён, которые
    # ВКЛЮЧАЮТ требование. Переименуют `save_user` — правило станет искать
    # несуществующее имя, найдёт ноль нарушителей и позеленеет НАВСЕГДА. Мутация
    # этого не ловит: она ломает сторожа тем же устаревшим именем. Поэтому имена
    # сверяются с определениями в самом auth.py. (Остальные списки — обратной
    # полярности и краснеют сами: пропал `paths.py` — не нашёлся файл; переехал
    # `users_save` — сравнение роли в нём перестало быть разрешённым.)
    defined = {fn.name for fn in _walk(by_path.get(_AUTH_MODULE) or ast.Module(
        body=[], type_ignores=[]))
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))}
    gone = sorted(_AUTH_WRITERS - defined)
    res.ok("список пишущих auth.json не протух", not gone,
           f"нет в {_AUTH_MODULE}: {', '.join(gone)} — правило ищет то, чего "
           f"больше нет, и молчит")

    # Внутри auth.py пломбу ставить не надо: модуль владеет файлом, и там
    # writers свободно зовут друг друга (verify_pin → _write_pin → _save_users).
    # Обязанность возникает у ЧУЖОГО кода, который тронул auth.json.
    bad = []
    for rel, tree in src:
        if rel == _AUTH_MODULE:
            continue
        for fn in _walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            called = _calls(fn)
            if called & _AUTH_WRITERS and "remember_auth_file" not in called:
                who = ", ".join(sorted(called & _AUTH_WRITERS))
                bad.append(f"{rel}:{fn.lineno} {fn.name}() зовёт {who}")
    res.ok("кто пишет auth.json — обновляет отпечаток", not bad,
           "забыт remember_auth_file(): " + "; ".join(bad))

    bad = []
    for rel in _PRELOAD:
        if rel not in by_path:
            bad.append(f"{rel} — нет по этому пути")
            continue
        for n in _walk(by_path[rel]):
            if not isinstance(n, (ast.Import, ast.ImportFrom)):
                continue
            targets = [m for m in _imported(n) if m]
            own = getattr(n, "level", 0) or any(
                m.split(".")[0] == "app" for m in targets)
            if not own:
                continue                    # стандартная библиотека — можно
            outside = [m for m in targets
                       if m.split(".")[-1] not in _PRELOAD_MOD]
            if outside:
                bad.append(f"{rel}:{n.lineno} → {', '.join(outside)}")
    res.ok("paths/dpapi/envfile в корне app/ и без импортов проекта", not bad,
           "лаунчер зовёт их до сборки приложения: " + "; ".join(bad))

    # Модули копий, которые зовёт лаунчер ДО сборки приложения (17.10):
    # автокопия, восстановление, ключ. Импорт `db`/`engine`/`storage`/
    # модулей в ШАПКЕ утянул бы FastAPI в `_prepare` и уронил бы старт у
    # клиники — а прогон этого не видит: harness лаунчер не исполняет.
    # Отложенный импорт внутри функции (dbkey → storage) законен.
    bad = []
    for rel in _LAUNCHER_COPY:
        tree = by_path.get(rel)
        if tree is None:
            bad.append(f"{rel} — нет по этому пути")
            continue
        for n in tree.body:
            if not isinstance(n, (ast.Import, ast.ImportFrom)):
                continue
            targets = [m for m in _imported(n) if m]
            own = getattr(n, "level", 0) or any(m.split(".")[0] == "app" for m in targets)
            if not own:
                continue
            outside = [m for m in targets if m.split(".")[-1] not in _LAUNCHER_COPY_OK]
            if outside:
                bad.append(f"{rel}:{n.lineno} → {', '.join(outside)}")
    res.ok("модули копий импортируемы лаунчером", not bad,
           "в шапке — то, что тянет приложение: " + "; ".join(bad))

    bad = []
    for rel, ok in _GWIRE.items():
        tree = by_path.get(rel)
        if tree is None:
            bad.append(f"{rel} — нет по этому пути")
            continue
        for n in _walk(tree):
            if not isinstance(n, (ast.Import, ast.ImportFrom)):
                continue
            targets = [m for m in _imported(n) if m]
            if not (getattr(n, "level", 0) or any(m.split(".")[0] == "app" for m in targets)):
                continue                    # стандартная библиотека — можно
            if isinstance(n, ast.ImportFrom) and n.level == 1 and (
                    n.module in ok or (n.module is None and {a.name for a in n.names} <= ok)):
                continue
            bad.append(f"{rel}:{n.lineno} → {', '.join(targets)}")
    res.ok("провод Google знает из проекта только ics", not bad, "; ".join(bad))

    bad = []
    tree = by_path.get(_GCLIENT)
    if tree is None:
        bad.append(f"{_GCLIENT} — нет по этому пути")
    else:
        if not any(isinstance(n, ast.ImportFrom) and n.level == 1 and (
                n.module == "gclient_build"
                or (n.module is None and any(a.name == "gclient_build" for a in n.names)))
                for n in _walk(tree)):
            bad.append(f"{_GCLIENT}: нет `from . import gclient_build`")
        for n in _walk(tree):
            if ((isinstance(n, ast.Name) and n.id == "__import__")
                    or (isinstance(n, ast.Import) and any(a.name.split(".")[0] == "importlib" for a in n.names))
                    or (isinstance(n, ast.ImportFrom) and (n.module or "").split(".")[0] == "importlib")):
                bad.append(f"{_GCLIENT}:{n.lineno} импорт по строке")
    res.ok("клиент Google в exe — статический импорт gclient_build", not bad, "; ".join(bad))

    # ---- связь с аккаунтом Google: гейт, возврат из браузера, токен ----
    glink = by_path.get(_GLINK)
    gfuncs = {n.name: n for n in (glink.body if glink else ())
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}

    def _gl_calls(fn, names) -> list:
        # не только вызов: сеть уходит в поток ссылкой (`asyncio.to_thread(gauth.exchange, …)`)
        return sorted(c.lineno for c in _walk(fn)
                      if (isinstance(c, ast.Attribute) and c.attr in names)
                      or (isinstance(c, ast.Name) and c.id in names))

    def _gl_gate(fn) -> list:
        return sorted(c.lineno for c in _walk(fn) if isinstance(c, ast.Call)
                      and ((isinstance(c.func, ast.Attribute) and c.func.attr == "feature_until")
                           or (isinstance(c.func, ast.Name) and c.func.id == "feature_until"))
                      and c.args and isinstance(c.args[0], ast.Constant) and c.args[0].value == "gcal")

    bad = []
    if glink is None:
        bad.append(f"{_GLINK} — нет по этому пути")
    for name in _GLINK_GATED if glink else ():
        fn = gfuncs.get(name)
        if fn is None:
            bad.append(f"{_GLINK}: нет функции {name} — список правила устарел")
            continue
        gates, net = _gl_gate(fn), _gl_calls(fn, _GLINK_NET)
        if not gates:
            bad.append(f"{_GLINK}:{fn.lineno} {name} не спрашивает feature_until(\"gcal\")")
        elif net and net[0] < gates[0]:
            bad.append(f"{_GLINK}:{net[0]} {name} идёт к Google раньше, чем спросил право")
        if any(isinstance(n, ast.Global) for n in _walk(fn)):
            bad.append(f"{_GLINK}:{fn.lineno} {name} пишет глобальное — право не кэшируется")
    for n in glink.body if glink else ():
        if isinstance(n, (ast.Assign, ast.AnnAssign)) and n.value is not None and _gl_gate(n):
            bad.append(f"{_GLINK}:{n.lineno} право в имени модуля — кэш вместо вопроса")
    res.ok("подключение и опрос Google спрашивают гейт", not bad, "; ".join(bad))

    # Возврат из браузера Windows приходит мимо /admin и /api: ни куки, ни посредников. Пир
    # соединения — первым делом, state своего входа (gauth.back) — до обмена кода; маршрут ведёт в
    # проверку, и его адрес — тот, что уходит в Google (BACK_PATH).
    bad = []
    fin = gfuncs.get("finish")
    if fin is None:
        bad.append(f"{_GLINK}: нет finish — якорь правила пропал")
    else:
        body = fin.body[1:] if (fin.body and isinstance(fin.body[0], ast.Expr)
                                and isinstance(fin.body[0].value, ast.Constant)) else fin.body
        first = body[0] if body else None
        if not (isinstance(first, ast.If) and _gl_calls(first.test, {"client_is_local"})
                and first.body and isinstance(first.body[-1], ast.Return)):
            bad.append(f"{_GLINK}:{fin.lineno} finish не начинается с отказа не-локальному пиру")
        backs = [c for c in _walk(fin) if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                 and c.func.attr == "back" and len(c.args) == 2]
        swaps = _gl_calls(fin, {"exchange"})
        if not backs:
            bad.append(f"{_GLINK}:{fin.lineno} finish не сверяет state (gauth.back)")
        elif not swaps or swaps[0] < min(c.lineno for c in backs):
            bad.append(f"{_GLINK}:{fin.lineno} обмен кода раньше сверки state")
    back_path = next((n.value.value for n in (glink.body if glink else ())
                      if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant)
                      and any(isinstance(t, ast.Name) and t.id == "BACK_PATH" for t in n.targets)), "")
    if not back_path:
        bad.append(f"{_GLINK}: нет BACK_PATH — якорь правила пропал")
    route = None
    for fn in _walk(by_path.get(_GLINK_API) or ast.Module(body=[], type_ignores=[])):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
                isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr == "get"
                and d.args and isinstance(d.args[0], ast.Constant) and d.args[0].value == back_path
                for d in fn.decorator_list):
            route = fn
    if back_path and route is None:
        bad.append(f"{_GLINK_API}: нет GET {back_path} — адрес возврата ведёт в никуда")
    elif route is not None and not _gl_calls(route, {"finish"}):
        bad.append(f"{_GLINK_API}:{route.lineno} возврат не зовёт gcal_link.finish")
    res.ok("возврат из Google проверяет state и локальность", not bad, "; ".join(bad))

    # Токен, код входа и секрет: ни в строке лога, ни в аргументе базы. Файл связи — не в копиях.
    bad = []

    def _gl_secret(node) -> bool:
        for x in _walk(node):
            if isinstance(x, ast.Name) and x.id in _GLINK_SECRETS:
                return True
            if isinstance(x, ast.Attribute) and x.attr in _GLINK_SECRETS:
                return True
            if (isinstance(x, ast.Subscript) and isinstance(x.slice, ast.Constant)
                    and x.slice.value in _GLINK_SECRETS):
                return True
        return False

    for rel in (_GLINK, _GLINK_API, *_GDOC_TOKEN_FILES):
        tree = by_path.get(rel)
        if tree is None:
            bad.append(f"{rel} — нет по этому пути")
            continue
        for c in _walk(tree):
            if not isinstance(c, ast.Call):
                continue
            f = c.func
            to_log = ((isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name)
                       and f.value.id in ("log", "logging", "logger"))
                      or (isinstance(f, ast.Name) and f.id == "print"))
            to_db = isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "db"
            if (to_log or to_db) and any(_gl_secret(a) for a in [*c.args, *(k.value for k in c.keywords)]):
                bad.append(f"{rel}:{c.lineno} {'лог' if to_log else 'база'} получает токен или код")
    def _file_name(rel: str) -> str:
        tree = by_path.get(rel)
        return next((n.value.value for n in (tree.body if tree else ())
                     if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant)
                     and isinstance(n.value.value, str)
                     and any(isinstance(t, ast.Name) and t.id == "FILE_NAME" for t in n.targets)), "")

    # у каждого файла связи свой якорь: подстрока одного имени другого не ловит
    anchors = [(owner, _file_name(owner)) for owner in (_GLINK, _GDOC)]
    for owner, name in anchors:
        if not name:
            bad.append(f"{owner}: нет FILE_NAME — якорь правила пропал")
    for rel in _GLINK_NO_COPY:
        tree = by_path.get(rel)
        if tree is None:
            bad.append(f"{rel} — нет по этому пути")
            continue
        for _owner, name in anchors:
            if name and any(isinstance(x, ast.Constant) and isinstance(x.value, str) and name in x.value
                            for x in _walk(tree)):
                bad.append(f"{rel} знает {name} — файл связи уехал бы в копию")
    res.ok("токен Google не в базе, не в логе и не в копиях", not bad, "; ".join(bad))

    # ---- календари врачей: тело события, право, отзыв, дверь, замок ----
    gw = by_path.get(_GWRITE)
    bad = []
    if gw is None:
        bad.append(f"{_GWRITE} — нет по этому пути")
    appt_cls = next((n for n in (gw.body if gw else ()) if isinstance(n, ast.ClassDef) and n.name == "Appt"), None)
    if gw is not None and appt_cls is None:
        bad.append(f"{_GWRITE}: нет класса Appt — якорь правила пропал")
    if appt_cls is not None:
        got = {n.target.id for n in appt_cls.body if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)}
        if not got or got - _GWRITE_APPT:
            bad.append(f"{_GWRITE}:{appt_cls.lineno} Appt несёт поля вне белого списка: "
                       f"{', '.join(sorted(got - _GWRITE_APPT)) or 'полей нет'}")
    keys_node = next((n.value for n in (gw.body if gw else ()) if isinstance(n, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == "EVENT_KEYS" for t in n.targets)), None)
    keys = {e.value for e in keys_node.elts if isinstance(e, ast.Constant)} \
        if isinstance(keys_node, (ast.Tuple, ast.List)) else set()
    if gw is not None and keys != _GWRITE_KEYS:
        bad.append(f"{_GWRITE}: EVENT_KEYS ≠ белому списку: {sorted(keys ^ _GWRITE_KEYS)}")
    body_fn = next((n for n in (gw.body if gw else ()) if isinstance(n, ast.FunctionDef) and n.name == "event_body"),
                   None)
    if gw is not None and body_fn is None:
        bad.append(f"{_GWRITE}: нет event_body — якорь правила пропал")

    def _dict_keys(d) -> set | None:
        return None if not isinstance(d, ast.Dict) or any(not isinstance(k, ast.Constant) for k in d.keys) \
            else {k.value for k in d.keys}

    if body_fn is not None:
        rets = [n.value for n in _walk(body_fn) if isinstance(n, ast.Return)]
        for r in rets or [None]:
            if _dict_keys(r) != keys:
                bad.append(f"{_GWRITE}:{body_fn.lineno} event_body отдаёт не словарь ровно из EVENT_KEYS")
                continue
            ext = dict(zip((k.value for k in r.keys), r.values)).get("extendedProperties")
            priv = dict(zip((k.value for k in ext.keys), ext.values)).get("private") \
                if _dict_keys(ext) == {"private"} else None
            if _dict_keys(priv) != _GWRITE_PRIVATE:
                bad.append(f"{_GWRITE}:{body_fn.lineno} частные свойства события — не только {sorted(_GWRITE_PRIVATE)}")
        for n in _walk(body_fn):
            if (isinstance(n, ast.Subscript) and isinstance(n.ctx, ast.Store)) or (
                    isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr in ("update", "setdefault")):
                bad.append(f"{_GWRITE}:{n.lineno} event_body дописывает тело после сборки")
    res.ok("тело события врача — белым списком", not bad, "; ".join(bad))

    gd = by_path.get(_GDOC)

    def _gd_gate(fn) -> list:
        return sorted(c.lineno for c in _walk(fn) if isinstance(c, ast.Call)
                      and ((isinstance(c.func, ast.Attribute) and c.func.attr == "feature_until")
                           or (isinstance(c.func, ast.Name) and c.func.id == "feature_until"))
                      and c.args and ((isinstance(c.args[0], ast.Constant) and c.args[0].value == _GDOC_GATE)
                                      or (isinstance(c.args[0], ast.Name) and c.args[0].id == "SYNC_GATE")
                                      or (isinstance(c.args[0], ast.Attribute) and c.args[0].attr == "SYNC_GATE")))

    bad = []
    sync = next((n.value.value for n in (gd.body if gd else ()) if isinstance(n, ast.Assign)
                 and isinstance(n.value, ast.Constant)
                 and any(isinstance(t, ast.Name) and t.id == "SYNC_GATE" for t in n.targets)), None)
    if sync != _GDOC_GATE:
        bad.append(f"{_GDOC}: SYNC_GATE ≠ «{_GDOC_GATE}» — якорь правила пропал")
    for rel, names in _GDOC_GATED.items():
        tree = by_path.get(rel)
        if tree is None:
            bad.append(f"{rel} — нет по этому пути")
            continue
        funcs = {n.name: n for n in _walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        for name in names:
            fn = funcs.get(name)
            if fn is None:
                bad.append(f"{rel}: нет функции {name} — список правила устарел")
                continue
            gates, net = _gd_gate(fn), _gl_calls(fn, _GDOC_NET)
            if not gates:
                bad.append(f"{rel}:{fn.lineno} {name} не спрашивает feature_until(\"{_GDOC_GATE}\")")
            elif net and net[0] < gates[0]:
                bad.append(f"{rel}:{net[0]} {name} идёт к Google раньше, чем спросил право")
            if any(isinstance(n, ast.Global) for n in _walk(fn)):
                bad.append(f"{rel}:{fn.lineno} {name} пишет глобальное — право не кэшируется")
        for n in tree.body:
            if isinstance(n, (ast.Assign, ast.AnnAssign)) and n.value is not None and _gd_gate(n):
                bad.append(f"{rel}:{n.lineno} право в имени модуля — кэш вместо вопроса")
    res.ok("дверь к Google врача спрашивает право gcal_doctor", not bad, "; ".join(bad))

    bad = []
    for rel in _GDOC_NO_REVOKE:
        tree = by_path.get(rel)
        if tree is None:
            bad.append(f"{rel} — нет по этому пути")
            continue
        for n in _walk(tree):
            if ((isinstance(n, ast.Name) and n.id in ("revoke", "REVOKE_URL"))
                    or (isinstance(n, ast.Attribute) and n.attr in ("revoke", "REVOKE_URL"))
                    or (isinstance(n, ast.alias) and n.name in ("revoke", "REVOKE_URL"))
                    or (isinstance(n, ast.Constant) and isinstance(n.value, str) and "/revoke" in n.value)):
                bad.append(f"{rel}:{getattr(n, 'lineno', '?')} отзыв у Google")
    res.ok("уход врача — без отзыва у Google", not bad, "; ".join(bad))

    # Ключ к календарю врача — только у двери: кто пишет в календари врачей (знает gwrite), тот не
    # знает DPAPI и клиента сборки, файл связи и внутренности двери не трогает.
    bad = []
    if gd is None:
        bad.append(f"{_GDOC} — нет по этому пути")
    gdoc_file = _file_name(_GDOC)

    def _knows(tree, name: str) -> bool:
        for n in _walk(tree):
            if not isinstance(n, (ast.Import, ast.ImportFrom)):
                continue
            targets = [m for m in _imported(n) if m]
            if getattr(n, "level", 0) or any(m.split(".")[0] == "app" for m in targets):
                if name in {m.split(".")[-1] for m in targets}:
                    return True
        return False

    for rel, tree in src:
        if rel == _GDOC:
            continue
        if _knows(tree, "gwrite"):
            for name in ("dpapi", "gclient"):
                if rel not in _GWRITE_KEYS_OK and _knows(tree, name):
                    bad.append(f"{rel} пишет в календари врачей и знает {name}")
            if rel not in _GWRITE_GAUTH_OK and _knows(tree, "gauth"):
                bad.append(f"{rel} пишет в календари врачей и знает gauth")
        for n in _walk(tree):
            if gdoc_file and isinstance(n, ast.Constant) and isinstance(n.value, str) and gdoc_file in n.value:
                bad.append(f"{rel}:{n.lineno} знает {gdoc_file}")
            if (isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "gdoc"
                    and (n.attr == "FILE_NAME" or n.attr.startswith("_"))):
                bad.append(f"{rel}:{n.lineno} лезет во внутренности двери: gdoc.{n.attr}")
    res.ok("к Google врача — только через дверь gdoc", not bad, "; ".join(bad))

    def _locked(node) -> bool:
        return isinstance(node, ast.AsyncWith) and any(
            isinstance(i.context_expr, ast.Call) and (
                (isinstance(i.context_expr.func, ast.Name) and i.context_expr.func.id == "lock")
                or (isinstance(i.context_expr.func, ast.Attribute) and i.context_expr.func.attr == "lock"))
            for i in node.items)

    bad = []
    if gd is not None:
        if not any(isinstance(n, ast.FunctionDef) and n.name == "_put" for n in gd.body):
            bad.append(f"{_GDOC}: нет _put — якорь правила пропал")
        under = {id(c) for w in _walk(gd) if _locked(w) for c in _walk(w)}
        bad += [f"{_GDOC}:{c.lineno} файл связи пишется не под замком врача" for c in _walk(gd)
                if isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id == "_put"
                and id(c) not in under]
    for rel, names in _GDOC_LOCKED.items():
        tree = by_path.get(rel)
        if tree is None:
            bad.append(f"{rel} — нет по этому пути")
            continue
        funcs = {n.name: n for n in _walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        for name in names:
            fn = funcs.get(name)
            if fn is None:
                bad.append(f"{rel}: нет функции {name} — список правила устарел")
            elif not any(_locked(w) for w in _walk(fn)):
                bad.append(f"{rel}:{fn.lineno} {name} не под замком врача (async with gdoc.lock)")
    res.ok("один замок врача на файл связи, уход и проход", not bad, "; ".join(bad))

    # ---- заказы лаунчеру подписаны (02.11, разбор коллеги Б2) ----
    # Папку данных пишет любая учётка Windows ПК, а заказ исполняет лаунчер
    # владельца. Исполнитель (`apply_pending`) обязан спросить подпись
    # (`orders.check`), а файл заказа пишется только подписанным
    # (`orders.write`): голый `write_text` в файл заказа — снова пустой
    # маркер, который положит и чужая учётка.
    bad = []
    for rel in ("app/core/dbkey.py", "app/core/restore.py"):
        tree = by_path.get(rel)
        fns = [n for n in _walk(tree) if isinstance(n, ast.FunctionDef)
               and n.name == "apply_pending"] if tree is not None else []
        if not fns:
            bad.append(f"{rel}: apply_pending не найдена")
        bad += [f"{rel}:{f.lineno}" for f in fns
                if not any(isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                           and c.func.attr == "check" and isinstance(c.func.value, ast.Name)
                           and c.func.value.id == "orders" for c in _walk(f))]
    res.ok("заказ лаунчеру исполняется только по подписи", not bad,
           "apply_pending без orders.check: " + ", ".join(bad))
    _ORDER_NAMES = {"DECRYPT_FILE", "PENDING_FILE", "REQUEST_FILE"}
    bad = []
    for rel, tree in src:
        for n in _walk(tree):
            if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr in ("write_text", "write_bytes")):
                continue
            names = {x.id if isinstance(x, ast.Name) else x.attr
                     for x in _walk(n.func.value)
                     if isinstance(x, (ast.Name, ast.Attribute))}
            if names & _ORDER_NAMES:
                bad.append(f"{rel}:{n.lineno}")
    res.ok("файл заказа лаунчеру пишется подписанным", not bad,
           "заказ записан мимо orders.write: " + ", ".join(bad))

    # main.py подключает роутеры модулей; обратный импорт замкнул бы круг.
    # Сегодня это упало бы и так, громко, — правило стоит здесь ради того, чтобы
    # его нельзя было «починить» отложенным импортом внутри функции.
    bad = [f"{rel}:{n.lineno}" for rel, tree in src
           if rel.startswith(("app/modules/", "app/core/"))
           for n in _walk(tree)
           if any(m.split(".")[-1] == "main" for m in _imported(n) if m)]
    res.ok("модуль не импортирует main", not bad,
           "модуль знает про main.py: " + ", ".join(bad))

    bad = [f"{rel}:{ln}" for rel, tree in src for ln, text in _templates(tree)
           if _INTER.search(text) and not any(d in text for d in _DECLARED)]
    res.ok("страница со своей вёрсткой объявляет шрифт", not bad,
           "просит 'Inter', не объявив его (__FONTS__ в <style>): "
           + ", ".join(bad))

    # ---- переприсваиваемое имя не импортируется по значению (14.10) ----
    # `from ..engine import CLINIC_NAME` копирует ЗНАЧЕНИЕ на миг импорта, а
    # `engine.apply_config` переприсваивает имя при сохранении настроек: модуль
    # показывал бы прежнее имя клиники до перезапуска — ни ошибки, ни следа.
    # С флагом режима хуже: `recovery._active` по значению — `False` навсегда,
    # и шлюз не пустил бы клинику с нечитаемым ключом к полю для кода.
    # ⭐ Какие имена переприсваиваются — считает разбор, а не список (список
    # имён, ВКЛЮЧАЮЩИХ требование, гниёт молча): имя под `global` в функции
    # модуля и имя, которому присваивают снаружи (`db.ACTOR_HOOK = …`).
    # Функции и классы импортировать по имени можно — их никто не подменяет.
    def _from_target(rel: str, n: ast.ImportFrom, name: str = "") -> str | None:
        """Файл, на который указывает `from … import`: модуль, а с `name` —
        модуль-имя внутри пакета. Чужие пакеты — None."""
        if n.level:
            base = rel.split("/")[:-1]
            base = base[:len(base) - (n.level - 1)]
        elif n.module and n.module.split(".")[0] == "app":
            base = []
        else:
            return None
        parts = base + (n.module.split(".") if n.module else []) + ([name] if name else [])
        for cand in ("/".join(parts) + ".py", "/".join(parts) + "/__init__.py"):
            if cand in by_path:
                return cand
        return None

    rebound: dict[str, set[str]] = {}
    for rel, tree in src:
        for g in _walk(tree):
            if isinstance(g, ast.Global):
                rebound.setdefault(rel, set()).update(g.names)
    for rel, tree in src:
        alias = {a.asname or a.name: f for n in _walk(tree) if isinstance(n, ast.ImportFrom)
                 for a in n.names if (f := _from_target(rel, n, a.name))}
        for n in _walk(tree):
            targets = (n.targets if isinstance(n, ast.Assign)
                       else [n.target] if isinstance(n, (ast.AugAssign, ast.AnnAssign)) else [])
            for tgt in targets:
                if (isinstance(tgt, ast.Attribute) and isinstance(tgt.value, ast.Name)
                        and tgt.value.id in alias):
                    rebound.setdefault(alias[tgt.value.id], set()).add(tgt.attr)
    # Якоря: оба пути разбора ещё видят то, ради чего написаны. Без них
    # сломанный обход нашёл бы ноль переприсваиваемых имён и позеленел навсегда.
    bad = [f"{f}: разбор не видит {name} — якорь правила пропал"
           for f, name in (("app/engine.py", "CLINIC_NAME"), (_DB_STATE, "ACTOR_HOOK"),
                            (_DB_STATE, "_CONN"))
           if name not in rebound.get(f, set())]
    bad += [f"{rel}:{n.lineno} {', '.join(sorted(hit))} из {f}"
            for rel, tree in src for n in _walk(tree) if isinstance(n, ast.ImportFrom)
            for f in [_from_target(rel, n)] if f
            for hit in [{a.name for a in n.names} & rebound.get(f, set())] if hit]
    res.ok("переприсваиваемое имя не импортируется по значению", not bad,
           "имя переприсваивается на ходу, а импорт заморозил его значение "
           "(читать как модуль.ИМЯ или функцией): " + "; ".join(bad))

    # ---- атрибуту db снаружи присваивают только состояние (03.11) ----
    # Пакет db: функции подмодулей зовут соседей СВОИМ именем (`from .conn
    # import _fetch`), а не `db._fetch`. Подмена `db.ИМЯ = …` (или setattr)
    # меняет только атрибут пакета — вызовы изнутри подмодулей её не видят, и
    # хук, тестовая подделка или «временная заплатка» молча не действуют.
    # Присваивать можно ровно состоянию, которое подмодули читают ЧЕРЕЗ пакет.
    _DB_REBINDABLE = {"_CONN", "_SQ", "ACTOR_HOOK"}
    bad = [f"{_DB_STATE}: {n}" for n in sorted(rebound.get(_DB_STATE, set()) - _DB_REBINDABLE)]
    for rel, tree in src:
        alias = {a.asname or a.name for n in _walk(tree) if isinstance(n, ast.ImportFrom)
                 for a in n.names if _from_target(rel, n, a.name) == _DB_STATE}
        bad += [f"{rel}:{n.lineno} {n.func.id}" for n in _walk(tree)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id in ("setattr", "delattr") and n.args
                and isinstance(n.args[0], ast.Name) and n.args[0].id in alias]
    if "ACTOR_HOOK" not in rebound.get(_DB_STATE, set()):
        bad.append("разбор не видит db.ACTOR_HOOK = … из main.py — якорь правила пропал")
    res.ok("атрибуту db снаружи присваивают только состояние", not bad,
           "подмена имени пакета db не дойдёт до вызовов из подмодулей (они зовут "
           "своё имя): " + "; ".join(bad))


    # ---- подмодуль db не держит переприсваиваемого состояния (03.11) ----
    # Пакет реэкспортирует каждое имя подмодуля (`from .teeth import …` в
    # __init__) — это КОПИЯ ссылки на миг импорта. Подмодуль, переприсвоивший
    # своё имя под `global`, разошёлся бы с `db.ИМЯ` молча: вызывающий читал бы
    # прежнее значение до перезапуска. Поэтому всё, что меняется на ходу, живёт
    # в __init__ (`_CONN`, `_SQ`, `ACTOR_HOOK`), а подмодули пишут и читают его
    # через пакет: `from .. import db`, `db._CONN = …`.
    pkg = [rel for rel in by_path if rel.startswith("app/db/") and rel != _DB_STATE]
    bad = [f"{rel}:{n.lineno} {', '.join(n.names)}" for rel in pkg
           for n in _walk(by_path[rel]) if isinstance(n, ast.Global)]
    if _DB_STATE not in by_path or not pkg:
        bad.append(f"{_DB_STATE} и подмодулей нет — якорь правила пропал")
    res.ok("подмодуль db не держит переприсваиваемого состояния", not bad,
           "global в подмодуле пакета db — реэкспорт `db.ИМЯ` останется "
           "прежним (состояние — в __init__, писать через `db.ИМЯ = …`): "
           + "; ".join(bad))


    # ---- ничего графического от Windows (08-11) ----
    # Эмодзи, стрелки, галочки и геометрию рисует ОПЕРАЦИОННАЯ СИСТЕМА своим
    # шрифтом: по-разному на 10 и 11, всегда цветными посреди сдержанного
    # экрана и мимо выбранного клиникой цвета. Вшитый Inter покрывает четыре
    # подмножества, и ни в одно из них не входят U+2192, U+25B2..U+25C0,
    # U+2714/U+2715, U+23F3 — то есть «не эмодзи» тут ничего не значит.
    # ⭐ Правило смотрит в СТРОКОВЫЕ ЛИТЕРАЛЫ, а не в файл: комментарии и
    # docstring'и до экрана не доезжают, и запрещать их незачем.
    # (До 03.11.2026 исключением были тексты бота — engine.py и telegram.py:
    # их рисовал Telegram на телефоне пациента. Бот удалён, исключения нет.)
    # ⚠️ Область — ВЕСЬ bot/, а не только modules/ и core/: тексты для
    # человека живут и вне modules/ и core/ — в пакете db (летопись), в update.py
    # (экран и лог обновления), до 14.10 и в main.py (вход, установка PIN,
    # весь режим восстановления). Префиксный фильтр держался
    # тут не по решению, и под ним пережили все релизы ✅ на экране
    # восстановления и две стрелки → в текстах летописи (тогда db.py). Заодно в область попадают
    # строки лога: знак в них безвреден, но и не нужен, а исключение по «это
    # лог» пришлось бы угадывать по имени функции.
    bad = []
    for rel, tree in src:
        for ln, text in _ui_texts(tree):
            found = "".join(dict.fromkeys(_SYSGLYPH.findall(text)))
            if found:
                bad.append(f"{rel}:{ln} {found}")
    res.ok("интерфейс не просит знаки у Windows", not bad,
           "рисует системным шрифтом (нужна иконка из core/icons._I): "
           + "; ".join(bad[:8]))

    # ⚠️ Забытый импорт `_ic` не виден ни глазами, ни этим набором иначе:
    # вызов в ветке `if meta.get("room")` на демо-профиле просто не исполняется,
    # страница открывается, а у клиники с заполненным кабинетом падает. Ровно
    # так и случилось 08-11 со списком врачей.
    bad = []
    for rel, tree in src:
        text = (BOT / rel).read_text(encoding="utf-8")
        if not re.search(r"(?<![A-Za-z_])_ic\(", text) or "def _ic(" in text:
            continue
        names = {a.asname or a.name for n in _walk(tree)
                 if isinstance(n, ast.ImportFrom) for a in n.names}
        if "_ic" not in names:
            bad.append(rel)
    res.ok("кто зовёт _ic — тот его импортирует", not bad,
           "вызывает _ic без импорта: " + ", ".join(bad))

    # ⚠️ Тот же вызов, забытый f-префиксом, не падает ВООБЩЕ: строка уезжает на
    # экран как есть, и заголовок раздела читается «{_ic('wifi')} Acces din
    # rețea». Ни ошибки, ни пустого места, ни следа в логе — глазами это
    # переживает и ревью, и релиз: так `settings/lan.py` прожил от 1.15.0 до
    # 1.19.23 (нашлось 08-13, когда страницу открыли по другому поводу).
    # Ловится только текстом литерала: f-строка разбирается парсером, и
    # заполнитель в её частях не остаётся, — значит `{_ic(` уцелел ровно там,
    # где префикс забыли.
    bad = [f"{rel}:{ln}" for rel, tree in src for ln, text in _ui_texts(tree)
           if "{_ic(" in text]
    res.ok("вызов _ic не остаётся текстом", not bad,
           "строка без f-префикса — знак уедет на экран как есть: "
           + ", ".join(bad))

    # ⚠️ «Данные лежат в папке программы» перестало быть правдой с переездом
    # в `Program Files` (P1): папка клиники теперь `%ProgramData%\DentPilot`
    # либо, у портативной, рядом с exe — решает ЛАУНЧЕР, а не положение
    # файла. Поведение поменяли, а семь текстов остались, и ни один экран от
    # неверного адреса не падает: расхождение пережило релиз молча.
    # ⛔ Дороже всех эта фраза стоит в CITESTE-MA.txt внутри вывозного архива
    # — её читают ровно тогда, когда данных на машине больше нет и сверить
    # не с чем. Распаковка в папку программы даёт пустой журнал БЕЗ единой
    # ошибки, и выглядит это как «архив оказался пустым».
    # ⭐ Поэтому правило на саму фразу: раскладку больше не пересказывают
    # словами, а показывают настоящий путь (`layout.data_folder`).
    # ⚠️ 27.09: правило читало только литералы Python и одну формулировку — и
    # пять текстов пережили его. Подсказки документов фиши и фото врача в
    # клиенте (с 21.09 их рисует React, а в клиент сторож не смотрел); мастер
    # установки, обещавший на странице выбора папки базу «chiar lângă program»
    # каждой НОВОЙ клинике; баннер фото врача (другими словами — «lângă
    # program»); подсказка старой фиши (фраза разорвана переносом строки).
    # Отсюда три области — сервер, клиент, мастер — и фразы выражением
    # `_DATA_PLACE`, а не подстрокой.
    # ⚠️ Полярность опасная: клиент и мастер обязаны НАЙТИСЬ, иначе правило
    # зелено на пустом месте.
    bad, used, client, scripts = [], set(), 0, 0

    def _data_place(where: str, text: str) -> list[int]:
        """Смещения фраз в тексте — за вычетом прощённых кусков."""
        for ok in _OLD_LAYOUT_OK.get(where, ()):
            if ok in text:
                used.add((where, ok))
                text = text.replace(ok, " " * len(ok))
        return [m.start() for m in _DATA_PLACE.finditer(text)]

    bad += [f"{rel}:{ln}" for rel, tree in src for ln, text in _ui_texts(tree)
            if _data_place(rel, text)]
    for f in sorted(FRONTEND.rglob("*.ts*")) if FRONTEND.exists() else []:
        rel = f.relative_to(FRONTEND).as_posix()
        if (f.suffix not in (".ts", ".tsx") or ".test." in f.name
                or rel.startswith("test/")):
            continue
        client += 1
        where = f"frontend/src/{rel}"
        code = _client_code(f.read_text(encoding="utf-8"))
        bad += [f"{where}:{code.count(chr(10), 0, p) + 1}"
                for p in _data_place(where, code)]
    for f in sorted(INSTALLER.glob("*.iss")) if INSTALLER.exists() else []:
        scripts += 1
        where = f"installer/{f.name}"
        bad += [f"{where}:{ln}"
                for ln, text in _iss_texts(f.read_text(encoding="utf-8-sig"))
                if _data_place(where, text)]
    if client < 20:
        bad.append(f"файлов клиента нашлось {client} — обход сломан, правило пусто")
    if not scripts:
        bad.append(f"в {INSTALLER} нет ни одного .iss — обход сломан, правило пусто")
    bad += [f"прощение протухло: в {where} больше нет «{ok}»"
            for where, oks in _OLD_LAYOUT_OK.items() for ok in oks
            if (where, ok) not in used]
    res.ok("интерфейс не обещает данные в папке программы", not bad,
           "с переезда в Program Files данные лежат не там (paths.data_root): "
           "где есть путь — layout.data_folder, где нет — «local, pe acest "
           "calculator»: " + ", ".join(bad))

    # ---- ответ на действие строит только core/messages (08-14) ----
    # msg_banner в core/messages — единственное место, где код из ?msg= становится
    # разметкой: плашка ПЛАВАЕТ поверх окна, потому что форма записи стоит
    # внизу страницы, а 303 открывает её с нулевой прокруткой — баннер в потоке
    # клиника не увидела («сказали ок, а что случилось — не поняли»). Модуль,
    # собравший баннер из словаря сам, вернул бы сообщение в поток, и на
    # коротких страницах разработчика это невидимо.
    # ⚠️ Полярность опасная: правило ищет ИМЯ, и после переименования словаря
    # оно позеленело бы навсегда — поэтому сперва якорь «словарь ещё есть».
    msg_tree = by_path.get(_LAY_MSG)
    has_dict = msg_tree is not None and any(
        isinstance(n, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "MSG_BANNER" for t in n.targets)
        for n in _walk(msg_tree))
    bad = [] if has_dict else [f"{_LAY_MSG}: словарь MSG_BANNER не найден"]
    # ⚠️ Список ВКЛЮЧАЕТ разрешение: файл, переставший читать словарь, не должен
    # оставаться в нём молча (список шире нужного прощал бы новое чтение там).
    bad += [f"{rel}: допущен к MSG_BANNER, но его не читает — убрать из _MSG_READERS"
            for rel in _MSG_READERS
            if not any(isinstance(n, ast.Name) and n.id == "MSG_BANNER"
                       for n in _walk(by_path.get(rel) or ast.parse("")))]
    bad += [f"{rel}:{n.lineno}" for rel, tree in src
            if rel not in _MSG_READERS
            for n in _walk(tree)
            if (isinstance(n, ast.Name) and n.id == "MSG_BANNER")
            or (isinstance(n, ast.ImportFrom)
                and any(a.name == "MSG_BANNER" for a in n.names))]
    res.ok("ответ на действие строит только core/messages", not bad,
           "MSG_BANNER вне core/messages — сообщение вернётся строкой в "
           "поток, и внизу страницы его опять не видно: " + ", ".join(bad))

    # ---- откуда пациент — одно правило и один словарь ----
    # Канал фиши выводился трижды (Python списка, SQL фильтра, своя функция шапки
    # фиши), и все три копии называли «web» каждую фишу, которая не tg: и не
    # manual:, — а фиши импорта и переноса из Google (ключ manual:) звались
    # «recepție». Теперь вывод — `ORIGIN_SQL` (фильтр, колонка списка, шапка,
    # пункты фильтра), подписи — `ORIGIN_LABEL`. Копия правила по префиксу ключа
    # (`startswith("tg:")`, `substr(… session_key …)`) вне plist.py снова
    # разошлась бы с ним молча; ключ ветки без подписи уехал бы на экран кодом.
    # ⚠️ Полярность: правило ищет нарушителей — поэтому сперва якоря: выражение
    # и словарь есть, их ключи совпадают.
    def _const_of(tree, name):
        for n in _walk(tree or ast.parse("")):
            if (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name
                                                  for t in n.targets)):
                return n.value
        return None
    o_sql = _const_of(by_path.get(_DB_ORIGIN), "ORIGIN_SQL")
    o_lab = _const_of(by_path.get(_LAY_LABELS), "ORIGIN_LABEL")
    bad = []
    if not (isinstance(o_sql, ast.Constant) and isinstance(o_sql.value, str)):
        bad.append(f"{_DB_ORIGIN}: строки ORIGIN_SQL нет")
    if not isinstance(o_lab, ast.Dict):
        bad.append(f"{_LAY_LABELS}: словаря ORIGIN_LABEL нет")
    if not bad:
        branches = set(re.findall(r"(?:THEN|ELSE) '(\w+)'", o_sql.value))
        labels = {k.value for k in o_lab.keys if isinstance(k, ast.Constant)}
        if not branches or branches != labels:
            bad.append(f"ветки ORIGIN_SQL {sorted(branches)} ≠ ключи ORIGIN_LABEL {sorted(labels)}")
    _prefixes = ("tg:", "web:", "manual:")
    bad += [f"{rel}:{n.lineno}" for rel, tree in src if rel != _DB_ORIGIN
            for n in _walk(tree)
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "startswith" and n.args
                and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str)
                and n.args[0].value.startswith(_prefixes))
            or (isinstance(n, ast.Constant) and isinstance(n.value, str)
                and "substr(" in n.value and "session_key" in n.value)]
    bad += [f"{rel}:{n.lineno}" for rel, tree in src if rel != _LAY_LABELS
            for n in _walk(tree)
            if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "ORIGIN_LABEL"
                                                 for t in n.targets)]
    res.ok("откуда пациент — ORIGIN_SQL и ORIGIN_LABEL", not bad,
           "канал фиши выводится одним выражением db/plist.ORIGIN_SQL, подписи — "
           "core/labels.ORIGIN_LABEL: " + ", ".join(bad))

    # ---- JSON рядом с <script> — только в экранированный атрибут (08-10, 04.11) ----
    # Аудит 08-10: на карточке пациента четыре площадки экранировали `</`, а две
    # нет, и незащищённым оказалось имя врача — поле, которое правит регистратура,
    # МЛАДШАЯ роль; скрипт оттуда выполнялся в сессии директора. `json.dumps`
    # безопасен для JavaScript, но не для HTML: `</script>` в значении закрывает тег.
    # С React данные страница получает ТОЛЬКО атрибутом `data-shell`/`data-params`
    # (`layout.react_shell`), поэтому правило теперь такое: в файле, печатающем
    # `<script`, каждый `json.dumps` — прямой аргумент `html.escape(…, quote=True)`.
    # (До 04.11 правило жило в test_anamneza и пропускало единственный файл с
    # `<script`, то есть не проверяло ничего.)
    # ⚠️ Полярность: «нарушителей нет» зеленеет на пустоте, поэтому якорь — такой
    # вызов обязан найтись; всё, что печатает модель страницы, идёт им.
    bad, esc_seen = [], 0
    for rel, tree in src:
        if "<script" not in (BOT / rel).read_text(encoding="utf-8"):
            continue
        aliases = {t.id for n in _walk(tree) if isinstance(n, ast.Assign)
                   and isinstance(n.value, ast.Attribute) and n.value.attr == "escape"
                   for t in n.targets if isinstance(t, ast.Name)}

        def _is_escape(call: ast.Call) -> bool:
            f = call.func
            named = ((isinstance(f, ast.Attribute) and f.attr == "escape"
                      and isinstance(f.value, ast.Name) and f.value.id == "html")
                     or (isinstance(f, ast.Name) and f.id in aliases))
            return named and any(k.arg == "quote" and getattr(k.value, "value", None) is True
                                 for k in call.keywords)

        guarded = set()
        for n in _walk(tree):
            if isinstance(n, ast.Call) and _is_escape(n):
                guarded.update(id(a) for a in n.args)
        for n in _walk(tree):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "dumps" and getattr(n.func.value, "id", "") == "json"):
                if id(n) in guarded:
                    esc_seen += 1
                else:
                    bad.append(f"{rel}:{n.lineno}")
    if not esc_seen:
        bad.append("json.dumps под html.escape(quote=True) не найден — якорь правила пропал")
    res.ok("JSON рядом с <script> — только экранированным атрибутом", not bad,
           "незащищённые площадки: " + ", ".join(bad))

    # ---- соседи layout ниже него (разнос 04.11) ----
    # layout реэкспортирует имена соседей и зовёт их функции; импорт layout соседом
    # на уровне модуля замкнул бы круг, и проявился бы он только при неудачном порядке
    # импорта — у одного входа, а не у всех. Отложенный импорт внутри функции законен:
    # так берут слова `db`, `auth`, `orders`, `backup_loop`.
    bad = []
    for rel in _LAY_BELOW:
        tree = by_path.get(rel)
        if tree is None:
            bad.append(f"{rel}: файла нет — якорь правила пропал")
            continue
        stack = list(tree.body)
        while stack:
            n = stack.pop()
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue
            stack.extend(ast.iter_child_nodes(n))
            if (isinstance(n, ast.ImportFrom)
                    and ((n.module or "").split(".")[-1] == "layout"
                         or any(a.name == "layout" for a in n.names))):
                bad.append(f"{rel}:{n.lineno}")
            elif isinstance(n, ast.Import) and any(a.name.split(".")[-1] == "layout" for a in n.names):
                bad.append(f"{rel}:{n.lineno}")
    res.ok("соседи layout не импортируют его на уровне модуля", not bad,
           "замкнётся круг импортов: " + ", ".join(bad))

    # ---- миграции db: версия схемы и schema_meta (08-15) ----
    # Шаг, добавленный в словари миграций без поднятия SCHEMA_VERSION, — мёртвый
    # код: цикл _migrate идёт range(have+1, SCHEMA_VERSION+1) и до него не
    # доходит, а страж «missing migration step» ловит только отсутствующие
    # шаги, не лишние. Ровно так шаг 4 ('waiting' в предикатах uq-индексов) не
    # исполнялся ни у одной клиники с 08-13 — молча: база «домигрирована»,
    # лог чист, страховки от двойной брони на waiting-визите нет.
    # ⚠️ Полярность опасная: правило ищет ИМЕНА. Переименуют SCHEMA_VERSION или
    # словарь — искать станет нечего, поэтому «не нашлось» здесь тоже красное.
    db_tree = by_path.get(_DB_SCHEMA)
    consts, dictkeys = {}, {}
    for n in _walk(db_tree or ast.Module(body=[], type_ignores=[])):
        if not (isinstance(n, ast.Assign) and len(n.targets) == 1
                and isinstance(n.targets[0], ast.Name)):
            continue
        name = n.targets[0].id
        if isinstance(n.value, ast.Constant):
            consts[name] = n.value.value
        elif isinstance(n.value, ast.Dict):
            dictkeys[name] = [k.value for k in n.value.keys
                              if isinstance(k, ast.Constant)]
    ver = consts.get("SCHEMA_VERSION")
    steps = dictkeys.get("MIGRATIONS")
    res.ok("версия схемы равна последнему шагу миграций",
           isinstance(ver, int) and bool(steps) and max(steps) == ver,
           f"SCHEMA_VERSION={ver!r}, max(MIGRATIONS)="
           f"{max(steps) if steps else None} — лишний шаг не исполнится ни у "
           f"одной клиники, недостающий уронит _migrate")

    # ---- индексы врача: кабинет в ключе ----
    # Без кабинета в ключе индекс запрещает врачу вторую запись в другом кабинете.
    # Имена — отдельным списком с проверкой, что оба лежат в `_uq_slot_sql`:
    # пропавшее имя правило искало бы впустую и позеленело бы навсегда.
    keyed, plain = set(), []
    for rel, tree in src:
        if rel != _DB_SLOTS:
            continue
        for ln, text in _templates(tree):
            if "CREATE UNIQUE INDEX" not in text.upper() or "_uq_slot_sql" not in _enclosing(tree, ln):
                continue
            for name in _UQ_DOCTOR:
                if f"INDEX {name}" in text:
                    keyed.add(name)
                    if "room_id" not in text:
                        plain.append(f"{name} ({rel}:{ln})")
    res.ok("у индексов врача кабинет в ключе",
           not plain and keyed == set(_UQ_DOCTOR),
           ("без кабинета в ключе: " + ", ".join(plain) if plain else
            f"в _uq_slot_sql найдены не оба индекса врача: {sorted(keyed)} — якорь "
            f"правила пропал")
           + " — врач с двумя кабинетами не сможет вести две записи на один час")

    # ---- слотовые uq-индексы: ОДИН владелец (08-16) ----
    # CREATE UNIQUE INDEX по слоту — операция НАД ЖИВЫМИ ДАННЫМИ, а не над
    # схемой: у клиники с двойной бронью он ПАДАЕТ. В базовой схеме (она идёт
    # при каждом старте) или в обычном шаге миграции такое падение значит, что
    # программа не открывается, и навсегда: версия схемы не растёт. Ровно так
    # уехала 1.20.0. Поэтому текст этих индексов живёт в ОДНОМ месте —
    # `_uq_slot_sql`, — а зовёт его только `_slot_guard_apply`, который сначала
    # спрашивает данные и при конфликте кладёт прежний узкий предикат.
    # ⚠️ Полярность опасная: правило ищет ТЕКСТ. Пропадут литералы — сверять
    # станет нечего и правило позеленеет навсегда, поэтому «якорь пропал» здесь
    # тоже красное.
    bad, anchor = [], 0
    for rel, tree in src:
        for ln, text in _templates(tree):
            if "CREATE UNIQUE INDEX" not in text.upper():
                continue
            if not any(n in text for n in _UQ_NAMES):
                continue
            if rel == _DB_SLOTS and "_uq_slot_sql" in _enclosing(tree, ln):
                anchor += 1
                continue
            bad.append(f"{rel}:{ln}")
    if not anchor:
        bad.append("текста слотовых индексов нет в _uq_slot_sql — якорь правила "
                   "пропал, сверять не с чем")
    res.ok("слотовые uq-индексы кладёт один владелец", not bad,
           "CREATE UNIQUE INDEX по слоту вне _uq_slot_sql: " + ", ".join(bad)
           + " — этот CREATE упадёт у клиники с двойной бронью там, куда "
             "сторож не доживает, и программа больше не откроется")

    # ---- длительность: одно правило допустимости ----
    # Нарушение — сверка `in`/`not in` со списком быстрых значений или с
    # литералом минут. Правило ищет ИМЯ, поэтому якорь — `dur_ok` есть и его
    # спрашивают оба входа.
    def _minutes(node: ast.AST) -> bool:
        if not isinstance(node, (ast.Tuple, ast.List, ast.Set)) or len(node.elts) < 3:
            return False
        vals = [e.value for e in node.elts
                if isinstance(e, ast.Constant) and type(e.value) is int]
        return len(vals) == len(node.elts) and all(
            5 <= v <= 480 and v % 5 == 0 for v in vals)

    bad = []
    for rel, tree in src:
        if rel == "app/engine.py":
            continue
        for node in _walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            for op, right in zip(node.ops, node.comparators):
                if not isinstance(op, (ast.In, ast.NotIn)):
                    continue
                if (isinstance(right, ast.Attribute) and right.attr == "DURATIONS") \
                        or (isinstance(right, ast.Name) and right.id.endswith("DURATIONS")) \
                        or _minutes(right):
                    bad.append(f"{rel}:{node.lineno}")
    eng_tree = by_path.get("app/engine.py")
    has_rule = eng_tree is not None and any(
        isinstance(n, ast.FunctionDef) and n.name == "dur_ok" for n in eng_tree.body)
    if not has_rule:
        bad.append("в app/engine.py нет dur_ok — якорь правила пропал")
    for rel in _DUR_ASKERS:
        tree = by_path.get(rel)
        if tree is None or "dur_ok" not in _calls(tree):
            bad.append(f"{rel} не спрашивает dur_ok")
    res.ok("допустимость длительности спрашивают у dur_ok", not bad,
           "длительность сверяют со своим списком: " + ", ".join(bad)
           + " — два списка разойдутся молча, и одна дверь примет длительность, "
             "которую отвергает другая")

    bad = []
    if eng_tree is None or not any(isinstance(n, ast.FunctionDef) and n.name == "in_agenda"
                                   for n in eng_tree.body):
        bad.append("в app/engine.py нет in_agenda — якорь правила пропал")
    for rel, fname in _AGENDA_READERS:
        tree = by_path.get(rel)
        fn = next((n for n in _walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                   and n.name == fname), None) if tree is not None else None
        if fn is None:
            bad.append(f"{rel}:{fname} не нашлась — список устарел")
            continue
        names = {n.attr for n in _walk(fn) if isinstance(n, ast.Attribute)}
        if not names & {"in_agenda", "WHERE_AGENDA"}:
            bad.append(f"{rel}:{fname}")
    res.ok("читатели агенды спрашивают in_agenda", not bad,
           "услугу агенды берут без места: " + ", ".join(bad)
           + " — строка только прайса плана уедет в окно записи типом визита")

    def _int_const(tree: ast.Module | None, name: str) -> int | None:
        for n in (tree.body if tree is not None else []):
            if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant) \
                    and type(n.value.value) is int \
                    and any(isinstance(t, ast.Name) and t.id == name for t in n.targets):
                return n.value.value
        return None

    dur_max = _int_const(eng_tree, "DUR_MAX")
    # соседей ищут две выборки (врача и кабинета): узкое окно любой из них
    # прячет длинный визит
    pads = []
    for n in _walk(by_path.get(_DB_SLOTS) or ast.Module(body=[], type_ignores=[])):
        if isinstance(n, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "pad" for t in n.targets) \
                and isinstance(n.value, ast.Call):
            for kw in n.value.keywords:
                if kw.arg == "minutes" and isinstance(kw.value, ast.Constant):
                    pads.append(kw.value.value)
    pad = min(pads) if pads else None
    res.ok("потолок длительности не выходит за окно поиска соседей",
           isinstance(dur_max, int) and isinstance(pad, int) and dur_max <= pad,
           f"eng.DUR_MAX = {dur_max}, самое узкое окно `pad` в db/slots = {pad}: "
           f"визит длиннее окна проверка занятости не увидит")

    # ---- замок брони: только через _slot_lock (08-20, аудит) ----
    # Одна точка входа у всех, кто занимает слот: появится второй процесс над
    # той же базой (как было у Postgres-издания до 12.10) — замок меняется в
    # ОДНОМ месте, а не ищется по всем путям брони.
    # ⚠️ Полярность опасная: правило ищет ИМЕНА, поэтому якорь — сам _slot_lock
    # существует.
    bad = []
    slot_fn = next((n for n in _walk(by_path.get(_DB_SLOTS)
                                        or ast.Module(body=[], type_ignores=[]))
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and n.name == "_slot_lock"), None)
    if slot_fn is None:
        bad.append(f"{_DB_SLOTS}: _slot_lock не найден — якорь правила пропал")
    for rel, tree in src:
        for n in _walk(tree):
            # ЛЮБОЕ обращение к имени, не только with-форма: прямой
            # `await _BOOK_LOCK.acquire()` или передача замка дальше обходили
            # бы сторож, смотревший на одни with (ревью 08-22). Определение
            # (`_BOOK_LOCK = asyncio.Lock()`) — Name в Store, пропускается;
            # у Attribute (db._BOOK_LOCK извне) запрещён и Store.
            name_use = (isinstance(n, ast.Name) and n.id == "_BOOK_LOCK"
                        and isinstance(n.ctx, ast.Load))
            attr_use = isinstance(n, ast.Attribute) and n.attr == "_BOOK_LOCK"
            if not (name_use or attr_use):
                continue
            if rel == _DB_SLOTS and "_slot_lock" in _enclosing(tree, n.lineno):
                continue
            bad.append(f"{rel}:{n.lineno}")
    res.ok("замок брони берётся только через _slot_lock", not bad,
           "_BOOK_LOCK взят напрямую — путь брони мимо общей точки входа: "
           + "; ".join(bad))

    # ---- диапазон PIN в текстах — только функцией (08-15, 17.10) ----
    # PIN_MIN/PIN_MAX живут в core/auth.py и уже поднимались (4–6 → 4–8,
    # 08-13). Текст, назвавший диапазон числами, при этом отстаёт МОЛЧА:
    # баннер «nu are 4–6 cifre» отговаривал от разрешённых 7–8 цифр, а экран
    # первой установки противоречил сам себе. С 17.10 минимум ещё и ЗАВИСИТ
    # ОТ СЕТИ (`auth.pin_min`: 6 при включённом «Acces din rețea»), поэтому
    # числами диапазон не пишется нигде: ни литералом, ни f-строкой с
    # константами (словарь MSG_BANNER — импорт, он заморозил бы старое).
    # Правило: в UI-текстах нет «N–M cifre» (докстринги и комментарии до
    # экрана не доезжают — их правило пропускает); единственный владелец
    # диапазона — `auth.pin_range_text`, и экран первой установки зовёт её.
    # ⚠️ Полярность: правило «нарушителей нет» зеленеет на пустоте, поэтому
    # якорь — вызов `pin_range_text(` в entry/routes.py обязан найтись.
    rng_re = re.compile(r"(\d+)\s*[–—-]\s*(\d+)\s+cifre")
    bad = []
    for rel, tree in src:
        for ln, text in _ui_texts(tree):
            for m in rng_re.finditer(text):
                bad.append(f"{rel}:{ln} «{m.group(0)}»")
    entry_tree = by_path.get("app/modules/entry/routes.py")
    anchored = any(isinstance(n, ast.Call) and getattr(n.func, "id", "") == "pin_range_text"
                   for n in _walk(entry_tree or ast.Module(body=[], type_ignores=[])))
    if not anchored:
        bad.append("entry/routes.py не зовёт pin_range_text — якорь правила пропал")
    res.ok("диапазон PIN в текстах — только auth.pin_range_text (зависит от сети)",
           not bad, "диапазон числами застынет при смене минимума: " + "; ".join(bad))

    # В schema_meta безусловно пишут _set_schema_version, set_meta и backfill —
    # таблица обязана создаваться схемой. Из схемы Postgres-издания её однажды
    # удалили случайно (434513c), и оно переставало стартовать на свежей базе.
    need = "CREATE TABLE IF NOT EXISTS schema_meta("
    res.ok("schema_meta создаётся схемой",
           any(need in str(consts.get(v, ""))
               for v in ("SQLITE_SCHEMA", "SQLITE_CARD_SCHEMA")),
           "нет CREATE TABLE schema_meta в SQLITE_SCHEMA/SQLITE_CARD_SCHEMA — "
           "программа не стартует на пустой базе")

    # ---- маршруты /api/* охраняет api_guard / api_require (09-17, 2.0) ----
    # HTML-охрана (_guard/require) отвечает 303 на /admin/login. fetch сходит
    # за редиректом сам и вернёт клиенту 200 с формой входа — экран покажет
    # пустоту вместо «сессия истекла», а регистратура решит, что у пациента
    # нет записей. Поэтому у JSON API своя пара в core/api.py, и каждый
    # маршрут под /api/ зовёт её. Неохраняемый маршрут — тоже нарушитель:
    # он отдал бы данные без входа.
    # ⚠️ Полярность опасная: правило ищет ИМЕНА. Якорей два — пара определена
    # в core/api.py, и хотя бы один маршрут /api/ существует.
    bad, n_api, doors, door_bad = [], 0, set(), []
    api_tree = by_path.get("app/core/api.py")
    api_defs = {fn.name for fn in _walk(api_tree or ast.Module(body=[], type_ignores=[]))
                if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))}
    if not {"api_guard", "api_require"} <= api_defs:
        bad.append("app/core/api.py: нет api_guard/api_require — якорь правила пропал")
    for rel, tree in src:
        for fn in _walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            routes = [d.args[0].value for d in fn.decorator_list
                      if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                      and d.func.attr in ("get", "post", "put", "delete", "patch")
                      and d.args and isinstance(d.args[0], ast.Constant)
                      and isinstance(d.args[0].value, str)]
            if not any(p.startswith("/api/") for p in routes):
                continue
            n_api += 1
            called = _calls(fn)
            if any(p in _API_OPEN for p in routes):
                # дверь: куки ещё нет, охрана заперла бы вход; защищает Origin
                doors.update(p for p in routes if p in _API_OPEN)
                if called & {"api_guard", "api_require"}:
                    door_bad.append(f"{rel}:{fn.lineno} {fn.name}() под охраной — "
                                    "войти через неё нельзя")
                if "same_origin_post" not in called:
                    door_bad.append(f"{rel}:{fn.lineno} {fn.name}() без same_origin_post "
                                    "— чужой сайт переберёт PIN и запрёт вход")
                continue
            if not called & {"api_guard", "api_require"}:
                bad.append(f"{rel}:{fn.lineno} {fn.name}() без api_guard/api_require")
            if called & {"_guard", "require"}:
                bad.append(f"{rel}:{fn.lineno} {fn.name}() зовёт HTML-охрану "
                           "(303 вместо JSON)")
    if not n_api:
        bad.append("ни одного маршрута /api/ — якорь правила пропал")
    res.ok("маршруты /api/ охраняет api_guard/api_require", not bad,
           "fetch получит 303 и покажет пустой экран вместо «сессия истекла»: "
           + "; ".join(bad))
    # ---- дверь под /api/ (B4.4, 16.10): без охраны, но со сверкой Origin ----
    # Вход JSON-ом (смена человека без перезагрузки) — единственный маршрут
    # `/api/`, куда приходят БЕЗ куки. Якорь — каждая дверь из `_API_OPEN`
    # нашлась среди маршрутов: иначе список прощал бы несуществующий адрес.
    door_bad += [f"{p}: двери нет среди маршрутов — _API_OPEN протух"
                 for p in sorted(_API_OPEN - doors)]
    res.ok("дверь /api/auth/login: без охраны, но со сверкой Origin", not door_bad,
           "; ".join(door_bad))

    # ---- команда к визиту журнала спрашивает, чей он (22.10, права врача) ----
    # Врач видит и правит только свои визиты. Модели режутся по `visits.mine`,
    # но адрес команды набирается руками, а вкладка живёт долго, поэтому каждая
    # команда К СТОЯЩЕМУ визиту — `/api/schedule/appointments/{id}/…` и отметка
    # звонка `/api/schedule/desk/call/{aid}` — обязана спросить `api_own_appt`
    # ДО правила. Новый маршрут команды (так появилась `…/service` 22.10) без
    # этого вызова молча открыл бы врачу чужой визит: ответ — «успех», экран
    # цел, и красным это ловится только здесь.
    # ⚠️ Полярность опасная: ищутся ИМЕНА. Якорей два — `api_own_appt` определён
    # в core/api.py, и маршрутов команд нашлось не меньше пяти.
    bad, n_cmd = [], 0
    if "api_own_appt" not in api_defs:
        bad.append("app/core/api.py: нет api_own_appt — якорь правила пропал")
    cmd_re = re.compile(r"^/api/schedule/(appointments|desk/call)/\{")
    for rel, tree in src:
        for fn in _walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            routes = [d.args[0].value for d in fn.decorator_list
                      if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                      and d.func.attr in ("get", "post", "put", "delete", "patch")
                      and d.args and isinstance(d.args[0], ast.Constant)
                      and isinstance(d.args[0].value, str)]
            if not any(cmd_re.match(p) for p in routes):
                continue
            n_cmd += 1
            if "api_own_appt" not in _calls(fn):
                bad.append(f"{rel}:{fn.lineno} {fn.name}() не спрашивает api_own_appt")
    if n_cmd < 5:
        bad.append(f"маршрутов команд к визиту нашлось {n_cmd} — якорь правила пропал")
    res.ok("команда к визиту журнала спрашивает, чей он", not bad,
           "врач с телефона тронул бы чужой визит адресом: " + "; ".join(bad))

    # ---- обрезок не носит имени полного значения (C26.5.2) ----
    # Один и тот же текст живёт в нескольких длинах: комментарий — 80 в списке
    # дня, 60 в карточке сетки, полный в базе; заметка — 80 в подсказке, 40 в
    # блоке. Пока обрезок звался так же, как полное значение, взять не тот было
    # нечем помешать: оба `str`, и типы не возражают. Цена названа опытом
    # 19.09 — правка комментария ПОСЛЕ 60-го знака не меняла живых данных, и
    # второе рабочее место получало `204` «день не менялся»; а диалог,
    # накормленный таким полем, записал бы обрезок обратно (08-16).
    # ⭐ Правило простое: значение, собранное срезом с постоянной границей, не
    # имеет права называться именем целого. Разрешены `title`/`label` — это
    # имена МЕСТА показа (подсказка и подпись блока), а не имена значения.
    # ⚠️ Полярность опасная: правило ищет ФОРМУ (срез с числом). Якоря два, оба
    # на неё — известный ключ в словаре и известный ключ в присваивании.
    cut_files = ("app/modules/schedule/day.py", "app/modules/schedule/canvas.py",
                 "app/modules/schedule/panel.py", "app/modules/schedule/week.py",
                 "app/core/visits.py")
    bad_cut, seen_cut = [], {}

    def _sliced(node) -> bool:
        """`что-то[:ЧИСЛО]` — срез с постоянной границей, то есть обрезок."""
        return (isinstance(node, ast.Subscript)
                and isinstance(node.slice, ast.Slice)
                and isinstance(node.slice.upper, ast.Constant)
                and isinstance(node.slice.upper.value, int))

    for rel in cut_files:
        tree = by_path.get(rel)
        if tree is None:
            bad_cut.append(f"{rel}: файла нет — якорь правила пропал")
            continue
        found = set()
        for node in _walk(tree):
            pairs = []
            if isinstance(node, ast.Dict):
                pairs = [(k.value, v) for k, v in zip(node.keys, node.values)
                         if isinstance(k, ast.Constant) and isinstance(k.value, str)]
            elif isinstance(node, ast.Assign) and len(node.targets) == 1:
                # ⚠️ Вторая форма обязательна: `v["title"] = r["service"][:80]`
                # в canvas.py — это НЕ словарь-литерал, и правило, знающее
                # только словари, прошло бы мимо половины случаев.
                tgt = node.targets[0]
                if (isinstance(tgt, ast.Subscript)
                        and isinstance(tgt.slice, ast.Constant)
                        and isinstance(tgt.slice.value, str)):
                    pairs = [(tgt.slice.value, node.value)]
            for key, val in pairs:
                if not _sliced(val):
                    continue
                found.add(key)
                if key not in ("title", "label") and not key.endswith("_cut"):
                    bad_cut.append(f"{rel}:{val.lineno} ключ «{key}» — обрезок "
                                   "под именем полного значения")
        seen_cut[rel] = found
    for rel, key in (("app/modules/schedule/day.py", "comment_cut"),
                     ("app/modules/schedule/canvas.py", "title")):
        if key not in seen_cut.get(rel, ()):
            bad_cut.append(f"{rel}: срез под ключом «{key}» не найден — "
                           "якорь правила пропал, форма изменилась")
    res.ok("обрезок не носит имени полного значения", not bad_cut,
           "диалог возьмёт обрезок за целое и запишет его обратно, а живой "
           "канал не заметит правки за границей: " + "; ".join(bad_cut))

    # ---- поверхность без состояния: клиент и сервер зовут её ОДИНАКОВО ----
    # ⭐ `_NO_STATE` (`schedule/api.py`) — имена поверхностей, которым команда
    # отвечает кодом БЕЗ состояния: у них своя модель, и день журнала им не
    # подходит. Имя это ДОГОВОР между клиентом и сервером, и опасное
    # направление у него не то, о котором думаешь.
    # ⛔ Клиент шлёт `screen=X`, сервер такого имени не знает — и вместо кода
    # приезжает ПОЛНАЯ МОДЕЛЬ ДНЯ, с другим ключом колонки, с кодом 200 и без
    # единого слова об этом. Ровно так и краснели первые проверки `e` и `f`
    # (C26.5.3): FastAPI молча игнорирует неизвестный ПАРАМЕТР, а неизвестное
    # ЗНАЧЕНИЕ параметра молча роняет ответ в ветку дня.
    # ⚠️ Второе направление дешевле, но тоже сторожится: имя в наборе, которого
    # не шлёт никто, — мёртвая ветка, и само по себе такое правило не краснеет
    # никогда (список с ВКЛЮЧАЮЩЕЙ полярностью, CLAUDE.md).
    # ⚠️ Проверки клиента из обхода исключены намеренно: они вправе назвать
    # небывалую поверхность, чтобы доказать отказ.
    # ⚠️ И таблица маршрутов B2 (`app/routes.ts`): её `screen:` — имя
    # React-экрана, та же ось, что `data-screen`, а не поверхность живого
    # канала, и в сеть она ничего не шлёт. Её держит `test_guards.suite_route_map`.
    # Исключение по ТОЧНОМУ пути: переименуют файл — правило покраснеет, а не
    # замолчит.
    routes_ts = ROOT / "frontend" / "src" / "app" / "routes.ts"
    sched = by_path.get("app/modules/schedule/api.py")
    surfaces: set[str] = set()
    if sched is not None:
        for node in _walk(sched):
            if (isinstance(node, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "_NO_STATE"
                            for t in node.targets)
                    and isinstance(node.value, ast.Set)):
                surfaces = {e.value for e in node.value.elts
                            if isinstance(e, ast.Constant) and isinstance(e.value, str)}
    sent: dict[str, str] = {}
    for f in sorted((ROOT / "frontend" / "src").rglob("*.ts*")):
        if ".test." in f.name or f == routes_ts:
            continue
        text = f.read_text(encoding="utf-8")
        for rx in (_SURF_URL, _SURF_KEY):
            for m in rx.finditer(text):
                sent.setdefault(m.group(1), str(f.relative_to(ROOT)))

    bad = []
    if not surfaces:
        bad.append("в app/modules/schedule/api.py нет набора _NO_STATE — "
                   "якорь правила пропал")
    bad += [f"{where}: клиент шлёт screen={name}, а сервер такого не знает"
            for name, where in sorted(sent.items()) if name not in surfaces]
    res.ok("поверхность, которую шлёт клиент, сервер знает", not bad,
           "команда вернёт полную модель ДНЯ вместо кода — с другим ключом "
           "колонки и с кодом 200: " + "; ".join(bad))

    dead = sorted(surfaces - set(sent))
    res.ok("в _NO_STATE нет имени, которого не шлёт никто",
           bool(surfaces) and not dead,
           "мёртвая ветка на сервере (или переименованная поверхность, о "
           "которой клиент уже не знает): " + "; ".join(dead or ["нет _NO_STATE"]))

    # ---- icons.ts свежий: иконки клиента — ИЗ core/icons._I (09-17, 2.0) ----
    # У иконок один владелец — словарь _I; frontend/src/components/icons.ts
    # генерируется из него (scripts/gen_icons.py). Правка иконки на сервере
    # без пересборки файла разошлась бы молча: старая форма рисует новое,
    # React — старое, и ни один запрос этого не видит. Сверка идёт разбором
    # ast, Node не нужен.
    # ⚠️ Полярность опасная: словарь обязан НАЙТИСЬ, файл — существовать.
    bad = []
    spec = importlib.util.spec_from_file_location(
        "gen_icons", ROOT / "scripts" / "gen_icons.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    icons_tree = by_path.get(_LAY_ICONS)
    icons = gen.icons_from_tree(icons_tree) if icons_tree is not None else None
    ts = ROOT / "frontend" / "src" / "components" / "icons.ts"
    if not icons:
        bad.append(f"в {_LAY_ICONS} нет словаря _I — якорь правила пропал")
    elif not ts.exists():
        bad.append(f"нет {ts.relative_to(ROOT)} — python scripts/gen_icons.py")
    elif ts.read_text(encoding="utf-8") != gen.render(icons):
        bad.append("icons.ts отстал от core/icons._I — python scripts/gen_icons.py")
    res.ok("icons.ts свежий: иконки клиента из core/icons._I", not bad,
           "React рисовал бы не те значки, что сервер: " + "; ".join(bad))

    # ---- ссылки экранов — AppLink (B4, 25.09) ----
    # Переход между экранами идёт роутером, и держит это ОДНО место —
    # `components/AppLink.tsx`: он сам решает, экран это (переход без
    # перезагрузки) или страница сервера (документ). Голый `<a href>` в экране
    # — переход перезагрузкой: с B1 оболочку рисует бандл, и окно гаснет
    # целиком. Ломается молча: ссылка работает, только с миганием — ровно то,
    # что Олег увидел на канарейке 1.30.0.
    # ⚠️ Полярность опасная: файлы обязаны НАЙТИСЬ, и `<AppLink` — встретиться
    # хоть раз, иначе правило зелено на пустой папке и на переименованном
    # компоненте.
    bad, found, links = [], 0, 0
    for f in sorted(FRONTEND.rglob("*.tsx")) if FRONTEND.exists() else []:
        rel = f.relative_to(FRONTEND).as_posix()
        if f.name.endswith(".test.tsx") or rel.split("/")[0] not in _LINK_DIRS:
            continue
        found += 1
        text = f.read_text(encoding="utf-8")
        links += text.count("<AppLink")
        if rel not in _RAW_ANCHOR_OK:
            bad += [f"{rel}:{ln}" for ln in _raw_anchors(text)]
    if found < 20:
        bad.append(f"файлов клиента нашлось {found} — обход сломан, правило пусто")
    if not links:
        bad.append("ни одного <AppLink> — компонент переименован, правило ищет не то")
    bad += [f"исключение протухло: нет {p}" for p in sorted(_RAW_ANCHOR_OK)
            if not (FRONTEND / p).exists()]
    res.ok("ссылки экранов — AppLink, а не голый <a href>", not bad,
           "переход перезагрузит документ, и окно мигнёт целиком: " + "; ".join(bad))

    # ---- подтверждение — своим окном (01.10) ----
    # Слово Олега 27.09: «перед любым удалением спросить» — и одним окном в
    # стиле программы, которое называет, что именно удаляется. Окно рисует
    # `ConfirmHost` рядом с роутером, вопрос задаёт `ask()` из
    # `components/confirm.ts`. `window.confirm` в экране — это снова серое
    # окно браузера без имени удаляемого; в нём же живёт и запасной путь (без
    # хоста), поэтому он — единственное законное место. Ломается молча: окно
    # браузера работает, только выглядит чужим и не говорит, что удаляет.
    # ⚠️ Полярность опасная: хост обязан стоять в App.tsx, `ask(`/`when(` —
    # встретиться в экранах; иначе правило зелено на удалённом компоненте.
    bad, asks = [], 0
    confirm_ok = "components/confirm.ts"
    for f in sorted(FRONTEND.rglob("*.ts*")) if FRONTEND.exists() else []:
        rel = f.relative_to(FRONTEND).as_posix()
        if (f.suffix not in (".ts", ".tsx") or ".test." in f.name
                or rel.startswith("test/") or rel == confirm_ok):
            continue
        code = _client_code(f.read_text(encoding="utf-8"))
        asks += len(re.findall(r"(?<![\w.])(?:ask|when)\(", code))
        bad += [f"{rel}:{code.count(chr(10), 0, m.start()) + 1}"
                for m in re.finditer(r"(?:window\.|(?<![\w.$]))confirm\(", code)]
    app_tsx = FRONTEND / "app" / "App.tsx"
    if not app_tsx.exists() or "<ConfirmHost" not in _client_code(app_tsx.read_text(encoding="utf-8")):
        bad.append("App.tsx не монтирует <ConfirmHost> — вопросы уйдут в окно браузера")
    if not (FRONTEND / confirm_ok).exists():
        bad.append(f"нет {confirm_ok} — исключение протухло")
    if asks < 5:
        bad.append(f"ask()/when() встречается {asks} раз — экраны больше не спрашивают этим путём")
    res.ok("подтверждение — своим окном, а не window.confirm", not bad,
           "вопрос перед удалением задаёт ask() из components/confirm, окно — ConfirmHost: "
           + "; ".join(bad))

    # ---- раздел с меню слева берёт данные загрузчиком маршрута ----
    # Экран со своим `useLoad` при переходе роутером встаёт сразу — меню без счётчиков, шапка, пустая таблица, —
    # а данные приезжают следующим кадром и перекладывают страницу; тем же путём прыгали блоки внутри вкладок
    # фиши. Раздел с
    # `SideMenu` (фиша, «Laborator», склад) — строка в `LOADS` App.tsx, и ни один его локальный модуль, вплоть
    # до блоков внутри вкладок, не зовёт `useLoad`. Стенд того же — `scripts/spa_shift.py`.
    # Полярность опасная: правило зелено, если не нашло ни одного раздела с меню — отсюда якорь по ИМЕНАМ известных
    # разделов: счёт «не меньше N» слепнет с каждым новым разделом (пропажа одного не опускает его ниже N).
    bad, side = [], set()
    app_code = _client_code(app_tsx.read_text(encoding="utf-8")) if app_tsx.exists() else ""
    comp_file = {name.strip().removeprefix("type ").strip(): src_
                 for names, src_ in re.findall(r"import\s*\{([^}]*)\}\s*from\s*'([^']+)'", app_code)
                 for name in names.split(",") if name.strip()}
    block = lambda head: (re.search(head + r"[^{]*\{(.*?)\n\}", app_code, re.S) or [None, ""])[1]  # noqa: E731
    screens = re.findall(r"^\s*(\w+): \([^)]*\) => <(\w+)", block(r"export const SCREENS"), re.M)
    loads = set(re.findall(r"^\s*(\w+):", _client_code(block(r"const LOADS")), re.M))

    def _resolve(f: pathlib.Path, spec: str) -> list[pathlib.Path]:
        base = (f.parent / spec).resolve()
        return [c for c in (base.with_name(base.name + ".tsx"), base.with_name(base.name + ".ts"),
                            base / "index.tsx", base / "index.ts") if c.is_file()][:1]

    def _local(f: pathlib.Path) -> list[pathlib.Path]:
        return [c for spec in re.findall(r"from\s*'(\.[^']*)'", _client_code(f.read_text(encoding="utf-8")))
                for c in _resolve(f, spec)]

    use_load_home = (FRONTEND / "hooks" / "useLoad.ts").resolve()
    for name, comp in screens:
        spec = comp_file.get(comp, "")
        top = next(iter(_resolve(app_tsx, spec)), None) if spec.startswith(".") else None
        if top is None or not re.search(r"from\s*'[./]*components/SideMenu'",
                                        _client_code(top.read_text(encoding="utf-8"))):
            continue
        side.add(name)
        if name not in loads:
            bad.append(f"{name}: нет строки в LOADS App.tsx")
        seen, todo = set(), [top]
        while todo:
            f = todo.pop()
            if f in seen or f == use_load_home:
                continue
            seen.add(f)
            code = _client_code(f.read_text(encoding="utf-8"))
            rel = f.relative_to(FRONTEND.resolve()).as_posix()
            bad += [f"{name}: {rel}:{code.count(chr(10), 0, m.start()) + 1} зовёт useLoad"
                    for m in re.finditer(r"(?<![\w.])useLoad\s*[<(]", code)]
            todo += _local(f)
    if lost := sorted(_SIDE_MENU_KNOWN - side):
        bad.append(f"разделы {lost} без SideMenu в SCREENS App.tsx — якорь правила пропал")
    res.ok("раздел с меню слева берёт данные загрузчиком маршрута", not bad,
           "свой useLoad встаёт пустым меню, а таблица и счётчики приезжают следующим кадром — прыжок при "
           "каждом переходе: " + "; ".join(bad))

    # ---- каждый экран берёт данные загрузчиком маршрута ----
    # Тот же прыжок у экрана без меню слева: «Registre» на своём `useLoad` вставал пустой карточкой, и плитки
    # приезжали кадром позже. Поэтому правило — про все экраны: каждое имя `SCREENS` — строка в `LOADS`, и
    # `useLoad` не зовёт ни один модуль клиента (сам хук остаётся домом `LoadState`/`defaultNavigate`).
    # Полярность опасная: при сломанном разборе App.tsx экранов ноль и нарушителей ноль — отсюда якорь на число.
    bad = [f"{name}: нет строки в LOADS App.tsx" for name, _ in screens if name not in loads]
    for f in sorted(FRONTEND.rglob("*.ts*")) if FRONTEND.exists() else []:
        rel = f.relative_to(FRONTEND).as_posix()
        if (f.suffix not in (".ts", ".tsx") or ".test." in f.name or rel.startswith("test/")
                or f.resolve() == use_load_home):
            continue
        code = _client_code(f.read_text(encoding="utf-8"))
        bad += [f"{rel}:{code.count(chr(10), 0, m.start()) + 1} зовёт useLoad"
                for m in re.finditer(r"(?<![\w.])useLoad\s*[<(]", code)]
    if len(screens) < 20:
        bad.append(f"в SCREENS App.tsx нашлось {len(screens)} экранов — разбор сломан, якорь правила пропал")
    res.ok("каждый экран берёт данные загрузчиком маршрута", not bad,
           "экран со своим useLoad встаёт при переходе пустым кадром, а содержимое приезжает следующим: "
           + "; ".join(bad))

    # ---- цвет врача считает ОДИН `_doc_hue` (19.09) ----
    # Палитра `_DOC_HUES` — внутренность формулы, а не общее добро: взять её
    # напрямую значит завести второй способ ответить «какого цвета этот врач».
    # Разойдутся они молча — цвета-то оба из палитры. Ровно так жила канва
    # панели до 19.09: она считала цвет по месту среди ПОКАЗАННЫХ в этот день
    # колонок, а карточка врача, `/api/doctors` и аватар — по месту в
    # справочнике. У врача без своего цвета колонка была одного цвета, аватар
    # другого, и цвет колонки менялся ото дня ко дню от того, у кого есть
    # записи.
    # ⚠️ Полярность опасная: правило ищет ИМЯ. Переименуют палитру или саму
    # формулу — нарушителей ноль, и сторож зелен навсегда. Отсюда якорь: оба
    # имени обязаны быть ОПРЕДЕЛЕНЫ в модуле-владельце (определены, а не
    # упомянуты: `_doc_hue` палитру называет, и проверка «имя встречается»
    # пережила бы переименование самого объявления).
    bad = [f"{rel}:{n.lineno}" for rel, tree in src if rel != _HUE_MODULE
           for n in _walk(tree)
           if (isinstance(n, ast.Name) and n.id == _HUE_PALETTE)
           or (isinstance(n, ast.Attribute) and n.attr == _HUE_PALETTE)
           or (isinstance(n, ast.alias) and n.name == _HUE_PALETTE)]
    hue_mod = by_path.get(_HUE_MODULE) or ast.Module(body=[], type_ignores=[])
    owns = {t.id for n in _walk(hue_mod) if isinstance(n, ast.Assign)
            for t in n.targets if isinstance(t, ast.Name)}
    owns |= {fn.name for fn in _walk(hue_mod)
             if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))}
    if not {_HUE_PALETTE, "_doc_hue"} <= owns:
        bad.append(f"{_HUE_MODULE}: нет {_HUE_PALETTE}/_doc_hue — "
                   "якорь правила пропал, искать оно будет несуществующее")
    res.ok("цвет врача считает один _doc_hue", not bad,
           "второй способ ответить «какого цвета этот врач» — цвет колонки "
           "разойдётся с аватаром того же врача молча: " + ", ".join(bad))

    # ---- выборка дня упорядочена ПОЛНОСТЬЮ (19.09, разведка живого канала) --
    # ⛔ Ничья по (starts_at, doctor) достижима: заметка стойки и визит на одну
    # минуту у одного врача (`_conflicts` заметки не стережёт). Ничья тянется
    # вниз — канва сортирует кластеры УСТОЙЧИВО, наследуя порядок базы, а
    # порядок внутри кластера решает геометрию блоков. SQLite на практике
    # стабилен, но не обещает ничего: без тай-брейка два опроса живого журнала
    # при неизменном дне дали бы разное тело, и подмена шла бы каждые 12 секунд.
    # Правило ловится ДОБАВЛЕНИЕМ — новой такой сортировкой без `a.id`.
    _DAY_ORDER = "ORDER BY a.starts_at, a.doctor"
    ordered = [(rel, n) for rel, tree in src if rel == _DB_DAY
               for n in _walk(tree)
               if isinstance(n, ast.Constant) and isinstance(n.value, str)
               and _DAY_ORDER in n.value]
    bad = [f"{_DB_DAY}:{n.lineno}" for _rel, n in ordered
           if f"{_DAY_ORDER}, a.id" not in n.value]
    # ⚠️ Якорь: правило ИЩЕТ ИМЯ, и переименование колонки сделало бы его
    # вечнозелёным — ноль нарушителей над нулём находок. (До 12.10 выборок было
    # две — тот же запрос текстом Postgres и текстом SQLite; теперь одна.)
    if not ordered:
        bad.append(f"{_DB_DAY}: выборки дня нет — якорь правила пропал, "
                   "искать оно будет несуществующую сортировку")
    res.ok("выборка дня упорядочена полностью, с тай-брейком по id", not bad,
           "ничья в сортировке дня перетасует блоки канвы между запросами: "
           "живой журнал начнёт подменять сетку без единой правки данных — "
           + ", ".join(bad))

    # ---- вход в журнал и подтверждение ИСТОЧНИКА — РАЗНЫЕ оракулы (21.09) ---
    # ⛔ Оба имени ниже привязаны к папке, В КОТОРОЙ ИДЁТ ПРОГРАММА, и оба в неё
    # ПИШУТ: `verify_pin` при удаче мигрирует auth.json v1→v2 и меняет ключ
    # подписи сессий, `note_fail` кладёт счётчик рядом. Позвать их против
    # ЧУЖОГО корня (экран раздвоения, P2) значит записать в источник, который
    # ещё не решено копировать, — и copy-only ломается до того, как начнётся.
    # Для источника есть `verify_source_pin`: он читает по ЯВНОМУ пути.
    # ⚠️ Белый список именной: вход в журнал живёт в modules/entry/routes.py
    # (до 14.10 — в main.py), и разрешение на
    # «любой модуль, где есть форма» спрятало бы в нём будущий экран миграции.
    # Переедет вход — правило покраснеет, и это правильно: повод посмотреть.
    bad = [f"{rel}:{n.lineno} → {name}" for rel, tree in src
           if rel not in _LOGIN_OK
           for n in _walk(tree)
           if isinstance(n, ast.Call) and isinstance(n.func, (ast.Name, ast.Attribute))
           for name in [n.func.id if isinstance(n.func, ast.Name) else n.func.attr]
           if name in _LOGIN_ORACLE]
    res.ok("оракул входа не зовётся вне входа", not bad,
           "проверка PIN или счётчик попыток спрошены там, где корень может "
           "быть чужим — источник получит запись: " + ", ".join(bad))

    # ---- подтверждение источника не пишет в источник ------------------------
    # ⭐ Правило смотрит внутрь ОДНОЙ функции, и это единственное место, где
    # «ничего не записано» проверяется разбором, а не снимком дерева. Снимок
    # (`tests/test_srcpin.py`) отвечает за поведение, разбор — за то, что новая
    # ветка в этой же функции не заведёт запись мимо стенда.
    src_fn = next((fn for fn in _walk(auth_mod)
                   if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
                   and fn.name == _SRC_VERIFY), None)
    bad = [f"{_AUTH_MODULE}:{n.lineno} → {name}"
           for n in _walk(src_fn or ast.Module(body=[], type_ignores=[]))
           if isinstance(n, ast.Call) and isinstance(n.func, (ast.Name, ast.Attribute))
           for name in [n.func.id if isinstance(n.func, ast.Name) else n.func.attr]
           if name in _SRC_WRITES]
    res.ok("подтверждение источника ничего не пишет", not bad,
           "в чужом корне после проверки останется след: " + ", ".join(bad))

    # ---- якорь обоих правил выше (полярность опасная) -----------------------
    # Оба списка ВКЛЮЧАЮЩИЕ: переименуют `verify_pin` или `verify_source_pin` —
    # правила станут искать несуществующие имена, найдут ноль нарушителей и
    # позеленеют навсегда. Мутация этого не ловит: она ломает сторожа тем же
    # устаревшим именем. Поэтому имена сверяются с ОПРЕДЕЛЕНИЯМИ — в auth.py
    # и в файлах входа (`try_login` живёт у формы, в modules/entry/routes.py).
    auth_defs = {fn.name for rel in _LOGIN_OK
                 for fn in _walk(by_path.get(rel) or ast.Module(body=[], type_ignores=[]))
                 if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef,
                                    ast.ClassDef))}
    gone = sorted((_LOGIN_ORACLE | _PIN_MATH | _SRC_OWNS) - auth_defs)
    res.ok("имена обоих оракулов не протухли", not gone,
           f"нет ни в {_AUTH_MODULE}, ни у входа: {', '.join(gone)} — правила "
           f"про вход и про источник ищут то, чего больше нет, и молчат")

    # ---- проверку PIN считает ОДИН модуль -----------------------------------
    # ⚠️ Реальный ход мысли, от которого правило и защищает: автор экрана
    # раздвоения видит, что `verify_pin` звать нельзя, и «просто читает json и
    # считает хеш сам». Вторая формула разойдётся с первой молча — у неё свои
    # KDF и число итераций, и разойдётся она ровно в тот день, когда формат
    # файла тронут. Правило не про доверие, а про то, что расхождение невидимо.
    bad = [f"{rel}:{n.lineno} → {name}" for rel, tree in src
           if rel != _AUTH_MODULE
           for n in _walk(tree)
           if isinstance(n, ast.Call) and isinstance(n.func, (ast.Name, ast.Attribute))
           for name in [n.func.id if isinstance(n.func, ast.Name) else n.func.attr]
           if name in _PIN_MATH]
    res.ok("PIN проверяет один модуль", not bad,
           "вторая формула хеша PIN вне auth.py: " + ", ".join(bad))

    # ---- оформление: ступень, а не число (B5, 25.09) ------------------------
    # Радиус, подскок при наведении и кольцо фокуса живут в :root panel.css
    # ступенями (--r-*, --lift*, --ring): так стиль темы меняет форму ВСЕГО
    # интерфейса одной записью в theme.STYLES. Число по месту — правило,
    # до которого стиль не достаёт: у стиля с углами 4/8 оно останется с
    # прежним углом, и увидит это клиника со своим стилем, а не разработчик на
    # умолчании. До 25.09 таких чисел было 104 в двадцати разных значениях.
    # ⚠️ Смотрятся ОБА файла: panel.css красит и React-экраны, и страницы
    # каркаса; app.css — то, чего в panel.css нет. Пилюля (999px), круг
    # (50%), планки до 4px и половинки дуги моста (`6px 6px 0 0`, два
    # значения) — форма, а не ступень, они законны числом.
    def _blank(text: str) -> str:
        """Комментарии — пробелами той же длины: номера строк остаются."""
        return re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group(0)),
                      text, flags=re.S)
    def _sheet(p) -> str:
        # на пустом дереве (канарейка мутации) файла нет — правила ниже тогда
        # просто не находят правил, красное даёт «исходники нашлись»
        return _blank(p.read_text(encoding="utf-8")) if p.exists() else ""
    sheets = {"static/css/panel.css": _sheet(BOT / "app/static/css/panel.css"),
              "frontend/app/app.css": _sheet(FRONTEND / "app" / "app.css")}
    # 5…99px — число вместо ступени; от 100px — пилюля (в файле она 999px)
    bad = [f"{name}:{text.count(chr(10), 0, m.start()) + 1} {m.group(0).strip()}"
           for name, text in sheets.items()
           for m in re.finditer(r"border-radius:\s*(\d+(?:\.\d+)?)px\s*(?=[;}])", text)
           if 5 <= float(m.group(1)) < 100]
    res.ok("радиус берётся ступенью, а не числом", not bad,
           "число вместо --r-card/-block/-ctl/-chip/-s/-xs: " + "; ".join(bad[:8]))

    # Подскок при наведении — та же история: translateY(-1px) в :hover стоял в
    # семнадцати правилах, и стиль без подскоков не смог бы их убрать.
    rules = [(name, " ".join(sel.split()), body)
             for name, text in sheets.items()
             for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", text)]
    bad = [f"{name}: {sel[-60:]}" for name, sel, body in rules
           if ":hover" in sel and re.search(r"translateY\(\s*-\d", body)]
    res.ok("подскок при наведении берётся ступенью", not bad,
           "translateY(-Npx) вместо var(--lift*): " + "; ".join(bad[:8]))

    # Кольцо фокуса — `var(--ring)`; числом оно стоит только в самой ступени
    # (:root). Исключений нет: кольцо выбора у кнопки поверхности зуба ушло
    # со старой одонтограммой (13.10), а список-исключение без единого живого
    # селектора только прощал бы будущий дубль.
    bad = [f"{name}: {sel[-60:]}" for name, sel, body in rules
           if "0 0 0 3px var(--teal-ring)" in body and sel != ":root"]
    res.ok("кольцо фокуса берётся ступенью", not bad,
           "0 0 0 3px var(--teal-ring) вместо var(--ring): " + "; ".join(bad[:8]))

    # Кегль — ступень шкалы `--fs-*` (шаг 7): 339 чисел в 30 значениях ушли
    # разом, и число вернётся первым же новым правилом, если его не ловить.
    # Законно одно число, и оно не размер текста ради вида: 16px у полей на
    # телефоне (ниже — iOS зумит страницу при фокусе).
    have = {sel for _name, sel, _body in rules}
    fs_ok = {(".dlg-form input,.dlg-form select,.dlg-form textarea, .top form.searchf input", "16px")}
    bad = [f"{name}: {sel[-50:]} {m.group(0)}"
           for name, sel, body in rules
           for m in re.finditer(r"font-size:\s*(\d+(?:\.\d+)?)px", body)
           if (sel, m.group(1) + "px") not in fs_ok]
    res.ok("кегль берётся ступенью", not bad,
           "число вместо var(--fs-*): " + "; ".join(bad[:8]))
    gone = sorted({s for s, _v in fs_ok} - have)
    res.ok("якоря кеглей не протухли", not gone,
           "в panel.css больше нет правила " + ", ".join(gone))

    # Длительность перехода — ступень `--dur*` (шаг 11): стиль Fluent короче,
    # и число по месту он не достанет. Анимации появления (@keyframes) —
    # не переходы, у них свой темп, правило их не смотрит.
    bad = [f"{name}: {sel[-50:]}" for name, sel, body in rules
           if re.search(r"transition\s*:[^;]*(?<![\w.])\.\d+s\b", body)]
    res.ok("длительность перехода берётся ступенью", not bad,
           "секунды числом вместо var(--dur*): " + "; ".join(bad[:8]))

    # Под `.anim` — только ВХОДНЫЕ анимации, поимённо (06.11.2026). Класс ставит
    # шапка документа, а панель дня снимает его первым же изменением дня; с B4
    # документ не перезагружается, и у стойки класс снят почти всегда. Отклик
    # на действие, поставленный под `.anim`, умирает молча: так не въезжал
    # плавающий ответ и одним кадром сворачивалось меню (а с ним не работала
    # правка 25.09 «дёргания на Detaliat»). Новое правило под `.anim` — либо
    # входная анимация (тогда в список осознанно), либо ему тут не место.
    entry = {".statbar>div", ".spark", ".ag-i", "*",
             # вход «Statistici» (07.11): класс ставит и снимает сам экран
             ".stx-bar", ".stx-bl-bar", ".stx-meter > *", ".stx-tbl tbody tr", ".stx-barlist li"}
    under = {(name, s.strip()) for name, sel, _body in rules
             for s in sel.split(",") if s.strip().startswith(".anim ")}
    bad = [f"{name}: {s}" for name, s in sorted(under)
           if re.sub(r":nth-child\([^)]*\)$", "", s[len(".anim "):]) not in entry]
    res.ok("под .anim только входные анимации", not bad,
           "отклик на действие под .anim умирает после первого изменения дня: " + "; ".join(bad[:8]))

    # Размытие — ступень материала (Sticlă, 16.10): backdrop-filter берёт
    # var(--glass-blur) / --top-blur / --backdrop-blur. Литерал blur(…) по
    # месту — правило, до которого стиль не достаёт: у сплошного стиля оно
    # размывало бы всегда, у стекла — не отвечало бы на prefers-reduced-
    # transparency, когда тот появится ключом. Условие @supports (blur(1px))
    # — не правило, разбор его не видит.
    bad = [f"{name}: {sel[-50:]}" for name, sel, body in rules
           if re.search(r"backdrop-filter\s*:[^;]*blur\(", body) and sel != ":root"]
    res.ok("размытие берётся ступенью", not bad,
           "blur(…) числом вместо var(--glass-blur): " + "; ".join(bad[:8]))
    # ⛔ Карточки в потоке и ячейки сетки размывать нельзя: blur считается на
    # каждом кадре прокрутки, а канва перерисовывается каждые 12 с. Размытие
    # разрешено только тому, под чем содержимое едет (список здесь, он же в
    # блоке «Sticlă» panel.css); новый селектор с размытием — в список осознанно.
    live = {".top", "dialog", "dialog::backdrop", ".pp-veil", ".side", ".gridcard>.gridhead",
            ".ppanel", ".toastbox .banner", ".dp-cmenu", ".dp-svc-list", ".dp-qf", ".dp-qf-back", ".dp-lock-card",
            ".dp-react-root .odop[data-sel] .odop-side"}
    blurred = {(name, s.strip()) for name, sel, body in rules
               if "backdrop-filter" in body for s in sel.split(",")}
    bad = [f"{name}: {s}" for name, s in sorted(blurred) if s not in live]
    res.ok("размытие только над прокруткой", not bad,
           "backdrop-filter у поверхности в потоке: " + "; ".join(bad[:8]))
    gone = sorted(s for s in live if s not in {s2 for _n, s2 in blurred})
    res.ok("якоря размытия не протухли", not gone,
           "в таблицах больше нет размытия у " + ", ".join(gone))
    # ---- ворота лицензии стоят в шлюзе, белый список — константа (L4) ----
    # Ворота одни: шлюз в main.py зовёт lic.refuses(...) ДО маршрутизации, и
    # ни один маршрут не решает про readonly сам. Второе решение разошлось бы
    # с белым списком молча — у клиники, не в тесте: маршрут, «просто
    # проверивший состояние» у себя, отказал бы бэкапу или пустил бы запись.
    # Три якоря: вызов в шлюзе, кортеж READONLY_ALLOW из адресов под /admin и
    # /api/, и строка кода отказа только там, где ей место.
    bad = []
    main_tree = by_path.get("app/main.py")
    # ⚠️ Именно `lic.refuses`, не любой `.refuses`: с 01.10 в том же шлюзе стоит
    # `demo.refuses`, и правило «есть хоть один refuses» молчало бы, когда
    # ворота лицензии вынесли, — поймано мутацией в день, когда появился демо.
    gate = [n for n in _walk(main_tree) if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute) and n.func.attr == "refuses"
            and isinstance(n.func.value, ast.Name) and n.func.value.id == "lic"] if main_tree else []
    if not gate:
        bad.append("app/main.py: шлюз не зовёт lic.refuses — ворот нет")
    allow = None
    lst_tree = by_path.get("app/core/license_state.py")
    for n in _walk(lst_tree) if lst_tree else ():
        if (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "READONLY_ALLOW"
                                              for t in n.targets)
                and isinstance(n.value, ast.Tuple)):
            allow = [e.value for e in n.value.elts
                     if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    if allow is None:
        bad.append("app/core/license_state.py: нет кортежа READONLY_ALLOW — якорь правила пропал")
    else:
        bad += [f"READONLY_ALLOW: {t} — не под /admin и не под /api/"
                for t in allow if not t.startswith(("/admin", "/api/"))]
    _GATE_HOME = ("app/core/license.py", "app/core/license_state.py",
                  _LAY_MSG, "app/main.py")
    bad += [f"{rel}:{ln} — второе решение про readonly вне шлюза"
            for rel, tree in src if rel not in _GATE_HOME
            for ln, text in _ui_texts(tree) if text == "license_readonly"]
    res.ok("ворота лицензии стоят в шлюзе, белый список — константа", not bad,
           "запись в readonly решается в двух местах или не решается вовсе: "
           + "; ".join(bad))

    # ---- шлюз — внешний посредник (14.10) ----
    # Starlette ставит каждый новый посредник СНАРУЖИ прежних, и запрос первым
    # встречает объявленный последним. До 14.10 шлюз стоял внешним только
    # потому, что был объявлен на 260 строк ниже двух других, — и ничто этого
    # не держало. Посредник, дописанный под ним, исполнялся бы РАНЬШЕ шлюза: в
    # восстановлении и при битом профиле база не открыта, и любое обращение к
    # ней роняло бы пятисотой и экран с полем для кода. Шлюз — тот посредник,
    # что зовёт `lic.refuses`; он обязан быть объявлен последним.
    bad = []
    regs, gate_at = [], None
    for n in _walk(main_tree) if main_tree else ():
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
                isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                and d.func.attr == "middleware" for d in n.decorator_list):
            regs.append(n.lineno)
            if any(isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                   and c.func.attr == "refuses" and isinstance(c.func.value, ast.Name)
                   and c.func.value.id == "lic" for c in _walk(n)):
                gate_at = n.lineno
        elif (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
              and n.func.attr == "add_middleware"):
            regs.append(n.lineno)
    if gate_at is None:
        bad.append("app/main.py: нет посредника, зовущего lic.refuses — якорь правила пропал")
    else:
        bad += [f"app/main.py:{ln} — посредник объявлен ниже шлюза и исполнится раньше него"
                for ln in regs if ln > gate_at]
    res.ok("шлюз — внешний посредник", not bad, "; ".join(bad))

    # ---- договор согласован с программой дословно (L11) ----
    # Сайт обещает клинике то, что делает программа: режим чтения — теми же
    # словами, что баннер license_readonly, и 14 дней без файла у обновившейся
    # клиники — тем же числом, что NO_FILE_GRACE. Расхождение — обещание,
    # которого программа не выполняет, и заметит его клиника, а не мы.
    # Страница лежит в docs/site/ (сам сайт — отдельный репозиторий), чтобы
    # правило могло её прочитать; числа и фразы берутся из КОДА, не из теста.
    bad = []
    terms_path = ROOT / "docs" / "site" / "termeni.html"
    # Страница переносит строки внутри фраз — сравниваем с одинарными пробелами.
    page = " ".join(terms_path.read_text(encoding="utf-8").split()) if terms_path.exists() else ""
    if not page:
        bad.append("docs/site/termeni.html не найден — договора нет")
    readonly_text = ""
    lay_tree = by_path.get(_LAY_MSG)
    for n in _walk(lay_tree) if lay_tree else ():
        if (isinstance(n, ast.Assign) and isinstance(n.value, ast.Dict)
                and any(isinstance(t, ast.Name) and t.id == "MSG_BANNER" for t in n.targets)):
            for k, v in zip(n.value.keys, n.value.values):
                if (isinstance(k, ast.Constant) and k.value == "license_readonly"
                        and isinstance(v, ast.Tuple) and len(v.elts) == 2
                        and isinstance(v.elts[1], ast.Constant)):
                    readonly_text = v.elts[1].value
    if not readonly_text:
        bad.append(f"{_LAY_MSG}: в MSG_BANNER нет license_readonly — якорь пропал")
    else:
        m = re.search(r"(Datele se pot [^;.]+)", readonly_text)
        phrase = m.group(1).strip() if m else readonly_text
        if phrase not in page:
            bad.append(f"termeni.html не повторяет слова программы о режиме чтения: «{phrase}»")
        if "regim de citire" not in readonly_text or "regim de citire" not in page:
            bad.append("«regim de citire» должно быть и в баннере, и в договоре")
    days = None
    for n in _walk(lst_tree) if lst_tree else ():
        if (isinstance(n, ast.Assign) and isinstance(n.value, ast.Call)
                and any(isinstance(t, ast.Name) and t.id == "NO_FILE_GRACE" for t in n.targets)):
            for kw in n.value.keywords:
                if kw.arg == "days" and isinstance(kw.value, ast.Constant):
                    days = kw.value.value
    if days is None:
        bad.append("app/core/license_state.py: нет NO_FILE_GRACE = timedelta(days=N) — якорь пропал")
    else:
        m = re.search(r"(\d+) zile de la prima pornire", page)
        if not m:
            bad.append("termeni.html: нет пункта «N zile de la prima pornire» для обновившейся клиники")
        elif int(m.group(1)) != days:
            bad.append(f"termeni.html обещает {m.group(1)} дней без файла, программа даёт {days}")
    # Галочка на странице активации принимает условия ПО АДРЕСУ и в ВЕРСИИ,
    # которые называет программа (license.TERMS_URL, TERMS_VERSION), и
    # летопись пишет эту версию навсегда. Страницу поправили, а дату в
    # программе нет — клиника «приняла» версию, которой уже нет на сайте.
    consts = {t.id: n.value.value for n in _walk(by_path.get("app/core/license.py") or ast.Module(
                  body=[], type_ignores=[]))
              if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant)
              for t in n.targets if isinstance(t, ast.Name) and t.id in ("TERMS_URL", "TERMS_VERSION")}
    if set(consts) != {"TERMS_URL", "TERMS_VERSION"}:
        bad.append("app/core/license.py: нет TERMS_URL / TERMS_VERSION — якорь пропал")
    else:
        m = re.search(r"Ultima actualizare: (\d\d\.\d\d\.\d{4})", page)
        if not m or m.group(1) != consts["TERMS_VERSION"]:
            bad.append(f"termeni.html обновлена {m.group(1) if m else '?'}, а программа принимает "
                       f"версию {consts['TERMS_VERSION']}")
        if f'<link rel="canonical" href="{consts["TERMS_URL"]}">' not in page:
            bad.append(f"TERMS_URL {consts['TERMS_URL']} — не адрес termeni.html")
    # Политика обещает, как часто программа спрашивает сервер, пока заявка на
    # пробный ждёт (активация без файла, 26.09): число — license.PENDING_EVERY.
    pol_path = ROOT / "docs" / "site" / "privacy.html"
    pol = " ".join(pol_path.read_text(encoding="utf-8").split()) if pol_path.exists() else ""
    minutes = [kw.value.value for n in _walk(by_path.get("app/core/license.py") or ast.Module(
                   body=[], type_ignores=[]))
               if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call)
               and any(isinstance(t, ast.Name) and t.id == "PENDING_EVERY" for t in n.targets)
               for kw in n.value.keywords if kw.arg == "minutes" and isinstance(kw.value, ast.Constant)]
    if not minutes:
        bad.append("app/core/license.py: нет PENDING_EVERY = timedelta(minutes=N) — якорь пропал")
    else:
        want = "o dată pe minut" if minutes[-1] == 1 else f"o dată la {minutes[-1]} minute"
        if want not in pol:
            bad.append(f"privacy.html не говорит «{want}»: программа спрашивает сервер раз в "
                       f"{minutes[-1]} мин., пока заявка ждёт")
    # Договор при активации (29.10): политика § 5, декларация п. 3 и Anexa 2
    # договора (docs/dentpilot-2/contract/anexa-2.html) называют, как часто
    # программа ходит наружу помимо лицензии: обновления — `_schedule(… N * 3600)`
    # в app/update.py, счёт SMS — ACCOUNT_EVERY в app/core/sms_loop.py. Текст,
    # разошедшийся с кодом, — обещание, которого программа не держит, и
    # подписанный PDF с ним хуже, чем никакой (декларация подписывается КЭП).
    # ⚠️ Берётся НАИБОЛЬШИЙ множитель 3600 среди вызовов _schedule: короткие
    # повторы (ожидание ассета) считаются секундами, не часами. С 29.10 те же
    # интервалы называют и условия (§ 8, § 16) — дата условий = TERMS_VERSION.
    texts = {"privacy.html": pol, "termeni.html": page}
    for rel in ("docs/site/declaratie-195.html", "docs/dentpilot-2/contract/anexa-2.html"):
        path = ROOT / rel
        texts[rel] = " ".join(path.read_text(encoding="utf-8").split()) if path.exists() else ""
        if not texts[rel]:
            bad.append(f"{rel} не найден — потоки данных описывать негде")
    empty = ast.Module(body=[], type_ignores=[])
    hours = [b.left.value for n in _walk(by_path.get("app/update.py") or empty)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_schedule"
             for b in _walk(n)
             if isinstance(b, ast.BinOp) and isinstance(b.op, ast.Mult)
             and isinstance(b.left, ast.Constant) and isinstance(b.right, ast.Constant)
             and b.right.value == 3600]
    if not hours:
        bad.append("app/update.py: нет _schedule(… N * 3600) — якорь периода обновлений пропал")
    else:
        want = f"la fiecare {max(hours)} ore"
        bad += [f"{name} не говорит «{want}»: программа проверяет обновления раз в {max(hours)} ч"
                for name, text in texts.items() if want not in text]
    every = [kw.value.value for n in _walk(by_path.get("app/core/sms_loop.py") or empty)
             if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call)
             and any(isinstance(t, ast.Name) and t.id == "ACCOUNT_EVERY" for t in n.targets)
             for kw in n.value.keywords if kw.arg == "minutes" and isinstance(kw.value, ast.Constant)]
    if not every:
        bad.append("app/core/sms_loop.py: нет ACCOUNT_EVERY = timedelta(minutes=N) — якорь пропал")
    else:
        # «la fiecare N minute», не «o dată la N minute»: вторая фраза — у опроса
        # заявки (PENDING_EVERY), и одинаковые слова глушили бы ту мутацию.
        want = "în fiecare minut" if every[-1] == 1 else f"la fiecare {every[-1]} minute"
        bad += [f"{name} не говорит «{want}»: счёт SMS читается раз в {every[-1]} мин."
                for name, text in texts.items() if want not in text]
    # Связь с аккаунтом Google: уведомление в программе называет частоту опроса константой
    # POLL_MINUTES, а документ, который описывает связь («contul Google»), — тем же числом; Anexa 2 —
    # и теми же словами кнопок. Документ, ещё не знающий связи, правилом не задет.
    gl = by_path.get(_GLINK)
    gl_consts = {t.id: n.value for n in (gl.body if gl else ()) if isinstance(n, ast.Assign)
                 for t in n.targets if isinstance(t, ast.Name)}
    poll = gl_consts.get("POLL_MINUTES")
    if not (isinstance(poll, ast.Constant) and isinstance(poll.value, int)):
        bad.append(f"{_GLINK}: нет POLL_MINUTES = N — якорь пропал")
    else:
        uses = [x for x in _walk(gl_consts["NOTICE"]) if isinstance(x, ast.FormattedValue)
                and isinstance(x.value, ast.Name) and x.value.id == "POLL_MINUTES"] \
            if "NOTICE" in gl_consts else []
        if len(uses) < 2:
            bad.append(f"{_GLINK}: NOTICE называет частоту опроса не из POLL_MINUTES")
        want = f"din {poll.value} în {poll.value} minute"
        bad += [f"{name} описывает связь с Google, но не говорит «{want}»"
                for name, text in texts.items() if "contul Google" in text and want not in text]
        words = gl_consts.get("WORDS")
        anexa = texts.get("docs/dentpilot-2/contract/anexa-2.html", "")
        if isinstance(words, ast.Dict) and "contul Google" in anexa:
            bad += [f"anexa-2.html не называет кнопку «{w.value}» словами программы"
                    for k, w in zip(words.keys, words.values)
                    if isinstance(k, ast.Constant) and k.value in ("connect", "disconnect", "check")
                    and isinstance(w, ast.Constant) and w.value not in anexa]
    res.ok("договор согласован с программой дословно", not bad,
           "сайт обещает не то, что делает программа: " + "; ".join(bad))

    # ---- текст перед скачиванием называет программу её словами (26.09) ----
    # docs/site/descarca*.html — закон 195 перед кнопкой «Descarcă» (L15).
    # Клиника, скачавшая программу сама, узнаёт о законе только из него, и он
    # отправляет её к кнопкам фиши и к разделам настроек. Кнопка, которой нет,
    # хуже молчания — тот же довод, что у FAQ. Запись на странице условная:
    # «…» — только надписи экранов клиента (React — умолчание продукта), путь
    # настроек — <b>Setări › X</b>, где X — плитка хаба (`_hub_tiles`). Обе
    # версии называют одно и то же: перевод, потерявший кнопку, — другой текст.
    # Надпись ищется ЦЕЛИКОМ — строкой в кавычках или текстом между тегами:
    # «accesările» живёт и внутри 'ascunde accesările', и подстрока пережила бы
    # переименование самой ссылки. Комментарии клиента не в счёт: надпись,
    # оставшаяся только в пояснении, на экране уже не стоит.
    # ⚠️ Полярность опасная: страницы, надписи, плитки и файлы клиента обязаны
    # НАЙТИСЬ, иначе правило зелено на пустом месте.
    bad, client = [], []
    for f in sorted(FRONTEND.rglob("*.ts*")) if FRONTEND.exists() else []:
        if ".test." in f.name:
            continue
        text = re.sub(r"/\*.*?\*/", " ", f.read_text(encoding="utf-8"), flags=re.S)
        client.append(re.sub(r"(?<![:\w'\"])//[^\n]*", " ", text))
    client_text = "\n".join(client)
    if len(client) < 20:
        bad.append(f"файлов клиента нашлось {len(client)} — обход сломан, правило пусто")
    set_tree = by_path.get("app/modules/settings/routes.py")
    hub = next((n for n in _walk(set_tree) if isinstance(n, ast.FunctionDef)
                and n.name == "_hub_tiles"), None) if set_tree else None
    tiles = {n.args[3].value for n in (_walk(hub) if hub else ())
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "tile" and len(n.args) >= 4
             and isinstance(n.args[3], ast.Constant)}
    if len(tiles) < 5:
        bad.append(f"плиток хаба нашлось {len(tiles)} — `_hub_tiles` или `tile(…)` "
                   "переименованы, правило ищет не то")
    named = {}
    for name in ("descarca.html", "descarca-ru.html"):
        path = ROOT / "docs" / "site" / name
        page = " ".join(path.read_text(encoding="utf-8").split()) if path.exists() else ""
        labels = re.findall(r"«([^»]+)»", page)
        paths = re.findall(r"<b>Setări › ([^<]+)</b>", page)
        if not labels or not paths:
            bad.append(f"docs/site/{name}: ни «надписей», ни путей Setări › — "
                       "страницы нет или запись сменилась")
        if page.count("Setări ›") != len(paths):
            bad.append(f"{name}: путь Setări › вне <b>…</b> — правило его не видит")
        bad += [f"{name}: «{t}» — такой надписи в клиенте нет" for t in labels
                if not re.search(r"['\"`>]\s*" + re.escape(t) + r"\s*['\"`<]", client_text)]
        bad += [f"{name}: Setări › {t} — такой плитки в настройках нет"
                for t in paths if t not in tiles]
        named[name] = (sorted(set(labels)), sorted(set(paths)))
    if len(set(map(repr, named.values()))) > 1:
        bad.append("descarca.html и descarca-ru.html называют разные кнопки или разделы")
    res.ok("текст перед скачиванием называет кнопки программы её словами", not bad,
           "сайт отправляет клинику к кнопке, которой нет: " + "; ".join(bad))

    # ---- каждый баннер каркаса — сигнал оболочки (посадка L5 на B1, 26.09) ----
    # React-оболочка рисует `shell_model()` — и только её. Баннер, заведённый
    # функцией в layout, но не положенный в модель, не виден НИГДЕ: так
    # лицензия (L5 писался до B1) была видна старой странице и не видна
    # React-экрану — у клиники, которой отказывают в записи. С 03.11.2026
    # серверного каркаса `_shell` нет, и список баннеров — сами функции
    # `_…_banner()` / `_…_hint()`, ОПРЕДЕЛЁННЫЕ в `core/` (до того — вызовы
    # внутри `_shell`): каждая обязана вызываться в `shell_model`, а каждый
    # ключ `signals` — рисоваться `AppShell.tsx`.
    # ⚠️ Обход — весь `core/`, а не один файл: баннеры переехали из layout в
    # `core/banners.py` (04.11), и правило, смотрящее в один файл, просто видело
    # бы их меньше — зелёным. Обратная половина (`in_model - printed`) держит тот
    # же переезд с другой стороны: зовётся то, чего обход не нашёл.
    bad = []
    lay_tree = by_path.get(_LAY_SHELL)
    funcs = {n.name: n for rel, tree in src if rel.startswith("app/core/")
             for n in _walk(tree) if isinstance(n, ast.FunctionDef)}

    def _banner_calls(node) -> set:
        return {c.func.id for c in _walk(node)
                if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                and re.fullmatch(r"_\w+_(banner|hint)", c.func.id)}
    printed = {name for name in funcs if re.fullmatch(r"_\w+_(banner|hint)", name)}
    in_model = _banner_calls(funcs["shell_model"]) if "shell_model" in funcs else set()
    keys = []
    for n in _walk(funcs["shell_model"]) if "shell_model" in funcs else ():
        if isinstance(n, ast.Dict):
            for k, v in zip(n.keys, n.values):
                if isinstance(k, ast.Constant) and k.value == "signals" and isinstance(v, ast.Dict):
                    keys = [kk.value for kk in v.keys if isinstance(kk, ast.Constant)]
    if not printed:
        bad.append("layout: функций баннеров не найдено — якорь правила пропал")
    if not keys:
        bad.append("layout.shell_model: нет словаря signals — якорь правила пропал")
    bad += [f"{name}() есть в core/, но не едет в модель оболочки"
            for name in sorted(printed - in_model)]
    bad += [f"{name}() зовётся в модели, но в core/ не найдена — обход ослеп"
            for name in sorted(in_model - printed)]
    shell_tsx = FRONTEND / "layouts" / "AppShell.tsx"
    tsx = shell_tsx.read_text(encoding="utf-8") if shell_tsx.exists() else ""
    bad += [f"AppShell.tsx не рисует sig.{k}" for k in keys if f"sig.{k}" not in tsx]
    res.ok("каждый баннер каркаса — сигнал оболочки", not bad,
           "баннер не виден ни на одном экране: " + "; ".join(bad))

    # ---- список демо-отказов не протух (демо с сайта, 01.10) ----
    # `core/demo.py` закрывает в демо адреса, меняющие машину и учётки, —
    # списком ПРЕФИКСОВ, который ВКЛЮЧАЕТ запрет (полярность из карты):
    # переименованный маршрут делает строку пустой, и запрет исчезает молча.
    # Строка, под которую не подходит ни один живой маршрут, краснеет здесь.
    # Вторая половина — сам отказ: шлюз в main.py и фильтр плиток хаба обязаны
    # спрашивать `demo.refuses`; без них список — правда, которую никто не
    # спрашивает. Адреса маршрутов собираются из декораторов, включая
    # `PAGE + "/confirm"` раздвоения — константы модуля разворачиваются.
    bad = []
    demo_tree = by_path.get("app/core/demo.py")
    blocked = []
    for n in _walk(demo_tree) if demo_tree else ():
        if (isinstance(n, ast.Assign) and isinstance(n.value, ast.Tuple)
                and any(isinstance(t, ast.Name) and t.id == "BLOCKED" for t in n.targets)):
            blocked = [e.value for e in n.value.elts if isinstance(e, ast.Constant)]
    if not blocked:
        bad.append("app/core/demo.py: нет кортежа BLOCKED — якорь правила пропал")

    def _route_str(node, consts: dict) -> str | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name):
            return consts.get(node.id)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left, right = _route_str(node.left, consts), _route_str(node.right, consts)
            return left + right if left is not None and right is not None else None
        return None

    routes = set()
    for rel, tree in src:
        consts = {t.id: n.value.value for n in tree.body if isinstance(n, ast.Assign)
                  and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)
                  for t in n.targets if isinstance(t, ast.Name)}
        for n in _walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for d in n.decorator_list:
                    if (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                            and d.func.attr in ("get", "post") and d.args):
                        path = _route_str(d.args[0], consts)
                        if path:
                            routes.add(path)
    if not routes:
        bad.append("маршрутов не найдено — обход декораторов сломан")
    for p in blocked:
        head = p if p.endswith("/") else p + "/"
        if not any(r == p or r.startswith(head) for r in routes):
            bad.append(f"demo.BLOCKED: под «{p}» нет ни одного маршрута — адрес переименован?")

    def _asks_demo(rel: str) -> bool:
        tree = by_path.get(rel)
        return bool(tree) and any(
            isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "refuses" and isinstance(n.func.value, ast.Name)
            and n.func.value.id == "demo" for n in _walk(tree))
    bad += [f"{rel} не зовёт demo.refuses — список есть, отказа нет"
            for rel in ("app/main.py", "app/modules/settings/routes.py") if not _asks_demo(rel)]
    res.ok("список демо-отказов не протух", not bad,
           "демо закрывает не те адреса: " + "; ".join(bad))

    # ---- опасное из сети — только с этого ПК (02.11, разбор коллеги Б3) ----
    # `auth.LOCAL_ONLY` — ОДИН список маршрутов, которые выдают ключ или
    # картотеку целиком, меняют шифрование, копии, учётки, восстановление. В
    # сети клиники канал — http и кука 12 ч: забытая проверка = подсмотренная
    # кука директора с телефона уносит всё. Правило в три стороны:
    #   1) маршрут из списка зовёт `local_only` сразу за охраной входа — раньше
    #      любой работы (иначе экспорт успел бы собрать архив);
    #   2) каждая строка списка совпадает с живым маршрутом (полярность
    #      ВКЛЮЧАЮЩАЯ: переименованный адрес выпал бы из охраны молча);
    #   3) маршрут, зовущий `local_only`, стоит в списке — иначе список врёт, а
    #      экраны и наборы читают именно его.
    bad = []
    auth_tree = by_path.get(_AUTH_MODULE)
    local_only = set()
    for n in _walk(auth_tree) if auth_tree else ():
        if (isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "LOCAL_ONLY" for t in n.targets)):
            local_only = {e.value for e in _walk(n.value)
                          if isinstance(e, ast.Constant) and isinstance(e.value, str)}
    if not local_only:
        bad.append(f"{_AUTH_MODULE}: нет LOCAL_ONLY — якорь правила пропал")
    _GUARDS = {"require", "api_require", "api_guard", "_guard"}

    def _guard_call(stmt, names) -> bool:
        return (isinstance(stmt, ast.If) and any(
            isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id in names
            for c in _walk(stmt.test))
            and len(stmt.body) == 1 and isinstance(stmt.body[0], ast.Return))

    seen = set()
    for rel, tree in src:
        for fn in _walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            paths = {d.args[0].value for d in fn.decorator_list
                     if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                     and d.func.attr in ("get", "post") and d.args
                     and isinstance(d.args[0], ast.Constant)}
            if not paths:
                continue
            body = fn.body[1:] if (fn.body and isinstance(fn.body[0], ast.Expr)
                                   and isinstance(fn.body[0].value, ast.Constant)) else fn.body
            rest = list(body)
            while rest and _guard_call(rest[0], _GUARDS):
                rest.pop(0)
            first_local = bool(rest) and _guard_call(rest[0], {"local_only"})
            calls_local = any(isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                              and c.func.id == "local_only" for c in _walk(fn))
            for p in paths:
                if p in local_only:
                    seen.add(p)
                    if not first_local:
                        bad.append(f"{rel}:{fn.lineno} {p} — нет `local_only` сразу за "
                                   f"охраной входа")
                elif calls_local:
                    bad.append(f"{rel}:{fn.lineno} {p} зовёт local_only, но его нет в "
                               f"auth.LOCAL_ONLY")
    bad += [f"auth.LOCAL_ONLY: «{p}» — нет такого маршрута (переименован?)"
            for p in sorted(local_only - seen)]
    res.ok("опасное из сети — только с этого ПК", not bad,
           "маршрут, выдающий ключ, картотеку или учётки, доступен из сети "
           "клиники: " + "; ".join(bad))

    # ---- каждый файл сборки клиента — в образе демо и в обоих игнорах (07.10) ----
    # Сборка клиента кладёт файлы в статику движка (vite.config.ts). В exe они
    # едут ПАПКОЙ (`--add-data`, новое имя подхватится само), а образ демо
    # копирует их из стадии `client` ПОИМЁННО. Свои модели зубов (`teeth.js`,
    # 1.39.1) дописали в конфиг и в оба игнора, а в Dockerfile — нет, и ничего
    # не покраснело: 3D на demo.dentpilot.md не упал бы, а молча строил
    # коронки-формулы (поймано перед обновлением демо, 892d69b).
    # Каждое имя выхода обязано стоять в трёх местах:
    #   demo/Dockerfile — `COPY --from=… …/static/<kind>/<имя>` в static/
    #                     приложения;
    #   .gitignore      — это артефакт: закоммиченная копия отстала бы от
    #                     источника;
    #   .dockerignore   — иначе локальная копия уехала бы в образ через
    #                     `COPY bot/app` и спрятала пропавшую строку у того, кто
    #                     собирает образ у себя, — а на сервере, из чистого
    #                     checkout, файла нет.
    # ⚠️ Полярность опасная: имена — список ВКЛЮЧАЮЩИЙ, собранный разбором
    # конфига. Разбор, переставший видеть файл, выключил бы для него правило
    # молча, поэтому каждая запись файла в конфиге обязана разобраться, а среди
    # имён обязаны быть оба бандла.
    # ⚠️ Копию папкой или маской правило не разбирает и прочтёт как пропажу:
    # образ копирует поимённо, строкой на файл, — эту запись оно и держит.
    bad, text = [], {}
    for rel in BUILD_FILES:
        p = BUILD / rel
        text[rel] = p.read_text(encoding="utf-8-sig") if p.exists() else ""
        if not text[rel]:
            bad.append(f"нет {rel} — сверять не с чем")
    outputs, blind = _vite_outputs(_client_code(text[_VITE_CONFIG]))
    bad += blind
    bad += [f"{_VITE_CONFIG}: среди выходов нет {name} — разбор его потерял, "
            "правило сверяет не тот список"
            for name in ("js/bundle.js", "css/bundle.css") if name not in outputs]
    copies = _docker_copies(text[_DEMO_IMAGE])
    hidden = {rel: _ignore_entries(text[rel]) for rel in _IGNORES}
    for path in sorted(outputs):
        # маршрут отдаёт файл из static/<kind>/: туда файлом или в папку
        kind, dests = path.rpartition("/")[0], _copied_to(copies, path)
        if not dests:
            bad.append(f"{_DEMO_IMAGE} не копирует static/{path} из сборки клиента")
        elif not any(d.endswith((f"/static/{path}", f"/static/{kind}/")) for d in dests):
            bad.append(f"{_DEMO_IMAGE} кладёт static/{path} мимо static/{kind}/ "
                       f"приложения: {', '.join(dests)}")
        bad += [f"{rel}: нет bot/app/static/{path}" for rel in _IGNORES
                if f"bot/app/static/{path}" not in hidden[rel]]
    res.ok("каждый файл сборки клиента — в образе демо и в обоих игнорах", not bad,
           "файл, который сборка пишет, а образ демо не везёт, ничего не роняет — "
           "экран молча работает без него (teeth.js, 07.10): " + "; ".join(bad))

    # ---- подстановки SMS — белый список (S5, 16.10) ----
    # SMS читают с экрана блокировки, и текст проходит через двух обработчиков
    # (сервер лицензий, sms.md): «extracție la 10:30» или имя врача — уже данные
    # о здоровье. Готовые тексты держат только `{clinica}`, `{ziua}`, `{data}`,
    # `{ora}`, `{telefon}` — список PLACEHOLDERS в core/sms_plan.py, и каждая
    # подстановка в текстах TEXTS / PHONE_LINE / RECALL_TEXTS («Rechemări»,
    # 30.10 — второй словарь, тот же список) обязана быть из него.
    # ⚠️ Полярность: список ВКЛЮЧАЮЩИЙ — отсюда вторая проверка: в нём самом нет
    # врача, услуги и имени (иначе «{medic}» легализуется одной строкой).
    bad, allowed, seen = [], set(), set()
    plan_tree = by_path.get("app/core/sms_plan.py")

    def _texts_of(node) -> set:
        return {c.value for c in _walk(node)
                if isinstance(c, ast.Constant) and isinstance(c.value, str)}
    for n in _walk(plan_tree) if plan_tree else ():
        if not isinstance(n, ast.Assign):
            continue
        names = {t.id for t in n.targets if isinstance(t, ast.Name)}
        # и `TEXTS["ro"][…] = …`: дописанный мимо словаря текст — тот же текст
        names |= {t.value.id for t in n.targets if isinstance(t, ast.Subscript)
                  and isinstance(t.value, ast.Name)}
        names |= {t.value.value.id for t in n.targets if isinstance(t, ast.Subscript)
                  and isinstance(t.value, ast.Subscript) and isinstance(t.value.value, ast.Name)}
        if "PLACEHOLDERS" in names:
            allowed = _texts_of(n.value)
        if names & {"TEXTS", "PHONE_LINE", "RECALL_TEXTS"}:
            for text in _texts_of(n.value):
                for hole in re.findall(r"\{([a-z_]+)\}", text):
                    seen.add(hole)
                    if allowed and hole not in allowed:
                        bad.append(f"app/core/sms_plan.py:{n.lineno} {{{hole}}}")
    if not plan_tree:
        bad.append("app/core/sms_plan.py не найден")
    if not allowed:
        bad.append("core/sms_plan.py: списка PLACEHOLDERS не найдено — якорь правила пропал")
    if not seen & allowed:
        bad.append("в текстах TEXTS/PHONE_LINE нет ни одной подстановки — якорь правила пропал")
    if plan_tree and not any(isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "RECALL_TEXTS"
                                                               for t in n.targets) for n in _walk(plan_tree)):
        bad.append("core/sms_plan.py: словаря RECALL_TEXTS не найдено — тексты Rechemări ушли из-под правила")
    res.ok("подстановки SMS — белый список", not bad,
           "в тексте SMS появились данные, которых в нём быть не может: " + "; ".join(bad))
    forbidden = {"medic", "doctor", "serviciu", "service", "nume", "name", "pacient",
                 "patient", "procedura", "tratament", "dinte"}
    hit = sorted(allowed & forbidden)
    res.ok("белый список SMS без врача, услуги и имени", bool(allowed) and not hit,
           "PLACEHOLDERS легализует данные о здоровье: " + ", ".join(hit))

    # ---- «мало SMS» — одно правило по штукам (Tauri, Т8, 18.10) ----
    # Олег 18.10: SMS мало — 30 у платного остатка, 10 в пробном; одно правило
    # для подсказки у пункта меню, баннера экрана SMS и уведомления у часов.
    # До того баннер жил «меньше чем на 4 дня расхода», а уведомление шло бы по
    # штукам: два порога одного состояния расходятся молча — меню молчит, часы
    # кричат. Поэтому: пороги читает ТОЛЬКО `sms_loop.low_limit`; три места
    # берут состояние у `sms_loop.low`; ни одно сравнение остатка с числом
    # мимо `low_limit` не живёт.
    # ⚠️ Полярность: список потребителей ВКЛЮЧАЮЩИЙ — каждый обязан найтись.
    low_users = {(_LAY_BANNERS, "_sms_alert"), ("app/core/sms_loop.py", "_low_view"),
                 ("app/core/notices.py", "sms_item")}
    bad, found, reads = [], set(), 0
    for rel, tree in src:
        for fn in _walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and (rel, fn.name) in low_users:
                found.add((rel, fn.name))
                if "low" not in _calls(fn):
                    bad.append(f"{rel}:{fn.lineno} {fn.name}() не берёт состояние у sms_loop.low()")
        for n in _walk(tree):
            name = (n.id if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
                    else n.attr if isinstance(n, ast.Attribute) else "")
            if name in ("LOW_PAID", "LOW_TRIAL"):
                if rel == "app/core/sms_loop.py" and "low_limit" in _enclosing(tree, n.lineno):
                    reads += 1
                else:
                    bad.append(f"{rel}:{n.lineno} порог {name} мимо low_limit")
            if name == "LOW_DAYS" or (isinstance(n, ast.Name) and n.id == "LOW_DAYS"):
                bad.append(f"{rel}:{n.lineno} LOW_DAYS — порог по дням снят 18.10")
            if isinstance(n, ast.Compare) and "low_limit" not in _enclosing(tree, n.lineno):
                consts = [c.value for c in _walk(n) if isinstance(c, ast.Constant)]
                if "balance" in consts and any(isinstance(v, (int, float)) and not isinstance(v, bool)
                                               for v in consts):
                    bad.append(f"{rel}:{n.lineno} остаток SMS сравнивается с числом мимо low_limit")
    bad += [f"{rel}: {name}() не найден — список потребителей протух"
            for rel, name in sorted(low_users - found)]
    if reads < 2:
        bad.append("sms_loop.low_limit не читает LOW_PAID и LOW_TRIAL — якорь правила пропал")
    res.ok("«мало SMS» — одно правило по штукам", not bad,
           "меню, экран SMS и уведомление у часов разойдутся молча: " + "; ".join(bad))

    # ---- /shell/* — только оболочке этого ПК (Tauri, контракт § 4) ----
    # Уведомления у часов спрашивает оболочка без сессии: охрана — токен её
    # запуска, loopback и заголовок (`notices.shell_request_ok`). Маршрут
    # `/shell/…` без неё отдал бы срок лицензии и остаток SMS любому
    # телефону в сети клиники. Якорь — хотя бы один такой маршрут есть.
    bad, n_shell = [], 0
    for rel, tree in src:
        for fn in _walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            paths_ = [d.args[0].value for d in fn.decorator_list
                      if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                      and d.func.attr in ("get", "post", "put", "delete", "patch")
                      and d.args and isinstance(d.args[0], ast.Constant)
                      and isinstance(d.args[0].value, str)]
            if not any(p.startswith("/shell/") for p in paths_):
                continue
            n_shell += 1
            if "shell_request_ok" not in _calls(fn):
                bad.append(f"{rel}:{fn.lineno} {fn.name}() без shell_request_ok")
    if not n_shell:
        bad.append("ни одного маршрута /shell/ — якорь правила пропал")
    res.ok("маршруты /shell/ охраняет токен оболочки", not bad,
           "срок лицензии и остаток SMS ушли бы в сеть клиники: " + "; ".join(bad))

    # ⛔ Файл открывает только `core/shellopen` (18.10, 2.0.3). `os.startfile` —
    # ShellExecute в процессе движка: Word рождается его ребёнком в «задании»
    # оболочки Tauri (KILL_ON_JOB_CLOSE) и гаснет вместе с DentPilot — с
    # несохранённой правкой врача. Поведение держит стенд
    # `test_patient_card.suite_doc_outlives_shell`; здесь — чтобы новое
    # открытие не завело болезнь заново в другом месте.
    bad = [f"{rel}:{n.lineno}" for rel, tree in src for n in _walk(tree)
           if isinstance(n, ast.Call) and isinstance(n.func, (ast.Name, ast.Attribute))
           and (n.func.id if isinstance(n.func, ast.Name) else n.func.attr) == "startfile"]
    res.ok("файл открывает только core/shellopen, не os.startfile", not bad,
           "программа, открытая так, гаснет вместе с оболочкой: " + "; ".join(bad))

    # ⛔ Колонтитулы браузера на бумаге (Олег 08.11: «убрать»): дату, заголовок,
    # адрес страницы и номер листа Chromium печатает в верхнем и нижнем поле
    # листа. Гасит их ОДНО правило `theme.PRINT_PAGE_CSS` (поле 0, отступ 1 см
    # у тела на каждом листе — раскладка прежняя до строки). Серверный бланк
    # с кнопкой печати без него снова напечатает «127.0.0.1:8088/admin/…» на
    # 043/e; листы React берут то же правило дословно из panel.css.
    bad, sheets_n, page_css = [], 0, None
    for rel, tree in src:
        if rel == "app/core/theme.py":
            for n in tree.body:
                if (isinstance(n, ast.Assign) and len(n.targets) == 1
                        and isinstance(n.targets[0], ast.Name) and n.targets[0].id == "PRINT_PAGE_CSS"):
                    page_css = ast.literal_eval(n.value)
        prints = any(isinstance(c, ast.Constant) and isinstance(c.value, str)
                     and re.search(r"""onclick=["']window\.print\(\)""", c.value)
                     for c in _walk(tree))
        if not prints:
            continue
        sheets_n += 1
        if not any(isinstance(n, ast.Attribute) and n.attr == "PRINT_PAGE_CSS" for n in _walk(tree)):
            bad.append(f"{rel}: кнопка window.print() без theme.PRINT_PAGE_CSS")
    if page_css is None:
        bad.append("theme.PRINT_PAGE_CSS не найден — якорь правила пропал")
    elif "@page{margin:0" not in page_css:
        bad.append("theme.PRINT_PAGE_CSS не обнуляет поле листа")
    elif page_css not in ((BOT / "app/static/css/panel.css").read_text(encoding="utf-8")
                          if (BOT / "app/static/css/panel.css").exists() else ""):
        bad.append("panel.css не держит theme.PRINT_PAGE_CSS дословно — листы React напечатают колонтитулы")
    if sheets_n < 5:
        bad.append(f"печатных бланков с кнопкой нашлось {sheets_n} — якорь правила пропал")
    res.ok("печатный лист без колонтитулов браузера", not bad,
           "дата, адрес и номер листа лягут на бумагу: " + "; ".join(bad))

    # «Registre» (10.11.2026): журналы санитарных регистров (257/e, 502/e,
    # 501/e) только ДОПИСЫВАЮТСЯ — это и есть их юридическая сила: подпись
    # строки (кто и когда) ставит программа, исправление — новая строка с
    # причиной, старая остаётся. UPDATE строки журнала живёт в одном месте —
    # `db/registre.py`, и только однократным заполнением ПУСТОГО поля (замок
    # `IS NULL` в самом SQL) или мягким удалением. Правка мимо него («поправить
    # время цикла на месте») молча превратила бы журнал в редактируемую таблицу:
    # ни ошибки, ни следа на листе, который подписывает руководитель.
    _SAN = re.compile(r"\b(?:UPDATE|DELETE\s+FROM|REPLACE\s+INTO|INSERT\s+OR\s+REPLACE\s+INTO)\s+"
                      r"(?:san_cycles|san_cleanings|san_uv)\b", re.I)
    _SAN_ANY = re.compile(r"\b(?:UPDATE|DELETE\s+FROM)\s+\{", re.I)

    def _sql_texts(tree):
        for n in _walk(tree):
            if isinstance(n, ast.Constant) and isinstance(n.value, str):
                yield n.lineno, n.value
            elif isinstance(n, ast.JoinedStr):
                yield n.lineno, "".join(v.value if isinstance(v, ast.Constant) else "{}" for v in n.values)

    bad, owner = [], by_path.get(_DB_SAN)
    for rel, tree in src:
        for line, text in _sql_texts(tree):
            if rel != _DB_SAN and _SAN.search(text):
                bad.append(f"{rel}:{line} пишет журнал san_* мимо {_DB_SAN}")
            if rel == _DB_SAN and (_SAN_ANY.search(text) or _SAN.search(text)):
                if re.search(r"DELETE\s+FROM", text, re.I):
                    bad.append(f"{rel}:{line} DELETE строки журнала — удаление только мягкое (deleted_at)")
                elif "IS NULL" not in text:
                    bad.append(f"{rel}:{line} UPDATE журнала без замка «IS NULL» — перезапись записанного")
    if owner is None or not any(isinstance(n, ast.AsyncFunctionDef) and n.name == "san_close" for n in owner.body):
        bad.append(f"{_DB_SAN} без san_close — якорь правила пропал")
    res.ok("журналы san_* только дописываются", not bad, "; ".join(bad))

    # Заказ в лабораторию — письменное назначение изделия на заказ: он не
    # удаляется (только `anulat`), а его история `lab_events` только
    # дописывается — отмена шага тоже событие. Статус шапки — пересчёт истории
    # (`core/lab.replay`), и правленная или стёртая строка истории молча
    # переписала бы, когда работу отправили и сколько было переделок.
    # Физическое стирание пациента идёт шаблоном по `_PATIENT_GRAND_CHILDREN`
    # (имя таблицы не литералом) и сюда не попадает намеренно.
    _LAB_EV = re.compile(r"\b(?:UPDATE|DELETE\s+FROM|REPLACE\s+INTO|INSERT\s+OR\s+REPLACE\s+INTO)\s+lab_events\b",
                         re.I)
    _LAB_DROP = re.compile(r"\b(?:DELETE\s+FROM|REPLACE\s+INTO|INSERT\s+OR\s+REPLACE\s+INTO|DROP\s+TABLE)\s+"
                           r"(?:IF\s+EXISTS\s+)?lab_orders\b", re.I)
    bad, owner = [], by_path.get(_DB_LAB)
    for rel, tree in src:
        for line, text in _sql_texts(tree):
            if _LAB_EV.search(text):
                bad.append(f"{rel}:{line} правит или стирает историю заказа lab_events")
            if _LAB_DROP.search(text):
                bad.append(f"{rel}:{line} удаляет заказ lab_orders — только «anulat»")
    if owner is None or not any(isinstance(n, ast.AsyncFunctionDef) and n.name == "_event_insert"
                                for n in owner.body):
        bad.append(f"{_DB_LAB} без _event_insert — якорь правила пропал")
    res.ok("заказ в лабораторию не удаляется, история только дописывается", not bad, "; ".join(bad))

    # Остаток склада — сумма журнала `stock_moves`; исправление — новая строка
    # `corectie`. Правленная или стёртая строка молча переписала бы остаток и
    # среднюю цену задним числом, и инвентаризация сверялась бы уже с выдумкой.
    # Писать строку — только `db/stock._stock_move_insert`. Физическое стирание
    # пациента идёт шаблоном по `_PATIENT_CHILD_TABLES` и сюда не попадает.
    _ST_EDIT = re.compile(r"\b(?:UPDATE|DELETE\s+FROM|REPLACE\s+INTO|INSERT\s+OR\s+REPLACE\s+INTO|DROP\s+TABLE)\s+"
                          r"(?:IF\s+EXISTS\s+)?stock_moves\b", re.I)
    _ST_INS = re.compile(r"\bINSERT\s+INTO\s+stock_moves\b", re.I)
    bad, owner = [], by_path.get(_DB_STOCK)
    for rel, tree in src:
        for line, text in _sql_texts(tree):
            if _ST_EDIT.search(text):
                bad.append(f"{rel}:{line} правит или стирает строку журнала склада stock_moves")
            if _ST_INS.search(text) and rel != _DB_STOCK:
                bad.append(f"{rel}:{line} пишет журнал склада мимо {_DB_STOCK}")
    if owner is None or not any(isinstance(n, ast.AsyncFunctionDef) and n.name == "_stock_move_insert"
                                for n in owner.body):
        bad.append(f"{_DB_STOCK} без _stock_move_insert — якорь правила пропал")
    res.ok("журнал склада только дописывается", not bad, "; ".join(bad))

    # Списание по техкарте — следствие перехода позиции плана: кто ставит
    # статус позиции, тот зовёт крючок склада. Путь без крючка молча оставил бы
    # склад без автосписания и без возврата при «Redeschide».
    bad, seen = [], 0
    for rel, tree in src:
        if rel.startswith("app/db/"):
            continue
        for fn in _walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and "set_plan_status" in _calls(fn):
                seen += 1
                if "on_plan_status" not in _calls(fn):
                    bad.append(f"{rel}:{fn.lineno} {fn.name}() ставит статус позиции без stock_tc.on_plan_status")
    if seen < 2:
        bad.append(f"нашлось {seen} мест, ставящих статус позиции плана (ждали ≥ 2) — правило ослепло")
    res.ok("статус позиции плана — вместе с крючком склада", not bad, "; ".join(bad))

    # Профиль клиники пишется целиком, поэтому писатели перечислены: набор
    # `test_plan_tpl.suite_writers` на каждого требует действие и проверяет, что
    # чужой раздел (шаблоны плана, их счётчик) запись пережил. Писатель мимо
    # списка — запись, которую этот набор не видел; имя из списка, которого в
    # коде уже нет, — действие набора, которое больше ничего не проверяет.
    found = {f"{rel}:{fn.name}" for rel, tree in src if rel != "app/engine.py"
             for fn in _walk(tree) if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
             and "save_config" in _calls(fn)}
    bad = [f"{w} пишет clinic.json, но его нет в _CFG_WRITERS" for w in sorted(found - _CFG_WRITERS)]
    bad += [f"{w} из _CFG_WRITERS больше не зовёт save_config" for w in sorted(_CFG_WRITERS - found)]
    eng_tree = by_path.get("app/engine.py")
    if eng_tree is None or not any(isinstance(n, ast.FunctionDef) and n.name == "save_config"
                                   for n in eng_tree.body):
        bad.append("app/engine.py без save_config — якорь правила пропал")
    res.ok("писатели clinic.json перечислены", not bad, "; ".join(bad))

    # Визит фише по номеру ставит одно правило: имя мимо списка — третья копия порядка проверок
    # окна записи; имя из списка, переставшее звать, — список, который ничего не держит.
    found = {f"{rel}:{fn.name}" for rel, tree in src if not rel.startswith("app/db/")
             for fn in _walk(tree) if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
             and "add_visit_for_patient" in _calls(fn)}
    bad = [f"{w} ставит визит фише мимо book.book_visit" for w in sorted(found - _VISIT_BY_ID)]
    bad += [f"{w} из _VISIT_BY_ID больше не зовёт add_visit_for_patient"
            for w in sorted(_VISIT_BY_ID - found)]
    day_tree = by_path.get(_DB_DAY)
    if day_tree is None or not any(isinstance(n, ast.AsyncFunctionDef) and n.name == "add_visit_for_patient"
                                   for n in day_tree.body):
        bad.append(f"{_DB_DAY} без add_visit_for_patient — якорь правила пропал")
    res.ok("визит фише по номеру — только через book_visit", not bad, "; ".join(bad))

    # Импорт с записями: в журнал — только через book; якоря — проба и запись в импорте, обе
    # функции в core/book.py (список включающий: пропавшее имя иначе выключило бы правило молча).
    bad = []
    imp = {rel: by_path.get(rel) for rel in _PIMPORT}
    for rel, tree in imp.items():
        if tree is None:
            bad.append(f"{rel} не найден — якорь правила пропал")
            continue
        for fn in _walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for name in sorted(_calls(fn) & _APPT_WRITERS):
                    bad.append(f"{rel}:{fn.name} пишет в журнал мимо book ({name})")
        for n in _walk(tree):
            if (isinstance(n, ast.Constant) and isinstance(n.value, str)
                    and re.search(r"(?i)\b(insert\s+(or\s+\w+\s+)?into|update)\s+appointments\b", n.value)):
                bad.append(f"{rel}:{n.lineno} пишет в appointments своим SQL")
    called = set().union(*(_calls(t) for t in imp.values() if t is not None))
    bad += [f"импорт больше не зовёт book.{name}" for name in ("book_visit", "probe") if name not in called]
    book_tree = by_path.get("app/core/book.py")
    defs = {n.name for n in (book_tree.body if book_tree else []) if isinstance(n, ast.AsyncFunctionDef)}
    bad += [f"app/core/book.py без {name} — якорь правила пропал" for name in ("book_visit", "probe")
            if name not in defs]
    res.ok("импорт ставит визиты только через book", not bad, "; ".join(bad))

    # ---- перенос из Google Calendar пачкой и автоматом ----
    gauto, gcal_t, dbg = by_path.get(_GAUTO), by_path.get(_GCAL), by_path.get(_DB_GCAL)
    funcs = {}
    for rel, tree in ((_GCAL, gcal_t), (_GAUTO, gauto)):
        for fn in _walk(tree) if tree is not None else ():
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                funcs[f"{rel}:{fn.name}"] = fn

    def _locks(fn) -> bool:
        return any(isinstance(n, ast.AsyncWith) and any(
            isinstance(it.context_expr, ast.Call) and _calls(it.context_expr) == {"move_lock"}
            for it in n.items) for n in _walk(fn))

    # Фоновый перенос подписан «sistem»: проход ставит подпись до работы и возвращает прежнюю в finally.
    bad = []
    if gauto is None:
        bad.append(f"{_GAUTO} не найден — якорь правила пропал")
    else:
        system = [n.value for n in gauto.body if isinstance(n, ast.Assign)
                  and any(isinstance(t, ast.Name) and t.id == "SYSTEM" for t in n.targets)]
        name = next((v.value for d in system if isinstance(d, ast.Dict)
                     for k, v in zip(d.keys, d.values) if isinstance(k, ast.Constant) and k.value == "name"
                     and isinstance(v, ast.Constant)), None)
        if name != "sistem":
            bad.append(f"{_GAUTO}: SYSTEM подписан {name!r}, а не «sistem»")
        fn = funcs.get(f"{_GAUTO}:auto_pass")
        if fn is None:
            bad.append(f"{_GAUTO}: нет auto_pass — якорь правила пропал")
        else:
            sets = [n for n in _walk(fn) if isinstance(n, ast.Call) and _calls(n) == {"set_request_user"}]
            if not any(isinstance(x, ast.Name) and x.id == "SYSTEM" for c in sets for x in c.args):
                bad.append("auto_pass не ставит подпись SYSTEM")
            if not any(isinstance(t, ast.Try) and any("set_request_user" in _calls(x) for x in t.finalbody)
                       for t in _walk(fn)):
                bad.append("auto_pass не возвращает прежнюю подпись в finally")
    res.ok("автоперенос подписан «sistem»", not bad, "; ".join(bad))

    # Один замок на перенос по одному, «Leagă», пачку, автоперенос, отмену и кнопки «schimbat».
    bad = [f"{w} — нет такой функции (переименована?)" for w in sorted(_GCAL_LOCKED - set(funcs))]
    bad += [f"{w} не берёт move_lock" for w in sorted(_GCAL_LOCKED & set(funcs)) if not _locks(funcs[w])]
    locked = {k for k, fn in funcs.items() if _locks(fn)}
    for key, fn in sorted(funcs.items()):
        if key in locked or not (_calls(fn) & _GCAL_WRITES):
            continue
        name = key.rsplit(":", 1)[1]
        callers = [k for k, f in funcs.items() if k != key and name in _calls(f)]
        if not callers:
            bad.append(f"{key} пишет журнал из вкладки без замка переноса")
        bad += [f"{key} пишет журнал, а зовёт его {c} без замка переноса" for c in callers if c not in locked]
    if gcal_t is not None and not any(isinstance(n, ast.FunctionDef) and n.name == "move_lock"
                                      for n in gcal_t.body):
        bad.append(f"{_GCAL} без move_lock — якорь правила пропал")
    res.ok("один замок на перенос по одному, «Leagă», пачку и автоперенос", not bad, "; ".join(bad))

    # Автоперенос спрашивает право `gcal` и рабочую лицензию сам: ворота 423 стоят только на запросах.
    bad = []
    allowed = funcs.get(f"{_GAUTO}:allowed")
    if allowed is None:
        bad.append(f"{_GAUTO}: нет allowed — якорь правила пропал")
    else:
        if "feature_until" not in _calls(allowed):
            bad.append("allowed не спрашивает право gcal (feature_until)")
        if not {"ACTIVE", "GRACE"} <= {n.attr for n in _walk(allowed) if isinstance(n, ast.Attribute)}:
            bad.append("allowed не спрашивает режим лицензии (ACTIVE/GRACE)")
    fn = funcs.get(f"{_GAUTO}:auto_pass")
    body = (fn.body[1:] if isinstance(fn.body[0], ast.Expr) else fn.body) if fn is not None else []
    if not body or not (isinstance(body[0], ast.If) and "allowed" in _calls(body[0].test)):
        bad.append("auto_pass не начинает с allowed()")
    res.ok("автоперенос спрашивает гейт и режим чтения", not bad, "; ".join(bad))

    # Отмена снимает только нетронутые: отпечаток записи и дети — в одном скрипте с удалением;
    # пустая новая фиша — только после erasure_kind и import_untouched; другого удаления записи нет.
    bad = []
    un = next((n for n in (dbg.body if dbg else [])
               if isinstance(n, ast.AsyncFunctionDef) and n.name == "gcal_unmove"), None)
    if un is None:
        bad.append(f"{_DB_GCAL}: нет gcal_unmove — якорь правила пропал")
    else:
        script = [n for n in _walk(un) if isinstance(n, ast.JoinedStr) and any(
            isinstance(v, ast.Constant) and "DELETE FROM appointments" in str(v.value) for v in n.values)]
        names = {v.value.id for n in script for v in n.values
                 if isinstance(v, ast.FormattedValue) and isinstance(v.value, ast.Name)}
        if not script:
            bad.append("gcal_unmove не удаляет запись своим скриптом")
        if "_APPT_SIG" not in names:
            bad.append("gcal_unmove не сверяет отпечаток записи (_APPT_SIG)")
        free = [n for n in _walk(un) if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id in names for t in n.targets)
                and any(isinstance(x, ast.Name) and x.id == "_APPT_CHILDREN" for x in _walk(n.value))]
        if not free:
            bad.append("gcal_unmove не проверяет детей записи (_APPT_CHILDREN)")
    undo = funcs.get(f"{_GAUTO}:undo")
    if undo is None:
        bad.append(f"{_GAUTO}: нет undo — якорь правила пропал")
    elif "delete_patient_fully" in _calls(undo) and not {"erasure_kind", "import_untouched"} <= _calls(undo):
        bad.append("undo удаляет фишу, не спросив erasure_kind и import_untouched")
    for rel, tree in ((_GCAL, gcal_t), (_GAUTO, gauto)):
        for n in _walk(tree) if tree is not None else ():
            if (isinstance(n, ast.Constant) and isinstance(n.value, str)
                    and re.search(r"(?i)\bdelete\s+from\s+appointments\b", n.value)):
                bad.append(f"{rel}:{n.lineno} удаляет запись своим SQL")
    res.ok("отмена снимает только нетронутые", not bad, "; ".join(bad))

    # Пачка и автоперенос подписывают «Programare: …» тем, кто перенёс: бронь из вкладки идёт под
    # `db.booked_by`, а строка брони читает эту подпись; окно журнала подписано каналом, как было.
    bad = []
    ev = by_path.get("app/db/events.py")
    log_b = next((n for n in (ev.body if ev else []) if isinstance(n, ast.AsyncFunctionDef)
                  and n.name == "_log_booking"), None)
    if log_b is None:
        bad.append("app/db/events.py: нет _log_booking — якорь правила пропал")
    elif not any(isinstance(n, ast.Name) and n.id == "_BOOKER" for n in _walk(log_b)):
        bad.append("_log_booking не читает подпись брони (_BOOKER)")
    apply_fn = funcs.get(f"{_GAUTO}:_apply")
    if apply_fn is None:
        bad.append(f"{_GAUTO}: нет _apply — якорь правила пропал")
    else:
        wrapped = {id(c) for w in _walk(apply_fn) if isinstance(w, ast.With)
                   and any(isinstance(it.context_expr, ast.Call) and _calls(it.context_expr) == {"booked_by"}
                           for it in w.items)
                   for c in _walk(w) if isinstance(c, ast.Call)}
        calls = [c for c in _walk(apply_fn) if isinstance(c, ast.Call) and _calls(c) == {"_journal_add"}]
        if not calls:
            bad.append("_apply больше не ставит запись через _journal_add — якорь правила пропал")
        bad += [f"{_GAUTO}:{c.lineno} бронь пачки или автопереноса без db.booked_by" for c in calls
                if id(c) not in wrapped]
    res.ok("перенос из Google подписывает запись тем, кто перенёс", not bad, "; ".join(bad))
