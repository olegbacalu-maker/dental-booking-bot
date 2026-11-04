"""Сигналы оболочки: баннеры-СОСТОЯНИЯ, которые `layout.shell_model` кладёт в модель
и рисует React (`AppShell`). ⛔ Баннер, не положенный в модель, не виден нигде (держит
`test_structure`). Проза серверная, доказуемо значением здесь УСЛОВИЕ показа.
"""
from __future__ import annotations

import html

from .. import db, relocate
from .. import engine as eng
from .. import update as upd
from . import demo
from . import license as lic
from . import backup_loop, sms_loop
from .auth import PERM_SETTINGS, can, request_user, tamper_alert
from .icons import _ic
from .messages import MSG_BANNER


def _update_banner() -> str:
    if upd.can_self_update():
        # в desktop-версии баннер ведёт к кнопке «Actualizează acum», не на GitHub
        return (f" · <a href='/admin/settings/system' "
                f"style='color:#e8710a;font-weight:600'>{_ic('refresh')} versiune nouă "
                f"{html.escape(upd.STATE['latest'])} — click pentru actualizare</a>")
    if upd.asset_pending() and upd.is_desktop():
        # релиз есть, установщика в нём ещё нет — честно говорим и НЕ шлём на GitHub
        return (f" · <span style='color:var(--text3)'>{_ic('refresh')} {html.escape(upd.STATE['latest'])} "
                f"se pregătește…</span>")
    if upd.newer_available():
        return (f" · <a href='{html.escape(upd.STATE['url'])}' target='_blank' "
                f"style='color:#e8710a;font-weight:600'>{_ic('refresh')} versiune nouă "
                f"{html.escape(upd.STATE['latest'])}</a>")
    return ""


def _sms_alert() -> str:
    """Подсказка треугольника у пункта меню «SMS pacienți», когда SMS мало
    (`sms_loop.low` — одно правило по штукам с экраном SMS и уведомлением у
    часов); пусто — всё в порядке. Баннера на каждом экране нет (слово Олега
    16.10 по кадру 1.43.0: «может человек не хочет продлевать»). Видит и
    регистратура — ей звонить пациентам, когда напоминания перестанут уходить."""
    lo = sms_loop.low()
    return f"{lo['title']}. {lo['text']}" if lo else ""


def _demo_banner() -> str:
    """Полоса демо (core/demo.py) — на КАЖДОМ экране, не только на входе:
    посетитель сайта обязан видеть, что данные вымышленные и сколько они живут,
    где бы он ни оказался по ссылке. Срок называет шлюз (`demo.ttl_text`).
    «Începe din nou» ведёт в шлюз демо (`/demo/…`), который и выдаёт свежую
    копию."""
    if not demo.on():
        return ""
    text = DEMO_HINT[0].replace("__TTL__", html.escape(demo.ttl_text()))
    return (f"<div class='banner warn' style='margin-bottom:14px'>{_ic('info')} "
            f"{text} <a href='/demo/reset'><b>{DEMO_HINT[1]}</b></a></div>")


# Две части одной фразы: текст и подпись ссылки сброса — источник один на
# старую страницу и на React-оболочку (та рисует готовую строку сигнала).
# __TTL__ — срок копии словами шлюза, «o oră» без него.
DEMO_HINT = ("Versiune demonstrativă: datele sunt fictive și se șterg automat "
             "după __TTL__. Nu introduceți date reale ale pacienților.",
             "Începe din nou")


def _setup_hint() -> str:
    """Пока профиль клиники — нетронутый шаблон, об этом надо говорить прямо.
    Иначе «Clinica mea» и «Medic 1» тихо доживают до первого пациента, а бот
    называет их вслух."""
    if not eng.CONFIG.get("template"):
        return ""
    return ("<div class='banner err' style='margin-bottom:14px'>"
            f"{SETUP_HINT[0]} "
            f"<a href='/admin/settings/clinic'><b>{SETUP_HINT[1]}</b></a>"
            f"{SETUP_HINT[2]}</div>")


