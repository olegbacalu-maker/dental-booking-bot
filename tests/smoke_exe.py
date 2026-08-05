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

    # CSS живёт строкой в коде: если он исчезнет, страница откроется «голой»
    r = c.get("/admin")
    check("стили на странице", ".banner" in r.body and "--teal" in r.body,
          "нет разметки стилей")

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
