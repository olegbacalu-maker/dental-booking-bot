"""Прогон всех проверок DentPilot.

    D:\\DentProject\\app\\.venv-desktop\\Scripts\\python.exe tests\\run_tests.py

Ничего ставить не нужно: только стандартная библиотека. Каждый набор поднимает
СВОЙ сервер на свободном порту со своей временной базой, поэтому прогон не
трогает ни установленную программу, ни чужие песочницы, и наборы не мешают
друг другу.

Код выхода 1 при любой неудаче — чтобы прогон годился как ворота перед сборкой.
"""
import pathlib
import sys

# Консоль Windows живёт в cp1251, а отчёт о НЕУДАЧЕ печатает знак ✗ — и прогон
# с красной проверкой падал UnicodeEncodeError, унося ИМЯ упавшего (замечено
# 08-20: трейс вместо ответа «что сломалось»). Плохой символ дешевле потерять,
# чем весь отчёт.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import test_activity  # noqa: E402
import test_admin  # noqa: E402
import test_admin_canvas  # noqa: E402
import test_anamneza  # noqa: E402
import test_api  # noqa: E402
import test_booking  # noqa: E402
import test_dbcrypt  # noqa: E402
import test_doctors  # noqa: E402
import test_doctor_windows  # noqa: E402
import test_day_actions  # noqa: E402
import test_day_forms  # noqa: E402
import test_grid  # noqa: E402
import test_guards  # noqa: E402
import test_hardening  # noqa: E402
import test_launcher  # noqa: E402
import test_installer  # noqa: E402
import test_legacy  # noqa: E402
import test_react_default  # noqa: E402
import test_relocate  # noqa: E402
import test_split  # noqa: E402
import test_srcpin  # noqa: E402
import test_migrate  # noqa: E402
import test_odontogram_api  # noqa: E402
import test_bot  # noqa: E402
import test_perio  # noqa: E402
import test_perio_api  # noqa: E402
import test_pin  # noqa: E402
import test_plan_acord  # noqa: E402
import test_privacy  # noqa: E402
import test_privileged  # noqa: E402
import test_review2  # noqa: E402
import test_review3  # noqa: E402
import test_review3_auth  # noqa: E402
import test_review3_bot  # noqa: E402
import test_restart  # noqa: E402
import test_panel_model  # noqa: E402
import test_patient_card  # noqa: E402
import test_patients_api  # noqa: E402
import test_schedule_api  # noqa: E402
import test_settings_api  # noqa: E402
import test_stats_api  # noqa: E402
import test_structure  # noqa: E402
import test_teeth  # noqa: E402
import test_theme  # noqa: E402
import test_visit  # noqa: E402
import test_visit_api  # noqa: E402
from harness import run  # noqa: E402

