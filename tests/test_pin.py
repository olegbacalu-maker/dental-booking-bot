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
import sys
import tempfile
import time

from harness import PIN as KEY  # ключ облачной ветки (ADMIN_KEY харнесса)
from harness import BOT, Client, Result, Server, _rmtree_settled, shell_model

NO_KEY = {"ADMIN_KEY": ""}          # без него издание уходит веткой ADMIN_KEY


def _v1_file(server: Server, pin: str) -> None:
    """Положить auth.json СТАРОГО формата — так выглядят установленные клиники."""
    salt = "0123456789abcdef"
    (server.dir / "auth.json").write_text(json.dumps(
        {"salt": salt,
         "hash": hashlib.sha256(f"{salt}:{pin}".encode()).hexdigest()}),
        encoding="utf-8")


def _feed(c: Client) -> str:
    """Лента «Activitate recentă» экрана статистики — тексты из /api/stats
    (старая страница, где её читали до 12.10, снята)."""
    r = c.get("/api/stats")
    if r.status != 200:
        return ""
    return "\n".join(a["text"] for a in json.loads(r.body)["data"]["activity"])


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

        # ⚠️ Экраны установки PIN и входа panel.css не подключают по замыслу,
        # значит объявление шрифта у них своё — заполнитель __FONTS__ в <style>
        # (layout.standalone подставляет туда текст fonts.css). Забытый
        # заполнитель ничем себя не выдаёт: страница цела, просто нарисована
        # системным шрифтом — и это первое, что видит клиника.
        # ⭐ Вход проверяется ПОСЛЕ установки: без PIN и без ADMIN_KEY
        # /admin/login отвечает редиректом, и проверка смотрела бы в пустоту.
        setup_page = c.get("/admin/setup").body
        res.ok("экран установки PIN несёт объявление шрифта",
               "@font-face{" in setup_page and "__FONTS__" not in setup_page,
               "нет @font-face — страница уедет на системный шрифт")

        c.post("/admin/setup", pin1="4321", pin2="4321")
        login_page = c.get("/admin/login")
        res.ok("экран входа несёт объявление шрифта",
               login_page.status == 200 and "@font-face{" in login_page.body
               and "__FONTS__" not in login_page.body,
               f"код {login_page.status}, @font-face нет — вход уедет на "
               f"системный шрифт")
        rec = _rec(s)
        u = (rec.get("users") or [{}])[0]
        res.check("PIN пишется в формате v2", rec.get("v"), 2)
        res.check("хеш считается pbkdf2", u.get("kdf"), "pbkdf2-sha256")
        res.ok("итераций не меньше 600 000", int(u.get("iter", 0)) >= 600_000,
               f"iter={u.get('iter')!r}")
        # ⭐ 08-08: проверка была флаки — «4321» искался подстрокой во ВСЁМ
        # json, а случайная соль/хеш в base64 изредка содержит эти цифры
        # (поймано на живом прогоне). Случайные блобы вычитаем, остальное —
        # любое поле с PIN открытым текстом — по-прежнему ловится.
        blob = json.dumps(rec)
        for rand in [rec.get("cookie_key")] + [
                x for usr in (rec.get("users") or [])
                for x in (usr.get("salt"), usr.get("hash"), usr.get("sid"))]:
            if isinstance(rand, str) and rand:
                blob = blob.replace(rand, "")
        res.ok("сам PIN в файл не попадает", "4321" not in blob,
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
        lock_page = c.get("/admin/login?err=lock&s=30").body
        res.ok("экран объясняет блокировку, а не врёт про неверный PIN",
               "încercări" in lock_page, "нет текста о превышении попыток")
        # вторая фраза — выход: после смены пароля коллегой человек попадает
        # сюда с «верным» по его памяти PIN-ом и не знает, что делать (08-13)
        res.ok("экран блокировки подсказывает про директора",
               "director" in lock_page,
               "запертый не знает, что PIN может сменить директор")

        # всплеск подбора обязан остаться в ленте ПОСЛЕ удачного входа: сам
        # счётчик обнуляется, и без записи серия исчезла бы бесследно (08-13).
        # Блокировку снимаем нашим же файлом состояния — ждать 30 с незачем.
        (s.dir / "auth_fail.json").write_text('{"fails": 0, "until": 0}',
                                              encoding="utf-8")
        ok = Client(s.url)
        ok.post("/admin/login", password="4321", next="/admin")
        res.ok("серия неудач записана в ленту клиники",
               "încercări greșite la intrare" in _feed(ok),
               "подбор PIN у стойки не оставил следа")


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
                  boss.post_json("/api/settings/users", {"uid": "d2", "name": "Dr. Liviu",
                                                        "role": "medic", "doctor_id": "d2",
                                                        "pin": "2222"}).msg, "ok_user")
        res.check("регистратура заводится",
                  boss.post_json("/api/settings/users", {"uid": "ana", "name": "Ana R",
                                                        "role": "receptie", "pin": "3333"}).msg, "ok_user")

        # вход возможен по ОДНОМУ паролю, значит одинаковых быть не должно —
        # иначе журнал доступа однажды назовёт не того человека
        res.check("чужой пароль повторить нельзя",
                  boss.post_json("/api/settings/users", {"uid": "x1", "name": "X",
                                                        "role": "medic", "pin": "2222"}).msg, "dup_user")
        res.check("8-значный PIN сотрудника принимается",
                  boss.post_json("/api/settings/users", {"uid": "opt8", "name": "Opt C",
                                                        "role": "receptie",
                                                        "pin": "44445555"}).msg, "ok_user")
        res.check("9 цифр — отбой",
                  boss.post_json("/api/settings/users", {"uid": "n9", "name": "N",
                                                        "role": "receptie",
                                                        "pin": "444455556"}).msg, "bad_user")
        res.check("id только из безопасных символов",
                  boss.post_json("/api/settings/users", {"uid": "Ана!", "name": "X",
                                                        "role": "medic", "pin": "4444"}).msg, "bad_user")
        res.check("новому нужен пароль",
                  boss.post_json("/api/settings/users", {"uid": "x2", "name": "X",
                                                        "role": "medic"}).msg, "bad_user")
        # ⭐ последний директор запер бы настройки НАВСЕГДА: вернуть право некому
        res.check("последний директор не снимает с себя роль",
                  boss.post_json("/api/settings/users", {"uid": "clinic", "name": "D",
                                                        "role": "medic"}).msg, "last_dir")
        res.check("и не удаляет сам себя",
                  boss.post_json("/api/settings/users/clinic/delete", {}).msg, "self_user")

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
        # /admin/casa — печатный отчёт кассы: это ВЫРУЧКА клиники, дверь та же,
        # что у статистики. Долг отдельного пациента врач по-прежнему видит —
        # он в фише и в списке, и это операционка, а не деньги клиники
        for path in ("/admin/stats", "/admin/casa", "/admin/settings",
                     "/admin/settings/security", "/admin/settings/system",
                     "/admin/settings/faq", "/admin/medici",
                     "/admin/doctor-card/d2"):
            r = med.get(path)
            res.ok(f"врачу закрыто {path}",
                   r.status == 303 and "no_access" in r.location,
                   f"код {r.status}, location {r.location!r}")
        # ⚠️ POST закрыт отдельно: форму отправляют не только из меню
        for path, kw in (("/admin/backup/export", {"parola": "x"}),):
            r = med.post(path, **kw)
            res.ok(f"врачу закрыт POST {path}",
                   r.status == 303 and "no_access" in r.location,
                   f"код {r.status}, location {r.location!r}")
        # настройки, учётки и врачей сохраняет только API (формы сняты 12.10)
        for path, body in (("/api/doctors/d2/photo/delete", {}),
                           ("/api/doctors/d2", {"name": "Dr. Hack"}),
                           ("/api/settings/clinic", {"name": "Hack"}),
                           ("/api/settings/users", {"uid": "z1", "name": "Z",
                                                    "role": "director", "pin": "9999"})):
            r = med.post_json(path, body)
            res.ok(f"врачу закрыт POST {path}",
                   r.status == 403 and r.msg == "no_access", f"{r!r}")
        res.ok("врач не смог завести себе директора",
               all(u.get("id") != "z1" for u in _rec(s)["users"]),
               "чужой POST создал учётку")

        page = med.get("/admin").body
        res.ok("в меню врача нет денег и настроек",
               "/admin/stats" not in page and "/admin/settings" not in page,
               "закрытый раздел остался в меню")
        res.ok("в меню врача нет раздела Medici",
               "/admin/medici" not in page, "закрытый каталог остался в меню")
        # день врача — React (13.10): ссылки на фишу врача он не рисует вовсе,
        # и в его данных её тоже нет — сторож на будущее поле со ссылкой
        res.ok("день врача не зовёт в закрытую фишу",
               "doctor-card" not in med.get("/api/schedule/day?doctor=d2").body,
               "ссылка на фишу врача видна врачу — поведёт в отказ")

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
        key_before = _rec(s)["cookie_key"]
        boss.post_json("/api/settings/users", {"uid": "d2", "name": "Dr. Liviu",
                                              "role": "medic", "doctor_id": "d2",
                                              "pin": "5555"})
        # ⭐ замок на политику из карты: правка ЧУЖОЙ учётки не вращает ключ
        # подписи — иначе смена пароля врачу разлогинила бы всю клинику
        res.ok("правка чужой учётки не вращает ключ подписи",
               _rec(s)["cookie_key"] == key_before,
               "cookie_key сменился — правка одной учётки закрыла сессии всех")
        res.ok("после смены пароля старая сессия врача закрыта",
               med.get("/admin").status == 303, "старая кука ещё пускает")
        res.ok("а директора — нет", boss.get("/admin").status == 200,
               "правка чужой учётки выкинула директора")
        med2 = Client(s.url)
        med2.post("/admin/login", password="5555", next="/admin")
        res.ok("новый пароль пускает", med2.get("/admin").status == 200, "не пустило")
        boss.post_json("/api/settings/users/d2/delete", {})
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
        r = a.post_json("/api/patients", {"name": "Pacient Jurnal", "phone": "069000111"})
        pid = json.loads(r.body)["data"]["id"]
        card = json.loads(a.get(f"/api/patients/{pid}").body)["data"]
        res.ok("в летописи стоит имя вошедшего",
               "Ana R" in [x["who"] for x in card["activity"]["items"]],
               "событие подписано каналом, а не человеком")

        # деньги: рецепция ПРИНИМАЕТ платёж (она их физически берёт), но не
        # удаляет и не видит сводных сумм — это директорское
        res.check("рецепция записывает платёж",
                  a.post_json(f"/api/patients/{pid}/payments", {"amount": "200",
                                                               "method": "numerar"}).msg, "ok_pay")
        fin = json.loads(a.get(f"/api/patients/{pid}").body)["data"]["finance"]
        res.check("рецепция видит платёж и аванс на фише",
                  ([p_["amount"] for p_ in fin["payments"]], fin["sold"]),
                  ([200], {"kind": "plus", "amount": 200}))
        res.check("удалять платёж рецепции не предлагается (право — директорское)",
                  fin["can_delete"], False)
        r = a.post_json(f"/api/patients/{pid}/payments/1/delete", {})
        res.ok("удаление платежа рецепции запрещено",
               r.status == 403 and r.msg == "no_access", f"{r!r}")


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
            c.post_json("/api/settings/users", {"uid": "ana", "name": "Ana R",
                                               "role": "receptie", "pin": "3333"})
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
                   "auth.json" in _feed(c),
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
        _rmtree_settled(base)


