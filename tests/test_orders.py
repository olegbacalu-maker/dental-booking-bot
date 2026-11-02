"""Заказы лаунчеру подписаны (02.11, разбор коллеги Б2).

Папку данных (`ProgramData\\DentPilot\\data`) пишет любая учётка Windows ПК,
а заказ исполняет лаунчер владельца: пустой маркер расшифровки или JSON
восстановления, положенный чужой учёткой, расшифровал бы ей картотеку или
подменил бы базу. Здесь — «чужой файл-заказ не исполняется, свой
исполняется» для расшифровки, шифрования и восстановления, плюс повтор
сохранённой копии и подмена приёмки под подписанным заказом.

Чужая учётка изображается другой папкой учётки (`DENTART_USER_DIR`): у неё
свой секрет, как у другой учётки Windows свой `%LOCALAPPDATA%` и свой DPAPI.
Исполнение — теми же функциями, что зовёт лаунчер (`desktop._prepare`);
сам лаунчер проверяется запуском в песочнице (заметка сессии `local-orders`).
"""
from __future__ import annotations

import base64
import contextlib
import json
import os
import pathlib
import shutil
import sqlite3
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "bot"))

from app import dpapi, paths  # noqa: E402
from app.core import dbkey, orders, restore  # noqa: E402

from harness import Client, Result, Server, _rmtree_settled, shell_signal  # noqa: E402

MARK = "Ionescu-Comanda-Test"


def _db(path: pathlib.Path, rows: int) -> None:
    """База, которую примет приёмка восстановления (patients, appointments,
    documents) и которую видно глазами в байтах (MARK)."""
    con = sqlite3.connect(str(path))
    con.execute("CREATE TABLE patients(id INTEGER PRIMARY KEY, name TEXT)")
    con.execute("CREATE TABLE appointments(id INTEGER PRIMARY KEY, note TEXT)")
    con.execute("CREATE TABLE documents(id INTEGER PRIMARY KEY, stored_path TEXT)")
    for i in range(rows):
        con.execute("INSERT INTO patients(name) VALUES (?)", (f"{MARK}-{i}",))
    con.commit()
    con.close()


def _patients(path: pathlib.Path) -> int:
    con = sqlite3.connect(str(path))
    try:
        return con.execute("SELECT COUNT(*) FROM patients").fetchone()[0]
    finally:
        con.close()


@contextlib.contextmanager
def _other_account(root: pathlib.Path):
    """Другая учётка Windows: своя папка учётки — свой секрет подписи."""
    was = os.environ.get(paths.USER_ENV)
    os.environ[paths.USER_ENV] = str(root / "alt-user")
    try:
        yield
    finally:
        if was is None:
            os.environ.pop(paths.USER_ENV, None)
        else:
            os.environ[paths.USER_ENV] = was


def _rejected(d: pathlib.Path, name: str) -> list[str]:
    return sorted(p.name for p in d.glob(f"{name}.{orders.REJECTED}-*"))


def _events(d: pathlib.Path) -> list[dict]:
    return orders.read_events(d / orders.DONE_FILE)


def _clear(d: pathlib.Path, name: str) -> None:
    for p in d.glob(f"{name}.{orders.REJECTED}-*"):
        p.unlink()
    (d / orders.DONE_FILE).unlink(missing_ok=True)


