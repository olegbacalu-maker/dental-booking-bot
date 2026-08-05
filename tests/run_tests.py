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
import test_booking  # noqa: E402
import test_bot  # noqa: E402
from harness import run  # noqa: E402

SUITES = [
    ("Чистая логика расписания", test_admin.suite_pure),
    ("Вход и охрана доступа", test_admin.suite_auth),
    ("Запись из журнала", test_booking.suite),
    ("Запись из фиши пациента", test_booking.suite_card),
    ("Статусы и заметки", test_booking.suite_status),
    ("Бот записи", test_bot.suite),
    ("Страницы журнала", test_admin.suite_pages),
    ("Карточка пациента", test_admin.suite_patient_card),
    ("Настройки и горячая перезагрузка", test_admin.suite_settings),
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