# Три куска одной фразы: баннер каркаса оборачивает средний в ссылку, а JSON
# API отдаёт их React-экрану сплошным текстом (там ссылка на самого себя
# бессмысленна). Источник один, чтобы «datele de exemplu» не разошлось.
SETUP_HINT = ("Programul încă are datele de exemplu.",
              "Completați datele clinicii",
              " — denumire, telefon, medici, servicii și program de lucru. "
              "Ele apar în programul de lucru, în formulare și pe documentele "
              "tipărite.")


def _tamper_banner() -> str:
    """Предупреждение «auth.json трогали вне программы» — только директору:
    остальные не могут ни оценить «это был техник», ни сменить PIN-ы, и для
    них баннер был бы просто страшилкой без кнопки действия."""
    txt = tamper_alert()
    if not txt:
        return ""
    me = request_user()
    if me is not None and not can(me, PERM_SETTINGS):
        return ""
    # Тем же каналом едут события лаунчера (`orders.report_done`, 02.11:
    # расшифровка, восстановление, отвергнутый заказ) — со своими словами.
    # Совет про PIN — только при самом сигнале auth.json.
    advice = (" Dacă nu a fost o intervenție cunoscută (resetarea unui PIN uitat, "
              "tehnicianul clinicii), schimbați PIN-urile în Setări › Utilizatori "
              "și verificați jurnalul de acces." if "auth.json" in txt else "")
    return (f"<div class='banner err' style='margin-bottom:14px'>{_ic('shield')} {html.escape(txt)}."
            f"{advice}"
            "<form method='post' action='/admin/security/ack' "
            "style='display:inline;margin-left:12px'>"
            "<button style='background:none;border:1px solid currentColor;"
            "border-radius:8px;padding:4px 12px;cursor:pointer;color:inherit;"
            "font-size:13px'>Am luat la cunoștință</button></form></div>")


def _backup_banner() -> str:
    """Копии картотеки (17.10): локальная не удалась, внешняя не удалась или
    старше `backup_loop.STALE_DAYS` — янтарная строка ДИРЕКТОРУ на каждом
    экране, ведёт к настройке. Регистратуре не показывается: папку и пароль
    меняет тот, у кого есть права на настройки. Текст — `backup_loop.alert()`,
    тот же, что видит Stare sistem; условие сторож сверяет значением."""
    txt = backup_loop.alert()
    if not txt or demo.on():
        return ""
    me = request_user()
    if me is not None and not can(me, PERM_SETTINGS):
        return ""
    # один значок — треугольник `.banner.warn` (Олег 02.11), без дискеты
    return (f"<div class='banner warn' style='margin-bottom:14px'>"
            f"{html.escape(txt)}. <a href='/admin/settings/backup'><b>Copie de "
            f"rezervă</b></a></div>")


def _lic_date(d) -> str:
    return d.astimezone(eng.TZ).strftime("%d.%m.%Y")


def _license_until() -> str:
    """Срок файла лицензии для «Despre» — та же дата, что «Valabil până la»
    страницы лицензии (`claim.valid_until`). Пусто, когда файла нет или
    лицензия в этой сборке не проверяется (`lic.applies()`)."""
    s = lic.current()
    if s is None or not lic.applies() or s.claim is None:
        return ""
    return _lic_date(s.claim.valid_until)
# Почему лицензии нет — словами про лицензию, не про файл (02.10): клиника файла
# не видит, а код состояния у программы остаётся кодом файла на диске.
_LIC_WHY = {"": "nu a fost găsită pe acest calculator",
            "license_malformed": "de pe acest calculator este deteriorată",
            "license_bad_signature": "de pe acest calculator este deteriorată",
            "license_key_unknown": "a fost emisă cu o cheie pe care această versiune a programului nu o cunoaște",
            "license_older": "de pe acest calculator este mai veche decât cea activată"}


