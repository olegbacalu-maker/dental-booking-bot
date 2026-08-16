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

import test_admin  # noqa: E402
import test_anamneza  # noqa: E402
import test_booking  # noqa: E402
import test_dbcrypt  # noqa: E402
import test_doctor_windows  # noqa: E402
import test_launcher  # noqa: E402
import test_migrate  # noqa: E402
import test_bot  # noqa: E402
import test_pin  # noqa: E402
import test_plan_acord  # noqa: E402
import test_privacy  # noqa: E402
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
    ("Дневник визита", test_visit.suite),
    ("Дневник визита: план и статусы", test_visit.suite_plan),
    ("Дневник визита: закон 195", test_visit.suite_195),
    ("Форма 043/e: печать", test_visit.suite_043),
    ("Отказ пациента: статус и охрана", test_plan_acord.suite_refuz),
    ("Отказ пациента: не считается активным",
     test_plan_acord.suite_refuz_not_active),
    ("Acord informat: печатный лист", test_plan_acord.suite_acord),
    ("Отказ пациента: 043/e и выгрузка", test_plan_acord.suite_refuz_docs),
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
    ("Закон 195: право на стирание", test_privacy.suite_erase),
    ("Закон 195: стирание по маркеру", test_privacy.suite_erase_marker),
    ("Закон 195: маркер и полное удаление",
     test_privacy.suite_erase_marker_delete),
    ("Закон 195: журнал доступа", test_privacy.suite_access_log),
    ("Закон 195: формуляр информирования", test_privacy.suite_acord),
    ("Миграции базы: шаг 4 у клиники с версии 3", test_migrate.suite_v4),
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
