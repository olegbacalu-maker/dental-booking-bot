"""Мутационные пары облака: каждая ломает одно свойство и требует, чтобы его набор покраснел.

    cd cloud && python tests/mutate.py            (на ПК Олега — TEMP на D:, как у прогона)

Это НЕ набор проверок, а инструмент рядом с ними — как `tests/mutate.py` движка; в `run_tests.py`
он не входит: проверяет он не сервер, а тесты. В CI — шаг «Мутация сторожей облака» работы `cloud`.

Зачем. Проверка поведения бывает зелёной и на сломанном коде — засев не дошёл до ветки, условие
слишком широкое, проверяется не то поле (`303` у формы на оба исхода). Отличить «держит» от «молчит»
можно одним способом: сломать свойство и увидеть красной ИМЕННО ту проверку, что его держит
(`mark` — кусок её названия; красная соседняя не в счёт: её мог уронить сам слом).

Настоящее дерево не трогается: `cloud/` (без `.venv`) и то, что наборы читают из соседей
(`bot/`, `tests/fixtures/`, `docs/site/`), копируются во временную папку; слом пишется в КОПИЮ,
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
# что наборы читают за пределами cloud/ (harness.FIX, load_by_path движка, страницы сайта)
NEIGHBOURS = ("bot", "tests/fixtures", "docs/site")
SKIP = shutil.ignore_patterns(".venv", "__pycache__", "*.pyc", ".pytest_cache")

# (что ломается, файл в cloud/, было, стало, наборы, кусок названия проверки, которая обязана покраснеть)
MUTATIONS = [
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
    return dst / "cloud"


def _run(cloud: pathlib.Path, suites: list) -> tuple[int, str]:
    env = dict(os.environ, PYTHONUTF8="1")
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