def _lic_why(code: str) -> str:
    return _LIC_WHY.get(code or "", MSG_BANNER.get(code, ("err", code))[1].split(" — ")[0].lower())


def _license_banner() -> str:
    """Лицензия (L5): льгота — директору, режим чтения — всем.

    Сосед `_tamper_banner`: тот же принцип «баннер, не стена» из
    split-contract и та же оговорка про `me is not None`. Без единого ключа
    выдачи (`lic.applies()`: исходники, песочница, exe до боевого ключа)
    баннера нет — иначе каждая страница разработчика кричала бы о файле,
    которого взять неоткуда."""
    s = lic.current()
    if s is None or not lic.applies() or s.state not in (lic.st.GRACE, lic.st.READONLY):
        return ""
    me = request_user()
    if s.state == lic.st.GRACE and me is not None and not can(me, PERM_SETTINGS):
        return ""
    link = "<a href='/admin/license'>Licență</a>"
    # «Plătește acum» (02.10) — директору, когда у файла есть свой сервер:
    # ссылка в системный браузер с ключом (`lic.pay_ticket`, см. маршрут /plata)
    pay = (s.claim is not None and lic.pay_available()
           and me is not None and can(me, PERM_SETTINGS))
    act = "achitați abonamentul" if pay else "activați abonamentul"
    if pay:
        link = (f"<a href='/plata/{lic.pay_ticket()}' target='_blank' rel='noopener'>"
                f"Plătește acum</a> · {link}")
    if s.claim is None:
        head = f"Licența {'lipsește' if not s.code else _lic_why(s.code)}."
        until = (f" Programul funcționează încă până la {_lic_date(s.grace_until)}"
                 if s.state == lic.st.GRACE else
                 f" Programul este în regim de citire din {_lic_date(s.grace_until)}")
        text = head + until + f"; pentru a continua, activați licența — {link}."
    elif s.state == lic.st.GRACE:
        text = (f"Abonamentul a expirat la {_lic_date(s.valid_until)}. Programul "
                f"funcționează încă până la {_lic_date(s.grace_until)}; pentru a continua "
                f"fără întrerupere, {act} — {link}.")
    else:
        text = (f"Programul este în regim de citire: abonamentul a expirat la "
                f"{_lic_date(s.valid_until)}. Datele se pot consulta, tipări și exporta; "
                f"pentru a continua lucrul, {act} — {link}.")
    cls = "warn" if s.state == lic.st.GRACE else "err"
    return f"<div class='banner {cls}' style='margin-bottom:14px'>{_ic('key')} {text}</div>"


def _mail_banner() -> str:
    """E-mail клиники не подтверждён (27.10, Олег через координатора): короткая янтарная строка
    ДИРЕКТОРУ на каждом экране, ссылка на страницу лицензии и «Mai târziu» — неделя тишины
    (`lic.mail_later`). Едет в сигнале `license` вслед за его баннером: тот же предмет, своего места
    в каркасе не заводим. Не знаем состояния — молчим (`lic.mail_banner_due`). ⛔ Ничего не запирает."""
    if not lic.mail_banner_due() or demo.on():
        return ""
    me = request_user()
    if me is not None and not can(me, PERM_SETTINGS):
        return ""
    box = lic.mailbox() or {}
    return (f"<div class='banner warn' style='margin-bottom:14px'>{_ic('mail')} "
            f"Adresa de e-mail a clinicii <b>{html.escape(box.get('email') or '')}</b> nu este "
            f"confirmată: pe ea vin codurile și notele de plată. "
            f"<a href='/admin/license'><b>Confirmați în Licență</b></a>"
            f"<form method='post' action='/admin/license/email/later' "
            f"style='display:inline;margin-left:12px'>"
            f"<button style='background:none;border:1px solid currentColor;"
            f"border-radius:8px;padding:4px 12px;cursor:pointer;color:inherit;"
            f"font-size:13px'>Mai târziu</button></form></div>")


