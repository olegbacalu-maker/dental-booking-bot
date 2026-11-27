"""Мутационные пары облака: каждая ломает одно свойство и требует, чтобы его набор покраснел.

    cd cloud && python tests/mutate.py            (на ПК Олега — TEMP на D:, как у прогона)

Это НЕ набор проверок, а инструмент рядом с ними — как `tests/mutate.py` движка; в `run_tests.py`
он не входит: проверяет он не сервер, а тесты. В CI — шаг «Мутация сторожей облака» работы `cloud`.

Зачем. Проверка поведения бывает зелёной и на сломанном коде — засев не дошёл до ветки, условие
слишком широкое, проверяется не то поле (`303` у формы на оба исхода). Отличить «держит» от «молчит»
можно одним способом: сломать свойство и увидеть красной ИМЕННО ту проверку, что его держит
(`mark` — кусок её названия; красная соседняя не в счёт: её мог уронить сам слом).

Настоящее дерево не трогается: `cloud/` (без `.venv`) и то, что наборы читают из соседей
(`bot/`, `tests/fixtures/`, `docs/site/`, `docs/dentpilot-2/`), копируются во временную папку; слом пишется в КОПИЮ,
наборы идут из неё (`harness.ROOT` — родитель `cloud/` копии), после каждой пары файл копии
возвращается байт в байт. Сервер наборы поднимают тем же интерпретатором, что запустил скрипт.

Пары кабинета SMS (05.11) жили вне репозитория (`sandbox\\sms-cabinet\\mutate_cabinet.py`) и
гонялись руками; перенесены 07.11 вместе с парами акта акцепта кабинета (`web.cont_terms`).
⚠️ Место слома ищется ТОЧНЫМ текстом и обязано встретиться ровно один раз: правка, которая
сдвинула текст, краснеет здесь «место не найдено» — поправить строку пары, не удалять её.
"""
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TESTS = pathlib.Path(__file__).resolve().parent
CLOUD = TESTS.parent
ROOT = CLOUD.parent
# что наборы читают за пределами cloud/ (harness.FIX, load_by_path движка, страницы сайта, файлы развёртывания)
NEIGHBOURS = ("bot", "tests/fixtures", "docs/site", "docs/dentpilot-2", ".gitignore")
SKIP = shutil.ignore_patterns(".venv", "__pycache__", "*.pyc", ".pytest_cache")

