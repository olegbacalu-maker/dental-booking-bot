"""Шифрование картотеки: состояние раздела и его проза.

Раздел устроен НЕОБЫЧНО для настроек, и это намеренно: включение идёт в два
шага через отдельную печатную страницу с листом восстановления. Разбор — в
`routes.settings_crypt`; здесь то, что нужно знать, правя этот файл.

⭐ Проза собрана КУСКАМИ, как у `lan.py` и по той же причине: старая страница
склеивает их со своими формами, JSON API отдаёт те же куски React-экрану,
который рисует кнопки сам. Текст, объясняющий директору, чем он рискует,
обязан быть ОДНИМ — разойдись две копии, и одна из них однажды пообещает не то.

⛔ Лист восстановления (`/admin/settings/crypt/sheet`) остаётся СЕРВЕРНЫМ и в
куски не разбирается: это печатный документ со своим `<!doctype>` и `@media
print`, а печать в React не переносится (migration-plan). Он же обязан
открываться, когда бандл не загрузился, — иначе код, без которого база не
откроется никогда, показать будет нечем.

⚠️ Состояния ровно три. Четвёртого — `dbkey.UNREADABLE` — на этой странице не
бывает: ключ, не читаемый на этой машине, переводит программу в режим
восстановления при старте, и `/admin/*` туда не пускает (`main._recovery_gate`).
"""
from __future__ import annotations

import pathlib

from ... import db
from ...core import dbkey
from ...core.layout import _ic

# Что показывает раздел. `CLOUD` — не состояние шифрования, а издание: у
# облака файла базы нет вовсе, и разговаривать не о чем.
CLOUD, OFF, PENDING, ON = "cloud", "off", "pending", "on"


def state(data_dir: pathlib.Path | None) -> str:
    """Состояние раздела — ОДНА функция на старую страницу и на JSON.

    ⚠️ Порядок веток значим: заказ (pending-файл) старше включённого ключа —
    клиника, заказавшая расшифровку, ещё зашифрована, и сказать ей «активна»
    значило бы спрятать тот факт, что она уже нажала «остановить».
    """
    if not db.IS_SQLITE:
        return CLOUD
    if data_dir and (data_dir / dbkey.PENDING_FILE).exists():
        return PENDING
    return ON if dbkey.state(data_dir) == dbkey.OK else OFF


def cloud_html() -> str:
    return ("<p class='hint'>Ediția cloud folosește PostgreSQL — criptarea "
            "fișierului nu se aplică.</p>")


def pending_html() -> str:
    return ("<div class='banner warn'>Criptarea este pregătită și se aplică "
            "la următoarea pornire a programului.</div>")


def on_html() -> str:
    return ("<div class='banner ok'>Evidența este criptată. Fișierul "
            "<b>dental.db</b> nu poate fi citit pe alt calculator sau de pe "
            "alt cont Windows.</div>")


def on_note_html() -> str:
    """Чем архив отличается от картотеки — вопрос, который директор задаёт
    сразу после включения: «а копии тоже?»."""
    return ("<p class='hint'>Copiile zilnice din <code>data\\backups</code> "
            "sunt și ele criptate. Arhiva de rezervă (Setări › Copie de "
            "rezervă) rămâne independentă: înăuntru baza este necriptată, "
            "protejată de parola arhivei — ca să nu depindă de aceeași "
            "cheie.</p>")


def off_html() -> str:
    """⚠️ Тон здесь — РЕШЕНИЕ Олега (08-09): шифрование это ОПЦИЯ, а не
    рекомендация. Требование закона 195 закрывает BitLocker, и программа его
    проверяет сама; клинике, которая включит шифрование, достаётся обязанность
    хранить лист восстановления. Уговаривать её взять эту обязанность не за
    что — раздел обязан честно назвать и то, что оно даёт, и то, чего стоит,
    а выбор оставить директору."""
    return ("<div class='banner ok'>Nu este obligatorie. Cerința Legii 195 "
            "este acoperită de criptarea discului (BitLocker) — starea ei o "
            "verifică programul singur, în <b>Stare sistem</b>. Aceasta este "
            "o măsură în plus, pentru cine o dorește.</div>")