def _terms_banner() -> str:
    """Условия обновились (29.10, план § 3.2): TERMS_VERSION программы новее принятой клиникой — янтарная
    строка ДИРЕКТОРУ с ссылкой на текст, галочкой и «Accept» (`/admin/license/terms`). Едет в сигнале
    `license` вслед за его баннерами — тот же предмет. ⛔ Уведомление, не замок (условия § 13): запись
    работает и без ответа; `lic.terms_due` молчит без лицензии и в режиме чтения."""
    if not lic.terms_due() or demo.on():
        return ""
    me = request_user()
    if me is not None and not can(me, PERM_SETTINGS):
        return ""
    was = lic.terms_accepted()
    before = f" (versiunea acceptată de clinică: {html.escape(was)})" if was else ""
    return (f"<div class='banner warn' style='margin-bottom:14px'>{_ic('key')} "
            f"Termenii și condițiile DentPilot s-au actualizat ({html.escape(lic.TERMS_VERSION)}){before}. "
            f"<a href='{lic.TERMS_URL}' target='_blank' rel='noopener'><b>Citiți versiunea nouă</b></a>"
            f"<form method='post' action='/admin/license/terms' "
            f"style='display:inline-flex;align-items:center;gap:8px;margin-left:12px'>"
            f"<label style='display:inline-flex;align-items:center;gap:6px;cursor:pointer'>"
            f"<input type='checkbox' name='terms' value='1' required style='margin:0'> Am citit și accept</label>"
            f"<button style='background:none;border:1px solid currentColor;border-radius:8px;padding:4px 12px;"
            f"cursor:pointer;color:inherit;font-size:13px'>Accept</button></form></div>")


def _split_banner() -> str:
    """На машине ДВЕ картотеки — вопрос к директору, но НЕ стена.

    ⛔ Противоположность режиму восстановления, хотя экран у них одного класса.
    Восстановление перекрывает весь `/admin`, потому что показывать нечего: база не
    открывается. Здесь показывать ЕСТЬ что — в назначении лежит рабочая
    картотека, клиника в ней уже принимает, — и стена закрыла бы её на день
    ради конфликта, который терпит до вечера.

    Родственник тут `_slot_banner`, а не сигнализация auth.json: гасить вручную
    нечем и не нужно. Как только человек ответил, ответ ложится в
    `migration.json`, и ближайшая же страница открывается без баннера — кнопка
    «понятно» здесь врала бы, что вопрос закрыт.
    """
    if relocate.split_pending() is None:
        return ""
    me = request_user()
    # ⚠️ Условие ровно такое же, как у соседей, и `me is not None` в нём не
    # лишнее: без него баннер пропадал бы у всякого, кого не опознали, — а это
    # каждая страница до того, как в клинике заведён первый PIN. Ровно та
    # машина, на которой раздвоение и случается.
    if me is not None and not can(me, PERM_SETTINGS):
        return ""
    return (f"<div class='banner warn' style='margin-bottom:14px'>{_ic('folder')} "
            f"Pe acest calculator sunt două fișe de pacienți. Programul lucrează "
            f"în cea curentă; care este cea reală decideți dumneavoastră — "
            f"<a href='/admin/migration'>Două fișe de pacienți</a>. "
            f"Nicio fișă nu este ștearsă până atunci.</div>")


