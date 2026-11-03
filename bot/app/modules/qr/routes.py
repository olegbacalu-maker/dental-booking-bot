"""Картинка QR-кода по адресу `/qr?data=…`.

Её зовёт экран «Acces din rețea» (`settings/lan.py`): код адреса программы
для второго компьютера и телефонов в сети клиники. Печатный листок «QR
pacienți» и выставочный `/demo` жили здесь с ботом записи и ушли вместе с ним
(03.11.2026, код — тег `archive/telegram-bot`).
"""
from __future__ import annotations

import io

import qrcode
from fastapi import APIRouter
from fastapi.responses import Response

router = APIRouter()


@router.get("/qr")
async def qr(data: str) -> Response:
    img = qrcode.make(data[:500])
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(buf.getvalue(), media_type="image/png")
