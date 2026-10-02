"""Дымовой тест СОБРАННОЙ программы: страницы реально открываются.

    python tests\\smoke_exe.py http://127.0.0.1:8100 smoke1234 [wall|grace] [папка-данных]

Зачем отдельно от run_tests.py: тот поднимает сервер из исходников, а здесь
проверяется exe, где файлы лежат не там, где в репозитории. Ровно этот класс
поломок — потерянный `--add-data`, сбитый путь к static или к clinic.json —
из исходников не воспроизводится и виден только на собранном бинарнике.

Проверка `/health` этого не ловит: она отвечает без единого файла на диске.

Две фазы (02.10, ключ лицензии в сборке — `rsa_verify.KEYS`; Build-Installer
запускает ОДИН exe дважды на одной лаборатории):
  wall  — свежая установка: картотека пуста, файла нет → стена активации:
          каждый адрес журнала ведёт на /admin/license, запись отказывает 423
          `license_missing`, на странице активации — заявка на пробный и ни
          слова о файле. В конце тест заводит пациента ПРЯМО в dental.db:
          пустоту картотеки программа считает на старте, поэтому следующая
          фаза — перезапуск.
  grace — тот же exe на живой картотеке: стены нет, баннер льготы называет
          лицензию и срок (баннер бывает только при ключе — так проверяется,
          что ключ действительно внутри exe), и все страницы открываются.
Без фазы (ручной запуск против песочницы без ключей) — только страницы.
"""
import json
import pathlib
import sqlite3
import sys
from datetime import datetime, timezone

# ⛔ Консоль Windows живёт в cp1251, а названия проверок — румынские: «ț» в
# «consultație» ей не по зубам, и печать отчёта падала UnicodeEncodeError
# ПОСРЕДИ прогона. Сборка при этом отказывалась класть тег, то есть дымовой
# тест не пускал ни один релиз — а выглядело как «сборка сломалась». Та же
# мера, что в run_tests.py: плохой символ дешевле потерять, чем весь отчёт.
import urllib.error
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from harness import Client  # noqa: E402

WALL, GRACE, PAGES = "wall", "grace", "pages"


def main(base: str, password: str, phase: str = PAGES, data_dir: str = "") -> int:
    bad: list[str] = []
    total = 0

    def check(label: str, cond: bool, detail: str = "") -> None:
        nonlocal total
        total += 1
        print(f"   {'OK  ' if cond else 'FAIL'} {label}" + (f" — {detail}" if not cond else ""))
        if not cond:
            bad.append(label)

    c = Client(base)

    r = c.get("/health")
    ver = json.loads(r.body).get("version", "") if r.status == 200 else ""
    check("/health отвечает", bool(ver), f"код {r.status}")

    _static(c, check)
    if phase == WALL:
        _wall(c, check, password, data_dir)
    else:
        _pages(c, check, password, grace=(phase == GRACE))

    tag = f" [{phase}]" if phase != PAGES else ""
    print(f"\n   дымовой тест{tag}: {'ПРОВАЛ' if bad else 'OK'} ({len(bad)} из "
          f"{total} проверок красные)" if bad
          else f"\n   дымовой тест собранной программы{tag}: OK, версия {ver}")
    return 1 if bad else 0