def suite_crypt(res: Result) -> None:
    """Шифрование и расшифровка: чужой заказ — в сторону, свой — исполняется."""
    if not dpapi.available():
        res.ok("DPAPI есть (только Windows)", False, "набор только для Windows")
        return
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="orders_crypt_"))
    try:
        d = tmp / "data"
        d.mkdir()
        db = d / "dental.db"
        _db(db, 4)
        key = dbkey.generate()

        # --- заказ шифрования прежнего вида: голый DPAPI-блоб ---
        # Так клал 2.7.0; так же положит чужая учётка блоб LOCAL_MACHINE,
        # который DPAPI владельца прочтёт, — со своим ключом.
        (d / dbkey.PENDING_FILE).write_text(
            dpapi.protect(base64.b64encode(key).decode()), encoding="utf-8")
        out = dbkey.apply_pending(d) or ""
        res.ok("шифрование: неподписанный заказ отвергнут", out.startswith("encrypt-rejected"), out)
        res.ok("шифрование: база осталась открытой, ключа нет",
               MARK.encode() in db.read_bytes() and not dbkey.enabled(d),
               "база легла под ключ из неподписанного заказа")
        res.ok("шифрование: заказ отодвинут в сторону, не удалён",
               not (d / dbkey.PENDING_FILE).exists() and _rejected(d, dbkey.PENDING_FILE),
               f"в папке: {sorted(p.name for p in d.iterdir())}")
        _clear(d, dbkey.PENDING_FILE)

        # --- своё шифрование ---
        res.ok("шифрование: свой заказ принят", dbkey.request_encrypt(d, key))
        res.check("лист печатается из подписанного заказа", dbkey.load_pending(d), key)
        out = dbkey.apply_pending(d) or ""
        res.ok("шифрование: свой заказ исполнен", out.startswith("encrypted"), out)
        res.ok("шифрование: база под ключом", MARK.encode() not in db.read_bytes()
               and dbkey.state(d) == dbkey.OK)

        # --- расшифровка: пустой маркер (так было до 2.8.0) ---
        (d / dbkey.DECRYPT_FILE).write_text("", encoding="utf-8")
        out = dbkey.apply_pending(d) or ""
        res.ok("расшифровка: пустой маркер отвергнут", out.startswith("decrypt-rejected"), out)
        res.ok("расшифровка: база под ключом, ключ на месте",
               MARK.encode() not in db.read_bytes() and dbkey.state(d) == dbkey.OK,
               "чужой маркер расшифровал картотеку")
        ev = _events(d)
        res.ok("расшифровка: отказ записан событием для директора",
               len(ev) == 1 and ev[0]["kind"] == "decrypt" and ev[0]["outcome"] == "rejected",
               repr(ev))
        res.ok("расшифровка: маркер отодвинут", _rejected(d, dbkey.DECRYPT_FILE)
               and not (d / dbkey.DECRYPT_FILE).exists())
        _clear(d, dbkey.DECRYPT_FILE)

        # --- расшифровка, подписанная ДРУГОЙ учёткой ---
        with _other_account(tmp):
            res.ok("другая учётка подписала свой заказ", dbkey.request_decrypt(d))
        out = dbkey.apply_pending(d) or ""
        res.ok("расшифровка: подпись другой учётки отвергнута",
               out.startswith("decrypt-rejected") and "semnătura" in out, out)
        res.ok("расшифровка: база всё ещё под ключом", dbkey.state(d) == dbkey.OK
               and MARK.encode() not in db.read_bytes())
        _clear(d, dbkey.DECRYPT_FILE)

        # --- подпись верна, но подменён вид заказа ---
        res.ok("свой заказ расшифровки положен", dbkey.request_decrypt(d))
        own = (d / dbkey.DECRYPT_FILE).read_text(encoding="utf-8")
        forged = json.loads(own)
        forged["kind"] = "restore"
        (d / dbkey.DECRYPT_FILE).write_text(json.dumps(forged), encoding="utf-8")
        out = dbkey.apply_pending(d) or ""
        res.ok("расшифровка: правка подписанного заказа ловится",
               out.startswith("decrypt-rejected"), out)
        _clear(d, dbkey.DECRYPT_FILE)

        # --- свой заказ расшифровки ---
        res.ok("свой заказ расшифровки положен", dbkey.request_decrypt(d))
        saved = (d / dbkey.DECRYPT_FILE).read_text(encoding="utf-8")
        res.check("расшифровка: свой заказ исполнен", dbkey.apply_pending(d), "decrypted")
        res.ok("расшифровка: база открытая, ключа нет",
               MARK.encode() in db.read_bytes() and dbkey.state(d) == dbkey.OFF)
        ev = _events(d)
        res.ok("расшифровка: исполнение записано событием",
               [(e["kind"], e["outcome"]) for e in ev] == [("decrypt", "done")], repr(ev))

        # --- повтор сохранённой копии после нового шифрования ---
        key2 = dbkey.generate()
        dbkey.request_encrypt(d, key2)
        res.ok("снова зашифровано", (dbkey.apply_pending(d) or "").startswith("encrypted"))
        (d / dbkey.DECRYPT_FILE).write_text(saved, encoding="utf-8")
        out = dbkey.apply_pending(d) or ""
        res.ok("расшифровка: сохранённая копия прошлого заказа отвергнута",
               out.startswith("decrypt-rejected"), out)
        res.ok("расшифровка: база под новым ключом", dbkey.state(d) == dbkey.OK
               and MARK.encode() not in db.read_bytes())

        # --- события: подделанное не доходит до директора ---
        ev = _events(d)
        fake = {**ev[0], "outcome": "done", "detail": "fals"}
        orders.write(d / orders.DONE_FILE, {"events": [*ev, fake]})
        got = orders.take_events(d)
        res.ok("события: подделанное отброшено, подписанные дошли",
               len(got) == len(ev) and all(e["detail"] != "fals" for e in got), repr(got))
        res.ok("события: файл снят после чтения", not (d / orders.DONE_FILE).exists())
    finally:
        _rmtree_settled(tmp)


