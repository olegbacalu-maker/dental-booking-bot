"""Страницы админки: серверная разметка, без React и без шаблонизатора.

Инструмент одного человека (cloud.md › «Админка»): списки, карточка, формы.
Всё, что пришло из базы или формы, проходит через html.escape — здесь и только
здесь строится разметка.
"""
from __future__ import annotations

import html
from datetime import datetime, timezone

from . import config, license, maib

esc = html.escape

MSG = {
    "clinic_ok": ("ok", "Клиника заведена"),
    "saved": ("ok", "Сохранено"),
    "issued": ("ok", "Файл выдан"),
    "issued_mailed": ("ok", "Файл выдан и отправлен письмом"),
    "mailed": ("ok", "Письмо отправлено"),
    "bad_name": ("err", "Название клиники обязательно"),
    "bad_idno": ("err", "IDNO — ровно 13 цифр (для пробного файла можно оставить пустым)"),
    "bad_email": ("err", "У клиники нет e-mail — письмо отправить некуда"),
    "bad_date": ("err", "Дата окончания должна быть в будущем, в формате ГГГГ-ММ-ДД"),
    "no_key": ("err", "Ключ выдачи не настроен (DP_LICENSE_KEY) — выдавать нечем"),
    "mail_failed": ("err", "Письмо не отправлено — смотрите лог сервера"),
    "no_issue": ("err", "Файла ещё не выдавали"),
    "payment_created": ("ok", "Платёж создан — reference в карточке"),
    "payment_created_mailed": ("ok", "Платёж создан, письмо с реквизитами отправлено"),
    "payment_confirmed": ("ok", "Платёж подтверждён, срок продлён, файл выдан"),
    "payment_confirmed_mailed": ("ok", "Платёж подтверждён, срок продлён, файл выдан и отправлен"),
    "payment_rejected": ("ok", "Платёж отклонён"),
    "payment_not_pending": ("err", "Этот платёж уже подтверждён или отклонён — второго продления не будет"),
    "bad_months": ("err", "Срок оплаты — 1, 3, 6 или 12 месяцев"),
    "bad_amount": ("err", "Сумма — целое число лей больше нуля"),
    "no_bank": ("err", "Платёж создан, но реквизиты (DP_BANK_*) не заполнены — письмо не отправлено"),
    "card_created": ("ok", "Платёж картой создан — ссылка maib в карточке"),
    "card_created_mailed": ("ok", "Платёж картой создан, письмо со ссылкой отправлено"),
    "no_maib": ("err", "Оплата картой не настроена (DP_MAIB_*) — платёж не создан"),
    "maib_failed": ("err", "maib не ответил — ничего не изменено, смотрите лог сервера"),
    "card_paid": ("ok", "maib подтвердил оплату: срок продлён, файл выдан и отправлен"),
    "card_waiting": ("ok", "maib: платёж ещё не оплачен"),
    "card_failed": ("err", "maib: платёж не прошёл — его слова в карточке; можно выслать новую ссылку"),
    "card_none": ("err", "У этого платежа нет ссылки maib — сначала «Ссылка на карту»"),
    "card_link": ("ok", "Ссылка maib создана — у клиники нет e-mail, передайте её сами"),
    "card_link_mailed": ("ok", "Ссылка maib создана и отправлена письмом"),
    "daily_done": ("ok", "Ежедневная задача выполнена — итог строкой в журнале"),
    "daily_failed": ("err", "Ежедневная задача: часть писем не ушла — смотрите журнал и лог сервера"),
    "login_bad": ("err", "Неверный логин или пароль"),
    "login_locked": ("err", "Слишком много попыток — подождите минуту"),
}

STATE_RU = {"active": ("ok", "действует"), "grace": ("warn", "льгота"),
            "readonly": ("bad", "только чтение"), "none": ("mute", "нет файла")}
PAY_RU = {"pending": ("warn", "ожидает"), "paid": ("ok", "оплачен"), "rejected": ("bad", "отклонён")}
KIND_RU = {"invoice": "счёт за 14 дней до конца срока", "expiring": "за 3 дня до конца срока",
           "expired": "срок истёк, идёт льгота", "last_warning": "завтра — только чтение",
           "readonly": "режим только чтения"}