def _static(c: Client, check) -> None:
    """Файлы, вшитые в сборку: не зависят ни от входа, ни от лицензии."""
    # страница пациента-бота: живёт в static/index.html внутри бандла
    r = c.get("/")
    check("главная (static/index.html) отдаётся",
          r.status == 200 and len(r.body) > 500, f"код {r.status}, {len(r.body)} б")

    r = c.get("/favicon.ico")
    check("значок отдаётся", r.status == 200 and len(r.body) > 50, f"код {r.status}")

    # Значок приложения РИСУЕТСЯ через PIL, а тот попадает в сборку только
    # потому, что его просит загрузка снимков в фише. Пропади он — телефон
    # получит 500 на иконку и поставит на домашний экран серый квадрат;
    # ни одна страница об этом не скажет, и прогон по исходникам тоже.
    r = c.get("/icon-192.png")
    check("значок приложения рисуется в сборке",
          r.status == 200 and r.raw[:8] == b"\x89PNG\r\n\x1a\n",
          f"код {r.status}, первые байты {r.raw[:8]!r}")
    r = c.get("/manifest.webmanifest")
    check("манифест отдаётся из сборки",
          r.status == 200 and '"standalone"' in r.body, f"код {r.status}")

    # Оформление — отдельный файл внутри бандла. Если он не попал в сборку,
    # страницы откроются «голыми», а /health об этом не скажет ни слова.
    r = c.get("/static/css/panel.css")
    check("таблица стилей отдаётся из сборки",
          r.status == 200 and ".banner" in r.body and len(r.body) > 10000,
          f"код {r.status}, {len(r.body)} б")
    check("стили кешируются у клиники",
          "immutable" in r.header("Cache-Control"),
          f"Cache-Control: {r.header('Cache-Control')!r}")
    r = c.get("/static/js/panel.js")
    check("общий скрипт отдаётся из сборки",
          r.status == 200 and "setInterval" in r.body,
          f"код {r.status}, {len(r.body)} б")

    # Бандл React-клиента (DentPilot 2.0) собирает npm ДО PyInstaller
    # (Build-Desktop.ps1), и он едет тем же --add-data, что panel.js. Пропади
    # шаг сборки — у клиники с включённым флагом React страница открылась бы
    # серверной заглушкой, а /health и всё выше осталось бы зелёным.
    r = c.get("/static/js/bundle.js")
    check("бандл React отдаётся из сборки",
          r.status == 200 and len(r.raw) > 50000,
          f"код {r.status}, {len(r.raw)} б (npm run build не выполнен?)")
    r = c.get("/static/css/bundle.css")
    check("стили React отдаются из сборки",
          r.status == 200 and len(r.body) > 50, f"код {r.status}, {len(r.body)} б")
    # three.js (B7) едет отдельным файлом и грузится только при открытии вида
    # 3D: потерянная копия не ломает ни одну страницу — заметит только врач,
    # нажавший «3D» у клиники. Поэтому ловим здесь, на собранном exe.
    r = c.get("/static/js/three.js")
    check("three.js для объёмной одонтограммы отдаётся из сборки",
          r.status == 200 and len(r.raw) > 100000,
          f"код {r.status}, {len(r.raw)} б (копия на сборке не сделана?)")
    # ядро three (r170+) едет вторым файлом: без него three.js падает на импорте
    r = c.get("/static/js/three-core.js")
    check("ядро three.js отдаётся из сборки",
          r.status == 200 and len(r.raw) > 100000, f"код {r.status}, {len(r.raw)} б")

    # ⚠️ Шрифт — ДВОИЧНЫЙ файл, и это его собственный способ не доехать: путь в
    # маршруте отдельный (байты, не текст), а страница без него не ломается —
    # просто рисуется системным Segoe UI, ровно как до вшивания Inter. То есть
    # потеря выглядит как «ну да, так и было» и не замечается никогда.
    # Проверяем сигнатуру, а не код ответа: 200 с HTML-ошибкой внутри тоже 200.
    # ⚠️ Считается `@font-face{`, а не слово: оно есть и в пояснениях файла.
    r = c.get("/static/css/fonts.css")
    check("объявление шрифта отдаётся из сборки",
          r.status == 200 and r.body.count("@font-face{") == 4,
          f"код {r.status}, правил {r.body.count('@font-face{')} — ждём 4")
    # Вход panel.css не подключает НАМЕРЕННО, поэтому объявление у него своё,
    # вставленное прямо в <style> (layout.fonts_css). Ровно этот угол и уцелел
    # до 08-11: первый экран клиники рисовался системным шрифтом.
    r = c.get("/admin/login")
    check("экран входа несёт объявление шрифта",
          r.status == 200 and "@font-face{" in r.body,
          f"код {r.status}, @font-face нет — вход уедет на Segoe UI")
    r = c.get("/static/fonts/inter-latin.woff2")
    check("шрифт отдаётся из сборки",
          r.status == 200 and r.raw[:4] == b"wOF2",
          f"код {r.status}, начало {r.raw[:8]!r}")


