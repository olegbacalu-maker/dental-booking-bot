"""Прогон тестов сервера лицензий.

    cd cloud && python tests/run_tests.py

Каждый набор поднимает СВОЙ сервер на свободном порту со своей базой.
Код выхода 1 при любой неудаче.
"""
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import test_admin  # noqa: E402
import test_clinics  # noqa: E402
import test_contract  # noqa: E402
import test_deploy  # noqa: E402
import test_issue  # noqa: E402
import test_jobs  # noqa: E402
import test_maib  # noqa: E402
import test_payments  # noqa: E402
import test_pure  # noqa: E402
import test_renew  # noqa: E402
import test_trial  # noqa: E402
from harness import run  # noqa: E402

SUITES = [
    ("Сервер: без импортов движка, одни версии", test_pure.suite),
    ("Сервер: вход, кука, выход, Origin", test_admin.suite_login),
    ("Сервер: лимит попыток входа", test_admin.suite_lock),
    ("Сервер: клиники", test_clinics.suite),
    ("Сервер: выдача файла — проходит проверку движка", test_issue.suite_issue),
    ("Сервер: письмо с файлом", test_issue.suite_mail),
    ("Сервер: декларация поставщика во вложении", test_issue.suite_declaration),
    ("Сервер: правило продления на неудобных датах", test_payments.suite_rules),
    ("Сервер: платёж переводом — ожидание, подтверждение, отказ", test_payments.suite_flow),
    ("Сервер: окна напоминаний — подставная дата на каждую строку", test_jobs.suite_windows),
    ("Сервер: ежедневная задача — письма, повтор, новый период", test_jobs.suite_daily),
    ("Сервер: задача — пробный, без e-mail, без реквизитов, кнопка, журнал", test_jobs.suite_edges),
    ("Сервер: автообновление — renew в файле, /v1/license, клиент программы", test_renew.suite_renew),
    ("Сервер: карта maib — ссылка, четыре callback, проверка, новая ссылка", test_maib.suite_flow),
    ("Сервер: карта maib — ежедневная задача, maib молчит", test_maib.suite_daily),
    ("Сервер: карта maib — без DP_MAIB_* всё как в шаге 1", test_maib.suite_off),
    ("Сервер: форма пробного — правила: ящик, поля, лимиты", test_trial.suite_rules),
    ("Сервер: форма пробного — auto, один пробный на IDNO/e-mail, спам", test_trial.suite_auto),
    ("Сервер: форма пробного — approve, кнопки, скрыть", test_trial.suite_approve),
    ("Прод: копия базы, её проверка, учение по восстановлению", test_deploy.suite_backup),
    ("Прод: проверка окружения", test_deploy.suite_check),
    ("Прод: файлы развёртывания согласованы", test_deploy.suite_files),
    ("Договор и сайт: страницы говорят то же, что сервер и письма", test_contract.suite),
]

if __name__ == "__main__":
    sys.exit(run(SUITES))
