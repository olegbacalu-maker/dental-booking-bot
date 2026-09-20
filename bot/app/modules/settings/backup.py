"""Зашифрованная копия ВСЕЙ клиники — то, что уезжает с компьютера.

Зачем шифровать именно здесь, а не `data/backups/`: автокопии при старте лежат
рядом с открытой живой базой, шифровать их — театр. Осмысленна защита того,
что ПОКИДАЕТ машину: флешка в ящике регистратуры, архив в почте. Для этого
архив закрыт AES-256 в формате обычного ZIP: клиника откроет его 7-Zip'ом на
любом компьютере, БЕЗ DentPilot и без нас. Это условие честного бэкапа для
продукта соло-вендора: копия, которую может открыть только программа, которая
может не запуститься, — не копия, а обязательство.

Пароль вводится при каждом экспорте и НИГДЕ не хранится. Хранить его — значит
привязать копию к этой машине (DPAPI) и потерять весь смысл выездного архива.
Забытый пароль убивает один архив, живая база остаётся читаемой — этим экспорт
безопаснее шифрования самой базы, где забытый ключ = потерянная картотека.

⚠️ pyzipper есть только в настольном издании (requirements-desktop). Облако
живёт без него, поэтому импорт ленивый, а `available()` — часть договора.
"""
from __future__ import annotations

import pathlib
import sqlite3
from datetime import datetime

from ... import paths

MIN_PASS = 10   # 4–8 цифр PIN здесь не годятся: архив уезжает с машины,
                # то есть попадает ровно туда, где офлайн-перебор возможен


def available() -> bool:
    try:
        import pyzipper  # noqa: F401
        return True
    except ImportError:
        return False


def _db_snapshot(src: pathlib.Path, dst: pathlib.Path) -> None:
    """Копия базы через backup API, а не copyfile: у живой базы WAL, и копия
    файла на ходу может поймать середину транзакции. Тот же приём, что в
    автобэкапе desktop.py.

    ⭐ Если картотека зашифрована, снимок кладётся в архив ВСЁ РАВНО ОТКРЫТЫМ —
    и это решение, а не недосмотр. Архив уже заперт своим паролем (AES-256), а
    самодостаточным он обязан остаться: положи внутрь шифр SQLCipher, и
    клиника, потерявшая лист восстановления, лишится разом и живой базы, и ВСЕХ
    копий. Единая точка отказа страшнее второго замка. Заодно уцелеет обещание
    «архив открывается 7-Zip'ом без DentPilot» — иначе оно стало бы ложью.
    ⚠️ Отсюда следует, что пароль архива — это и есть защита картотеки в нём.
    Требование «не короче 10 знаков» после шифрования базы стало важнее, а не
    наоборот.
    """
    from ...core import dbkey

    if not dbkey.enabled():
        a = sqlite3.connect(str(src))
        b = sqlite3.connect(str(dst))
        try:
            with b:
                a.backup(b)
        finally:
            a.close()
            b.close()
        return

    key = dbkey.load()
    if key is None:
        # ключ есть, но не читается — молча сделать пустой архив нельзя:
        # клиника узнала бы об этом в день, когда архив понадобился
        raise RuntimeError("cheia bazei de date nu poate fi citită — "
                           "copia de rezervă nu a fost creată")
    import sqlcipher3.dbapi2 as sqlcipher
    con = sqlcipher.connect(str(src))
    try:
        con.execute(f"PRAGMA key = {dbkey.pragma_value(key)}")
        # KEY '' = приёмник без шифрования; sqlcipher_export переписывает в него
        # всю базу постранично — это штатный способ снять шифр, а не backup(),
        # который между разными состояниями шифрования не определён
        con.execute("ATTACH DATABASE ? AS plain KEY ''", (str(dst),))
        con.execute("SELECT sqlcipher_export('plain')")
        con.execute("DETACH DATABASE plain")
    finally:
        con.close()


