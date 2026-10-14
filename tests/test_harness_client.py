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

Второй набор — опрос `/health` на старте сервера (`harness._health`, 14.10):
он закрывал сокет по одним заголовкам, и под нагрузкой закрытие приходило
серверу RST-ом под его `shutdown` — трейсбек asyncio в логе сервера
краснил «лог: renew=offline, без трейсбека». Пара та же: штатный
`with urlopen(…): pass` на сцене обязан БРОСИТЬ ответ на середине.
"""
from __future__ import annotations

import http.client
import http.server
import json
import pathlib
import socket
import sys
import threading
import time
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from harness import Client, Result, _health  # noqa: E402


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


def _closed_within(c: socket.socket, seconds: float) -> bool:
    """Закрыл ли клиент сокет за `seconds`: FIN (пустое чтение) или RST."""
    c.settimeout(seconds)
    try:
        return c.recv(1) == b""
    except (socket.timeout, BlockingIOError):      # нуль секунд — сокет неблокирующий
        return False
    except OSError:
        return True


def _stage(head_after: float, body_after: float) -> tuple[int, list, socket.socket]:
    """Сцена на сырых сокетах: на подключение — заголовки через `head_after`
    секунд, тело ещё через `body_after`. Итог каждого подключения —
    «дочитал» (клиент закрыл сокет, получив ответ целиком) или «бросил»
    (закрыл раньше: сервер получил бы обрыв посреди ответа)."""
    ls = socket.socket()
    ls.bind(("127.0.0.1", 0))
    ls.listen()
    seen: list[str] = []
    body = b'{"ok": true}'
    head = (b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
            b"Content-Length: %d\r\nConnection: close\r\n\r\n" % len(body))

    def serve():
        while True:
            try:
                c, _ = ls.accept()
            except OSError:
                return                           # сцену закрыли
            with c:
                buf = b""
                while b"\r\n\r\n" not in buf:
                    chunk = c.recv(4096)
                    if not chunk:
                        break
                    buf += chunk
                if head_after and _closed_within(c, head_after):
                    seen.append("бросил")
                    continue
                c.settimeout(None)
                c.sendall(head)
                if body_after and _closed_within(c, body_after):
                    seen.append("бросил")
                    continue
                c.settimeout(None)
                try:
                    c.sendall(body)
                except OSError:
                    seen.append("бросил")
                    continue
                seen.append("дочитал" if _closed_within(c, 10) else "не закрыл")

    threading.Thread(target=serve, daemon=True).start()
    return ls.getsockname()[1], seen, ls


def _outcome(seen: list, timeout: float = 10.0) -> list:
    """Итог сцены появляется в её потоке — дождаться его."""
    deadline = time.time() + timeout
    while not seen and time.time() < deadline:
        time.sleep(0.01)
    return list(seen)


def _urlopen_unread(port: int) -> None:
    """Опрос, каким он был до 14.10: заголовки — и закрыть."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1):
            pass
    except OSError:
        pass


def suite_health_probe(res: Result) -> None:
    """Опрос старта сервера не бросает ответ на середине: ни тело,
    пришедшее отдельной записью, ни ответ медленнее секунды. Пары — штатный
    `with urlopen(…): pass` на тех же сценах обязан бросить."""
    # Тело — отдельной записью через 0.2 с, как пишет uvicorn (заголовки, потом тело)
    port, seen, ls = _stage(head_after=0, body_after=0.2)
    try:
        _urlopen_unread(port)
        res.check("пара: штатный опрос без чтения бросает ответ посреди тела",
                  _outcome(seen), ["бросил"])
    finally:
        ls.close()
    port, seen, ls = _stage(head_after=0, body_after=0.2)
    try:
        up = _health(port, time.time() + 10)
        got = _outcome(seen)
        res.ok("опрос старта дочитывает тело до конца и только потом закрывает",
               up and got == ["дочитал"], f"ответил {up}, сцена: {got}")
    finally:
        ls.close()

    # Ответ медленнее секунды: прежний таймаут бросал уже принятый запрос
    port, seen, ls = _stage(head_after=1.3, body_after=0)
    try:
        _urlopen_unread(port)
        res.check("пара: штатный опрос с таймаутом в секунду бросает долгий ответ",
                  _outcome(seen), ["бросил"])
    finally:
        ls.close()
    port, seen, ls = _stage(head_after=1.3, body_after=0)
    try:
        up = _health(port, time.time() + 10)
        got = _outcome(seen)
        res.ok("опрос старта ждёт ответа на принятый запрос, а не бросает его",
               up and got == ["дочитал"], f"ответил {up}, сцена: {got}")
    finally:
        ls.close()

    # Сервер ещё не слушает: «нет» — и не дольше секунды (опрос раз в 0.3 с)
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    closed = s.getsockname()[1]
    s.close()
    t0 = time.time()
    up = _health(closed, time.time() + 10)
    took = time.time() - t0
    res.ok("порт ещё не слушает: «не поднялся», и не дольше секунды",
           up is False and took < 1.5, f"ответил {up} за {took:.2f} с")