# (что ломается, файл в cloud/, было, стало, наборы, кусок названия проверки, которая обязана покраснеть)
MUTATIONS = [
    # --- документы волны 2а: ответ пациента по ссылке, подарки Premium (test_contract) ---
    ("волна 2а: договор без кл. 5.9 об ответе по ссылке",
     "../docs/dentpilot-2/contract/contract.html",
     "<b class=\"n\">5.9.</b> <b>Răspunsul pacientului prin link.</b>", "<b class=\"n\">5.9.</b> <b>Răspuns.</b>",
     ["test_contract.suite"], "волна 2а: § 19 — Răspunsul pacientului prin link"),
    ("волна 2а: лист на стойке не называет ссылку",
     "../bot/app/modules/patients/acord.py",
     "\"conține un link de răspuns, răspunsul dat pe pagina \"", "\"conține un link, răspunsul dat pe pagina \"",
     ["test_contract.suite"], "волна 2а: § 19 — Răspunsul pacientului prin link"),
    ("волна 2а: образец информирования без галочки ссылки",
     "app/assets/modele/informare-pacienti.html",
     "<input type=\"checkbox\" id=\"link-toggle\">", "<input type=\"checkbox\" id=\"link-toggle-x\">",
     ["test_contract.suite"], "волна 2а: § 19 — Răspunsul pacientului prin link"),
    ("волна 2а: условия § 19 — другой срок стирания",
     "../docs/site/termeni.html",
     "șterg de pe server la 3 zile după începutul vizitei.</li>",
     "șterg de pe server la 30 zile după începutul vizitei.</li>",
     ["test_contract.suite"], "срок стирания кода и ответа"),
    ("волна 2а: политика RU — другой срок стирания",
     "../docs/site/privacy.html",
     "Код и ответ удаляются с сервера через 3", "Код и ответ удаляются с сервера через 5",
     ["test_contract.suite"], "срок стирания кода и ответа"),
    ("волна 2а: декларация связывает код с номером",
     "../docs/site/declaratie-195.html",
     "pacientului, medicul sau serviciul, iar codul nu este legat pe server de",
     "pacientului, medicul sau serviciul, iar codul este legat pe server de",
     ["test_contract.suite"], "сервер не получает имя, врача, услугу"),
    ("волна 2а: политика обещает, что сервер не знает времени приёма",
     "../docs/site/privacy.html",
     "    Momentul de valabilitate este începutul vizitei; în rest serverul nu",
     "    Serverul nu primește ora programării. Momentul de valabilitate este începutul vizitei; în rest serverul nu",
     ["test_contract.suite"], "«не получает время визита» не сказано нигде"),
    ("волна 2а: Anexa 2 — программа отменяет сама",
     "../docs/dentpilot-2/contract/anexa-2.html",
     "anulează și nu mută singur nicio programare</td>", "anulează singur programarea</td>",
     ["test_contract.suite"], "ответ — отметка, не отмена"),
    ("волна 2а: условия § 19 — функция включена сразу",
     "../docs/site/termeni.html",
     "Funcția este oprită până o pornește clinica.", "Funcția este pornită.",
     ["test_contract.suite"], "только Premium, выключено до галочки"),
    ("волна 2а: условия § 19 — ответ открытием страницы",
     "../docs/site/termeni.html",
     "se înregistrează numai la apăsarea unui buton, nu la deschiderea paginii",
     "se înregistrează la deschiderea paginii",
     ["test_contract.suite"], "ответ — только нажатием"),
    ("волна 2а: условия § 16 снова обещают один сегмент",
     "../docs/site/termeni.html",
     "caractere chirilice. Câte segmente are fiecare variantă de text",
     "caractere chirilice; memento-urile sunt alcătuite să încapă într-un segment. Câte segmente are fiecare variantă de text",
     ["test_contract.suite"], "2 сегмента"),
    ("волна 2а: DPA без Contabo как субобработчика данных ссылки",
     "../docs/dentpilot-2/contract/dpa.html",
     "3.2), <b>Contabo GmbH</b> (Germania), care găzduiește", "3.2), Contabo (Germania), care găzduiește",
     ["test_contract.suite"], "субобработчик по данным ссылки"),
    ("волна 2а: DPA — снова два случая обработки",
     "../docs/dentpilot-2/contract/dpa.html",
     "Acestea sunt trei și numai trei:", "Acestea sunt două și numai două:",
     ["test_contract.suite"], "«trei și numai trei»"),
    ("волна 2а: декларация — два исключения",
     "../docs/site/declaratie-195.html",
     "de operator. Excepțiile sunt trei, toate", "de operator. Excepțiile sunt două, toate",
     ["test_contract.suite"], "декларация — три исключения"),
    ("волна 2а: политика ссылается на § 19 условий",
     "../docs/site/privacy.html",
     "  <h2 id=\"pacienti\">7. Pentru pacienți", "  <p>(secțiunea 19)</p>\n  <h2 id=\"pacienti\">7. Pentru pacienți",
     ["test_contract.suite"], "политика не ссылается на § 19"),
    ("волна 2а: формула Premium на сервере без ответа по ссылке",
     "app/tiers.py",
     "PREMIUM: \"cu modulul SMS, calendarele medicilor în Google și răspunsul pacientului prin link\"}",
     "PREMIUM: \"cu modulul SMS și calendarele medicilor în Google\"}",
     ["test_contract.suite"], "формула Premium — tiers.WHAT"),
    ("волна 2а: условия § 16 — другой подарок Premium",
     "../docs/site/termeni.html",
     "clinica primește, o singură dată, 80 de SMS gratuit", "clinica primește, o singură dată, 50 de SMS gratuit",
     ["test_contract.suite"], "SMS один раз при первой оплате Premium"),
    ("волна 2а: условия § 16 — имя бесплатно и при помесячном Premium",
     "../docs/site/termeni.html",
     "la DentPilot™ Premium plătit pe o lună anul numelui se plătește,",
     "la DentPilot™ Premium plătit pe o lună anul numelui nu se plătește,",
     ["test_contract.suite"], "своё имя — без оплаты года"),
    ("волна 2а: условия § 4.1 — подарок имени без лимита знаков",
     "../docs/site/termeni.html",
     "numele propriu al expeditorului (până la 11\n    caractere) nu se plătește separat",
     "numele propriu al expeditorului nu se plătește separat",
     ["test_contract.suite"], "своё имя — без оплаты года"),
    # --- кабинет SMS (05.11) ---
    ("одно зачисление при callback + /pay/ok: settle забыл, что попытка уже зачтена",
     "app/payments.py",
     "    counted = bool(att[\"counted\"]) if att is not None else payment[\"paid_via\"] == CARD\n",
     "    counted = False\n",
     ["test_sms_cabinet.suite_cabinet"], "зачисление ОДНО"),
    ("замена ноты шлёт письмо (кабинет): письмо только у новой, не у заменённой",
     "app/routes_cont.py",
     "            if outcome != payments.EXISTS:\n                # новая нота — письмом и при карте",
     "            if outcome == payments.CREATED:\n                # новая нота — письмом и при карте",
     ["test_sms_cabinet.suite_replace"], "письмо с новой нотой ушло"),
    ("замена ноты шлёт письмо (программа): created только у новой",
     "app/routes_program.py",
     "            created = outcome != payments.EXISTS\n",
     "            created = outcome == payments.CREATED\n",
     ["test_sms_cabinet.suite_replace", "test_sms.suite_send"], "нота заменена"),
    ("нота SMS первой на /plata: карточка абонемента снова сверху",
     "app/views.py",
     "sms_notes_block(list(sms_notes), action, card_on) + card, msg=msg,",
     "card + sms_notes_block(list(sms_notes), action, card_on), msg=msg,",
     ["test_sms_cabinet.suite_plata"], "нота SMS — первой"),
    # --- гид имени SMS в кабинете (sms_guide.py) ---
    ("цена в гиде — числом в коде, а не из прайса сервера",
     "app/routes_cont.py",
     "    return HTMLResponse(sms_guide.page(acc, config.SMS_NAME_PRICE, ",
     "    return HTMLResponse(sms_guide.page(acc, 77, ",
     ["test_sms_guide.suite_page"], "другой прайс сервера"),
    ("гид открыт клинике, которой раздел SMS не показан",
     "app/routes_cont.py",
     "        if not sms.offered(sa):\n            return RedirectResponse(\"/cont\", status_code=303)\n        multi = ",
     "        multi = ",
     ["test_sms_guide.suite_page"], "клинике без раздела SMS гид не показан"),
    ("гид называет кнопку своими словами, а не словами карточки",
     "app/sms_guide.py",
     "apăsați {_q(views.NAME_UPLOAD)}.",
     "apăsați «Încarcă cererea».",
     ["test_sms_guide.suite_words"], "слова гида в «ёлочках»"),
    ("в виде филиала ссылки на гид нет",
     "app/views.py",
     "        return (f\"<div class='card'>{_chead('message', NAME_CARD, sub, guide)}\"\n",
     "        return (f\"<div class='card'>{_chead('message', NAME_CARD, sub)}\"\n",
     ["test_sms_guide.suite_page"], "вид филиала: ссылка на гид"),
    ("кадр гида отдаётся без входа",
     "app/routes_cont.py",
     "        if _current_account(con, request) is None:\n            return _cont_login_redirect()\n    data = sms_guide.frame(key)",
     "        pass\n    data = sms_guide.frame(key)",
     ["test_sms_guide.suite_frames"], "без входа кадр не отдаётся"),
    ("кадр гида — файлом по имени из адреса, мимо словаря",
     "app/sms_guide.py",
     "    f = FRAMES.get(key)\n    if f is None:\n        return None\n",
     "    f = FRAMES.get(key) or (key,)\n",
     ["test_sms_guide.suite_frames"], "только по ключу словаря"),
    # --- акт акцепта при оплате из кабинета (07.11, web.cont_terms) ---
    ("кабинет снова не пишет акт: только terms_at",
     "app/web.py",
     "        terms_mod.record(con, cid, terms_mod.CURRENT,",
     "        (lambda *a, **k: None)(con, cid, terms_mod.CURRENT,",
     ["test_terms.suite_cabinet_act"], "акт source=pay"),
    ("акт на каждую галочку, а не один на ноту",
     "app/web.py",
     "    if not (payments.mark_terms(con, note) or fresh):\n",
     "    if not (payments.mark_terms(con, note) or True):\n",
     ["test_terms.suite_cabinet_act"], "второго акта нет"),
    ("нота админки без отметки: новизну галочки потеряли — акта нет",
     "app/routes_cont.py",
     "outcome != payments.EXISTS or not prior[\"terms_at\"]",
     "outcome != payments.EXISTS",
     ["test_terms.suite_cabinet_act"], "галочка к ноте админки"),
    ("общая нота: акт только плательщику, не каждой клинике строк",
     "app/web.py",
     "if note[\"kind\"] == payments.CABINET\n",
     "if False\n",
     ["test_terms.suite_cabinet_act"], "по акту на каждую клинику строк"),
    # --- корень облака и повтор просьбы кода (09.11, первая посторонняя клиника) ---
    ("корень снова ведёт во вход админки",
     "app/routes_cont.py",
     "(test_robots.suite_root).\"\"\"\n    return RedirectResponse(\"/cont\", status_code=303)\n",
     "(test_robots.suite_root).\"\"\"\n    return RedirectResponse(\"/admin\", status_code=303)\n",
     ["test_robots.suite_root"], "корень → кабинет клиники"),
    ("страница входа кабинета ссылается на админку",
     "app/views.py",
     "<p class='fine'>Datele pacienților nu ajung aici niciodată: ele rămân pe calculatorul clinicii.</p></div>\")",
     "<p class='fine'>Datele pacienților nu ajung aici niciodată: ele rămân pe calculatorul clinicii.</p>"
     "<a href='/admin'>Admin</a></div>\")",
     ["test_robots.suite_root"], "/cont/login: 200 и ни одной ссылки на админку"),
    ("повтор той же просьбы кода снова шлёт новый код",
     "app/trial.py",
     "    if again is not None and clinic[\"email\"]:\n",
     "    if False:\n",
     ["test_trial.suite_code_repeat"], "с ОДНИМ verify_id"),
    ("повтор узнаётся у любого просителя: код программы достаётся кабинету",
     "app/trial.py",
     "    by = asker(who, ip)\n",
     "    by = asker(\"program\", \"\")\n",
     ["test_trial.suite_code_repeat"], "другой проситель (кабинет) и другой адрес"),
    ("повтор шлёт Олегу второе письмо о том же повторе",
     "app/routes_program.py",
     "        # ни письма клинике, ни второго письма Олегу о том же повторе\n        return outcome, token, vid, act\n",
     "        # ни письма клинике, ни второго письма Олегу о том же повторе\n        pass\n",
     ["test_trial.suite_code_repeat"], "Олегу — одно письмо о повторе"),
    ("неотправленный код остаётся живым: повтор отдаёт verify_id кода, которого никто не получил",
     "app/routes_program.py",
     "            log.error(\"код активации клинике %s не отправлен: %r\", clinic[\"id\"], e)\n"
     "            trial.unsent(vid)\n",
     "            log.error(\"код активации клинике %s не отправлен: %r\", clinic[\"id\"], e)\n",
     ["test_trial.suite_code_repeat"], "повтор после отказа почты"),
    # --- отзыв лицензии и IDNO заявки пробного (11.11, revoke.py, trial.idno_ok) ---
    ("файл отзыва со сроком «ровно сейчас»: программа отвергла бы его как битый и жила бы дальше",
     "app/revoke.py", "REVOKE_SECONDS = 2  ", "REVOKE_SECONDS = 0  ",
     ["test_revoke.suite_revoke"], "программа забирает файл № 2"),
    ("оплата по старой ноте продлевает отозванную",
     "app/payments.py", "    if revoke.is_revoked(clinic):\n        # ⛔ лицензия отозвана",
     "    if False:\n        # ⛔ лицензия отозвана",
     ["test_revoke.suite_revoke"], "срок не продлён, файла нет"),
    ("ежедневная задача шлёт отозванной письмо о сроке",
     "app/jobs.py", "s.cancelled_at IS NULL AND c.revoked_at IS NULL", "s.cancelled_at IS NULL",
     ["test_revoke.suite_revoke"], "ежедневная задача"),
    ("старая страница оплаты живёт при отзыве",
     "app/paylink.py", "declined_at IS NULL AND revoked_at IS NULL", "declined_at IS NULL",
     ["test_revoke.suite_revoke"], "старая страница оплаты"),
    ("«Plătește acum» программы выдаёт ссылку отозванной",
     "app/routes_program.py", "        if revoke.is_revoked(c):\n            # лицензия отозвана (revoke.py): ссылки оплаты нет",
     "        if False:\n            # лицензия отозвана (revoke.py): ссылки оплаты нет",
     ["test_revoke.suite_revoke"], "«Plătește acum» программы"),
    ("SMS отозванной уходят",
     "app/sms.py", "    if revoke.is_revoked(con.execute(", "    if False and revoke.is_revoked(con.execute(",
     ["test_revoke.suite_revoke"], "SMS: сразу sms_off"),
    ("«Выдать вручную» снимает отзыв молча",
     "app/routes_admin.py", "        if revoke.is_revoked(c):\n            # поверх отзыва — только «Вернуть»",
     "        if False:\n            # поверх отзыва — только «Вернуть»",
     ["test_revoke.suite_revoke"], "«Выдать вручную» поверх отзыва"),
    ("нота абонемента в кабинете отозванной",
     "app/routes_cont.py", "        if revoke.is_revoked(cl):\n            return RedirectResponse(_cont_to(con, acc, cl[\"id\"], \"revoked\")",
     "        if False:\n            return RedirectResponse(_cont_to(con, acc, cl[\"id\"], \"revoked\")",
     ["test_revoke.suite_revoke"], "кабинет: нота абонемента"),
    ("«Adaugă clinică» в кабинете отозванной",
     "app/routes_cont.py", "    if revoke.in_cabinet(con, cl[\"id\"]):", "    if False:",
     ["test_revoke.suite_revoke"], "«Adaugă clinică» — 409"),
    ("«Вернуть» выдаёт новый срок вместо прежнего",
     "app/revoke.py", "license.issue(con, clinic, plan, max(valid, soon), grace,", "license.issue(con, clinic, plan, soon, grace,",
     ["test_revoke.suite_restore"], "файл № 3 с прежним сроком"),
    ("IDNO из одинаковых цифр проходит (у нулей контрольная сходится)",
     "app/trial.py", "    if not IDNO_RE.match(idno) or len(set(idno)) == 1:", "    if not IDNO_RE.match(idno):",
     ["test_revoke.suite_idno"], "программа: 0000000000000"),
    ("контрольная цифра IDNO не считается",
     "app/trial.py", "    return sum(int(d) * w for d, w in zip(idno[:12], _IDNO_WEIGHTS)) % 10 == int(idno[12])",
     "    return True", ["test_revoke.suite_idno"], "кабинет: IDNO с чужой контрольной"),
    # --- архив клиник и удаление из архива (11.11, archive.py) ---
    ("удаление не держит «ноты и платежи»",
     "app/archive.py", "    (\"payments\", \"ноты и платежи\", \"clinic_id=?\"),\n", "",
     ["test_archive.suite_blockers"], "payments: "),
    ("удаление не держит «строки общей ноты»",
     "app/archive.py", "    (\"payment_lines\", \"строки общей ноты\", \"clinic_id=?\"),\n", "",
     ["test_archive.suite_blockers"], "payment_lines: "),
    ("удаление не держит «cont de plată»",
     "app/archive.py", "    (\"receipts\", \"cont de plată\", \"clinic_id=?\"),\n", "",
     ["test_archive.suite_blockers"], "receipts: "),
    ("удаление не держит «попытки оплаты картой»",
     "app/archive.py", "\"payment_id IN (SELECT id FROM payments WHERE clinic_id=?1 UNION",
     "\"0 AND payment_id IN (SELECT id FROM payments WHERE clinic_id=?1 UNION",
     ["test_archive.suite_blockers"], "pay_attempts: "),
    ("удаление не держит «отправленные SMS»",
     "app/archive.py", "    (\"sms_messages\", \"отправленные SMS\", \"clinic_id=?\"),\n", "",
     ["test_archive.suite_blockers"], "sms_messages: "),
    ("удаление не держит «списания и пакеты SMS»",
     "app/archive.py", "\"clinic_id=? AND (reason IN ('send', 'pack', 'refund')",
     "\"0 AND clinic_id=? AND (reason IN ('send', 'pack', 'refund')",
     ["test_archive.suite_blockers"], "sms_ledger: "),
    ("удаление не держит «подписанные клиникой документы»",
     "app/archive.py", "    (\"clinic_contracts\", \"подписанные клиникой документы\", \"clinic_id=?\"),\n", "",
     ["test_archive.suite_blockers"], "clinic_contracts: "),
    ("удаление не держит «подписанные заявления на имя SMS»",
     "app/archive.py", "    (\"sms_papers\", \"подписанные заявления на имя SMS\", \"clinic_id=?\"),\n", "",
     ["test_archive.suite_blockers"], "sms_papers: "),
    ("удаление не из архива",
     "app/archive.py", "    if not is_archived(clinic):\n        return NOT_ARCHIVED\n    reason = _clean(reason)\n    if not reason:",
     "    reason = _clean(reason)\n    if not reason:",
     ["test_archive.suite_delete"], "не в архиве — удалить нельзя"),
    ("удаление без слова УДАЛИТЬ",
     "app/archive.py", "    if (word or \"\").strip().upper() != CONFIRM_WORD:\n        return NEED_WORD",
     "    if False:\n        return NEED_WORD",
     ["test_archive.suite_delete"], "без слова УДАЛИТЬ"),
    ("удаление без причины",
     "app/archive.py", "    if not reason:\n        return NEED_REASON", "    if False:\n        return NEED_REASON",
     ["test_archive.suite_delete"], "без причины"),
    ("архивная остаётся в списке",
     "app/routes_admin.py", "\"WHERE c.archived_at IS NULL ORDER BY c.created_at DESC\"", "\"ORDER BY c.created_at DESC\"",
     ["test_archive.suite_archive"], "список: архивной нет"),
    ("ежедневная задача пишет архивной",
     "app/jobs.py", " AND c.archived_at IS NULL", "",
     ["test_archive.suite_archive"], "ежедневная задача: архивной"),
    ("флот считает компьютеры архивной",
     "app/fleet.py", "           WHERE c.archived_at IS NULL\n", "",
     ["test_archive.suite_archive"], "флот: компьютеров архивной"),
    ("окно архива молчит о действующем файле",
     "app/routes_admin.py", "        lives = {r[\"id\"]: archive.live_until(con, r) for r in rows}",
     "        lives = {}",
     ["test_archive.suite_archive"], "строка списка: «В архив»"),
    # --- предел тела в Caddy у маршрутов загрузки файла ---
    ("предел загрузки в десятичных мегабайтах: ниже того, что дочитывает приложение",
     "deploy/Caddyfile", "\t\t\tmax_size 32MiB\n", "\t\t\tmax_size 32MB\n",
     ["test_deploy.suite_files"], "не ниже того, что дочитывает приложение"),
    ("маршрут загрузки выпал из своего предела и режется общим",
     "deploy/Caddyfile", "\t@upload path /cont/sms/cerere /cont/documente/incarca\n",
     "\t@upload path /cont/sms/cerere\n",
     ["test_deploy.suite_files"], "ровно у маршрутов загрузки файла"),
    # --- право gcal в файле лицензии (features) ---
    ("право gcal у Basic — до конца файла, а не до конца модуля SMS",
     "app/tiers.py", "    return _right(current(sub) in GCAL_TIERS, sms_until(sub), end, now)\n",
     "    return _right(True, sms_until(sub), end, now)\n",
     ["test_tiers.suite_rules"], "право gcal: пробный и Plus"),
    ("выдача ставит право без варианта",
     "app/license.py", "    for name, until in ((\"gcal\", tiers.gcal_until(sub, grace_until, now)),\n",
     "    for name, until in ((\"gcal\", grace_until),\n",
     ["test_tiers.suite_gcal"], "нота Basic без подписки"),
    ("оплата пишет вариант после выдачи: файл с правом прежнего варианта",
     "app/payments.py", "f\"платёж {payment['reference']}\", who,\n"
     "                           tier=tier, sms_until=sms_until, gdoc_until=gdoc_until)",
     "f\"платёж {payment['reference']}\", who)",
     ["test_tiers.suite_gcal"], "пробный → Basic: право до конца пробного"),
    ("«Вариант вручную» снова без файла",
     "app/payments.py", "    seq = reissue(con, clinic, \"вариант вручную\", who)\n", "    seq = 0\n",
     ["test_tiers.suite_gcal"], "«Вариант вручную» Basic: новый файл"),
    ("перевыдача теряет основание срока на оплату первой ноты",
     "app/payments.py", "    reason = ADVANCE if last[\"reason\"] == ADVANCE else why\n", "    reason = why\n",
     ["test_tiers.suite_gcal"], "перевыдача у клиники со сроком на оплату"),
    ("перевыдача поверх отзыва",
     "app/payments.py", "    if revoke.is_revoked(clinic):\n        return 0\n", "",
     ["test_revoke.suite_tier"], "«Вариант вручную» при отзыве"),
    ("команда перевыдачи берёт файл с прошедшей льготой",
     "app/tools.py", "        if last is None or db.parse_ts(last[\"grace_until\"]) <= soon:\n",
     "        if last is None:\n",
     ["test_tiers.suite_gcal"], "reissue без --apply"),
    ("«Adaugă clinică» выдаёт файл без варианта: Basic получает право gcal на срок оплаты",
     "app/account.py", "                      payments.ADVANCE, who, tier=tier)\n",
     "                      payments.ADVANCE, who)\n",
     ["test_branches.suite_paid"], "Basic с первого дня: в файле на срок оплаты"),
    ("проверка программы теряет право из claim",
     "../bot/app/core/rsa_verify.py", "dates[0], dates[1], dates[2], renew, _features(c.get(\"features\")))",
     "dates[0], dates[1], dates[2], renew)",
     ["test_tiers.suite_gcal"], "проверка программы принимает файл с правом"),
    # --- третий вариант Premium: множества tiers, право gcal_doctor, три пути перехода ---
    # Без права программа убирает из календаря врача все приёмы, и прошлые: письмо и кабинет снова обещают,
    # что прошлое осталось.
    ("письмо ушедшей с Premium: из календарей уходят снова только будущие приёмы",
     "app/mail.py", 'f"scoate din ele toate programările, și pe cele trecute." if',
     'f"scoate din ele programările viitoare." if',
     ["test_tiers.suite_premium_rules"], "письмо о лицензии ушедшей с Premium"),
    ("кабинет Premium: из календарей уходят снова только будущие приёмы",
     "app/views.py", 'apoi programul scoate din "\n                    f"ele toate programările, și pe cele trecute; {back}")',
     'apoi programările viitoare se scot din "\n                    f"ele; {back}")',
     ["test_tiers.suite_premium_rules"], "«что будет при выборе» у Premium"),
    ("кабинет Premium после конца периода: из календарей уходят снова только будущие приёмы",
     "app/views.py", 'iar programul scoate "\n                    f"din ele toate programările, și pe cele trecute; {back}")',
     'iar programările viitoare se "\n                    f"scot din ele; {back}")',
     ["test_tiers.suite_premium_rules"], "у Premium после конца периода"),
    ("модуль SMS у Premium гаснет: module_on снова «только Plus»",
     "app/tiers.py", "    if current(sub) in SMS_TIERS:\n        return True\n",
     "    if current(sub) == PLUS:\n        return True\n",
     ["test_tiers.suite_premium_rules"], "модуль SMS у Premium работает"),
    ("связь с Google у Premium гаснет: gcal_until снова «только Plus»",
     "app/tiers.py", "    return _right(current(sub) in GCAL_TIERS, sms_until(sub), end, now)\n",
     "    return _right(current(sub) == PLUS, sms_until(sub), end, now)\n",
     ["test_tiers.suite_premium_rules"], "право gcal у Premium"),
    ("календари врачей и у Plus",
     "app/tiers.py", "GDOC_TIERS = frozenset({PREMIUM})", "GDOC_TIERS = frozenset({PLUS, PREMIUM})",
     ["test_tiers.suite_premium_rules"], "право gcal_doctor: Premium"),
    ("выдача кладёт только gcal: у Premium нет права календарей врачей",
     "app/license.py", "(\"gcal_doctor\", tiers.gdoc_until(sub, grace_until, now))", "(\"gcal_doctor\", None)",
     ["test_tiers.suite_premium_rules"], "права файла Premium"),
    ("оплата Premium снова считается уходом с SMS (двоичный tier_after)",
     "app/payments.py", "    sms_had, sms_has = before in tiers.SMS_TIERS, tier in tiers.SMS_TIERS\n",
     "    sms_had, sms_has = before in tiers.SMS_TIERS, tier in {tiers.PLUS}\n",
     ["test_tiers.suite_premium_rules"], "Basic → Premium"),
    ("Premium → Plus гасит календари сразу, а не с конца периода",
     "app/payments.py", "    gdoc_until = _left(doc_had, doc_has, kept[\"gdoc_until\"], sub, now)\n",
     "    gdoc_until = None\n",
     ["test_tiers.suite_premium_rules"], "Premium → Plus: модуль SMS работает"),
    ("оплата не везёт остаток календарей в выдачу",
     "app/payments.py", "                           tier=tier, sms_until=sms_until, gdoc_until=gdoc_until)",
     "                           tier=tier, sms_until=sms_until)",
     ["test_tiers.suite_premium"], "Premium → Plus оплатой"),
    ("«Вариант вручную» не снимает остаток календарей",
     "app/payments.py", "sms_until=NULL, gdoc_until=NULL, updated_at=?", "sms_until=NULL, updated_at=?",
     ["test_tiers.suite_premium"], "остаток календарей снят"),
    ("«Вариант вручную» снова отказывает варианту без прайса: канарейке Premium не выдать",
     "app/payments.py", "    p = tiers.price(sub, tier)\n    if license.key() is None:\n",
     "    p = tiers.price(sub, tier)\n    if p <= 0:\n        return \"tier_bad\"\n    if license.key() is None:\n",
     ["test_tiers.suite_premium"], "вручную Premium без прайса"),
    ("Premium без прайса продаётся",
     "app/config.py", "\"premium\": _lei(env(\"DP_PRICE_PREMIUM\"))", "\"premium\": _lei(env(\"DP_PRICE_PREMIUM\") or \"9\")",
     ["test_tiers.suite_premium"], "без прайса Premium: на странице оплаты его нет"),
    ("перевыдача снова своей сборкой прав: файл Premium «другой» по кругу",
     "app/tools.py", "        will = license.features({**(dict(sub) if sub else {}), \"plan\": claim[\"plan\"]},\n"
     "                                db.parse_ts(last[\"grace_until\"]), now)\n",
     "        g = tiers.gcal_until({**(dict(sub) if sub else {}), \"plan\": claim[\"plan\"]},\n"
     "                             db.parse_ts(last[\"grace_until\"]), now)\n"
     "        will = {\"gcal\": g.strftime(db.TS)} if g else {}\n",
     ["test_tiers.suite_premium"], "не к перевыдаче"),
    ("карточки без строки Premium: /plata — 500 в день появления прайса",
     "app/views.py", "    tiers.PREMIUM: ((True, \"Tot ce are Plus\"),", "    \"premium-x\": ((True, \"Tot ce are Plus\"),",
     ["test_tiers.suite_premium_rules"], "строка на каждый вариант"),
    ("«что будет при выборе» молчит, что календари уйдут",
     "app/views.py", "    if cur in tiers.GDOC_TIERS and no_doc and running:\n", "    if False:\n",
     ["test_tiers.suite_premium_rules"], "«что будет при выборе» у Premium"),
    ("письмо о лицензии молчит о сроке календарей после ухода с Premium",
     "app/mail.py", "if gdoc_until and not trial and tier not in tiers.GDOC_TIERS", "if False",
     ["test_tiers.suite_premium_rules"], "письмо о лицензии ушедшей с Premium"),
    ("письмо зовёт на Premium без прайса",
     "app/mail.py", "    ts = [t for t in tiers.TIERS if tiers.list_price(t) > 0] or list(tiers.TIERS)\n",
     "    ts = list(tiers.TIERS)\n",
     ["test_tiers.suite_premium_rules"], "без прайса Premium — прежняя формула"),
    ("шаг 24 не переживает повтор",
     "app/db.py", "    if \"gdoc_until\" not in {r[1] for r in con.execute(\"PRAGMA table_info(subscriptions)\")}:\n",
     "    if True:\n",
     ["test_tiers.suite_premium_rules"], "шаг 24"),
    ("сторож множеств: сравнение с одним вариантом в тексте карточки",
     "app/views.py", "if t in tiers.SMS_TIERS else \"\"", "if t == tiers.PLUS else \"\"",
     ["test_tiers.suite_sets"], "нет сравнения с одним вариантом"),
    ("сторож множеств: строка варианта вместо множества (поведение то же — видит только сторож)",
     "app/views.py", "    if cur in tiers.GDOC_TIERS:\n        doc = \"; календари врачей работают\"\n",
     "    if cur == \"premium\":\n        doc = \"; календари врачей работают\"\n",
     ["test_tiers.suite_sets"], "нет сравнения с одним вариантом"),
    ("сторож множеств: кортеж из одного варианта",
     "app/payments.py", "    doc_had, doc_has = before in tiers.GDOC_TIERS, tier in tiers.GDOC_TIERS\n",
     "    doc_had, doc_has = before in (tiers.PREMIUM,), tier in tiers.GDOC_TIERS\n",
     ["test_tiers.suite_sets"], "нет сравнения с одним вариантом"),
    ("клиника на Premium без прайса видит отмеченным Basic: один клик гасит модуль SMS",
     "app/tiers.py", "    below = [t for t in sold if TIERS.index(t) < TIERS.index(cur)]\n",
     "    below = []\n",
     ["test_tiers.suite_premium_rules"], "клиника на Premium без прайса: в форме отмечен Plus"),
    ("Premium-филиал без права календарей: «Adaugă clinică» снова без варианта в выдаче",
     "app/account.py", "                      payments.ADVANCE, who, tier=tier)\n",
     "                      payments.ADVANCE, who, tier=tier if tier != \"premium\" else None)\n",
     ["test_branches.suite_paid"], "Premium из «Adaugă clinică»"),
    # --- Premium волна 2а: ответ пациента ссылкой из SMS (plink.py, plink_page.py) и подарки Premium ---
    ("GET страницы пишет в базу: робот превью «отвечал» бы за пациента",
     "app/routes_public.py", "        row = plink.lookup(con, plink.norm(code))\n",
     "        row = plink.lookup(con, plink.norm(code))\n"
     "        con.execute(\"UPDATE links SET seq=seq WHERE code=?\", (plink.norm(code),))\n",
     ["test_plink.suite_get_readonly"], "GET страницы: ни immediate"),
    ("ответ без подписи формы: слепой POST отвечает за пациента",
     "app/routes_public.py", "    if not plink_page.mark_ok(code, t, now):\n", "    if False:\n",
     ["test_plink.suite_api"], "POST без подписи формы — 403"),
    ("ответ с чужим Origin принимается",
     "app/routes_public.py",
     "    if not auth.same_origin_post(request):\n        return Response(status_code=403)\n    if plink_page.post_limited",
     "    if plink_page.post_limited",
     ["test_plink.suite_api"], "POST с чужим Origin — 403"),
    ("закрытому коду ответ принимается: визит перенесён, а регистратура видит старое «Vin»",
     "app/plink.py", "    if what not in ANSWERS or not alive(row, now) or row[\"state\"] == CLOSED:\n",
     "    if what not in ANSWERS or not alive(row, now):\n",
     ["test_plink.suite_api"], "закрытому коду ответ не принимается"),
    ("в таблице ссылок колонка телефона",
     "app/db.py", "            until TEXT NOT NULL, created_at TEXT NOT NULL, answered_at TEXT)\"\"\",\n",
     "            until TEXT NOT NULL, created_at TEXT NOT NULL, answered_at TEXT, phone TEXT)\"\"\",\n",
     ["test_plink.suite_schema"], "links: состав колонок перечислен"),
    ("шаг 25 не переживает повтор",
     "app/db.py", "    if \"name_free_until\" not in {r[1] for r in con.execute(\"PRAGMA table_info(subscriptions)\")}:\n",
     "    if True:\n",
     ["test_plink.suite_schema"], "шаг 25: повтор шага"),
    ("право ответа ссылкой и у Plus",
     "app/tiers.py", "LINK_TIERS = frozenset({PREMIUM})", "LINK_TIERS = frozenset({PLUS, PREMIUM})",
     ["test_plink.suite_rules", "test_plink.suite_api"], "sms_link: Premium — до конца файла"),
    ("файл Premium без права sms_link",
     "app/license.py", "(\"sms_link\", tiers.link_until(sub, grace_until, now))", "(\"sms_link\", None)",
     ["test_plink.suite_rules"], "права файла Premium: gcal, gcal_doctor и sms_link"),
    ("клиника в мета-тегах: карточка превью в переписке называет клинику",
     "app/plink_page.py", "    return _page(lang, body, head=meta(meta_lang), clinic=row[\"label\"]",
     "    return _page(lang, body, head=meta(meta_lang) + f\"<meta property='og:site_name' content='{E(row['label'])}'>\", "
     "clinic=row[\"label\"]",
     ["test_plink.suite_rules"], "ни клиники"),
    ("мета-теги от языка страницы, а не кода: разные карточки у одной ссылки",
     "app/plink_page.py", "    meta_lang = row[\"lang\"] if row[\"lang\"] in W else \"ro\"\n", "    meta_lang = lang\n",
     ["test_plink.suite_rules"], "мета-теги одни на все состояния"),
    ("предел промахов с адреса снят",
     "app/plink_page.py", "MISS_PER_HOUR = 10\n", "MISS_PER_HOUR = 10 ** 6\n",
     ["test_plink.suite_limit"], "11-й промах с адреса — 429"),
    ("робот превью считается человеком: адреса Google упираются в 429",
     "app/plink_page.py", "    return any(b in low for b in PREVIEW_BOTS)\n", "    return False\n",
     ["test_plink.suite_limit"], "робот превью: 15 промахов"),
    ("перебор запирает и живые коды с того же адреса",
     "app/routes_public.py",
     "    now = datetime.now(timezone.utc)\n    with db.connect() as con:\n        row = plink.lookup(con, plink.norm(code))\n",
     "    now = datetime.now(timezone.utc)\n"
     "    if plink_page.miss_limited(web.ip(request), request.headers.get(\"user-agent\", \"\")):\n"
     "        return _page(plink_page.dead(l, limited=True), 429)\n"
     "    with db.connect() as con:\n        row = plink.lookup(con, plink.norm(code))\n",
     ["test_plink.suite_limit"], "живой код с того же адреса отвечает"),
    ("коды не стираются задачей",
     "app/jobs.py", "            rep.links = plink.purge(con, now)", "            rep.links = 0",
     ["test_plink.suite_jobs"], "старше срока — стёрт"),
    ("80 SMS при каждой оплате Premium",
     "app/sms.py", "    if bonus_at(con, clinic_id) is not None:\n        return False\n", "",
     ["test_plink.suite_gifts"], "подарок 80 не повторяется"),
    ("подарки Premium и у Plus",
     "app/payments.py", "    if tier in tiers.GIFT_TIERS:\n", "    if True:\n",
     ["test_plink.suite_gifts"], "оплата Plus — подарка нет"),
    ("имя бесплатно и при помесячном Premium",
     "app/payments.py", "        if int(line[\"months\"]) == 12:\n            con.execute(\"UPDATE subscriptions SET name_free_until",
     "        if True:\n            con.execute(\"UPDATE subscriptions SET name_free_until",
     ["test_plink.suite_gifts"], "помесячный Premium: имя не бесплатно"),
    ("год имени продаётся при годовом Premium: клиника платит за включённое",
     "app/web.py", "    if year == sms.Y_FREE:\n", "    if False:\n",
     ["test_plink.suite_gifts"], "год имени при годовом Premium не продаётся"),
    ("имя при годовом Premium не работает без оплаты года",
     "app/sms.py", "        if (until is not None and until > now) or (free is not None and free > now):\n",
     "        if until is not None and until > now:\n",
     ["test_plink.suite_rules", "test_plink.suite_gifts"], "имя при годовом Premium: от своего имени"),
    ("письма о конце годового Premium не уходят",
     "app/sms.py", "        gift = free is not None and (paid is None or free > paid)\n", "        gift = False\n",
     ["test_plink.suite_gifts"], "письмо заранее"),
    ("короткий хост с no-referrer: «Vin» — 403 за Caddy",
     "deploy/Caddyfile", "\t\t# Origin: null, и same_origin_post отвечает 403 (тот же прайор, что у cloud.dentpilot.md выше)\n"
     "\t\tReferrer-Policy strict-origin-when-cross-origin\n",
     "\t\t# Origin: null, и same_origin_post отвечает 403 (тот же прайор, что у cloud.dentpilot.md выше)\n"
     "\t\tReferrer-Policy no-referrer\n",
     ["test_plink.suite_caddy"], "нигде не no-referrer"),
    ("короткий хост проксирует всё: кабинет и админка на v.dentpilot.md",
     "deploy/Caddyfile", "\thandle {\n\t\trespond 404\n\t}\n", "\thandle {\n\t\treverse_proxy cloud:8090\n\t}\n",
     ["test_plink.suite_caddy"], "всё прочее — 404"),
    ("код ссылки в журнале доступа рядом с IP",
     "app/logmask.py", "    return _LINK.sub(r\"\\g<1>\" + CODE_LABEL, _DLR.sub(r\"\\g<1>\" + LABEL, text))\n",
     "    return _DLR.sub(r\"\\g<1>\" + LABEL, text)\n",
     ["test_plink.suite_log"], "метка вместо кода"),
]