def suite_restore(res: Result) -> None:
    """Восстановление: неподписанный, чужой, подменённый, повторённый — нет;
    свой — да."""
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="orders_restore_"))
    try:
        d = tmp / "data"
        (d / "backups").mkdir(parents=True)
        live = d / "dental.db"
        _db(live, 5)
        copy = "dental_20260101_090000_1.db"
        _db(d / "backups" / copy, 2)

        def stage() -> None:
            restore.stage_local(d, copy, None)

        # у владельца есть свой секрет (что-то он уже заказывал) — иначе
        # чужая подпись отвергается раньше, словами «нет ключа»
        orders._secret(create=True)

        # --- заказ прежнего вида: сводка JSON без подписи ---
        stage()
        (d / restore.REQUEST_FILE).write_text(
            json.dumps(restore.summary(d)), encoding="utf-8")
        out = restore.apply_pending(d, d) or ""
        res.ok("восстановление: неподписанный заказ отвергнут",
               out.startswith("restore-rejected"), out)
        res.check("восстановление: живая база та же", _patients(live), 5)
        res.ok("восстановление: заказ и приёмка отодвинуты в сторону, не удалены",
               _rejected(d, restore.REQUEST_FILE) and not restore.stage_dir(d).exists()
               and not restore.pending(d)
               and any((p / restore.ARC_DB).exists()
                       for p in d.glob(f"{restore.STAGE_DIR}.{orders.REJECTED}-*")),
               f"в папке: {sorted(p.name for p in d.iterdir())}")
        res.ok("восстановление: живую базу не отодвигали",
               not list(d.glob(f"dental.{restore.ASIDE}-*")))
        _clear(d, restore.REQUEST_FILE)

        # --- подписан другой учёткой ---
        stage()
        with _other_account(tmp):
            res.ok("другая учётка подписала заказ", restore.request(d))
        out = restore.apply_pending(d, d) or ""
        res.ok("восстановление: подпись другой учётки отвергнута",
               out.startswith("restore-rejected") and "semnătura" in out, out)
        res.check("восстановление: живая база та же (чужая подпись)", _patients(live), 5)
        _clear(d, restore.REQUEST_FILE)

        # --- свой заказ, но база в приёмке подменена после подписи ---
        stage()
        res.ok("свой заказ положен", restore.request(d))
        staged = restore.stage_dir(d) / restore.ARC_DB
        staged.unlink()
        _db(staged, 9)
        out = restore.apply_pending(d, d) or ""
        res.ok("восстановление: подмена приёмки под подписанным заказом ловится",
               out.startswith("restore-rejected") and "conținutul" in out, out)
        res.check("восстановление: живая база та же (подмена)", _patients(live), 5)
        _clear(d, restore.REQUEST_FILE)

        # --- свой заказ: исполняется ---
        stage()
        res.ok("свой заказ положен", restore.request(d))
        keep = tmp / "saved"
        shutil.copytree(restore.stage_dir(d), keep / restore.STAGE_DIR)
        shutil.copy2(d / restore.REQUEST_FILE, keep / restore.REQUEST_FILE)
        out = restore.apply_pending(d, d) or ""
        res.ok("восстановление: свой заказ исполнен", out.startswith("restored"), out)
        res.check("восстановление: живая база — из копии", _patients(live), 2)
        ev = _events(d)
        res.ok("восстановление: исполнение записано событием",
               [(e["kind"], e["outcome"], e["detail"]) for e in ev]
               == [("restore", "done", copy)], repr(ev))
        _clear(d, restore.REQUEST_FILE)

        # --- повтор: сохранённая копия заказа и приёмки ---
        live.unlink()
        _db(live, 7)
        shutil.copytree(keep / restore.STAGE_DIR, restore.stage_dir(d))
        shutil.copy2(keep / restore.REQUEST_FILE, d / restore.REQUEST_FILE)
        out = restore.apply_pending(d, d) or ""
        res.ok("восстановление: повтор исполненного заказа отвергнут",
               out.startswith("restore-rejected") and "folosită" in out, out)
        res.check("восстановление: база после повтора та же", _patients(live), 7)
        _clear(d, restore.REQUEST_FILE)

        # --- снятый заказ, подложенный позже ---
        stage()
        restore.request(d)
        shutil.rmtree(keep)
        shutil.copytree(restore.stage_dir(d), keep / restore.STAGE_DIR)
        shutil.copy2(d / restore.REQUEST_FILE, keep / restore.REQUEST_FILE)
        restore.cancel(d)
        shutil.copytree(keep / restore.STAGE_DIR, restore.stage_dir(d))
        shutil.copy2(keep / restore.REQUEST_FILE, d / restore.REQUEST_FILE)
        out = restore.apply_pending(d, d) or ""
        res.ok("восстановление: снятый заказ, подложенный позже, отвергнут",
               out.startswith("restore-rejected"), out)
        res.check("восстановление: база та же (снятый заказ)", _patients(live), 7)
    finally:
        _rmtree_settled(tmp)


