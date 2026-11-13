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
import test_archive  # noqa: E402
import test_clinics  # noqa: E402
import test_contlink  # noqa: E402
import test_contract  # noqa: E402
import test_contracts  # noqa: E402
import test_cont_tabs  # noqa: E402
import test_deploy  # noqa: E402
import test_email  # noqa: E402
import test_fleet  # noqa: E402
import test_issue  # noqa: E402
import test_jobs  # noqa: E402
import test_lock  # noqa: E402
import test_maib  # noqa: E402
import test_mail_tx  # noqa: E402
import test_modele  # noqa: E402
import test_payments  # noqa: E402
import test_paylink  # noqa: E402
import test_update  # noqa: E402
import test_pure  # noqa: E402
import test_receipts  # noqa: E402
import test_renew  # noqa: E402
import test_robots  # noqa: E402
import test_revoke  # noqa: E402
import test_routes  # noqa: E402
import test_sms  # noqa: E402
import test_sms_admin  # noqa: E402
import test_sms_cabinet  # noqa: E402
import test_sms_name  # noqa: E402
import test_sms_paper  # noqa: E402
import test_sms_client  # noqa: E402
import test_sms_rule  # noqa: E402
import test_terms  # noqa: E402
import test_tiers  # noqa: E402
import test_trial  # noqa: E402
import test_tx  # noqa: E402
from harness import run  # noqa: E402