RUNNER = ("import importlib, sys\n"
          "sys.stdout.reconfigure(encoding='utf-8', errors='replace')\n"
          "sys.path.insert(0, 'tests')\n"
          "from harness import run\n"
          "sys.exit(run([(s, getattr(importlib.import_module(s.split('.')[0]), s.split('.')[1])) "
          "for s in sys.argv[1:]]))\n")


def _copy(dst: pathlib.Path) -> pathlib.Path:
    shutil.copytree(CLOUD, dst / "cloud", ignore=SKIP)
    for rel in NEIGHBOURS:
        if (ROOT / rel).is_dir():
            shutil.copytree(ROOT / rel, dst / rel, ignore=SKIP)
        elif (ROOT / rel).is_file():
            shutil.copyfile(ROOT / rel, dst / rel)
    return dst / "cloud"


def _run(cloud: pathlib.Path, suites: list) -> tuple[int, str]:
    # .pyc сверяет исходник лишь по секунде mtime и размеру: мутация той же длины в ту же секунду исполнила бы прошлую
    env = dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
    p = subprocess.run([sys.executable, "-c", RUNNER, *suites], cwd=str(cloud), env=env, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=900)
    return p.returncode, p.stdout + p.stderr


def main() -> int:
    bad = 0
    # места слома — до копии и прогонов: устаревшая пара видна сразу, а не через десять минут
    for name, rel, old, _new, _suites, _mark in MUTATIONS:
        n = (CLOUD / rel).read_text(encoding="utf-8").replace("\r\n", "\n").count(old)
        if n != 1:
            print(f"✗ {name}: место слома в {rel} встретилось {n} раз, нужно ровно 1")
            bad += 1
    if bad:
        print(f"УСТАРЕЛО ПАР: {bad}")
        return 1
    with tempfile.TemporaryDirectory(prefix="dp_cloud_mut_") as tmp:
        cloud = _copy(pathlib.Path(tmp))
        for name, rel, old, new, suites, mark in MUTATIONS:
            f = cloud / rel
            raw = f.read_bytes()
            f.write_bytes(raw.decode("utf-8").replace("\r\n", "\n").replace(old, new).encode("utf-8"))
            try:
                code, out = _run(cloud, suites)
            finally:
                f.write_bytes(raw)
            red = [ln.strip()[:120] for ln in out.splitlines() if ln.strip().startswith("✗")]
            hit = any(mark in ln for ln in red)
            ok = code != 0 and hit
            bad += 0 if ok else 1
            print(f"{'ok' if ok else '✗ '} {name}: код {code}, красных {len(red)}, "
                  f"нужная проверка {'красная' if hit else 'НЕ красная — сторож слепой'}")
            if not ok:
                print("\n".join("      " + ln for ln in (red[:5] or out.splitlines()[-15:])))
    print(f"все {len(MUTATIONS)} мутаций красные" if not bad else f"СЛЕПЫХ: {bad} из {len(MUTATIONS)}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
