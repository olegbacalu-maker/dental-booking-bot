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

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import test_activity  # noqa: E402
import test_admin  # noqa: E402
import test_anamneza  # noqa: E402
import test_booking  # noqa: E402
import test_dbcrypt  # noqa: E402
import test_doctor_windows  # noqa: E402
import test_guards  # noqa: E402
import test_launcher  # noqa: E402
import test_migrate  # noqa: E402
import test_bot  # noqa: E402
import test_pin  # noqa: E402
import test_plan_acord  # noqa: E402
import test_privacy  # noqa: E402
import test_review2  # noqa: E402
import test_review3  # noqa: E402
import test_review3_auth  # noqa: E402
import test_review3_bot  # noqa: E402
import test_restart  # noqa: E402
import test_structure  # noqa: E402
import test_teeth  # noqa: E402
import test_theme  # noqa: E402
import test_visit  # noqa: E402
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
    ("Выпуск: версия с «v» в check_release", test_guards.suite_release_arg),
    ("Чистая логика расписания", test_admin.suite_pure),
    ("Вход и охрана доступа", test_admin.suite_auth),
    ("PIN: хранение и переезд", test_pin.suite_store),
    ("PIN: клиника с прошлой версии", test_pin.suite_migrate),
    ("PIN: защита от подбора", test_pin.suite_throttle),
    ("PIN: смена", test_pin.suite_change),
    ("Роли и права доступа", test_pin.suite_roles),
    ("PIN: битый auth.json", test_pin.suite_broken),
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
    ("Края дневной сетки", test_admin.suite_grid_edges),
    ("Аналитика", test_admin.suite_analytics),
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