SUITES = [
    ("Сервер: без импортов движка, одни версии", test_pure.suite),
    ("Маршруты: тот же набор, что до разноса main.py; один адрес — один маршрут", test_routes.suite_snapshot),
    ("Маршруты: ни один модуль не импортирует main", test_routes.suite_layout),
    ("Маршруты: main.py — только сборка, роутеры подключены и не знают друг друга", test_routes.suite_routers),
    ("Оплата картой: settle только под замком записи (immediate)", test_tx.suite_settle_lock),
    ("Оплата картой: письма об оплате — после commit", test_tx.suite_mail_after_commit),
    ("Оплата картой: сеть maib — вне транзакции", test_tx.suite_net_outside_tx),
    ("Транзакции: та, что пишет, — под замком записи с начала (immediate)", test_tx.suite_write_lock),    ("SMS: сегменты и номер — общий вектор с программой", test_sms_rule.suite_vectors),
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
    ("Замок записи: /v1/license при соседе-писателе ждёт, а не падает «database is locked»",
     test_lock.suite_license),
    ("Замок записи: /v1/sms/* при соседе-писателе ждут; три запроса программы разом — без 500",
     test_lock.suite_program),
    ("Замок записи: формы кабинета и админки при соседе-писателе ждут и сохраняют", test_lock.suite_pages),
    ("Замок записи: сосед закоммитил между чтением и записью — отложенная падает сразу, immediate исключает",
     test_lock.suite_snapshot),
    ("Письма после commit: письмо о сроке — сосед пишет, пока почта думает; отказ почты; смерть процесса",
     test_mail_tx.suite_daily),
    ("Письма после commit: тревоги SMS Олегу и «Au rămas N SMS» — вне транзакции, раз на вид",
     test_mail_tx.suite_sms),
    ("Письма после commit: пробный с формы и из программы, файл письмом из админки — замок свободен, отказ почты",
     test_mail_tx.suite_trial_admin),
    ("Письма после commit: регистрация кабинета, «Adaugă clinică», нота SMS из программы",
     test_mail_tx.suite_cabinet_sms),
    ("Сервер: карта maib — ссылка, четыре callback, проверка, новая ссылка", test_maib.suite_flow),
    ("Сервер: карта maib — ежедневная задача, maib молчит", test_maib.suite_daily),
    ("Сервер: карта maib — ежечасный проход cards: свежие попытки за час, старые — daily", test_maib.suite_hourly),
    ("Сервер: карта maib — второй платёж по закрытой ноте зачитывается", test_maib.suite_duplicate),
    ("Сервер: карта maib — callback и возврат браузера разом: одна оплата, без 500", test_maib.suite_race),
    ("Сервер: карта maib — maib думает, соседи пишут; отказ на ноте — нота остаётся", test_maib.suite_slow),
    ("Сервер: карта maib — сумма или валюта не те: не подтверждено, журнал один раз", test_maib.suite_mismatch),
    ("Сервер: карта maib — без DP_MAIB_* всё как в шаге 1", test_maib.suite_off),
    ("Сервер: tools check — песочница maib при боевом адресе: предупреждение", test_maib.suite_sandbox_live),
    ("Провод maib Checkout: подпись по образцу документации, поля checkout, статусы, токен, 403, возврат", test_maib.suite_wire),
    ("Сервер: форма пробного — правила: ящик, поля, лимиты", test_trial.suite_rules),
    ("IDNO заявки пробного: контрольная 7-3-1, не все одинаковые — три двери", test_revoke.suite_idno),
    ("Отзыв лицензии: файл «сейчас», чтение, SMS, оплата, кабинет, письма", test_revoke.suite_revoke),
    ("Отзыв лицензии: IDNO, ящик и компьютер заняты — нового пробного нет", test_revoke.suite_doors),
    ("Отзыв лицензии: «Вернуть» — прежний срок; срок прошёл — без файла", test_revoke.suite_restore),
    ("Отзыв лицензии: шаг схемы 22 переживает повтор", test_revoke.suite_schema),
    ("Архив клиник: шаг схемы 23; каждая ссылка на клинику названа", test_archive.suite_schema),
    ("Архив клиник: вне списка, флота и писем; файл не отозван; IDNO, ящик и ПК заняты", test_archive.suite_archive),
    ("Архив клиник: удалить навсегда — слово, причина, всё стёрто, IDNO свободен, журнал", test_archive.suite_delete),
    ("Архив клиник: деньги, SMS и подписанное запрещают удаление — по живой базе", test_archive.suite_blockers),
    ("Сервер: лимиты заявки и проверки кода — старые ключи выметаются", test_trial.suite_hits_sweep),
    ("Сервер: форма пробного — auto, один пробный на IDNO/e-mail, спам", test_trial.suite_auto),
    ("Сервер: форма пробного — approve, кнопки, скрыть", test_trial.suite_approve),
    ("Сервер: заявка из программы — токен, выдача, повтор, скрыть, auto", test_trial.suite_program),
    ("Сервер: новый компьютер — код на e-mail клиники, код → токен → файл", test_trial.suite_code),
    ("Сервер: повтор просьбы кода за секунды — тот же verify_id, одно письмо; отказ почты, окно",
     test_trial.suite_code_repeat),
    ("E-mail клиники: письмо о пробном, ссылка, страница с кнопкой (GET не пишет)", test_email.suite_letter),
    ("E-mail клиники: программа — код, «Retrimite», «Schimbă adresa», лимит", test_email.suite_program),
    ("E-mail клиники: ошибки кода и ссылка из письма", test_email.suite_attempts),
    ("E-mail клиники: вход в кабинет и регистрация из кабинета — подтверждение", test_email.suite_login),
    ("E-mail клиники: метка и «Ждёт вас» в админке, смена ящика Олегом", test_email.suite_admin),
    ("E-mail клиники: шаг 17 на базе шага 16", test_email.suite_migration),
    ("E-mail клиники: заголовки /v1/license и текст письма", test_email.suite_parts),
    ("Письма и кабинет: даты для человека — dd.mm.yyyy, не ISO", test_email.suite_dates),
    ("Кабинет: чистые правила — claim'ы токена, реквизиты, куки по видам", test_account.suite_rules),
    ("Кабинет: вход через Google — стенд, state, кука, отказы токена, выход", test_account.suite_login),
    ("Кабинет: вход кодом на e-mail — без Google, лимиты, регистрация, известная клиника", test_account.suite_email_login),
    ("Оплата из программы: ссылка по токену, страница /plata, нота, карта через стенд maib, IDNO, срок", test_paylink.suite_paylink),
    ("Лимиты в памяти: ключи ушедших адресов выметаются, лимит в час прежний", test_paylink.suite_hits_sweep),
    ("Сервер обновлений: /v1/update — каналы, файлы, кэш, GitHub лёг; провод программы", test_update.suite_update),
    ("Кабинет: регистрация, файл, нота, продление, админка, отвязка, вход по ящику", test_account.suite_cabinet),
    ("Кабинет: клиника из админки, повтор по IDNO, approve, скрытые", test_account.suite_link_and_duplicate),
    ("Сайт: /descarca — установщик последнего выпуска, память, API молчит", test_account.suite_download),
    ("Филиалы: чистые правила — код кабинета 7 цифр, хеш, потолок общей ноты", test_branches.suite_rules),
    ("Филиалы: главная кабинета в одну секунду — по порядку заведения, не по id", test_branches.suite_order),
    ("Формы оплаты: срок только из ряда, сумма сервером, ноты SMS — не нота абонемента («0 MDL»)",
     test_branches.suite_forms),
    ("Филиалы: несколько клиник у входа, «Adaugă clinică», форма несёт клинику, чужой IDNO, вход по ящику",
     test_branches.suite_cabinet),
    ("Кабинет по вкладкам: пять вкладок, ключи без id, счётчики, чипы клиник, /cont/documente на вкладке",
     test_cont_tabs.suite_tabs),
    ("Филиалы: код компьютера из кабинета — провод программы, свой кабинет, ошибки, срок, переезд",
     test_branches.suite_code),
    ("Филиалы: общая нота — строки, замена, долг один, свои файлы, один документ, отмена, зачёт",
     test_branches.suite_group),
    ("Филиалы: /plata клиники в общей ноте", test_branches.suite_plata),
    ("Филиалы: имя отправителя SMS общее на кабинет, остаток свой", test_branches.suite_sms_name),
    ("Филиалы: клиника из кабинета — сразу платная, без пробного и без одобрения", test_branches.suite_paid),
    ("Филиалы: админка — клиники кабинета, «Добавить клинику», подсказка флота", test_branches.suite_admin),
    ("Филиалы: шаг 16 на данных шага 15", test_branches.suite_migration),
    ("Кабинет из программы: маршруты /cont разобраны, срок и лимит", test_contlink.suite_rules),
    ("Кабинет из программы: ссылка по токену, одноразовый вход, журнал, лимит, скрытая клиника",
     test_contlink.suite_link),
    ("Кабинет из программы: только своя клиника — филиал не видит главную, общую ноту, «Adaugă»",
     test_contlink.suite_scope),
    ("Флот: чистые правила — заголовки, версии", test_fleet.suite_rules),
    ("Флот: компьютеры из запросов программы, страница, карточка, JSON, кабинет", test_fleet.suite_devices),
    ("Флот: активация из программы и кодом привязывает компьютер", test_fleet.suite_activation),
    ("Флот: компьютер чужой клиники — второго пробного нет, своя клиника — кодом", test_fleet.suite_device_taken),
    ("Флот: код к неоплаченному пробному на компьютере чужой клиники — отказ (/proba + код)", test_fleet.suite_device_kept),
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
    *test_sms_name.SUITES,
    ("SMS-пакет из кабинета: слова ноты — письмо, реквизиты, страница возврата без «срока»; карточка пакетов",
     test_sms_cabinet.suite_words),
    ("SMS-пакет из кабинета: заказ, перевод и карта, одно зачисление, второй платёж, задача, отказы, филиал",
     test_sms_cabinet.suite_cabinet),
    ("SMS-пакет: другой пакет при открытой ноте — замена, письмо, оплата по прежней странице банка зачтена",
     test_sms_cabinet.suite_replace),
    ("SMS-пакет: год имени отправителя из кабинета — нота главной клинике, филиал, кнопка программы, оплата",
     test_sms_cabinet.suite_name),
    ("SMS-пакет: счёт для программы несёт ожидающие ноты SMS; ключи программы 2.9.1 на месте",
     test_sms_cabinet.suite_account_notes),
    ("SMS-пакет: страница оплаты — нота SMS первой и под своим заголовком", test_sms_cabinet.suite_plata),
    ("SMS-пакет: провод программы против этого сервера", test_sms_client.suite_client),
    ("Прод: копия базы, её проверка, учение по восстановлению", test_deploy.suite_backup),
    ("Прод: проверка окружения", test_deploy.suite_check),
    ("Прод: файлы развёртывания согласованы", test_deploy.suite_files),
    ("Договор и сайт: страницы говорят то же, что сервер и письма", test_contract.suite),
    ("Акт акцепта условий: одна версия на троих, провод, compose", test_terms.suite_pure),
    ("Акт акцепта условий: заявка, код, /v1/terms/accept, заголовок, карточка", test_terms.suite_program),
    ("Акт акцепта условий: страница оплаты, кабинет, печатная страница акта", test_terms.suite_pay_and_cabinet),
    ("Акт акцепта условий: галочка перед нотой в кабинете — акт, один на ноту", test_terms.suite_cabinet_act),
    ("Акт акцепта условий: idem хешем (миграция 19), срок журнала", test_terms.suite_idem_and_audit),
    ("Документы в кабинете: версия из имени, письмо, вывоз — без сервера", test_contracts.suite_rules),
    ("Документы в кабинете: три PDF поставщика, экземпляр клиники, чужая клиника, админка, check",
     test_contracts.suite_cabinet),
    ("Документы в кабинете: без DP_CONTRACT / DP_DPA — «ещё не выложен», check предупреждает",
     test_contracts.suite_without),
    ("Документы в кабинете: схема 18 → 20 одним init (шаг 19 функцией, шаг 20), загрузка после",
     test_contracts.suite_migration),
    ("Образцы 195 в кабинете: файлы, версии, основания как в программе, экранирование — без сервера",
     test_modele.suite_rules),
    ("Образцы 195 в кабинете: только под входом, своя клиника и филиал, вкладка, SMS, вход из программы",
     test_modele.suite_cabinet),
    ("Поисковики: noindex на каждом ответе, robots.txt обход не закрывает", test_robots.suite),
    ("Корень облака — кабинет клиники, админка только прямым адресом", test_robots.suite_root),
]

if __name__ == "__main__":
    sys.exit(run(SUITES))
