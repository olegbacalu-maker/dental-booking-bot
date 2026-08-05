"""Дымовой тест СОБРАННОЙ программы: страницы реально открываются.

    python tests\\smoke_exe.py http://127.0.0.1:8100 smoke1234

Зачем отдельно от run_tests.py: тот поднимает сервер из исходников, а здесь
проверяется exe, где файлы лежат не там, где в репозитории. Ровно этот класс
поломок — потерянный `--add-data`, сбитый путь к static или к clinic.json —
из исходников не воспроизводится и виден только на собранном бинарнике.

Проверка `/health` этого не ловит: она отвечает без единого файла на диске.
"""
import json
import pathlib
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from harness import Client  # noqa: E402


def main(base: str, password: str) -> int:
    bad: list[str] = []

    def check(label: str, cond: bool, detail: str = "") -> None:
        print(f"   {'OK  ' if cond else 'FAIL'} {label}" + (f" — {detail}" if not cond else ""))
        if not cond:
            bad.append(label)

    c = Client(base)

    r = c.get("/health")
    ver = json.loads(r.body).get("version", "") if r.status == 200 else ""
    check("/health отвечает", bool(ver), f"код {r.status}")

    # страница пациента-бота: живёт в static/index.html внутри бандла
    r = c.get("/")
    check("главная (static/index.html) отдаётся",
          r.status == 200 and len(r.body) > 500, f"код {r.status}, {len(r.body)} б")

    r = c.get("/favicon.ico")
    check("значок отдаётся", r.status == 200 and len(r.body) > 50, f"код {r.status}")

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

    # Оформление — отдельный файл внутри бандла. Если он не попал в сборку,
    # страницы откроются «голыми», а /health об этом не скажет ни слова.
    r = c.get("/admin")
    check("страница ссылается на таблицу стилей",
          "/static/css/panel.css?v=" in r.body, "нет <link> на panel.css")
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

    # Маршруты вынесенных модулей. Если подпакет не попал в сборку, роутер не
    # подключится и адрес ответит 404 — а страницы выше при этом будут целы,
    # то есть без такой проверки потеря целого модуля выглядела бы как успех.
    r = c.get("/admin/patient/999999")
    check("маршруты модуля «пациенты» подключены",
          r.status in (200, 303), f"код {r.status} (404 = модуль не в сборке)")
    r = c.get("/admin/patient/999999/slots?date=2026-01-01&doctor=d1&service=consult")
    check("действия карточки подключены", r.status == 200, f"код {r.status}")

    # бот-диалог: конфиг клиники прочитан из бандла
    r = c.post_json("/chat", {"session_id": "smoke", "message": "/start"})
    check("бот отвечает на /start",
          r.status == 200 and "lang:ro" in r.body, f"код {r.status}")

    print(f"\n   дымовой тест: {'ПРОВАЛ' if bad else 'OK'} ({len(bad)} из "
          f"{len(pages) + 6} проверок красные)" if bad
          else f"\n   дымовой тест собранной программы: OK, версия {ver}")
    return 1 if bad else 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Укажите адрес: python tests\\smoke_exe.py http://127.0.0.1:8100 [пароль]")
    sys.exit(main(sys.argv[1].rstrip("/"),
                  sys.argv[2] if len(sys.argv) > 2 else "smoke1234"))
