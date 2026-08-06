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

MIN_PASS = 10   # 4–6 цифр PIN здесь не годятся: архив уезжает с машины,
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
    автобэкапе desktop.py."""
    a = sqlite3.connect(str(src))
    b = sqlite3.connect(str(dst))
    try:
        with b:
            a.backup(b)
    finally:
        a.close()
        b.close()


def write_encrypted(data_dir: pathlib.Path, clinic_json: pathlib.Path | None,
                    password: str, dest: pathlib.Path) -> int:
    """Собрать зашифрованный архив клиники. Возвращает число файлов внутри.

    Внутрь идёт всё, из чего клиника восстанавливается НА ЛЮБОЙ машине:
    база, профиль клиники, документы пациентов. Не идут: dental.env (токен там
    зашифрован DPAPI этой машины — на другой он мусор, а класть его открытым
    значило бы ронять секрет в архив), логи и автокопии (это уже копии).
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
        "Restaurare pe un calculator nou:\r\n"
        "  1. Instalati DentPilot si porniti-l o data (se creeaza folderul).\r\n"
        "  2. Inchideti programul.\r\n"
        "  3. Dezarhivati continutul PESTE folderul programului\r\n"
        "     (clinic.json langa DentPilot.exe, folderul data\\ peste data\\).\r\n"
        "  4. Porniti programul - pacientii, programarile si documentele sunt la loc.\r\n"
        "  5. Reintroduceti tokenul botului Telegram in Setari (tokenul nu se\r\n"
        "     copiaza intre calculatoare, din motive de securitate).\r\n\r\n"
        "Arhiva contine date despre sanatate. Pastrati-o intr-un loc sigur.\r\n")


def archive_name() -> str:
    return f"dentpilot-backup-{datetime.now().strftime('%Y%m%d_%H%M')}.zip"
