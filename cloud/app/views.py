"""Страницы админки: серверная разметка, без React и без шаблонизатора.

Инструмент одного человека (cloud.md › «Админка»): списки, карточка, формы.
Всё, что пришло из базы или формы, проходит через html.escape — здесь и только
здесь строится разметка.
"""
from __future__ import annotations

import html
from datetime import datetime, timezone

from . import config, license, maib, mail, trial
from . import payments as pay  # ⚠️ не `payments`: так зовётся параметр карточки клиники (список строк)

esc = html.escape

MSG = {
    "clinic_ok": ("ok", "Клиника заведена"),
    "saved": ("ok", "Сохранено"),
    "issued": ("ok", "Файл выдан"),
    "issued_mailed": ("ok", "Файл выдан, письмо о лицензии отправлено (без файла: программа забирает его сама)"),
    "mailed": ("ok", "Письмо о лицензии отправлено"),
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
    "trial_declined": ("ok", "Заявка скрыта — пробный не выдан; клиника остаётся в списке"),
    "account_detached": ("ok", "Учётная запись отвязана — следующий вход этого аккаунта Google начнётся с регистрации"),
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

# Шрифт сайта — с dentpilot.md (Pages отдаёт woff2 с CORS *): одна гарнитура на
# сайт, кабинет и админку; без него страницы рисовались системным Segoe UI.
_FONTS = (
    "@font-face{font-family:'Inter';font-style:normal;font-weight:100 900;font-display:swap;"
    "src:url('https://dentpilot.md/fonts/inter-latin-ext.woff2') format('woff2');"
    "unicode-range:U+0100-02BA,U+02BD-02C5,U+02C7-02CC,U+02CE-02D7,U+02DD-02FF,U+0304,U+0308,U+0329,"
    "U+1D00-1DBF,U+1E00-1E9F,U+1EF2-1EFF,U+2020,U+20A0-20AB,U+20AD-20C0,U+2113,U+2C60-2C7F,U+A720-A7FF}"
    "@font-face{font-family:'Inter';font-style:normal;font-weight:100 900;font-display:swap;"
    "src:url('https://dentpilot.md/fonts/inter-cyrillic.woff2') format('woff2');"
    "unicode-range:U+0301,U+0400-045F,U+0490-0491,U+04B0-04B1,U+2116}"
    "@font-face{font-family:'Inter';font-style:normal;font-weight:100 900;font-display:swap;"
    "src:url('https://dentpilot.md/fonts/inter-latin.woff2') format('woff2');"
    "unicode-range:U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,"
    "U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD}"
)
# Админка — инструмент одного человека, по-русски; с 02.10 («выглядит немного сыро»)
# в тех же токенах, что сайт и кабинет: тёмная липкая шапка с разделами и активным
# разделом, карточки с заголовками-значками, таблицы с подсветкой строки, кнопки и
# поля как в кабинете. ⛔ Тексты страниц держат cloud/tests — слова не менять.
_CSS = _FONTS + """
:root{--ink:#16232B;--muted:#5B6B72;--line:#E6EDEB;--teal:#0E9F8A;--teal-d:#0B7F70;--teal-soft:#E9F6F3;--bg:#F4F8F7;--dark:#0B2B26;--shadow:0 1px 2px rgba(11,43,38,.04),0 14px 36px -20px rgba(11,43,38,.18)}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:'Inter',system-ui,-apple-system,'Segoe UI',sans-serif;-webkit-font-smoothing:antialiased;line-height:1.45;font-size:14.5px}
a{color:var(--teal-d)}
.top{position:sticky;top:0;z-index:5;background:var(--dark);color:#fff}
.top-in{max-width:1180px;margin:0 auto;padding:0 24px;height:56px;display:flex;align-items:center;gap:4px}
.brand{display:flex;align-items:center;gap:10px;color:#fff;text-decoration:none;font-weight:700;font-size:15px;margin-right:16px;white-space:nowrap}
.brand .ic{width:28px;height:28px;border-radius:8px;background:var(--teal);display:inline-flex;align-items:center;justify-content:center;flex:none}
.brand .sub{color:#8FCFC3;font-weight:500;font-size:13px}
.nav{display:flex;gap:2px;flex-wrap:wrap}
.nav a{color:#CDEDE6;text-decoration:none;font-weight:600;font-size:14px;padding:7px 12px;border-radius:9px;white-space:nowrap}
.nav a:hover{background:rgba(255,255,255,.08);color:#fff}
.nav a.on{background:rgba(255,255,255,.14);color:#fff}
.top form{margin-left:auto;margin-bottom:0}
.top form button{background:transparent;border:1px solid rgba(255,255,255,.35);color:#E6F4F1;border-radius:9px;padding:6px 12px;font:inherit;font-size:13px;font-weight:600;cursor:pointer;white-space:nowrap}
.top form button:hover{border-color:#fff;color:#fff;background:rgba(255,255,255,.08)}
.wrap{max-width:1180px;margin:0 auto;padding:28px 24px 64px}
.ph{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:0 0 18px}
h1{font-size:24px;letter-spacing:-.02em;margin:0;line-height:1.2}
.ph .lead{color:var(--muted);font-size:14px;margin:0;flex-basis:100%}
h2{font-size:16px;margin:0;letter-spacing:-.01em}
.card{background:#fff;border:1px solid var(--line);border-radius:16px;padding:18px 20px;margin-bottom:16px;box-shadow:var(--shadow);overflow-x:auto}
.card.alert{border-color:#F1D79E;background:linear-gradient(180deg,#FFFDF6,#fff 60%)}
.chead{display:flex;align-items:center;gap:12px;margin:0 0 12px;flex-wrap:wrap}
.chead .ico{width:34px;height:34px;border-radius:10px;background:var(--teal-soft);color:var(--teal-d);display:inline-flex;align-items:center;justify-content:center;flex:none}
.card.alert .chead .ico{background:#FFF3D6;color:#B45309}
.chead h2{font-size:15.5px}.chead .sub{font-size:12.5px;color:var(--muted);margin:1px 0 0}
.chead>div{flex:1;min-width:0}.chead .right{margin-left:auto;flex:none}
table{border-collapse:collapse;width:100%;font-size:14px}
th,td{text-align:left;padding:9px 10px;border-bottom:1px solid #EEF2F1;vertical-align:top}
th{color:var(--muted);font-weight:600;font-size:11.5px;text-transform:uppercase;letter-spacing:.05em;white-space:nowrap}
tr:hover td{background:#F8FBFA}tr:last-child td{border-bottom:0}
input,select,textarea{font:inherit;font-size:14px;padding:9px 11px;border:1px solid #D8E2DF;border-radius:9px;width:100%;background:#fff;color:var(--ink)}
input:focus,select:focus,textarea:focus{outline:none;border-color:var(--teal);box-shadow:0 0 0 3px rgba(14,159,138,.18)}
label{display:block;font-size:12.5px;color:var(--muted);margin:8px 0 4px;font-weight:500}
label.chk{display:flex;gap:8px;align-items:center;color:var(--ink);font-size:14px;font-weight:400;margin:12px 0 4px}
label.chk input{width:auto;margin:0}
.kv{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px 18px}
.kv label{margin:0 0 2px}.kv .v{font-size:14.5px;line-height:1.4}
button{font:inherit;cursor:pointer}
button.primary,a.btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;background:var(--teal);color:#fff;border:1px solid var(--teal);border-radius:9px;padding:9px 16px;font-size:14px;font-weight:600;text-decoration:none;white-space:nowrap}
button.primary:hover,a.btn:hover{background:var(--teal-d);border-color:var(--teal-d);color:#fff}
button:not(.primary){background:#fff;border:1px solid #D8E2DF;color:var(--ink);border-radius:9px;padding:8px 13px;font-size:13.5px;font-weight:500;white-space:nowrap}
button:not(.primary):hover{border-color:var(--teal);color:var(--teal-d)}
.actions{display:flex;gap:6px;align-items:center;flex-wrap:wrap}
.actions form{display:inline-flex;gap:6px;align-items:center;margin:0}
.actions input{width:150px;padding:7px 10px;font-size:13px}
details summary{cursor:pointer;color:var(--teal-d);font-weight:600;font-size:14px;margin:-4px 0 14px;list-style:none;display:inline-flex;align-items:center;gap:8px}
details summary::-webkit-details-marker{display:none}
details summary:before{content:'';width:0;height:0;border:5px solid transparent;border-left-color:currentColor;margin-left:4px;transition:transform .15s}
details[open] summary:before{transform:rotate(90deg)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:0 18px}
.banner{padding:11px 14px;border-radius:11px;margin:0 0 16px;font-size:14px}
.banner.ok{background:#ECFDF5;color:#065F46}.banner.err{background:#FEF2F2;color:#B91C1C}
.tag{display:inline-block;padding:2px 9px;border-radius:999px;font-size:12px;font-weight:600;white-space:nowrap;vertical-align:middle}
.tag.ok{background:#ECFDF5;color:#065F46}.tag.warn{background:#FFFBEB;color:#B45309}
.tag.bad{background:#FEF2F2;color:#B91C1C}.tag.mute{background:#EEF2F1;color:#5B6B72}
.mono{font-family:ui-monospace,Consolas,monospace;font-size:12.5px}.muted{color:#7C8B91;font-size:13px}
.login{max-width:400px;margin:40px auto 0}
.login .mark{width:46px;height:46px;border-radius:13px;background:var(--teal);display:inline-flex;align-items:center;justify-content:center;margin-bottom:12px}
.login h1{font-size:22px;margin:0 0 4px}
@media (max-width:760px){.top-in{padding:8px 14px;height:auto;flex-wrap:wrap}.top form{margin-left:auto}.wrap{padding:18px 14px 48px}.card{padding:14px;border-radius:14px}.nav a{padding:6px 9px}.chead .right{margin-left:0;flex-basis:100%}}
"""


def page(title: str, body: str, user: str | None = None, msg: str = "", pending: int = 0,
         active: str = "", lead: str = "", plain: bool = False) -> str:
    """Каркас админки: тёмная шапка с разделами (активный подсвечен), выход;
    заголовок с подписью; баннер сообщения; тело. Без входа — только бренд."""
    banner = ""
    if msg in MSG:
        cls, text = MSG[msg]
        banner = f"<div class='banner {cls}'>{esc(text)}</div>"
    pend = f" ({pending})" if pending else ""

    def item(href: str, text: str, key: str) -> str:
        # ⚠️ порядок атрибутов: class, потом href — тест ищет «href='/admin/fleet'>Флот</a>»
        return f"<a class='on' href='{href}'>{text}</a>" if active == key else f"<a href='{href}'>{text}</a>"

    nav = (f"<div class='top'><div class='top-in'><a class='brand' href='/admin'><span class='ic'>{_TOOTH}</span>"
           f"DentPilot Cloud <span class='sub'>· админка</span></a>"
           + ((f"<nav class='nav'>{item('/admin', 'Клиники', 'clinics')}"
               f"{item('/admin/payments', 'Платежи' + pend, 'payments')}{item('/admin/fleet', 'Флот', 'fleet')}"
               f"{item('/admin/audit', 'Журнал', 'audit')}</nav>"
               f"<form method='post' action='/admin/logout'><button>Выход · {esc(user)}</button></form>")
              if user else "") + "</div></div>")
    head = "" if plain else f"<div class='ph'><h1>{esc(title)}</h1>{('<p class=' + chr(39) + 'lead' + chr(39) + '>' + lead + '</p>') if lead else ''}</div>"
    return (f"<!doctype html><html lang='ru'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<meta name='robots' content='noindex'>"
            f"<title>{esc(title)} — DentPilot Cloud</title><style>{_CSS}</style></head>"
            f"<body>{nav}<div class='wrap'>{head}{banner}{body}</div></body></html>")


def login_page(msg: str = "") -> str:
    body = (f"<div class='card login'><span class='mark'>{_TOOTH_L}</span>"
            f"<h1>Вход в админку</h1><p class='muted' style='margin:0 0 14px'>DentPilot Cloud — сервер лицензий.</p>"
            f"<form method='post' action='/admin/login'>"
            f"<label>Логин</label><input name='user' autocomplete='username' required autofocus>"
            f"<label>Пароль</label><input name='password' type='password' autocomplete='current-password' required>"
            f"<p style='margin:16px 0 0'><button class='primary' style='width:100%'>Войти</button></p></form></div>")
    return page("Вход", body, msg=msg, plain=True)


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


ORIGIN_RU = {"form": ("форма", "заявка с формы"), "program": ("программа", "заявка из программы"),
             "cont": ("кабинет", "заявка из кабинета")}


def _requests_block(requests: list) -> str:
    """Заявки с формы /proba, из программы и из кабинета, ещё без файла и не
    скрытые (L14). Заявке из программы выдача — всё, что нужно: программа
    забирает файл сама; заявке из кабинета — файл появляется в кабинете."""
    if not requests:
        return ""
    trs = "".join(
        f"<tr><td><a href='/admin/clinics/{esc(r['id'])}'>{esc(r['name'])}</a> "
        f"<span class='tag mute'>{ORIGIN_RU.get(r['origin'], ORIGIN_RU['form'])[0]}</span></td>"
        f"<td class='mono'>{esc(r['idno'] or '—')}</td><td>{esc(r['contact_name'] or '—')}</td>"
        f"<td>{esc(r['email'])}<br><span class='muted'>{esc(r['phone'] or '')}</span></td>"
        f"<td>{esc((r['requested_at'] or '')[:16].replace('T', ' '))}</td>"
        f"<td><div class='actions'><form method='post' action='/admin/clinics/{esc(r['id'])}/issue'>"
        f"<input type='hidden' name='kind' value='trial'><input type='hidden' name='send' value='1'>"
        f"<input type='hidden' name='reason' value='{ORIGIN_RU.get(r['origin'], ORIGIN_RU['form'])[1]}'>"
        f"<button class='primary'>Выдать пробный и отправить</button></form>"
        f"<form method='post' action='/admin/clinics/{esc(r['id'])}/decline'>"
        f"<button>Скрыть</button></form></div></td></tr>"
        for r in requests)
    return (f"<div class='card alert'>{_chead('inbox', f'Заявки на пробный период ({len(requests)})', 'ждут кнопки «Выдать»: программа клиники заберёт файл сама, в кабинете он появится тут же')}"
            f"<table><tr><th>Клиника</th><th>IDNO</th><th>Контакт</th><th>E-mail · телефон</th>"
            f"<th>Подана</th><th></th></tr>{trs}</table></div>")


def clinics_page(rows: list, user: str, msg: str = "", requests: list = ()) -> str:
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
    summary = " · ".join(f"<span class='tag {STATE_RU[k][0]}'>{STATE_RU[k][1]} {n}</span>" for k, n in counts.items())
    daily = ("<form method='post' action='/admin/jobs/daily' style='margin:0'>"
             "<button title='Напоминания по таблице cloud.md за сегодня; cron делает то же раз в сутки'>"
             "Запустить ежедневную задачу</button></form>")
    table = (f"<div class='card'>{_chead('list', f'Все клиники ({len(rows)})', f'Состояния: {summary}', daily)}"
             "<table><tr><th>Клиника</th><th>IDNO</th><th>Тариф</th>"
             f"<th>Срок до</th><th>Состояние</th><th>Файлов</th></tr>{trs}</table></div>")
    form = (f"<div class='card'>{_chead('plus', 'Новая клиника', 'заводится вручную — файл выдаётся из карточки')}"
            "<form method='post' action='/admin/clinics'>"
            "<div class='grid'><div><label>Название *</label><input name='name' required maxlength='120'></div>"
            "<div><label>IDNO (13 цифр)</label><input name='idno' maxlength='13' pattern='[0-9]{13}'></div>"
            "<div><label>Контактное лицо</label><input name='contact_name'></div>"
            "<div><label>E-mail</label><input name='email' type='email'></div>"
            "<div><label>Телефон</label><input name='phone'></div>"
            "<div><label>Адрес</label><input name='address'></div></div>"
            "<p style='margin:14px 0 0'><button class='primary'>Завести</button></p></form></div>")
    return page("Клиники", _requests_block(list(requests)) + table + form, user, msg, active="clinics",
                lead="Клиники, их файлы лицензии и заявки на пробный период.")


# ---------- форма пробного периода (L14): публичные страницы, по-румынски ----------

TRIAL_MSG = {
    "bad_name": "Indicați denumirea clinicii (2–120 de caractere).",
    "bad_idno": "IDNO are exact 13 cifre — sau lăsați câmpul gol pentru perioada de probă.",
    "bad_email": "Indicați o adresă de e-mail valabilă: pe ea primiți confirmarea și codurile de activare.",
    "too_long": "Persoana de contact sau telefonul sunt prea lungi.",
    "no_consent": "Bifați acordul cu Termenii și condițiile și Politica de confidențialitate.",
    "limited": "Prea multe cereri de la această adresă — încercați peste o oră sau scrieți-ne.",
    # Только заявке из программы (JSON, trial.API_PATH): там повтор объявляется
    "duplicate": "Clinica este deja înregistrată la DentPilot (după IDNO sau e-mail), dar codul de activare "
                 "nu a putut fi trimis pe e-mailul ei. Scrieți-ne și activăm programul împreună.",
    "duplicate_code": "Clinica este deja înregistrată la DentPilot. Am trimis un cod de activare pe "
                      "adresa de e-mail a clinicii — introduceți-l mai jos (este valabil "
                      f"{int(trial.CODE_TTL.total_seconds() // 60)} minute).",
    "bad_code": "Codul nu este corect sau a expirat — verificați e-mailul sau trimiteți din nou "
                "cererea pentru un cod nou.",
    "code_limited": "Prea multe încercări — încercați peste o oră sau scrieți-ne.",
    "bad_json": "Cererea nu a putut fi citită — actualizați programul sau scrieți-ne.",
    "no_renew": "Activarea automată nu este disponibilă acum — încercați mai târziu sau scrieți-ne.",
}


def _public(title: str, inner: str) -> str:
    return (f"<!doctype html><html lang='ro'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<title>{esc(title)} — DentPilot</title><style>{_CSS}"
            f".box{{max-width:560px;margin:32px auto;padding:0 16px}}.hp{{position:absolute;left:-9999px}}"
            f"label.chk{{display:flex;gap:8px;align-items:flex-start;color:#16232B;font-size:14px}}"
            f"label.chk input{{width:auto;margin-top:3px}}</style></head>"
            f"<body><div class='box'>{inner}"
            f"<p class='muted'>Întrebări: {esc(config.SUPPORT_EMAIL)} · {esc(config.SUPPORT_PHONE)}</p>"
            f"</div></body></html>")


def trial_page(msg: str = "", values: dict | None = None) -> str:
    v = {k: esc((values or {}).get(k, "")) for k in ("name", "idno", "contact_name", "email", "phone")}
    err = f"<div class='banner err'>{esc(TRIAL_MSG.get(msg, msg))}</div>" if msg else ""
    site = config.SITE_URL.rstrip("/")
    inner = (f"<h1>Perioadă de probă DentPilot — {mail.zile(license.TRIAL_DAYS)}</h1>"
             f"<div class='card'><p>Completați formularul: perioada de probă de {mail.zile(license.TRIAL_DAYS)} "
             f"se activează fără plată și fără obligații. Descărcați programul de pe "
             f"<a href='{esc(site)}/descarca.html'>dentpilot.md</a> și, la prima pornire, introduceți aceleași "
             f"date — programul se activează singur (dacă e nevoie, cu un cod trimis pe acest e-mail). "
             f"Instalăm împreună, la telefon, dacă doriți. Datele pacienților rămân pe calculatorul clinicii.</p>"
             f"{err}<form method='post' action='/proba'>"
             f"<label>Denumirea clinicii *</label><input name='name' value='{v['name']}' required maxlength='{trial.NAME_MAX}'>"
             f"<label>IDNO (13 cifre, opțional pentru probă)</label><input name='idno' value='{v['idno']}' maxlength='13' inputmode='numeric'>"
             f"<label>Persoana de contact</label><input name='contact_name' value='{v['contact_name']}' maxlength='{trial.CONTACT_MAX}'>"
             f"<label>E-mail *</label><input name='email' type='email' value='{v['email']}' required maxlength='{trial.EMAIL_MAX}'>"
             f"<label>Telefon</label><input name='phone' value='{v['phone']}' maxlength='{trial.PHONE_MAX}'>"
             f"<div class='hp' aria-hidden='true'><label>Website</label>"
             f"<input name='{trial.HONEYPOT}' tabindex='-1' autocomplete='off'></div>"
             f"<p><label class='chk'><input type='checkbox' name='consent' value='1'> Am citit și accept "
             f"<a href='{esc(site)}/termeni.html' target='_blank' rel='noopener'>Termenii și condițiile</a> și "
             f"<a href='{esc(site)}/privacy.html' target='_blank' rel='noopener'>Politica de confidențialitate</a>."
             f"</label></p><p><button class='primary'>Solicit perioada de probă</button></p></form></div>")
    return _public("Perioadă de probă", inner)


def trial_done_page(outcome: str, email: str) -> str:
    """Два лица: «отправлено» и «принято». Повтор и файл без письма показывают
    «принято» — форма не оракул о том, кто уже клиент; дальше отвечает Олег."""
    site = config.SITE_URL.rstrip("/")
    if outcome == trial.ISSUED:
        title, text = ("Perioada de probă este activă",
                       f"Perioada de probă de {mail.zile(license.TRIAL_DAYS)} pentru {email} este activă, iar "
                       f"confirmarea a plecat pe e-mail. Descărcați programul de pe {site}/descarca.html; la "
                       f"prima pornire introduceți aceleași date și programul se activează singur. Dacă nu "
                       f"găsiți e-mailul în câteva minute, verificați dosarul Spam sau scrieți-ne.")
    else:
        title, text = ("Cererea a fost primită", f"Vă răspundem la {email} în cel mult o zi lucrătoare — "
                       f"cu confirmarea perioadei de probă de {mail.zile(license.TRIAL_DAYS)} și pașii de "
                       f"instalare.")
    return _public(title, f"<div class='card'><h1>{esc(title)}</h1><p>{esc(text)}</p></div>")


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
            actions = (f"<form method='post' action='/admin/payments/{p['id']}/confirm'>"
                       f"<button class='primary'>Подтвердить</button></form>"
                       f"<form method='post' action='/admin/payments/{p['id']}/reject'>"
                       f"<input name='reason' placeholder='причина'>"
                       f"<button>Отклонить</button></form>")
            if p["provider_id"]:
                actions += (f"<form method='post' action='/admin/payments/{p['id']}/check'>"
                            f"<button title='Спросить maib о статусе'>Проверить</button></form>")
            if maib.enabled():
                actions += (f"<form method='post' action='/admin/payments/{p['id']}/link'>"
                            f"<button title='Ссылка на оплату картой к этому же reference'>"
                            f"{'Новая ссылка' if p['provider_id'] else 'Ссылка на карту'}</button></form>")
            actions = f"<div class='actions'>{actions}</div>"
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
        title, text = ("Mulțumim!", "Plata a fost transmisă către bancă. După confirmare termenul se "
                                    "prelungește automat — de obicei în câteva minute: programul DentPilot "
                                    "îl preia singur când are acces la internet, iar confirmarea vine pe e-mail.")
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
    body = (f"<div class='card'>{_chead('card', f'В ожидании: {len(rows)}', 'подтверждение продлевает срок и выдаёт файл; письмо клинике уходит само')}"
            f"<table><tr><th>Reference</th><th>Клиника</th><th>Сумма</th><th>Срок</th>"
            f"<th>Создан</th><th>Состояние</th><th></th></tr>{trs}</table></div>")
    return page("Платежи в ожидании", body, user, msg, pending=len(rows), active="payments",
                lead="Переводы, которых ждём: сверить с выпиской и подтвердить.")


def _reminder_rows(rows: list) -> str:
    return "".join(f"<tr><td>{esc(KIND_RU.get(r['kind'], r['kind']))}</td><td>{_d(r['period'])}</td>"
                   f"<td>{esc(r['sent_at'][:16].replace('T', ' '))}</td></tr>" for r in rows)


def audit_page(rows: list, user: str, msg: str = "", pending: int = 0) -> str:
    out = []
    for a in rows:
        who = (f"<a href='/admin/clinics/{esc(a['clinic_id'])}'>{esc(a['clinic'] or a['clinic_id'])}</a>"
               if a["clinic_id"] else "—")
        out.append(f"<tr><td class='mono'>{esc(a['at'][:16].replace('T', ' '))}</td><td>{esc(a['who'])}</td>"
                   f"<td><span class='tag mute'>{esc(a['what'])}</span></td><td>{who}</td><td>{esc(a['detail'])}</td></tr>")
    trs = "".join(out)
    body = (f"<div class='card'>{_chead('clock', 'Последние события', 'кто что сделал — выдачи, платежи, входы, коды')}"
            f"<table><tr><th>Когда (UTC)</th><th>Кто</th><th>Что</th><th>Клиника</th>"
            f"<th>Подробности</th></tr>{trs or '<tr><td colspan=5 class=muted>пусто</td></tr>'}</table></div>")
    return page("Журнал", body, user, msg, pending=pending, active="audit")


def _device_rows(devices: list, latest: str = "") -> str:
    from . import fleet
    out = []
    for d in devices:
        tags = ""
        if d["version"] and latest and fleet.behind(d["version"], latest):
            tags += " <span class='tag warn'>отстаёт</span>"
        out.append(f"<tr><td class='mono'>{esc(d['id'])}</td><td>{esc(d['version'] or '—')}{tags}</td>"
                   f"<td>{esc(d['channel'] or '—')}</td><td>{esc(d['os'] or '—')}</td>"
                   f"<td>{esc((d['first_seen_at'] or '')[:10])}</td>"
                   f"<td>{esc((d['last_seen_at'] or '')[:16].replace('T', ' '))}</td>"
                   f"<td>{d['last_seq'] if d['last_seq'] is not None else '—'}</td></tr>")
    return "".join(out)


def fleet_page(rep: dict, user: str, msg: str = "", pending: int = 0) -> str:
    """Флот (02.10): компьютеры клиник, версии, кто отстал от выпуска, кто молчит."""
    c = rep["counts"]
    latest = rep["latest"]
    head = (f"<div class='card'>{_chead('monitor', 'Компьютеры клиник', 'как программы назвались серверу при последней связи')}"
            f"<p style='margin:0 0 8px'>Последний выпуск: <b>{esc(latest) or 'API GitHub не ответил'}</b>"
            f" · компьютеров {c['devices']} у {c['clinics']} клиник · отстают {c['behind']}"
            f" · молчат дольше недели {c['silent']}</p>"
            f"<p class='muted' style='margin:0'>Программа называет себя при каждом запросе файла (раз в сутки) и при активации: "
            f"версия, канал, Windows, личность машины (device.json). Сервер только слушает — обновиться "
            f"программе никто не велит. JSON того же: <a href='/admin/api/fleet'>/admin/api/fleet</a>.</p></div>")
    rows = []
    for d in rep["devices"]:
        tags = (" <span class='tag warn'>отстаёт</span>" if d["behind"] else "") + \
               (" <span class='tag bad'>молчит</span>" if d["silent"] else "")
        rows.append(f"<tr><td><a href='/admin/clinics/{esc(d['clinic_id'])}'>{esc(d['clinic'])}</a> {_tag(d['state'])}</td>"
                    f"<td class='mono'>{esc(d['device'])}</td><td>{esc(d['version'] or '—')}{tags}</td>"
                    f"<td>{esc(d['channel'] or '—')}</td><td>{esc(d['os'] or '—')}</td>"
                    f"<td>{esc((d['last_seen_at'] or '')[:16].replace('T', ' '))}"
                    f"{(' <span class=muted>(' + str(d['silent_days']) + ' дн.)</span>') if d['silent_days'] else ''}</td>"
                    f"<td>{d['last_seq'] if d['last_seq'] is not None else '—'}</td></tr>")
    table = (f"<div class='card'><table><tr><th>Клиника</th><th>Компьютер</th><th>Версия</th><th>Канал</th>"
             f"<th>Windows</th><th>Последняя связь (UTC)</th><th>Файл у программы</th></tr>"
             f"{''.join(rows) or '<tr><td colspan=7 class=muted>Ни один компьютер ещё не выходил на связь</td></tr>'}"
             f"</table></div>")
    return page("Флот", head + table, user, msg, pending=pending, active="fleet",
                lead="Кто на какой версии и когда программа выходила на связь в последний раз.")


def clinic_page(c, sub, issues: list, audit: list, user: str, msg: str = "",
                payments: list = (), pending: int = 0, reminders: list = (), accounts: list = (),
                devices: list = ()) -> str:
    now = datetime.now(timezone.utc)
    st = license.state(_ts(sub["valid_until"]) if sub else None, sub["grace_days"] if sub else 0, now)
    head = (f"<div class='card'><div class='kv'>"
            f"<div><label>IDNO</label><div class='v mono'>{esc(c['idno'] or '—')}</div></div>"
            f"<div><label>Контакт</label><div class='v'>{esc(c['contact_name'] or '—')}</div></div>"
            f"<div><label>E-mail</label><div class='v'>{esc(c['email'] or '—')}</div></div>"
            f"<div><label>Телефон</label><div class='v'>{esc(c['phone'] or '—')}</div></div>"
            f"<div><label>Тариф</label><div class='v'>{esc(sub['plan']) if sub else '—'}</div></div>"
            f"<div><label>Срок до</label><div class='v'>{_d(sub['valid_until']) if sub else '—'} {_tag(st)}</div></div>"
            f"<div><label>Льгота</label><div class='v'>{sub['grace_days'] if sub else '—'} дн.</div></div>"
            f"<div><label>Идентификатор</label><div class='v mono'>{esc(c['id'])}</div></div>"
            f"<div><label>Программа спрашивала</label><div class='v'>"
            f"{_renew_info(c, max((i['seq'] for i in issues), default=0))}</div></div>"
            f"</div></div>")
    edit = (f"<details><summary>Изменить реквизиты</summary><div class='card'>"
            f"<form method='post' action='/admin/clinics/{esc(c['id'])}/edit'><div class='grid'>"
            f"<div><label>Название *</label><input name='name' value='{esc(c['name'])}' required></div>"
            f"<div><label>IDNO</label><input name='idno' value='{esc(c['idno'])}' maxlength='13'></div>"
            f"<div><label>Контакт</label><input name='contact_name' value='{esc(c['contact_name'])}'></div>"
            f"<div><label>E-mail</label><input name='email' value='{esc(c['email'])}'></div>"
            f"<div><label>Телефон</label><input name='phone' value='{esc(c['phone'])}'></div>"
            f"<div><label>Адрес</label><input name='address' value='{esc(c['address'])}'></div></div>"
            f"<p style='margin:14px 0 0'><button class='primary'>Сохранить</button></p></form></div></details>")
    issue_form = (f"<div class='card'>{_chead('key', 'Выдать файл', 'пробный или абонемент до даты; программа клиники заберёт файл сама')}"
                  f"<form method='post' action='/admin/clinics/{esc(c['id'])}/issue'>"
                  f"<div class='grid'><div><label>Что выдать</label><select name='kind'>"
                  f"<option value='trial'>Пробный: {license.TRIAL_DAYS} дней + {license.TRIAL_GRACE_DAYS} льготы</option>"
                  f"<option value='dates'>Абонемент до даты</option></select></div>"
                  f"<div><label>Срок до (для абонемента)</label><input name='valid_until' type='date'></div>"
                  f"<div><label>Льгота, дней</label><input name='grace_days' type='number' value='{license.GRACE_DAYS}' min='0' max='60'></div>"
                  f"<div><label>Основание</label><input name='reason' placeholder='платёж DP-2026-000001, демонстрация…'></div></div>"
                  f"<label class='chk'><input type='checkbox' name='send' value='1'> сразу отправить письмом на {esc(c['email'] or '— e-mail не указан')}</label>"
                  f"<p style='margin:12px 0 0'><button class='primary'>Выдать</button></p></form></div>")
    price = sub["price"] if sub else config.PRICE_MONTH
    opts = "".join(f"<option value='{m}'>{'месяц' if m == 1 else 'год'} — {pay.amount(m, price)} MDL</option>"
                   for m in pay.MONTHS)
    if maib.enabled():
        method = ("<div><label>Как платит клиника</label><select name='method'>"
                  "<option value='transfer'>Переводом — реквизиты и reference в письме</option>"
                  "<option value='card'>Картой — ссылка maib в письме (и reference для перевода)</option>"
                  "</select></div>")
    else:
        method = ("<div><label>Как платит клиника</label><div class='muted' style='padding:9px 0'>только переводом: "
                  "DP_MAIB_* не заданы, ссылки на карту нет</div></div>")
    pay_form = (f"<div class='card'>{_chead('card', 'Платежи', f'{price} MDL в месяц · {pay.amount(12, price)} MDL в год')}"
                f"<form method='post' action='/admin/clinics/{esc(c['id'])}/payments'>"
                f"<div class='grid'><div><label>Срок</label><select name='months'>{opts}</select></div>"
                f"<div><label>Сумма, MDL (пусто = по тарифу)</label><input name='amount' inputmode='numeric'></div>"
                f"{method}</div>"
                f"<label class='chk'><input type='checkbox' name='send' value='1' checked> отправить письмо с нотой "
                f"на {esc(c['email'] or '— e-mail не указан')}</label>"
                f"<p style='margin:12px 0 16px'><button class='primary'>Создать платёж</button></p></form>"
                f"<table><tr><th>Reference</th><th>Сумма</th><th>Срок</th><th>Создан</th><th>Состояние</th><th></th></tr>"
                f"{_payment_rows(list(payments)) or '<tr><td colspan=6 class=muted>Платежей ещё нет</td></tr>'}</table></div>")
    trs = "".join(
        f"<tr><td>{i['seq']}</td><td class='mono'>{esc(i['issued_at'][:16].replace('T', ' '))}</td>"
        f"<td>{_d(i['valid_until'])}</td><td>{_d(i['grace_until'])}</td><td>{esc(i['reason'])}</td>"
        f"<td><a href='/admin/clinics/{esc(c['id'])}/issues/{i['seq']}/license.json'>license.json</a></td></tr>"
        for i in issues) or "<tr><td colspan='6' class='muted'>Файлов ещё не выдавали</td></tr>"
    mail_btn = (f"<form method='post' action='/admin/clinics/{esc(c['id'])}/email' style='margin:12px 0 0'>"
                f"<button class='primary' title='Письмо о сроке лицензии; файла в письме нет (02.10) — программа "
                f"забирает его сама'>Отправить письмо о лицензии</button></form>" if issues else "")
    issues_html = (f"<div class='card'>{_chead('file', 'Выданные файлы', 'каждый следующий — с номером выше; программа берёт только новее принятого')}"
                   f"<table><tr><th>№</th><th>Выдан (UTC)</th>"
                   f"<th>Срок до</th><th>Льгота до</th><th>Основание</th><th>Файл</th></tr>{trs}</table>{mail_btn}</div>")
    rem_html = (f"<div class='card'>{_chead('bell', 'Напоминания', 'письма ежедневной задачи этой клинике')}"
                f"<table><tr><th>Письмо</th><th>Период до</th>"
                f"<th>Отправлено</th></tr>{_reminder_rows(list(reminders)) or '<tr><td colspan=3 class=muted>Напоминаний ещё не было</td></tr>'}"
                f"</table></div>")
    ars = "".join(f"<tr><td class='mono'>{esc(a['at'][:16].replace('T', ' '))}</td><td>{esc(a['who'])}</td>"
                  f"<td><span class='tag mute'>{esc(a['what'])}</span></td><td>{esc(a['detail'])}</td></tr>" for a in audit)
    audit_html = (f"<div class='card'>{_chead('clock', 'Журнал', 'события этой клиники')}"
                  f"<table><tr><th>Когда (UTC)</th><th>Кто</th><th>Что</th>"
                  f"<th>Подробности</th></tr>{ars or '<tr><td colspan=4 class=muted>пусто</td></tr>'}</table></div>")
    acc_rows = "".join(
        f"<tr><td>{esc(a['email'])}</td><td>{esc(a['provider'] if 'provider' in a.keys() else 'google')}</td>"
        f"<td>{esc(a['name'] or '—')}</td><td>{esc((a['created_at'] or '')[:10])}</td>"
        f"<td>{esc((a['last_login_at'] or '')[:16].replace('T', ' '))}</td>"
        f"<td><form method='post' action='/admin/accounts/{esc(a['id'])}/detach' style='margin:0'>"
        f"<button title='Запись удаляется; следующий вход этого аккаунта начнётся с регистрации'>"
        f"Отвязать</button></form></td></tr>" for a in accounts)
    acc_html = (f"<div class='card'>{_chead('user', 'Кабинет клиники', f'кто входит в кабинет {esc(config.BASE_URL.rstrip(chr(47)))}/cont — через Google или кодом на e-mail')}"
                f"<p class='muted' style='margin:0 0 10px'>Смена директора: впишите клинике новый "
                f"e-mail (выше) и отвяжите старую запись — новый вход привяжется к клинике по ящику.</p>"
                f"<table><tr><th>E-mail</th><th>Вход</th><th>Имя</th><th>С</th><th>Последний вход</th><th></th></tr>"
                f"{acc_rows or '<tr><td colspan=6 class=muted>В кабинет ещё никто не входил</td></tr>'}</table></div>")
    dev_html = (f"<div class='card'>{_chead('monitor', 'Компьютеры', 'как программа этой клиники назвалась серверу')}"
                f"<table><tr><th>Компьютер</th><th>Версия</th><th>Канал</th>"
                f"<th>Windows</th><th>С</th><th>Последняя связь (UTC)</th><th>Файл у программы</th></tr>"
                f"{_device_rows(list(devices)) or '<tr><td colspan=7 class=muted>Программа этой клиники ещё не выходила на связь</td></tr>'}"
                f"</table></div>")
    lead = f"{_tag(st)} <span class='muted'>{esc(sub['plan']) if sub else 'без файла'} · срок до {_d(sub['valid_until']) if sub else '—'} · IDNO {esc(c['idno'] or '—')}</span>"
    return page(c["name"], head + edit + acc_html + dev_html + pay_form + issue_form + issues_html + rem_html
                + audit_html, user, msg, pending=pending, active="clinics", lead=lead)


# ---------- кабинет клиники (шаг 3, 01.10): страницы по-румынски ----------

CONT_MSG = {
    "google_off": "Contul clinicii nu este disponibil încă: autentificarea cu Google nu este configurată pe "
                  "acest server. Scrieți-ne.",
    "google_denied": "Autentificarea a fost anulată. Puteți încerca din nou.",
    "google_expired": "Sesiunea de autentificare a expirat sau nu s-a potrivit — încercați din nou.",
    "google_failed": "Google nu a confirmat autentificarea — încercați din nou peste un minut sau scrieți-ne.",
    "google_unverified": "Adresa de e-mail a contului Google nu este confirmată de Google — folosiți alt cont "
                         "Google sau scrieți-ne.",
    "logged_out": "Ați ieșit din cont.",
    "registered_issued": "Clinica a fost înregistrată, perioada de probă este activă. Descărcați programul: "
                         "la prima pornire se activează singur.",
    "registered_requested": "Clinica a fost înregistrată. Cererea de probă a fost primită — vă răspundem pe "
                            "e-mail în cel mult o zi lucrătoare.",
    "duplicate": "O clinică cu acest IDNO este deja înregistrată la DentPilot, dar codul de conectare nu a "
                 "putut fi trimis pe e-mailul ei. Am notat cererea și vă răspundem pe e-mail.",
    "linked": "Contul Google a fost conectat la clinică.",
    "saved": "Datele clinicii au fost salvate.",
    "idno_taken": "Acest IDNO este deja înregistrat la altă clinică — scrieți-ne.",
    "note_created": "Nota de plată a fost creată: datele pentru plată sunt mai jos și pe e-mail.",
    "note_exists": "Aveți deja o notă de plată în așteptare — datele pentru plată sunt mai jos.",
    "need_idno": "Pentru abonament completați mai întâi IDNO-ul clinicii (13 cifre), în datele clinicii.",
    "maib_failed": "Pagina de plată cu cardul nu a putut fi creată acum — încercați din nou sau alegeți "
                   "transferul bancar.",
    "bad_months": "Alegeți o lună sau un an.",
    "closed": "Cererea clinicii a fost închisă — scrieți-ne.",
    # вход кодом на e-mail (02.10)
    "bad_email": "Introduceți o adresă de e-mail validă.",
    "login_limited": "Prea multe coduri cerute — încercați peste o oră sau scrieți-ne.",
    "mail_failed": "Nu am putut trimite e-mailul cu codul — încercați din nou peste un minut sau scrieți-ne.",
}
_CONT_OK = {"logged_out", "registered_issued", "registered_requested", "saved", "note_created", "note_exists",
            "linked"}
STATE_RO = {"active": ("ok", "activă"), "grace": ("warn", "expirată — perioada de plată"),
            "readonly": ("bad", "regim de citire"), "none": ("mute", "neactivată")}
PAY_RO = {"pending": ("warn", "în așteptare"), "paid": ("ok", "plătită"), "rejected": ("bad", "respinsă")}
# Кабинет клиники — СВОЙ стиль по токенам сайта dentpilot.md (Inter с сайта: шрифты
# Pages отдаются с CORS *, бирюза, карточки с мягкой тенью, липкая шапка). 02.10,
# слово Олега «под современный дизайн»: главная — дашборд, а не столбик карточек:
# карточка состояния лицензии во всю ширину (срок, полоса дней, панель программы с
# кнопкой скачивания и действием по оплате), ниже компьютеры клиники и аккаунт,
# затем абонамент и платежи, данные клиники. Вход — панель бренда слева, карточка
# справа. Телефон — в один столбец. Админка остаётся на _CSS — инструмент одного
# человека. ⛔ Тексты страниц — поведение: их держат cloud/tests (test_account,
# test_fleet, test_contract); правя раскладку, слова не менять.
_CONT_CSS = _FONTS + """
:root{--ink:#16232B;--muted:#5B6B72;--line:#E6EDEB;--teal:#0E9F8A;--teal-d:#0B7F70;--teal-soft:#E9F6F3;--bg:#F4F8F7;--shadow:0 1px 2px rgba(11,43,38,.04),0 18px 44px -22px rgba(11,43,38,.18)}
*{box-sizing:border-box}
html{background:var(--bg)}
body{margin:0;background:var(--bg);color:var(--ink);font-family:'Inter',system-ui,-apple-system,'Segoe UI',sans-serif;-webkit-font-smoothing:antialiased;line-height:1.5}
a{color:var(--teal-d)}
.top{position:sticky;top:0;z-index:5;background:rgba(255,255,255,.88);backdrop-filter:blur(14px) saturate(1.2);border-bottom:1px solid var(--line)}
.top-in{max-width:1120px;margin:0 auto;padding:0 24px;height:64px;display:flex;align-items:center;gap:14px}
.logo{display:flex;align-items:center;gap:10px;text-decoration:none;color:var(--ink);font-weight:700;font-size:16px}
.logo .ic{width:32px;height:32px;border-radius:9px;background:var(--teal);display:inline-flex;align-items:center;justify-content:center}
.logo .sub{font-weight:500;color:var(--muted);font-size:14px}
.acc{margin-left:auto;display:flex;align-items:center;gap:8px;background:#fff;border:1px solid var(--line);border-radius:999px;padding:4px 6px 4px 4px}
.acc .av{width:30px;height:30px;border-radius:50%;background:var(--teal-soft);color:var(--teal-d);display:inline-flex;align-items:center;justify-content:center;font-weight:700;font-size:12.5px;flex:none}
.acc .em{font-size:13.5px;color:var(--ink);max-width:28vw;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.acc form{margin:0}.acc button{background:transparent;border:0;border-left:1px solid var(--line);border-radius:0;color:var(--muted);padding:4px 8px 4px 10px;font:inherit;font-size:13.5px;font-weight:600;cursor:pointer}
.acc button:hover{color:var(--teal-d)}
.site{margin-left:auto;text-decoration:none;color:var(--muted);font-size:14px;font-weight:500}
.wrap{max-width:1120px;margin:0 auto;padding:32px 24px 72px}
.eyebrow{display:inline-flex;align-items:center;gap:8px;font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--teal-d);margin:0 0 10px}
.eyebrow:before{content:'';width:6px;height:6px;border-radius:50%;background:var(--teal)}
h1{font-size:clamp(26px,3.6vw,34px);letter-spacing:-.025em;margin:0 0 8px;line-height:1.15}
.lead{color:var(--muted);font-size:16px;line-height:1.55;margin:0 0 22px;max-width:48em}
.card{background:#fff;border:1px solid var(--line);border-radius:18px;padding:22px 24px;box-shadow:var(--shadow);margin:0 0 18px}
.chead{display:flex;align-items:center;gap:12px;margin:0 0 14px;flex-wrap:wrap}
.chead .ico{width:38px;height:38px;border-radius:11px;background:var(--teal-soft);color:var(--teal-d);display:inline-flex;align-items:center;justify-content:center;flex:none}
.chead h2{font-size:16.5px;margin:0;letter-spacing:-.01em}.chead .sub{font-size:13px;color:var(--muted);margin:2px 0 0}
.chead .right{margin-left:auto}
.grid2{display:grid;grid-template-columns:minmax(0,1.6fr) minmax(0,1fr);gap:18px;margin:0 0 18px}
.grid2 .card{margin:0;display:flex;flex-direction:column}
.hero{display:grid;grid-template-columns:minmax(0,1fr) 340px;padding:0;overflow:hidden}
.hero .main{padding:26px 28px}
.hero .side{background:linear-gradient(160deg,#0E9F8A 0%,#0B7F70 100%);color:#fff;padding:26px 24px;display:flex;flex-direction:column;gap:10px}
.hero .side .eyebrow{color:rgba(255,255,255,.78)}.hero .side .eyebrow:before{background:rgba(255,255,255,.6)}
.hero .side .big{font-size:27px;font-weight:700;letter-spacing:-.02em;line-height:1.1}
.hero .side .small{font-size:13.5px;color:rgba(255,255,255,.82);line-height:1.5}
.hero .side .small a{color:#fff}
.hero .side .actions{margin-top:auto;display:flex;flex-direction:column;gap:8px;padding-top:8px}
.hero .side a.btn{background:#fff;color:var(--teal-d);border-color:#fff;width:100%}
.hero .side a.btn:hover{background:var(--teal-soft);border-color:var(--teal-soft);color:var(--teal-d)}
.hero .side a.btn.ghost{background:transparent;color:#fff;border-color:rgba(255,255,255,.55)}
.hero .side a.btn.ghost:hover{background:rgba(255,255,255,.12);border-color:#fff;color:#fff}
.lic{font-size:18px;line-height:1.45;margin:0 0 6px}
.bar{height:8px;border-radius:999px;background:#E6EFEC;overflow:hidden;margin:16px 0 8px}
.bar>span{display:block;height:100%;border-radius:999px;background:var(--teal)}
.bar.warn>span{background:#D97706}.bar.bad>span{background:#DC2626}
.days{display:flex;justify-content:space-between;gap:12px;font-size:13px;color:var(--muted)}.days span:first-child{white-space:nowrap}
.dev{list-style:none;padding:0;margin:0}
.dev li{display:flex;align-items:flex-start;gap:12px;padding:10px 0;border-top:1px solid #EEF2F1;font-size:14px;line-height:1.45}
.dev li:first-child{border-top:0;padding-top:0}
.dev .dot{width:8px;height:8px;border-radius:50%;background:var(--teal);margin-top:7px;flex:none}
.dev .dot.old{background:#D97706}
.dev .when{color:var(--muted);font-size:13px}
.empty{color:var(--muted);font-size:14px;line-height:1.5;padding:12px 14px;background:var(--bg);border-radius:12px}
label{display:block;font-size:13px;color:var(--muted);margin:10px 0 5px;font-weight:500}
input,select{font:inherit;font-size:15px;padding:11px 13px;border:1px solid #D8E2DF;border-radius:10px;width:100%;background:#fff;color:var(--ink)}
input:focus,select:focus{outline:none;border-color:var(--teal);box-shadow:0 0 0 3px rgba(14,159,138,.18)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:0 20px}
button.primary,a.btn{display:inline-flex;align-items:center;justify-content:center;gap:10px;background:var(--teal);color:#fff;border:1px solid var(--teal);border-radius:10px;padding:12px 22px;font:inherit;font-size:15px;font-weight:600;cursor:pointer;text-decoration:none;transition:background .15s,border-color .15s,color .15s}
button.primary:hover,a.btn:hover{background:var(--teal-d);border-color:var(--teal-d);color:#fff}
a.btn.second{background:#fff;color:var(--ink);border-color:#D8E2DF}a.btn.second:hover{background:var(--teal-soft);color:var(--teal-d);border-color:var(--teal)}
button:not(.primary){background:#fff;border:1px solid #D8E2DF;color:var(--ink);border-radius:10px;padding:10px 16px;font:inherit;font-size:14.5px;font-weight:500;cursor:pointer}
a.gbtn{display:inline-flex;align-items:center;justify-content:center;gap:12px;background:#fff;color:var(--ink);border:1px solid #D8E2DF;border-radius:12px;padding:14px 24px;font-size:15.5px;font-weight:600;text-decoration:none;width:100%;box-shadow:0 1px 2px rgba(11,43,38,.06)}
a.gbtn:hover{border-color:var(--teal);color:var(--teal-d)}
.banner{padding:12px 16px;border-radius:12px;margin:0 0 18px;font-size:14.5px}
.banner.ok{background:#ECFDF5;color:#065F46}.banner.err{background:#FEF2F2;color:#B91C1C}
.tag{display:inline-block;padding:3px 10px;border-radius:999px;font-size:12.5px;font-weight:600;vertical-align:middle}
.tag.ok{background:#ECFDF5;color:#065F46}.tag.warn{background:#FFFBEB;color:#B45309}.tag.bad{background:#FEF2F2;color:#B91C1C}.tag.mute{background:#EEF2F1;color:#5B6B72}
.mono{font-family:ui-monospace,Consolas,monospace;font-size:13px}.muted{color:var(--muted);font-size:14px;line-height:1.5}
table{border-collapse:collapse;width:100%;font-size:14px}th,td{text-align:left;padding:10px;border-bottom:1px solid #EEF2F1;vertical-align:top}
th{color:var(--muted);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.05em}
tr:last-child td{border-bottom:0}
pre.pay{background:var(--bg);border:1px solid var(--line);border-radius:14px;padding:16px 18px;font:inherit;font-size:14.5px;white-space:pre-wrap;margin:12px 0;line-height:1.55}
.price{display:inline-flex;gap:6px;align-items:baseline;background:var(--teal-soft);color:var(--teal-d);border-radius:10px;padding:6px 12px;font-size:13.5px;font-weight:600;white-space:nowrap}
label.chk{display:flex;gap:10px;align-items:flex-start;color:var(--ink);font-size:14.5px;font-weight:400;margin:14px 0 4px}
label.chk input{width:auto;margin-top:3px}
.foot{font-size:13px;color:#7C8B91;margin-top:36px;border-top:1px solid var(--line);padding-top:16px;line-height:1.6}
.split{display:grid;grid-template-columns:minmax(0,1fr) 380px;gap:18px;align-items:start}
.split .card{margin:0}
.perks{list-style:none;padding:0;margin:0}.perks li{display:flex;gap:10px;align-items:flex-start;font-size:14.5px;line-height:1.45;margin:0 0 10px}
.perks svg{flex:none;margin-top:2px}.chip{display:inline-block;background:var(--teal-soft);color:var(--teal-d);border-radius:999px;padding:5px 12px;font-size:13.5px;font-weight:600}
.narrow{max-width:560px;margin:0 auto}
.auth{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);border-radius:22px;overflow:hidden;box-shadow:var(--shadow);border:1px solid var(--line);background:#fff;margin-top:6px}
.auth .brand{background:linear-gradient(160deg,#0E9F8A 0%,#0B7F70 100%);color:#fff;padding:40px 36px;display:flex;flex-direction:column;gap:18px}
.auth .brand .mark{width:48px;height:48px;border-radius:14px;background:rgba(255,255,255,.16);display:inline-flex;align-items:center;justify-content:center}
.auth .brand h2{font-size:clamp(24px,3vw,30px);margin:0;letter-spacing:-.02em;line-height:1.15}
.auth .brand p{margin:0;color:rgba(255,255,255,.85);font-size:15px;line-height:1.55}
.auth .brand .perks li{color:#fff}.auth .brand .perks svg path{stroke:#fff}
.auth .brand .fine{margin-top:auto;font-size:13px;color:rgba(255,255,255,.72);line-height:1.5}
.auth .form{padding:40px 36px}
.auth .form h2{margin:0 0 6px;font-size:22px;letter-spacing:-.015em}
.or{display:flex;align-items:center;gap:12px;color:var(--muted);font-size:13px;margin:4px 0 14px}
.or:before,.or:after{content:'';flex:1;height:1px;background:var(--line)}
@media (max-width:900px){.hero{grid-template-columns:1fr}.grid2{grid-template-columns:1fr}.split{grid-template-columns:1fr}.auth{grid-template-columns:1fr}.auth .brand{padding:28px 22px}.auth .form{padding:26px 22px}}
@media (max-width:720px){.chead .right{margin-left:0;flex-basis:100%}.price{white-space:normal}.wrap{padding:22px 16px 48px}.top-in{padding:0 16px;height:60px}.logo .sub{display:none}.acc .em{display:none}.card{padding:18px 16px;border-radius:16px}.hero .main{padding:20px 18px}.hero .side{padding:20px 18px}button.primary,a.btn,a.gbtn{width:100%}}
"""
_TOOTH = ("<svg width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='#FFFFFF' stroke-width='1.8' "
          "stroke-linecap='round' stroke-linejoin='round'><path d='M8.2 3.8C5.9 3.8 4 5.7 4 8.2c0 1.9.8 3.2 1.4 4.7.7 "
          "1.7 1 4.4 1.8 6.6.3.9 1.5.9 1.8 0 .6-1.9.8-4 1.6-5.2.6-.9 1.7-.9 2.3 0 .8 1.2 1 3.3 1.6 5.2.3.9 1.5.9 1.8 0 "
          ".8-2.2 1.1-4.9 1.8-6.6.6-1.5 1.4-2.8 1.4-4.7 0-2.5-1.9-4.4-4.2-4.4-1.1 0-1.9.5-3.1.5s-2-.5-3.2-.5z'/></svg>")
_TOOTH_L = _TOOTH.replace("width='16' height='16'", "width='26' height='26'")
_CHECK = ("<svg width='18' height='18' viewBox='0 0 24 24' fill='none' stroke='#0E9F8A' stroke-width='2.2' "
          "stroke-linecap='round' stroke-linejoin='round'><path d='M5 12.5l4.5 4.5L19 7'/></svg>")
# Значки карточек — currentColor, как на сайте: цвет берут у .chead .ico
_ICO = {
    "shield": "<path d='M12 3l7 3v5c0 5-3.5 8.6-7 10-3.5-1.4-7-5-7-10V6z'/><path d='M9 12l2 2 4-4'/>",
    "download": "<path d='M12 4v11'/><path d='M7 10l5 5 5-5'/><path d='M4 20h16'/>",
    "monitor": "<rect x='3' y='4' width='18' height='12' rx='2'/><path d='M8 20h8M12 16v4'/>",
    "card": "<rect x='3' y='5' width='18' height='14' rx='2'/><path d='M3 10h18'/><path d='M7 15h4'/>",
    "building": "<path d='M4 21V5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v16'/><path d='M16 9h2a2 2 0 0 1 2 2v10'/>"
                "<path d='M8 7h4M8 11h4M8 15h4'/><path d='M3 21h18'/>",
    "user": "<circle cx='12' cy='8' r='4'/><path d='M4 20c0-3.3 3.6-5.5 8-5.5s8 2.2 8 5.5'/>",
    "key": "<circle cx='8' cy='15' r='4'/><path d='M10.8 12.2L20 3'/><path d='M16 7l2 2M13 10l2 2'/>",
    # админка
    "inbox": "<path d='M4 13l2.5-7h11L20 13'/><path d='M4 13v5a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-5h-5l-1.5 2h-3L9 13z'/>",
    "list": "<path d='M8 6h12M8 12h12M8 18h12'/><circle cx='4' cy='6' r='1'/><circle cx='4' cy='12' r='1'/><circle cx='4' cy='18' r='1'/>",
    "plus": "<path d='M12 5v14M5 12h14'/>",
    "file": "<path d='M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z'/><path d='M14 3v5h5'/>",
    "bell": "<path d='M6 9a6 6 0 0 1 12 0v4l2 3H4l2-3z'/><path d='M10 20a2 2 0 0 0 4 0'/>",
    "clock": "<circle cx='12' cy='12' r='9'/><path d='M12 7v5l3 2'/>",
}


def _ic(name: str, size: int = 18) -> str:
    return (f"<svg width='{size}' height='{size}' viewBox='0 0 24 24' fill='none' stroke='currentColor' "
            f"stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round' aria-hidden='true'>{_ICO[name]}</svg>")


def _chead(icon: str, title: str, sub: str = "", right: str = "") -> str:
    return (f"<div class='chead'><span class='ico'>{_ic(icon)}</span><div><h2>{title}</h2>"
            f"{('<p class=' + chr(39) + 'sub' + chr(39) + '>' + sub + '</p>') if sub else ''}</div>"
            f"{('<div class=' + chr(39) + 'right' + chr(39) + '>' + right + '</div>') if right else ''}</div>")


def _perks(items: list[str]) -> str:
    return "<ul class='perks'>" + "".join(f"<li>{_CHECK}<span>{t}</span></li>" for t in items) + "</ul>"
_G = ("<svg width='18' height='18' viewBox='0 0 48 48' aria-hidden='true'>"
      "<path fill='#EA4335' d='M24 9.5c3.5 0 6.6 1.2 9.1 3.6l6.8-6.8C35.8 2.4 30.3 0 24 0 14.6 0 6.5 5.4 2.6 13.3l7.9 6.1C12.4 13.7 17.7 9.5 24 9.5z'/>"
      "<path fill='#4285F4' d='M46.5 24.5c0-1.6-.1-3.1-.4-4.5H24v9h12.7c-.6 2.9-2.2 5.4-4.7 7.1l7.6 5.9c4.4-4.1 6.9-10.1 6.9-17.5z'/>"
      "<path fill='#FBBC05' d='M10.5 28.6c-.5-1.4-.8-3-.8-4.6s.3-3.2.8-4.6l-7.9-6.1C.9 16.5 0 20.1 0 24s.9 7.5 2.6 10.7l7.9-6.1z'/>"
      "<path fill='#34A853' d='M24 48c6.5 0 11.9-2.1 15.9-5.8l-7.6-5.9c-2.1 1.4-4.9 2.3-8.3 2.3-6.3 0-11.6-4.2-13.5-10l-7.9 6.1C6.5 42.6 14.6 48 24 48z'/></svg>")


def cont_text(code: str) -> str:
    return CONT_MSG.get(code) or TRIAL_MSG.get(code) or code


def _ro(s: str | None) -> str:
    """ISO-дата сервера → как пишут в Молдове: 17.10.2026."""
    if not s or len(s) < 10:
        return "—"
    return f"{s[8:10]}.{s[5:7]}.{s[0:4]}"


def _initials(acc) -> str:
    """Две буквы для аватара: из имени Google, иначе первая буква ящика."""
    # ⚠️ acc — строка sqlite (Row): доступ по ключу, метода .get у неё нет
    name = (acc["name"] or "").strip()
    parts = [p for p in name.replace("-", " ").split() if p]
    if len(parts) >= 2:
        return (parts[0][0] + parts[-1][0]).upper()
    if parts:
        return parts[0][:2].upper()
    return (acc["email"] or "?")[:1].upper()


def _cont_shell(title: str, inner: str, acc=None, msg: str = "", lead: str = "",
                eyebrow: str = "Contul clinicii", plain: bool = False) -> str:
    """Каркас кабинета: липкая шапка (логотип, чип аккаунта с выходом), заголовок
    с надстрочником, баннер сообщения, тело, подвал. `plain` — без заголовка
    (вход: его роль играет панель бренда)."""
    site = config.SITE_URL.rstrip("/")
    banner = ""
    if msg:
        banner = f"<div class='banner {'ok' if msg in _CONT_OK else 'err'}'>{esc(cont_text(msg))}</div>"
    if acc is not None:
        who = (f"<div class='acc'><span class='av'>{esc(_initials(acc))}</span>"
               f"<span class='em' title='{esc(acc['email'])}'>{esc(acc['email'])}</span>"
               f"<form method='post' action='/cont/iesire'><button title='{esc(acc['email'])}'>Ieșire</button></form></div>")
    else:
        who = f"<a class='site' href='{esc(site)}'>dentpilot.md</a>"
    bar = (f"<div class='top'><div class='top-in'><a class='logo' href='/cont'><span class='ic'>{_TOOTH}</span>"
           f"DentPilot <span class='sub'>· Contul clinicii</span></a>{who}</div></div>")
    head = "" if plain else (
        f"{('<p class=' + chr(39) + 'eyebrow' + chr(39) + '>' + esc(eyebrow) + '</p>') if eyebrow else ''}"
        f"<h1>{esc(title)}</h1>"
        f"{('<p class=' + chr(39) + 'lead' + chr(39) + '>' + lead + '</p>') if lead else ''}")
    foot = (f"<p class='foot'><a href='{esc(site)}/termeni.html'>Termeni și condiții</a> · "
            f"<a href='{esc(site)}/privacy.html'>Politica de confidențialitate</a> · "
            f"Întrebări: <a href='mailto:{esc(config.SUPPORT_EMAIL)}'>{esc(config.SUPPORT_EMAIL)}</a> · "
            f"{esc(config.SUPPORT_PHONE)}</p>")
    return (f"<!doctype html><html lang='ro'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<meta name='robots' content='noindex'>"
            f"<title>{esc(title)} — DentPilot</title><style>{_CONT_CSS}</style></head>"
            f"<body>{bar}<div class='wrap'>{head}{banner}{inner}{foot}</div></body></html>")


_PERKS = [
    "Perioada de probă — o lună gratuită, fără card și fără obligații",
    "Programul DentPilot, de descărcat oricând — se activează singur",
    "Nota de plată pentru abonament, cu datele pentru plată",
    "Datele clinicii și calculatoarele pe care rulează programul",
]


def cont_login_page(msg: str = "", enabled: bool = True, values: dict | None = None) -> str:
    """Вход: Google (если настроен) и код на e-mail (всегда, 02.10). `values` —
    ящик, введённый перед отказом, чтобы не набирать заново."""
    site = config.SITE_URL.rstrip("/")
    typed = esc((values or {}).get("email", ""))
    by_mail = (f"<form method='post' action='/cont/login/email' style='margin-top:4px'>"
               f"<label for='l-email'>E-mailul clinicii sau al dvs.</label>"
               f"<input id='l-email' type='email' name='email' value='{typed}' required maxlength='{trial.EMAIL_MAX}' "
               f"autocomplete='email' placeholder='nume@clinica.md'>"
               f"<p style='margin:12px 0 0'><button class='primary' style='width:100%'>Trimite codul de intrare</button></p>"
               f"</form><p class='muted' style='margin:10px 0 0'>Primiți pe e-mail un cod de 6 cifre, valabil "
               f"{int(trial.CODE_TTL.total_seconds() // 60)} minute — fără parolă.</p>")
    if enabled:
        entry = (f"<p style='margin:18px 0 14px'><a class='gbtn' href='/auth/google'>{_G} Continuați cu Google</a></p>"
                 f"<div class='or'><span>sau cu e-mail</span></div>{by_mail}"
                 f"<p class='muted' style='margin-top:18px'>Prima dată: după intrare completați datele clinicii și primiți perioada de "
                 f"probă de {mail.zile(license.TRIAL_DAYS)}, fără plată. Clinica deja înregistrată la DentPilot cu "
                 f"același e-mail intră direct în cont.</p>")
    else:
        entry = (f"<div style='margin-top:18px'>{by_mail}</div>"
                 f"<p class='muted' style='margin-top:18px'>Prima dată: după intrare completați datele clinicii și primiți perioada de "
                 f"probă de {mail.zile(license.TRIAL_DAYS)}, fără plată. Clinica deja înregistrată la DentPilot cu "
                 f"același e-mail intră direct în cont.</p>"
                 f"<p class='muted'>Autentificarea cu Google nu este configurată pe acest server.</p>")
    brand = (f"<div class='brand'><span class='mark'>{_TOOTH_L}</span>"
             f"<h2>Contul clinicii DentPilot</h2>"
             f"<p>Un singur loc pentru licența DentPilot a clinicii: intrați cu contul Google sau cu un cod primit pe e-mail — fără parolă.</p>"
             f"{_perks(_PERKS)}"
             f"<p class='fine'>Datele pacienților nu ajung aici niciodată: ele rămân pe calculatorul clinicii.</p></div>")
    form = (f"<div class='form'><h2>Intrați în cont</h2>"
            f"<p class='muted' style='margin:0'>Cu contul Google sau cu un cod primit pe e-mail — fără parolă.</p>{entry}"
            f"<p class='muted'>Preferați formularul? <a href='/proba'>Trimiteți cererea de probă</a> "
            f"— confirmarea vine pe e-mail.</p>"
            f"<p class='muted' style='margin-bottom:0'>De la Google primim doar adresa de e-mail, numele și "
            f"identificatorul contului; parola rămâne la Google. Codul de pe e-mail îl păstrăm doar ca amprentă — "
            f"<a href='{esc(site)}/privacy.html'>Politica de confidențialitate</a>, § 5.</p></div>")
    if msg:
        # баннер — над разворотом, в карточке формы, где глаз ищет ответ на свой клик
        form = form.replace("<div class='form'>",
                            f"<div class='form'><div class='banner {'ok' if msg in _CONT_OK else 'err'}'>"
                            f"{esc(cont_text(msg))}</div>", 1)
        msg = ""
    return _cont_shell("Contul clinicii", f"<div class='auth'>{brand}{form}</div>", msg=msg, plain=True)


def cont_email_code_page(vid: str, email: str, msg: str = "") -> str:
    """Код входа ушёл на ящик (02.10): страница с полем кода. Ящик показан — его
    ввёл сам человек секунду назад, оракулом страница не становится."""
    minutes = int(trial.CODE_TTL.total_seconds() // 60)
    inner = (f"<div class='card narrow'>{_chead('key', 'Codul din e-mail', f'valabil {minutes} minute')}"
             f"<p>Am trimis un cod de 6 cifre pe <b>{esc(email)}</b>. Introduceți-l mai jos — intrați în cont "
             f"fără parolă. Nu vedeți mesajul? Verificați și dosarul Spam.</p>"
             f"<form method='post' action='/cont/login/cod'>"
             f"<input type='hidden' name='verify_id' value='{esc(vid)}'>"
             f"<input type='hidden' name='email' value='{esc(email)}'>"
             f"<label for='l-code'>Codul din e-mail</label><input id='l-code' name='code' inputmode='numeric' maxlength='12' "
             f"autocomplete='one-time-code' required autofocus style='font-size:22px;letter-spacing:.2em;max-width:240px'>"
             f"<p><button class='primary'>Intră în cont</button></p></form>"
             f"<p class='muted' style='margin-bottom:0'>Ați greșit adresa sau codul a expirat? <a href='/cont/login'>Înapoi la "
             f"intrare</a> — cereți alt cod.</p></div>")
    return _cont_shell("Intrarea în cont", inner, msg=msg)


def cont_register_page(acc, msg: str = "", values: dict | None = None) -> str:
    v = {k: esc((values or {}).get(k, "")) for k in ("name", "idno", "contact_name", "phone")}
    if not values:
        v["contact_name"] = esc(acc["name"] or "")
    site = config.SITE_URL.rstrip("/")
    form = (f"<div class='card'>{_chead('building', 'Datele clinicii', 'Perioada de probă începe imediat după înregistrare')}"
            f"<form method='post' action='/cont/inregistrare'>"
            f"<label>Denumirea clinicii *</label><input name='name' value='{v['name']}' required maxlength='{trial.NAME_MAX}' autofocus>"
            f"<div class='grid'><div>"
            f"<label>IDNO (13 cifre, opțional pentru probă)</label><input name='idno' value='{v['idno']}' maxlength='13' inputmode='numeric'></div>"
            f"<div><label>Telefon</label><input name='phone' value='{v['phone']}' maxlength='{trial.PHONE_MAX}'></div></div>"
            f"<div class='grid'><div>"
            f"<label>Persoana de contact</label><input name='contact_name' value='{v['contact_name']}' maxlength='{trial.CONTACT_MAX}'></div>"
            f"<div><label>{'E-mail (contul Google)' if acc['provider'] == 'google' else 'E-mail (adresa de intrare)'}</label>"
            f"<div style='padding:11px 0'><span class='chip'>{esc(acc['email'])}</span></div></div></div>"
            f"<label class='chk'><input type='checkbox' name='consent' value='1'> <span>Am citit și accept "
            f"<a href='{esc(site)}/termeni.html' target='_blank' rel='noopener'>Termenii și condițiile</a> și "
            f"<a href='{esc(site)}/privacy.html' target='_blank' rel='noopener'>Politica de confidențialitate</a>."
            f"</span></label><p style='margin:14px 0 0'><button class='primary'>Înregistrez clinica</button></p></form></div>")
    aside = (f"<div class='card'>{_chead('shield', 'Ce urmează')}{_perks(['Perioada de probă de ' + mail.zile(license.TRIAL_DAYS) + ' se activează imediat; confirmarea vine pe e-mail', 'Descărcați programul din cont; la prima pornire introduceți aceleași date și se activează singur', 'IDNO și adresa le completați oricând — sunt necesare doar pentru abonament'])}"
             f"<p class='muted' style='margin-bottom:0'>Aveți deja DentPilot pe un calculator al clinicii? "
             f"Completați aceleași date: trimitem un cod pe e-mailul clinicii și contul se conectează.</p></div>")
    return _cont_shell("Înregistrarea clinicii", f"<div class='split'>{form}{aside}</div>", acc, msg,
                       lead=f"Completați datele clinicii: primiți perioada de probă DentPilot de "
                            f"{mail.zile(license.TRIAL_DAYS)}, fără plată și fără obligații.")


def cont_code_page(acc, vid: str, msg: str = "") -> str:
    """Повтор по IDNO: код ушёл на ящик клиники (01.10). Сам ящик не называется —
    страница не оракул о том, чей e-mail у клиники; письмо называет Google-ящик
    просителя, чтобы клиника видела, кто стучится."""
    minutes = int(trial.CODE_TTL.total_seconds() // 60)
    inner = (f"<div class='card narrow'>{_chead('key', 'Codul din e-mailul clinicii', f'valabil {minutes} minute')}"
             f"<p>O clinică cu acest IDNO este deja înregistrată la DentPilot. Am trimis un "
             f"cod de 6 cifre pe e-mailul înregistrat al clinicii: introduceți-l mai jos și contul "
             f"{'Google ' if acc['provider'] == 'google' else ''}<b>{esc(acc['email'])}</b> va fi conectat la clinică. "
             f"Codul este valabil {minutes} minute.</p>"
             f"<form method='post' action='/cont/inregistrare/cod'>"
             f"<input type='hidden' name='verify_id' value='{esc(vid)}'>"
             f"<label>Codul din e-mail</label><input name='code' inputmode='numeric' maxlength='12' "
             f"autocomplete='one-time-code' required autofocus style='font-size:22px;letter-spacing:.2em;max-width:240px'>"
             f"<p><button class='primary'>Conectează contul</button></p></form>"
             f"<p class='muted' style='margin-bottom:0'>Nu aveți acces la e-mailul clinicii? <a href='/cont/inregistrare'>Înapoi la "
             f"înregistrare</a> sau scrieți-ne.</p></div>")
    return _cont_shell("Conectarea contului", inner, acc, msg)


def _pay_tag_ro(status: str) -> str:
    cls, text = PAY_RO.get(status, ("mute", status))
    return f"<span class='tag {cls}'>{esc(text)}</span>"


def _card_link_ro(p) -> str:
    """Ссылка maib у ожидающего платежа (L12) — в кабинете, по-румынски."""
    if p["status"] != "pending" or not p["pay_url"]:
        return ""
    return f" · <a href='{esc(p['pay_url'])}' target='_blank' rel='noopener'>plata cu cardul</a>"


def _lic_parts(c, sub, issue, st: str, now: datetime) -> dict:
    """Состояние лицензии словами: `text` (с тегом), `check` (последняя проверка
    программой), `bar` (полоса дней — только при выданном файле)."""
    if issue is None:
        if c["declined_at"]:
            return {"text": esc(CONT_MSG["closed"]), "check": "", "bar": ""}
        return {"text": (f"Cererea de probă a fost primită la {_ro(c['requested_at'] or c['created_at'])}. "
                         f"Programul se activează singur imediat ce aprobăm cererea — de obicei în aceeași zi "
                         f"lucrătoare; vă anunțăm pe e-mail."), "check": "", "bar": ""}
    plan = sub["plan"] if sub else "trial"
    what = "Perioada de probă" if plan == "trial" else "Abonamentul"
    d, g = _ro(issue["valid_until"]), _ro(issue["grace_until"])
    cls, tag = STATE_RO.get(st, ("mute", st))
    if st == "active":
        text = f"{what} {'este valabilă' if plan == 'trial' else 'este valabil'} până la <b>{d}</b>."
    elif st == "grace":
        text = (f"{what} a expirat la {d}. Programul funcționează complet până la <b>{g}</b>, apoi trece în "
                f"regim de citire.")
    else:
        text = (f"Din {g} programul este în regim de citire: {esc(mail._READONLY)} După plată programul "
                f"revine singur la lucru complet.")
    text += f" <span class='tag {cls}'>{esc(tag)}</span>"
    if c["renew_at"]:
        behind = (c["renew_seq"] or 0) < issue["seq"]
        check = (f"Programul a verificat licența ultima dată la {esc(c['renew_at'][:16].replace('T', ' '))} UTC"
                 + (" — noul termen ajunge la următoarea verificare (o dată pe zi)." if behind else "."))
    else:
        check = ("Programul instalat nu a verificat încă licența; activat și cu acces la internet, o face o "
                 "dată pe zi.")
    # полоса дней: от выдачи до конца срока; при льготе и чтении — полная, своим цветом
    start, end = _ts(issue["issued_at"]), _ts(issue["valid_until"])
    bar = ""
    if start and end and end > start:
        total = max(1, (end - start).days)
        if st == "active":
            passed = min(total, max(0, (now - start).days))
            left = max(0, -(-(end - now).total_seconds() // 86400))      # дни до конца, вверх
            pct = round(passed / total * 100)
            l_text = "Începută azi" if passed == 0 else f"Au trecut {mail.zile(passed)}"
            r_text = f"Mai sunt {mail.zile(int(left))} — până la {d}"
            bar = (f"<div class='bar'><span style='width:{pct}%'></span></div>"
                   f"<div class='days'><span>{l_text}</span><span>{r_text}</span></div>")
        elif st == "grace":
            bar = (f"<div class='bar warn'><span style='width:100%'></span></div>"
                   f"<div class='days'><span>A expirat la {d}</span><span>Funcționează complet până la {g}</span></div>")
        else:
            bar = (f"<div class='bar bad'><span style='width:100%'></span></div>"
                   f"<div class='days'><span>Regim de citire din {g}</span><span>Revine la lucru după plată</span></div>")
    return {"text": text, "check": check, "bar": bar}


def _cont_payments(c, sub, payments: list) -> str:
    price = sub["price"] if sub else config.PRICE_MONTH
    pending = [p for p in payments if p["status"] == "pending"]
    if pending:
        p = pending[0]
        try:
            ways = f"<pre class='pay'>{esc(mail.ways_to_pay(p['reference'], p['amount'], p['pay_url']))}</pre>"
        except RuntimeError:
            ways = "<p>Datele pentru plată le primiți pe e-mail.</p>"
        top = (f"<p><b>Nota de plată {esc(p['reference'])}</b>: {p['amount']} MDL pentru "
               f"{mail.luni(p['months'])}.</p>{ways}"
               f"<p class='muted'>După confirmarea plății termenul se prelungește automat — programul îl preia "
               f"singur; primiți și confirmarea pe e-mail.</p>")
    elif len(c["idno"] or "") == 13:
        opts = "".join(f"<option value='{m}'>{'o lună' if m == 1 else 'un an (12 luni)'} — "
                       f"{pay.amount(m, price)} MDL</option>" for m in pay.MONTHS)
        method = ""
        if maib.enabled():
            method = ("<div><label>Cum plătiți</label><select name='method'>"
                      "<option value='transfer'>Transfer bancar</option>"
                      "<option value='card'>Cu cardul (link de plată maib)</option></select></div>")
        top = (f"<form method='post' action='/cont/nota'><div class='grid'><div><label>Abonament</label>"
               f"<select name='months'>{opts}</select></div>{method}</div>"
               f"<p><button class='primary'>Comandă nota de plată</button></p></form>"
               f"<p class='muted'>Nota de plată cu referința și datele pentru plată apare aici și vine pe e-mail; "
               f"după confirmarea plății termenul se prelungește, iar programul îl preia singur.</p>")
    else:
        top = (f"<p>Pentru abonament ({price} MDL pe lună sau {pay.amount(12, price)} MDL pe an) completați "
               f"IDNO-ul clinicii în datele de mai jos, apoi comandați nota de plată.</p>")
    rows = "".join(
        f"<tr><td class='mono'>{esc(p['reference'])}</td><td>{p['amount']} MDL</td>"
        f"<td>{esc(mail.luni(p['months']))}</td><td>{_ro(p['created_at'])}</td>"
        f"<td>{_pay_tag_ro(p['status'])}{(' · ' + _ro(p['paid_at'])) if p['paid_at'] else ''}{_card_link_ro(p)}"
        f"</td></tr>" for p in payments)
    table = (f"<table><tr><th>Referința</th><th>Suma</th><th>Termen</th><th>Data</th><th>Stare</th></tr>"
             f"{rows or '<tr><td colspan=5 class=muted>Nu sunt note de plată</td></tr>'}</table>") if payments else ""
    return top + table


def _cont_devices(devices: list, latest: str) -> str:
    """Calculatoare cu DentPilot: версия, Windows, последняя проверка (флот, 02.10).
    Пусто — объяснение, не тишина: компьютер появляется после первой проверки."""
    if not devices:
        return ("<div class='empty'>Niciun calculator nu a verificat încă licența. După activare, programul "
                "o face o dată pe zi — atunci apare aici, cu versiunea și data ultimei verificări.</div>")
    from . import fleet
    rows = "".join(
        f"<li><span class='dot{' old' if (d['version'] and latest and fleet.behind(d['version'], latest)) else ''}'></span>"
        f"<div><div>{esc(d['os'] or 'Windows')} — DentPilot {esc(d['version'] or '?')}"
        f"{' <span class=tag warn>versiune veche</span>' if d['version'] and latest and fleet.behind(d['version'], latest) else ''}"
        f"</div><div class='when'>ultima verificare {esc((d['last_seen_at'] or '')[:16].replace('T', ' '))} UTC</div></div></li>"
        for d in devices)
    return f"<ul class='dev'>{rows}</ul>"


def cont_page(acc, c, sub, issue, payments: list, release, msg: str = "", devices: list = ()) -> str:
    now = datetime.now(timezone.utc)
    st = license.state(_ts(sub["valid_until"]) if sub else None, sub["grace_days"] if sub else 0, now)
    site = config.SITE_URL.rstrip("/")
    lic = _lic_parts(c, sub, issue, st, now)
    ver = f" {esc(release.version)}" if release else ""
    setup = f"DentPilot-Setup{('-' + esc(release.version)) if release else ''}.exe"
    payments = list(payments)
    pending = any(p["status"] == "pending" for p in payments)
    # действие по оплате на панели программы — те же условия, что у формы ноты ниже
    if pending:
        act = "<a class='btn ghost' href='#plati'>Vezi nota de plată</a>"
    elif len(c["idno"] or "") == 13 and issue is not None:
        act = "<a class='btn ghost' href='#plati'>Comandă nota de plată</a>"
    else:
        act = ""
    how = (f"<p class='muted' style='margin:14px 0 0'>La prima pornire programul cere datele clinicii și se "
           f"activează singur; pe un calculator nou al clinicii deja înregistrate cere codul trimis pe e-mail. "
           f"Înainte de instalare citiți <a href='{esc(site)}/descarca.html'>ce cere Legea 195</a>.</p>")
    hero = (f"<div class='card hero'><div class='main'><p class='eyebrow'>Licența</p>"
            f"<p class='lic'>{lic['text']}</p>{lic['bar']}"
            f"{('<p class=' + chr(39) + 'muted' + chr(39) + ' style=' + chr(39) + 'margin:14px 0 0' + chr(39) + '>' + lic['check'] + '</p>') if lic['check'] else ''}"
            f"{how}</div><div class='side'><p class='eyebrow'>Programul</p>"
            f"<div class='big'>DentPilot{ver}</div>"
            f"<p class='small'>Instalator semnat digital — arhivă zip cu {setup}.</p>"
            f"<div class='actions'><a class='btn' href='/descarca'>{_ic('download')} Descarcă DentPilot{ver}</a>{act}</div>"
            f"</div></div>")
    devs = (f"<div class='card'>{_chead('monitor', 'Calculatoare cu DentPilot', 'versiunea programului și ultima verificare a licenței')}"
            f"{_cont_devices(list(devices), release.version if release else '')}</div>")
    if acc["provider"] == "google":
        who = (f"<p style='margin:0 0 6px'>Autentificat cu Google: <b>{esc(acc['email'])}</b>"
               f"{(' (' + esc(acc['name']) + ')') if acc['name'] else ''}.</p>"
               f"<p class='muted' style='margin:0 0 14px'>De la Google avem doar e-mailul, numele și identificatorul "
               f"contului — <a href='{esc(site)}/privacy.html'>Politica de confidențialitate</a>, § 5.</p>")
    else:
        who = (f"<p style='margin:0 0 6px'>Autentificat prin e-mail: <b>{esc(acc['email'])}</b>.</p>"
               f"<p class='muted' style='margin:0 0 14px'>Intrarea se face cu un cod trimis pe acest e-mail; parolă "
               f"nu există — <a href='{esc(site)}/privacy.html'>Politica de confidențialitate</a>, § 5.</p>")
    acct = (f"<div class='card'>{_chead('user', 'Contul')}{who}"
            f"<form method='post' action='/cont/iesire' style='margin-top:auto'><button>Ieșire</button></form></div>")
    price = sub["price"] if sub else config.PRICE_MONTH
    chip = f"<span class='price'>{price} MDL / lună · {pay.amount(12, price)} MDL / an</span>"
    pays = (f"<div class='card' id='plati'>{_chead('card', 'Abonament și plăți', 'un singur abonament pentru toată clinica', chip)}"
            f"{_cont_payments(c, sub, payments)}</div>")
    data = (f"<div class='card'>{_chead('building', 'Datele clinicii', 'apar în nota de plată și în licență')}"
            f"<form method='post' action='/cont/date'><div class='grid'>"
            f"<div><label>Denumirea clinicii *</label><input name='name' value='{esc(c['name'])}' required maxlength='{trial.NAME_MAX}'></div>"
            f"<div><label>IDNO (13 cifre)</label><input name='idno' value='{esc(c['idno'])}' maxlength='13' inputmode='numeric'></div>"
            f"<div><label>Persoana de contact</label><input name='contact_name' value='{esc(c['contact_name'])}' maxlength='{trial.CONTACT_MAX}'></div>"
            f"<div><label>Telefon</label><input name='phone' value='{esc(c['phone'])}' maxlength='{trial.PHONE_MAX}'></div>"
            f"<div><label>Adresa</label><input name='address' value='{esc(c['address'])}' maxlength='200'></div>"
            f"<div><label>E-mail</label><div class='mono' style='padding:8px 0'>{esc(c['email'] or '—')}</div>"
            f"<span class='muted'>pentru schimbare scrieți-ne</span></div></div>"
            f"<p style='margin:16px 0 0'><button class='primary'>Salvează</button></p></form></div>")
    return _cont_shell(c["name"], hero + f"<div class='grid2'>{devs}{acct}</div>" + pays + data, acc, msg)