_CSS = """
body{font-family:Inter,'Segoe UI',system-ui,sans-serif;margin:0;background:#F4F7F6;color:#16232B}
a{color:#0B7F70}.top{background:#0B2B26;color:#fff;padding:12px 24px;display:flex;gap:18px;align-items:center}
.top a{color:#BFEFE6;text-decoration:none;font-weight:600}.top form{margin-left:auto}
.top button{background:none;border:1px solid #BFEFE6;color:#BFEFE6;border-radius:8px;padding:4px 10px;cursor:pointer}
.wrap{max-width:1040px;margin:0 auto;padding:24px}h1{font-size:22px;margin:0 0 14px}h2{font-size:16px;margin:24px 0 8px}
.card{background:#fff;border:1px solid #E6EDEB;border-radius:14px;padding:18px 20px;margin-bottom:16px}
table{border-collapse:collapse;width:100%;font-size:14px}th,td{text-align:left;padding:8px 10px;border-bottom:1px solid #EEF2F1;vertical-align:top}
th{color:#5B6B72;font-weight:600;font-size:12.5px;text-transform:uppercase;letter-spacing:.04em}
input,select,textarea{font:inherit;padding:8px 10px;border:1px solid #D8E2DF;border-radius:9px;width:100%;box-sizing:border-box}
label{display:block;font-size:13px;color:#5B6B72;margin:8px 0 4px}
button.primary{background:#0E9F8A;color:#fff;border:none;border-radius:9px;padding:10px 16px;font-weight:600;cursor:pointer}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:0 18px}
.banner{padding:10px 14px;border-radius:10px;margin:0 0 16px;font-size:14px}
.banner.ok{background:#ECFDF5;color:#065F46}.banner.err{background:#FEF2F2;color:#B91C1C}
.tag{display:inline-block;padding:2px 9px;border-radius:999px;font-size:12px;font-weight:600}
.tag.ok{background:#ECFDF5;color:#065F46}.tag.warn{background:#FFFBEB;color:#B45309}
.tag.bad{background:#FEF2F2;color:#B91C1C}.tag.mute{background:#EEF2F1;color:#5B6B72}
.mono{font-family:ui-monospace,Consolas,monospace;font-size:12.5px}.muted{color:#7C8B91;font-size:13px}
"""


def page(title: str, body: str, user: str | None = None, msg: str = "", pending: int = 0) -> str:
    banner = ""
    if msg in MSG:
        cls, text = MSG[msg]
        banner = f"<div class='banner {cls}'>{esc(text)}</div>"
    pend = f" ({pending})" if pending else ""
    nav = ("<div class='top'><a href='/admin'>DentPilot Cloud</a><a href='/admin'>Клиники</a>"
           f"<a href='/admin/payments'>Платежи{pend}</a><a href='/admin/audit'>Журнал</a>"
           + (f"<form method='post' action='/admin/logout'><button>Выход · {esc(user)}</button></form>"
              if user else "") + "</div>")
    return (f"<!doctype html><html lang='ru'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<title>{esc(title)} — DentPilot Cloud</title><style>{_CSS}</style></head>"
            f"<body>{nav}<div class='wrap'><h1>{esc(title)}</h1>{banner}{body}</div></body></html>")


def login_page(msg: str = "") -> str:
    body = ("<div class='card' style='max-width:380px'><form method='post' action='/admin/login'>"
            "<label>Логин</label><input name='user' autocomplete='username' required>"
            "<label>Пароль</label><input name='password' type='password' autocomplete='current-password' required>"
            "<p><button class='primary'>Войти</button></p></form></div>")
    return page("Вход", body, msg=msg)


def _tag(state: str) -> str:
    cls, text = STATE_RU.get(state, ("mute", state))
    return f"<span class='tag {cls}'>{esc(text)}</span>"


