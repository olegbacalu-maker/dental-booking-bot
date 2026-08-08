"""PIN клиники: хранение, переезд старого файла и защита от подбора.

Отдельный файл, потому что все прочие наборы входят по ADMIN_KEY — это ветка
ОБЛАЧНОГО издания, и ветка PIN-файла ими не проверялась вовсе. А именно она
несёт то, что клиника получает на свой компьютер: стойкость хеша и счётчик
попыток. Поэтому сервер здесь поднимается с пустым ADMIN_KEY.
"""
import hashlib
import json
import os
import pathlib
import shutil
import sys
import tempfile
import time

from harness import BOT, Client, Result, Server

NO_KEY = {"ADMIN_KEY": ""}          # без него издание уходит веткой ADMIN_KEY


def _v1_file(server: Server, pin: str) -> None:
    """Положить auth.json СТАРОГО формата — так выглядят установленные клиники."""
    salt = "0123456789abcdef"
    (server.dir / "auth.json").write_text(json.dumps(
        {"salt": salt,
         "hash": hashlib.sha256(f"{salt}:{pin}".encode()).hexdigest()}),
        encoding="utf-8")


def _rec(server: Server) -> dict:
    return json.loads((server.dir / "auth.json").read_text(encoding="utf-8"))


def suite_store(res: Result) -> None:
    """Что именно ложится на диск при первой установке PIN."""
    with Server(env=NO_KEY) as s:
        c = Client(s.url)
        r = c.get("/admin")
        res.ok("без PIN журнал ведёт на установку",
               r.status == 303 and "/admin/setup" in r.location,
               f"код {r.status}, location {r.location!r}")

        c.post("/admin/setup", pin1="4321", pin2="4321")
        rec = _rec(s)
        u = (rec.get("users") or [{}])[0]
        res.check("PIN пишется в формате v2", rec.get("v"), 2)
        res.check("хеш считается pbkdf2", u.get("kdf"), "pbkdf2-sha256")
        res.ok("итераций не меньше 600 000", int(u.get("iter", 0)) >= 600_000,
               f"iter={u.get('iter')!r}")
        res.ok("сам PIN в файл не попадает", "4321" not in json.dumps(rec),
               "PIN виден в auth.json")
        res.ok("подпись сессии отдельна от хеша PIN",
               bool(rec.get("cookie_key")) and rec["cookie_key"] != u.get("hash"),
               "подпись привязана к хешу — второго пользователя не добавить")
        res.ok("список пользователей, а не один",
               isinstance(rec.get("users"), list), "users не список")
        res.ok("после установки журнал открыт", c.get("/admin").status == 200,
               "не пустил сразу после установки PIN")


def suite_migrate(res: Result) -> None:
    """Клиника, обновившаяся с прошлой версии, входит своим прежним PIN."""
    s = Server(env=NO_KEY)
    _v1_file(s, "4321")
    with s:
        bad = Client(s.url)
        bad.post("/admin/login", password="1111", next="/admin")
        res.ok("неверный PIN не пускает", bad.get("/admin").status == 303,
               "пустил по неверному PIN")
        res.ok("неудачная попытка файл не трогает", "v" not in _rec(s),
               "файл переписан при НЕверном PIN")

        c = Client(s.url)
        c.post("/admin/login", password="4321", next="/admin")
        # ⚠️ главная проверка набора: переезд меняет ключ подписи, и если кука
        # выдана до него — вход «удался» и тут же отваливается на первой странице
        res.ok("прежний PIN пускает, и сессия переживает переезд",
               c.get("/admin").status == 200,
               "клиника с прошлой версии осталась за дверью")
        res.check("файл переехал в v2", _rec(s).get("v"), 2)
        res.check("и на pbkdf2", _rec(s)["users"][0].get("kdf"), "pbkdf2-sha256")
        res.ok("старый одноитерационный хеш с диска убран",
               "0123456789abcdef" not in json.dumps(_rec(s)),
               "прежняя соль осталась в файле")