def suite_broken(res: Result) -> None:
    """Битый auth.json ≠ «PIN не установлен».

    Усечённый обрывом записи файл раньше был неотличим от отсутствующего:
    _pin_rec() давал None, и программа предлагала ПЕРВИЧНУЮ установку PIN
    поверх живых учёток — любой за компьютером становился единственным
    директором. Стережётся: setup закрыт, вход объясняет беду по-румынски,
    и сам файл ни разу не переписан (учётки восстановимы только из копии).
    """
    s = Server(env=NO_KEY)
    # так выглядит auth.json после обрыва питания посреди записи
    broken = '{"v": 2, "cookie_key": "abc", "users": [{"id": "cl'
    (s.dir / "auth.json").write_text(broken, encoding="utf-8")
    with s:
        c = Client(s.url)
        r = c.get("/admin")
        res.ok("битый файл не ведёт на первичную установку",
               r.status == 303 and "/admin/setup" not in r.location,
               f"код {r.status}, location {r.location!r} — установка поверх "
               f"живых учёток")
        res.ok("экран установки PIN закрыт",
               c.get("/admin/setup").status == 303,
               "setup отдал страницу — новый PIN сотрёт все учётки")
        c.post("/admin/setup", pin1="9999", pin2="9999")
        res.check("POST мимо экрана файл не переписывает",
                  (s.dir / "auth.json").read_text(encoding="utf-8"), broken)
        page = c.get("/admin/login")
        res.ok("вход объясняет, что файл повреждён",
               page.status == 200 and "deteriorat" in page.body,
               f"код {page.status}, на входе нет слова о битом файле")
        res.ok("и говорит, откуда восстановить",
               "auth.json" in page.body and "rezerv" in page.body,
               "нет подсказки про копию — клиника не знает, что делать")
        r = c.post("/admin/login", password="9999", next="/admin")
        res.ok("форма входа не врёт про неверный PIN",
               "err=broken" in r.location, f"location {r.location!r}")
        res.check("и после попытки входа файл цел",
                  (s.dir / "auth.json").read_text(encoding="utf-8"), broken)


