"""Клиент прогона (`harness.Client`): небольшой запрос уходит в сокет ОДНОЙ
записью.

12.10: «ворота в readonly» падали `ConnectionAbortedError` 10053 раз в 3–15
прогонов, на случайном JSON-POST. Штатный http.client пишет заголовки и тело
двумя записями, urllib просит `Connection: close`, и ранний отказ сервера
(423 ворот до разбора тела) успевал закрыть сокет между ними: тело приходило
в закрытый сокет, RST выбрасывал уже пришедший ответ. Разбор —
`harness._OneWrite`.

Пара, как у остальных сторожей харнесса: штатный urllib на том же сервере
обязан показать ДВЕ записи — иначе счётчик смотрел бы не туда и зеленел бы
и на сломанном клиенте. И обратная граница: мегабайт идёт штатно, двумя
записями, — одна запись вредит раннему отказу на крупных телах (замер —
в `harness._OneWrite`).
"""
from __future__ import annotations

import http.client
import http.server
import json
import pathlib
import sys
import threading
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from harness import Client, Result  # noqa: E402


class _Sink(http.server.BaseHTTPRequestHandler):
    """Дочитывает тело и отвечает 204: серверу здесь проверять нечего."""

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.send_response(204)
        self.end_headers()

    def log_message(self, *args):
        pass


def suite_one_write(res: Result) -> None:
    """Запись в сокет: штатный urllib — две, клиент прогона — одна, а крупное
    тело у него — снова две, как у штатного."""
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Sink)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    body = json.dumps({"a": 1}).encode()
    writes: list[bytes] = []
    send = http.client.HTTPConnection.send

    def spy(self, data):
        writes.append(bytes(data))
        return send(self, data)

    http.client.HTTPConnection.send = spy
    try:
        urllib.request.build_opener().open(
            urllib.request.Request(base + "/x", data=body), timeout=10).read()
        res.check("пара: штатный urllib пишет заголовки и тело двумя записями",
                  len(writes), 2)
        writes.clear()
        c = Client(base)
        r = c.post_json("/x", {"a": 1})
        res.check("клиент прогона: ответ дошёл", r.status, 204)
        res.check("клиент прогона: запрос одной записью", len(writes), 1)
        res.ok("в этой записи и заголовки, и тело",
               len(writes) == 1 and writes[0].startswith(b"POST /x ")
               and writes[0].endswith(b"\r\n\r\n" + body), repr(writes)[:200])
        writes.clear()
        # 1 МБ — размер из замера, а не от MERGE_MAX: поднятый до мегабайтов
        # потолок обязан краснеть здесь, а не уезжать вместе с проверкой
        big = b"0" * (1024 * 1024)
        r = c.post_file("/x", "file", "f.bin", big)
        res.check("крупное тело: ответ дошёл", r.status, 204)
        res.ok("крупное тело — штатно: заголовки, потом тело",
               len(writes) == 2 and writes[0].startswith(b"POST /x ")
               and writes[0].endswith(b"\r\n\r\n") and big in writes[1],
               f"записей {len(writes)}: {[len(w) for w in writes]}")
    finally:
        http.client.HTTPConnection.send = send
        srv.shutdown()
        srv.server_close()