def _wall(c: Client, check, password: str, data_dir: str) -> None:
    """Свежая установка с ключом в exe: стена активации без двери наружу."""
    # шлюз стоит ДО маршрута: даже без входа журнал ведёт на активацию,
    # а сама активация — на вход (войти всё равно надо)
    r = c.get("/admin")
    check("стена: журнал без входа ведёт на /admin/license",
          r.status == 303 and "/admin/license" in r.location, f"код {r.status}, {r.location!r}")
    r = c.get("/admin/license")
    check("активация без входа ведёт на вход",
          r.status == 303 and "login" in r.location, f"код {r.status}, {r.location!r}")

    c.post("/admin/login", password=password, next="/admin")
    for path in ("/admin", "/admin/all", "/admin/settings"):
        r = c.get(path)
        check(f"стена: {path} после входа ведёт на /admin/license",
              r.status == 303 and "/admin/license" in r.location, f"код {r.status}, {r.location!r}")
    r = c.get("/admin/license")
    check("страница активации открывается",
          r.status == 200 and len(r.body) > 1000, f"код {r.status}, {len(r.body)} б")
    check("активация: заявка на пробный уходит на сервер лицензий",
          "action='/admin/license/request'" in r.body and "Activare automată" in r.body,
          "формы заявки нет")
    # 02.10: клиника файла не видит — ни поля загрузки, ни слова о нём
    check("активация: формы файла нет (02.10)",
          "type='file'" not in r.body and 'type="file"' not in r.body and "fișier" not in r.body,
          "на странице осталась загрузка файла")
    # ворота записи за стеной — своим кодом, до разбора тела
    r = c.post_json("/api/patients", {"name": "Smoke Zid", "phone": "069000001"})
    check("за стеной запись отказывает 423 license_missing",
          r.status == 423 and "license_missing" in r.body, f"код {r.status}, {r.body[:120]!r}")
    # и /health при этом жив — по нему лаунчер понимает, что сервер поднялся
    check("/health открыт и за стеной", c.get("/health").status == 200)

    if data_dir:
        check("лаборатория: пациент заведён в картотеку для фазы grace",
              _seed_patient(pathlib.Path(data_dir)), "dental.db не найдена или не записалась")


def _seed_patient(root: pathlib.Path) -> bool:
    """Один пациент прямо в dental.db лаборатории: так exe на следующем старте
    видит живую картотеку (льгота), а не пустую (стена). Мимо программы —
    намеренно: за стеной она пациента не заведёт, а источник второй фазы
    должен быть тем же exe, не сервером из исходников."""
    for db in (root / "data" / "dental.db", root / "dental.db"):
        if db.exists():
            break
    else:
        return False
    try:
        con = sqlite3.connect(str(db), timeout=15)
        try:
            con.execute(
                "INSERT INTO patients(session_key, name, phone, lang, created_at) VALUES(?, ?, ?, ?, ?)",
                ("smoke-exe-grace", "Pacient Smoke", "069000000", "ro",
                 datetime.now(timezone.utc).isoformat(timespec="seconds")))
            con.commit()
            n = con.execute("SELECT count(*) FROM patients").fetchone()[0]
        finally:
            con.close()
        return n >= 1
    except sqlite3.Error as e:
        print(f"   (sqlite: {e!r})")
        return False