def _logo_files() -> list[tuple[pathlib.Path, str]]:
    """Логотип клиники — единственный файл профиля ВНЕ `data/`.

    Он лежит в корне папки клиники, рядом с `clinic.json`, то есть уровнем выше
    единственного обхода каталога в белом списке, — и потому не попадал в архив
    ни при каких условиях. Наружу это выглядело так: клиника восстановилась на
    новом ПК, всё на месте, а логотип пропал из 043/e, acord и шапки журнала.
    Ни ошибки, ни пустого места — просто бланк без логотипа, как у клиники,
    которая его не загружала.

    ⚠️ Папку спрашиваем у `theme`, а не считаем от `clinic_json`: второй
    вычислитель этого пути запрещён прямо в докстринге `eng.config_path()` —
    разойдясь, они увезли бы в архив файл из папки, в которую программа при
    следующем запуске не смотрит.
    ⭐ Смотрим на ДИСК по двум разрешённым именам, а не на
    `theme.current()["logo"]`: копия обязана повторять то, что лежит, а не то,
    что записано в профиле. `save_logo` держит на диске ровно один файл (при
    смене формата удаляет второй), так что список выходит из одного имени, а
    расхождение профиля с диском копию больше не обкрадывает.
    """
    from ...core import theme

    d = theme.logo_dir()
    out = []
    for name in sorted(theme.LOGO_NAMES.values()):
        if (p := d / name).is_file():
            out.append((p, name))
    return out


def write_encrypted(data_dir: pathlib.Path, clinic_json: pathlib.Path | None,
                    password: str, dest: pathlib.Path) -> int:
    """Собрать зашифрованный архив клиники. Возвращает число файлов внутри.

    Внутрь идёт всё, из чего клиника восстанавливается НА ЛЮБОЙ машине:
    база, профиль клиники, ЛОГОТИП, документы пациентов. Не идут: dental.env
    (токен там зашифрован DPAPI этой машины — на другой он мусор, а класть его
    открытым значило бы ронять секрет в архив), логи и автокопии (это уже
    копии).

    ⛔ Состав — БЕЛЫЙ СПИСОК, и обход каталога здесь ровно один: по
    `data/files/`. Расширить его до обхода папки клиники нельзя — в её корне
    лежит `dental.env`, а по задаче P7 туда же ляжет `device.json` (личность
    машины): обход склонировал бы на чужой компьютер и то, и другое. Всё, что
    лежит в корне и обязано переехать, добавляется ПОИМЁННО.
    """
    import pyzipper

    files: list[tuple[pathlib.Path, str]] = []
    snap = dest.with_suffix(".db_snapshot")
    db_file = data_dir / "dental.db"
    if db_file.exists():
        _db_snapshot(db_file, snap)
        files.append((snap, "data/dental.db"))
    if clinic_json and clinic_json.exists():
        files.append((clinic_json, "clinic.json"))
        files += _logo_files()
    auth = data_dir / "auth.json"
    if auth.exists():                     # хеши PIN, не сам PIN — можно
        files.append((auth, "data/auth.json"))
    fdir = data_dir / "files"
    if fdir.is_dir():
        for f in sorted(fdir.rglob("*")):
            if f.is_file() and not f.name.endswith(".thumb.jpg"):
                files.append((f, f"data/files/{f.relative_to(fdir).as_posix()}"))

    try:
        # ⚠️ Архив собирается ДВУМЯ заходами, и это не причуда. CITESTE-MA.txt
        # обязан лежать БЕЗ шифра: Проводник Windows не умеет WinZip-AES, и
        # если инструкция «откройте 7-Zip/WinRAR» заперта тем же паролем, она
        # не существует — человек на чужой машине видит архив, который «не
        # извлекается», и всё (найдено на первом же живом экспорте 08-06).
        # Секретов в readme нет; одним заходом не выйдет — AESZipFile с
        # encryption=WZ_AES требует пароль на КАЖДУЮ запись.
        with pyzipper.AESZipFile(dest, "w",
                                 compression=pyzipper.ZIP_DEFLATED) as z:
            z.writestr("CITESTE-MA.txt", _readme())
        with pyzipper.AESZipFile(dest, "a", compression=pyzipper.ZIP_DEFLATED,
                                 encryption=pyzipper.WZ_AES) as z:
            z.setpassword(password.encode("utf-8"))
            # опись — в ШИФРОВАННУЮ часть: в ней имена пациентов
            z.writestr("CONTINUT.txt", _manifest(snap, files))
            for src, arc in files:
                z.write(src, arc)
    finally:
        snap.unlink(missing_ok=True)
    return len(files)