def suite_throttle(res: Result) -> None:
    """Перебор через форму. Стойкость хеша тут ни при чём — считает счётчик."""
    s = Server(env=NO_KEY)
    _v1_file(s, "4321")
    with s:
        c = Client(s.url)
        t0 = time.time()
        c.post("/admin/login", password="1111", next="/admin")
        spent = time.time() - t0
        res.ok("неудача стоит заметной паузы", spent >= 0.5,
               f"ответ за {spent:.2f} с — скрипт переберёт 10 000 вариантов")

        for _ in range(4):                    # 5 подряд — первая ступень лестницы
            c.post("/admin/login", password="1111", next="/admin")
        r = c.post("/admin/login", password="4321", next="/admin")
        res.ok("после серии неудач не пускает даже ВЕРНЫЙ PIN",
               "err=lock" in r.location, f"location {r.location!r}")
        res.ok("и журнал остаётся закрыт", c.get("/admin").status == 303,
               "пустил в журнал во время блокировки")
        res.ok("счётчик переживает перезагрузку страницы входа",
               "err=lock" in Client(s.url).post(
                   "/admin/login", password="4321", next="/admin").location,
               "новая сессия обходит блокировку")
        res.ok("экран объясняет блокировку, а не врёт про неверный PIN",
               "încercări" in c.get("/admin/login?err=lock&s=30").body,
               "нет текста о превышении попыток")