def _renew_info(c, latest_seq: int) -> str:
    """Автообновление (L13): когда программа клиники спрашивала последний раз и
    какой файл у неё был — видно, дошёл ли до неё выданный файл."""
    at = c["renew_at"] if "renew_at" in c.keys() else None
    if not at:
        return "<span class='tag mute'>программа ещё не обращалась</span>"
    have = c["renew_seq"] or 0
    tag = ("<span class='tag ok'>файл у программы</span>" if have >= latest_seq
           else f"<span class='tag warn'>у программы файл {have}, выдан {latest_seq}</span>")
    return f"{esc(at[:16].replace('T', ' '))} UTC {tag}"


def _d(s: str | None) -> str:
    return esc(s[:10]) if s else "—"


def _renew_short(r) -> str:
    """В списке: файл ещё не дошёл до программы — заметно; дошёл или не спрашивала — тихо."""
    if not r["renew_at"] or (r["renew_seq"] or 0) >= (r["seq"] or 0):
        return ""
    return f" <span class='tag warn' title='программа спрашивала {esc(r['renew_at'][:16])}'>у программы {r['renew_seq'] or 0}</span>"


def clinics_page(rows: list, user: str, msg: str = "") -> str:
    now = datetime.now(timezone.utc)
    trs = "".join(
        f"<tr><td><a href='/admin/clinics/{esc(r['id'])}'>{esc(r['name'])}</a></td>"
        f"<td class='mono'>{esc(r['idno'] or '—')}</td><td>{esc(r['plan'] or '—')}</td>"
        f"<td>{_d(r['valid_until'])}</td>"
        f"<td>{_tag(license.state(_ts(r['valid_until']), r['grace_days'] or 0, now))}</td>"
        f"<td>{r['seq'] or 0}{_renew_short(r)}</td></tr>"
        for r in rows) or "<tr><td colspan='6' class='muted'>Пока ни одной клиники</td></tr>"
    counts = {k: 0 for k in STATE_RU}
    for r in rows:
        counts[license.state(_ts(r["valid_until"]), r["grace_days"] or 0, now)] += 1
    summary = " · ".join(f"{STATE_RU[k][1]} {n}" for k, n in counts.items())
    daily = ("<form method='post' action='/admin/jobs/daily' style='margin:0'>"
             "<button title='Напоминания по таблице cloud.md за сегодня; cron делает то же раз в сутки'>"
             "Запустить ежедневную задачу</button></form>")
    table = (f"<div class='card'><div style='display:flex;justify-content:space-between;align-items:center;"
             f"margin-bottom:8px'><span class='muted'>Состояния: {summary}</span>{daily}</div>"
             "<table><tr><th>Клиника</th><th>IDNO</th><th>Тариф</th>"
             f"<th>Срок до</th><th>Состояние</th><th>Файлов</th></tr>{trs}</table></div>")
    form = ("<h2>Новая клиника</h2><div class='card'><form method='post' action='/admin/clinics'>"
            "<div class='grid'><div><label>Название *</label><input name='name' required maxlength='120'></div>"
            "<div><label>IDNO (13 цифр)</label><input name='idno' maxlength='13' pattern='[0-9]{13}'></div>"
            "<div><label>Контактное лицо</label><input name='contact_name'></div>"
            "<div><label>E-mail</label><input name='email' type='email'></div>"
            "<div><label>Телефон</label><input name='phone'></div>"
            "<div><label>Адрес</label><input name='address'></div></div>"
            "<p><button class='primary'>Завести</button></p></form></div>")
    return page("Клиники", table + form, user, msg)


def _ts(s):
    from . import db
    return db.parse_ts(s)


def _pay_tag(status: str) -> str:
    cls, text = PAY_RU.get(status, ("mute", status))
    return f"<span class='tag {cls}'>{esc(text)}</span>"


def _card_cell(p) -> str:
    """Карта (L12): ссылка maib и последние слова maib о платеже."""
    if not p["provider_id"]:
        return ""
    words = esc(p["provider_status"] or "ссылка выслана, ответа maib ещё нет")
    return (f"<br><a href='{esc(p['pay_url'] or '#')}' target='_blank' rel='noopener'>ссылка maib</a>"
            f" <span class='muted'>{words}</span>")