def _manifest(snap: pathlib.Path, files: list[tuple[pathlib.Path, str]]) -> str:
    """Опись архива человеческим языком — ответ на «а мои данные вообще тут?».

    Родилась из первого живого экспорта (08-06): Олег распаковал архив и увидел
    базу-кирпич да файлы с шестнадцатеричными именами — «ни имён, ничего, пара
    фотографий». Данные там БЫЛИ все, но проверить это человеку было нечем, а
    бэкап, которому нельзя поверить глазами, клиника делать перестанет.

    Имена файлов на диске технические НАМЕРЕННО (их связывает база, и при
    восстановлении они обязаны совпасть) — поэтому опись, а не переименование.
    Читается СНИМОК базы, не живая база: снимок уже сделан, консистентен и
    никого не блокирует. Любая ошибка описи не должна валить сам бэкап —
    опись украшает архив, а спасает его содержимое.
    """
    from ...core import theme

    logo_arcs = set(theme.LOGO_NAMES.values())
    arc_by_name = {src.name: arc for src, arc in files}
    pat, appt, docs, rows = "?", "?", "?", []
    if snap.exists():
        try:
            c = sqlite3.connect(str(snap))
            try:
                pat = c.execute("SELECT COUNT(*) FROM patients").fetchone()[0]
                appt = c.execute("SELECT COUNT(*) FROM appointments").fetchone()[0]
                docs = c.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
                rows = c.execute(
                    """SELECT d.stored_path, d.filename, COALESCE(p.name, '')
                       FROM documents d LEFT JOIN patients p ON p.id = d.patient_id
                       ORDER BY d.patient_id, d.id""").fetchall()
            finally:
                c.close()
        except sqlite3.Error:
            pass
    lines = [
        "CE CONTINE ACEASTA ARHIVA",
        "=========================",
        "",
        f"Pacienti: {pat} · Programari: {appt} · Documente: {docs}",
        "",
        "data/dental.db - TOATA evidenta clinicii: pacientii cu fisele lor,",
        "    programarile, planurile de tratament, istoricul. Fisierul se",
        "    citeste DOAR prin programul DentPilot (restaurarea - in",
        "    CITESTE-MA.txt). Numele pacientilor sunt inauntru, nu in numele",
        "    fisierelor.",
        "clinic.json - profilul clinicii: medici, servicii, program de lucru.",
    ]
    # логотип называем ТОЛЬКО когда он правда внутри: опись отвечает на вопрос
    # «мои данные тут?», и строка про файл, которого в архиве нет, отвечает на
    # него ложью — а это хуже молчания
    for _, arc in files:
        if arc in logo_arcs:
            lines.append(f"{arc} - logo-ul clinicii (apare pe documentele")
            lines.append("    tiparite - 043/e, acord - si la intrare).")
    lines += [
        "data/auth.json - PIN-ul jurnalului (pastrat ca hash).",
        "data/files/doctors/ - fotografiile medicilor.",
        "data/files/<nr>/ - documentele pacientilor. Numele de pe disc sunt",
        "    tehnice (asa le leaga baza de date); corespondenta reala:",
        "",
    ]
    for stored, fname, pname in rows:
        arc = arc_by_name.get(pathlib.PurePath(stored).name)
        who = f" ({pname})" if pname else ""
        mark = "" if arc else "  [!] lipseste pe disc"
        lines.append(f"  {arc or '—':42} <- {fname}{who}{mark}")
    if not rows:
        lines.append("  — nu exista documente incarcate —")
    lines += [
        "",
        "Pentru o copie LIZIBILA a unui singur pacient (HTML + documentele",
        "lui cu nume reale) folositi butonul «Descarca datele pacientului»",
        "din fisa pacientului, in program.",
        "",
    ]
    return "\r\n".join(lines)