SUITES = [
    # Первым: сервера не поднимает, идёт доли секунды, и ломается ровно там,
    # где переезд файла убил бы собранную программу. Ждать этого 60 секунд,
    # пока прогоняются наборы с сервером, незачем.
    ("Раскладка кода: правила карты", test_structure.suite),
    # Сразу за ним: те же правила, но на СЛЕПЫЕ ЗОНЫ — область, форма вызова,
    # список имён без якоря. Мутация о таком промахе сказать не может.
    ("Сторожа: область правила о знаках", test_guards.suite_glyph_scope),
    ("Сторожа: отпечаток auth.json и форма вызова", test_guards.suite_auth_fp),
    ("Сторожа: знаки математики в текстах", test_guards.suite_glyph_math),
    ("Сторожа: якорь списка ролей", test_guards.suite_roles_anchor),
    ("Сторожа: карта экранов видит все маршруты",
     test_guards.suite_screen_map),
    ("Выпуск: версия с «v» в check_release", test_guards.suite_release_arg),
    ("Выпуск: версия одна у движка, клиента и exe", test_guards.suite_version_source),
    ("P4.1: граница прав HKLM", test_privileged.suite_boundary),
    ("P4.1: операция за UAC", test_privileged.suite_op),
    ("P4.1: что уходит в UAC", test_privileged.suite_request),
    ("P4.1: вход лаунчера", test_privileged.suite_argv),
    ("P4.1: приложение не пишет в реестр", test_privileged.suite_no_direct_write),
    ("Чистая логика расписания", test_admin.suite_pure),
    ("Вход и охрана доступа", test_admin.suite_auth),
    ("PIN: хранение и переезд", test_pin.suite_store),
    ("PIN: клиника с прошлой версии", test_pin.suite_migrate),
    ("PIN: защита от подбора", test_pin.suite_throttle),
    ("PIN: смена", test_pin.suite_change),
    ("Роли и права доступа", test_pin.suite_roles),
    ("PIN: битый auth.json", test_pin.suite_broken),
    ("Hardening: установка PIN только локально", test_hardening.suite_setup_local),
    ("Hardening: битый clinic.json не подменяется демо",
     test_hardening.suite_config_fallback),
    ("Hardening: гонка за один слот", test_hardening.suite_booking_race),
    ("Hardening: гонка сохранения моста", test_hardening.suite_punte_race),
    ("Hardening: сессия переживает hot-reload конфига",
     test_hardening.suite_stale_session),
    ("Hardening: стирание пациента атомарно",
     test_hardening.suite_delete_rollback),
    ("Hardening: сессии — TTL и очистка PII", test_hardening.suite_session_pii),
    ("Hardening: CSRF на маршрутах без куки", test_hardening.suite_csrf_origin),
    ("Hardening: auth_fail.json атомарен", test_hardening.suite_authfail_atomic),
    ("Hardening: документы — только своим", test_hardening.suite_doc_ownership),
    ("PIN: атомарная запись auth.json", test_pin.suite_atomic),
    ("Сигнализация auth.json", test_pin.suite_tamper),
    ("Секреты: шифрование токена", test_pin.suite_secret),
    ("Секреты: токен в dental.env", test_pin.suite_env_token),
    ("Окна расписания: обед впритык к краю", test_doctor_windows.suite_fits),
    ("Окна расписания: «Oricare disponibil»", test_doctor_windows.suite_any),
    ("Окна расписания: график врача на сервере",
     test_doctor_windows.suite_routes),
    ("Окна расписания: бросок на занятый час", test_doctor_windows.suite_drop),
    ("Запись из журнала", test_booking.suite),
    ("Запись из фиши пациента", test_booking.suite_card),
    ("Статусы и заметки", test_booking.suite_status),
    ("Перенос визита (drag & drop)", test_booking.suite_move),
    ("Бот записи", test_bot.suite),
    ("Страницы журнала", test_admin.suite_pages),
    ("Панель дня", test_admin.suite_dashboard),
    ("Живой журнал: опрос вместо перезагрузки", test_admin.suite_live_swap),
    ("Пациент без телефона и поиск по дате", test_admin.suite_nophone),
    ("Края дневной сетки", test_admin.suite_grid_edges),
    ("Аналитика", test_admin.suite_analytics),
    ("Аналитика (JSON)", test_stats_api.suite_stats),
    ("Аналитика: React-экран и право", test_stats_api.suite_switch),
    ("Заморозка бота: интерфейс", test_admin.suite_bot_ui),
    ("Карточка пациента", test_admin.suite_patient_card),
    ("Анамнез: опросник", test_anamneza.suite),
    ("Анамнез: закон 195", test_anamneza.suite_195),
    ("Печать на языке пациента", test_anamneza.suite_lang),
    ("Находки ревью 08-08", test_anamneza.suite_review),
    ("Анамнез: бумажный бланк", test_anamneza.suite_form),
    ("Одонтограмма: поверхности", test_teeth.suite_surfaces),
    ("Одонтограмма: молочный прикус", test_teeth.suite_milk),
    ("Одонтограмма: форма зуба", test_teeth.suite_shape),
    ("Одонтограмма: вид сверху", test_teeth.suite_occlusal),
    ("Одонтограмма: детальная страница", test_teeth.suite_odo_page),
    ("Одонтограмма: состояние поверхности", test_teeth.suite_surface_states),
    ("Одонтограмма: память поверхностей", test_teeth.suite_surface_memory),
    ("Одонтограмма: ввод поверхностей", test_teeth.suite_surface_input),
    ("Одонтограмма: отметки поверх находки", test_teeth.suite_marks),
    ("Одонтограмма: мост (punte)", test_teeth.suite_punte),
    ("Пародонтограмма: шесть точек на зуб", test_perio.suite_perio),
    ("Дневник визита", test_visit.suite),
    ("Дневник визита: план и статусы", test_visit.suite_plan),
    ("Дневник визита: закон 195", test_visit.suite_195),
    ("Форма 043/e: печать", test_visit.suite_043),
    ("Отказ пациента: статус и охрана", test_plan_acord.suite_refuz),
    ("Отказ пациента: не считается активным",
     test_plan_acord.suite_refuz_not_active),
    ("Acord informat: печатный лист", test_plan_acord.suite_acord),
    ("Acord informat: кто подписывает", test_plan_acord.suite_acord_medic),
    ("Отказ пациента: 043/e и выгрузка", test_plan_acord.suite_refuz_docs),
    ("Ревью-2: предпросмотр и план", test_review2.suite_peek_plan),
    ("Ревью-2: очистка даты рождения", test_review2.suite_birth_clear),
    ("Ревью-2: Pacient nou без двойника", test_review2.suite_new_dup),
    ("Ревью-2: настройки (confirm и услуги)", test_review2.suite_settings_ui),
    ("API: охрана и конверт", test_api.suite_guard),
    ("API: настройки клиники — данные", test_api.suite_clinic),
    ("React-экран: рубильник и старая форма", test_api.suite_switch),
    ("Продукт: чистая установка открывается на React",
     test_react_default.suite_fresh),
    ("Продукт: аварийный выключатель React", test_react_default.suite_switch_off),
    ("Врачи: старые POST без проверок", test_doctors.suite_legacy),
    ("Врачи: JSON API", test_doctors.suite_api),
    ("Врачи: React-экраны и старые страницы", test_doctors.suite_switch),
    ("Настройки: хаб (JSON)", test_settings_api.suite_hub),
    ("Настройки: сеть (JSON)", test_settings_api.suite_lan),
    ("Настройки: справка (JSON)", test_settings_api.suite_faq),
    ("Настройки: часы (JSON)", test_settings_api.suite_hours),
    ("Настройки: услуги (JSON)", test_settings_api.suite_services),
    ("Настройки: вид клиники (JSON)", test_settings_api.suite_theme),
    ("Настройки: учётки и PIN (JSON)", test_settings_api.suite_security),
    ("Настройки: копия (JSON)", test_settings_api.suite_backup),
    ("Настройки: шифрование картотеки (JSON)", test_settings_api.suite_crypt),
    ("Настройки: состояние системы (JSON)", test_settings_api.suite_system),
    ("Настройки: React-экраны пачки A", test_settings_api.suite_switch),
    ("Пациенты: старая страница и API — одна выдача", test_patients_api.suite_parity),
    ("Пациенты: JSON API списка", test_patients_api.suite_api),
    ("Пациенты: React-экран списка", test_patients_api.suite_switch),
    ("Фиша: старая страница — эталон", test_patient_card.suite_pin),
    ("Фиша: JSON API повторяет страницу", test_patient_card.suite_api),
    ("Фиша: действия через JSON", test_patient_card.suite_actions),
    ("Фиша: React-экран и старая страница", test_patient_card.suite_switch),
    ("Дневник визита: старая страница — эталон", test_visit_api.suite_pin),
    ("Дневник визита: JSON API", test_visit_api.suite_api),
    ("Дневник визита: React-экран и старая страница", test_visit_api.suite_switch),
    ("Одонтограмма: старые страницы — эталон", test_odontogram_api.suite_pin),
    ("Одонтограмма: JSON API", test_odontogram_api.suite_api),
    ("Одонтограмма: React-экран и старая страница", test_odontogram_api.suite_switch),
    ("Живой журнал: React-узел не внутри #live, конверт состояния",
     test_api.suite_live_react),
    ("Живой журнал: тело детерминировано между запросами",
     test_admin.suite_live_stable),
    ("Неделя: пин поведения (C24)", test_admin.suite_week),
    ("Неделя: JSON API и паритет со страницей", test_schedule_api.suite_api),
    ("Неделя: React-экран и живой опрос", test_schedule_api.suite_switch),
    ("Сетка дня: контракт построителя (C25)", test_grid.suite_grid),
    ("Сетка дня: измерение врача", test_grid.suite_doctors),
    ("Сетка дня: легаси-имена без doctor_id", test_grid.suite_orphan),
    ("Сетка дня: паритет модели и страницы", test_schedule_api.suite_day_parity),
    ("Сетка дня: легаси-колонка в паритете", test_schedule_api.suite_day_orphan),
    ("Дневные экраны: флаг и живой опрос", test_schedule_api.suite_day_switch),
    ("День: форма записи — что она предлагает (C25.5b)", test_day_forms.suite_form),
    ("День: диалог «+» и заметки стойки", test_day_forms.suite_slot),
    ("День: карточка визита и её кнопки", test_day_forms.suite_card),
    ("День: диалог переноса и имя в нём", test_day_forms.suite_move),
    ("День: список дня, его кнопки и фильтр (C25.5c)", test_day_forms.suite_list),
    ("Панель: колонка-сирота и relink (C26.2)", test_admin_canvas.suite_orphan),
    ("Панель: геометрия блоков и кластеры", test_admin_canvas.suite_geometry),
    ("Панель: плитка и её собственный фильтр", test_admin_canvas.suite_tiles),
    ("Панель: шапка врача на канве", test_admin_canvas.suite_head),
    ("Панель: мини-календарь месяца", test_admin_canvas.suite_minical),
    ("Панель: повестка дня", test_admin_canvas.suite_agenda),
    ("Панель: тренды и их полярность", test_admin_canvas.suite_trends),
    ("Живой канал данными: конверт (C27.1)",
     test_schedule_api.suite_live_envelope),
    ("Панель: флаг schedule_dash и обе половины отката (C26.5.2)",
     test_schedule_api.suite_dash_flag),
    ("Панель: команды без состояния (C26.5.3-e)",
     test_schedule_api.suite_panel_cmds),
    ("Правая колонка: повестка — правила", test_panel_model.suite_agenda_pure),
    ("Правая колонка: повестка против страницы",
     test_panel_model.suite_agenda_parity),
    ("Правая колонка: плитки и полярность трендов",
     test_panel_model.suite_tiles_pure),
    ("Правая колонка: плитки против страницы",
     test_panel_model.suite_tiles_parity),
    ("Правая колонка: мини-календарь — правила",
     test_panel_model.suite_minical_pure),
    ("Правая колонка: мини-календарь против страницы",
     test_panel_model.suite_minical_parity),
    ("Панель: модель канвы против страницы (C26.4)", test_admin_canvas.suite_model),
    ("Панель: текущий час в модели и на странице", test_admin_canvas.suite_model_now),
    ("Панель: пустой день в модели", test_admin_canvas.suite_model_empty),
    ("Панель: цвет врача — одна формула на все экраны", test_admin_canvas.suite_hue),
    ("День: модель для диалогов (C25.5b)", test_day_actions.suite_model),
    ("День: действия через JSON", test_day_actions.suite_actions),
    ("День: форма и API отвечают одним кодом", test_day_actions.suite_parity),
    ("Пародонтограмма: старая страница — эталон", test_perio_api.suite_pin),
    ("Пародонтограмма: JSON API осмотров", test_perio_api.suite_api),
    ("Пародонтограмма: React-экран и старая страница", test_perio_api.suite_switch),
    ("Пародонтограмма: дата осмотра в зоне клиники", test_perio_api.suite_day),
    ("Пародонтограмма: два рабочих места в одном осмотре",
     test_perio_api.suite_two_seats),
    ("Ревью-3: фирменный цвет и знаки в CSS", test_review3.suite_css),
    ("Ревью-3: часы в подвале сайдбара", test_review3.suite_clock),
    ("Ревью-3: услуги врача и чужой отпуск", test_review3.suite_doc_services),
    ("Ревью-3: границы периода в аналитике", test_review3.suite_stats_period),
    ("Ревью-3: «botul a adus» без неявок", test_review3.suite_stats_bot),
    ("Ревью-3: часы формы по графику врача", test_review3.suite_form_hours),
    ("Ширина: окно странице, потолок строке", test_review3.suite_width),
    ("Ширина: сетки без мёртвых колонок", test_review3.suite_grids),
    ("Ширина: колонка цены в услугах", test_review3.suite_svc_table),
    ("Ревью-3: веб-чат выдаёт ключ сессии сам",
     test_review3_bot.suite_chat_session),
    ("Ревью-3: кнопка из вчерашнего напоминания",
     test_review3_bot.suite_callback_ack),
    ("Ревью-3: перенос визита и напоминание",
     test_review3_bot.suite_move_reminder),
    ("Ревью-3: состояние канала Telegram", test_review3_bot.suite_tg_status),
    ("Ревью-3: смена PIN на чужой", test_review3_auth.suite_pin_dup),
    ("Ревью-3: ID при входе и регистр", test_review3_auth.suite_login_uid_case),
    ("Ревью-3: битый auth.json при ADMIN_KEY",
     test_review3_auth.suite_broken_with_key),
    ("Ревью-3: обновление (таймеры, планировщик, версия)",
     test_review3_auth.suite_update),
    ("Перезапуск: один заказ планировщику", test_restart.suite_once),
    ("Перезапуск: отказ планировщика на экране", test_restart.suite_failed),
    ("Перезапуск: издания без перезапуска", test_restart.suite_dev_banner),
    ("Список пациентов", test_admin.suite_patients_list),
    ("Долги в списке и касса дня", test_admin.suite_money),
    ("Настройки и горячая перезагрузка", test_admin.suite_settings),
    ("Вид клиники: палитра и отказы", test_theme.suite_palette),
    ("Вид клиники: цвет на страницах", test_theme.suite_pages),
    ("Вид клиники: логотип", test_theme.suite_logo),
    ("Доступ из сети (LAN)", test_admin.suite_lan),
    ("Значок приложения (манифест)", test_admin.suite_pwa),
    ("Закон 195: выгрузка данных пациента", test_privacy.suite_export),
    ("Закон 195: полнота выгрузки", test_privacy.suite_export_full),
    ("Закон 195: имена файлов в архиве", test_privacy.suite_export_names),
    ("Закон 195: копия без внутренних кодов", test_privacy.suite_export_words),
    ("Закон 195: потерянный документ в копии",
     test_privacy.suite_export_lost_doc),
    ("Закон 195: право на стирание", test_privacy.suite_erase),
    ("Закон 195: стирание по маркеру", test_privacy.suite_erase_marker),
    ("Закон 195: маркер и полное удаление",
     test_privacy.suite_erase_marker_delete),
    ("Закон 195: журнал доступа", test_privacy.suite_access_log),
    ("Закон 195: формуляр информирования", test_privacy.suite_acord),
    ("Летопись: событие словом, а не кодом", test_activity.suite_words),
    ("Миграции базы: шаг 4 у клиники с версии 3", test_migrate.suite_v4),
    ("Миграции базы: шаг 4 против двойной брони",
     test_migrate.suite_v4_conflict),
    ("Миграции базы: клиника с версии 2 и переименованный врач",
     test_migrate.suite_v2_conflict),
    ("Миграции базы: доверсионная база и лестница отката",
     test_migrate.suite_v0_conflict),
    ("Миграции базы: клиника пришла от 1.20.0", test_migrate.suite_from_1200),
    ("Миграции базы: индексы пропали без метки", test_migrate.suite_selfheal),
    ("Миграции базы: индексы были узкими без метки",
     test_migrate.suite_selfheal_narrow),
    ("Миграции базы: список шага 4 исполняется", test_migrate.suite_step4_list),
    ("Миграции базы: отказ не в данных", test_migrate.suite_slot_guard_no_data),
    ("Миграции базы: отказ раскладки индексов", test_migrate.suite_uq_apply_fails),
    ("Миграции базы: не осталось ни одной проверки",
     test_migrate.suite_uq_all_gone),
    ("Миграции базы: состояние индексов не прочитано",
     test_migrate.suite_uq_state_unreadable),
    ("Миграции базы: без проверок запись всё равно отбивается",
     test_migrate.suite_uq_gone_still_blocks),
    ("Летопись: метка снята там, где разводить было нечего",
     test_migrate.suite_uq_cleared_no_conflict),
    ("Летопись: строки про страховку влезают в колонку",
     test_migrate.suite_uq_event_len),
    ("Миграции базы: кому виден баннер страховки",
     test_migrate.suite_slot_banner_roles),
    ("Миграции базы: «в лечении» стало отметкой", test_migrate.suite_v5_marks),
    ("Летопись: backfill в часах клиники", test_migrate.suite_backfill_tz),
    ("Шифрование базы: код восстановления", test_dbcrypt.suite_key),
    ("Шифрование базы: переезд", test_dbcrypt.suite_convert),
    ("Шифрование базы: программа на шифре", test_dbcrypt.suite_live),
    ("Шифрование базы: отложенный переезд", test_dbcrypt.suite_pending),
    ("Шифрование базы: выключение и копии", test_dbcrypt.suite_off_backups),
    ("Шифрование базы: заказ по галочке", test_dbcrypt.suite_confirm),
    ("Шифрование базы: восстановление по листу", test_dbcrypt.suite_recover),
    ("Бэкап: отказ экспорта и инструкции db.key", test_dbcrypt.suite_export_err),
    ("Лаунчер: dental.env из Блокнота", test_launcher.suite_envfile),
    ("Лаунчер: DENTART_PORT", test_launcher.suite_port),
    ("Лаунчер: автокопия базы", test_launcher.suite_autobackup),
    ("P3-min: происхождение старой установки", test_legacy.suite_origin),
    ("P3-min: где ищем ярлыки (свои и общие)", test_legacy.suite_shortcut_places),
    ("P3-min: программа без картотеки — не старая раскладка",
     test_legacy.suite_program_only),
    ("P3-min: папка назначения кандидатом не бывает",
     test_legacy.suite_destination),
    ("P3-min: источник «откуда запущен процесс»", test_legacy.suite_self_origin),
    ("P3-min: путь, названный человеком", test_legacy.suite_human),
    ("P2 шаг 2: отпечаток без открытия", test_relocate.suite_fingerprint),
    ("P2 шаг 3: решение", test_relocate.suite_decide),
    ("P2 шаг 3: приказы шифрования останавливают", test_relocate.suite_blockers),
    ("P2: из какого корня работать запуску", test_relocate.suite_root_for),
    ("P2 шаги 1-3: ни одного записанного байта", test_relocate.suite_read_only),
    ("P2 шаги 1-3: драйверы не зовутся", test_relocate.suite_no_drivers),
    ("P2 split: подтверждение источника его PIN", test_srcpin.suite_verify),
    ("P2 split: источник побайтно не тронут", test_srcpin.suite_untouched),
    ("P2 split: нечем подтвердить — остановка", test_srcpin.suite_no_auth),
    ("P2 split: счётчик попыток в назначении", test_srcpin.suite_counter),
    ("P2 split: счётчик внутри источника отвергнут", test_srcpin.suite_guard),
    ("P2 шаг 4: migration.json — граница транзакции", test_split.suite_state),
    ("P2 шаг 4: экран раздвоения", test_split.suite_screen),
    ("P2 шаг 4: охрана формы выбора", test_split.suite_guard),
    ("P3-min: резерв остаётся резервом", test_legacy.suite_reserved),
    ("P3-min: намерение установщика", test_legacy.suite_install_info),
    ("P3-min: засев канала", test_legacy.suite_channel_seed),
    ("P3-min: разбор настоящих ярлыков", test_legacy.suite_real_shortcuts),
    ("P3-min: контракт установщика", test_installer.suite_contract),
    ("P3-min: права на папку данных", test_installer.suite_acl),
    ("P3-min: первый запуск и блокировка", test_installer.suite_first_run),
    ("P3-min: комментарии Pascal", test_installer.suite_pascal_comments),
    ("P3-min: установщик компилируется", test_installer.suite_compiles),
    ("Зашифрованный бэкап клиники",test_privacy.suite_backup),
    ("Закон 195: уведомление в боте", test_privacy.suite_bot_notice),
]

if __name__ == "__main__":
    only = sys.argv[1].lower() if len(sys.argv) > 1 else ""
    suites = [(n, f) for n, f in SUITES if not only or only in n.lower()]
    if not suites:
        print(f"Нет наборов по фильтру {only!r}. Доступные:")
        for n, _ in SUITES:
            print(f"  {n}")
        sys.exit(2)
    sys.exit(run(suites))
