"""Находки ревью волны 3 (08-16): канал бота и веб-чат.

Канал заморожен 08-08, но КОД ЖИВ и работает у grandfather-установок
(канарейка Олега), поэтому четыре дефекта чинятся, а не откладываются:

  * /chat принимал session_id ОТ КЛИЕНТА, а session_key — единственное
    удостоверение пациента в движке: по угадываемому ключу `manual:<цифры
    телефона>` посторонний видел и отменял чужие визиты и переписывал имя
    в чужой фише;
  * `await c.answer()` стоял вне try: нажатие, доехавшее после ночного
    простоя, отвечает «query is too old», aiogram гасит исключение — и
    отмена записи пропадает молча;
  * перенос визита не снимал reminded_day: суточное напоминание с НОВЫМ
    временем не уходило, а журнал продолжал показывать «Reminder trimis»;
  * отказ адаптера не попадал в STATUS: при отозванном токене экран говорил
    «activ», при неверном — вечное «pornire…», а причина уезжала в print,
    которого в собранной программе нет.

⚠️ Три из четырёх проверяются ВНЕ сервера: адаптер живёт в aiogram-петле, а
не в HTTP-маршруте. Отдельный процесс — тем же приёмом, что «чистые функции»
в test_admin: окружение наследуется целиком, иначе Windows не грузит winsock.
"""
import ast
import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
from datetime import date, timedelta

from harness import BOT, PYTHON, TG_ON, Bot, Client, Result, Server

TELEGRAM_PY = BOT / "app" / "telegram.py"

# Знаки, которые рисует система: те же диапазоны, что стережёт
# test_structure._SYSGLYPH. Строка состояния канала уезжает на экран журнала,
# а не в Telegram, — значит на неё правило карты распространяется.
_SYSGLYPH = re.compile("[🀀-🫿←-⇿∀-⋿⌀-⏿"
                       "■-➿⬀-⯿]")


def _d(offset: int) -> str:
    return (date.today() + timedelta(days=offset)).isoformat()


def _answers(node: ast.AST) -> list[int]:
    """Строки, где зовут `c.answer()` — гашение «часиков» на кнопке."""
    return [n.lineno for n in ast.walk(node)
            if isinstance(n, ast.Attribute) and n.attr == "answer"
            and isinstance(n.value, ast.Name) and n.value.id == "c"]