def suite_atomic(res: Result) -> None:
    """auth.json пишется атомарно: обрыв посреди записи (питание, убитый
    процесс) не должен оставлять усечённый файл. Сервер не нужен — проверяется
    сам модуль: «обрыв» имитируется прямой записью, оборванной на середине."""
    sys.path.insert(0, str(BOT))
    from app.core import auth

    tmp_dir = pathlib.Path(tempfile.mkdtemp(prefix="dp_auth_"))
    p = tmp_dir / "auth.json"
    orig_path, orig_write = auth._auth_path, pathlib.Path.write_text
    try:
        auth._auth_path = lambda: p
        auth._save_users([{"id": "clinic", "role": "director", "kdf": auth.KDF,
                           "iter": 1, "salt": "s", "hash": "h", "sid": "x"}],
                         rotate=True)
        before = json.loads(p.read_text(encoding="utf-8"))
        res.check("файл записан и читается", before.get("v"), 2)

        def cut(self, data, *a, **kw):
            """Обрыв питания: на диск доезжает половина, дальше — тьма."""
            with open(self, "w", encoding="utf-8") as f:
                f.write(data[: len(data) // 2])
            raise OSError("simulated power loss")

        pathlib.Path.write_text = cut
        try:
            auth._save_users(before["users"] + [{"id": "ana"}], rotate=False)
        except OSError:
            pass
        finally:
            pathlib.Path.write_text = orig_write
        try:
            after = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            after = None
        res.ok("обрыв записи не оставляет битый файл", after is not None,
               "auth.json усечён — при следующем старте все учётки пропадут")
        res.ok("в файле либо старое, либо новое содержимое целиком",
               after is not None and len(after.get("users") or []) in (1, 2),
               f"получено {after!r}")
    finally:
        auth._auth_path = orig_path
        pathlib.Path.write_text = orig_write
        _rmtree_settled(tmp_dir)


def suite_change(res: Result) -> None:
    with Server(env=NO_KEY) as s:
        c = Client(s.url)
        c.post("/admin/setup", pin1="4321", pin2="4321")
        key_before = _rec(s)["cookie_key"]

        r = c.post_json("/api/settings/pin", {"old_pin": "9999", "new1": "5678", "new2": "5678"})
        res.check("смена по неверному старому PIN отбита", r.msg, "bad_pin")
        r = c.post_json("/api/settings/pin", {"old_pin": "4321", "new1": "5678", "new2": "5678"})
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

        # --- журнал входов (08-13): вход перестал быть бесследным ---
        res.ok("вход записан в ленту клиники",
               "A intrat în registru" in _feed(new),
               "входа нет в «Activitate recentă» — «кто входил вчера вечером» "
               "снова без ответа")
        sec = json.loads(new.get("/api/settings/security").body)["data"]["users"]
        res.ok("у сотрудника виден последний вход",
               any(u.get("last_login") for u in sec),
               "последнего входа нет в данных «Securitate»")

        # --- потолок длины поднят до 8 (08-13, LAN) ---
        r = new.post_json("/api/settings/pin", {"old_pin": "5678", "new1": "123456789",
                                               "new2": "123456789"})
        res.check("9 цифр не принимаются", r.msg, "bad_pin")
        r = new.post_json("/api/settings/pin", {"old_pin": "5678", "new1": "87654321",
                                               "new2": "87654321"})
        res.check("8 цифр принимаются", r.msg, "ok_pin")
        eight = Client(s.url)
        eight.post("/admin/login", password="87654321", next="/admin")
        res.ok("вход по 8-значному PIN работает",
               eight.get("/admin").status == 200, "8 цифр не пускают")
        res.ok("форма входа не режет восьмую цифру на вводе",
               "maxlength='8'" in eight.get("/admin/login").body,
               "maxlength остался 6 — восьмая цифра молча не наберётся")
        # дальше суита живёт с PIN 87654321 — вернуть 5678 для читаемости низа
        new = eight
        new.post_json("/api/settings/pin", {"old_pin": "87654321", "new1": "5678",
                                           "new2": "5678"})
        new = Client(s.url)
        new.post("/admin/login", password="5678", next="/admin")

        # Блокировка на форме смены обязана говорить о блокировке. «PIN-ul vechi
        # e greșit» здесь — вранья того же рода, что и погашенный бот: человек
        # начинает перебирать заведомо ВЕРНЫЙ PIN и множит неудачи.
        burn = Client(s.url)
        for _ in range(5):
            burn.post("/admin/login", password="1111", next="/admin")
        r = new.post_json("/api/settings/pin", {"old_pin": "5678", "new1": "4321", "new2": "4321"})
        res.check("во время блокировки форма смены не врёт про старый PIN",
                  r.msg, "lock_pin")


def suite_api_login(res: Result) -> None:
    """JSON-дверь смены человека (B4.4, 16.10): тот же оракул, что у формы.

    Клиент меняет человека без перезагрузки: `POST /api/auth/logout` снимает
    куку, `POST /api/auth/login` ставит куку вошедшего. Стережётся, что это
    ОДНА дверь с формой, а не вторая: те же отказы (битый файл, блокировка,
    неверный PIN), тот же счётчик (неудачи формы и JSON складываются), тот же
    след в ленте, тот же переезд v1→v2 с отпечатком, та же сверка Origin.
    ⛔ И что 401 здесь не бывает: на него клиент уходит документом на
    страницу входа, а экран PIN обязан показать отказ на месте.
    """
    login, logout = "/api/auth/login", "/api/auth/logout"
    base = pathlib.Path(tempfile.mkdtemp(prefix="dp_apilogin_"))
    try:
        s = Server(env=NO_KEY, dir_=base)
        _v1_file(s, "4321")
        with s:
            c = Client(s.url)
            r = c.post_json(login, {"pin": "1111"})
            res.ok("неверный PIN — 422 login_bad, а не 401",
                   r.status == 422 and r.msg == "login_bad", f"{r!r} {r.body[:120]}")
            res.check("отказ называет поле", json.loads(r.body).get("field"), "pin")
            res.ok("текст отказа — слово формы входа",
                   json.loads(r.body).get("text") == "PIN greșit", r.body[:120])
            res.ok("и журнал закрыт", c.get("/admin").status == 303,
                   "пустил по неверному PIN")
            res.ok("неудача файл v1 не трогает", "v" not in _rec(s),
                   "файл переписан при НЕверном PIN")

            r = c.post_json(login, {"pin": "4321"})
            sc = r.header("Set-Cookie")
            res.ok("верный PIN — 200 с кукой вошедшего",
                   r.status == 200 and "admin_auth=" in sc, f"{r!r} cookie {sc[:60]!r}")
            res.check("ответ называет вошедшего", json.loads(r.body)["data"]["uid"], "clinic")
            res.ok("журнал открыт по куке JSON-входа", c.get("/admin").status == 200,
                   "кука JSON-входа не пускает")
            # ⚠️ как у формы: переезд v1→v2 меняет ключ подписи, и кука,
            # выданная ДО него, отвалилась бы на первой же странице
            res.check("файл переехал в v2 тем же оракулом", _rec(s).get("v"), 2)
            model = shell_model(c.get("/admin").body)
            res.ok("оболочка называет дверь: вход по PIN, потолок из констант",
                   model.get("entry", {}).get("pin") is True
                   and model["entry"].get("pin_max") == 8, f"{model.get('entry')!r}")
            res.ok("фон экрана PIN едет строкой сервера",
                   "dp-bg" in model["entry"].get("backdrop", ""), "нет фона в модели")
            res.ok("логотип карточки входа — в модели", "logo" in model.get("clinic", {}),
                   f"{model.get('clinic')!r}")

            r = c.post_json(logout, {})
            sc = r.header("Set-Cookie")
            res.ok("выход — 200, кука снята",
                   r.status == 200 and "admin_auth=" in sc
                   and ("Max-Age=0" in sc or 'admin_auth=""' in sc), f"{r!r} {sc[:80]!r}")
            res.ok("после выхода журнал закрыт", c.get("/admin").status == 303,
                   "кука пережила выход")
            res.check("выход без куки — 401 (api_guard)", c.post_json(logout, {}).status, 401)

            # явный id: сверка только с ним, без учёта регистра (телефон ставит
            # заглавную) — как у формы
            c.post_json(login, {"pin": "4321"})
            res.check("регистратура заводится",
                      c.post_json("/api/settings/users", {"uid": "ana", "name": "Ana R",
                                                         "role": "receptie", "pin": "3333"}).msg,
                      "ok_user")
            a = Client(s.url)
            r = a.post_json(login, {"pin": "3333", "uid": "clinic"})
            res.ok("свой PIN с чужим id — отказ", r.status == 422 and r.msg == "login_bad", f"{r!r}")
            r = a.post_json(login, {"pin": "3333", "uid": "ANA"})
            res.ok("id — без учёта регистра",
                   r.status == 200 and json.loads(r.body)["data"]["name"] == "Ana R",
                   f"{r!r} {r.body[:120]}")
            res.ok("регистратура вошла в журнал", a.get("/admin").status == 200,
                   "кука регистратуры не пускает")

            # CSRF: чужой сайт в браузере клиники — ни проверки PIN, ни счётчика
            # счётчик устройства «local» (с 17.10 стойка считается отдельно)
            fails = lambda: json.loads((s.dir / "auth_fail.json").read_text(encoding="utf-8")).get("peers", {}).get("local", {}).get("fails", 0)  # noqa: E731
            r = Client(s.url).post_json(login, {"pin": "4321"},
                                        headers={"Origin": "http://atacator.example"})
            res.check("чужой Origin — 403", r.status, 403)
            res.check("и счётчик неудач не тронут", fails(), 0)
            r = Client(s.url).post_json(login, {"pin": "1111"},
                                        headers={"Origin": f"http://127.0.0.1:{s.port}"})
            res.ok("свой Origin (окно программы) проходит до оракула",
                   r.status == 422 and fails() == 1, f"{r!r} fails={fails()}")

            # один счётчик на обе двери: неудачи формы и JSON складываются
            bad = Client(s.url)
            for _ in range(3):
                bad.post("/admin/login", password="1111", next="/admin")
            r = bad.post_json(login, {"pin": "1111"})
            res.ok("пятая неудача (через JSON) запирает: 423 lock_pin с секундами",
                   r.status == 423 and r.msg == "lock_pin"
                   and json.loads(r.body).get("data", {}).get("left", 0) > 0,
                   f"{r!r} {r.body[:120]}")
            r = bad.post_json(login, {"pin": "4321"})
            res.ok("верный PIN при блокировке — 423, а не 200",
                   r.status == 423 and r.msg == "lock_pin", f"{r!r}")
            res.ok("форма заперта той же лестницей",
                   "err=lock" in bad.post("/admin/login", password="4321", next="/admin").location,
                   "у формы свой счётчик — лестница разошлась")
            (s.dir / "auth_fail.json").write_text('{"fails": 0, "until": 0}', encoding="utf-8")
            ok = Client(s.url)
            ok.post_json(login, {"pin": "4321"})
            feed = _feed(ok)
            res.ok("вход JSON-ом и всплеск подбора — в ленте клиники",
                   "A intrat în registru" in feed and "încercări greșite la intrare" in feed,
                   "JSON-дверь не оставляет следа")
        # рестарт: свой переезд v1→v2 через JSON-вход запомнен отпечатком
        with Server(env=NO_KEY, dir_=base) as s:
            c = Client(s.url)
            c.post_json(login, {"pin": "4321"})
            res.ok("переезд файла через JSON-вход — без ложной тревоги при рестарте",
                   "în afara programului" not in c.get("/admin").body,
                   "ложный «взлом» после JSON-входа")
    finally:
        _rmtree_settled(base)

    # битый auth.json: отказ объясняет беду теми же словами, что и форма,
    # файл не тронут
    s = Server(env=NO_KEY)
    broken = '{"v": 2, "cookie_key": "abc", "users": [{"id": "cl'
    (s.dir / "auth.json").write_text(broken, encoding="utf-8")
    with s:
        r = Client(s.url).post_json(login, {"pin": "9999"})
        res.ok("битый файл — 409 auth_broken",
               r.status == 409 and r.msg == "auth_broken"
               and "deteriorat" in json.loads(r.body).get("text", ""), f"{r!r} {r.body[:120]}")
        res.check("файл цел", (s.dir / "auth.json").read_text(encoding="utf-8"), broken)
        res.ok("форма входа — теми же словами",
               "deteriorat" in Client(s.url).get("/admin/login").body,
               "страница входа разошлась со словарём")

    # облачная ветка (ADMIN_KEY): дверь работает ключом, а в оболочке сказано,
    # что смены человека без перезагрузки здесь нет (демо отдаёт слот на
    # /admin/logout)
    with Server() as s:
        c = Client(s.url)
        res.check("чужой ключ — 422", c.post_json(login, {"pin": "nu"}).status, 422)
        r = c.post_json(login, {"pin": KEY})
        res.ok("ключ облака пускает", r.status == 200 and c.get("/admin").status == 200, f"{r!r}")
        res.ok("оболочка: вход не по PIN-файлу",
               shell_model(c.get("/admin").body).get("entry", {}).get("pin") is False,
               "облако объявило вход по PIN")


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
        _rmtree_settled(tmp)


# ---------- 17.10: сетевой режим — длина PIN, срок и отзыв сессии ----------

def _hash_user(uid: str, name: str, role: str, pin: str) -> dict:
    """Запись учётки в формате файла — как её писала программа ДО 17.10
    (без `plen`); pbkdf2 считается так же, как в `auth._derive`."""
    salt = "a" * 32
    return {"id": uid, "name": name, "role": role, "kdf": "pbkdf2-sha256",
            "iter": 600_000, "salt": salt, "sid": "0" * 16,
            "hash": hashlib.pbkdf2_hmac("sha256", pin.encode(), salt.encode(),
                                        600_000).hex()}


def suite_lan_pin(res: Result) -> None:
    """PIN не короче 6 цифр при включённом «Acces din rețea» (17.10).

    Правило — одно (`auth.pin_len_ok` через `pin_min()`), и его видят все три
    формы и экран установки. Существующие короткие PIN не ломаются: сеть не
    включается, пока у всех не ≥ 6 (`pin_readiness`), а длину записей до
    17.10 программа узнаёт при первом входе (`plen`).
    """
    LAN = {**NO_KEY, "DENTART_LAN": "1"}
    sec = "/api/settings/security"
    with Server(env=LAN) as s:
        c = Client(s.url)
        page = c.get("/admin/setup").body
        res.ok("экран установки при включённой сети просит 6–8 цифр",
               "6–8 cifre" in page and "4–8" not in page,
               "текст экрана не следует за состоянием сети")
        r = c.post("/admin/setup", pin1="4321", pin2="4321")
        res.ok("4 цифры при сети — отказ, файла нет",
               "err=1" in r.location and not (s.dir / "auth.json").exists(),
               f"location {r.location!r}")
        res.ok("отказ называет 6–8", "6–8 cifre" in c.get("/admin/setup?err=1").body,
               "в тексте отказа старый диапазон")
        r = c.post("/admin/setup", pin1="654321", pin2="654321")
        res.ok("6 цифр — принято", r.status == 303 and r.location.endswith("/admin"),
               f"{r!r}")
        res.check("длина PIN записана в учётку", _rec(s)["users"][0].get("plen"), 6)
        d = json.loads(c.get(sec).body)["data"]
        res.check("API учёток называет минимум 6", d["pin"]["min"], 6)
        r = c.post_json("/api/settings/users", {"uid": "ana", "name": "Ana R",
                                                "role": "receptie", "pin": "3333"})
        res.check("учётка с 4 цифрами при сети — bad_user", r.msg, "bad_user")
        r = c.post_json("/api/settings/pin", {"old_pin": "654321", "new1": "4321",
                                              "new2": "4321"})
        res.check("свой PIN на 4 цифры при сети — bad_pin", r.msg, "bad_pin")
        r = c.post_json("/api/settings/users", {"uid": "ana", "name": "Ana R",
                                                "role": "receptie", "pin": "333333"})
        res.check("6 цифр у учётки проходят", r.msg, "ok_user")
        bad = c.post_json("/api/settings/users", {"uid": "x", "name": "X",
                                                  "role": "medic", "pin": "1"})
        res.ok("отказы не называют диапазон числами (минимум зависит от сети)",
               "4–8" not in json.loads(bad.body).get("text", ""), bad.body[:160])

    with Server(env=NO_KEY) as s:
        c = Client(s.url)
        res.ok("без сети экран установки просит 4–8, как раньше",
               "4–8 cifre" in c.get("/admin/setup").body, "диапазон изменился без сети")
        c.post("/admin/setup", pin1="4321", pin2="4321")
        res.check("без сети 4 цифры принимаются", c.get("/admin").status, 200)
        res.check("и API учёток называет минимум 4",
                  json.loads(c.get(sec).body)["data"]["pin"]["min"], 4)

    # включение сети держат учётки: короткий PIN и неизвестная длина
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="dp_lanpin_"))
    env_path = tmp / "dental.env"
    env_path.write_text("TELEGRAM_TOKEN=\n", encoding="utf-8")
    try:
        s = Server(env={**NO_KEY, "DENTART_ENV_FILE": str(env_path)})
        _v1_file(s, "4321")
        with s:
            c = Client(s.url)
            c.post("/admin/login", password="4321", next="/admin")
            rec = _rec(s)
            res.check("вход доливает длину PIN в запись прошлой версии",
                      rec["users"][0].get("plen"), 4)
            # коллега, не входившая после обновления: длина неизвестна
            rec["users"].append(_hash_user("ana", "Ana R", "receptie", "777777"))
            (s.dir / "auth.json").write_text(json.dumps(rec), encoding="utf-8")
            d = json.loads(c.get("/api/settings/lan").body)["data"]
            res.check("короткий PIN назван", d["pins"]["short"], ["Director"])
            res.check("неизвестная длина названа отдельно", d["pins"]["unknown"], ["Ana R"])
            res.ok("кнопка включения закрыта, причина — прозой с именами",
                   d["pins"]["blocked"] is True and "Director" in d["blocks"]["pins"]
                   and "Ana R" in d["blocks"]["pins"] and "6 cifre" in d["blocks"]["pins"],
                   f"{d['pins']!r} {d['blocks']['pins'][:160]}")
            r = c.post_json("/api/settings/lan", {"mode": "on"})
            res.ok("включение — 409 lan_pins", r.status == 409 and r.msg == "lan_pins",
                   f"{r!r}")
            res.ok("dental.env не тронут",
                   "DENTART_LAN=1" not in env_path.read_text(encoding="utf-8"),
                   "сеть включилась вопреки отказу")
            res.ok("выключение не держится учётками",
                   c.post_json("/api/settings/lan", {"mode": "off"}).msg == "ok_set",
                   "mode=off отказан")

            # директор чинит за минуту: себе — смена, коллеге — новый PIN
            r = c.post_json("/api/settings/pin", {"old_pin": "4321", "new1": "654321",
                                                  "new2": "654321"})
            res.check("свой PIN сменён на 6", r.msg, "ok_pin")
            res.check("длина нового PIN записана",
                      next(u for u in _rec(s)["users"] if u["id"] == "clinic").get("plen"), 6)
            res.ok("ещё держит: коллега неизвестной длины",
                   c.post_json("/api/settings/lan", {"mode": "on"}).msg == "lan_pins",
                   "включилось с учёткой неизвестной длины")
            r = c.post_json("/api/settings/users", {"uid": "ana", "name": "Ana R",
                                                    "role": "receptie", "pin": "777777"})
            res.check("коллеге задан новый PIN", r.msg, "ok_user")
            d = json.loads(c.get("/api/settings/lan").body)["data"]
            res.ok("все готовы — блока нет, кнопка открыта",
                   d["pins"]["blocked"] is False and d["blocks"]["pins"] == ""
                   and not d["pins"]["short"] and not d["pins"]["unknown"], f"{d['pins']!r}")
            r = c.post_json("/api/settings/lan", {"mode": "on"})
            res.ok("теперь включается", r.status == 200 and r.msg == "ok_set", f"{r!r}")
            res.ok("dental.env получил флаг",
                   "DENTART_LAN=1" in env_path.read_text(encoding="utf-8"), "флага нет")
            res.check("минимум поднялся сразу, без перезапуска",
                      json.loads(c.get(sec).body)["data"]["pin"]["min"], 6)
            d = json.loads(c.get("/api/settings/lan").body)["data"]
            res.ok("включённая сеть без коротких PIN — предупреждения нет",
                   d["enabled"] is True and d["blocks"]["pins"] == "", f"{d['pins']!r}")
    finally:
        _rmtree_settled(tmp)