def _readme() -> str:
    """Инструкция восстановления — единственный файл архива БЕЗ шифра.

    ⭐ Папку называем НАСТОЯЩИМ путём, а не «рядом с exe»: с переезда в
    `Program Files` раскладок две (обычная `%ProgramData%\\DentPilot` и
    портативная — рядом с exe, по `portable.flag`), и словесное описание
    устареет на следующем же переезде. ⚠️ Подставляется путь ИСХОДНОЙ машины,
    поэтому он и подписан как «откуда снята копия»: на новом компьютере папка
    может быть другой, и авторитетом назван экран «Stare sistem» ТОЙ машины,
    куда восстанавливают.

    ⛔ Шаг 4 остаётся ОБОБЩЁННЫМ («весь состав, сохраняя структуру»), а не
    перечислением файлов. Перечисление — ловушка на будущее: состав архива
    растёт, и файл, забытый в списке, молча останется невосстановленным у
    клиники, которая всё сделала по инструкции.
    ⚠️ Папка названа ДО шага 3, а не внутри шага 4, как было: шаг 3 велит
    удалить `data\\dental.db-wal`, то есть уже требует знать, в какой папке
    искать, — прежний порядок отвечал на это шагом позже.
    """
    # Путь спрашиваем у того же делегата, что и экран «Stare sistem»
    # (`layout.data_folder`): второй вычислитель папки — ровно тот класс
    # ошибки, который там и описан.
    root = paths.data_root()
    where = ("\r\n"
             "  Pe calculatorul de unde s-a luat aceasta copie, folderul cu\r\n"
             "  date era:\r\n"
             "    " + str(root) + "\r\n") if root is not None else ""
    return (
        "COPIE DE REZERVA DENTPILOT (criptata AES-256)\r\n"
        "=============================================\r\n\r\n"
        "ACEST fisier se deschide fara parola - restul fisierelor sunt criptate.\r\n\r\n"
        "IMPORTANT: Windows (Explorer) NU poate extrage aceasta arhiva -\r\n"
        "va afisa o eroare. Folositi un program gratuit:\r\n"
        "  * 7-Zip  (www.7-zip.org)  - click dreapta -> 7-Zip -> Extract...\r\n"
        "  * WinRAR - click dreapta -> Extract...\r\n"
        "La extragere introduceti parola stabilita la export.\r\n"
        "Parola NU este salvata nicaieri - fara ea datele nu pot fi citite.\r\n\r\n"
        "Ce este inauntru - vezi CONTINUT.txt dupa dezarhivare: cati pacienti,\r\n"
        "cate programari si care fisier tehnic este care document real.\r\n\r\n"
        "Restaurare pe un calculator nou:\r\n\r\n"
        "  FOLDERUL CU DATE - acolo se restaureaza totul.\r\n"
        "  ATENTIE: NU este folderul in care se instaleaza DentPilot.exe.\r\n"
        "  Datele clinicii stau separat de program:\r\n"
        "    * instalare obisnuita:  C:\\ProgramData\\DentPilot\r\n"
        "    * varianta portabila (pe stick, cu fisierul portable.flag langa\r\n"
        "      DentPilot.exe): chiar folderul in care sta DentPilot.exe\r\n"
        "  Calea exacta o arata programul DE PE CALCULATORUL NOU:\r\n"
        "  Setari > Stare sistem, randul \"Folderul cu date\". Verificati\r\n"
        "  acolo, nu ghiciti: dezarhivata in alt folder, arhiva nu ajunge la\r\n"
        "  program - el porneste cu evidenta goala, ca si cum copia ar fi\r\n"
        "  fost goala, si nu apare nicio eroare.\r\n"
        + where +
        "  Mai jos, \"folderul cu date\" inseamna acest folder.\r\n\r\n"
        "  1. Instalati DentPilot si porniti-l o data (se creeaza folderul).\r\n"
        "  2. Inchideti programul.\r\n"
        "  3. In folderul cu date STERGETI fisierele data\\dental.db-wal si\r\n"
        "     data\\dental.db-shm, daca exista. ACEST PAS NU SE SARE: ele\r\n"
        "     apartin bazei create la pasul 1, iar daca raman, Windows le\r\n"
        "     aplica peste baza restaurata si evidenta revine goala - fara\r\n"
        "     nicio eroare, ca si cum arhiva ar fi fost goala.\r\n"
        "  4. Dezarhivati TOT continutul arhivei PESTE folderul cu date,\r\n"
        "     pastrand structura din arhiva: folderul data\\ din arhiva se\r\n"
        "     suprapune peste data\\, iar celelalte fisiere ajung direct in\r\n"
        "     folderul cu date, unul langa altul.\r\n"
        "  5. DACA exista fisierul data\\db.key (criptarea evidentei era\r\n"
        "     activata pe acest calculator) - STERGETI data\\db.key. Baza din\r\n"
        "     arhiva NU este criptata, iar cu cheia ramasa pe loc programul ar\r\n"
        "     deschide-o ca pe una criptata si ar da eroare la pornire\r\n"
        "     (\"file is not a database\"). Dupa restaurare criptarea se\r\n"
        "     activeaza din nou din Setari - Criptarea evidentei. Este singura\r\n"
        "     situatie in care acest fisier se sterge.\r\n"
        "  6. Porniti programul - pacientii, programarile si documentele sunt la loc.\r\n"
        "  7. Reintroduceti tokenul botului Telegram in Setari (tokenul nu se\r\n"
        "     copiaza intre calculatoare, din motive de securitate).\r\n\r\n"
        "ACELASI PAS 3 se aplica si cand copiati o singura copie zilnica din\r\n"
        "data\\backups peste data\\dental.db: stergeti intai -wal si -shm.\r\n"
        "(Pasul 5 NU se aplica la copiile zilnice: ele sunt criptate cu aceeasi\r\n"
        "cheie ca baza, deci db.key ramane pe loc.)\r\n\r\n"
        "Arhiva contine date despre sanatate. Pastrati-o intr-un loc sigur.\r\n")


def archive_name() -> str:
    return f"dentpilot-backup-{datetime.now().strftime('%Y%m%d_%H%M')}.zip"
