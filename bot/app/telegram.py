"""Telegram-адаптер поверх того же диалогового движка (engine.handle).
Включается автоматически, если задан TELEGRAM_TOKEN (см. .env.example).
Веб-чат и Telegram работают параллельно: сессии независимы, БД общая."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (CallbackQuery, InlineKeyboardButton,
                           InlineKeyboardMarkup, Message)

from . import db
from . import engine as eng

log = logging.getLogger("telegram")

# статус канала для страницы настроек
STATUS = {"running": False, "username": "", "error": ""}


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


async def _send_reminder(bot: Bot, r) -> None:
    lang = r["lang"] if r["lang"] in eng.T else "ro"
    s = eng.Session(lang=lang)
    dt = r["starts_at"].astimezone(eng.TZ)
    soon = dt - datetime.now(eng.TZ) <= timedelta(hours=2)
    if soon and r["reminded_2h"]:
        return
    if not soon and r["reminded_day"]:
        return
    if soon:
        text = eng.t(s, "reminder_soon").format(
            time=dt.strftime("%H:%M"), doctor=r["doctor"], service=r["service"])
    else:
        when = f"{eng.day_label(s, dt.date())} {dt.strftime('%H:%M')}"
        text = eng.t(s, "reminder").format(
            when=when, doctor=r["doctor"], service=r["service"])
    kb = _keyboard([
        [eng.btn(eng.t(s, "btn_rem_ok"), "rem_ok")],
        [eng.btn(f"{eng.t(s, 'btn_cancel_appt')} #{r['id']}", f"cancel:{r['id']}")],
    ])
    chat_id = int(r["session_key"][3:])
    try:
        await bot.send_message(chat_id, text, reply_markup=kb)
        log.warning("Reminder sent: appt #%s -> chat %s (%s)",
                    r["id"], chat_id, "2h" if soon else "24h")
    except Exception as e:  # noqa: BLE001 — пациент мог заблокировать бота
        log.warning("Reminder FAILED for appt #%s: %r", r["id"], e)
    # помечаем в любом случае — ретрай-шторм хуже пропущенного напоминания
    await db.mark_reminded(r["id"], day=True, soon=soon)


async def _reminder_loop(bot: Bot) -> None:
    log.warning("Reminder loop: started (tick 60s; T-24h and T-2h)")
    while True:
        try:
            for r in await db.tg_due_reminders(datetime.now(eng.TZ)):
                await _send_reminder(bot, r)
        except Exception as e:  # noqa: BLE001 — цикл не должен умирать
            log.warning("Reminder loop error: %r", e)
        await asyncio.sleep(60)


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
    STATUS.update(running=True, username=me.username or "", error="")
    log.warning("Telegram adapter: polling started as @%s", me.username)
    asyncio.create_task(_reminder_loop(bot))
    try:
        await dp.start_polling(bot, handle_signals=False)
    finally:
        STATUS["running"] = False
