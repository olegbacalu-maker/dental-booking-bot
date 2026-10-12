"""Поисковики и cloud.dentpilot.md (12.10.2026): ни один ответ облака не должен
попасть в выдачу — кабинет, вход, форма пробного, админка, API программы.

⛔ Запрет — заголовком `X-Robots-Tag: noindex` на КАЖДОМ ответе, а НЕ
`Disallow: /` в robots.txt. robots.txt запрещает ОБХОД, а не индекс: адреса
облака стоят ссылками на сайте (`/cont` — «Logare / Înregistrare» на каждой
странице, `/proba` и `/descarca` — на страницах скачивания и в условиях), и
закрытый для обхода адрес Google индексирует по ссылке голым («Indexed, though
blocked by robots.txt»), потому что запрет на самой странице он прочесть не
может. Поэтому обход открыт, а запрет едет с каждым ответом — HTML, JSON
программы, редирект, 404 — без оглядки на то, вспомнила ли о нём страница
(meta `noindex` есть не у всех: у /proba, страниц оплаты и maib её не было).
У демо наоборот — `Disallow: /` (demo/admit.py): там сам обход дорог (слот).

Заголовок ставит ASGI-обёртка, а не BaseHTTPMiddleware: та переупаковывает
ответ, и ей нечего здесь делать. Ответ 500, собранный ServerErrorMiddleware
(он снаружи всех обёрток), заголовка не получит — ошибка сервера в выдачу и
так не попадает.
"""
from __future__ import annotations

TXT = "User-agent: *\nAllow: /\n"

_NAME = b"x-robots-tag"
_VALUE = b"noindex, nofollow"


class NoIndex:
    """Дописывает `X-Robots-Tag: noindex, nofollow` к каждому HTTP-ответу
    приложения; свой такой заголовок у маршрута заменяется — значение одно."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_tagged(message):
            if message["type"] == "http.response.start":
                headers = [h for h in message.get("headers", []) if h[0].lower() != _NAME]
                headers.append((_NAME, _VALUE))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_tagged)