def _payment_rows(rows: list, with_clinic: bool = False) -> str:
    out = []
    for p in rows:
        actions = ""
        if p["status"] == "pending":
            actions = (f"<form method='post' action='/admin/payments/{p['id']}/confirm' style='display:inline'>"
                       f"<button class='primary'>Подтвердить</button></form> "
                       f"<form method='post' action='/admin/payments/{p['id']}/reject' style='display:inline'>"
                       f"<input name='reason' placeholder='причина' style='width:140px;display:inline'> "
                       f"<button>Отклонить</button></form>")
            if p["provider_id"]:
                actions += (f" <form method='post' action='/admin/payments/{p['id']}/check' style='display:inline'>"
                            f"<button title='Спросить maib о статусе'>Проверить</button></form>")
            if maib.enabled():
                actions += (f" <form method='post' action='/admin/payments/{p['id']}/link' style='display:inline'>"
                            f"<button title='Ссылка на оплату картой к этому же reference'>"
                            f"{'Новая ссылка' if p['provider_id'] else 'Ссылка на карту'}</button></form>")
        clinic_td = (f"<td><a href='/admin/clinics/{esc(p['clinic_id'])}'>{esc(p['clinic'])}</a></td>"
                     if with_clinic else "")
        out.append(f"<tr><td class='mono'>{esc(p['reference'])}</td>{clinic_td}"
                   f"<td>{p['amount']} {esc(p['currency'])}</td><td>{p['months']} мес.</td>"
                   f"<td>{esc(p['created_at'][:10])}</td><td>{_pay_tag(p['status'])}"
                   f"{(' · ' + esc(p['paid_at'][:10])) if p['paid_at'] else ''}"
                   f"{(' · ' + esc(p['confirmed_by'])) if p['confirmed_by'] and p['status'] == 'paid' else ''}"
                   f"{_card_cell(p)}</td><td>{actions}</td></tr>")
    return "".join(out)


def pay_page(ok: bool) -> str:
    """Куда maib возвращает браузер клиники (L12). Редирект — не истина о платеже,
    поэтому страница не говорит «оплачено»: подтверждение и файл придут письмом."""
    if ok:
        title, text = ("Mulțumim!", "Plata a fost transmisă către bancă. După confirmare primiți pe e-mail "
                                    "fișierul de licență cu noul termen — de obicei în câteva minute. "
                                    "Programul DentPilot îl preia singur dacă are acces la internet.")
    else:
        title, text = ("Plata nu a reușit", "Banca nu a confirmat plata. Puteți încerca din nou din e-mailul "
                                            "cu nota de plată sau plăti prin transfer bancar cu referința din "
                                            "aceeași notă.")
    return (f"<!doctype html><html lang='ro'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<title>{esc(title)} — DentPilot</title><style>{_CSS}"
            f".box{{max-width:520px;margin:48px auto;padding:0 16px}}</style></head>"
            f"<body><div class='box'><div class='card'><h1>{esc(title)}</h1><p>{esc(text)}</p>"
            f"<p class='muted'>Întrebări: {esc(config.SUPPORT_EMAIL)} · {esc(config.SUPPORT_PHONE)}</p>"
            f"</div></div></body></html>")


def payments_page(rows: list, user: str, msg: str = "") -> str:
    trs = _payment_rows(rows, with_clinic=True) or "<tr><td colspan='7' class='muted'>Ожидающих платежей нет</td></tr>"
    body = (f"<div class='card'><table><tr><th>Reference</th><th>Клиника</th><th>Сумма</th><th>Срок</th>"
            f"<th>Создан</th><th>Состояние</th><th></th></tr>{trs}</table></div>")
    return page("Платежи в ожидании", body, user, msg, pending=len(rows))


def _reminder_rows(rows: list) -> str:
    return "".join(f"<tr><td>{esc(KIND_RU.get(r['kind'], r['kind']))}</td><td>{_d(r['period'])}</td>"
                   f"<td>{esc(r['sent_at'][:16].replace('T', ' '))}</td></tr>" for r in rows)