def what_html() -> str:
    return ("<p class='hint'><b>Ce face.</b> Acum <b>data\\dental.db</b> este "
            "o bază SQLite obișnuită: copiată de pe calculator, se deschide "
            "cu orice program. Criptarea o face inutilizabilă în afara "
            "acestui calculator. Are sens mai ales dacă programul stă pe un "
            "laptop care iese din clinică.</p>")


def cost_html() -> str:
    return ("<p class='hint'><b>Ce cere în schimb.</b> Cheia este legată de "
            "contul Windows de pe acest calculator. După reinstalarea Windows "
            "sau la schimbarea calculatorului evidența se deschide "
            "<b>numai</b> cu codul de pe foaia de recuperare — foaia devine "
            "responsabilitatea clinicii, iar pierderea ei nu poate fi "
            "reparată de nimeni, nici de noi. De aceea pasul următor este "
            "tipărirea ei.</p>")


def limit_html() -> str:
    return ("<p class='hint'><b>Ce NU face.</b> Nu vă apără de cineva care "
            "lucrează la acest calculator sub acest cont Windows. Acolo "
            "lucrează parola de intrare și blocarea ecranului (Win+L).</p>")


def blocks(st: str) -> dict[str, str]:
    """Проза состояния — то же, что видит старая страница, кусками.

    ⚠️ Ключи ФИКСИРОВАННЫЕ, пустая строка значит «в этом состоянии блока нет».
    Так клиент не угадывает состав по наличию ключа, а сторож паритета
    сравнивает куски со старой страницей по именам.
    """
    return {
        "status": {CLOUD: cloud_html(), PENDING: pending_html(),
                   ON: on_html()}.get(st, off_html()),
        "what": what_html() if st == OFF else "",
        "cost": cost_html() if st == OFF else "",
        "limit": limit_html() if st == OFF else "",
        "note": on_note_html() if st == ON else "",
    }


# Кнопки старой страницы. React рисует свои — ему уезжает только проза.
_SHEET_LINK = (f"<div class='nav'><a class='primary' "
               f"href='/admin/settings/crypt/sheet'>{_ic('print')} "
               f"Deschide foaia de recuperare</a></div>")
_SHEET_LINK_ON = (f"<div class='nav'><a href='/admin/settings/crypt/sheet'>"
                  f"{_ic('print')} Foaia de recuperare</a></div>")
_OFF_FORM = ("<form method='post' action='/admin/settings/crypt/off' "
             "onsubmit=\"return confirm('Evidența va fi decriptată la "
             "următoarea pornire. Continuați?')\">"
             "<button class='rowdel'>Oprește criptarea</button></form>")
_PREPARE_FORM = ("<form method='post' action='/admin/settings/crypt/prepare'>"
                 "<button class='savebtn'>Pregătește criptarea ›</button>"
                 "</form>")


def render(st: str) -> str:
    """Тело старой страницы. Заголовок у облачной ветки не печатается — там
    и раздела нет, только объяснение, почему его нет."""
    if st == CLOUD:
        return cloud_html()
    b = blocks(st)
    body = [f"<h2>{_ic('lock')} Criptarea evidenței</h2>", b["status"]]
    if st == PENDING:
        body.append(_SHEET_LINK)
    elif st == ON:
        body += [b["note"], _SHEET_LINK_ON, _OFF_FORM]
    else:
        body += [b["what"], b["cost"], b["limit"], _PREPARE_FORM]
    return "".join(body)


# ---- заказ шифрования ----