def _in_app(res: Result, label: str, code: str, env: dict | None = None) -> dict:
    """Запустить кусок кода внутри пакета app и вернуть напечатанный им JSON."""
    e = dict(os.environ)
    e.update(env or {})
    p = subprocess.run([str(PYTHON), "-c", code % str(BOT)], cwd=str(BOT),
                       text=True, capture_output=True, env=e)
    if p.returncode != 0:
        res.failed.append((label, p.stderr.strip()[-400:]))
        return {}
    try:
        return json.loads(p.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        res.failed.append((label, f"не JSON: {p.stdout[-300:]!r}"))
        return {}


# ---------- 1. /chat: ключ сессии выдаёт сервер ----------

def suite_chat_session(res: Result) -> None:
    """Чужой session_key не открывает ни записи, ни фишу.

    Ключи рецепции строятся как `manual:<цифры телефона>` (db.admin_add), то
    есть угадываются с первого раза. Пока /chat брал ключ из тела запроса, это
    был готовый вход в чужую карточку — у клиники с ботом и доступом из сети
    (второй компьютер) и в облачном демо, открытом наружу.
    """
    with Server(env=TG_ON) as s:
        adm = Client(s.url).login()
        res.check("визит регистратуры заведён",
                  adm.post("/admin/add", adate=_d(1), atime="10:00",
                           adoctor="d2", aservice="consult",
                           aname="Ion Popescu", aphone="069123456",
                           back="/admin/all").msg, "ok")

        anon = Client(s.url)          # ни одной куки, без входа

        def chat(msg: str, session: str = "", key: str = "") -> dict:
            body = {"message": msg, "session": session, "session_id": key}
            return json.loads(anon.post_json("/chat", body).body)

        stolen = chat("my", key="manual:069123456")
        texts = " | ".join(m["text"] for m in stolen["messages"])
        res.ok("чужой ключ не показывает записи", "10:00" not in texts,
               f"ответ: {texts[:200]}")
        btns = [b["value"] for row in stolen.get("buttons", []) for b in row]
        res.ok("чужой ключ не даёт кнопку отмены",
               not [b for b in btns if b.startswith("cancel:")], f"кнопки: {btns}")
        for appt_id in (1, 2, 3):
            chat(f"cancel:{appt_id}", key="manual:069123456")
        res.check("час так и остался занятым",
                  adm.post("/admin/add", adate=_d(1), atime="10:00",
                           adoctor="d2", aservice="consult", aname="Al Doilea",
                           aphone="069000111", back="/admin/all").msg, "conflict")

        # --- две ЧЕСТНЫЕ сессии не видят друг друга ---
        a, b = Bot(Client(s.url)), Bot(Client(s.url))
        for step in ("/start", "lang:ro", "book", "svc:consult", "doc:d2",
                     f"day:{_d(1)}", f"time:{_d(1)}T14:00", "Ana Web",
                     "skip_year", "069222333", "confirm"):
            texts, _ = a.say(step)
        res.ok("сессия A записалась", "14:00" in texts, f"ответ: {texts[:160]}")
        mine, buttons = a.say("my")
        res.ok("сессия A видит СВОЮ запись", "14:00" in mine, f"ответ: {mine[:160]}")
        cancels = [x for x in buttons if x.startswith("cancel:")]
        res.ok("у сессии A есть кнопка отмены", bool(cancels), f"кнопки: {buttons}")

        b.say("/start")
        b.say("lang:ro")
        other, _ = b.say("my")
        res.ok("сессия B чужих записей не видит", "14:00" not in other,
               f"ответ: {other[:160]}")
        if cancels:
            b.say(cancels[0])
            still, _ = a.say("my")
            res.ok("сессия B не отменила запись сессии A", "14:00" in still,
                   f"ответ: {still[:160]}")

        # выданный токен не подделать: подпись считается секретом клиники
        forged = json.loads(anon.post_json(
            "/chat", {"session": "deadbeef.00", "message": "my"}).body)
        res.ok("токен с чужой подписью начинает новую сессию",
               forged.get("session", "").split(".")[0] != "deadbeef",
               f"сервер принял подделку: {forged.get('session')!r}")


# ---------- 2. кнопка из вчерашнего напоминания ----------

_ACK_CODE = """
import asyncio, json, sys
sys.path.insert(0, %r)
from app import telegram as tg


class Stale:
    data = "cancel:57"

    async def answer(self):
        raise RuntimeError("query is too old and response timeout expired")


async def main():
    await tg._ack(Stale())          # обработчик обязан пережить отказ

asyncio.run(main())
print(json.dumps({"survived": True}))
"""


def suite_callback_ack(res: Result) -> None:
    """Отказ answerCallbackQuery не уносит обработчик кнопки.

    Программу клиники закрывают на ночь, а Telegram держит апдейты сутки: то,
    что пациент нажал в 21:00, приезжает в 08:30 уже устаревшим. Голый
    `await c.answer()` падал на этом первой же строкой, aiogram писал строку в
    лог и брался за следующий апдейт — отмена визита пропадала молча.
    """
    got = _in_app(res, "гашение «часиков» не роняет обработчик", _ACK_CODE)
    res.ok("отказ answerCallbackQuery пережит", got.get("survived") is True,
           "«часики» унесли обработчик кнопки")
    # ⚠️ Мало того, что _ack умеет молчать: обработчик обязан звать ИМЕННО его.
    # Вернувшийся в on_callback голый вызов уронит всё то же самое, а первая
    # проверка этого не увидит — она смотрит на helper, а не на вызывающего.
    src = TELEGRAM_PY.read_text(encoding="utf-8")
    fns = {n.name: n for n in ast.walk(ast.parse(src))
           if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    res.ok("обработчик не гасит «часики» сам",
           "on_callback" in fns and not _answers(fns["on_callback"]),
           "await c.answer() снова стоит в on_callback, вне try")
    res.ok("обработчик гасит «часики» через _ack", "await _ack(c)" in src,
           "on_callback перестал звать _ack")
    ack = fns.get("_ack")
    res.ok("сам _ack держит вызов под try",
           ack is not None and any(_answers(t) for t in ast.walk(ack)
                                   if isinstance(t, ast.Try)),
           "_ack зовёт answer() вне try — отказ снова уйдёт наверх")


# ---------- 3. перенос визита и суточное напоминание ----------

_MOVE_CODE = """
import asyncio, json, sys
sys.path.insert(0, %r)
from datetime import datetime, timedelta, timezone
from app import db


async def flags(appt_id):
    r = await db._fetch(
        "SELECT reminded_day, reminded_2h FROM appointments WHERE id = $1",
        "SELECT reminded_day, reminded_2h FROM appointments WHERE id = ?", appt_id)
    return [int(r[0]["reminded_day"]), int(r[0]["reminded_2h"])]


async def main():
    await db.init()
    start = (datetime.now(timezone.utc) + timedelta(days=1)).replace(
        minute=0, second=0, microsecond=0)
    aid = await db.create_appointment(
        "tg:900777", "Ion Mutat", "069700700", "ro", "Consultatie",
        "Dr. Activ Doi", start, source="bot", doctor_id="d2")
    await db.mark_reminded(aid, day=True, soon=False)
    out = {"marked": await flags(aid)}
    out["moved"] = await db.move_appointment(
        aid, "d2", "Dr. Activ Doi", start + timedelta(hours=26), when="test")
    out["after_time"] = await flags(aid)
    await db.mark_reminded(aid, day=True, soon=False)
    out["same_hour"] = await db.move_appointment(
        aid, "d3", "Dr. Activ Trei", start + timedelta(hours=26), when="test")
    out["after_doctor"] = await flags(aid)
    print(json.dumps(out))
    await db._CONN.close()   # иначе поток aiosqlite не даёт процессу выйти

asyncio.run(main())
"""


def suite_move_reminder(res: Result) -> None:
    """Перенос ВРЕМЕНИ снимает отметку напоминания, перенос врача — нет."""
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="dp_move_"))
    try:
        got = _in_app(res, "перенос визита: отметки напоминаний", _MOVE_CODE,
                      {"DATABASE_URL": f"sqlite:///{tmp / 'dental.db'}"})
        if not got:
            return
        res.check("напоминание отмечено", got["marked"], [1, 0])
        res.check("перенос принят", got["moved"], "")
        res.check("перенос часа снял отметку", got["after_time"], [0, 0])
        res.check("перенос к другому врачу принят", got["same_hour"], "")
        res.ok("тот же час — отметка на месте", got["after_doctor"] == [1, 0],
               f"флаги после смены врача: {got['after_doctor']}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------- 4. состояние канала на странице «Stare sistem» ----------

_STATUS_CODE = """
import asyncio, json, sys
sys.path.insert(0, %r)
from aiogram.exceptions import TelegramUnauthorizedError
from app import telegram as tg


class Revoked:
    def __init__(self, *a, **kw):
        pass

    async def get_me(self):
        raise TelegramUnauthorizedError(method=None, message="Unauthorized")


tg.Bot = Revoked
out = {}
try:
    asyncio.run(tg.run("123456:AAtoken-de-test-care-nu-exista"))
except Exception:
    pass
out["start_running"] = tg.STATUS["running"]
out["start_error"] = tg.STATUS["error"]

# канал умер ПОСЛЕ старта: поллинг ретраит вечно, статус обязан догнать
tg._WATCH_TICK = 0.05
tg.STATUS.update(running=True, username="clinica_bot", error="")


async def watch():
    t = asyncio.create_task(tg._watch(Revoked()))
    await asyncio.sleep(0.4)
    t.cancel()

asyncio.run(watch())
out["live_running"] = tg.STATUS["running"]
out["live_error"] = tg.STATUS["error"]
print(json.dumps(out))
"""


def suite_tg_status(res: Result) -> None:
    """Отозванный и неверный токен видны клинике, а не только логу aiogram."""
    got = _in_app(res, "состояние канала Telegram", _STATUS_CODE)
    if not got:
        return
    res.check("неверный токен: канал не «запускается» вечно",
              got["start_running"], False)
    res.ok("неверный токен назван причиной", bool(got["start_error"]),
           "поле error пустое — экран покажет «pornire…» навсегда")
    res.check("отозванный токен снимает «activ»", got["live_running"], False)
    res.ok("отозванный токен назван причиной", "token" in got["live_error"],
           f"текст состояния: {got['live_error']!r}")
    res.ok("причина без знаков, которые рисует Windows",
           not _SYSGLYPH.search(got["live_error"]),
           f"текст состояния: {got['live_error']!r}")
