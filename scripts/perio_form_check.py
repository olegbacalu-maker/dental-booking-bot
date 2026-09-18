# -*- coding: utf-8 -*-
"""СТАРАЯ форма пародонтограммы в headless Edge: сообщает ли она о ТРОНУТОМ.

⛔ Не в CI и не в `.\\dev test`: нужны Edge и websocket-client в СИСТЕМНОМ
Python (в .venv-desktop ничего не ставить — это окружение сборки). Механика
общая с кадрами одонтограммы и берётся оттуда: `odo_shots.CDP`, `Page`,
`login_cookie`, `start_edge`. Пациент — `test_perio_api._seed`.

Запуск из app\\:   python scripts\\perio_form_check.py

⚠️ Зачем отдельно от наборов. Наборы шлют поля формы НАПРЯМУЮ и её JS не
исполняют вовсе, а с 18.09 именно он решает, о чём сообщает сохранение: лист
снимает слепок при загрузке и перед отправкой сравнивает с ним каждую колонку
(поле `covers`). Ошибись он — сервер честно выполнит не то намерение, а наборы
останутся зелёными. У клиник сегодня работает как раз эта страница, поэтому
проверка живёт в репозитории, а не в чьей-то временной папке.

Сцены: лист без правок (не сообщаем ничего), тронутый зуб (назван только он),
очищенный зуб (назван в `covers`, но не прислан — это и есть «стереть»),
изменённая заметка при нетронутой подписи. Красная проверка — код возврата 1.
"""
import json
import os
import pathlib
import sys

# Консоль Windows живёт в cp1251, а отчёт печатает русские слова и кавычки.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "scripts"))

from harness import Client, Server  # noqa: E402
from test_perio_api import _seed  # noqa: E402
import odo_shots as odo  # noqa: E402

PORT = 9341

# Отправку перехватываем: обработчик страницы зарегистрирован ПЕРВЫМ, поэтому
# он успевает заполнить скрытые поля, а наш слушатель гасит саму отправку.
# ⚠️ После срабатывания у неизменённых полей уже снят `name` — каждой сцене
# нужна СВОЯ загрузка страницы.
SNAP = r"""
(function () {
  var f = document.getElementById('pform');
  f.addEventListener('submit', function (e) { e.preventDefault(); }, {once: true});
  f.dispatchEvent(new Event('submit', {bubbles: true, cancelable: true}));
  var has = function (n) { return !!f.querySelector("[name='" + n + "']"); };
  return JSON.stringify({
    chart: document.getElementById('pchart').value,
    covers: document.getElementById('pcovers').value,
    rev: (f.querySelector("[name='rev']") || {}).value || '',
    doctor: has('doctor'), note: has('note')
  });
})()
"""

# ⚠️ Подстановка процентом, а не `format`: в теле JS фигурные скобки.
SET_CELL = ("(function () { var i = document.querySelector("
            "\".ptooth[data-tooth='%(n)s'] input[data-k='%(k)s'][data-i='%(i)s']\");"
            " i.value = '%(v)s'; return i.value; })()")

SET_NOTE = ("(function () { var n = document.querySelector(\"[name='note']\");"
            " n.value = '%s'; return n.value; })()")


def run() -> int:
    fails = []

    def want(name, got, expect):
        if got != expect:
            fails.append(f"{name}: получено {got!r}, ожидалось {expect!r}")
            print(f"RED {name}: {got!r} != {expect!r}")
        else:
            print(f"OK  {name}: {got!r}")

    s1 = Server()
    s1._own_dir = False
    with s1:
        c = Client(s1.url).login()
        d = _seed(c)
    profile = os.path.join(os.environ["TEMP"], "dp-edge-perio-form")
    s2 = Server(dir_=s1.dir)
    proc = None
    try:
        with s2:
            origin = s2.url
            cookie = odo.login_cookie(origin)
            proc, ws_url = odo.start_edge(profile, PORT)
            cdp = odo.CDP(ws_url)
            for dom in ("Network", "Runtime", "Log", "Page"):
                cdp.cmd(f"{dom}.enable")
            cdp.cmd("Network.setCookie", name="admin_auth", value=cookie,
                    url=origin + "/")
            page = odo.Page(cdp, origin)
            page.size(1700, 1000)
            path = f"/admin/patient/{d['pid']}/parodontograma?exam={d['eid']}"

            # 1. Лист открыли и ничего не тронули
            page.go(path)
            snap = json.loads(page.js(SNAP))
            want("ничего не трогали — covers пуст", snap["covers"], "")
            want("и лист не уезжает", snap["chart"], "")
            want("отпечаток осмотра на месте", len(snap["rev"]), 12)
            want("неизменённая подпись не отправляется", snap["doctor"], False)
            want("неизменённая заметка не отправляется", snap["note"], False)

            # 2. Тронули ОДИН зуб из тридцати двух
            page.go(path)
            page.js(SET_CELL % {"n": 11, "k": "pd", "i": 0, "v": 5})
            snap = json.loads(page.js(SNAP))
            want("тронули 11 — только он и назван", snap["covers"], "11")
            want("и уехал только он",
                 snap["chart"], "11:5,0,0,0,0,0/0,0,0,0,0,0/000000/0/0")

            # 3. У измеренного зуба убрали все шесть точек
            page.go(path)
            for i in range(6):
                page.js(SET_CELL % {"n": 46, "k": "pd", "i": i, "v": ""})
            snap = json.loads(page.js(SNAP))
            want("очищенный 46 назван в covers", snap["covers"], "46")
            want("и не прислан в chart — это и есть «стереть»", snap["chart"], "")

            # 4. Тронули заметку — уезжает она, но не подпись
            page.go(path)
            page.js(SET_NOTE % "a doua")
            snap = json.loads(page.js(SNAP))
            want("изменённая заметка отправляется", snap["note"], True)
            want("а нетронутая подпись — нет", snap["doctor"], False)
            want("зубы при этом не тронуты", snap["covers"], "")

            want("консоль чиста", cdp.errors(), [])
    finally:
        if proc:
            proc.kill()
    print("\n" + ("ВСЁ ЗЕЛЁНОЕ" if not fails else f"КРАСНЫХ: {len(fails)}"))
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(run())