def _slot_banner() -> str:
    """Страховка от двойной брони встала не полностью — что именно развести.

    Тем же приёмом, что и сигнализация auth.json: метка в schema_meta, состояние
    в процессе, баннер директору. Разница одна — гасить его вручную нечем и не
    нужно: как только записи разведены, ближайший старт кладёт широкие индексы
    и баннер исчезает сам (кнопка «понятно» тут врала бы, что вопрос закрыт).
    ⛔ Молчать нельзя: программа стартовала, экраны целы, и без этой строки
    клиника узнала бы о неполной защите только второй записью на тот же час.
    """
    g = db.slot_guard()
    if not g.get("pending"):
        return ""
    me = request_user()
    if me is not None and not can(me, PERM_SETTINGS):
        return ""
    rows = g.get("rows") or []
    # ⚠️ Типы считаются по ВСЕМУ списку, а не по восьми показанным: совет для
    # пациента нужен и тогда, когда пациентские строки не влезли в обрезку —
    # иначе директор чинил бы девятую строку по инструкции для первой.
    kinds = {"pacient" if r.get("kind") == "pacient" else "medic" for r in rows}
    items = []
    for r in rows[:8]:
        when = r.get("when")
        # час в базе UTC, читает его человек: без astimezone визит на 09:00
        # напечатался бы как 06:00 — и директор искал бы не тот слот
        if hasattr(when, "strftime"):
            if getattr(when, "tzinfo", None) is not None:
                when = when.astimezone(eng.TZ)
            stamp = when.strftime("%d.%m.%Y %H:%M")
        else:
            stamp = str(when or "")
        kind = "pacient" if r.get("kind") == "pacient" else "medic"
        # ⛔ Без пометки типа список врёт: имя пациента, стоящее в одном столбце
        # с именами врачей, читается как ещё один врач, и директор идёт чинить
        # не то. Тип приезжает из запроса (db._slot_conflict_sql).
        items.append(f"<li><b>{'Pacient' if kind == 'pacient' else 'Medic'}:</b> "
                     f"{html.escape(str(r.get('who') or ''))} · "
                     f"{html.escape(stamp)} · "
                     f"{int(r.get('n') or 0)} programări</li>")
    if len(rows) > 8:
        items.append(f"<li>și încă {len(rows) - 8}</li>")
    # список может быть и пуст — тогда шаг упёрся не в данные, а во что-то ещё
    # (это записано в лог). Пустой <ul> выглядел бы как «баннер сломался»,
    # поэтому его просто нет, а сама строка остаётся: молчать нельзя.
    lst = f"<ul style='margin:8px 0 0 18px'>{''.join(items)}</ul>" if items else ""
    # ⛔ Совет обязан быть РАЗНЫМ по типу конфликта. Для врача годится и перенос
    # к другому медику, и другой час; для пациента перенос к другому медику НЕ
    # помогает — та же пара «пациент + час» остаётся, и менять надо ЧАС.
    how = ""
    if "medic" in kinds:
        how += (" La <b>medic</b>: mutați una dintre programări la alt medic "
                "sau la altă oră.")
    if "pacient" in kinds:
        how += (" La <b>pacient</b>: schimbați <b>ora</b> uneia dintre "
                "programări — mutarea la alt medic nu ajută, pacientul rămâne "
                "programat de două ori la aceeași oră.")
    # ⭐ Исходов ТРИ, и они не сводятся к «narrow или всё плохо». Безымянный
    # уровень читается как «не знаем», а не как «всё на месте»: ошибиться в
    # сторону лишнего вопроса можно, в сторону ложного «всё хорошо» — нет.
    level = g.get("level") or db.UQ_UNKNOWN
    narrow = level == db.UQ_NARROW
    broken = level == db.UQ_BROKEN
    if broken:
        # ⛔ Говорим ТОЛЬКО проверенное: каких проверок нет в базе и сколько
        # осталось. «Защиты нет» — приговор, которого код не выносил: у базы
        # версии ≤2 uq_doctor_slot_id нет по определению, а два остальных целы и
        # работают. Прежний текст посылал в поддержку директора, которому надо
        # было развести час, напечатанный строкой ниже (08-16).
        gone = list(g.get("gone") or [])
        left = db.UQ_SLOT_COUNT - len(gone)
        # ⚠️ Согласование числа с существительным — не косметика: «lipsesc 1
        # verificări» читается как машинный текст ровно там, где от строки
        # требуется доверие директора.
        if not left:
            # ⛔ «Тот же час можно занять дважды» — утверждение, которого код не
            # проверял, и программа его ОПРОВЕРГАЕТ: вторую запись в занятый час
            # отбивает прикладная проверка под `db._BOOK_LOCK`, а уникальные
            # индексы — ВТОРОЙ пояс. Измерено на базе без единого индекса: журнал
            # ответил «conflict» на второго пациента в занятый час врача и «dup»
            # на того же пациента у другого врача — ни одна двойная запись не
            # прошла (08-16). Пугать сильнее, чем есть, — тот же класс, что и
            # «защиты нет»: директор читает про свою программу неправду ровно
            # там, где от строки требуется доверие. Говорим проверенное.
            what = (f"niciuna dintre cele {db.UQ_SLOT_COUNT} verificări nu este "
                    "în evidență — programul refuză în continuare a doua "
                    "programare la aceeași oră, dar verificarea de rezervă din "
                    "baza de date lipsește")
        else:
            miss = (f"lipsește din evidență o verificare ({db.uq_gone_ro(gone)})"
                    if len(gone) == 1 else
                    f"lipsesc din evidență {len(gone)} verificări "
                    f"({db.uq_gone_ro(gone)})")
            rest = ("cealaltă verificare lucrează" if left == 1
                    else f"celelalte {left} verificări lucrează")
            what = f"{miss}, {rest}"
        head = ("<b>Protecția împotriva programărilor duble nu este completă</b>"
                f" — {what}.")
    elif not narrow:
        # ⛔ Состояние ПРОЧИТАТЬ НЕ УДАЛОСЬ — и это всё, что можно сказать.
        # Пустой ответ базы прежде считался за «в базе нет ни одной проверки», и
        # директор читал самый страшный текст на картотеке, где все проверки
        # целы и работают. Разница не в тоне: «нет защиты» — утверждение,
        # которое кто-то должен был проверить, а тут его никто не проверял.
        head = ("<b>Starea protecției împotriva programărilor duble nu a putut "
                "fi citită</b> — programul nu știe câte verificări sunt în "
                "evidență. Programările se fac ca de obicei.")
    else:
        # ⛔ Причину называем ту, которая есть. Список конфликтов может быть и
        # пуст — тогда шаг упёрся не в данные (это в логе), и фраза «există ore
        # cu mai multe programări active» была бы выдумкой про картотеку.
        # ⚠️ «Проверено» относится ровно к тому, что прочитано в базе: все три
        # проверки на месте. Обещать «защита та же, что была» код не вправе —
        # он сравнивает не с прошлым состоянием, а с текущим (08-16).
        head = ("Protecția împotriva programărilor duble nu a putut fi extinsă: "
                + ("în evidență există ore cu mai multe programări active"
                   if rows else "operația nu s-a încheiat") +
                ". Programul lucrează normal, iar toate cele "
                f"{db.UQ_SLOT_COUNT} verificări sunt în evidență (verificat).")
    # ⛔ Совет нужен ВО ВСЕХ состояниях, и в broken он нужнее: недостающая
    # проверка не ложится как раз из-за тех часов, которые напечатаны строкой
    # ниже, и их разведение возвращает её на ближайшем старте само. Без совета
    # директор перезапускает программу (безрезультатно), звонит в поддержку и
    # работает день с неполной страховкой слота.
    tail = (" Reporniți programul; dacă mesajul revine, contactați suportul "
            "astăzi." if not narrow or not rows else
            " După aceea reporniți programul — restul se face singur.")
    if narrow and not rows:
        how = ""                     # советовать нечего: разводить нечего
    elif not how:
        how = " Verificați jurnalul programului."
    return (f"<div class='banner err' style='margin-bottom:14px'>{_ic('clock')} "
            f"{head}{how}{tail}{lst}</div>")