def _feed(c: Client) -> list[str]:
    """Строки ленты «Activitate recentă» (аналитика)."""
    r = c.get("/api/stats")
    if r.status != 200:
        return []
    return [a["text"] for a in json.loads(r.body)["data"].get("activity", [])]


def suite_report(res: Result) -> None:
    """Старт приложения: события лаунчера — в летопись готовой строкой и
    баннером директору; подделанное событие не доходит. Восстановление в
    летопись пишет `backup_loop` (restore.done) — здесь от него только баннер."""
    s1 = Server(keep_dir=True)
    try:
        with s1:
            pass                               # первый старт: база, схема
        d = s1.dir
        orders.note(d, orders.DECRYPT, "done", nonce="t1")
        orders.note(d, orders.RESTORE, "rejected",
                    "semnătura nu corespunde acestui cont Windows")
        ev = orders.read_events(d / orders.DONE_FILE)
        orders.write(d / orders.DONE_FILE,
                     {"events": [*ev, {**ev[0], "nonce": "fals", "detail": "fals"}]})
        with Server(dir_=d) as s2:
            c = Client(s2.url).login()
            sig = shell_signal(c.get("/admin").body, "tamper")
            html = sig.get("html") or ""
            res.ok("баннер директору виден", sig.get("shown"), repr(sig)[:300])
            res.ok("баннер: расшифровка исполнена", "Criptarea evidenței a fost oprită" in html,
                   html[:400])
            res.ok("баннер: заказ отвергнут, названо что", "respins" in html
                   and "restaurarea evidenței" in html, html[:400])
            res.ok("баннер: у отказа — «ничего не удалено, повторите»",
                   "Nimic nu a fost șters" in html and "repetați" in html, html[:500])
            res.ok("баннер: совета про PIN нет — это не сигнал auth.json",
                   "schimbați PIN-urile" not in html, html[:500])
            res.check("подделанное событие не дошло (одна строка расшифровки)",
                      html.count("Criptarea evidenței a fost oprită"), 1)
            feed = _feed(c)
            res.ok("летопись: расшифровка готовой строкой",
                   any("Criptarea evidenței a fost oprită" in x for x in feed), repr(feed[:5]))
            res.ok("летопись: отказ готовой строкой, без подсказки",
                   any("respins" in x and "restaurarea" in x and "repetați" not in x
                       for x in feed), repr(feed[:5]))
            res.ok("файл событий снят", not (d / orders.DONE_FILE).exists())
            r = c.post("/admin/security/ack")
            res.ok("директор гасит баннер", r.status in (200, 303), r.status)
            sig = shell_signal(c.get("/admin").body, "tamper")
            res.ok("после «Am luat la cunoștință» баннера нет", not sig.get("shown"),
                   repr(sig)[:200])
    finally:
        s1.drop()


def suite_user_dir(res: Result) -> None:
    """Папка учётки — у Windows, не из окружения: `dental.env` лежит в общей
    папке и вливается в окружение лаунчера. Собранная программа
    `DENTART_USER_DIR` не слушает; Windows не ответила — заказ не исполняется
    (без отката в общую папку)."""
    if not dpapi.available():
        res.ok("Windows (SHGetKnownFolderPath)", False, "набор только для Windows")
        return
    fake = pathlib.Path(r"C:\Users\Public\dp-podmena")
    was_env, was_frozen, was_known = (os.environ.get(paths.USER_ENV), paths.is_frozen,
                                      paths._known_local_appdata)
    try:
        known = paths._known_local_appdata()
        res.ok("Windows отдаёт LocalAppData", known is not None and known.is_absolute(),
               repr(known))
        os.environ[paths.USER_ENV] = str(fake)
        res.check("из исходников переменная слушается", paths.user_dir(), fake)
        paths.is_frozen = lambda: True
        res.check("собранная программа переменную не слушает", paths.user_dir(),
                  (known / "DentPilot") if known else None)
        paths._known_local_appdata = lambda: None
        res.check("Windows не ответила — папки нет, отката в окружение нет",
                  paths.user_dir(), None)
        why = orders.check({"kind": "decrypt", "nonce": "x", "mac": "y"}, orders.DECRYPT)
        res.ok("без папки учётки заказ не исполняется", bool(why) and "folderul" in why,
               repr(why))
        res.check("без папки учётки подписать нечем", orders.sign(orders.DECRYPT), None)
    finally:
        paths.is_frozen, paths._known_local_appdata = was_frozen, was_known
        if was_env is None:
            os.environ.pop(paths.USER_ENV, None)
        else:
            os.environ[paths.USER_ENV] = was_env