def suite_roles(res: Result) -> None:
    """Роли: директор / регистратура / медик (08-06, просьба первой клиники).

    ⭐ Главное, что стережётся здесь, — что запрет живёт В МАРШРУТЕ, а не в
    меню. Спрятанный пункт защищает ровно до первого набранного вручную адреса
    и не защищает POST вообще; проверка «страница не в меню» без проверки
    «страница не открывается» дала бы зелёный прогон при настежь открытых
    деньгах.
    """
    with Server(env=NO_KEY) as s:
        boss = Client(s.url)
        boss.post("/admin/setup", pin1="1111", pin2="1111")
        res.check("врач заводится",
                  boss.post("/admin/users/save", uid="d2", name="Dr. Liviu",
                            role="medic", doctor_id="d2", pin="2222").msg, "ok_user")
        res.check("регистратура заводится",
                  boss.post("/admin/users/save", uid="ana", name="Ana R",
                            role="receptie", pin="3333").msg, "ok_user")

        # вход возможен по ОДНОМУ паролю, значит одинаковых быть не должно —
        # иначе журнал доступа однажды назовёт не того человека
        res.check("чужой пароль повторить нельзя",
                  boss.post("/admin/users/save", uid="x1", name="X", role="medic",
                            pin="2222").msg, "dup_user")
        res.check("id только из безопасных символов",
                  boss.post("/admin/users/save", uid="Ана!", name="X", role="medic",
                            pin="4444").msg, "bad_user")
        res.check("новому нужен пароль",
                  boss.post("/admin/users/save", uid="x2", name="X",
                            role="medic").msg, "bad_user")
        # ⭐ последний директор запер бы настройки НАВСЕГДА: вернуть право некому
        res.check("последний директор не снимает с себя роль",
                  boss.post("/admin/users/save", uid="clinic", name="D",
                            role="medic").msg, "last_dir")
        res.check("и не удаляет сам себя",
                  boss.post("/admin/users/delete", uid="clinic").msg, "self_user")

        med = Client(s.url)
        med.post("/admin/login", password="2222", next="/admin")
        res.ok("врач входит своим паролем", med.get("/admin").status == 200,
               "не пустило по личному паролю")
        for path in ("/admin/all", "/admin/search", "/admin/doctor/d2"):
            res.ok(f"врачу открыто {path}", med.get(path).status == 200,
                   "закрыли лишнее")
        # каталог врачей врачу закрыт с 1.15.1 (канарейка 1.15.0: врач с
        # телефона открывал ЧУЖИЕ карточки и мог менять фото) — журнал и
        # пациенты открыты, карточки врачей нет
        for path in ("/admin/stats", "/admin/settings",
                     "/admin/settings/security", "/admin/settings/system",
                     "/admin/settings/faq", "/admin/medici",
                     "/admin/doctor-card/d2"):
            r = med.get(path)
            res.ok(f"врачу закрыто {path}",
                   r.status == 303 and "no_access" in r.location,
                   f"код {r.status}, location {r.location!r}")
        # ⚠️ POST закрыт отдельно: форму отправляют не только из меню
        for path, kw in (("/admin/settings/save", {"payload": "{}"}),
                         ("/admin/users/save", {"uid": "z1", "name": "Z",
                                                "role": "director", "pin": "9999"}),
                         ("/admin/backup/export", {"parola": "x"}),
                         ("/admin/doctor-card/d2/photo/del", {}),
                         ("/admin/doctor-card/d2/save", {"name": "Dr. Hack"})):
            r = med.post(path, **kw)
            res.ok(f"врачу закрыт POST {path}",
                   r.status == 303 and "no_access" in r.location,
                   f"код {r.status}, location {r.location!r}")
        res.ok("врач не смог завести себе директора",
               all(u.get("id") != "z1" for u in _rec(s)["users"]),
               "чужой POST создал учётку")

        page = med.get("/admin").body
        res.ok("в меню врача нет денег и настроек",
               "/admin/stats" not in page and "/admin/settings" not in page,
               "закрытый раздел остался в меню")
        res.ok("в меню врача нет раздела Medici",
               "/admin/medici" not in page, "закрытый каталог остался в меню")
        res.ok("день врача не зовёт в закрытую фишу",
               "doctor-card" not in med.get("/admin/doctor/d2").body,
               "ссылка «Fișa medicului» видна врачу — поведёт в отказ")

        # регистратуре каталог врачей ОСТАВЛЕН: отпуск/часы/услуги — операционка
        rec_c = Client(s.url)
        rec_c.post("/admin/login", password="3333", next="/admin")
        res.ok("регистратуре каталог врачей открыт",
               rec_c.get("/admin/medici").status == 200,
               "у стойки отняли врачей — отпуск теперь только через директора")
        res.ok("регистратуре открыта и карточка врача",
               rec_c.get("/admin/doctor-card/d2").status == 200,
               "карточка врача закрылась и для стойки")
        res.ok("врач подписан в углу", "Dr. Liviu" in page and "Medic" in page,
               "нет имени вошедшего")
        boss_page = boss.get("/admin").body
        res.ok("у директора разделы на месте",
               "/admin/stats" in boss_page and "/admin/settings" in boss_page,
               "директор потерял свои разделы")

        # смена пароля закрывает вкладки ИМЕННО этого человека
        boss.post("/admin/users/save", uid="d2", name="Dr. Liviu", role="medic",
                  doctor_id="d2", pin="5555")
        res.ok("после смены пароля старая сессия врача закрыта",
               med.get("/admin").status == 303, "старая кука ещё пускает")
        res.ok("а директора — нет", boss.get("/admin").status == 200,
               "правка чужой учётки выкинула директора")
        med2 = Client(s.url)
        med2.post("/admin/login", password="5555", next="/admin")
        res.ok("новый пароль пускает", med2.get("/admin").status == 200, "не пустило")
        boss.post("/admin/users/delete", uid="d2")
        res.ok("удалённая учётка перестаёт пускать НЕМЕДЛЕННО",
               med2.get("/admin").status == 303, "уволенный остался внутри")

        a = Client(s.url)
        a.post("/admin/login", password="3333", uid="ana", next="/admin")
        res.ok("вход с указанием своего id", a.get("/admin").status == 200,
               "не пустило по id+паролю")
        b = Client(s.url)
        b.post("/admin/login", password="3333", uid="clinic", next="/admin")
        res.ok("свой пароль под чужим id не пускает",
               b.get("/admin").status == 303, "пустило под чужим именем")

        # закон 195 спрашивает «кто именно», а не «канал»
        r = a.post("/admin/patients/new", name="Pacient Jurnal", phone="069000111")
        pid = r.location.split("/admin/patient/")[1].split("?")[0]
        res.ok("в летописи стоит имя вошедшего",
               "Ana R" in a.get(f"/admin/patient/{pid}").body,
               "событие подписано каналом, а не человеком")

        # деньги: рецепция ПРИНИМАЕТ платёж (она их физически берёт), но не
        # удаляет и не видит сводных сумм — это директорское
        res.check("рецепция записывает платёж",
                  a.post(f"/admin/patient/{pid}/pay", amount="200",
                         method="numerar").msg, "ok_pay")
        page = a.get(f"/admin/patient/{pid}").body
        res.ok("рецепция видит платёж и аванс на фише",
               "200 MDL" in page and "Avans" in page, "платёж не виден")
        res.ok("кнопки удаления платежа у рецепции нет",
               "/pay/" not in page.replace(f"{pid}/pay'", ""),
               "рецепции нарисовали директорскую кнопку")
        r = a.post(f"/admin/patient/{pid}/pay/1/del")
        res.ok("удаление платежа рецепции запрещено",
               r.status == 303 and "no_access" in r.location,
               f"location {r.location!r}")