def _pages(c: Client, check, password: str, *, grace: bool) -> None:
    """Живая картотека: страницы открываются; при ключе в exe — с баннером льготы."""
    r = c.get("/admin")
    check("журнал закрыт без входа",
          r.status == 303 and "login" in r.location, f"код {r.status}")

    c.post("/admin/login", password=password, next="/admin")
    pages = ["/admin", "/admin/all", "/admin/week", "/admin/stats",
             "/admin/settings", "/admin/medici", "/admin/search", "/admin/qr-print"]
    for path in pages:
        r = c.get(path)
        check(f"{path} открывается",
              r.status == 200 and len(r.body) > 1000, f"код {r.status}, {len(r.body)} б")
    home = c.get("/admin")
    if grace:
        # баннер бывает ТОЛЬКО когда ключ выдачи есть (lic.applies()): это и
        # есть доказательство, что rsa_verify.KEYS уехал в сборку
        check("льгота: баннер называет лицензию, срок и ссылку на активацию",
              "banner warn" in home.body and "Licența lipsește" in home.body
              and "href='/admin/license'" in home.body, "баннера льготы нет — ключа в exe нет?")
        check("льгота: стены нет, страница активации открывается",
              c.get("/admin/license").status == 200)
        # запись при льготе разрешена: пациент из фазы wall находится поиском
        r = c.get("/admin/search?q=Smoke")
        check("пациент, заведённый в лаборатории, находится поиском",
              r.status == 200 and "Pacient Smoke" in r.body, f"код {r.status}")

    # ⭐ Живой канал панели — В СОБРАННОЙ программе. Страницы его не задевают
    # вовсе: `/admin` открывается и без него, а `/health` тем более. При этом
    # именно от него зависит, будет ли панель у клиники обновляться сама, и
    # ломается он ровно так же, как всё в exe, — потерянным модулем.
    r = c.get("/api/schedule/live?screen=panel")
    ok = False
    try:
        d = json.loads(r.body).get("data") or {}
        ok = r.status == 200 and d.get("live") is True and "canvas" in d
    except Exception:
        ok = False
    check("живой канал панели отвечает состоянием в сборке",
          ok and r.header("X-DP-Hash") != "" and r.header("X-DP-Surface") != "",
          f"код {r.status}, отпечаток {r.header('X-DP-Hash')!r}, "
          f"поверхность {r.header('X-DP-Surface')!r}")

    # Выгрузка в Excel собирается zip'ом на лету (core/xlsx). В СОБРАННОЙ
    # программе это стоит проверить отдельно: страницы её не задевают, а
    # сжатие живёт в модуле, который PyInstaller тянет неявно.
    r = c.get("/admin/export.xlsx")
    check("выгрузка Excel собирается в сборке",
          r.status == 200 and r.raw[:2] == b"PK" and len(r.raw) > 800,
          f"код {r.status}, {len(r.raw)} б, первые байты {r.raw[:4]!r}")

    check("страница ссылается на таблицу стилей",
          "/static/css/panel.css?v=" in home.body, "нет <link> на panel.css")
    check("журнал подключает объявление шрифта",
          "/static/css/fonts.css?v=" in home.body, "нет <link> на fonts.css")

    # Маршруты вынесенных модулей. Если подпакет не попал в сборку, роутер не
    # подключится и адрес ответит 404 — а страницы выше при этом будут целы,
    # то есть без такой проверки потеря целого модуля выглядела бы как успех.
    r = c.get("/admin/patient/999999")
    check("маршруты модуля «пациенты» подключены",
          r.status in (200, 303), f"код {r.status} (404 = модуль не в сборке)")
    r = c.get("/admin/patient/999999/slots?date=2026-01-01&doctor=d1&service=consult")
    check("действия карточки подключены", r.status == 200, f"код {r.status}")
    r = c.get("/admin/visit/999999")
    check("дневник визита (consultația) подключён", r.status in (200, 303),
          f"код {r.status} (404 = visit.py не попал в сборку)")
    # печатные листы — отдельные файлы модуля: их пропажа из сборки не видна
    # ни по /health, ни по страницам журнала
    r = c.get("/admin/patient/999999/fisa043")
    check("печатная 043/e подключена", r.status in (200, 303),
          f"код {r.status} (404 = fisa043.py не попал в сборку)")
    r = c.get("/admin/patient/999999/acord")
    check("формуляр informare/acord подключён", r.status in (200, 303),
          f"код {r.status} (404 = acord.py не попал в сборку)")
    r = c.get("/admin/patient/999999/parodontograma")
    check("пародонтограмма подключена", r.status in (200, 303),
          f"код {r.status} (404 = perio.py не попал в сборку)")
    # касса живёт в другом модуле (stats), но по той же причине: отдельный
    # файл, который может не уехать в бандл, и по /health этого не видно
    r = c.get("/admin/casa")
    check("отчёт кассы подключён", r.status in (200, 303),
          f"код {r.status} (404 = casa.py не попал в сборку)")

    # бот-диалог: конфиг клиники прочитан из бандла
    # ключ сессии выдаёт сам сервер (core.auth.chat_session) — клиент его не шлёт
    r = c.post_json("/chat", {"message": "/start"})
    check("бот отвечает на /start",
          r.status == 200 and "lang:ro" in r.body, f"код {r.status}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Укажите адрес: python tests\\smoke_exe.py http://127.0.0.1:8100 [пароль] [wall|grace] [папка]")
    _phase = sys.argv[3] if len(sys.argv) > 3 else PAGES
    if _phase not in (WALL, GRACE, PAGES):
        sys.exit(f"фаза {_phase!r}: ожидается wall, grace или ничего")
    sys.exit(main(sys.argv[1].rstrip("/"),
                  sys.argv[2] if len(sys.argv) > 2 else "smoke1234",
                  _phase, sys.argv[4] if len(sys.argv) > 4 else ""))
