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

import test_account  # noqa: E402
import test_branches  # noqa: E402
import test_admin  # noqa: E402
import test_clinics  # noqa: E402
import test_contract  # noqa: E402
import test_deploy  # noqa: E402
import test_fleet  # noqa: E402
import test_issue  # noqa: E402
import test_jobs  # noqa: E402
import test_maib  # noqa: E402
import test_payments  # noqa: E402
import test_paylink  # noqa: E402
import test_update  # noqa: E402
import test_pure  # noqa: E402
import test_receipts  # noqa: E402
import test_renew  # noqa: E402
import test_robots  # noqa: E402
import test_sms  # noqa: E402
import test_sms_admin  # noqa: E402
import test_sms_paper  # noqa: E402
import test_sms_client  # noqa: E402
import test_sms_rule  # noqa: E402
import test_tiers  # noqa: E402
import test_trial  # noqa: E402
from harness import run  # noqa: E402

SUITES = [
    ("Сервер: без импортов движка, одни версии", test_pure.suite),
    ("SMS: сегменты и номер — общий вектор с программой", test_sms_rule.suite_vectors),
    ("SMS: копия сервера и копия программы отвечают одинаково", test_sms_rule.suite_twins),
    ("SMS: белый список личного текста — копия сервера против sms_plan программы", test_sms_rule.suite_custom_twins),
    ("Сервер: вход, кука, выход, Origin", test_admin.suite_login),
    ("Сервер: лимит попыток входа", test_admin.suite_lock),
    ("Сервер: клиники", test_clinics.suite),
    ("Сервер: карточка клиники — обзор и вкладки", test_clinics.suite_tabs),
    ("Сервер: разделы меню — вкладки, фильтры, счётчики шапки", test_clinics.suite_menu),
    ("Журнал словами: у каждого кода сервера есть слово и раздел", test_clinics.suite_audit_words),
    ("Сервер: выдача файла — проходит проверку движка", test_issue.suite_issue),
    ("Сервер: письмо с файлом", test_issue.suite_mail),
    ("Сервер: декларация поставщика во вложении", test_issue.suite_declaration),
    ("Сервер: правило продления на неудобных датах", test_payments.suite_rules),
    ("Сервер: платёж переводом — ожидание, подтверждение, отказ", test_payments.suite_flow),
    ("Сервер: якорь продления и зачёт повторного перевода", test_payments.suite_anchor_repeat),
    ("Сервер: cont de plată — генератор PDF без библиотек, деньги, имя, режим шрифта", test_receipts.suite_pdf),
    ("Сервер: cont de plată — снимок при оплате, PDF админки и кабинета, вложение, чужой документ",
     test_receipts.suite_flow),
    ("Варианты Basic / Plus: цена, модуль SMS после оплаты, тексты — без сервера", test_tiers.suite_rules),
    ("Варианты Basic / Plus: выбор на /plata, замена ноты, confirm, sms_basic, вручную, страница возврата",
     test_tiers.suite_flow),
    ("Варианты Basic / Plus: вариант без цены не продаётся", test_tiers.suite_not_sold),
    ("Варианты Basic / Plus: нота за 14 дней — в текущем варианте", test_tiers.suite_jobs),
    ("Варианты Basic / Plus: данные до шага 15 — Plus, цена прежняя", test_tiers.suite_migration),
    ("Карта по клику: письмо — страница оплаты, ссылка maib за галочкой, прежняя попытка узнаётся, ноты SMS",
     test_tiers.suite_card),
    ("Сервер: окна напоминаний — подставная дата на каждую строку", test_jobs.suite_windows),
    ("Сервер: ежедневная задача — письма, повтор, новый период", test_jobs.suite_daily),
    ("Сервер: задача — пробный, без e-mail, без реквизитов, кнопка, журнал", test_jobs.suite_edges),
    ("Сервер: автообновление — renew в файле, /v1/license, клиент программы", test_renew.suite_renew),
    ("Сервер: заявка из программы — её провод против этого сервера", test_renew.suite_request),
    ("Сервер: карта maib — ссылка, четыре callback, проверка, новая ссылка", test_maib.suite_flow),
    ("Сервер: карта maib — ежедневная задача, maib молчит", test_maib.suite_daily),
    ("Сервер: карта maib — второй платёж по закрытой ноте зачитывается", test_maib.suite_duplicate),
    ("Сервер: карта maib — без DP_MAIB_* всё как в шаге 1", test_maib.suite_off),
    ("Провод maib: подпись по образцу документации, поля /pay, pay-info, токен, 403, возврат", test_maib.suite_wire),
    ("Сервер: форма пробного — правила: ящик, поля, лимиты", test_trial.suite_rules),
    ("Сервер: форма пробного — auto, один пробный на IDNO/e-mail, спам", test_trial.suite_auto),
    ("Сервер: форма пробного — approve, кнопки, скрыть", test_trial.suite_approve),
    ("Сервер: заявка из программы — токен, выдача, повтор, скрыть, auto", test_trial.suite_program),
    ("Сервер: новый компьютер — код на e-mail клиники, код → токен → файл", test_trial.suite_code),
    ("Кабинет: чистые правила — claim'ы токена, реквизиты, куки по видам", test_account.suite_rules),
    ("Кабинет: вход через Google — стенд, state, кука, отказы токена, выход", test_account.suite_login),
    ("Кабинет: вход кодом на e-mail — без Google, лимиты, регистрация, известная клиника", test_account.suite_email_login),
    ("Оплата из программы: ссылка по токену, страница /plata, нота, карта через стенд maib, IDNO, срок", test_paylink.suite_paylink),
    ("Сервер обновлений: /v1/update — каналы, файлы, кэш, GitHub лёг; провод программы", test_update.suite_update),
    ("Кабинет: регистрация, файл, нота, продление, админка, отвязка, вход по ящику", test_account.suite_cabinet),
    ("Кабинет: клиника из админки, повтор по IDNO, approve, скрытые", test_account.suite_link_and_duplicate),
    ("Сайт: /descarca — установщик последнего выпуска, память, API молчит", test_account.suite_download),
    ("Филиалы: чистые правила — код кабинета 7 цифр, хеш, потолок общей ноты", test_branches.suite_rules),
    ("Филиалы: главная кабинета в одну секунду — по порядку заведения, не по id", test_branches.suite_order),
    ("Филиалы: несколько клиник у входа, «Adaugă clinică», форма несёт клинику, чужой IDNO, вход по ящику",
     test_branches.suite_cabinet),
    ("Филиалы: код компьютера из кабинета — провод программы, свой кабинет, ошибки, срок, переезд",
     test_branches.suite_code),
    ("Филиалы: общая нота — строки, замена, долг один, свои файлы, один документ, отмена, зачёт",
     test_branches.suite_group),
    ("Филиалы: /plata клиники в общей ноте", test_branches.suite_plata),
    ("Филиалы: имя отправителя SMS общее на кабинет, остаток свой", test_branches.suite_sms_name),
    ("Филиалы: админка — клиники кабинета, «Добавить клинику», подсказка флота", test_branches.suite_admin),
    ("Филиалы: шаг 16 на данных шага 15", test_branches.suite_migration),
    ("Флот: чистые правила — заголовки, версии", test_fleet.suite_rules),
    ("Флот: компьютеры из запросов программы, страница, карточка, JSON, кабинет", test_fleet.suite_devices),
    ("Флот: активация из программы и кодом привязывает компьютер", test_fleet.suite_activation),
    ("SMS-пакет: чистые правила — время Кишинёва, тихие часы, имя, уведомление", test_sms.suite_rules),
    ("SMS-пакет: отправка — план, имя, нота за пакет, повтор без дубля, молчание, отказы, потолок", test_sms.suite_send),
    ("SMS-пакет: уведомление о доставке — секрет, перепроверка, 9 без возврата, 10 с возвратом", test_sms.suite_dlr),
    ("SMS-пакет: секрет уведомлений — мимо журнала доступа", test_sms.suite_dlr_log),
    ("SMS-пакет: ежедневная задача — опрос, имена, остаток, баланс sms.md", test_sms.suite_daily),
    ("SMS-пакет: модуль админки — сводка за период, JSON, карточка, кнопки, имена, Excel, тестовая SMS",
     test_sms_admin.suite_admin),
    ("SMS-пакет: личный текст клиники — карточка, проверки, счёт программы", test_sms_admin.suite_custom),
    ("SMS-пакет: одно имя отправителя — одна клиника, общее DentPilot не дают", test_sms_admin.suite_taken),
    ("SMS-пакет: заявление на имя — бланк sms.md, заполнение, проверки", test_sms_paper.suite_render),
    ("SMS-пакет: кабинет — заявка на имя, заполненное заявление, подписанное в базу, админка",
     test_sms_paper.suite_cabinet),
    ("SMS-пакет: кабинет без пакета — раздела SMS нет", test_sms_paper.suite_not_offered),
    ("SMS-пакет: провод программы против этого сервера", test_sms_client.suite_client),
    ("Прод: копия базы, её проверка, учение по восстановлению", test_deploy.suite_backup),
    ("Прод: проверка окружения", test_deploy.suite_check),
    ("Прод: файлы развёртывания согласованы", test_deploy.suite_files),
    ("Договор и сайт: страницы говорят то же, что сервер и письма", test_contract.suite),
    ("Поисковики: noindex на каждом ответе, robots.txt обход не закрывает", test_robots.suite),
]

if __name__ == "__main__":
    sys.exit(run(SUITES))
