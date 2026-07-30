"""Telegram-адаптер поверх того же диалогового движка (engine.handle).
Включается автоматически, если задан TELEGRAM_TOKEN (см. .env.example).
Веб-чат и Telegram работают параллельно: сессии независимы, БД общая."""
from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (CallbackQuery, InlineKeyboardButton,
                           InlineKeyboardMarkup, Message)

from . import engine as eng

log = logging.getLogger("telegram")


def _keyboard(buttons: list[list[dict]]) -> InlineKeyboardMarkup | None:
    if not buttons:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=b["label"], callback_data=b["value"][:64]) for b in row]
        for row in buttons
    ])


async def _dialog(chat_id: int, text: str, send) -> None:
    sid = f"tg:{chat_id}"
    s = eng.get_session(sid)
    texts, buttons = await eng.handle(s, sid, text)
    kb = _keyboard(buttons)
    for i, t in enumerate(texts):
        await send(t, reply_markup=kb if i == len(texts) - 1 else None)


async def run(token: str) -> None:
    bot = Bot(token=token)
    dp = Dispatcher()

    @dp.message(CommandStart())
    async def on_start(m: Message) -> None:
        await _dialog(m.chat.id, "/start",
                      lambda t, reply_markup=None: m.answer(t, reply_markup=reply_markup))

    @dp.message(F.text)
    async def on_text(m: Message) -> None:
        await _dialog(m.chat.id, m.text or "",
                      lambda t, reply_markup=None: m.answer(t, reply_markup=reply_markup))

    @dp.callback_query()
    async def on_callback(c: CallbackQuery) -> None:
        await c.answer()
        if c.message is None:
            return
        await _dialog(c.message.chat.id, c.data or "",
                      lambda t, reply_markup=None: c.message.answer(t, reply_markup=reply_markup))

    me = await bot.get_me()
    log.warning("Telegram adapter: polling started as @%s", me.username)
    await dp.start_polling(bot, handle_signals=False)
