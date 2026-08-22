"""Telegram-адаптер поверх того же диалогового движка (engine.handle).
Включается автоматически, если задан TELEGRAM_TOKEN (см. .env.example).
Веб-чат и Telegram работают параллельно: сессии независимы, БД общая."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.exceptions import (TelegramBadRequest, TelegramForbiddenError,
                                TelegramUnauthorizedError)
from aiogram.filters import CommandStart
from aiogram.types import (CallbackQuery, InlineKeyboardButton,
                           InlineKeyboardMarkup, Message)

from . import db
from . import engine as eng

log = logging.getLogger("telegram")

# статус канала для страницы настроек
STATUS = {"running": False, "username": "", "error": ""}

# Как часто переспрашивать Telegram, жив ли канал (см. _watch).
_WATCH_TICK = 300


def _note_fail(e: Exception) -> None:
    """Отказ канала — в STATUS, а не только в лог.

    Страница «Stare sistem» читает ровно эти два поля (settings/routes._tg_line),
    и без записи она врала дважды: при ОТОЗВАННОМ токене показывала «activ»
    (aiogram ретраит getUpdates вечно, поллинг не завершается, running остаётся
    True), а при НЕВЕРНОМ — вечное «pornire…», потому что get_me падал до
    единственной записи STATUS. Причина при этом уезжала в print, которого в
    собранной программе нет вовсе (--noconsole).
    """
    STATUS.update(
        running=False,
        error=("tokenul a fost respins de Telegram — reintroduceți-l în "
               "secțiunea Telegram Bot"
               if isinstance(e, TelegramUnauthorizedError)
               else f"canalul nu răspunde ({type(e).__name__})"))
    log.warning("Telegram channel DOWN: %r", e)


# ---- визитка бота (описание в профиле и в пустом чате) --------------------
# Description хранится на серверах Telegram, поэтому виден и тогда, когда
# программа клиники ВЫКЛЮЧЕНА и бот молчит. Это единственный канал сказать
# пациенту, почему нет ответа и куда звонить, — потому тексты не выдумываются
# здесь, а собираются из clinic.json (contacts пересобирают настройки при
# каждом сохранении: адрес + телефон + орар одной строкой).
_DESC_MAX, _SHORT_MAX = 512, 120   # лимиты Bot API на тексты визитки
_BOT: Bot | None = None            # живой бот — для refresh_meta() из настроек
_LOOP: asyncio.AbstractEventLoop | None = None


def _meta_texts() -> dict[str, dict[str, str]]:
    name = str(eng.CONFIG.get("name", "")).strip()
    phone = str(eng.CONFIG.get("phone", "")).strip()
    contacts = eng.CONFIG.get("contacts") or {}
    out: dict[str, dict[str, str]] = {}
    for lang, head, hint in (
            ("ro", f"Programări online — {name}",
             "Dacă botul nu răspunde, încercați în orele de lucru ale "
             "clinicii sau sunați:"),
            ("ru", f"Онлайн-запись — {name}",
             "Если бот не отвечает, попробуйте в часы работы клиники "
             "или позвоните:")):
        c = str(contacts.get(lang, "")).strip()
        out[lang] = {
            "desc": "\n".join(x for x in (head + ".", hint, c) if x)[:_DESC_MAX],
            "short": (f"{head} · ☎️ {phone}" if phone else head)[:_SHORT_MAX],
        }
    return out


async def _apply_meta(bot: Bot) -> None:
    """Догнать визитку бота до текущего clinic.json. Сравниваем с тем, что
    уже у Telegram, — ежедневный старт программы не шлёт одно и то же."""
    if eng.CONFIG.get("template"):
        return  # клиника ещё не заполнена — заглушку в профиль не публикуем
    try:
        texts = _meta_texts()
        cur_d = (await bot.get_my_description()).description
        cur_s = (await bot.get_my_short_description()).short_description
        if cur_d == texts["ro"]["desc"] and cur_s == texts["ro"]["short"]:
            return
        await bot.set_my_description(description=texts["ro"]["desc"])
        await bot.set_my_description(description=texts["ru"]["desc"],
                                     language_code="ru")
        await bot.set_my_short_description(short_description=texts["ro"]["short"])
        await bot.set_my_short_description(short_description=texts["ru"]["short"],
                                           language_code="ru")
        log.warning("Bot profile updated (description + short)")
    except Exception as e:  # noqa: BLE001 — визитка не смеет мешать боту
        log.warning("Bot profile update failed: %r", e)


def refresh_meta() -> None:
    """Зовётся после сохранения настроек (через core.layout.tg_refresh_meta):
    имя/телефон/орар в профиле бота должны догнать clinic.json. Потокобезопасно
    (роуты могут жить в threadpool); без запущенного бота — no-op: _apply_meta
    при следующем старте сам увидит расхождение и дошлёт."""
    if _BOT is not None and _LOOP is not None:
        asyncio.run_coroutine_threadsafe(_apply_meta(_BOT), _LOOP)


def _keyboard(buttons: list[list[dict]]) -> InlineKeyboardMarkup | None:
    if not buttons:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=b["label"], callback_data=b["value"][:64]) for b in row]
        for row in buttons
    ])


_ERR_TEXT = ("A apărut o eroare tehnică — încercați încă o dată 🙏 / "
             "Техническая ошибка — попробуйте ещё раз 🙏")


async def _dialog(chat_id: int, text: str, send) -> None:
    sid = f"tg:{chat_id}"
    # session_alive, не `in SESSIONS`: протухшую по TTL get_session снесёт
    # прямо сейчас — для восстановления языка она такая же «новая»
    fresh = not eng.session_alive(sid)
    s = eng.get_session(sid)
    if fresh:
        # после рестарта отвечаем возвращённому пациенту на ЕГО языке, не на ro
        try:
            lang = await db.patient_lang(sid)
            if lang in eng.T:
                s.lang = lang
        except Exception as e:  # noqa: BLE001
            log.warning("patient_lang lookup failed for chat %s: %r", chat_id, e)
    try:
        texts, buttons = await eng.handle(s, sid, text)
    except Exception:  # noqa: BLE001 — юзер не должен получать молчание
        log.exception("Dialog CRASHED: chat %s, state %s", chat_id, s.state)
        texts, buttons = [_ERR_TEXT], []
    kb = _keyboard(buttons)
    for i, t in enumerate(texts):
        try:
            await send(t, reply_markup=kb if i == len(texts) - 1 else None)
        except Exception as e:  # noqa: BLE001 — flood-limit/блокировка и т.п.
            log.warning("Send FAILED to chat %s: %r", chat_id, e)
            break


async def _ack(c: CallbackQuery) -> None:
    """Погасить «часики» на кнопке — и НЕ уронить на этом обработчик.

    answerCallbackQuery отвечает 400 «query is too old», если нажатие пролежало
    в очереди Telegram, пока программа была выключена (настольное издание
    закрывают на ночь, а апдейты Telegram держит до суток). Голый вызов уносил
    весь обработчик: aiogram гасит исключение строкой в логе и берётся за
    следующий апдейт — то есть отмена визита из напоминания пропадала молча,
    и пациент оставался уверен, что записи больше нет.
    """
    try:
        await c.answer()
    except Exception as e:  # noqa: BLE001 — «часики» не смеют отменить действие
        log.warning("Callback ack failed (%s): %r", c.data, e)


async def _send_reminder(bot: Bot, r) -> None:
    lang = r["lang"] if r["lang"] in eng.T else "ro"
    s = eng.Session(lang=lang)
    dt = r["starts_at"].astimezone(eng.TZ)
    soon = dt - datetime.now(eng.TZ) <= timedelta(hours=2)
    if soon and r["reminded_2h"]:
        return
    if not soon and r["reminded_day"]:
        return
    # напоминание — про БУДУЩИЙ визит: имя врача берём АКТУАЛЬНОЕ (после
    # переименования), снапшот из строки — только фолбэк для легаси
    doctor = eng.DOCTORS.get(r.get("doctor_id") or "", "") or r["doctor"]
    if soon:
        text = eng.t(s, "reminder_soon").format(
            time=dt.strftime("%H:%M"), doctor=doctor, service=r["service"])
    else:
        when = f"{eng.day_label(s, dt.date())} {dt.strftime('%H:%M')}"
        text = eng.t(s, "reminder").format(
            when=when, doctor=doctor, service=r["service"])
    kb = _keyboard([
        [eng.btn(eng.t(s, "btn_rem_ok"), "rem_ok")],
        [eng.btn(f"{eng.t(s, 'btn_cancel_appt')} #{r['id']}", f"cancel:{r['id']}")],
    ])
    chat_id = int(r["session_key"][3:])
    try:
        await bot.send_message(chat_id, text, reply_markup=kb)
        log.warning("Reminder sent: appt #%s -> chat %s (%s)",
                    r["id"], chat_id, "2h" if soon else "24h")
    except (TelegramForbiddenError, TelegramBadRequest) as e:
        # заблокировал бота / чат недоступен — ретраить бессмысленно, помечаем
        log.warning("Reminder DROPPED for appt #%s: %r", r["id"], e)
    except Exception as e:  # noqa: BLE001 — сеть моргнула: НЕ помечаем, ретрай через 60с
        log.warning("Reminder send failed for appt #%s (will retry): %r", r["id"], e)
        return
    try:
        await db.mark_reminded(r["id"], day=True, soon=soon)
    except Exception as e:  # noqa: BLE001 — иначе один сбой БД пересылает всю пачку
        log.warning("mark_reminded failed for appt #%s: %r", r["id"], e)


async def _reminder_loop(bot: Bot) -> None:
    log.warning("Reminder loop: started (tick 60s; T-24h and T-2h)")
    while True:
        try:
            for r in await db.tg_due_reminders(datetime.now(eng.TZ)):
                await _send_reminder(bot, r)
        except Exception as e:  # noqa: BLE001 — цикл не должен умирать
            log.warning("Reminder loop error: %r", e)
        await asyncio.sleep(60)


async def _watch(bot: Bot) -> None:
    """Канал мог умереть ПОСЛЕ старта: отозванный в @BotFather токен aiogram
    переживает молча — getUpdates падает, диспетчер ретраит вечно, поллинг не
    завершается. Раз в несколько минут спрашиваем Telegram, кто мы: это
    единственное место, где такой отказ становится видимым клинике."""
    while True:
        await asyncio.sleep(_WATCH_TICK)
        try:
            me = await bot.get_me()
        except Exception as e:  # noqa: BLE001 — сторож не имеет права падать
            _note_fail(e)
        else:
            STATUS.update(running=True, username=me.username or "", error="")


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

    @dp.message(F.contact)
    async def on_contact(m: Message) -> None:
        # «поделиться контактом» скрепкой — естественный жест на шаге телефона
        phone = (m.contact.phone_number or "") if m.contact else ""
        await _dialog(m.chat.id, phone,
                      lambda t, reply_markup=None: m.answer(t, reply_markup=reply_markup))

    @dp.message()
    async def on_other(m: Message) -> None:
        # голос/фото/стикер: раньше бот молчал — неотличимо от «бот умер»
        log.warning("Non-text message from chat %s: %s", m.chat.id, m.content_type)
        await m.answer("Vă rog scrieți mesajul ca text 🙏 / "
                       "Пожалуйста, напишите сообщение текстом 🙏")

    @dp.callback_query()
    async def on_callback(c: CallbackQuery) -> None:
        await _ack(c)
        if c.message is None:
            return
        chat_id = c.message.chat.id
        data = c.data or ""
        # рестарт стёр in-memory сессию: объясняем ТОЛЬКО если кнопка из середины
        # флоу записи; rem_ok/cancel:/меню и т.п. стейтлесс — работают и так
        _MIDFLOW = ("svc:", "doc:", "day:", "time:", "confirm", "change", "skip_year")
        if not eng.session_alive(f"tg:{chat_id}") and data.startswith(_MIDFLOW):
            try:
                await c.message.answer("Sesiunea s-a întrerupt — să reluăm de la început 🙏 / "
                                       "Сессия прервалась — начнём сначала 🙏")
            except Exception as e:  # noqa: BLE001
                log.warning("Send FAILED to chat %s: %r", chat_id, e)
        await _dialog(chat_id, data,
                      lambda t, reply_markup=None: c.message.answer(t, reply_markup=reply_markup))

    try:
        me = await bot.get_me()
    except Exception as e:  # noqa: BLE001 — токен с опечаткой: сказать, а не молчать
        _note_fail(e)
        raise
    STATUS.update(running=True, username=me.username or "", error="")
    log.warning("Telegram adapter: polling started as @%s", me.username)
    global _BOT, _LOOP
    _BOT, _LOOP = bot, asyncio.get_running_loop()
    asyncio.create_task(_apply_meta(bot))   # визитка — не задерживая поллинг
    asyncio.create_task(_reminder_loop(bot))
    asyncio.create_task(_watch(bot))        # канал жив? — иначе экран врёт
    try:
        await dp.start_polling(bot, handle_signals=False)
    except Exception as e:  # noqa: BLE001 — поллинг всё-таки упал: это отказ
        _note_fail(e)
        raise
    finally:
        STATUS["running"] = False
        _BOT = None