def suite_tamper(res: Result) -> None:
    """Сигнализация auth.json: подмена или удаление файла вне программы видны.

    Это след, а не замок — у кого файл, у того рядом и база. Стережётся два
    свойства: чужое вмешательство оставляет баннер и строку в ленте, а СВОИ
    записи (setup, смена PIN, учётки) при следующем старте тревогу НЕ дают —
    ложный «взлом» напугал бы клинику сильнее настоящего.
    """
    base = pathlib.Path(tempfile.mkdtemp(prefix="dp_tamper_"))
    try:
        marker = "în afara programului"
        with Server(env=NO_KEY, dir_=base) as s:
            c = Client(s.url)
            c.post("/admin/setup", pin1="1111", pin2="1111")
            c.post("/admin/users/save", uid="ana", name="Ana R",
                   role="receptie", pin="3333")
            res.ok("после своих правок баннера нет",
                   marker not in c.get("/admin").body, "тревога на свою запись")
        # рестарт без изменений — тихо (свои записи запомнены отпечатком)
        with Server(env=NO_KEY, dir_=base) as s:
            c = Client(s.url).login("1111")
            res.ok("рестарт после своих правок тих",
                   marker not in c.get("/admin").body,
                   "ложная тревога после рестарта")
        # подмена файла руками между запусками
        p = base / "auth.json"
        p.write_text(p.read_text(encoding="utf-8") + " ", encoding="utf-8")
        with Server(env=NO_KEY, dir_=base) as s:
            c = Client(s.url).login("1111")
            body = c.get("/admin").body
            res.ok("директор видит предупреждение о подмене",
                   marker in body and "modificat" in body, "баннера нет")
            res.ok("событие попало в ленту аналитики",
                   "auth.json" in c.get("/admin/stats").body,
                   "в ленте нет следа")
            a = Client(s.url)
            a.post("/admin/login", password="3333", next="/admin")
            res.ok("регистратуре баннер не показывается",
                   marker not in a.get("/admin").body,
                   "страшилка без кнопки действия")
            r = a.post("/admin/security/ack")
            res.ok("погасить может только директор",
                   r.status == 303 and "no_access" in r.location,
                   f"location {r.location!r}")
            c.post("/admin/security/ack")
            res.ok("после подтверждения баннер снят",
                   marker not in c.get("/admin").body, "баннер остался")
        with Server(env=NO_KEY, dir_=base) as s:
            c = Client(s.url).login("1111")
            res.ok("подтверждение переживает рестарт",
                   marker not in c.get("/admin").body,
                   "погашенная тревога вернулась")
        # удаление файла — наш же путь «забыл PIN», но теперь он оставляет след
        p.unlink()
        with Server(env=NO_KEY, dir_=base) as s:
            c = Client(s.url)
            res.ok("без файла — снова экран установки",
                   "/admin/setup" in c.get("/admin").location, "не увёл на setup")
            c.post("/admin/setup", pin1="2222", pin2="2222")
            body = c.get("/admin").body
            res.ok("сброс через удаление файла виден",
                   marker in body and "șters" in body, "тихий сброс остался тихим")
    finally:
        shutil.rmtree(base, ignore_errors=True)


def suite_change(res: Result) -> None:
    with Server(env=NO_KEY) as s:
        c = Client(s.url)
        c.post("/admin/setup", pin1="4321", pin2="4321")
        key_before = _rec(s)["cookie_key"]

        r = c.post("/admin/pin/change", old_pin="9999", new1="5678", new2="5678")
        res.check("смена по неверному старому PIN отбита", r.msg, "bad_pin")
        r = c.post("/admin/pin/change", old_pin="4321", new1="5678", new2="5678")
        res.check("смена по верному PIN принята", r.msg, "ok_pin")
        res.ok("подпись сессии обновлена",
               _rec(s)["cookie_key"] != key_before,
               "чужие открытые вкладки пережили смену PIN")

        old = Client(s.url)
        old.post("/admin/login", password="4321", next="/admin")
        res.ok("старый PIN больше не пускает", old.get("/admin").status == 303,
               "старый PIN всё ещё работает")
        new = Client(s.url)
        new.post("/admin/login", password="5678", next="/admin")
        res.ok("новый PIN пускает", new.get("/admin").status == 200,
               "не пустил по новому PIN")

        # Блокировка на форме смены обязана говорить о блокировке. «PIN-ul vechi
        # e greșit» здесь — вранья того же рода, что и погашенный бот: человек
        # начинает перебирать заведомо ВЕРНЫЙ PIN и множит неудачи.
        burn = Client(s.url)
        for _ in range(5):
            burn.post("/admin/login", password="1111", next="/admin")
        r = new.post("/admin/pin/change", old_pin="5678", new1="4321", new2="4321")
        res.check("во время блокировки форма смены не врёт про старый PIN",
                  r.msg, "lock_pin")