def audit_page(rows: list, user: str, msg: str = "", pending: int = 0) -> str:
    out = []
    for a in rows:
        who = (f"<a href='/admin/clinics/{esc(a['clinic_id'])}'>{esc(a['clinic'] or a['clinic_id'])}</a>"
               if a["clinic_id"] else "—")
        out.append(f"<tr><td>{esc(a['at'][:16].replace('T', ' '))}</td><td>{esc(a['who'])}</td>"
                   f"<td>{esc(a['what'])}</td><td>{who}</td><td>{esc(a['detail'])}</td></tr>")
    trs = "".join(out)
    body = (f"<div class='card'><table><tr><th>Когда</th><th>Кто</th><th>Что</th><th>Клиника</th>"
            f"<th>Подробности</th></tr>{trs or '<tr><td colspan=5 class=muted>пусто</td></tr>'}</table></div>")
    return page("Журнал", body, user, msg, pending=pending)


def clinic_page(c, sub, issues: list, audit: list, user: str, msg: str = "",
                payments: list = (), pending: int = 0, reminders: list = ()) -> str:
    now = datetime.now(timezone.utc)
    st = license.state(_ts(sub["valid_until"]) if sub else None, sub["grace_days"] if sub else 0, now)
    head = (f"<div class='card'><div class='grid'>"
            f"<div><label>IDNO</label><div class='mono'>{esc(c['idno'] or '—')}</div></div>"
            f"<div><label>Контакт</label><div>{esc(c['contact_name'] or '—')}</div></div>"
            f"<div><label>E-mail</label><div>{esc(c['email'] or '—')}</div></div>"
            f"<div><label>Телефон</label><div>{esc(c['phone'] or '—')}</div></div>"
            f"<div><label>Тариф</label><div>{esc(sub['plan']) if sub else '—'}</div></div>"
            f"<div><label>Срок до</label><div>{_d(sub['valid_until']) if sub else '—'} {_tag(st)}</div></div>"
            f"<div><label>Льгота</label><div>{sub['grace_days'] if sub else '—'} дн.</div></div>"
            f"<div><label>Идентификатор</label><div class='mono'>{esc(c['id'])}</div></div>"
            f"<div><label>Программа спрашивала</label><div>"
            f"{_renew_info(c, max((i['seq'] for i in issues), default=0))}</div></div>"
            f"</div></div>")
    edit = (f"<details><summary class='muted'>Изменить реквизиты</summary><div class='card'>"
            f"<form method='post' action='/admin/clinics/{esc(c['id'])}/edit'><div class='grid'>"
            f"<div><label>Название *</label><input name='name' value='{esc(c['name'])}' required></div>"
            f"<div><label>IDNO</label><input name='idno' value='{esc(c['idno'])}' maxlength='13'></div>"
            f"<div><label>Контакт</label><input name='contact_name' value='{esc(c['contact_name'])}'></div>"
            f"<div><label>E-mail</label><input name='email' value='{esc(c['email'])}'></div>"
            f"<div><label>Телефон</label><input name='phone' value='{esc(c['phone'])}'></div>"
            f"<div><label>Адрес</label><input name='address' value='{esc(c['address'])}'></div></div>"
            f"<p><button class='primary'>Сохранить</button></p></form></div></details>")
    issue_form = (f"<h2>Выдать файл</h2><div class='card'><form method='post' action='/admin/clinics/{esc(c['id'])}/issue'>"
                  f"<div class='grid'><div><label>Что выдать</label><select name='kind'>"
                  f"<option value='trial'>Пробный: {license.TRIAL_DAYS} дней + {license.TRIAL_GRACE_DAYS} льготы</option>"
                  f"<option value='dates'>Абонемент до даты</option></select></div>"
                  f"<div><label>Срок до (для абонемента)</label><input name='valid_until' type='date'></div>"
                  f"<div><label>Льгота, дней</label><input name='grace_days' type='number' value='{license.GRACE_DAYS}' min='0' max='60'></div>"
                  f"<div><label>Основание</label><input name='reason' placeholder='платёж DP-2026-000001, демонстрация…'></div></div>"
                  f"<label><input type='checkbox' name='send' value='1' style='width:auto'> сразу отправить письмом на {esc(c['email'] or '— e-mail не указан')}</label>"
                  f"<p><button class='primary'>Выдать</button></p></form></div>")
    price = sub["price"] if sub else 399
    opts = "".join(f"<option value='{m}'>{m} мес. — {m * price} MDL</option>" for m in (1, 3, 6, 12))
    if maib.enabled():
        method = ("<div><label>Как платит клиника</label><select name='method'>"
                  "<option value='transfer'>Переводом — реквизиты и reference в письме</option>"
                  "<option value='card'>Картой — ссылка maib в письме (и reference для перевода)</option>"
                  "</select></div>")
    else:
        method = ("<div><label>Как платит клиника</label><div class='muted'>только переводом: "
                  "DP_MAIB_* не заданы, ссылки на карту нет</div></div>")
    pay_form = (f"<h2>Платежи</h2><div class='card'><form method='post' action='/admin/clinics/{esc(c['id'])}/payments'>"
                f"<div class='grid'><div><label>Срок</label><select name='months'>{opts}</select></div>"
                f"<div><label>Сумма, MDL (пусто = по тарифу)</label><input name='amount' inputmode='numeric'></div>"
                f"{method}</div>"
                f"<label><input type='checkbox' name='send' value='1' checked style='width:auto'> отправить письмо с нотой "
                f"на {esc(c['email'] or '— e-mail не указан')}</label>"
                f"<p><button class='primary'>Создать платёж</button></p></form>"
                f"<table><tr><th>Reference</th><th>Сумма</th><th>Срок</th><th>Создан</th><th>Состояние</th><th></th></tr>"
                f"{_payment_rows(list(payments)) or '<tr><td colspan=6 class=muted>Платежей ещё нет</td></tr>'}</table></div>")
    trs = "".join(
        f"<tr><td>{i['seq']}</td><td>{esc(i['issued_at'][:16].replace('T', ' '))}</td>"
        f"<td>{_d(i['valid_until'])}</td><td>{_d(i['grace_until'])}</td><td>{esc(i['reason'])}</td>"
        f"<td><a href='/admin/clinics/{esc(c['id'])}/issues/{i['seq']}/license.json'>license.json</a></td></tr>"
        for i in issues) or "<tr><td colspan='6' class='muted'>Файлов ещё не выдавали</td></tr>"
    mail_btn = (f"<form method='post' action='/admin/clinics/{esc(c['id'])}/email' style='margin-top:10px'>"
                f"<button class='primary'>Отправить последний файл письмом</button></form>" if issues else "")
    issues_html = (f"<h2>Выданные файлы</h2><div class='card'><table><tr><th>№</th><th>Выдан</th>"
                   f"<th>Срок до</th><th>Льгота до</th><th>Основание</th><th>Файл</th></tr>{trs}</table>{mail_btn}</div>")
    rem_html = (f"<h2>Напоминания</h2><div class='card'><table><tr><th>Письмо</th><th>Период до</th>"
                f"<th>Отправлено</th></tr>{_reminder_rows(list(reminders)) or '<tr><td colspan=3 class=muted>Напоминаний ещё не было</td></tr>'}"
                f"</table></div>")
    ars = "".join(f"<tr><td>{esc(a['at'][:16].replace('T', ' '))}</td><td>{esc(a['who'])}</td>"
                  f"<td>{esc(a['what'])}</td><td>{esc(a['detail'])}</td></tr>" for a in audit)
    audit_html = (f"<h2>Журнал</h2><div class='card'><table><tr><th>Когда</th><th>Кто</th><th>Что</th>"
                  f"<th>Подробности</th></tr>{ars or '<tr><td colspan=4 class=muted>пусто</td></tr>'}</table></div>")
    return page(c["name"], head + edit + pay_form + issue_form + issues_html + rem_html + audit_html, user,
                msg, pending=pending)