# Ключ, показанный на листе, но ещё НЕ заказанный. Заказ (pending-файл на
# диске) появляется только на галочке «Am tipărit foaia»: докстринг dbkey
# обещает, что включение ТРЕБУЕТ подтверждения листа, а раньше pending клал
# уже /crypt/prepare — директор закрывал страницу листа, не печатая, и
# следующий старт молча шифровал картотеку. Без листа на бумаге это потеря
# базы при первой же смене ПК. Память процесса — правильное место ровно
# потому, что перезапуск её стирает: не подтверждено = не заказано.
_SHEET_KEY: bytes | None = None

# Слово, которым экран перезапуска и JSON отвечают на выключение. ОДНО на оба:
# разойдись они, клиника прочла бы у React-экрана не то, что у старой формы.
OFF_DONE = "Criptarea va fi oprită"
ON_DONE = "Criptarea a fost activată"


def prepare(data_dir: pathlib.Path | None) -> str | None:
    """Приготовить ключ для листа. Код отказа или None — одно на форму и JSON.

    ⛔ Второе нажатие НЕ создаёт новый ключ (найдено враждебным ревью 08-09).
    Раньше оно перезаписывало ожидающий ключ, и напечатанный лист переставал
    подходить; а нажатие при УЖЕ включённом шифровании было хуже вдвойне:
    заказ на переезд не мог выполниться никогда (база под старым ключом),
    экран навсегда застревал на «криптование подготовлено», а лист печатался
    с ключом, который не открывает ничего. Прежний ключ при этом становился
    недоступен для печати. Открытая в соседней вкладке страница — обычное
    дело в регистратуре, так что это не теоретический случай.
    """
    global _SHEET_KEY
    if not data_dir:
        return "bad_crypt"
    if dbkey.enabled(data_dir):
        return "crypt_on"
    if dbkey.load_pending(data_dir) is None and _SHEET_KEY is None:
        _SHEET_KEY = dbkey.generate()
    return None


def key_for_sheet(data_dir: pathlib.Path | None) -> tuple[bytes | None, bool]:
    """Что печатать на листе и нужно ли под ним подтверждение.

    Порядок источников: заказ на диске, показанный-но-не-подтверждённый ключ
    процесса, действующий ключ. Подтверждение нужно обоим незавершённым
    состояниям и не нужно листу уже работающего шифрования.
    """
    key = None
    if data_dir and (data_dir / dbkey.PENDING_FILE).exists():
        key = dbkey.load_pending(data_dir)
    if key is None and not dbkey.enabled(data_dir):
        key = _SHEET_KEY
    if key is None:
        key = dbkey.load()
    pending = bool(data_dir and ((data_dir / dbkey.PENDING_FILE).exists()
                                 or (_SHEET_KEY is not None
                                     and not dbkey.enabled(data_dir))))
    return key, pending


def confirm(data_dir: pathlib.Path | None) -> str | None:
    """Галочка «лист напечатан»: кладём заказ. Код отказа или None.

    ⭐ Заказ (pending-файл) кладётся ИМЕННО ЗДЕСЬ, а не в `prepare`: закрытая
    без подтверждения страница листа не должна оставлять на диске ничего, что
    следующий старт исполнит как приказ шифровать. Ключ заказа — ровно тот,
    что напечатан на листе.
    """
    global _SHEET_KEY
    if not data_dir:
        return "bad_crypt"
    if not dbkey.enabled(data_dir) and dbkey.load_pending(data_dir) is None:
        if _SHEET_KEY is None or not dbkey.request_encrypt(data_dir, _SHEET_KEY):
            return "bad_crypt"
    _SHEET_KEY = None
    return None


def turn_off(data_dir: pathlib.Path | None) -> str | None:
    """Заказать расшифровку. Сам переезд делает ЛАУНЧЕР до старта приложения:
    базу нельзя подменять под открытым соединением — подмена файла с
    `-wal`/`-shm` даёт порчу, которая всплывает часами позже."""
    if not data_dir:
        return "bad_crypt"
    dbkey.request_decrypt(data_dir)
    return None