def suite_secret(res: Result) -> None:
    """Шифрование токена бота. Сервер тут не нужен — важен сам модуль, и
    прежде всего то, что он отличает «не расшифровалось» от «пусто»."""
    sys.path.insert(0, str(BOT))
    from app import dpapi

    if not dpapi.available():
        res.ok("DPAPI доступен", False, "не Windows — проверки неприменимы")
        return
    tok = "123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw"
    enc = dpapi.protect(tok)
    res.ok("шифротекст помечен префиксом", (enc or "").startswith(dpapi.PREFIX),
           f"получено {enc!r}")
    res.ok("токен в шифротексте не читается", tok not in (enc or ""),
           "токен виден как есть")
    res.check("расшифровка возвращает исходный токен", dpapi.unprotect(enc), tok)
    res.check("открытый токен прежней установки читается как есть",
              dpapi.unprotect(tok), tok)
    res.check("пусто остаётся пустым", dpapi.unprotect(""), "")
    res.ok("шифротекст с чужой машины даёт None, а не пустую строку",
           dpapi.unprotect(dpapi.PREFIX + "bm90LW1pbmU=") is None,
           "«чужая машина» неотличима от «токена нет» — клиника пойдёт "
           "чинить настройки бота, которые в порядке")


def suite_env_token(res: Result) -> None:
    """Жизнь токена в dental.env: то, что исполняется при КАЖДОМ старте у
    клиники. Проверяется именно функция из dpapi, а не её пересказ: код в теле
    desktop.py вызвать из теста нельзя, и раньше эта часть не проверялась никак.
    """
    sys.path.insert(0, str(BOT))
    from app import dpapi

    if not dpapi.available():
        res.ok("DPAPI доступен", False, "не Windows — проверки неприменимы")
        return

    tok = "123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw"
    keep = {k: os.environ.get(k)
            for k in (dpapi.TOKEN_KEY, dpapi.UNREADABLE_FLAG)}
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="dp_env_"))
    env_path = tmp / "dental.env"
    try:
        # так выглядит уже установленная клиника: токен вписан открытым
        env_path.write_text(f"# Token botului Telegram:\nTELEGRAM_TOKEN={tok}\n",
                            encoding="utf-8")
        os.environ[dpapi.TOKEN_KEY] = tok
        dpapi.unlock_env_token(env_path)
        on_disk = env_path.read_text(encoding="utf-8")
        res.check("бот получает открытый токен", os.environ[dpapi.TOKEN_KEY], tok)
        res.ok("на диске токен больше не читается", tok not in on_disk,
               "открытый токен остался в файле")
        res.ok("комментарии клиники в файле уцелели", "@BotFather" in on_disk
               or on_disk.startswith("#"), "файл переписан без комментариев")

        # следующий старт: в окружение попадает уже шифротекст из файла
        os.environ[dpapi.TOKEN_KEY] = dict(
            ln.split("=", 1) for ln in on_disk.splitlines()
            if "=" in ln and not ln.startswith("#"))["TELEGRAM_TOKEN"]
        dpapi.unlock_env_token(env_path)
        res.check("повторный старт снова отдаёт открытый токен",
                  os.environ[dpapi.TOKEN_KEY], tok)
        res.ok("флаг нечитаемости не выставлен",
               dpapi.UNREADABLE_FLAG not in os.environ, "ложная тревога")

        # переустановка Windows / другой компьютер
        os.environ[dpapi.TOKEN_KEY] = dpapi.PREFIX + "bm90LW1pbmU="
        dpapi.unlock_env_token(env_path)
        res.check("чужой шифротекст гасит бота", os.environ[dpapi.TOKEN_KEY], "")
        res.check("и поднимает флаг, чтобы интерфейс объяснил причину",
                  os.environ.get(dpapi.UNREADABLE_FLAG), "1")
    finally:
        for k, v in keep.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(tmp, ignore_errors=True)
