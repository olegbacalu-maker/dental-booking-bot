"""Страницы админки: серверная разметка, без React и без шаблонизатора.

Инструмент одного человека (cloud.md › «Админка»): списки, карточка, формы.
Всё, что пришло из базы или формы, проходит через html.escape — здесь и только
здесь строится разметка.
"""
from __future__ import annotations

import html
from datetime import datetime, timedelta, timezone

from . import config, contracts, license, maib, mail, sms, tiers, trial
from . import emailconf  # подтверждение ящика (27.10)
from . import payments as pay  # ⚠️ не `payments`: так зовётся параметр карточки клиники (список строк)

esc = html.escape

MSG = {
    "clinic_ok": ("ok", "Клиника заведена"),
    # клиника в кабинет (26.10): «Добавить клинику в кабинет» в карточке
    "sibling_added": ("ok", "Клиника добавлена в кабинет — пробный выдаётся кнопкой во вкладке «Лицензия» её карточки"),
    "sibling_duplicate": ("err", "IDNO или e-mail чужой клиники (не этого кабинета) — клиника не заведена"),
    "sibling_no_cabinet": ("err", "В кабинет этой клиники ещё никто не входил — добавлять некуда"),
    "need_address": ("err", "Адрес обязателен: по нему клиники кабинета различают в списке"),
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
    "payment_created": ("ok", "Нота выставлена — reference в карточке; ждём перевод"),
    "payment_created_mailed": ("ok", "Нота выставлена, письмо с реквизитами отправлено; ждём перевод"),
    "payment_confirmed": ("ok", "Платёж подтверждён, срок продлён, файл выдан"),
    # вторая ожидающая нота не выставляется (03.10): у бухгалтера клиники был бы выбор из двух номеров
    "note_pending": ("err", "У клиники уже есть ожидающая нота — вторую не выставляем (номер в таблице ниже). "
                            "Переотправить её письмом — кнопка «Письмо»; другая сумма или срок — сначала «Отклонить» ожидающую"),
    "note_pending_mailed": ("ok", "У клиники уже есть ожидающая нота — вторую не выставляем; письмо с ней отправлено ещё раз"),
    "payment_mailed": ("ok", "Письмо с нотой отправлено ещё раз"),
    "payment_confirmed_mailed": ("ok", "Платёж подтверждён, срок продлён, файл выдан и отправлен"),
    "payment_rejected": ("ok", "Платёж отклонён"),
    # повторный платёж по одной ноте (02.10): зачёт следующим периодом, payments.credit_again
    "payment_repeat": ("ok", "Повторный перевод зачтён следующим периодом: новая строка, срок продлён, файл выдан"),
    "payment_repeat_mailed": ("ok", "Повторный перевод зачтён следующим периодом: срок продлён, файл выдан, письмо отправлено"),
    "payment_is_pending": ("err", "Нота ещё ожидает — её закрывает «Подтвердить», а не зачёт повторного перевода"),
    "repeat_unsure": ("err", "Отметьте «перевод пришёл» — зачёт продлевает срок и выдаёт файл"),
    "payment_not_pending": ("err", "Этот платёж уже подтверждён или отклонён — второго продления не будет"),
    "bad_months": ("err", "Срок оплаты — 1, 3, 6 или 12 месяцев"),
    "bad_amount": ("err", "Сумма — целое число лей больше нуля"),
    "no_bank": ("err", "Нота выставлена, но реквизиты (DP_BANK_*) не заполнены — письмо не отправлено"),
    "card_created": ("ok", "Платёж картой создан — ссылка maib в карточке"),
    "card_created_mailed": ("ok", "Платёж картой создан, письмо со ссылкой отправлено"),
    "no_maib": ("err", "Оплата картой не настроена (DP_MAIB_*) — платёж не создан"),
    "maib_failed": ("err", "maib не ответил — ссылки на карту нет, смотрите лог сервера; выставленная нота "
                           "осталась переводом, ссылку к ней — позже кнопкой «Ссылка на карту»"),
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
    # модуль «SMS» (S4)
    "sms_saved": ("ok", "Сохранено"),
    "sms_custom_ro": ("err", "Текст RO не принят: подстановки только {clinica} {ziua} {data} {ora} {telefon} "
                             "(обязательны clinica, data, ora), латиница без диакритики, один сегмент"),
    "sms_custom_ru": ("err", "Текст RU не принят: подстановки только {clinica} {ziua} {data} {ora} {telefon} "
                             "(обязательны clinica, data, ora), один сегмент — 70 знаков с названием клиники"),
    "sms_custom_empty": ("err", "Личный текст включён, а текста нет — впишите хотя бы RO"),
    "sms_credited": ("ok", "Начислено — строка в журнале SMS с причиной"),
    "credit_no_note": ("err", "Начисление без причины не делается — впишите, за что"),
    "credit_amount": ("err", "Начисление: целое число сегментов, не ноль"),
    "credit_reason": ("err", "Начисление: вид — bonus или fix"),
    "cap_bad": ("err", "Потолок — целое число сегментов в сутки от 0 до 100000"),
    "sender_not_requested": ("err", "У клиники нет заявки на имя в этом состоянии"),
    "sender_no_paper": ("err", "Сначала отметка «Заявление получено»: без подписанного заявления имя в sms.md не подаётся"),
    "sender_no_reason": ("err", "Отказ — только с причиной: её увидит клиника"),
    "sms_name": ("err", "Имя: до 11 знаков латиницы, цифр, пробел, точка или тире, хоть одна буква"),
    "sms_name_taken": ("err", "Имя занято: его держит или просит другая клиника, либо это общее DentPilot. "
                              "Регистр, пробел, точка и тире имя не меняют. Заявка не принята"),
    "sms_synced": ("ok", "Имена сверены с sms.md — изменения в журнале"),
    "sms_sync_failed": ("err", "sms.md не ответил на запрос имён — смотрите лог сервера"),
    "sms_test_sent": ("ok", "Тестовая SMS принята sms.md — от общего имени, мимо пакетов клиник"),
    "sms_test_failed": ("err", "sms.md не принял тестовую SMS — причина в журнале"),
    "sms_test_phone": ("err", "Номер — мобильный Молдовы (8 цифр, 6x/7x)"),
    "sms_unconfigured": ("err", "DP_SMSMD_TOKEN пуст — к sms.md не обратиться"),
    "sms_action": ("err", "Неизвестное действие"),
    # варианты абонемента (23.10, tiers.py)
    "tier_set": ("ok", "Вариант изменён — строка в журнале; модуль SMS следует за вариантом сразу"),
    "tier_bad": ("err", "Вариант — DentPilot Basic или DentPilot Plus"),
    "tier_trial": ("err", "Пробный — всегда Plus: вариант клиника выберет при оплате"),
    "tier_no_sub": ("err", "У клиники нет подписки — сперва выдайте файл"),
    "tier_price": ("err", "У варианта нет прайса в cloud.env — он не продаётся"),
    "tier_not_sold": ("err", "У варианта нет цены (DP_PRICE_* в cloud.env) — впишите сумму руками или выберите другой"),
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
.brand .ic{width:34px;display:inline-flex;flex:none;color:#fff}.brand .ic svg{width:34px;height:auto;display:block}
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
.actions input[type=checkbox]{width:auto;padding:0}td.mono{white-space:nowrap}
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
.tabs{display:flex;gap:2px;border-bottom:1px solid var(--line);margin:0 0 18px;overflow-x:auto;overflow-y:hidden}
.tabs a{display:inline-flex;align-items:center;gap:7px;padding:10px 14px;margin-bottom:-1px;border-bottom:2px solid transparent;color:var(--muted);text-decoration:none;font-weight:600;font-size:14px;white-space:nowrap}
.tabs a:hover{color:var(--ink)}.tabs a.on{color:var(--teal-d);border-bottom-color:var(--teal)}
.tabs .n{min-width:20px;height:20px;padding:0 6px;border-radius:999px;background:#FFF3D6;color:#B45309;font-size:12px;display:inline-flex;align-items:center;justify-content:center}
.tabbed:not(.js) .tabs{display:none}.tabbed.js .pane{display:none}.tabbed.js .pane.on{display:block}
.todo{list-style:none;margin:0;padding:0}
.todo li{display:flex;align-items:center;gap:10px 16px;flex-wrap:wrap;padding:10px 0;border-top:1px solid #F3E6C4}
.todo li:first-child{border-top:0;padding-top:2px}.todo .what{flex:1;min-width:260px}
.todo .actions a{font-weight:600;font-size:13.5px;text-decoration:none}
.calm{padding:11px 14px;border-radius:11px;margin:0 0 16px;font-size:14px;background:#ECFDF5;color:#065F46}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:14px;margin:0 0 16px}
a.tile,div.tile{display:flex;flex-direction:column;gap:6px;background:#fff;border:1px solid var(--line);border-radius:16px;padding:16px 18px;box-shadow:var(--shadow);color:var(--ink);text-decoration:none}
a.tile:hover{border-color:var(--teal)}
.tile .k{display:flex;align-items:center;gap:8px;font-size:11.5px;font-weight:600;text-transform:uppercase;letter-spacing:.05em;color:var(--muted)}
.tile .ico{width:26px;height:26px;border-radius:8px;background:var(--teal-soft);color:var(--teal-d);display:inline-flex;align-items:center;justify-content:center}
.tile .big{font-size:19px;font-weight:700;letter-spacing:-.01em;line-height:1.25;overflow-wrap:anywhere}
.tile .s{font-size:13px;color:var(--muted);line-height:1.5}
.tabs .c{color:var(--muted);font-weight:500}
.acts{display:flex;gap:8px;align-items:flex-start;flex-wrap:wrap;margin:0 0 16px}
.acts>form{margin:0}
details.drop{display:block}details.drop[open]{flex-basis:100%}
details.drop>summary{display:inline-flex;align-items:center;gap:8px;margin:0;padding:9px 16px;border:1px solid #D8E2DF;border-radius:9px;background:#fff;color:var(--ink);font-size:14px;font-weight:600;white-space:nowrap}
details.drop>summary:before{content:none}
details.drop>summary:after{content:'';border:4px solid transparent;border-top-color:currentColor;margin-top:4px}
details.drop.p>summary{background:var(--teal);border-color:var(--teal);color:#fff}
details.drop>summary:hover{border-color:var(--teal)}details.drop.p>summary:hover{background:var(--teal-d)}
.drop .open{margin:10px 0 0;padding:14px 16px;border:1px dashed var(--teal);background:var(--teal-soft);border-radius:12px}
.drop .open .muted{margin:0 0 6px}
.chips{display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin:0 0 14px}
.chips a{padding:5px 12px;border-radius:999px;border:1px solid #D8E2DF;background:#fff;font-size:13px;font-weight:600;color:var(--muted);text-decoration:none;white-space:nowrap}
.chips a:hover{border-color:var(--teal);color:var(--teal-d)}.chips a.on{background:var(--teal);border-color:var(--teal);color:#fff}
.flow{display:flex;align-items:center;flex-wrap:wrap;gap:8px 0;margin:2px 0 14px;padding:0;list-style:none}
.flow li{display:flex;align-items:center;gap:7px;font-weight:600;font-size:13.5px;color:var(--muted)}
.flow li+li:before{content:'';width:28px;height:2px;background:#D5E0DD;margin:0 10px}
.flow i{width:16px;height:16px;border-radius:50%;border:2px solid #C9D6D2;flex:none}
.flow .done{color:var(--teal-d)}.flow .done i{background:var(--teal);border-color:var(--teal)}
.flow .cur{color:#B45309}.flow .cur i{border-color:#E0A33B;background:#FFF3D6}
table.set td{vertical-align:middle}table.set td:first-child{font-weight:600;width:24%;white-space:nowrap}
table.set .actions{gap:8px}
.tot{margin:0 0 12px}
.login{max-width:400px;margin:40px auto 0}
.login .mark{width:46px;height:46px;display:inline-flex;margin-bottom:12px}.login .mark svg{display:block}
.login h1{font-size:22px;margin:0 0 4px}
@media (max-width:760px){.top-in{padding:8px 14px;height:auto;flex-wrap:wrap}.top form{margin-left:auto}.wrap{padding:18px 14px 48px}.card{padding:14px;border-radius:14px}.nav a{padding:6px 9px}.chead .right{margin-left:0;flex-basis:100%}}
"""


def page(title: str, body: str, user: str | None = None, msg: str = "", pending: int = 0,
         active: str = "", lead: str = "", plain: bool = False, names: int = 0) -> str:
    """Каркас админки: тёмная шапка с разделами (активный подсвечен), выход;
    заголовок с подписью; баннер сообщения; тело. Без входа — только бренд.
    `names` — имена отправителей, ждущие подачи: счётчик у раздела «SMS»."""
    banner = ""
    if msg in MSG:
        cls, text = MSG[msg]
        banner = f"<div class='banner {cls}'>{esc(text)}</div>"
    pend = f" ({pending})" if pending else ""
    nm = f" ({names})" if names else ""

    def item(href: str, text: str, key: str) -> str:
        # ⚠️ порядок атрибутов: class, потом href — тест ищет «href='/admin/fleet'>Флот</a>»
        return f"<a class='on' href='{href}'>{text}</a>" if active == key else f"<a href='{href}'>{text}</a>"

    nav = (f"<div class='top'><div class='top-in'><a class='brand' href='/admin'><span class='ic'>{_mark(_MARK_WHITE, 'dpab')}</span>"
           f"DentPilot Cloud <span class='sub'>· админка</span></a>"
           + ((f"<nav class='nav'>{item('/admin', 'Клиники', 'clinics')}"
               f"{item('/admin/payments', 'Платежи' + pend, 'payments')}{item('/admin/fleet', 'Флот', 'fleet')}"
               f"{item('/admin/sms', 'SMS' + nm, 'sms')}"
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
    body = (f"<div class='card login'><span class='mark'>{_mark(_MARK_ICON, 'dpal')}</span>"
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
             "cont": ("кабинет", "заявка из кабинета"),
             "cont_add": ("кабинет +", "клиника, добавленная в кабинете")}


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


def _email_tag(c) -> str:
    """Метка «e-mail neconfirmat» (27.10, emailconf.py) — в списке клиник и в карточке. Нет ящика —
    метки нет: об этом своя строка «Ждёт вас»."""
    if not c["email"] or c["email_confirmed_at"]:
        return ""
    return " <span class='tag warn' title='ящик не подтверждён ни ссылкой, ни кодом, ни входом в кабинет'>e-mail neconfirmat</span>"


def clinics_page(rows: list, user: str, msg: str = "", requests: list = (), state: str = "",
                 pending: int = 0, names: int = 0) -> str:
    """Клиники (17.10 — вкладки): «Клиники» со счётчиками-фильтрами состояний и «+ Новая клиника»
    за кнопкой; «Заявки на пробный» со счётчиком «ждёт»."""
    now = datetime.now(timezone.utc)
    requests = list(requests)
    states = {r["id"]: license.state(_ts(r["valid_until"]), r["grace_days"] or 0, now) for r in rows}
    counts = {k: 0 for k in STATE_RU}
    for st in states.values():
        counts[st] += 1
    state = state if state in STATE_RU else ""
    shown = [r for r in rows if not state or states[r["id"]] == state]
    trs = "".join(
        f"<tr><td><a href='/admin/clinics/{esc(r['id'])}'>{esc(r['name'])}</a>{_email_tag(r)}</td>"
        f"<td class='mono'>{esc(r['idno'] or '—')}</td><td>{esc(r['plan'] or '—')}</td>"
        f"<td>{_d(r['valid_until'])}</td><td>{_tag(states[r['id']])}</td>"
        f"<td>{r['seq'] or 0}{_renew_short(r)}</td></tr>"
        for r in shown) or (f"<tr><td colspan='6' class='muted'>{'Пока ни одной клиники' if not rows else 'Клиник в этом состоянии нет'}</td></tr>")
    chips = _chips([("", f"Все {len(rows)}", "/admin")]
                   + [(k, f"{STATE_RU[k][1]} {n}", f"/admin?state={k}") for k, n in counts.items()], state)
    chips = chips.replace("<div class='chips'>", "<div class='chips'><span class='muted'>Состояния:</span>", 1)
    daily = ("<form method='post' action='/admin/jobs/daily' style='margin:0'>"
             "<button title='Напоминания по таблице cloud.md за сегодня; cron делает то же раз в сутки'>"
             "Запустить ежедневную задачу</button></form>")
    form = ("<p class='muted'>Заводится вручную — файл выдаётся из карточки клиники.</p>"
            "<form method='post' action='/admin/clinics'>"
            "<div class='grid'><div><label>Название *</label><input name='name' required maxlength='120'></div>"
            "<div><label>IDNO (13 цифр)</label><input name='idno' maxlength='13' pattern='[0-9]{13}'></div>"
            "<div><label>Контактное лицо</label><input name='contact_name'></div>"
            "<div><label>E-mail</label><input name='email' type='email'></div>"
            "<div><label>Телефон</label><input name='phone'></div>"
            "<div><label>Адрес</label><input name='address'></div></div>"
            "<p style='margin:14px 0 0'><button class='primary'>Завести</button></p></form>")
    table = (f"<div class='acts'>{_drop('+ Новая клиника', form, primary=True)}</div>{chips}"
             f"<div class='card'>{_chead('list', f'Все клиники ({len(rows)})', 'нажмите на состояние выше, чтобы оставить только такие', daily)}"
             "<table><tr><th>Клиника</th><th>IDNO</th><th>Тариф</th>"
             f"<th>Срок до</th><th>Состояние</th><th>Файлов</th></tr>{trs}</table></div>")
    reqs = _requests_block(requests) or "<div class='calm'>Новых заявок на пробный период нет</div>"
    body = _tabbed([("list", f"Клиники <span class='c'>{len(rows)}</span>", table, 0),
                    ("requests", "Заявки на пробный", reqs, len(requests))])
    return page("Клиники", body, user, msg, pending=pending, active="clinics", names=names,
                lead="Клиники, их файлы лицензии и заявки на пробный период.")


# ---------- форма пробного периода (L14): публичные страницы, по-румынски ----------

TRIAL_MSG = {
    "bad_terms": "Versiunea termenilor lipsește sau nu este o dată (zz.ll.aaaa).",
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
    # Подтверждение ящика из программы (27.10, emailconf.py)
    "email_bad_code": "Codul nu este corect sau a expirat — verificați e-mailul sau apăsați „Retrimite” "
                      "pentru un cod nou.",
    "email_limited": "Am trimis deja mai multe e-mailuri în ultima oră — verificați și dosarul Spam sau "
                     "încercați peste o oră.",
    "email_locked": "Adresa de e-mail a clinicii este deja confirmată: o schimbați din contul clinicii "
                    "sau scriindu-ne.",
    "email_same": "Aceasta este deja adresa clinicii — apăsați „Retrimite” pentru un cod nou.",
    "email_taken": "Adresa aparține altei clinici înregistrate la DentPilot — indicați adresa clinicii "
                   "dvs. sau scrieți-ne.",
    "email_mail_failed": "E-mailul nu a putut fi trimis acum — încercați mai târziu sau scrieți-ne.",
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
             f"date și codul pe care îl trimitem pe acest e-mail — așa se activează programul. "
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
                       f"prima pornire introduceți aceleași date, iar programul se activează cu codul pe care "
                       f"îl trimitem pe e-mailul clinicii. Dacă nu "
                       f"găsiți e-mailul în câteva minute, verificați dosarul Spam sau scrieți-ne.")
    else:
        title, text = ("Cererea a fost primită", f"Vă răspundem la {email} în cel mult o zi lucrătoare — "
                       f"cu confirmarea perioadei de probă de {mail.zile(license.TRIAL_DAYS)} și pașii de "
                       f"instalare.")
    return _public(title, f"<div class='card'><h1>{esc(title)}</h1><p>{esc(text)}</p></div>")


# ---------- подтверждение ящика клиники (27.10, emailconf.py): публичная страница ссылки ----------

CONFIRM_STATES = {
    "ask": ("Confirmați adresa de e-mail", ""),
    "done": ("Adresa de e-mail este confirmată",
             "Mulțumim. Pe această adresă vin codurile pentru un calculator nou, intrarea în contul clinicii și "
             "notele de plată. Programul afișează confirmarea în cel mult o zi; pe pagina Setări › Licența "
             "o vedeți imediat după „Verifică acum”."),
    "already": ("Adresa este deja confirmată", "Nu mai trebuie făcut nimic. Puteți închide această filă."),
    "dead": ("Linkul nu mai este valabil",
             "Linkul a expirat, a fost deja folosit sau adresa clinicii s-a schimbat între timp. Cereți un "
             "link nou din program: Setări › Licența › „Retrimite”."),
}


def confirm_page(state: str, clinic: str = "", email: str = "", token: str = "") -> str:
    """`ask` — кнопка POST (GET ничего не пишет: почтовые сканеры открывают ссылки сами);
    остальные — итог словами. Ключ ссылки — только в action формы."""
    title, text = CONFIRM_STATES.get(state, CONFIRM_STATES["dead"])
    if state == "ask":
        inner = (f"<div class='card'><h1>{esc(title)}</h1>"
                 f"<p>Confirmați că <b>{esc(email)}</b> este adresa de e-mail a clinicii <b>{esc(clinic)}</b> "
                 f"la DentPilot.</p><p>{esc(mail.CONFIRM_WHY)}</p>"
                 f"<form method='post' action='{emailconf.PAGE}/{esc(token)}'>"
                 f"<button class='primary'>Confirmă adresa</button></form></div>")
    else:
        inner = f"<div class='card'><h1>{esc(title)}</h1><p>{esc(text)}</p></div>"
    return _public(title, inner)


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


def _term(p) -> str:
    """Предмет ноты: срок абонемента, пакет SMS или год имени (payments.kind, S3)."""
    kind = p["kind"] if "kind" in p.keys() else "license"
    if kind == "sms":
        return f"SMS ×{p['sms_units']}"
    if kind == "sms_name":
        return "имя SMS, год"
    if kind == "cabinet":
        return "абонементы клиник кабинета (общая нота)"
    tier = p["tier"] if "tier" in p.keys() else None
    return f"{p['months']} мес.{(' · ' + tiers.NAME[tier].split()[-1]) if tier in tiers.TIERS else ''}"


def _receipt_link(p) -> str:
    """Cont de plată оплаченного платежа (17.10): ссылка в новое окно; у неоплаченного ничего."""
    if p["status"] != "paid":
        return ""
    return (f" · <a href='/admin/payments/{p['id']}/cont.pdf' target='_blank' rel='noopener' "
            f"title='Cont de plată с отметкой achitat — то, что ушло клинике вложением'>cont PDF</a>")


def _payment_rows(rows: list, with_clinic: bool = False) -> str:
    out = []
    for p in rows:
        actions = ""
        if p["status"] == "pending":
            actions = (f"<form method='post' action='/admin/payments/{p['id']}/confirm'>"
                       f"<button class='primary'>Подтвердить</button></form>"
                       f"<form method='post' action='/admin/payments/{p['id']}/mail'>"
                       f"<button title='Письмо с нотой и реквизитами ещё раз — та же нота, тот же reference'>Письмо</button></form>")
            if p["provider_id"]:
                actions += (f"<form method='post' action='/admin/payments/{p['id']}/check'>"
                            f"<button title='Спросить maib о статусе'>Проверить</button></form>")
            if maib.enabled():
                actions += (f"<form method='post' action='/admin/payments/{p['id']}/link'>"
                            f"<button title='Ссылка на оплату картой к этому же reference'>"
                            f"{'Новая ссылка' if p['provider_id'] else 'Ссылка на карту'}</button></form>")
            # отказ — с причиной, за кнопкой и последним: раскрывшись, он не сдвигает соседние кнопки
            actions += _drop("Отклонить", f"<form method='post' action='/admin/payments/{p['id']}/reject' class='actions'>"
                                          f"<input name='reason' placeholder='причина'>"
                                          f"<button>Отклонить ноту</button></form>")
            actions = f"<div class='actions'>{actions}</div>"
        elif p["status"] in ("paid", "rejected"):
            # второй платёж по этой же ноте (02.10): не теряем — следующий период
            # редкое действие — за кнопкой (17.10): строка истории не держит открытую форму
            actions = _drop("Пришёл ещё перевод",
                            f"<p class='muted'>По этой ноте пришёл ещё один перевод: зачесть его следующим периодом, "
                            f"с новым reference, файлом и письмом.</p>"
                            f"<form method='post' action='/admin/payments/{p['id']}/repeat' class='actions'>"
                            f"<label class='chk' style='margin:0'><input type='checkbox' name='sure' value='1' required> "
                            f"перевод пришёл</label> <button>Зачесть повторный перевод</button></form>")
        clinic_td = (f"<td><a href='/admin/clinics/{esc(p['clinic_id'])}'>{esc(p['clinic'])}</a></td>"
                     if with_clinic else "")
        out.append(f"<tr><td class='mono'>{esc(p['reference'])}</td>{clinic_td}"
                   f"<td>{p['amount']} {esc(p['currency'])}</td><td>{_term(p)}</td>"
                   f"<td>{esc(p['created_at'][:10])}</td><td>{_pay_tag(p['status'])}"
                   f"{(' · ' + esc(p['paid_at'][:10])) if p['paid_at'] else ''}"
                   f"{(' · ' + esc(p['confirmed_by'])) if p['confirmed_by'] and p['status'] == 'paid' else ''}"
                   f"{(' · ' + ('картой' if p['paid_via'] == 'card' else 'переводом')) if p['status'] == 'paid' and p['paid_via'] else ''}"
                   f"{_receipt_link(p)}{_card_cell(p)}</td><td>{actions}</td></tr>")
    return "".join(out)


def pay_page(ok: bool, p=None) -> str:
    """Куда maib возвращает браузер клиники (L12). Редирект — не истина о платеже:
    «plătită» — только когда сервер уже закрыл ноту по ответу maib (settle), иначе «în
    curs de confirmare». `p` — платёж по payId из адреса (main._returned): № заказа, что
    оплачивается, сумма, дата, поставщик и сайт — требование maib к странице возврата;
    без него (адрес без payId, чужой) — общий текст без подробностей."""
    if ok:
        title, sub, text = ("Mulțumim!", "plata a fost transmisă către bancă",
                            "Banca ne confirmă plata de obicei în câteva minute. După confirmare termenul se "
                            "prelungește automat, programul DentPilot îl preia singur când are acces la internet, "
                            "iar confirmarea și contul de plată (PDF) vin pe e-mailul clinicii.")
    else:
        title, sub, text = ("Plata nu a reușit", "banca nu a confirmat plata",
                            "Banca nu a confirmat plata, banii nu au fost retrași. Puteți încerca din nou din program "
                            "(„Plătește acum”) sau din e-mailul cu nota de plată, ori plăti prin transfer bancar cu "
                            "referința din aceeași notă.")
    details = ""
    if p is not None:
        paid = p["status"] == "paid"
        when = _ro(p["paid_at"]) if paid else sms.local(datetime.now(timezone.utc)).strftime("%d.%m.%Y")
        state = ("<span class='tag ok'>plătită — confirmată de bancă</span>" if paid
                 else "<span class='tag warn'>în curs de confirmare</span>" if ok
                 else "<span class='tag bad'>neplătită</span>")
        seller = ", ".join(x for x in (config.BANK["beneficiary"], "antreprenor independent") if x)
        what = pay.subject(p)
        details = (f"<dl class='ok-list'><dt>Comanda nr.</dt><dd class='mono'>{esc(p['reference'])}</dd>"
                   f"<dt>Ce plătiți</dt><dd>{esc(what[:1].upper() + what[1:])}</dd>"
                   f"<dt>Suma</dt><dd>{_mdl(p['amount'])} {esc(p['currency'] or 'MDL')}</dd>"
                   f"<dt>Data</dt><dd>{when}</dd><dt>Starea</dt><dd>{state}</dd>"
                   f"<dt>Furnizor</dt><dd class='plain'>{esc(seller)} · "
                   f"{esc(config.SITE_URL.rstrip('/').split('//', 1)[-1])}</dd></dl>"
                   f"<p class='muted' style='margin:0'>Păstrați numărul comenzii: după el găsim plata la orice "
                   f"întrebare.</p>")
        if paid and ok:
            text = ("Plata a fost confirmată de bancă: termenul se prelungește automat, programul DentPilot îl "
                    "preia singur când are acces la internet, iar confirmarea și contul de plată (PDF) vin pe "
                    "e-mailul clinicii.")
    inner = (f"<div class='card narrow'>{_chead('shield' if ok else 'clock', esc(title), esc(sub))}"
             f"<p style='margin:0'>{esc(text)}</p>{details}</div>")
    return _cont_shell("Plata cu cardul", inner, eyebrow="DentPilot · plata online")


_MONTHS_RU = ("январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь",
              "октябрь", "ноябрь", "декабрь")
_MONTHS_IN = ("январе", "феврале", "марте", "апреле", "мае", "июне", "июле", "августе", "сентябре",
              "октябре", "ноябре", "декабре")


def _month_ru(ym: str, where: bool = False) -> str:
    """'2026-10' → «Октябрь 2026», с where — «октябре 2026» (после «в»)."""
    y, m = ym.split("-")
    return f"{_MONTHS_IN[int(m) - 1]} {y}" if where else f"{_MONTHS_RU[int(m) - 1].capitalize()} {y}"


def _plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return one
    return few if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else many


def payments_page(rows: list, user: str, msg: str = "", paid: list = (), month: str = "", months: list = (),
                  rejected: list = (), names: int = 0) -> str:
    """Платежи (17.10 — вкладки): «Ждут подтверждения» — сверить с выпиской и подтвердить;
    «Оплачены» — по месяцам с суммой (учёт доходов); «Отклонены» — с причиной из журнала."""
    rows, paid, rejected = list(rows), list(paid), list(rejected)
    trs = _payment_rows(rows, with_clinic=True) or "<tr><td colspan='7' class='muted'>Ожидающих платежей нет</td></tr>"
    wait = (f"<div class='card'>{_chead('card', f'В ожидании: {len(rows)}', 'подтверждение продлевает срок и выдаёт файл; письмо клинике уходит само')}"
            f"<table><tr><th>Reference</th><th>Клиника</th><th>Сумма</th><th>Срок</th>"
            f"<th>Создан</th><th>Состояние</th><th></th></tr>{trs}</table></div>")
    sums: dict[str, int] = {}
    for p in paid:
        sums[p["currency"]] = sums.get(p["currency"], 0) + p["amount"]
    total = " + ".join(f"{v} {esc(k)}" for k, v in sums.items()) or "0 MDL"
    prows = "".join(
        f"<tr><td class='mono'>{esc(p['reference'])}</td>"
        f"<td><a href='/admin/clinics/{esc(p['clinic_id'])}'>{esc(p['clinic'])}</a></td>"
        f"<td>{_term(p)}</td><td>{p['amount']} {esc(p['currency'])}</td><td>{_d(p['paid_at'])}</td>"
        f"<td>{'картой' if p['paid_via'] == 'card' else 'переводом'}</td>"
        f"<td>{_receipt_link(p).removeprefix(' · ')}</td></tr>" for p in paid)
    paid_html = ""
    if month:
        chips = _chips([(m, _month_ru(m), f"/admin/payments?month={m}#paid") for m in months], month)
        paid_html = (f"{chips}<p class='tot'>Пришло в {_month_ru(month, where=True)}: <b>{total}</b> · "
                     f"{len(paid)} {_plural(len(paid), 'платёж', 'платежа', 'платежей')}</p>"
                     f"<div class='card'><table><tr><th>Reference</th><th>Клиника</th><th>За что</th><th>Сумма</th>"
                     f"<th>Оплачено</th><th>Как</th><th>Документ</th></tr>"
                     f"{prows or '<tr><td colspan=7 class=muted>В этом месяце оплат не было</td></tr>'}</table></div>")
    rrows = "".join(
        f"<tr><td class='mono'>{esc(p['reference'])}</td>"
        f"<td><a href='/admin/clinics/{esc(p['clinic_id'])}'>{esc(p['clinic'])}</a></td>"
        f"<td>{_term(p)}</td><td>{p['amount']} {esc(p['currency'])}</td><td>{_d(p['created_at'])}</td>"
        f"<td>{esc((p['why'] or '').split(': ', 1)[-1] or '—')}</td></tr>" for p in rejected)
    rej_html = (f"<div class='card'><table><tr><th>Reference</th><th>Клиника</th><th>За что</th><th>Сумма</th>"
                f"<th>Выставлена</th><th>Причина</th></tr>"
                f"{rrows or '<tr><td colspan=6 class=muted>Отклонённых нот нет</td></tr>'}</table></div>")
    body = _tabbed([("wait", "Ждут подтверждения", wait, len(rows)), ("paid", "Оплачены", paid_html, 0),
                    ("rejected", f"Отклонены <span class='c'>{len(rejected)}</span>", rej_html, 0)])
    return page("Платежи", body, user, msg, pending=len(rows), active="payments", names=names,
                lead="Ноты, которые ждут перевода, и всё, что уже оплачено.")


def _reminder_rows(rows: list) -> str:
    return "".join(f"<tr><td>{esc(KIND_RU.get(r['kind'], r['kind']))}</td><td>{_d(r['period'])}</td>"
                   f"<td>{esc(r['sent_at'][:16].replace('T', ' '))}</td></tr>" for r in rows)


def audit_page(rows: list, user: str, msg: str = "", pending: int = 0, kind: str = "",
               by_what: dict | None = None, names: int = 0) -> str:
    """Журнал (17.10): события словами, фильтры по разделам (?kind=pay) с числами по всему журналу."""
    out = []
    for a in rows:
        who = (f"<a href='/admin/clinics/{esc(a['clinic_id'])}'>{esc(a['clinic'] or a['clinic_id'])}</a>"
               if a["clinic_id"] else "—")
        out.append(f"<tr><td class='mono'>{esc(a['at'][:16].replace('T', ' '))}</td><td>{esc(a['who'])}</td>"
                   f"<td>{_what(a['what'])}</td><td style='min-width:150px'>{who}</td><td>{esc(a['detail'])}</td></tr>")
    trs = "".join(out)
    chips = _journal_chips(by_what or {}, kind, lambda k: f"/admin/audit?kind={k}" if k else "/admin/audit")
    body = (f"{chips}<div class='card'>{_chead('clock', 'Последние события', 'кто что сделал — выдачи, платежи, входы, коды; последние 200')}"
            f"<table><tr><th>Когда (UTC)</th><th>Кто</th><th>Что</th><th>Клиника</th>"
            f"<th>Подробности</th></tr>{trs or '<tr><td colspan=5 class=muted>пусто</td></tr>'}</table></div>")
    return page("Журнал", body, user, msg, pending=pending, active="audit", names=names)


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


def _multi_tag(n: int) -> str:
    """Подсказка флота (26.10): у клиники больше одного активного компьютера за 30 дней."""
    if n < 2:
        return ""
    return (f" <span class='tag warn' title='возможно, второй пункт на одной лицензии: у одного места работы "
            f"обычно один компьютер с программой, остальные ходят к нему по сети'>{n} активных за 30 дн.</span>")


def fleet_page(rep: dict, user: str, msg: str = "", pending: int = 0, names: int = 0) -> str:
    """Флот (02.10; 17.10 — вкладки): все компьютеры, кто отстал от выпуска, кто молчит неделю."""
    c = rep["counts"]
    latest = rep["latest"]
    head = (f"<p style='margin:0 0 4px'>Последний выпуск: <b>{esc(latest) or 'API GitHub не ответил'}</b>"
            f" · компьютеров {c['devices']} у {c['clinics']} клиник · отстают {c['behind']}"
            f" · молчат дольше недели {c['silent']}"
            f" · клиник с 2+ активными за 30 дн.: {c.get('multi_clinics', 0)}</p>"
            f"<p class='muted' style='margin:0 0 16px'>Программа называет себя при каждом запросе файла (раз в сутки) "
            f"и при активации; сервер только слушает. JSON того же: <a href='/admin/api/fleet'>/admin/api/fleet</a>.</p>")

    def table(devices: list, empty: str) -> str:
        rows = []
        for d in devices:
            tags = (" <span class='tag warn'>отстаёт</span>" if d["behind"] else "") + \
                   (" <span class='tag bad'>молчит</span>" if d["silent"] else "")
            rows.append(f"<tr><td><a href='/admin/clinics/{esc(d['clinic_id'])}'>{esc(d['clinic'])}</a> {_tag(d['state'])}"
                        f"{_multi_tag(d.get('clinic_active', 0))}</td>"
                        f"<td class='mono'>{esc(d['device'])}</td><td>{esc(d['version'] or '—')}{tags}</td>"
                        f"<td>{esc(d['channel'] or '—')}</td><td>{esc(d['os'] or '—')}</td>"
                        f"<td>{esc((d['last_seen_at'] or '')[:16].replace('T', ' '))}"
                        f"{(' <span class=muted>(' + str(d['silent_days']) + ' дн.)</span>') if d['silent_days'] else ''}</td>"
                        f"<td>{d['last_seq'] if d['last_seq'] is not None else '—'}</td></tr>")
        return (f"<div class='card'><table><tr><th>Клиника</th><th>Компьютер</th><th>Версия</th><th>Канал</th>"
                f"<th>Windows</th><th>Последняя связь (UTC)</th><th>Файл у программы</th></tr>"
                f"{''.join(rows) or '<tr><td colspan=7 class=muted>' + empty + '</td></tr>'}</table></div>")
    devs = rep["devices"]
    behind = [d for d in devs if d["behind"]]
    silent = [d for d in devs if d["silent"]]
    multi = [d for d in devs if d.get("multi")]
    why = ("<p class='muted' style='margin:0 0 12px'>У одного места работы обычно один компьютер с программой — "
           "остальные ходят к нему по сети. Два и больше активных за 30 дней у одной клиники — повод спросить, "
           "не второй ли это пункт на одной лицензии (филиал — своя клиника в кабинете). Только подсказка: "
           "ничего не запрещается.</p>")
    body = head + _tabbed([
        ("all", f"Все компьютеры <span class='c'>{len(devs)}</span>",
         table(devs, "Ни один компьютер ещё не выходил на связь"), 0),
        ("behind", "Отстают от выпуска", table(behind, "Все на последнем выпуске"), len(behind)),
        ("silent", "Молчат больше недели", table(silent, "Все выходили на связь за последнюю неделю"), len(silent)),
        ("multi", "Несколько компьютеров", why + table(multi, "Ни у одной клиники нет двух активных компьютеров"),
         rep["counts"].get("multi_clinics", 0))])
    return page("Флот", body, user, msg, pending=pending, active="fleet", names=names,
                lead="Кто на какой версии и когда программа выходила на связь в последний раз.")


SENDER_RU = {"none": ("mute", "имени нет"), "requested": ("warn", "заявка"), "submitted": ("warn", "подано в sms.md"),
             "active": ("ok", "одобрено"), "rejected": ("bad", "отказ")}
SMS_STATE_RU = {"delivered": "доставлено", "undelivered": "не доставлено", "failed": "отказ оператора (10)",
                "rejected": "отказ оператора (11)", "refused": "отказ sms.md", "retry": "sms.md: не сейчас",
                "unanswered": "sms.md не ответил", "queued": "в очереди", "sent": "у оператора", "unknown": "неизвестно"}
LEDGER_RU = {"pack": "пакет", "send": "отправка", "refund": "возврат", "bonus": "бонус", "fix": "правка", "expire": "сгорело"}


def _sender_tag(state: str) -> str:
    cls, text = SENDER_RU.get(state, ("mute", state))
    return f"<span class='tag {cls}'>{esc(text)}</span>"


def _period_links(rep: dict) -> str:
    """Период — кнопки одного вида: сегодня / 7 дней / месяц; свой — за кнопкой (форма GET)."""
    p = rep["period"]
    form = (f"<form method='get' action='/admin/sms' class='actions'>"
            f"<input type='hidden' name='period' value='custom'>"
            f"<input type='date' name='from' value='{esc(p['from'])}' style='width:160px'>"
            f"<input type='date' name='to' value='{esc(p['to'])}' style='width:160px'>"
            f"<button>Показать</button></form>")
    chips = _chips([(k, t, f"/admin/sms?period={k}") for k, t in
                    (("today", "Сегодня"), ("week", "7 дней"), ("month", "Месяц"))], p["kind"])
    return chips[:-len("</div>")] + _drop("Свой период", form, primary=p["kind"] == "custom") + "</div>"


def _sender_actions(i: dict) -> str:
    """Шаги Олега по имени (очередь раздела SMS): заявление → подано → отказ."""
    cid = esc(i["clinic_id"])
    out = []
    if i.get("sender_paper_file"):
        out.append(f"<a class='btn' href='/admin/clinics/{cid}/sms/cerere.pdf' "
                   f"title='Подписанное заявление, загруженное клиникой в кабинете'>Заявление клиники (PDF)</a>")
    if i["sender_state"] == "requested":
        if not i["sender_paper"]:
            out.append(f"<form method='post' action='/admin/clinics/{cid}/sms'><input type='hidden' name='action' value='paper'>"
                       f"<button title='Подписанное заявление клиники у меня'>Заявление получено</button></form>")
        else:
            out.append(f"<form method='post' action='/admin/clinics/{cid}/sms'><input type='hidden' name='action' value='submitted'>"
                       f"<button class='primary' title='Имя подано в кабинете sms.md'>Подано в sms.md</button></form>")
    if i["sender_state"] in ("requested", "submitted", "active"):
        out.append(_drop("Отказ", f"<form method='post' action='/admin/clinics/{cid}/sms' class='actions'>"
                                  f"<input type='hidden' name='action' value='rejected'>"
                                  f"<input name='note' placeholder='причина отказа' required><button>Записать отказ</button></form>"))
    return f"<div class='actions'>{''.join(out)}</div>" if out else ""


def sms_page(rep: dict, user: str, msg: str = "", pending: int = 0) -> str:
    """Модуль «SMS» (S4; 17.10 — вкладки): сводка за период, имена на подачу, сбои,
    выгрузка и тестовая SMS."""
    t, c = rep["totals"], rep["counts"]
    p = rep["period"]
    bal = (f"<b>{esc(rep['smsmd_balance'])} MDL</b>" if rep["smsmd_balance"] is not None else
           ("<span class='tag bad'>баланс не получен</span>" if rep["configured"] else "<span class='tag mute'>DP_SMSMD_TOKEN пуст</span>"))
    offered = ("всем клиникам (DP_SMS_OFFERED=1)" if rep["offered_all"] else
               f"только пилотам ({sum(1 for i in rep['clinics'] if i['pilot'])}) — DP_SMS_OFFERED пуст")
    tiles = ("<div class='tiles'>"
             + _stat("Отправлено", str(t["sent"]),
                     f"доставлено {t['delivered']} · не доставлено {t['undelivered']} · отказ {t['refused']} · в пути {t['pending']}")
             + _stat("Потрачено", f"<b>{t['spent']}</b> сегм.", f"куплено {t['packs']} пакетов на {t['pack_units']} SMS")
             + _stat("Должны клиникам", f"<b>{rep['owed']}</b> сегм.",
                     f"продано и не потрачено ≈ {esc(rep['owed_mdl'])} MDL по {esc(rep['segment_cost'])}")
             + _stat("Баланс sms.md", bal, "сколько у нас осталось в sms.md")
             + "</div>")
    rows = []
    for i in rep["clinics"]:
        flags = ("" if i["enabled"] else " <span class='tag bad'>выкл.</span>") + \
                (" <span class='tag ok'>пилот</span>" if i["pilot"] and not rep["offered_all"] else "")
        rows.append(f"<tr><td><a href='/admin/clinics/{esc(i['clinic_id'])}'>{esc(i['clinic'])}</a> {_tag(i['state'])}{flags}</td>"
                    f"<td>{esc(i['from'] or '—')}{(' ' + _sender_tag(i['sender_state'])) if i['sender'] else ''}</td>"
                    f"<td><b>{i['balance']}</b></td><td>{i['sent']}</td><td>{i['delivered']}</td>"
                    f"<td>{i['undelivered'] + i['refused']}</td><td>{i['spent']}</td>"
                    f"<td>{i['used_today']} / {i['daily_cap']}</td></tr>")
    total = (f"<tr><td><b>Итого</b></td><td></td><td><b>{t['balance']}</b></td><td><b>{t['sent']}</b></td><td>{t['delivered']}</td>"
             f"<td>{t['undelivered'] + t['refused']}</td><td><b>{t['spent']}</b></td><td></td></tr>") if rows else ""
    period = f"период {esc(p['from'])} — {esc(p['to'])}, сутки по Кишинёву; сортировка по расходу; пакеты, «в пути» и последняя отправка — в Excel"
    table = (f"<div class='card'>{_chead('message', 'По клиникам', period)}"
             f"<table><tr><th>Клиника</th><th>От имени</th><th>Остаток</th><th>Отправлено</th>"
             f"<th>Доставлено</th><th>Сбои</th><th>Потрачено, сегм.</th><th>Сегодня / потолок</th></tr>"
             f"{''.join(rows) or '<tr><td colspan=8 class=muted>Ни одна клиника ещё не спрашивала про SMS</td></tr>'}{total}</table></div>")
    note = (f"<p class='muted' style='margin:0'>Счетов {c['clinics']}, включено {c['enabled']}; пакет предложен {esc(offered)}. "
            f"Номеров пациентов и текстов SMS на сервере нет — видно, сколько, а не кому. "
            f"JSON того же: <a href='/admin/api/sms?period={esc(p['kind'])}&from={esc(p['from'])}&to={esc(p['to'])}'>/admin/api/sms</a>.</p>")
    summary = _period_links(rep) + tiles + table + note
    if rep["queue"]:
        qrows = "".join(
            f"<tr><td><a href='/admin/clinics/{esc(i['clinic_id'])}'>{esc(i['clinic'])}</a></td>"
            f"<td><b>{esc(i['sender'])}</b> {_sender_tag(i['sender_state'])}"
            + (" <span class='tag'>заявление есть</span>" if i["sender_paper"] else " <span class='tag mute'>без заявления</span>")
            + (f" · оплачено лет: {i['sender_prepaid']}" if i["sender_prepaid"] else " · <span class='muted'>год имени не оплачен</span>")
            + f"</td><td>{_sender_actions(i)}</td></tr>" for i in rep["queue"])
        queue = (f"<div class='card alert'>{_chead('inbox', f'Имена на подачу ({len(rep[chr(113) + chr(117) + chr(101) + chr(117) + chr(101)])})', 'заявка → заявление получено → подано в кабинете sms.md → одобрение читает сервер сам (ежедневная задача или кнопка «Сверить»)', _sync_btn(rep))}"
                 f"<table><tr><th>Клиника</th><th>Имя</th><th></th></tr>{qrows}</table></div>")
    else:
        sync = _sync_btn(rep)
        queue = "<div class='calm'>Имён на подачу нет</div>" + (f"<div class='acts'>{sync}</div>" if sync else "")
    frows = "".join(f"<tr><td>{esc(SMS_STATE_RU.get(f['reason'].split(':')[0], f['reason'].split(':')[0]))}"
                    f"{esc(f['reason'][len(f['reason'].split(':')[0]):])}</td><td>{f['count']}</td><td>{f['clinics']}</td></tr>"
                    for f in rep["failures"])
    fail = (f"<div class='card'>{_chead('bell', 'Сбои за период', f'по причинам: статус оператора или код отказа sms.md; период {esc(p[chr(102) + chr(114) + chr(111) + chr(109)])} — {esc(p[chr(116) + chr(111)])} (выбирается на «Сводке»)')}"
            f"<table><tr><th>Причина</th><th>SMS</th><th>Клиник</th></tr>"
            f"{frows or '<tr><td colspan=3 class=muted>Сбоев нет</td></tr>'}</table></div>")
    month = p["from"][:7]
    tools = (f"<div class='card'>{_chead('file', 'Excel за месяц', 'для сверки с фактурой sms.md: по клиникам, без номеров и текстов')}"
             f"<form method='get' action='/admin/sms/export.xlsx' class='actions'>"
             f"<input type='month' name='month' value='{esc(month)}' style='width:170px'><button>Скачать Excel</button></form></div>"
             f"<div class='card'>{_chead('message', 'Тестовая SMS себе', 'одна SMS от общего имени DentPilot, мимо пакетов клиник; номер на диск не пишется')}"
             f"<form method='post' action='/admin/sms/test' class='actions'><input name='to' placeholder='069 123 456' required>"
             f"<button>Тестовая SMS себе</button></form></div>")
    nfail = sum(f["count"] for f in rep["failures"])
    body = _tabbed([("summary", "Сводка", summary, 0), ("names", "Имена на подачу", queue, c["queue"]),
                    ("failures", f"Сбои <span class='c'>{nfail}</span>", fail, 0),
                    ("tools", "Выгрузка и тест", tools, 0)])
    return page("SMS", body, user, msg, pending=pending, active="sms",
                names=c["queue"], lead="Кто сколько отправил, остатки, имена отправителей и сбои — по всем клиникам.")


def _sync_btn(rep: dict) -> str:
    return (f"<form method='post' action='/admin/sms/sync' style='margin:0'>"
            f"<button title='GET /v3/sender-aliases: подано → одобрено или отказ'>Сверить имена с sms.md</button></form>"
            if rep["configured"] else "")


def _sender_card(c, det: dict) -> str:
    """SMS › имя отправителя шагами (17.10): заявка → заявление → подано → одобрено; где стоим
    и одна кнопка следующего шага. Отказ и другое имя — за кнопками. Имя общее на кабинет (26.10):
    у филиала — ссылка на главную, шаги там."""
    if det.get("name_from"):
        return (f"<div class='card'>{_chead('message', 'Имя отправителя', 'общее на клиники кабинета')}"
                f"<p style='margin:0'>SMS этой клиники уходят от «{esc(det['from'] or '—')}» — имени главной клиники "
                f"кабинета, <a href='/admin/clinics/{esc(det['name_from'])}#sms'>{esc(det['name_from_name'])}</a>: "
                f"заявка, заявление и оплаченный год — там.</p></div>")
    cid = esc(c["id"])
    act = f"/admin/clinics/{cid}/sms"
    state, name = det["sender_state"], det["sender"]
    other = _drop("Другое имя" if name else "Заявка на имя",
                  f"<p class='muted'>Латиница и цифры, до 11 знаков; заявка ставит имя в очередь на подачу.</p>"
                  f"<form method='post' action='{act}' class='actions'><input type='hidden' name='action' value='request'>"
                  f"<input name='name' value='{esc(name or det['suggest'])}' maxlength='11'><button>Заявка на имя</button></form>",
                  primary=state in ("none", "rejected"))
    if state in ("none", "rejected") or not name:
        why = (f"«{esc(name)}» — {_sender_tag(state)}{(' · ' + esc(det['sender_note'])) if det['sender_note'] else ''}. "
               if state == "rejected" else "")
        sender_now = esc(det["from"] or "—")
        return (f"<div class='card'>{_chead('message', 'Имя отправителя', why + 'Своего имени нет: SMS идут от «' + sender_now + '»')}"
                f"<div class='acts' style='margin:0'>{other}</div></div>")
    paper, sub_ok, active = det["sender_paper"], state in ("submitted", "active"), state == "active"
    steps = (("Заявка", "done"), ("Заявление клиники", "done" if paper or sub_ok else "cur"),
             ("Подано в sms.md", "done" if sub_ok else ("cur" if paper else "")),
             ("Одобрено", "done" if active else ("cur" if state == "submitted" else "")))
    flow = "<ol class='flow'>" + "".join(f"<li class='{k}'><i></i>{t}</li>" for t, k in steps) + "</ol>"
    info = []
    if det["sender_paper_file"]:
        info.append("заявление загружено клиникой")
    elif paper:
        info.append("заявление получено")
    if det["sender_until"]:
        info.append(f"одобрено до {esc(det['sender_until'][:10])}")
    if det["sender_prepaid"]:
        info.append(f"оплачено вперёд лет: {det['sender_prepaid']}")
    if det["sender_note"]:
        info.append(esc(det["sender_note"]))
    nxt = ""
    if state == "requested" and not paper:
        nxt = (f"<form method='post' action='{act}'><input type='hidden' name='action' value='paper'>"
               f"<button class='primary' title='Подписанное заявление клиники у меня'>Заявление получено</button></form>")
    elif state == "requested":
        nxt = (f"<form method='post' action='{act}'><input type='hidden' name='action' value='submitted'>"
               f"<button class='primary' title='Имя подано в кабинете sms.md'>Подано в sms.md</button></form>")
    pdf = (f"<a class='btn' href='/admin/clinics/{cid}/sms/cerere.pdf' "
           f"title='Подписанное заявление, загруженное клиникой в кабинете'>Заявление клиники (PDF)</a>"
           if det["sender_paper_file"] else "")
    refuse = _drop("Отказ", f"<form method='post' action='{act}' class='actions'><input type='hidden' name='action' value='rejected'>"
                            f"<input name='note' placeholder='причина отказа' required><button>Записать отказ</button></form>")
    waiting = state in ("requested", "submitted")
    sub = (f"{_sender_tag(state)}{(' · ' + ' · '.join(info)) if info else ''}"
           + (" · одобрение читает сервер сам (ежедневная задача или «Сверить» в разделе SMS)" if state == "submitted" else ""))
    return (f"<div class='card{' alert' if waiting else ''}'>{_chead('message', f'Имя отправителя «{esc(name)}»', sub)}"
            f"{flow}<div class='acts' style='margin:0'>{nxt}{pdf}{refuse}{other}</div></div>")


def sms_block(c, det: dict | None, module: str = "") -> str:
    """Карточка клиники › SMS (S4, разложено 17.10): плитки, имя отправителя шагами, настройки
    с подписями; свой текст, расход по дням и журнал — свёрнуты. `module` — что с модулем
    по варианту абонемента (23.10, `_tier_sub`): тумблер «включено» не значит, что SMS уходят."""
    cid = esc(c["id"])
    act = f"/admin/clinics/{cid}/sms"
    if det is None:
        return (f"<div class='card'>{_chead('message', 'SMS', 'счёта ещё нет: программа не спрашивала, пакет не трогали')}"
                f"<table class='set'>"
                f"<tr><td>Пакет SMS</td><td><div class='actions'><span class='muted'>не предложен</span>"
                f"<form method='post' action='{act}'><input type='hidden' name='action' value='pilot_on'>"
                f"<button>Предложить пакет (пилот)</button></form></div></td></tr>"
                f"<tr><td>Имя отправителя</td><td><div class='actions'>"
                f"<form method='post' action='{act}'><input type='hidden' name='action' value='request'>"
                f"<input name='name' value='{esc(sms_suggest(c['name']))}' maxlength='11'><button>Заявка на имя</button></form>"
                f"</div></td></tr></table></div>")
    state_txt = "включено" if det["enabled"] else "выключено"
    state_sub = " · ".join(x for x in (
        esc(module), "пилот" if det["pilot"] else "", "" if det["offered"] else "программе не предложено",
        f"в {esc(det['month'])} отправлено {det['sent']}") if x)
    tiles = (f"<div class='tiles'>"
             f"{_stat('Остаток', '<b>' + str(det['balance']) + '</b> сегм.', 'потрачено за месяц: ' + str(det['spent']) + ' сегм.')}"
             f"{_stat('Сегодня', str(det['used_today']) + ' из ' + str(det['daily_cap']), 'потолок в сутки')}"
             f"{_stat('Имя отправителя', esc(det['sender'] or '—'), _sender_tag(det['sender_state']) + ' · SMS идут от ' + esc(det['from'] or '—'))}"
             f"{_stat('Состояние', state_txt, state_sub)}</div>")
    on = det["enabled"]
    on_txt = "включена" if on else "<span class='tag bad'>выключена</span>"
    settings = (
        f"<div class='card'>{_chead('message', 'Настройки пакета', 'остаток — сумма журнала; номеров и текстов на сервере нет')}"
        f"<table class='set'>"
        f"<tr><td>Отправка SMS</td><td><div class='actions'>"
        f"{on_txt}"
        f"<form method='post' action='{act}'><input type='hidden' name='action' value='{'off' if on else 'on'}'>"
        f"<button title='{'Исключение: программа покажет «Modulul SMS este oprit» и наши контакты (код sms_off). Вариант Basic гасит модуль сам (sms_basic) — тумблер для этого не нужен' if on else 'Снять исключение: отправка возобновится, если вариант это позволяет'}'>"
        f"{'Выключить' if on else 'Включить'}</button></form></div></td></tr>"
        f"<tr><td>Пилот</td><td><div class='actions'>"
        f"{'пакет предложен этой клинике' if det['pilot'] else ('предложен всем клиникам' if det['offered'] else 'программе не предложено')}"
        f"<form method='post' action='{act}'><input type='hidden' name='action' value='{'pilot_off' if det['pilot'] else 'pilot_on'}'>"
        f"<button title='Пакет предложен этой клинике, пока DP_SMS_OFFERED пуст'>{'Снять пилот' if det['pilot'] else 'Пилот'}</button></form>"
        f"</div></td></tr>"
        f"<tr><td>Потолок в сутки</td><td><div class='actions'>"
        f"<form method='post' action='{act}'><input type='hidden' name='action' value='cap'>"
        f"<input name='value' type='number' value='{det['daily_cap']}' min='0' max='100000' style='width:100px'>"
        f"<span class='muted'>сегм.</span><button>Сохранить</button></form></div></td></tr>"
        f"<tr><td>Начислить или списать</td><td><div class='actions'>"
        f"<form method='post' action='{act}'><input type='hidden' name='action' value='credit'>"
        f"<input name='value' type='number' placeholder='± сегм.' style='width:100px' required>"
        f"<select name='reason' style='width:auto;padding:7px'><option value='bonus'>бонус</option><option value='fix'>правка</option></select>"
        f"<input name='note' placeholder='причина (обязательно)' style='width:220px' required><button>Начислить</button></form>"
        f"</div></td></tr></table>")
    # Личный текст клиники (S6, «Свой текст — по заявке»): программа предложит
    # вариант «Textul clinicii». Подстановки — белый список sms_rule; тексты
    # клиники — не данные пациентов, их показывать можно.
    custom = (f"<details{' open' if det['custom_on'] else ''} style='margin:16px 0 0'><summary>Свой текст клиники (по заявке)"
              f"{' · включён' if det['custom_on'] else ''}</summary>"
              f"<form method='post' action='{act}'><input type='hidden' name='action' value='custom'>"
              f"<p class='muted'>Подстановки только {{clinica}} {{ziua}} {{data}} {{ora}} {{telefon}}; обязательны "
              f"clinica, data, ora. RO — латиница без диакритики, один сегмент GSM-7; RU — один сегмент (70 знаков). "
              f"Без врача, услуги и имени пациента.</p>"
              f"<label>RO<br><textarea name='custom_ro' rows='3' maxlength='400' style='width:100%'>"
              f"{esc(det['custom_ro'])}</textarea></label>"
              f"<label>RU<br><textarea name='custom_ru' rows='3' maxlength='400' style='width:100%'>"
              f"{esc(det['custom_ru'])}</textarea></label>"
              f"<label><input type='checkbox' name='custom_on' value='1'{' checked' if det['custom_on'] else ''}> "
              f"включить — программа клиники получит вариант «Textul clinicii»</label> "
              f"<button>Сохранить текст</button></form></details>")
    drows = "".join(f"<tr><td>{esc(d['day'])}</td><td>{d['sent']}</td><td>{d['delivered']}</td><td>{d['undelivered']}</td>"
                    f"<td>{d['refused']}</td><td>{d['pending']}</td><td>{d['segments']}</td></tr>" for d in det["by_day"])
    days = (f"<details><summary>Расход по дням за {esc(det['month'])}</summary>"
            f"<p class='muted' style='margin:0 0 8px'>за месяц: отправлено {det['sent']}, доставлено {det['delivered']}, "
            f"не доставлено {det['undelivered']}, отказ {det['refused']}; потрачено {det['spent']} сегм.</p>"
            f"<table><tr><th>День</th><th>Отправлено</th><th>Доставлено</th>"
            f"<th>Не доставлено</th><th>Отказ</th><th>В пути</th><th>Сегментов</th></tr>"
            f"{drows or '<tr><td colspan=7 class=muted>В этом месяце SMS не было</td></tr>'}</table></details>")
    lrows = "".join(f"<tr><td class='mono'>{esc(l['at'][:16].replace('T', ' '))}</td><td>{l['delta']:+d}</td>"
                    f"<td>{esc(LEDGER_RU.get(l['reason'], l['reason']))}</td><td>{esc(l['who'])}</td>"
                    f"<td>{esc(l['note'] or '')}{(' · ' + esc(l['reference'])) if l.get('reference') else ''}"
                    f"{(' · SMS #' + str(l['message_id'])) if l.get('message_id') else ''}</td></tr>" for l in det["ledger"])
    ledger = (f"<details><summary>Журнал SMS (последние {len(det['ledger'])})</summary><table><tr><th>Когда (UTC)</th><th>±</th><th>Что</th>"
              f"<th>Кто</th><th>Примечание</th></tr>{lrows or '<tr><td colspan=5 class=muted>пусто</td></tr>'}</table></details>")
    return f"{tiles}{_sender_card(c, det)}{settings}{custom}{days}{ledger}</div>"


def sms_suggest(name: str) -> str:
    from . import sms
    return sms.suggest(name)


# Карточка клиники (16.10, слово Олега: «всё в одном месте и слишком много информации»):
# обзор + вкладки. Обзор отвечает «всё ли в порядке и что ждёт меня» — ожидающая нота
# с «Подтвердить», имя SMS без заявления, срок и льгота, файл не дошёл, нет e-mail — и
# четырьмя плитками; подробности и редкие формы уходят во вкладки. Все вкладки в ОДНОЙ
# странице, переключает метка адреса (#pay). ⚠️ Элемента с id, равным имени вкладки, в
# странице нет намеренно: иначе браузер прокрутит к нему (Олег: «без прыжков»).
# Форма уходит с меткой своей вкладки (скрипт дописывает её в action), а 303 без метки
# наследует метку запроса — после действия Олег остаётся на той же вкладке. Без скрипта
# видны все разделы подряд, как до 16.10. ⛔ Тексты карточки держат cloud/tests.
# 17.10 (Олег: «дальше … полный хаос, сделать красиво и организованно с вкладками»):
# «Лицензия и оплата» разделена — деньги и файл лицензии две разные работы. Каждая
# вкладка устроена как обзор: сверху плитки «что сейчас», под ними кнопки (редкие
# формы раскрываются по нажатию, `_drop`), внизу история. Тот же механизм вкладок —
# у разделов меню (`_tabbed`); первая вкладка — та, что открыта без метки.
CLINIC_TABS = (("overview", "Обзор"), ("pay", "Оплата"), ("lic", "Лицензия"), ("sms", "SMS"),
               ("access", "Компьютеры и кабинет"), ("profile", "Реквизиты"), ("log", "Журнал"))
_TABS_JS = ("(function(){var r=document.querySelector('.tabbed');if(!r)return;"
            "var tabs=r.querySelectorAll('[data-tab]'),panes=r.querySelectorAll('[data-pane]');"
            "function show(){var k=location.hash.slice(1),ok=false;"
            "panes.forEach(function(p){if(p.getAttribute('data-pane')===k)ok=true});"
            "if(!ok)k=r.getAttribute('data-default')||panes[0].getAttribute('data-pane');"
            "panes.forEach(function(p){p.classList.toggle('on',p.getAttribute('data-pane')===k)});"
            "tabs.forEach(function(t){var on=t.getAttribute('data-tab')===k;t.classList.toggle('on',on);"
            "t.setAttribute('aria-selected',on?'true':'false')})}"
            "r.classList.add('js');window.addEventListener('hashchange',show);"
            "r.addEventListener('submit',function(e){var p=e.target.closest('[data-pane]');if(!p)return;"
            "var a=e.target.getAttribute('action')||'';"
            "e.target.setAttribute('action',a.split('#')[0]+'#'+p.getAttribute('data-pane'))});show()})();")


def _n(n: int) -> str:
    """Счётчик «ждёт вас» у вкладки (янтарный); ноль не рисуется."""
    return f"<span class='n'>{n}</span>" if n else ""


def _tabbed(panes: list) -> str:
    """Вкладки в одной странице: [(ключ, подпись, разметка, счётчик «ждёт»)]. ⛔ Ключ не
    равен ни одному id страницы — иначе метка адреса прокрутит к элементу."""
    tabs = "".join(f"<a href='#{k}' data-tab='{k}' role='tab'>{t}{_n(n)}</a>" for k, t, _, n in panes)
    return (f"<div class='tabbed'><nav class='tabs' role='tablist'>{tabs}</nav>"
            + "".join(f"<section class='pane' data-pane='{k}'>{h}</section>" for k, _, h, _ in panes)
            + f"</div><script>{_TABS_JS}</script>")


def _drop(label: str, inner: str, primary: bool = False) -> str:
    """Кнопка, под которой раскрывается форма: пока не нужна, места не занимает."""
    return (f"<details class='drop{' p' if primary else ''}'><summary>{label}</summary>"
            f"<div class='open'>{inner}</div></details>")


def _stat(label: str, big: str, sub: str = "") -> str:
    """Плитка «что сейчас» внутри вкладки (не ссылка — в отличие от плиток обзора)."""
    return f"<div class='tile'><span class='k'>{label}</span><span class='big'>{big}</span><span class='s'>{sub}</span></div>"


def _chips(items: list, on: str) -> str:
    """Кнопки-фильтры: [(ключ, подпись, ссылка)]; ключ `on` подсвечен."""
    return "<div class='chips'>" + "".join(
        f"<a class='on' href='{href}'>{text}</a>" if k == on else f"<a href='{href}'>{text}</a>"
        for k, text, href in items) + "</div>"


# Журнал словами (17.10): в базе остаётся код (`audit.what` читают тесты, ежедневная
# задача и SQL Олега), страница показывает слово и раздел, код — во всплывающей
# подсказке. Код без строки здесь показан как есть и виден только во «Все».
AUDIT_RU = {
    "payment_new": ("нота выставлена", "pay"), "payment_paid": ("оплата подтверждена", "pay"),
    "payment_rejected": ("нота отклонена", "pay"), "payment_repeat": ("повторный перевод", "pay"),
    "card_link": ("ссылка на карту", "pay"), "card_failed": ("карта: отказ", "pay"),
    "card_mismatch": ("карта: сумма или валюта не те — не подтверждено", "pay"),
    "paylink_new": ("ссылка оплаты из программы", "pay"), "reminder": ("напоминание о сроке", "pay"),
    "tier_set": ("вариант вручную", "pay"),
    "issue": ("файл выдан", "lic"), "trial_request": ("заявка на пробный", "lic"),
    "trial_declined": ("заявка скрыта", "lic"), "trial_duplicate": ("повторная заявка", "lic"),
    "trial_no_key": ("пробный не выдан", "lic"), "add_no_key": ("файл новой клинике не выдан", "lic"),
    "sms_sender": ("имя SMS", "sms"), "sms_toggle": ("SMS вкл./выкл.", "sms"), "sms_cap": ("потолок SMS", "sms"),
    "sms_credit": ("SMS начислены", "sms"), "sms_custom": ("свой текст SMS", "sms"), "sms_pack": ("пакет SMS", "sms"),
    "sms_name": ("год имени SMS", "sms"), "sms_test": ("тестовая SMS", "sms"), "sms_export": ("выгрузка SMS", "sms"),
    "mail": ("письмо", "mail"), "mail_failed": ("письмо не ушло", "mail"),
    "renew": ("программа забрала файл", "prog"), "code_sent": ("код активации отправлен", "prog"),
    "code_ok": ("код активации принят", "prog"), "code_bad": ("код активации неверный", "prog"),
    "code_limit": ("коды активации: лимит", "prog"), "download": ("скачивание программы", "prog"),
    "account_new": ("кабинет: новая запись", "cab"), "account_login": ("вход в кабинет", "cab"),
    "cont_program": ("вход в кабинет из программы", "cab"),
    "clinic_added": ("клиника добавлена в кабинет", "cab"),
    "cont_code": ("код кабинета выдан", "prog"), "cont_code_ok": ("код кабинета принят", "prog"),
    "device_moved": ("компьютер перешёл от другой клиники", "prog"),
    "account_link": ("кабинет привязан", "cab"), "account_detach": ("кабинет отвязан", "cab"),
    "login_code_sent": ("код входа отправлен", "cab"), "login_code_ok": ("вход по коду", "cab"),
    "login_code_bad": ("код входа неверный", "cab"), "login_code_limit": ("коды входа: лимит", "cab"),
    "login_ok": ("вход в админку", "adm"), "login_fail": ("неудачный вход в админку", "adm"),
    "clinic_new": ("клиника заведена", "adm"), "clinic_edit": ("реквизиты изменены", "adm"),
    "daily": ("ежедневная задача", "adm"),
    # подтверждение ящика клиники (27.10, emailconf.py)
    "email_confirmed": ("e-mail подтверждён", "cab"), "email_code_sent": ("код подтверждения e-mail", "mail"),
    "email_code_bad": ("код подтверждения неверный", "prog"), "email_change": ("e-mail сменён из программы", "prog"),
    "email_reset": ("e-mail сменён — снова не подтверждён", "adm"),
    "terms_accept": ("условия приняты (акт)", "lic"),       # акт акцепта условий (29.10, terms.py)
    # документы поставщика в кабинете (29.10, contracts.py)
    "doc_signed": ("экземпляр документа, подписанный клиникой", "lic"),
}
AUDIT_CATS = (("pay", "Оплата"), ("lic", "Лицензия"), ("sms", "SMS"), ("mail", "Письма"),
              ("prog", "Программа"), ("cab", "Кабинет"), ("adm", "Админка"))


def audit_codes(cat: str) -> list[str]:
    """Коды раздела журнала — для отбора в SQL; неизвестный раздел — пусто (значит «все»)."""
    return [w for w, (_, c) in AUDIT_RU.items() if c == cat]


def _what(code: str) -> str:
    cls = {"payment_paid": "ok", "payment_rejected": "bad", "card_failed": "bad", "card_mismatch": "bad", "mail_failed": "bad",
           "login_fail": "bad", "trial_no_key": "bad", "add_no_key": "bad"}.get(code, "mute")
    return f"<span class='tag {cls}' title='{esc(code)}'>{esc(AUDIT_RU.get(code, (code, ''))[0])}</span>"


def _journal_chips(by_what: dict, on: str, href) -> str:
    """Фильтры журнала с числами: «Все» и разделы, где что-то есть. `href(раздел)` — ссылка."""
    cats: dict[str, int] = {}
    for w, n in by_what.items():
        k = AUDIT_RU.get(w, ("", ""))[1]
        cats[k] = cats.get(k, 0) + n
    items = [("", f"Все {sum(by_what.values())}", href(""))]
    items += [(k, f"{t} {cats[k]}", href(k)) for k, t in AUDIT_CATS if cats.get(k)]
    return _chips(items, on if on in dict(AUDIT_CATS) else "")


def _todo_li(what: str, act: str = "") -> str:
    acts = f"<div class='actions'>{act}</div>" if act else ""
    return f"<li><div class='what'>{what}</div>{acts}</li>"


def _clinic_todo(c, sub, st: str, issues: list, payments: list, smsinfo: dict | None, now: datetime) -> list[str]:
    """Обзор › «Ждёт вас»: то, что требует Олега или говорит, что что-то не так. Пусто — всё спокойно."""
    out = []
    pending = [p for p in payments if p["status"] == "pending"]
    for p in pending:
        out.append(_todo_li(
            f"Нота <span class='mono'>{esc(p['reference'])}</span> ждёт перевода: {p['amount']} {esc(p['currency'])} "
            f"за {_term(p)}, выставлена {esc(p['created_at'][:10])}",
            f"<form method='post' action='/admin/payments/{p['id']}/confirm'><button class='primary'>Подтвердить</button></form>"
            f"<a href='#pay'>Отклонить, письмо, карта</a>"))
    vu = _ts(sub["valid_until"]) if sub else None
    note = "" if pending else "<a href='#pay'>Выставить ноту</a>"
    if st == "none":
        out.append(_todo_li("Файл лицензии не выдан: программа клиники не активирована", "<a href='#lic'>Выдать</a>"))
    elif st == "grace":
        out.append(_todo_li(f"Срок кончился {_d(sub['valid_until'])}, идёт льгота до "
                            f"{(vu + timedelta(days=sub['grace_days'])):%Y-%m-%d}", note))
    elif st == "readonly":
        out.append(_todo_li("Льгота кончилась: программа клиники в режиме только чтения", note))
    elif vu is not None and (vu - now).days < 14 and not pending:
        out.append(_todo_li(f"Срок кончается через {(vu - now).days} дн. ({_d(sub['valid_until'])})", note))
    latest = max((i["seq"] for i in issues), default=0)
    if c["renew_at"] and (c["renew_seq"] or 0) < latest:
        out.append(_todo_li(f"Программа ещё не забрала новый файл: у неё {c['renew_seq'] or 0}, выдан {latest}",
                            "<a href='#access'>Компьютеры</a>"))
    if smsinfo:
        name = f"Имя SMS «{esc(smsinfo['sender'] or '')}»"
        if smsinfo["sender_state"] == "requested":
            out.append(_todo_li(f"{name}: заявление получено, подать в sms.md" if smsinfo["sender_paper"]
                                else f"{name}: ждём подписанное заявление клиники", "<a href='#sms'>SMS</a>"))
        elif smsinfo["sender_state"] == "submitted":
            out.append(_todo_li(f"{name} подано в sms.md, ждём одобрения", "<a href='#sms'>SMS</a>"))
    if not c["email"]:
        out.append(_todo_li("У клиники нет e-mail: ноты и письма о лицензии некуда отправлять",
                            "<a href='#profile'>Вписать</a>"))
    elif not c["email_confirmed_at"]:
        out.append(_todo_li(f"E-mail <span class='mono'>{esc(c['email'])}</span> не подтверждён: опечатка — и код "
                            f"второго компьютера, вход в кабинет и ноты уйдут в пустоту. Директор видит "
                            f"напоминание в программе", "<a href='#profile'>Реквизиты</a>"))
    return out


def _tile(tab: str, icon: str, label: str, big: str, sub: str) -> str:
    return (f"<a class='tile' href='#{tab}'><span class='k'><span class='ico'>{_ic(icon, 16)}</span>{label}</span>"
            f"<span class='big'>{big}</span><span class='s'>{sub}</span></a>")


def _ver_key(v: str) -> list:
    return [int(x) if x.isdigit() else 0 for x in v.split(".")]


def _clinic_tiles(c, sub, st: str, issues: list, devices: list, accounts: list, smsinfo: dict | None,
                  now: datetime, cabinet: list = (), active: int = 0) -> str:
    """Обзор › четыре плитки: лицензия, программа, SMS, кабинет; каждая ведёт в свою вкладку."""
    vu = _ts(sub["valid_until"]) if sub else None
    left = f" · осталось {(vu - now).days} дн." if st == "active" and vu else ""
    lic = _tile("lic", "key", "Лицензия", f"до {_d(sub['valid_until'])}" if sub else "файла нет",
                f"{_tag(st)} {esc(sub['plan']) if sub else ''}"
                f"{(' · льгота ' + str(sub['grace_days']) + ' дн.') if sub else ''}{left}")
    vers = sorted({d["version"] for d in devices if d["version"]}, key=_ver_key, reverse=True)
    many = f" · компьютеров: {len(devices)}" if devices else ""
    prog = _tile("access", "monitor", "Программа", esc(", ".join(vers)) if vers else "не выходила на связь",
                 f"Программа спрашивала {_renew_info(c, max((i['seq'] for i in issues), default=0))}{many}"
                 f"{('<br>' + _multi_tag(active).strip()) if active > 1 else ''}")
    if smsinfo is None:
        sms_t = _tile("sms", "message", "SMS", "не подключено", "счёта нет: программа не спрашивала, пакет не трогали")
    else:
        sms_t = _tile("sms", "message", "SMS", f"{smsinfo['balance']} сегм.",
                      f"имя {esc(smsinfo['sender'] or '—')} {_sender_tag(smsinfo['sender_state'])} · "
                      f"{'включено' if smsinfo['enabled'] else 'выключено'}{' · пилот' if smsinfo['pilot'] else ''}")
    last = max(((a["last_login_at"] or "") for a in accounts), default="")
    who = (esc(accounts[0]["email"]) if len(accounts) == 1
           else (f"записей: {len(accounts)}" if accounts else "никто не входил"))
    many_c = f"клиник в кабинете: {len(cabinet)} · " if len(cabinet) > 1 else ""
    cab = _tile("access", "user", "Кабинет", who,
                many_c + (f"последний вход {esc(last[:16].replace('T', ' '))} UTC" if last
                          else "вход через Google или кодом на e-mail"))
    return f"<div class='tiles'>{lic}{prog}{sms_t}{cab}</div>"


def _pay_pane(c, sub, st: str, payments: list, reminders: list, now: datetime) -> str:
    """Вкладка «Оплата»: срок, что ждёт оплаты, тариф; «Выставить ноту» за кнопкой; ноты; напоминания."""
    cid = esc(c["id"])
    cur = tiers.current(sub)
    price = tiers.price(sub, cur)
    vu = _ts(sub["valid_until"]) if sub else None
    if vu is None:
        term = _stat("Срок", "файла нет", "лицензия не выдана: вкладка «Лицензия»")
    else:
        gu = vu + timedelta(days=sub["grace_days"])
        left = {"active": f" · осталось {(vu - now).days} дн., льгота {sub['grace_days']} дн.",
                "grace": f" · льгота до {gu:%Y-%m-%d}", "readonly": f" · только чтение с {gu:%Y-%m-%d}"}.get(st, "")
        term = _stat("Срок", f"до {_d(sub['valid_until'])}", f"{_tag(st)} {esc(sub['plan'] or '')}{left}")
    pending = [p for p in payments if p["status"] == "pending"]
    if pending:
        p = pending[0]
        wait = _stat("Ждёт оплаты", f"{p['amount']} {esc(p['currency'])}",
                     f"нота <span class='mono'>{esc(p['reference'])}</span> от {esc(p['created_at'][:10])}, {_term(p)}")
    else:
        wait = _stat("Ждёт оплаты", "ничего", "ожидающих нот нет")
    tariff = _stat("Вариант", f"{esc(tiers.NAME[cur])}", _tier_sub(sub, now))
    tsel = "".join(f"<option value='{t}'{' selected' if t == cur else ''}{'' if tiers.price(sub, t) else ' disabled'}>"
                   f"{esc(tiers.NAME[t])} — "
                   f"{(str(tiers.price(sub, t)) + ' MDL / мес.') if tiers.price(sub, t) else 'не продаётся'}</option>"
                   for t in tiers.TIERS)
    opts = "".join(f"<option value='{m}'>{'месяц' if m == 1 else 'год (цена 11 месяцев)'}</option>"
                   for m in pay.MONTHS)
    if maib.enabled():
        method = ("<div><label>Как платит клиника</label><select name='method'>"
                  "<option value='transfer'>Переводом — реквизиты и reference в письме</option>"
                  f"<option value='card'>Картой — ссылка maib сразу, в таблице (живёт {maib.PAY_TTL // 60} минут); "
                  "в письме — "
                  "страница оплаты с галочкой</option>"
                  "</select></div>")
    else:
        method = ("<div><label>Как платит клиника</label><div class='muted' style='padding:9px 0'>только переводом: "
                  "DP_MAIB_* не заданы, ссылки на карту нет</div></div>")
    form = (f"<p class='muted'>Нота — счёт клинике с reference. «Подтвердить» у ноты = перевод пришёл: "
            f"срок продлится, файл выдастся сам.</p>"
            f"<form method='post' action='/admin/clinics/{cid}/payments'>"
            f"<div class='grid'><div><label>Вариант</label><select name='tier'>{tsel}</select></div>"
            f"<div><label>Срок</label><select name='months'>{opts}</select></div>"
            f"<div><label>Сумма, MDL (пусто = по тарифу)</label><input name='amount' inputmode='numeric'></div>"
            f"{method}</div>"
            f"<label class='chk'><input type='checkbox' name='send' value='1' checked> отправить письмо с нотой "
            f"на {esc(c['email'] or '— e-mail не указан')}</label>"
            f"<p style='margin:12px 0 0'><button class='primary'>Выставить</button></p></form>")
    rems = list(reminders)
    table = (f"<div class='card'>{_chead('card', 'Ноты и платежи', 'ожидающую ноту можно подтвердить, отклонить или отправить ещё раз')}"
             f"<table><tr><th>Reference</th><th>Сумма</th><th>Срок</th><th>Создан</th><th>Состояние</th><th></th></tr>"
             f"{_payment_rows(payments) or '<tr><td colspan=6 class=muted>Платежей ещё нет</td></tr>'}</table>"
             f"<details style='margin:16px 0 0'><summary>Напоминания о сроке ({len(rems)})</summary>"
             f"<p class='muted' style='margin:0 0 8px'>письма ежедневной задачи этой клинике</p>"
             f"<table><tr><th>Письмо</th><th>Период до</th><th>Отправлено</th></tr>"
             f"{_reminder_rows(rems) or '<tr><td colspan=3 class=muted>Напоминаний ещё не было</td></tr>'}"
             f"</table></details></div>")
    if sub is None or sub["plan"] == "trial":
        manual = ""
    else:
        msel = "".join(f"<option value='{t}'{' selected' if t != cur else ''}>{esc(tiers.NAME[t])}</option>"
                       for t in tiers.TIERS)
        manual = _drop("Вариант вручную",
                       f"<p class='muted'>Исключение: вариант меняется сразу, без оплаты, строкой в журнале. Plus — "
                       f"модуль SMS работает сразу; Basic — гаснет сразу. Обычный путь — выбор клиники при "
                       f"оплате (Basic с конца оплаченного Plus).</p>"
                       f"<form method='post' action='/admin/clinics/{cid}/tier' class='actions'>"
                       f"<select name='tier' style='width:auto'>{msel}</select>"
                       f"<button>Сменить вариант</button></form>"
                       f"<p class='muted' style='margin:8px 0 0'>Цена — прайс варианта; разовая скидка — суммой "
                       f"ноты в «Выставить ноту».</p>")
    return (f"<div class='tiles'>{term}{wait}{tariff}</div>"
            f"<div class='acts'>{_drop('Выставить ноту', form, primary=True)}{manual}</div>{table}")


def _tier_sub(sub, now: datetime) -> str:
    """Подпись плитки «Вариант»: цена и что с модулем SMS (tiers.module_on)."""
    if sub is None or sub["plan"] == "trial":
        sold = ", ".join(f"{tiers.NAME[t].split()[-1]} {tiers.list_price(t)}" for t in tiers.offered(sub))
        return f"пробный = Plus; при оплате клиника выберет сама · прайс: {esc(sold or 'нет')} MDL / мес."
    p = tiers.price(sub, tiers.current(sub))
    return f"{p} MDL / мес. · {pay.amount(12, p)} за год · {_module_word(sub, now)}"


def _module_word(sub, now: datetime) -> str:
    """Модуль SMS по варианту — словами админки (tiers.module_on): пробный и Plus — работает."""
    if tiers.current(sub) == tiers.PLUS:
        return "по варианту модуль SMS работает" if sub is not None else ""
    if tiers.module_on(sub, now):
        return f"Basic: модуль SMS до {_d(sub['sms_until'])}, потом sms_basic"
    return "Basic: модуль SMS выключен (sms_basic)"


def _cabinet_card(c, cabinet: list, accounts: list) -> str:
    """Обзор › «Клиники того же кабинета» (26.10): филиал = ещё одна клиника кабинета, своя
    лицензия и оплата; «Добавить клинику в кабинет» — входы те же, пробный — кнопкой в её карточке.
    `cabinet` — [(клиника, подписка, число компьютеров)] без этой."""
    cid = esc(c["id"])
    now = datetime.now(timezone.utc)
    trs = []
    for r, sub, n in cabinet:
        st = license.state(_ts(sub["valid_until"]) if sub else None, sub["grace_days"] if sub else 0, now)
        plan = ((("пробный · " if sub["plan"] == "trial" else "") + esc(tiers.NAME[tiers.current(sub)]))
                if sub else "без файла")
        trs.append(f"<tr><td><a href='/admin/clinics/{esc(r['id'])}'>{esc(r['name'])}</a> {_tag(st)}"
                   f"<div class='muted'>{esc(r['address'] or '—')}</div></td><td class='mono'>{esc(r['idno'] or '—')}</td>"
                   f"<td>{plan}</td><td>{_d(sub['valid_until']) if sub else '—'}</td><td>{n or '—'}</td>"
                   f"<td>{esc((r['created_at'] or '')[:10])}</td></tr>")
    who = ", ".join(esc(a["email"]) for a in accounts) or "—"
    form = (f"<p class='muted'>новая клиника получит те же входы кабинета, что у этой ({who}); пробный — кнопкой "
            f"«Выдать вручную» в её карточке, код активации компьютера — в кабинете клиники</p>"
            f"<form method='post' action='/admin/clinics/{cid}/sibling'><div class='grid'>"
            f"<div><label>Название *</label><input name='name' required maxlength='{trial.NAME_MAX}'></div>"
            f"<div><label>Адрес *</label><input name='address' required maxlength='200'></div>"
            f"<div><label>Телефон</label><input name='phone' maxlength='{trial.PHONE_MAX}'></div>"
            f"<div><label>E-mail</label><input name='email' value='{esc(c['email'])}' maxlength='{trial.EMAIL_MAX}'></div>"
            f"<div><label>IDNO</label><input name='idno' value='{esc(c['idno'])}' maxlength='13'></div>"
            f"<div><label>Контакт</label><input name='contact_name' value='{esc(c['contact_name'])}' maxlength='{trial.CONTACT_MAX}'></div></div>"
            f"<p style='margin:12px 0 0'><button class='primary'>Добавить в кабинет</button></p></form>")
    table = (f"<table><tr><th>Клиника</th><th>IDNO</th><th>Вариант</th><th>Срок до</th><th>Компьютеры</th>"
             f"<th>Добавлена</th></tr>{''.join(trs)}</table>" if trs else
             "<p class='muted' style='margin:0'>Других клиник в кабинете нет.</p>")
    add = (_drop("Добавить клинику в кабинет", form) if accounts else
           "<p class='muted' style='margin:0'>В кабинет этой клиники ещё никто не входил — добавлять некуда.</p>")
    return (f"<div class='card'>{_chead('building', 'Клиники того же кабинета', 'один вход — несколько клиник; у каждой своя лицензия, пробный и оплата')}"
            f"{table}<div class='acts' style='margin:14px 0 0'>{add}</div></div>")


def _lic_pane(c, issues: list, devices: list) -> str:
    """Вкладка «Лицензия»: какой файл действует и какой у программы; письмо; выдача вручную; файлы."""
    cid = esc(c["id"])
    latest = max((i["seq"] for i in issues), default=0)
    cur = max(issues, key=lambda i: i["seq"], default=None)
    if cur is not None:
        now_file = _stat("Действующий файл", f"№ {cur['seq']} · до {_d(cur['valid_until'])}",
                         f"льгота до {_d(cur['grace_until'])} · {esc(cur['reason'] or '—')}")
    else:
        now_file = _stat("Действующий файл", "файла нет", "программа клиники не активирована")
    many = f" · компьютеров: {len(devices)}" if devices else ""
    if c["renew_at"]:
        prog = _stat("У программы", f"№ {c['renew_seq'] or 0}", f"спрашивала {_renew_info(c, latest)}{many}")
    else:
        prog = _stat("У программы", "не спрашивала", "программа ещё не обращалась за файлом")
    mail_btn = (f"<form method='post' action='/admin/clinics/{cid}/email'>"
                f"<button class='primary' title='Письмо о сроке лицензии; файла в письме нет (02.10) — программа "
                f"забирает его сама'>Отправить письмо о лицензии</button></form>" if issues else "")
    form = (f"<h2>Лицензия вручную (без оплаты)</h2>"
            f"<p class='muted'>пробный, демонстрация, договорённость; оплаченный срок выдаётся САМ при подтверждении "
            f"платежа — программа клиники заберёт файл сама</p>"
            f"<form method='post' action='/admin/clinics/{cid}/issue'>"
            f"<div class='grid'><div><label>Что выдать</label><select name='kind'>"
            f"<option value='trial'>Пробный: {license.TRIAL_DAYS} дней + {license.TRIAL_GRACE_DAYS} льготы</option>"
            f"<option value='dates'>Абонемент до даты</option></select></div>"
            f"<div><label>Срок до (для абонемента)</label><input name='valid_until' type='date'></div>"
            f"<div><label>Льгота, дней</label><input name='grace_days' type='number' value='{license.GRACE_DAYS}' min='0' max='60'></div>"
            f"<div><label>Основание</label><input name='reason' placeholder='платёж DP-2026-000001, демонстрация…'></div></div>"
            f"<label class='chk'><input type='checkbox' name='send' value='1'> сразу отправить письмом на {esc(c['email'] or '— e-mail не указан')}</label>"
            f"<p style='margin:12px 0 0'><button class='primary'>Выдать</button></p></form>")
    trs = "".join(
        f"<tr><td>{i['seq']}</td><td class='mono'>{esc(i['issued_at'][:16].replace('T', ' '))}</td>"
        f"<td>{_d(i['valid_until'])}</td><td>{_d(i['grace_until'])}</td><td>{esc(i['reason'])}</td>"
        f"<td><a href='/admin/clinics/{cid}/issues/{i['seq']}/license.json'>license.json</a></td></tr>"
        for i in issues) or "<tr><td colspan='6' class='muted'>Файлов ещё не выдавали</td></tr>"
    files = (f"<div class='card'>{_chead('file', 'Выданные файлы', 'каждый следующий — с номером выше; программа берёт только новее принятого')}"
             f"<table><tr><th>№</th><th>Выдан (UTC)</th>"
             f"<th>Срок до</th><th>Льгота до</th><th>Основание</th><th>Файл</th></tr>{trs}</table></div>")
    return (f"<div class='tiles'>{now_file}{prog}</div>"
            f"<div class='acts'>{mail_btn}{_drop('Выдать вручную', form, primary=not issues)}</div>{files}")


def documents_block(c, rows: list) -> str:
    """Вкладка «Лицензия» › «Документы» (29.10, contracts.py): какие подписанные Олегом PDF выложены
    (DP_CONTRACT, DP_DPA, DP_DECLARATION) и экземпляры, которые клиника загрузила со своей подписью."""
    cid = esc(c["id"])
    docs = "".join(
        f"<li>{esc(d['title'])}: " + (f"версия {esc(d['version'])}" if d["ok"] else
                                      "<span class='tag warn'>не выложен</span> — путь в cloud.env (DP_"
                                      f"{esc(contracts.DOCS[d['key']]['env'])})") + "</li>" for d in contracts.statuses())
    trs = "".join(
        f"<tr><td>{esc(contracts.DOCS[r['doc']]['title'])}</td><td class='mono'>{esc(r['version'] or '—')}</td>"
        f"<td>{esc(r['uploaded_at'][:16].replace('T', ' '))}</td><td>{esc(r['who'])}</td>"
        f"<td>{max(1, (r['size'] or 0) // 1024)} КБ</td>"
        f"<td><a href='/admin/clinics/{cid}/documente/{r['id']}.pdf'>PDF</a></td></tr>" for r in rows)
    table = (f"<table><tr><th>Документ</th><th>Версия</th><th>Загружен (UTC)</th><th>Кто</th><th>Размер</th><th></th></tr>"
             f"{trs}</table>" if rows else
             "<p class='muted' style='margin:0'>Клиника своих подписанных экземпляров не загружала — это не обязательно: "
             "документы подписаны поставщиком, акцепт условий фиксируется при активации.</p>")
    return (f"<div class='card'>{_chead('file', 'Документы', 'подписанные поставщиком PDF в кабинете клиники и экземпляры, подписанные клиникой')}"
            f"<ul class='muted' style='margin:0 0 12px 18px;padding:0'>{docs}</ul>{table}</div>")


def _log_pane(cid: str, audit: list, log: str, by_what: dict) -> str:
    """Вкладка «Журнал»: события клиники словами, фильтры по разделам (ссылкой, страница отбирает сама)."""
    href = (lambda k: f"/admin/clinics/{cid}?log={k}#log" if k else f"/admin/clinics/{cid}#log")
    rows = "".join(f"<tr><td class='mono'>{esc(a['at'][:16].replace('T', ' '))}</td><td>{esc(a['who'])}</td>"
                   f"<td>{_what(a['what'])}</td><td>{esc(a['detail'])}</td></tr>" for a in audit)
    return (f"{_journal_chips(by_what, log, href)}"
            f"<div class='card'>{_chead('clock', 'Журнал', 'события этой клиники, последние 50')}"
            f"<table><tr><th>Когда (UTC)</th><th>Кто</th><th>Что</th>"
            f"<th>Подробности</th></tr>{rows or '<tr><td colspan=4 class=muted>пусто</td></tr>'}</table></div>")


def clinic_page(c, sub, issues: list, audit: list, user: str, msg: str = "",
                payments: list = (), pending: int = 0, reminders: list = (), accounts: list = (),
                devices: list = (), smsinfo: dict | None = None, names: int = 0,
                log: str = "", log_counts: dict | None = None, cabinet: list = (), active: int = 0,
                terms_html: str = "", docs: list = ()) -> str:
    """`terms_html` — акты акцепта условий (terms.admin_fragment, 29.10) под вкладкой «Лицензия»;
    `docs` — экземпляры документов, подписанные клиникой (contracts.of_clinic), там же, ниже."""
    now = datetime.now(timezone.utc)
    issues, payments, accounts, devices, audit = list(issues), list(payments), list(accounts), list(devices), list(audit)
    st = license.state(_ts(sub["valid_until"]) if sub else None, sub["grace_days"] if sub else 0, now)
    cid = esc(c["id"])
    todo = _clinic_todo(c, sub, st, issues, payments, smsinfo, now)
    todo_html = (f"<div class='card alert'>{_chead('bell', 'Ждёт вас', 'ожидающие ноты, заявки и то, что не так')}"
                 f"<ul class='todo'>{''.join(todo)}</ul></div>" if todo
                 else "<div class='calm'>Ничего не ждёт: ожидающих нот, заявок и тревог нет</div>")
    contacts = (f"<div class='card'>{_chead('building', 'Клиника', '', '<a href=' + chr(39) + '#profile' + chr(39) + '>Изменить реквизиты</a>')}"
                f"<div class='kv'>"
                f"<div><label>Контакт</label><div class='v'>{esc(c['contact_name'] or '—')}</div></div>"
                f"<div><label>Телефон</label><div class='v'>{esc(c['phone'] or '—')}</div></div>"
                f"<div><label>E-mail</label><div class='v'>{esc(c['email'] or '—')}{_email_tag(c)}</div></div>"
                f"<div><label>Адрес</label><div class='v'>{esc(c['address'] or '—')}</div></div>"
                f"<div><label>IDNO</label><div class='v mono'>{esc(c['idno'] or '—')}</div></div>"
                f"<div><label>Идентификатор</label><div class='v mono'>{cid}</div></div>"
                f"</div></div>")
    overview = (todo_html + _clinic_tiles(c, sub, st, issues, devices, accounts, smsinfo, now,
                                          cabinet=[c, *cabinet], active=active)
                + (_cabinet_card(c, list(cabinet), accounts) if cabinet or accounts else "") + contacts)
    edit = (f"<div class='card'>{_chead('building', 'Реквизиты', 'название, IDNO и контакты: на них уходят ноты и письма')}"
            f"<form method='post' action='/admin/clinics/{cid}/edit'><div class='grid'>"
            f"<div><label>Название *</label><input name='name' value='{esc(c['name'])}' required></div>"
            f"<div><label>IDNO</label><input name='idno' value='{esc(c['idno'])}' maxlength='13'></div>"
            f"<div><label>Контакт</label><input name='contact_name' value='{esc(c['contact_name'])}'></div>"
            f"<div><label>E-mail</label><input name='email' value='{esc(c['email'])}'></div>"
            f"<div><label>Телефон</label><input name='phone' value='{esc(c['phone'])}'></div>"
            f"<div><label>Адрес</label><input name='address' value='{esc(c['address'])}'></div></div>"
            f"<p style='margin:14px 0 0'><button class='primary'>Сохранить</button></p></form></div>")
    acc_rows = "".join(
        f"<tr><td>{esc(a['email'])}</td><td>{esc(a['provider'] if 'provider' in a.keys() else 'google')}</td>"
        f"<td>{esc(a['name'] or '—')}</td><td>{esc((a['created_at'] or '')[:10])}</td>"
        f"<td>{esc((a['last_login_at'] or '')[:16].replace('T', ' '))}</td>"
        f"<td><form method='post' action='/admin/accounts/{esc(a['id'])}/detach' style='margin:0'>"
        f"<button title='Запись удаляется; следующий вход этого аккаунта начнётся с регистрации'>"
        f"Отвязать</button></form></td></tr>" for a in accounts)
    acc_html = (f"<div class='card'>{_chead('user', 'Кабинет клиники', f'кто входит в кабинет {esc(config.BASE_URL.rstrip(chr(47)))}/cont — через Google или кодом на e-mail')}"
                f"<p class='muted' style='margin:0 0 10px'>Сменился директор: новый e-mail — во вкладке «Реквизиты», "
                f"старую запись — «Отвязать»; новый вход привяжется к клинике по ящику.</p>"
                f"<table><tr><th>E-mail</th><th>Вход</th><th>Имя</th><th>С</th><th>Последний вход</th><th></th></tr>"
                f"{acc_rows or '<tr><td colspan=6 class=muted>В кабинет ещё никто не входил</td></tr>'}</table></div>")
    dev_html = (f"<div class='card'>{_chead('monitor', 'Компьютеры', 'как программа этой клиники назвалась серверу')}"
                f"<table><tr><th>Компьютер</th><th>Версия</th><th>Канал</th>"
                f"<th>Windows</th><th>С</th><th>Последняя связь (UTC)</th><th>Файл у программы</th></tr>"
                f"{_device_rows(devices) or '<tr><td colspan=7 class=muted>Программа этой клиники ещё не выходила на связь</td></tr>'}"
                f"</table></div>")
    if log_counts is None:
        log_counts = {}
        for a in audit:
            log_counts[a["what"]] = log_counts.get(a["what"], 0) + 1
    count = {"overview": len(todo), "pay": sum(1 for p in payments if p["status"] == "pending"),
             "sms": 1 if smsinfo and smsinfo["sender_state"] in ("requested", "submitted") else 0}
    panes = {"overview": overview, "pay": _pay_pane(c, sub, st, payments, list(reminders), now),
             "lic": _lic_pane(c, issues, devices) + terms_html + documents_block(c, list(docs)),
             "sms": sms_block(c, smsinfo, _module_word(sub, now)), "access": dev_html + acc_html,
             "profile": edit, "log": _log_pane(cid, audit, log, log_counts)}
    body = _tabbed([(k, t, panes[k], count.get(k, 0)) for k, t in CLINIC_TABS])
    plan_txt = (esc(sub["plan"]) + ("" if sub["plan"] == "trial" else " · " + esc(tiers.NAME[tiers.current(sub)]))
                if sub else "без файла")
    lead = f"{_tag(st)} <span class='muted'>{plan_txt} · срок до {_d(sub['valid_until']) if sub else '—'} · IDNO {esc(c['idno'] or '—')}</span>"
    return page(c["name"], body, user, msg, pending=pending, active="clinics", lead=lead, names=names)


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
                         "la prima pornire introduceți aceleași date, iar programul se activează cu codul pe "
                         "care îl trimitem pe e-mailul clinicii.",
    "registered_requested": "Clinica a fost înregistrată. Cererea de probă a fost primită — vă răspundem pe "
                            "e-mail în cel mult o zi lucrătoare.",
    "duplicate": "O clinică cu acest IDNO este deja înregistrată la DentPilot, dar codul de conectare nu a "
                 "putut fi trimis pe e-mailul ei. Am notat cererea și vă răspundem pe e-mail.",
    "linked": "Contul Google a fost conectat la clinică.",
    "saved": "Datele clinicii au fost salvate.",
    "idno_taken": "Acest IDNO este deja înregistrat la altă clinică — scrieți-ne.",
    "note_created": "Nota de plată a fost creată: datele pentru plată sunt mai jos și pe e-mail.",
    "note_exists": "Aveți deja o notă de plată în așteptare — datele pentru plată sunt mai jos.",
    "note_replaced": "Nota de plată a fost înlocuită: datele noii note sunt mai jos și pe e-mail — nota veche nu "
                     "se mai plătește.",
    "need_terms": "Pentru plată bifați „Am citit și accept Termenii și condițiile”.",
    "card_paid": "Banca a confirmat deja plata cu cardul: termenul se prelungește automat, iar confirmarea vine "
                 "pe e-mail.",
    "note_gone": "Această notă de plată nu mai așteaptă plata — reîncărcați pagina.",
    "no_card": "Plata cu cardul nu este disponibilă acum — plătiți prin transfer bancar, cu referința din notă.",
    "tier_not_sold": "Varianta aleasă nu se poate plăti acum online — alegeți cealaltă variantă sau scrieți-ne.",
    "need_idno": "Pentru abonament completați mai întâi IDNO-ul clinicii (13 cifre), în datele clinicii.",
    "maib_failed": "Pagina de plată cu cardul nu a putut fi creată acum — încercați din nou sau alegeți "
                   "transferul bancar.",
    "bad_months": "Alegeți o lună sau un an.",
    "closed": "Cererea clinicii a fost închisă — scrieți-ne.",
    # вход кодом на e-mail (02.10)
    "bad_email": "Introduceți o adresă de e-mail validă.",
    "login_limited": "Prea multe coduri cerute — încercați peste o oră sau scrieți-ne.",
    # страница оплаты из программы (02.10)
    "pay_need_idno": "Pentru abonament indicați IDNO-ul clinicii (13 cifre) — îl puteți completa chiar aici.",
    "idno_locked": "IDNO-ul clinicii este deja înregistrat și nu se schimbă de aici — îl puteți modifica în "
                   "contul clinicii.",
    "mail_failed": "Nu am putut trimite e-mailul cu codul — încercați din nou peste un minut sau scrieți-ne.",
    # SMS › numele expeditorului și cererea (17.10, sms_paper.py)
    "sms_requested": "Cererea pentru numele expeditorului a fost înregistrată. Descărcați cererea completată, "
                     "semnați-o și încărcați-o mai jos.",
    "sms_name": "Numele expeditorului: până la 11 caractere — litere latine, cifre, spațiu, punct sau cratimă, "
                "cel puțin o literă.",
    "sms_name_taken": "Acest nume de expeditor este deja folosit sau cerut de altă clinică — alegeți alt nume.",
    "sms_not_offered": "Modulul SMS nu este disponibil acum pentru clinica dvs.",
    "sms_paper_state": "Cererea se descarcă și se încarcă doar pentru un nume cerut și încă nedepus la SMS.MD.",
    "sms_paper_data": "Pentru cerere completați mai întâi datele clinicii: IDNO, adresa, telefonul.",
    "sms_paper_rep": "Scrieți numele și prenumele reprezentantului legal care semnează cererea.",
    "sms_paper_ok": "Cererea semnată a fost primită. O depunem la SMS.MD; aprobarea durează 1–2 zile lucrătoare.",
    "sms_paper_big": "Fișierul este prea mare: cererea semnată se încarcă PDF, până la 5 MB.",
    "sms_paper_pdf": "Fișierul nu este PDF. Încărcați cererea semnată ca PDF (scanată sau semnată electronic).",
    "sms_paper_empty": "Alegeți fișierul PDF al cererii semnate.",
    # clinicile contului (26.10, filiale)
    "clinic_added": "Clinica a fost adăugată în cont și licența ei este activă. Instalați programul cu codul de mai "
                    "jos; nota de plată pentru prima perioadă este în contul clinicii și pe e-mailul ei.",
    "clinic_added_wait": "Clinica a fost adăugată în cont, iar nota de plată pentru prima perioadă este gata. "
                         "Licența o activăm noi, de obicei în aceeași zi lucrătoare; între timp puteți instala "
                         "programul cu codul de mai jos.",
    "add_unpaid": "Achitați mai întâi nota clinicii {name} ({ref}), apoi puteți adăuga o clinică nouă.",
    "add_need_idno": "Indicați IDNO-ul clinicii noi (13 cifre) — fără el nu se emite licența abonamentului. Poate fi "
                     "același ca la celelalte clinici din cont.",
    "need_address": "Indicați adresa clinicii — după ea deosebiți clinicile în listă.",
    "clinics_max": "În cont sunt deja prea multe clinici — scrieți-ne.",
    "add_duplicate": "O clinică cu acest IDNO sau e-mail este deja înregistrată la DentPilot și nu este în contul "
                     "dvs. — scrieți-ne.",
    "pick_clinic": "Pagina era deschisă pentru altă clinică — reîncărcați pagina și încercați din nou.",
    "code_limit": "Prea multe coduri cerute pentru această clinică — încercați peste o oră.",
    "in_group": "Abonamentul acestei clinici este în nota comună — plătiți nota comună sau anulați-o, apoi faceți "
                "o notă separată.",
    "group_created": "Nota comună a fost creată: datele pentru plată sunt mai jos și pe e-mail.",
    "group_replaced": "Nota comună a fost creată și înlocuiește notele în așteptare ale clinicilor incluse — pe "
                      "acelea nu le mai plătiți.",
    "group_cancelled": "Nota comună a fost anulată — clinicile se pot plăti separat sau într-o notă comună nouă.",
    "group_empty": "Alegeți varianta pentru cel puțin o clinică.",
    "group_too_many": f"Într-o notă comună intră cel mult {pay.GROUP_MAX} clinici.",
    "need_idno_payer": "Pentru nota comună completați IDNO-ul primei clinici din notă (13 cifre): ea apare ca "
                       "beneficiar în contul de plată.",
    "group_gone": "Nota comună nu mai așteaptă plata — reîncărcați pagina.",
    # intrarea din program (27.10, contlink.py): doar clinica acestui program
    "cont_program_only": "Ați intrat din programul clinicii: vedeți doar această clinică. Celelalte clinici ale "
                         "contului, nota comună și adăugarea unei clinici — după intrarea cu Google sau cu codul "
                         "pe e-mail.",
    # documente (29.10, contracts.py)
    "doc_ok": "Exemplarul semnat de clinică a fost primit și păstrat în contul clinicii.",
    "doc_kind": "Alegeți documentul: contractul de licență sau acordul de prelucrare a datelor.",
    "doc_empty": "Alegeți fișierul PDF al exemplarului semnat.",
    "doc_pdf": "Fișierul nu este PDF. Încărcați exemplarul semnat ca PDF (semnat electronic sau scanat).",
    "doc_big": f"Fișierul este prea mare: exemplarul semnat se încarcă PDF, până la {contracts.MAX_BYTES // (1024 * 1024)} MB.",
    "doc_missing": "Acest document nu este încă publicat de furnizor — reveniți mai târziu sau scrieți-ne.",
}
_CONT_OK = {"logged_out", "registered_issued", "registered_requested", "saved", "note_created", "note_exists",
            "note_replaced", "card_paid", "clinic_added", "clinic_added_wait", "group_created",
            "group_replaced", "group_cancelled",
            "linked", "sms_requested", "sms_paper_ok", "doc_ok"}
SENDER_RO = {"none": ("mute", "fără nume propriu"), "requested": ("warn", "cerere în lucru"),
             "submitted": ("warn", "la operatori"), "active": ("ok", "aprobat"), "rejected": ("bad", "respins")}
STATE_RO = {"active": ("ok", "activă"), "grace": ("warn", "expirată — perioada de plată"),
            "readonly": ("bad", "regim de citire"), "none": ("mute", "neactivată")}
# срок на оплату первой ноты клиники из кабинета (payments.ADVANCE): активна, но не оплачена
ADVANCE_TAG = ("warn", "nota de plată")
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
.logo .ic{width:42px;display:inline-flex;flex:none}.logo .ic svg{width:42px;height:auto;display:block}.logo .wm{font-weight:800;letter-spacing:-.03em;color:var(--teal)}.logo .wm .d{color:#1E3A8A}
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
.tscroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
pre.pay{background:var(--bg);border:1px solid var(--line);border-radius:14px;padding:16px 18px;font:inherit;font-size:14.5px;white-space:pre-wrap;margin:12px 0;line-height:1.55}
.price{display:inline-flex;gap:6px;align-items:baseline;background:var(--teal-soft);color:var(--teal-d);border-radius:10px;padding:6px 12px;font-size:13.5px;font-weight:600;white-space:nowrap}
.steps{margin:0 0 16px;padding:0 0 0 22px;color:var(--muted);font-size:14px;line-height:1.5}.steps li{margin:0 0 6px}.steps b{color:var(--ink)}
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
.auth .brand .mark{width:64px;display:inline-flex;color:#fff}.auth .brand .mark svg{width:64px;height:auto;display:block}
.auth .brand h2{font-size:clamp(24px,3vw,30px);margin:0;letter-spacing:-.02em;line-height:1.15}
.auth .brand p{margin:0;color:rgba(255,255,255,.85);font-size:15px;line-height:1.55}
.auth .brand .perks li{color:#fff}.auth .brand .perks svg path{stroke:#fff}
.auth .brand .fine{margin-top:auto;font-size:13px;color:rgba(255,255,255,.72);line-height:1.5}
.auth .form{padding:40px 36px}
.auth .form h2{margin:0 0 6px;font-size:22px;letter-spacing:-.015em}
.or{display:flex;align-items:center;gap:12px;color:var(--muted);font-size:13px;margin:4px 0 14px}
.or:before,.or:after{content:'';flex:1;height:1px;background:var(--line)}
/* выбор варианта абонемента (23.10): карточки Basic / Plus, срок, сумма, галочка условий */
.tiers{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px;margin:4px 0 18px}
label.tier{position:relative;display:flex;flex-direction:column;gap:6px;border:1.5px solid #D8E2DF;border-radius:16px;padding:16px 18px;margin:0;cursor:pointer;background:#fff;color:var(--ink);font-size:14.5px;font-weight:400}
label.tier:has(input:checked){border-color:var(--teal);box-shadow:0 0 0 3px rgba(14,159,138,.14);background:linear-gradient(180deg,#F2FBF8,#fff 60%)}
label.tier input{position:absolute;top:16px;right:16px;width:18px;height:18px;margin:0;accent-color:var(--teal)}
.tier .nm{font-weight:700;font-size:17px;letter-spacing:-.01em;padding-right:26px}.tier .what{font-size:13px;color:var(--muted);margin-top:-4px}
.tier .pr{font-size:28px;font-weight:800;letter-spacing:-.02em;line-height:1.1;margin-top:6px}.tier .pr small{font-size:14px;font-weight:600;color:var(--muted)}
.tier .yr{font-size:13px;color:var(--muted)}
.tier ul{list-style:none;padding:0;margin:8px 0 0}.tier li{display:flex;gap:8px;align-items:flex-start;margin:0 0 6px;font-size:14px;line-height:1.4}
.tier li svg{flex:none;margin-top:1px}.tier li.no{color:var(--muted)}.tier .fine{font-size:12.5px;color:var(--muted);margin-top:auto;padding-top:6px}
.seg{display:inline-flex;background:#EEF2F1;border-radius:12px;padding:4px;gap:4px;flex-wrap:wrap}
.seg label{margin:0;padding:8px 14px;border-radius:9px;cursor:pointer;font-size:14.5px;color:var(--ink);font-weight:600;display:flex;gap:8px;align-items:center}
.seg label input{width:auto;margin:0;accent-color:var(--teal)}.seg label:has(input:checked){background:#fff;box-shadow:0 1px 2px rgba(11,43,38,.12)}
.gift{font-weight:600;font-size:12px;color:var(--teal-d);background:var(--teal-soft);border-radius:999px;padding:2px 8px}
.total{display:flex;align-items:baseline;justify-content:space-between;gap:12px;flex-wrap:wrap;background:var(--bg);border:1px solid var(--line);border-radius:14px;padding:14px 16px;margin:16px 0 4px}
.total .t{font-size:14px;color:var(--muted)}.total .t b{color:var(--ink)}.total .s{font-size:22px;font-weight:800;letter-spacing:-.02em}
.note{font-size:13px;color:var(--muted);line-height:1.5;margin:10px 0 0}.terms{border-top:1px solid var(--line);margin-top:18px;padding-top:6px}
.btns{margin:14px 0 0;display:flex;gap:10px;flex-wrap:wrap}.lbl{display:block;font-size:13px;color:var(--muted);margin:16px 0 8px;font-weight:500}
details.more summary{cursor:pointer;color:var(--teal-d);font-size:14px;font-weight:600}details.more{margin:16px 0 0}
.ok-list{display:grid;grid-template-columns:auto 1fr;gap:6px 16px;font-size:14.5px;margin:14px 0}.ok-list dt{color:var(--muted)}.ok-list dd{margin:0;font-weight:600}.ok-list dd.plain{font-weight:400}
/* clinicile contului (26.10, filiale): rând = clinică, cea deschisă — cu bara turcoaz */
.clist{border:1px solid var(--line);border-radius:14px;overflow:hidden}
.crow{display:grid;grid-template-columns:minmax(0,1fr) 190px 200px 100px 236px;gap:14px;align-items:center;padding:14px 16px;border-top:1px solid #EEF2F1;background:#fff}
.crow:first-child{border-top:0}
.crow.on{background:linear-gradient(90deg,#F2FBF8,#fff 70%);box-shadow:inset 3px 0 0 var(--teal)}
.crow .nm{font-weight:700;font-size:15px;color:var(--ink);text-decoration:none}.crow a.nm:hover{color:var(--teal-d)}
.crow .ad{display:block;font-size:13px;color:var(--muted);margin-top:2px}
.crow .k{display:block;font-size:11.5px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;font-weight:600;margin:0 0 2px}
.crow .v{font-size:14px;line-height:1.4}.crow .v .tag{margin-left:4px}
.crow .act{display:flex;gap:8px;justify-content:flex-end;flex-wrap:wrap}.crow .act form{margin:0}
.crow .here{font-size:12.5px;font-weight:600;color:var(--teal-d);background:var(--teal-soft);border-radius:999px;padding:4px 10px;white-space:nowrap}
a.btn.sm,button.sm{padding:8px 14px;font-size:14px;border-radius:9px}
.addline{display:flex;gap:14px;align-items:center;justify-content:space-between;flex-wrap:wrap;border-top:1px solid var(--line);margin-top:16px;padding-top:14px}
.addline p{margin:0;font-size:14px;color:var(--muted);line-height:1.5;max-width:38em}.addline b{color:var(--ink)}
.code{display:flex;gap:8px;justify-content:center;margin:20px 0 8px}
.code span{width:52px;height:64px;border:1.5px solid var(--teal);border-radius:12px;display:inline-flex;align-items:center;justify-content:center;font:700 32px/1 ui-monospace,Consolas,monospace;color:var(--ink);background:#F2FBF8}
.code-sub{text-align:center;font-size:14px;color:var(--muted);margin:0 0 18px}
.warnbox{background:#FFFBEB;border:1px solid #FDE68A;color:#78350F;border-radius:12px;padding:12px 14px;font-size:14px;line-height:1.5;margin:16px 0 0}
.hint{font-size:13px;color:var(--muted);margin:4px 0 0}
.side-code{margin:0}.side-code button{width:100%;background:transparent;color:#fff;border-color:rgba(255,255,255,.55);font-weight:600}
.side-code button:hover{background:rgba(255,255,255,.12);border-color:#fff}
.gsel{width:100%;font-size:14px;padding:9px 10px}
@media (max-width:720px){.crow{grid-template-columns:1fr 1fr;gap:10px 14px}.crow .who{grid-column:1/-1}.crow .act{grid-column:1/-1;justify-content:stretch}.crow .act>*{flex:1}.crow .act a.btn,.crow .act button{width:100%}.code{gap:5px}.code span{width:40px;height:52px;font-size:26px}}
@media (max-width:900px){.hero{grid-template-columns:1fr}.grid2{grid-template-columns:1fr}.split{grid-template-columns:1fr}.auth{grid-template-columns:1fr}.auth .brand{padding:28px 22px}.auth .form{padding:26px 22px}}
/* вкладки кабинета (29.10, вариант 1 Олега): полоса под заголовком, метка адреса, без перезагрузки */
.ctabs{display:flex;gap:2px;border-bottom:1px solid var(--line);margin:0 0 20px;overflow-x:auto;overflow-y:hidden;scrollbar-width:none}
.ctabs a{display:inline-flex;align-items:center;gap:8px;padding:11px 16px;margin-bottom:-1px;border-bottom:2px solid transparent;color:var(--muted);text-decoration:none;font-weight:600;font-size:14.5px;white-space:nowrap}
.ctabs a svg{opacity:.75}.ctabs a:hover{color:var(--ink)}.ctabs a.on{color:var(--teal-d);border-bottom-color:var(--teal)}.ctabs a.on svg{opacity:1}
.ctabs .n{min-width:20px;height:20px;padding:0 6px;border-radius:999px;background:#FFF3D6;color:#B45309;font-size:12px;display:inline-flex;align-items:center;justify-content:center}
.tabbed:not(.js) .ctabs{display:none}.tabbed.js .pane{display:none}.tabbed.js .pane.on{display:block}
.pane>.card:last-child,.pane>.grid2:last-child{margin-bottom:0}
/* клиники кабинета под заголовком: чипы, на телефоне — список */
.cpick{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:-6px 0 18px}
.cpick a{display:inline-flex;align-items:center;gap:8px;padding:7px 12px 7px 10px;border-radius:999px;border:1px solid #D8E2DF;background:#fff;color:var(--ink);text-decoration:none;font-size:14px;font-weight:600}
.cpick a .tag{font-size:11.5px;padding:2px 8px}.cpick a.on{border-color:var(--teal);background:var(--teal-soft);color:var(--teal-d)}
.cpick a.add{color:var(--teal-d);border-style:dashed}.cpick .k{font-size:13px;color:var(--muted);margin-right:4px}
.cpick-sel{display:none;margin:-6px 0 18px}
@media (max-width:720px){.ctabs{margin:0 -16px 18px;padding:0 16px}.ctabs a{padding:10px 12px;font-size:14px}.cpick{display:none}.cpick-sel{display:block}}
@media (max-width:720px){.seg{display:grid;grid-template-columns:1fr}.seg label{padding:10px 12px}.total .s{font-size:20px}.chead .right{margin-left:0;flex-basis:100%}.price{white-space:normal}.wrap{padding:22px 16px 48px}.top-in{padding:0 16px;height:60px}.logo .sub{display:none}.acc .em{display:none}.card{padding:18px 16px;border-radius:16px}.hero .main{padding:20px 18px}.hero .side{padding:20px 18px}button.primary,a.btn,a.gbtn{width:100%}}
"""
# Знак DentPilot v2 (05.10.2026): зуб с лентой и стрелкой-«пилотом». ⛔ Облако
# не импортирует bot/, поэтому знак здесь — готовыми SVG-строками, снятыми с
# app/bot/app/brand.py (mark_svg(flat=True), mark_svg(46), color_mark_svg).
# Меняется знак там — пересобрать строки здесь, иначе кабинет снова покажет
# старый значок (05.10: так и было — сайт и программа уже новые, кабинет нет).
# ⚠️ id масок и градиентов внутри уникальны на странице: приставка — своя у
# каждого места (_mark).
_MARK_WHITE = '<svg class="x" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="DentPilot" viewBox="0 0 284 220"><defs><mask id="dpxk" maskUnits="userSpaceOnUse" x="0" y="0" width="284" height="220"><rect width="284" height="220" fill="#fff"/><path d="M4.0 160.0 L6.6 160.0 L9.1 159.9 L11.7 159.7 L14.3 159.5 L16.9 159.3 L19.5 159.0 L22.2 158.8 L24.8 158.5 L27.5 158.1 L30.1 157.8 L32.8 157.4 L35.5 157.1 L38.1 156.6 L40.8 156.2 L43.5 155.8 L46.3 155.3 L49.0 154.8 L51.7 154.3 L54.4 153.8 L57.2 153.2 L59.9 152.7 L62.6 152.1 L65.4 151.5 L68.2 150.9 L70.9 150.2 L73.7 149.6 L76.5 148.9 L79.2 148.2 L82.0 147.4 L84.8 146.7 L87.6 145.9 L90.4 145.2 L93.2 144.4 L95.9 143.6 L98.7 142.7 L101.5 141.9 L104.3 141.0 L107.1 140.1 L109.9 139.2 L112.7 138.3 L115.5 137.3 L118.3 136.4 L121.1 135.4 L123.9 134.4 L126.6 133.4 L129.4 132.4 L132.2 131.3 L135.0 130.2 L137.8 129.2 L140.5 128.1 L143.3 126.9 L146.1 125.8 L148.8 124.6 L151.6 123.5 L154.3 122.3 L157.1 121.1 L159.8 119.8 L162.5 118.6 L165.3 117.3 L168.0 116.1 L170.7 114.8 L173.4 113.4 L176.1 112.1 L178.8 110.8 L181.4 109.4 L184.1 108.0 L186.8 106.6 L189.4 105.2 L192.1 103.8 L194.7 102.3 L197.3 100.9 L199.9 99.4 L202.5 97.9 L205.1 96.4 L207.7 94.8 L210.2 93.3 L212.8 91.7 L215.3 90.1 L217.8 88.5 L220.4 86.9 L222.9 85.3 L225.3 83.7 L227.8 82.0 L230.3 80.3 L232.7 78.6 L235.1 76.9 L237.5 75.2 L239.9 73.4 L242.3 71.7 L244.7 69.9 L235.3 58.1 L233.1 59.9 L230.9 61.7 L228.7 63.5 L226.5 65.3 L224.2 67.0 L221.9 68.8 L219.6 70.5 L217.3 72.2 L215.0 73.9 L212.6 75.6 L210.3 77.2 L207.9 78.9 L205.5 80.5 L203.1 82.2 L200.7 83.8 L198.3 85.4 L195.8 86.9 L193.4 88.5 L190.9 90.1 L188.4 91.6 L185.9 93.1 L183.4 94.6 L180.9 96.1 L178.4 97.6 L175.8 99.1 L173.3 100.5 L170.7 102.0 L168.2 103.4 L165.6 104.8 L163.0 106.2 L160.4 107.5 L157.8 108.9 L155.2 110.2 L152.6 111.6 L149.9 112.9 L147.3 114.2 L144.7 115.4 L142.0 116.7 L139.4 118.0 L136.7 119.2 L134.1 120.4 L131.4 121.6 L128.7 122.8 L126.0 124.0 L123.4 125.1 L120.7 126.2 L118.0 127.4 L115.3 128.5 L112.6 129.5 L109.9 130.6 L107.2 131.7 L104.5 132.7 L101.8 133.7 L99.1 134.7 L96.4 135.7 L93.7 136.7 L91.0 137.6 L88.3 138.6 L85.6 139.5 L82.9 140.4 L80.2 141.3 L77.5 142.2 L74.8 143.0 L72.1 143.9 L69.4 144.7 L66.7 145.5 L64.1 146.3 L61.4 147.0 L58.7 147.8 L56.0 148.5 L53.4 149.2 L50.7 149.9 L48.1 150.6 L45.4 151.3 L42.8 151.9 L40.1 152.6 L37.5 153.2 L34.9 153.8 L32.2 154.4 L29.6 155.0 L27.0 155.5 L24.4 156.0 L21.8 156.6 L19.3 157.1 L16.7 157.6 L14.1 158.1 L11.6 158.5 L9.0 159.0 L6.5 159.5 L4.0 160.0Z" fill="#000" stroke="#000" stroke-width="14.0" stroke-linejoin="round"/></mask></defs><g mask="url(#dpxk)"><path d="M8.2 3.8C5.9 3.8 4 5.7 4 8.2c0 1.9.8 3.2 1.4 4.7.7 1.7 1 4.4 1.8 6.6.3.9 1.5.9 1.8 0 .6-1.9.8-4 1.6-5.2.6-.9 1.7-.9 2.3 0 .8 1.2 1 3.3 1.6 5.2.3.9 1.5.9 1.8 0 .8-2.2 1.1-4.9 1.8-6.6.6-1.5 1.4-2.8 1.4-4.7 0-2.5-1.9-4.4-4.2-4.4-1.1 0-1.9.5-3.1.5s-2-.5-3.2-.5z" transform="translate(4.0 6.0) scale(9.6)" fill="none" stroke="currentColor" stroke-width="2.25" stroke-linecap="round" stroke-linejoin="round"/></g><path d="M4.0 160.0 L6.6 160.0 L9.1 159.9 L11.7 159.7 L14.3 159.5 L16.9 159.3 L19.5 159.0 L22.2 158.8 L24.8 158.5 L27.5 158.1 L30.1 157.8 L32.8 157.4 L35.5 157.1 L38.1 156.6 L40.8 156.2 L43.5 155.8 L46.3 155.3 L49.0 154.8 L51.7 154.3 L54.4 153.8 L57.2 153.2 L59.9 152.7 L62.6 152.1 L65.4 151.5 L68.2 150.9 L70.9 150.2 L73.7 149.6 L76.5 148.9 L79.2 148.2 L82.0 147.4 L84.8 146.7 L87.6 145.9 L90.4 145.2 L93.2 144.4 L95.9 143.6 L98.7 142.7 L101.5 141.9 L104.3 141.0 L107.1 140.1 L109.9 139.2 L112.7 138.3 L115.5 137.3 L118.3 136.4 L121.1 135.4 L123.9 134.4 L126.6 133.4 L129.4 132.4 L132.2 131.3 L135.0 130.2 L137.8 129.2 L140.5 128.1 L143.3 126.9 L146.1 125.8 L148.8 124.6 L151.6 123.5 L154.3 122.3 L157.1 121.1 L159.8 119.8 L162.5 118.6 L165.3 117.3 L168.0 116.1 L170.7 114.8 L173.4 113.4 L176.1 112.1 L178.8 110.8 L181.4 109.4 L184.1 108.0 L186.8 106.6 L189.4 105.2 L192.1 103.8 L194.7 102.3 L197.3 100.9 L199.9 99.4 L202.5 97.9 L205.1 96.4 L207.7 94.8 L210.2 93.3 L212.8 91.7 L215.3 90.1 L217.8 88.5 L220.4 86.9 L222.9 85.3 L225.3 83.7 L227.8 82.0 L230.3 80.3 L232.7 78.6 L235.1 76.9 L237.5 75.2 L239.9 73.4 L242.3 71.7 L244.7 69.9 L235.3 58.1 L233.1 59.9 L230.9 61.7 L228.7 63.5 L226.5 65.3 L224.2 67.0 L221.9 68.8 L219.6 70.5 L217.3 72.2 L215.0 73.9 L212.6 75.6 L210.3 77.2 L207.9 78.9 L205.5 80.5 L203.1 82.2 L200.7 83.8 L198.3 85.4 L195.8 86.9 L193.4 88.5 L190.9 90.1 L188.4 91.6 L185.9 93.1 L183.4 94.6 L180.9 96.1 L178.4 97.6 L175.8 99.1 L173.3 100.5 L170.7 102.0 L168.2 103.4 L165.6 104.8 L163.0 106.2 L160.4 107.5 L157.8 108.9 L155.2 110.2 L152.6 111.6 L149.9 112.9 L147.3 114.2 L144.7 115.4 L142.0 116.7 L139.4 118.0 L136.7 119.2 L134.1 120.4 L131.4 121.6 L128.7 122.8 L126.0 124.0 L123.4 125.1 L120.7 126.2 L118.0 127.4 L115.3 128.5 L112.6 129.5 L109.9 130.6 L107.2 131.7 L104.5 132.7 L101.8 133.7 L99.1 134.7 L96.4 135.7 L93.7 136.7 L91.0 137.6 L88.3 138.6 L85.6 139.5 L82.9 140.4 L80.2 141.3 L77.5 142.2 L74.8 143.0 L72.1 143.9 L69.4 144.7 L66.7 145.5 L64.1 146.3 L61.4 147.0 L58.7 147.8 L56.0 148.5 L53.4 149.2 L50.7 149.9 L48.1 150.6 L45.4 151.3 L42.8 151.9 L40.1 152.6 L37.5 153.2 L34.9 153.8 L32.2 154.4 L29.6 155.0 L27.0 155.5 L24.4 156.0 L21.8 156.6 L19.3 157.1 L16.7 157.6 L14.1 158.1 L11.6 158.5 L9.0 159.0 L6.5 159.5 L4.0 160.0Z" fill="currentColor"/><path d="M210.7 52.8 L272.9 37.9 L244.3 95.1 L240.0 64.0Z" fill="currentColor"/></svg>'
_MARK_ICON = '<svg class="y" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="DentPilot" viewBox="0 0 256 256" width="46" height="46"><defs><linearGradient id="dpyp" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#14B8A3"/><stop offset="1" stop-color="#0A7C80"/></linearGradient></defs><rect width="256" height="256" rx="68" fill="url(#dpyp)"/><g transform="translate(32.5 44.4) scale(0.6901)"><defs><mask id="dpyk" maskUnits="userSpaceOnUse" x="0" y="0" width="284" height="220"><rect width="284" height="220" fill="#fff"/><path d="M4.0 160.0 L6.6 160.0 L9.1 159.9 L11.7 159.7 L14.3 159.5 L16.9 159.3 L19.5 159.0 L22.2 158.8 L24.8 158.5 L27.5 158.1 L30.1 157.8 L32.8 157.4 L35.5 157.1 L38.1 156.6 L40.8 156.2 L43.5 155.8 L46.3 155.3 L49.0 154.8 L51.7 154.3 L54.4 153.8 L57.2 153.2 L59.9 152.7 L62.6 152.1 L65.4 151.5 L68.2 150.9 L70.9 150.2 L73.7 149.6 L76.5 148.9 L79.2 148.2 L82.0 147.4 L84.8 146.7 L87.6 145.9 L90.4 145.2 L93.2 144.4 L95.9 143.6 L98.7 142.7 L101.5 141.9 L104.3 141.0 L107.1 140.1 L109.9 139.2 L112.7 138.3 L115.5 137.3 L118.3 136.4 L121.1 135.4 L123.9 134.4 L126.6 133.4 L129.4 132.4 L132.2 131.3 L135.0 130.2 L137.8 129.2 L140.5 128.1 L143.3 126.9 L146.1 125.8 L148.8 124.6 L151.6 123.5 L154.3 122.3 L157.1 121.1 L159.8 119.8 L162.5 118.6 L165.3 117.3 L168.0 116.1 L170.7 114.8 L173.4 113.4 L176.1 112.1 L178.8 110.8 L181.4 109.4 L184.1 108.0 L186.8 106.6 L189.4 105.2 L192.1 103.8 L194.7 102.3 L197.3 100.9 L199.9 99.4 L202.5 97.9 L205.1 96.4 L207.7 94.8 L210.2 93.3 L212.8 91.7 L215.3 90.1 L217.8 88.5 L220.4 86.9 L222.9 85.3 L225.3 83.7 L227.8 82.0 L230.3 80.3 L232.7 78.6 L235.1 76.9 L237.5 75.2 L239.9 73.4 L242.3 71.7 L244.7 69.9 L235.3 58.1 L233.1 59.9 L230.9 61.7 L228.7 63.5 L226.5 65.3 L224.2 67.0 L221.9 68.8 L219.6 70.5 L217.3 72.2 L215.0 73.9 L212.6 75.6 L210.3 77.2 L207.9 78.9 L205.5 80.5 L203.1 82.2 L200.7 83.8 L198.3 85.4 L195.8 86.9 L193.4 88.5 L190.9 90.1 L188.4 91.6 L185.9 93.1 L183.4 94.6 L180.9 96.1 L178.4 97.6 L175.8 99.1 L173.3 100.5 L170.7 102.0 L168.2 103.4 L165.6 104.8 L163.0 106.2 L160.4 107.5 L157.8 108.9 L155.2 110.2 L152.6 111.6 L149.9 112.9 L147.3 114.2 L144.7 115.4 L142.0 116.7 L139.4 118.0 L136.7 119.2 L134.1 120.4 L131.4 121.6 L128.7 122.8 L126.0 124.0 L123.4 125.1 L120.7 126.2 L118.0 127.4 L115.3 128.5 L112.6 129.5 L109.9 130.6 L107.2 131.7 L104.5 132.7 L101.8 133.7 L99.1 134.7 L96.4 135.7 L93.7 136.7 L91.0 137.6 L88.3 138.6 L85.6 139.5 L82.9 140.4 L80.2 141.3 L77.5 142.2 L74.8 143.0 L72.1 143.9 L69.4 144.7 L66.7 145.5 L64.1 146.3 L61.4 147.0 L58.7 147.8 L56.0 148.5 L53.4 149.2 L50.7 149.9 L48.1 150.6 L45.4 151.3 L42.8 151.9 L40.1 152.6 L37.5 153.2 L34.9 153.8 L32.2 154.4 L29.6 155.0 L27.0 155.5 L24.4 156.0 L21.8 156.6 L19.3 157.1 L16.7 157.6 L14.1 158.1 L11.6 158.5 L9.0 159.0 L6.5 159.5 L4.0 160.0Z" fill="#000" stroke="#000" stroke-width="14.0" stroke-linejoin="round"/></mask></defs><g mask="url(#dpyk)"><path d="M8.2 3.8C5.9 3.8 4 5.7 4 8.2c0 1.9.8 3.2 1.4 4.7.7 1.7 1 4.4 1.8 6.6.3.9 1.5.9 1.8 0 .6-1.9.8-4 1.6-5.2.6-.9 1.7-.9 2.3 0 .8 1.2 1 3.3 1.6 5.2.3.9 1.5.9 1.8 0 .8-2.2 1.1-4.9 1.8-6.6.6-1.5 1.4-2.8 1.4-4.7 0-2.5-1.9-4.4-4.2-4.4-1.1 0-1.9.5-3.1.5s-2-.5-3.2-.5z" transform="translate(4.0 6.0) scale(9.6)" fill="none" stroke="#FFFFFF" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/></g><path d="M4.0 160.0 L6.6 160.0 L9.1 159.9 L11.7 159.7 L14.3 159.5 L16.9 159.3 L19.5 159.0 L22.2 158.8 L24.8 158.5 L27.5 158.1 L30.1 157.8 L32.8 157.4 L35.5 157.1 L38.1 156.6 L40.8 156.2 L43.5 155.8 L46.3 155.3 L49.0 154.8 L51.7 154.3 L54.4 153.8 L57.2 153.2 L59.9 152.7 L62.6 152.1 L65.4 151.5 L68.2 150.9 L70.9 150.2 L73.7 149.6 L76.5 148.9 L79.2 148.2 L82.0 147.4 L84.8 146.7 L87.6 145.9 L90.4 145.2 L93.2 144.4 L95.9 143.6 L98.7 142.7 L101.5 141.9 L104.3 141.0 L107.1 140.1 L109.9 139.2 L112.7 138.3 L115.5 137.3 L118.3 136.4 L121.1 135.4 L123.9 134.4 L126.6 133.4 L129.4 132.4 L132.2 131.3 L135.0 130.2 L137.8 129.2 L140.5 128.1 L143.3 126.9 L146.1 125.8 L148.8 124.6 L151.6 123.5 L154.3 122.3 L157.1 121.1 L159.8 119.8 L162.5 118.6 L165.3 117.3 L168.0 116.1 L170.7 114.8 L173.4 113.4 L176.1 112.1 L178.8 110.8 L181.4 109.4 L184.1 108.0 L186.8 106.6 L189.4 105.2 L192.1 103.8 L194.7 102.3 L197.3 100.9 L199.9 99.4 L202.5 97.9 L205.1 96.4 L207.7 94.8 L210.2 93.3 L212.8 91.7 L215.3 90.1 L217.8 88.5 L220.4 86.9 L222.9 85.3 L225.3 83.7 L227.8 82.0 L230.3 80.3 L232.7 78.6 L235.1 76.9 L237.5 75.2 L239.9 73.4 L242.3 71.7 L244.7 69.9 L235.3 58.1 L233.1 59.9 L230.9 61.7 L228.7 63.5 L226.5 65.3 L224.2 67.0 L221.9 68.8 L219.6 70.5 L217.3 72.2 L215.0 73.9 L212.6 75.6 L210.3 77.2 L207.9 78.9 L205.5 80.5 L203.1 82.2 L200.7 83.8 L198.3 85.4 L195.8 86.9 L193.4 88.5 L190.9 90.1 L188.4 91.6 L185.9 93.1 L183.4 94.6 L180.9 96.1 L178.4 97.6 L175.8 99.1 L173.3 100.5 L170.7 102.0 L168.2 103.4 L165.6 104.8 L163.0 106.2 L160.4 107.5 L157.8 108.9 L155.2 110.2 L152.6 111.6 L149.9 112.9 L147.3 114.2 L144.7 115.4 L142.0 116.7 L139.4 118.0 L136.7 119.2 L134.1 120.4 L131.4 121.6 L128.7 122.8 L126.0 124.0 L123.4 125.1 L120.7 126.2 L118.0 127.4 L115.3 128.5 L112.6 129.5 L109.9 130.6 L107.2 131.7 L104.5 132.7 L101.8 133.7 L99.1 134.7 L96.4 135.7 L93.7 136.7 L91.0 137.6 L88.3 138.6 L85.6 139.5 L82.9 140.4 L80.2 141.3 L77.5 142.2 L74.8 143.0 L72.1 143.9 L69.4 144.7 L66.7 145.5 L64.1 146.3 L61.4 147.0 L58.7 147.8 L56.0 148.5 L53.4 149.2 L50.7 149.9 L48.1 150.6 L45.4 151.3 L42.8 151.9 L40.1 152.6 L37.5 153.2 L34.9 153.8 L32.2 154.4 L29.6 155.0 L27.0 155.5 L24.4 156.0 L21.8 156.6 L19.3 157.1 L16.7 157.6 L14.1 158.1 L11.6 158.5 L9.0 159.0 L6.5 159.5 L4.0 160.0Z" fill="#FFFFFF"/><path d="M210.7 52.8 L272.9 37.9 L244.3 95.1 L240.0 64.0Z" fill="#FFFFFF"/></g></svg>'
_MARK_COLOR = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 284 220" role="img" aria-label="DentPilot"><defs><mask id="zk" maskUnits="userSpaceOnUse" x="0" y="0" width="284" height="220"><rect width="284" height="220" fill="#fff"/><path d="M4.0 160.0 L6.6 160.0 L9.1 159.9 L11.7 159.7 L14.3 159.5 L16.9 159.3 L19.5 159.0 L22.2 158.8 L24.8 158.5 L27.5 158.1 L30.1 157.8 L32.8 157.4 L35.5 157.1 L38.1 156.6 L40.8 156.2 L43.5 155.8 L46.3 155.3 L49.0 154.8 L51.7 154.3 L54.4 153.8 L57.2 153.2 L59.9 152.7 L62.6 152.1 L65.4 151.5 L68.2 150.9 L70.9 150.2 L73.7 149.6 L76.5 148.9 L79.2 148.2 L82.0 147.4 L84.8 146.7 L87.6 145.9 L90.4 145.2 L93.2 144.4 L95.9 143.6 L98.7 142.7 L101.5 141.9 L104.3 141.0 L107.1 140.1 L109.9 139.2 L112.7 138.3 L115.5 137.3 L118.3 136.4 L121.1 135.4 L123.9 134.4 L126.6 133.4 L129.4 132.4 L132.2 131.3 L135.0 130.2 L137.8 129.2 L140.5 128.1 L143.3 126.9 L146.1 125.8 L148.8 124.6 L151.6 123.5 L154.3 122.3 L157.1 121.1 L159.8 119.8 L162.5 118.6 L165.3 117.3 L168.0 116.1 L170.7 114.8 L173.4 113.4 L176.1 112.1 L178.8 110.8 L181.4 109.4 L184.1 108.0 L186.8 106.6 L189.4 105.2 L192.1 103.8 L194.7 102.3 L197.3 100.9 L199.9 99.4 L202.5 97.9 L205.1 96.4 L207.7 94.8 L210.2 93.3 L212.8 91.7 L215.3 90.1 L217.8 88.5 L220.4 86.9 L222.9 85.3 L225.3 83.7 L227.8 82.0 L230.3 80.3 L232.7 78.6 L235.1 76.9 L237.5 75.2 L239.9 73.4 L242.3 71.7 L244.7 69.9 L235.3 58.1 L233.1 59.9 L230.9 61.7 L228.7 63.5 L226.5 65.3 L224.2 67.0 L221.9 68.8 L219.6 70.5 L217.3 72.2 L215.0 73.9 L212.6 75.6 L210.3 77.2 L207.9 78.9 L205.5 80.5 L203.1 82.2 L200.7 83.8 L198.3 85.4 L195.8 86.9 L193.4 88.5 L190.9 90.1 L188.4 91.6 L185.9 93.1 L183.4 94.6 L180.9 96.1 L178.4 97.6 L175.8 99.1 L173.3 100.5 L170.7 102.0 L168.2 103.4 L165.6 104.8 L163.0 106.2 L160.4 107.5 L157.8 108.9 L155.2 110.2 L152.6 111.6 L149.9 112.9 L147.3 114.2 L144.7 115.4 L142.0 116.7 L139.4 118.0 L136.7 119.2 L134.1 120.4 L131.4 121.6 L128.7 122.8 L126.0 124.0 L123.4 125.1 L120.7 126.2 L118.0 127.4 L115.3 128.5 L112.6 129.5 L109.9 130.6 L107.2 131.7 L104.5 132.7 L101.8 133.7 L99.1 134.7 L96.4 135.7 L93.7 136.7 L91.0 137.6 L88.3 138.6 L85.6 139.5 L82.9 140.4 L80.2 141.3 L77.5 142.2 L74.8 143.0 L72.1 143.9 L69.4 144.7 L66.7 145.5 L64.1 146.3 L61.4 147.0 L58.7 147.8 L56.0 148.5 L53.4 149.2 L50.7 149.9 L48.1 150.6 L45.4 151.3 L42.8 151.9 L40.1 152.6 L37.5 153.2 L34.9 153.8 L32.2 154.4 L29.6 155.0 L27.0 155.5 L24.4 156.0 L21.8 156.6 L19.3 157.1 L16.7 157.6 L14.1 158.1 L11.6 158.5 L9.0 159.0 L6.5 159.5 L4.0 160.0Z" fill="#000" stroke="#000" stroke-width="14.0" stroke-linejoin="round"/></mask><linearGradient id="zt" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#2ED3BF"/><stop offset=".55" stop-color="#0E9F8A"/><stop offset="1" stop-color="#0A7480"/></linearGradient><linearGradient id="zs" gradientUnits="userSpaceOnUse" x1="4" y1="160" x2="272.9" y2="37.9"><stop offset="0" stop-color="#0A7480"/><stop offset=".6" stop-color="#0E9F8A"/><stop offset="1" stop-color="#2ED3BF"/></linearGradient></defs><g mask="url(#zk)"><path d="M8.2 3.8C5.9 3.8 4 5.7 4 8.2c0 1.9.8 3.2 1.4 4.7.7 1.7 1 4.4 1.8 6.6.3.9 1.5.9 1.8 0 .6-1.9.8-4 1.6-5.2.6-.9 1.7-.9 2.3 0 .8 1.2 1 3.3 1.6 5.2.3.9 1.5.9 1.8 0 .8-2.2 1.1-4.9 1.8-6.6.6-1.5 1.4-2.8 1.4-4.7 0-2.5-1.9-4.4-4.2-4.4-1.1 0-1.9.5-3.1.5s-2-.5-3.2-.5z" transform="translate(4.0 6.0) scale(9.6)" fill="none" stroke="url(#zt)" stroke-width="2.25" stroke-linecap="round" stroke-linejoin="round"/></g><path d="M4.0 160.0 L6.6 160.0 L9.1 159.9 L11.7 159.7 L14.3 159.5 L16.9 159.3 L19.5 159.0 L22.2 158.8 L24.8 158.5 L27.5 158.1 L30.1 157.8 L32.8 157.4 L35.5 157.1 L38.1 156.6 L40.8 156.2 L43.5 155.8 L46.3 155.3 L49.0 154.8 L51.7 154.3 L54.4 153.8 L57.2 153.2 L59.9 152.7 L62.6 152.1 L65.4 151.5 L68.2 150.9 L70.9 150.2 L73.7 149.6 L76.5 148.9 L79.2 148.2 L82.0 147.4 L84.8 146.7 L87.6 145.9 L90.4 145.2 L93.2 144.4 L95.9 143.6 L98.7 142.7 L101.5 141.9 L104.3 141.0 L107.1 140.1 L109.9 139.2 L112.7 138.3 L115.5 137.3 L118.3 136.4 L121.1 135.4 L123.9 134.4 L126.6 133.4 L129.4 132.4 L132.2 131.3 L135.0 130.2 L137.8 129.2 L140.5 128.1 L143.3 126.9 L146.1 125.8 L148.8 124.6 L151.6 123.5 L154.3 122.3 L157.1 121.1 L159.8 119.8 L162.5 118.6 L165.3 117.3 L168.0 116.1 L170.7 114.8 L173.4 113.4 L176.1 112.1 L178.8 110.8 L181.4 109.4 L184.1 108.0 L186.8 106.6 L189.4 105.2 L192.1 103.8 L194.7 102.3 L197.3 100.9 L199.9 99.4 L202.5 97.9 L205.1 96.4 L207.7 94.8 L210.2 93.3 L212.8 91.7 L215.3 90.1 L217.8 88.5 L220.4 86.9 L222.9 85.3 L225.3 83.7 L227.8 82.0 L230.3 80.3 L232.7 78.6 L235.1 76.9 L237.5 75.2 L239.9 73.4 L242.3 71.7 L244.7 69.9 L235.3 58.1 L233.1 59.9 L230.9 61.7 L228.7 63.5 L226.5 65.3 L224.2 67.0 L221.9 68.8 L219.6 70.5 L217.3 72.2 L215.0 73.9 L212.6 75.6 L210.3 77.2 L207.9 78.9 L205.5 80.5 L203.1 82.2 L200.7 83.8 L198.3 85.4 L195.8 86.9 L193.4 88.5 L190.9 90.1 L188.4 91.6 L185.9 93.1 L183.4 94.6 L180.9 96.1 L178.4 97.6 L175.8 99.1 L173.3 100.5 L170.7 102.0 L168.2 103.4 L165.6 104.8 L163.0 106.2 L160.4 107.5 L157.8 108.9 L155.2 110.2 L152.6 111.6 L149.9 112.9 L147.3 114.2 L144.7 115.4 L142.0 116.7 L139.4 118.0 L136.7 119.2 L134.1 120.4 L131.4 121.6 L128.7 122.8 L126.0 124.0 L123.4 125.1 L120.7 126.2 L118.0 127.4 L115.3 128.5 L112.6 129.5 L109.9 130.6 L107.2 131.7 L104.5 132.7 L101.8 133.7 L99.1 134.7 L96.4 135.7 L93.7 136.7 L91.0 137.6 L88.3 138.6 L85.6 139.5 L82.9 140.4 L80.2 141.3 L77.5 142.2 L74.8 143.0 L72.1 143.9 L69.4 144.7 L66.7 145.5 L64.1 146.3 L61.4 147.0 L58.7 147.8 L56.0 148.5 L53.4 149.2 L50.7 149.9 L48.1 150.6 L45.4 151.3 L42.8 151.9 L40.1 152.6 L37.5 153.2 L34.9 153.8 L32.2 154.4 L29.6 155.0 L27.0 155.5 L24.4 156.0 L21.8 156.6 L19.3 157.1 L16.7 157.6 L14.1 158.1 L11.6 158.5 L9.0 159.0 L6.5 159.5 L4.0 160.0Z" fill="url(#zs)"/><path d="M210.7 52.8 L272.9 37.9 L240.0 64.0Z" fill="#2ED3BF"/><path d="M240.0 64.0 L272.9 37.9 L244.3 95.1Z" fill="#0A7480"/></svg>'


def _mark(svg: str, uid: str) -> str:
    """Знак со своими id: два знака на одной странице не делят маску."""
    return svg.replace('id="dpx', f'id="{uid}').replace('#dpx', f'#{uid}') \
              .replace('id="dpy', f'id="{uid}').replace('#dpy', f'#{uid}') \
              .replace('id="dpz', f'id="{uid}').replace('#dpz', f'#{uid}')


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
    "message": "<path d='M4 5h16a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H9l-5 4V6a1 1 0 0 1 1-1z'/><path d='M8 10h8M8 13h5'/>",
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
    """ISO-дата сервера → как пишут в Молдове: 17.10.2026 (тот же формат, что в письмах)."""
    return mail.ro_date(s)


def _ro_time(s: str | None) -> str:
    """Отметка сервера → «30.10.2026 08:12» (UTC, как хранится; пояс пишет вызывающий)."""
    return f"{_ro(s)} {s[11:16]}" if s and len(s) >= 16 else _ro(s)


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
    # логотип: со входом — в кабинет, без входа — на сайт (03.10, Олег: «выхожу, нажимаю
    # на DentPilot, но на dentpilot.md не иду» — без входа /cont лишь возвращал на вход)
    home = "/cont" if acc is not None else esc(site)
    bar = (f"<div class='top'><div class='top-in'><a class='logo' href='{home}'><span class='ic'>{_mark(_MARK_COLOR, 'dpcb')}</span>"
           f"<span class='wm'><span class='d'>Dent</span>Pilot</span> <span class='sub'>· Contul clinicii</span></a>{who}</div></div>")
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
    "Programul DentPilot, de descărcat oricând — se activează cu un cod trimis pe e-mailul clinicii",
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
    brand = (f"<div class='brand'><span class='mark'>{_mark(_MARK_WHITE, 'dpca')}</span>"
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
    aside = (f"<div class='card'>{_chead('shield', 'Ce urmează')}{_perks(['Perioada de probă de ' + mail.zile(license.TRIAL_DAYS) + ' se activează imediat; confirmarea vine pe e-mail', 'Descărcați programul din cont; la prima pornire introduceți aceleași date și codul primit pe e-mail', 'IDNO și adresa le completați oricând — sunt necesare doar pentru abonament'])}"
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


def _lic_parts(c, sub, issue, st: str, now: datetime) -> dict:
    """Состояние лицензии словами: `text` (с тегом), `check` (последняя проверка
    программой), `bar` (полоса дней — только при выданном файле)."""
    if issue is None:
        if c["declined_at"]:
            return {"text": esc(CONT_MSG["closed"]), "check": "", "bar": ""}
        if c["origin"] == "cont_add":
            # клиника, добавленная в кабинете (27.10: без пробного, сразу на абонементе): файла нет
            # только без ключа выдачи на сервере — нота есть, лицензию выдаёт Олег
            return {"text": (f"Clinica a fost adăugată în cont la {_ro(c['requested_at'] or c['created_at'])}. "
                             f"Licența ei o activăm noi, de obicei în aceeași zi lucrătoare, și vă anunțăm pe "
                             f"e-mail. Programul îl puteți instala chiar acum: pe calculatorul clinicii se "
                             f"activează cu codul din acest cont și pornește singur după activare."),
                    "check": "", "bar": ""}
        return {"text": (f"Cererea de probă a fost primită la {_ro(c['requested_at'] or c['created_at'])}. "
                         f"O aprobăm de obicei în aceeași zi lucrătoare și vă anunțăm pe e-mail. Programul de pe "
                         f"calculatorul din care ați trimis cererea se activează singur; pe alt calculator — cu "
                         f"codul trimis pe e-mail."), "check": "", "bar": ""}
    plan = sub["plan"] if sub else "trial"
    what = "Perioada de probă" if plan == "trial" else f"Abonamentul {tiers.NAME[tiers.current(sub)]}"
    d, g = _ro(issue["valid_until"]), _ro(issue["grace_until"])
    cls, tag = STATE_RO.get(st, ("mute", st))
    advance = st == "active" and issue["reason"] == pay.ADVANCE
    if advance:
        # срок на оплату первой ноты клиники из кабинета (27.10) — не оплаченный период
        cls, tag = ADVANCE_TAG
        text = (f"{what} este activ — achitați nota de plată până la <b>{d}</b>; perioada plătită se numără din "
                f"ziua adăugării clinicii.")
    elif st == "active":
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
        check = (f"Programul a verificat licența ultima dată la {_ro_time(c['renew_at'])} UTC"
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
            r_text = f"Mai sunt {mail.zile(int(left))}{' pentru plată' if advance else ''} — până la {d}"
            bar = (f"<div class='bar'><span style='width:{pct}%'></span></div>"
                   f"<div class='days'><span>{l_text}</span><span>{r_text}</span></div>")
        elif st == "grace":
            bar = (f"<div class='bar warn'><span style='width:100%'></span></div>"
                   f"<div class='days'><span>A expirat la {d}</span><span>Funcționează complet până la {g}</span></div>")
        else:
            bar = (f"<div class='bar bad'><span style='width:100%'></span></div>"
                   f"<div class='days'><span>Regim de citire din {g}</span><span>Revine la lucru după plată</span></div>")
    return {"text": text, "check": check, "bar": bar}


def _subscribe_label(sub) -> str:
    """Кнопка по цели, не по средству (02.10): пробной — «Treci la abonament»,
    абонементу — «Prelungește abonamentul»; нота де плата остаётся средством."""
    return "Treci la abonament" if (sub is None or sub["plan"] == "trial") else "Prelungește abonamentul"


def _steps(card_on: bool) -> str:
    """Три шага оплаты; с картой (maib настроен) — и она. Срок перевода — словами условий § 4.6
    («după ce banii ajung în contul furnizorului»): его подтверждает Олег руками, своего срока
    у сервера нет — «в тот же рабочий день» не обещать (координатор 23.10)."""
    pay_ = ("<li><b>Plătiți</b> cu cardul, chiar aici, sau prin transfer bancar, cu referința din notă în "
            "destinația plății.</li>" if card_on else
            "<li><b>Plătiți</b> prin transfer bancar, cu referința din notă în destinația plății.</li>")
    when = ("plata cu cardul — în câteva minute, transferul — după ce banii ajung în contul furnizorului"
            if card_on else "transferul după ce banii ajung în contul furnizorului")
    return ("<ol class='steps'>"
            "<li><b>Alegeți</b> varianta — DentPilot Basic sau DentPilot Plus — și termenul, o lună sau un an; "
            "nota de plată o primiți și pe e-mail, cu referința.</li>"
            f"{pay_}<li><b>Confirmăm</b> {when}: termenul se prelungește, iar programul preia "
            "singur noul termen — o dată pe zi sau cu «Verifică acum».</li></ol>")


def _receipt_link_ro(p) -> str:
    """Cont de plată (PDF) оплаченной ноты в кабинете; у неоплаченной — тире."""
    if p["status"] != "paid":
        return "<span class='muted'>—</span>"
    return (f"<a href='/cont/plati/{esc(p['reference'])}.pdf' target='_blank' rel='noopener'>"
            f"cont de plată (PDF)</a>")


def _mdl(n) -> str:
    """12345 → «12 345» (неразрывный пробел между разрядами): суммы на страницах оплаты."""
    return f"{int(n):,}".replace(",", "\u00a0")


_DASH = ("<svg width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='#9AA8AD' stroke-width='2.4' "
         "stroke-linecap='round' aria-hidden='true'><path d='M6 12h12'/></svg>")
# Что даёт вариант — словами условий (§ 4.1, § 10, § 16): телефон — только Plus (вариант B Олега)
_TIER_PERKS = {
    tiers.BASIC: ((True, "Programări, fișe, odontogramă, statistică"), (True, "Actualizări incluse"),
                  (True, "Suport pe e-mail"), (False, "Fără modulul SMS")),
    tiers.PLUS: ((True, "Tot ce are Basic"), (True, "Modulul SMS: memento-uri automate pentru pacienți"),
                 (True, "Suport pe e-mail și la telefon")),
}
# Сумма под выбором считается в браузере из data-атрибутов карточек; без скрипта — сумма
# выбора при открытии (сервер всё равно считает сам: payments.choose)
_TOTAL_JS = ("(function(){document.querySelectorAll('form.pick').forEach(function(f){"
             "function up(){var t=f.querySelector('[name=tier]:checked'),m=f.querySelector('[name=months]:checked');"
             "if(!t||!m)return;var y=m.value=='12';"
             "f.querySelector('.total .t').innerHTML='<b>'+t.dataset.name+'</b> · '+(y?'un an (12 luni)':'o lună');"
             "f.querySelector('.total .s').textContent=(y?t.dataset.y:t.dataset.m)+' MDL'}"
             "f.addEventListener('change',up);up()})})()")


def _online(card_on: bool) -> list[tuple[str, str]]:
    """Способы оплаты онлайн кнопками, по порядку (value поля `method`, надпись). Сейчас —
    карта maib. MIA QR (Олег 23.10: «QR MIA будет», в договоре maib — «API plăți prin QR
    MIA») ляжет сюда второй парой («mia», «Plătește cu MIA QR»): страница рисует столько
    кнопок, сколько способов, а pay_link_submit различает их по `method`. Значков Apple Pay /
    Google Pay нет, пока maib их не включит."""
    return [("card", "Plătește cu cardul")] if card_on else []


def _buttons(card_on: bool, transfer: str = "", online_prefix: str = "") -> str:
    """Ряд кнопок формы: онлайн-способы (первый — главный) и, если назван, перевод."""
    online = _online(card_on)
    out = "".join(f"<button class='{'primary' if i == 0 else ''}' name='method' value='{v}'>"
                  f"{esc(online_prefix + (label[0].lower() + label[1:] if online_prefix else label))}</button>"
                  for i, (v, label) in enumerate(online))
    if transfer:
        out += (f"<button class='{'' if online else 'primary'}' name='method' value='transfer'>"
                f"{esc(transfer)}</button>")
    return f"<p class='btns'>{out}</p>"


def _terms_box() -> str:
    """Галочка условий перед оплатой (требование maib): обязательна в браузере и на сервере."""
    site = config.SITE_URL.rstrip("/")
    return (f"<div class='terms'><label class='chk'><input type='checkbox' name='terms' value='1' required> "
            f"<span>Am citit și accept <a href='{esc(site)}/termeni.html' target='_blank' rel='noopener'>"
            f"Termenii și condițiile</a> DentPilot.</span></label></div>")


def _module_note(sub, now: datetime) -> str:
    """Что будет с модулем SMS при выборе (условия § 4.2, § 16.10) — по состоянию подписки."""
    cur = tiers.current(sub)
    vu = _ts(sub["valid_until"]) if sub else None
    until = tiers.sms_until(sub)
    if cur == tiers.PLUS and vu is not None and vu > now:
        basic = (f"Cu DentPilot Basic modulul SMS rămâne pornit până la sfârșitul perioadei în curs "
                 f"(<b>{_ro(sub['valid_until'])}</b>) și se oprește apoi; SMS-urile rămase nu se pierd.")
    elif cur == tiers.PLUS:
        basic = "Cu DentPilot Basic modulul SMS se oprește; SMS-urile rămase nu se pierd."
    elif until is not None and until > now:
        basic = (f"Acum clinica are DentPilot Basic: modulul SMS mai funcționează până la "
                 f"<b>{_ro(sub['sms_until'])}</b>.")
    else:
        basic = "Acum clinica are DentPilot Basic: modulul SMS este oprit, SMS-urile rămase așteaptă."
    return (f"<p class='note'>Varianta o alegeți la fiecare plată. DentPilot Plus pornește modulul SMS imediat "
            f"după confirmarea plății. {basic} SMS-urile se plătesc separat, în pachete — în nicio variantă nu "
            f"intră în abonament.</p>")


def _tier_card(sub, t: str, checked: bool) -> str:
    m1 = pay.amount_for(sub, t, 1)
    y = pay.amount_for(sub, t, 12)
    lis = "".join(f"<li class='{'' if ok else 'no'}'>{_CHECK if ok else _DASH}<span>{esc(x)}</span></li>"
                  for ok, x in _TIER_PERKS[t])
    fine = "<span class='fine'>SMS-urile — în pachete, separat de abonament</span>" if t == tiers.PLUS else ""
    return (f"<label class='tier'><input type='radio' name='tier' value='{t}'{' checked' if checked else ''} required "
            f"data-name='{esc(tiers.NAME[t])}' data-m='{_mdl(m1)}' data-y='{_mdl(y)}'>"
            f"<span class='nm'>{esc(tiers.NAME[t])}</span><span class='what'>{esc(tiers.WHAT[t])}</span>"
            f"<span class='pr'>{_mdl(m1)} MDL <small>/ lună</small></span>"
            f"<span class='yr'>sau {_mdl(y)} MDL pe an — o lună gratuită</span><ul>{lis}</ul>{fine}</label>")


def tier_form(sub, action: str, card_on: bool, now: datetime, tier: str = "", months: int = 1,
              extra: str = "", replace: str = "") -> str:
    """Выбор варианта и срока + галочка условий + кнопки (вариант A кадров 23.10): одна форма
    на /plata и кабинет. `extra` — поля перед галочкой (IDNO); `replace` — reference
    ожидающей ноты: форма заменяет её (кнопки и подпись другие)."""
    sold = tiers.offered(sub)
    if not sold:
        return ("<p class='empty'>Abonamentul nu se poate plăti acum online. Scrieți-ne — vă trimitem nota de "
                "plată noi.</p>")
    t = tiers.pick(sub, tier)
    cards = "".join(_tier_card(sub, x, x == t) for x in sold)
    # ⛔ срок — только из ряда: нота SMS (months = 0), принятая за ноту абонемента, давала форму без
    # отмеченного срока и «0 MDL» (кадр Олега 26.10, живой кабинет); не из ряда — месяц
    months = months if months in pay.MONTHS else 1

    def seg(m: int, text: str, gift: str = "") -> str:
        return (f"<label><input type='radio' name='months' value='{m}'{' checked' if m == months else ''} required> {text}"
                f"{(' <span class=gift>' + gift + '</span>') if gift else ''}</label>")
    when = "un an (12 luni)" if months == 12 else "o lună"
    total = (f"<div class='total'><span class='t'><b>{esc(tiers.NAME[t])}</b> · {when}</span>"
             f"<span class='s'>{_mdl(pay.amount_for(sub, t, months))} MDL</span></div>")
    if replace:
        note = (f"<p class='note'>Nota {esc(replace)} se anulează și primiți una nouă, cu altă referință — nu mai "
                f"plătiți nota veche.</p>")
        buttons = _buttons(card_on, "Înlocuiește nota de plată", online_prefix="Înlocuiește și ")
    else:
        note = _module_note(sub, now)
        buttons = _buttons(card_on, "Transfer bancar — primesc nota de plată")
    return (f"<form method='post' action='{action}' class='pick'><span class='lbl'>Varianta</span>"
            f"<div class='tiers'>{cards}</div><span class='lbl'>Termen</span><div class='seg'>"
            f"{seg(1, 'O lună')}{seg(12, 'Un an (12 luni)', 'o lună gratuită')}</div>{total}{note}{extra}"
            f"{_terms_box()}{buttons}</form><script>{_TOTAL_JS}</script>")


def pending_note(p, sub, action: str, card_on: bool, now: datetime) -> str:
    """Ожидающая нота на /plata и в кабинете: вариант и срок в строке ноты, карта — ТОЖЕ за
    галочкой условий (прямой ссылки maib на странице нет: та пускала бы мимо галочки),
    реквизиты перевода, «Altă variantă sau alt termen?» — замена ноты (payments.choose)."""
    tier = p["tier"] if p["tier"] in tiers.TIERS else tiers.PLUS
    try:
        ways = f"<pre class='pay'>{esc(mail.ways_to_pay(p['reference'], p['amount'], None))}</pre>"
    except RuntimeError:
        ways = "<p>Datele pentru transfer bancar le primiți pe e-mail.</p>"
    card = ""
    if _online(card_on):
        card = (f"<form method='post' action='{action}'><input type='hidden' name='tier' value='{tier}'>"
                f"<input type='hidden' name='months' value='{p['months']}'>{_terms_box()}"
                f"{_buttons(card_on)}</form>")
    change = (f"<details class='more'><summary>Altă variantă sau alt termen?</summary>"
              f"{tier_form(sub, action, card_on, now, tier, int(p['months']), replace=p['reference'])}</details>")
    return (f"<p><b>Nota de plată {esc(p['reference'])}</b> — <b>{esc(tiers.NAME[tier])}</b>, "
            f"{mail.luni(p['months'])}: <b>{_mdl(p['amount'])} MDL</b> <span class='tag warn'>în așteptare</span></p>"
            f"{card}{ways}"
            f"<p class='muted' style='margin:0'>După confirmarea plății termenul se prelungește automat — programul "
            f"îl preia singur, o dată pe zi sau cu «Verifică acum»; primiți și confirmarea pe e-mail.</p>{change}")


def sms_notes_block(notes: list, action: str, card_on: bool) -> str:
    """Ожидающие ноты SMS (пакет, имя) на странице оплаты: письмо и программа ведут сюда —
    карта тем же путём, за галочкой условий (поле `ref`), перевод — по реквизитам ноты."""
    out = []
    for p in notes:
        what = pay.subject(p)
        try:
            ways = f"<pre class='pay'>{esc(mail.ways_to_pay(p['reference'], p['amount'], None))}</pre>"
        except RuntimeError:
            ways = "<p>Datele pentru transfer bancar le primiți pe e-mail.</p>"
        card = (f"<form method='post' action='{action}'><input type='hidden' name='ref' value='{esc(p['reference'])}'>"
                f"{_terms_box()}{_buttons(card_on)}</form>") if _online(card_on) else ""
        out.append(f"<div class='card narrow' style='max-width:760px'>"
                   f"{_chead('message', 'Nota de plată ' + esc(p['reference']), esc(what[:1].upper() + what[1:]))}"
                   f"<p><b>{_mdl(p['amount'])} MDL</b> <span class='tag warn'>în așteptare</span></p>{card}{ways}</div>")
    return "".join(out)


def _cont_payments(c, sub, payments: list, q: str = "", group=None, group_link: bool = True) -> str:
    """Абонемент и ноты клиники в кабинете. `q` — «?c=…» у кабинета с несколькими клиниками
    (форма несёт свою клинику); `group` — открытая общая нота, где клиника строкой (26.10):
    своя нота тогда не выставляется — ссылка на общую."""
    now = datetime.now(timezone.utc)
    # ⛔ нота абонемента — только вида license: нота SMS (пакет, имя; months = 0), принятая за неё,
    # давала «Altă variantă» без срока и «0 MDL» (кадр Олега 26.10, живой кабинет). Ноты SMS — своими
    # строками с реквизитами (_cont_sms_due)
    pending = [p for p in payments if p["status"] == "pending" and p["clinic_id"] == c["id"]
               and (p["kind"] or "license") == "license"]
    sms_due = [p for p in payments if p["status"] == "pending" and p["clinic_id"] == c["id"]
               and (p["kind"] or "license") in ("sms", "sms_name")]
    if group is not None:
        top = (f"<p>Abonamentul acestei clinici este în <b>nota comună {esc(group['reference'])}</b> — "
               f"<b>{_mdl(group['amount'])} MDL</b> pentru toate clinicile din ea "
               f"<span class='tag warn'>în așteptare</span>.</p>"
               + ("<p class='btns'><a class='btn' href='/cont/nota-comuna'>Vezi nota comună</a></p>"
                  "<p class='muted'>Altă variantă sau o notă separată pentru această clinică — după anularea notei "
                  "comune, pe pagina ei.</p>" if group_link else
                  "<p class='muted'>Nota comună se vede și se plătește după intrarea în cont cu Google sau cu codul "
                  "pe e-mail.</p>"))
    elif pending:
        top = pending_note(pending[0], sub, f"/cont/nota{q}", maib.enabled(), now)
    elif len(c["idno"] or "") == 13:
        top = (f"{_steps(maib.enabled())}{tier_form(sub, '/cont/nota' + q, maib.enabled(), now)}"
               f"<p class='muted'>Nota de plată cu referința și datele pentru plată apare aici și vine pe e-mail; "
               f"după confirmarea plății termenul se prelungește, iar programul îl preia singur.</p>")
    else:
        offer = "; ".join(f"{tiers.NAME[t]} — {_mdl(tiers.price(sub, t))} MDL pe lună sau "
                          f"{_mdl(pay.amount_for(sub, t, 12))} MDL pe an" for t in tiers.offered(sub))
        top = (f"{_steps(maib.enabled())}<p>Pentru abonament ({offer or 'prețul din oferta de pe dentpilot.md'}) completați "
               f"IDNO-ul clinicii în datele de mai jos, apoi {_subscribe_label(sub).lower()[0] + _subscribe_label(sub)[1:]} "
               f"— nota de plată apare aici.</p>")
    rows = "".join(
        f"<tr><td class='mono'>{esc(p['reference'])}</td><td>{p['amount']} MDL</td>"
        f"<td>{_cont_term(p)}</td>"
        f"<td>{_ro(p['created_at'])}</td>"
        f"<td>{_pay_tag_ro(p['status'])}{(' · ' + _ro(p['paid_at'])) if p['paid_at'] else ''}"
        f"</td><td>{_receipt_link_ro(p)}</td></tr>" for p in payments)
    # ⚠️ шесть столбцов не входят в 390 px телефона: без обёртки таблица раздвигала ВСЮ страницу вбок
    table = (f"<div class='tscroll'><table><tr><th>Referința</th><th>Suma</th><th>Termen</th><th>Data</th><th>Stare</th>"
             f"<th>Document</th></tr>"
             f"{rows or '<tr><td colspan=6 class=muted>Nu sunt note de plată</td></tr>'}</table></div>") if payments else ""
    return top + _cont_sms_due(sms_due) + table


def _cont_sms_due(notes: list) -> str:
    """Ожидающие ноты SMS в кабинете: что, сумма, реквизиты перевода; карта — со страницы оплаты
    из письма или из программы (Setări › SMS)."""
    out = []
    for p in notes:
        what = pay.subject(p)
        try:
            ways = f"<pre class='pay'>{esc(mail.ways_to_pay(p['reference'], p['amount'], None))}</pre>"
        except RuntimeError:
            ways = "<p class='muted'>Datele pentru transfer bancar le primiți pe e-mail.</p>"
        out.append(f"<div class='terms'><p><b>Nota de plată {esc(p['reference'])}</b> — {esc(what)}: "
                   f"<b>{_mdl(p['amount'])} MDL</b> <span class='tag warn'>în așteptare</span></p>{ways}"
                   f"<p class='muted' style='margin:0'>Cu cardul — din linkul din e-mailul cu nota sau din program, "
                   f"Setări › SMS.</p></div>")
    return "".join(out)


def _cont_term(p) -> str:
    """Что за нота в таблице кабинета: вариант и срок; общая — «notă comună»."""
    if (p["kind"] or "license") == "cabinet":
        return "notă comună (mai multe clinici)"
    return esc((tiers.NAME[p['tier']] + ', ') if p['tier'] in tiers.TIERS else '') + esc(mail.luni(p['months']))


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
        f"</div><div class='when'>ultima verificare {_ro_time(d['last_seen_at'])} UTC</div></div></li>"
        for d in devices)
    return f"<ul class='dev'>{rows}</ul>"


def group_note(p, lines: list, action: str, card_on: bool) -> str:
    """Открытая общая нота кабинета (26.10) на /plata клиники-строки: строки, итог, карта за
    галочкой (поле `ref`), реквизиты. Сменить выбор или отменить — в кабинете."""
    trs = "".join(f"<tr><td><b>{esc(ln['name'])}</b><div class='muted'>{esc(ln['address'] or '—')}</div></td>"
                  f"<td>{esc(tiers.NAME.get(ln['tier'], ln['tier']))}</td><td>{esc(mail.luni(int(ln['months'])))}</td>"
                  f"<td>{_mdl(ln['amount'])} MDL</td></tr>" for ln in lines)
    try:
        ways = f"<pre class='pay'>{esc(mail.ways_to_pay(p['reference'], p['amount'], None))}</pre>"
    except RuntimeError:
        ways = "<p>Datele pentru transfer bancar le primiți pe e-mail.</p>"
    card = (f"<form method='post' action='{action}'><input type='hidden' name='ref' value='{esc(p['reference'])}'>"
            f"{_terms_box()}{_buttons(card_on)}</form>") if _online(card_on) else ""
    return (f"<p>Abonamentul acestei clinici este în <b>nota comună {esc(p['reference'])}</b>: "
            f"<b>{_mdl(p['amount'])} MDL</b> <span class='tag warn'>în așteptare</span></p>"
            f"<div class='tscroll'><table><tr><th>Clinica</th><th>Varianta</th><th>Termen</th><th>Suma</th></tr>"
            f"{trs}</table></div>{card}{ways}"
            f"<p class='muted' style='margin:0'>Altă alegere sau anularea notei comune — din contul clinicii, "
            f"{esc(config.BASE_URL.rstrip('/'))}/cont/nota-comuna.</p>")


def pay_link_page(c, sub, pending, pid: str, msg: str = "", card_on: bool = False, sms_notes: list = (),
                  lines: list = ()) -> str:
    """Страница оплаты по ссылке из программы или письма (02.10, paylink.py): срок клиники,
    выбор варианта (Basic / Plus) и срока с галочкой условий — или ожидающая нота с
    реквизитами и заменой (23.10); ниже — ожидающие ноты SMS. Без входа: ссылка
    неугадываема и живёт сутки (из письма — 45 дней); кроме оплаты и IDNO здесь нет ничего."""
    now = datetime.now(timezone.utc)
    st = license.state(_ts(sub["valid_until"]) if sub else None, sub["grace_days"] if sub else 0, now)
    plan = sub["plan"] if sub else "trial"
    action = f"/plata/{esc(pid)}"
    if sub is not None and sub["valid_until"]:
        what = "Perioada de probă" if plan == "trial" else f"Abonamentul {tiers.NAME[tiers.current(sub)]}"
        cls, tag = STATE_RO.get(st, ("mute", st))
        term = (f"{what} {'este valabilă' if plan == 'trial' else 'este valabil'} până la "
                f"<b>{_ro(sub['valid_until'])}</b> <span class='tag {cls}'>{esc(tag)}</span>")
    else:
        term = "Licența nu este încă activată."
    if pending is not None and pending["kind"] == "cabinet":
        head = _chead("card", esc(c["name"]), f"notă comună pentru {len(lines)} clinici")
        body = f"<p class='lic'>{term}</p>{group_note(pending, list(lines), action, card_on)}"
    elif pending is not None:
        tier = pending["tier"] if pending["tier"] in tiers.TIERS else tiers.PLUS
        head = _chead("card", esc(c["name"]), f"{esc(tiers.NAME[tier])} · "
                                              f"{'un an (12 luni)' if int(pending['months']) == 12 else 'o lună'}")
        body = f"<p class='lic'>{term}</p>{pending_note(pending, sub, action, card_on, now)}"
    else:
        head = _chead("card", esc(c["name"]), "abonament DentPilot · varianta și termenul le alegeți mai jos")
        idno = "" if len(c["idno"] or "") == 13 else (
            "<label for='p-idno'>IDNO-ul clinicii (13 cifre) — necesar pentru abonament</label>"
            "<input id='p-idno' name='idno' maxlength='16' inputmode='numeric' required>")
        body = f"<p class='lic'>{term}</p>{_steps(card_on)}{tier_form(sub, action, card_on, now, extra=idno)}"
    inner = (f"<div class='card narrow' style='max-width:760px'>{head}{body}</div>"
             f"{sms_notes_block(list(sms_notes), action, card_on)}")
    return _cont_shell("Plata abonamentului", inner, msg=msg, eyebrow="DentPilot · plata online",
                       lead="Linkul din program sau din e-mailul cu nota de plată: aici plătiți abonamentul clinicii — "
                            "fără parolă, fără cont.")


def pay_link_expired_page() -> str:
    sub = "linkul din program este valabil o zi, cel din e-mail — 45 de zile"
    inner = (f"<div class='card narrow'>{_chead('clock', 'Linkul de plată a expirat', sub)}"
             f"<p>Deschideți din nou «Plătește acum» în program — primiți un link nou — sau linkul din cel mai nou "
             f"e-mail cu nota de plată. Sau intrați în "
             f"<a href='/cont'>contul clinicii</a>: acolo comandați nota de plată oricând.</p></div>")
    return _cont_shell("Linkul a expirat", inner, eyebrow="DentPilot · plata din program")


def cont_link_enter_page(clinic: str, action: str) -> str:
    """Ответ GET /cont/intra/<id> на живую ссылку (27.10, contlink.py): кнопка POST, которая и входит.
    GET ничего не гасит — окно программы и предзагрузка браузера открывают адреса сами."""
    sub = "linkul din program se deschide o singură dată, în 5 minute"
    inner = (f"<div class='card narrow'>{_chead('user', 'Contul clinicii ' + esc(clinic), sub)}"
             f"<p>Intrați în contul clinicii DentPilot din programul clinicii: vedeți abonamentul, notele și "
             f"contul de plată, calculatoarele și datele acestei clinici.</p>"
             f"<form method='post' action='{esc(action)}'><p style='margin:16px 0 0'>"
             f"<button class='primary'>Intră în contul clinicii</button></p></form></div>")
    return _cont_shell("Contul clinicii", inner, eyebrow="DentPilot · intrarea din program")


def cont_link_expired_page() -> str:
    """Ответ /cont/intra/<id> на погашенную или истёкшую ссылку (27.10, contlink.py)."""
    sub = "linkul din program se deschide o singură dată, în 5 minute"
    inner = (f"<div class='card narrow'>{_chead('clock', 'Linkul de intrare a expirat', sub)}"
             f"<p>Apăsați din nou «Deschide contul clinicii» în program (pagina Licență) — primiți un link nou. "
             f"Sau <a href='/cont/login'>intrați în contul clinicii</a> cu Google sau cu codul pe e-mail.</p></div>")
    return _cont_shell("Linkul a expirat", inner, eyebrow="DentPilot · intrarea din program")


def _cont_sms(c, info: dict, q: str = "") -> str:
    """Кабинет › SMS: имя отправителя клиники и заявление на него (бланк sms.md):
    заявка на имя → заполненное заявление (PDF) → подписанное обратно → подача
    Олегом → одобрение операторов. Только когда пакет клинике предложен. Имя общее на
    кабинет (26.10): `c` и счёт — главной клиники; `info['shared']` — её название, когда
    открыт филиал; формы несут открытую клинику (`q`), сервер ведёт их к главной."""
    sa = info["acc"]
    shared = info.get("shared") or ""
    state = sa["sender_state"] if sa is not None else "none"
    name = sa["sender"] if sa is not None else ""
    cls, word = SENDER_RO.get(state, ("mute", state))
    tag = f"<span class='tag {cls}'>{esc(word)}</span>"
    sub = f"acum SMS-urile pleacă de la «{esc(info['from'] or 'DentPilot')}»"
    hint = ("<p class='muted' style='margin:8px 0 0'>Până la 11 caractere: litere latine, cifre, spațiu, punct, "
            "cratimă — denumirea juridică sau marca clinicii. Până la aprobare memento-urile pleacă de la "
            "«DentPilot». Anul numelui propriu se comandă din program: Setări › SMS.</p>")

    def ask(label: str) -> str:
        return (f"<form method='post' action='/cont/sms/nume{q}'><label>Numele expeditorului</label>"
                f"<input name='name' value='{esc(name or info['suggest'])}' maxlength='11' required style='max-width:320px'>"
                f"{hint}<p style='margin:14px 0 0'><button class='primary'>{label}</button></p></form>")

    if state == "requested":
        paper = info["paper"]
        miss = info["missing"]
        if miss:
            step1 = (f"<p class='muted' style='margin:6px 0 0'>Lipsesc din <a href='{esc(info.get('data_href') or '#clinica')}'>datele clinicii</a>: "
                     f"{esc(', '.join(miss))}. Completați-le și cererea se poate descărca.</p>")
        else:
            step1 = (f"<form method='post' action='/cont/sms/cerere.pdf{q}' style='margin:6px 0 0'>"
                     f"<label>Reprezentantul legal care semnează (nume, prenume)</label>"
                     f"<input name='rep' value='{esc(c['contact_name'])}' maxlength='80' required style='max-width:420px'>"
                     f"<p style='margin:10px 0 0'><button class='primary'>{_ic('download')} Descarcă cererea (PDF)</button></p></form>")
        have = (f"<p class='muted' style='margin:6px 0 0'>Primită la {_ro(paper['uploaded_at'])}, "
                f"{max(1, paper['size'] // 1024)} KB. O puteți înlocui cu alt fișier.</p>") if paper else ""
        step3 = (f"<form method='post' action='/cont/sms/cerere{q}' enctype='multipart/form-data' style='margin:6px 0 0'>"
                 f"<input type='file' name='file' accept='application/pdf,.pdf' required style='max-width:420px'>"
                 f"<p style='margin:10px 0 0'><button>Încarcă cererea semnată</button></p></form>{have}")
        body = (f"<p style='margin:0 0 12px'>Numele cerut: <b>{esc(name)}</b> {tag}</p>"
                f"<ol class='steps'>"
                f"<li><b>Descărcați cererea completată</b>: formularul SMS.MD cu datele clinicii și numele cerut.{step1}</li>"
                f"<li><b>Semnați-o</b>: de mână, apoi scanați-o, sau cu semnătura electronică (MSign).</li>"
                f"<li><b>Încărcați cererea semnată</b>: PDF, până la 5 MB.{step3}</li>"
                f"<li><b>O depunem la SMS.MD</b>: aprobarea operatorilor durează 1–2 zile lucrătoare.</li></ol>"
                f"<details><summary>Alt nume</summary>{ask('Cere alt nume')}</details>")
    elif state == "submitted":
        body = (f"<p style='margin:0'>Numele <b>{esc(name)}</b> {tag}: cererea semnată a fost depusă la SMS.MD, "
                f"aprobarea durează 1–2 zile lucrătoare. Starea se actualizează aici.</p>")
    elif state == "active":
        until = f", achitat până la {_ro(sa['sender_until'])}" if sa["sender_until"] else ""
        body = (f"<p style='margin:0 0 12px'>Numele <b>{esc(name)}</b> {tag}{until}.</p>"
                f"<details><summary>Alt nume</summary><p class='muted'>Numele aprobat rămâne până la aprobarea "
                f"celui nou.</p>{ask('Cere alt nume')}</details>")
    else:
        note = (f"<p style='margin:0 0 12px'>Cererea pentru <b>{esc(name)}</b> {tag}"
                f"{(': ' + esc(sa['sender_note'])) if sa is not None and sa['sender_note'] else ''}.</p>"
                if state == "rejected" else
                "<p style='margin:0 0 4px'>Clinica nu are încă nume propriu de expeditor: pacienții primesc "
                "memento-urile de la «DentPilot».</p>")
        body = note + ask("Cere numele")
    if shared:
        body = (f"<p class='muted' style='margin:0 0 12px'>Numele expeditorului este comun pentru clinicile din acest "
                f"cont: cererea, documentul semnat și anul numelui sunt la <b>{esc(shared)}</b>.</p>") + body
    return f"<div class='card'>{_chead('message', 'SMS · numele expeditorului', sub)}{body}</div>"


def _crow(x: dict, on: bool, now: datetime) -> str:
    """Строка списка «Clinicile mele»: название и адрес, вариант и цена, срок с состоянием,
    компьютеры, действия (открыть, оплатить, код для компьютера)."""
    c, sub, issue, n = x["c"], x["sub"], x["issue"], x["devices"]
    cid = esc(c["id"])
    if issue is None:
        tier, until = "—", "—"
        tag = ("<span class='tag bad'>închisă</span>" if c["declined_at"]
               else "<span class='tag mute'>cerere de probă în lucru</span>")
    else:
        st = license.state(_ts(sub["valid_until"]) if sub else None, sub["grace_days"] if sub else 0, now)
        cur = tiers.current(sub)
        tier = (f"{tiers.NAME[cur]} · probă" if sub is None or sub["plan"] == "trial"
                else f"{tiers.NAME[cur]} · {_mdl(tiers.price(sub, cur))} MDL / lună")
        until = _ro(sub["valid_until"]) if sub else "—"
        cls, word = STATE_RO.get(st, ("mute", st))
        if st == "active" and issue["reason"] == pay.ADVANCE:
            # срок на оплату первой ноты (27.10): не «valabil», а «achitați nota până la»
            until, (cls, word) = f"Activă — achitați nota până la {until}", ADVANCE_TAG
        tag = f"<span class='tag {cls}'>{esc(word)}</span>"
    opn = f"<a class='btn second sm' href='/cont?c={cid}'>Deschide</a>"
    if on:
        act = "<span class='here'>deschisă acum</span>"
    elif not n and not c["declined_at"]:
        act = (f"<form method='post' action='/cont/cod?c={cid}'><button class='primary sm'>Cod de activare</button>"
               f"</form>{opn}")
    elif x["group"] is not None:
        act = f"<a class='btn second sm' href='/cont/nota-comuna'>În nota comună</a>{opn}"
    else:
        act = f"<a class='btn second sm' href='/cont?c={cid}#plati'>Plătește</a>{opn}"
    return (f"<div class='crow{' on' if on else ''}'>"
            f"<div class='who'><a class='nm' href='/cont?c={cid}'>{esc(c['name'])}</a>"
            f"<span class='ad'>{esc(c['address'] or '—')}</span></div>"
            f"<div><span class='k'>Varianta</span><span class='v'>{esc(tier)}</span></div>"
            f"<div><span class='k'>Valabil până la</span><span class='v'>{until} {tag}</span></div>"
            f"<div><span class='k'>Calculatoare</span><span class='v'>{n or 'niciunul'}</span></div>"
            f"<div class='act'>{act}</div></div>")


def _clinics_card(cab: list, cur: str, now: datetime) -> str:
    """«Clinicile mele» (26.10): клиники кабинета над дашбордом открытой."""
    add = f"<a class='btn sm' href='/cont/clinica-noua?c={esc(cur)}'>{_ic('plus')} Adaugă clinică</a>"
    common = "<a class='btn second sm' href='/cont/nota-comuna'>Notă comună</a>"
    sub = f"{len(cab)} clinici în acest cont · fiecare are licența și abonamentul ei"
    return (f"<div class='card'>{_chead('building', 'Clinicile mele', sub, common + ' ' + add)}"
            f"<div class='clist'>{''.join(_crow(x, x['c']['id'] == cur, now) for x in cab)}</div></div>")


def _doc_line(d: dict, q: str = "") -> str:
    """Строка документа поставщика: название, версия, ссылка на PDF или «ещё не выложен»."""
    if d["ok"]:
        link = f"<a href='/cont/documente/{d['key']}.pdf{q}'>{_ic('download', 14)} PDF</a>"
        ver = f" <span class='muted'>· versiunea {esc(d['version'])}</span>" if d["version"] else ""
    else:
        link, ver = "<span class='tag mute'>încă nepublicat</span>", ""
    return f"<li><b>{esc(d['title'])}</b>{ver} — {link}<br><span class='muted'>{esc(d['what'])}</span></li>"


def _cont_docs_body(c, docs: list, mine: list, fragment: str = "", q: str = "") -> str:
    """Вкладка «Documente» (29.10, contracts.py): подписанные поставщиком PDF — скачать; акты акцепта
    условий — фрагмент terms (`fragment`) или общая строка; загрузка экземпляра клиники со своей
    подписью (по желанию) и список загруженных."""
    mine = list(mine)
    items = "".join(_doc_line(d, q) for d in docs)
    about = ("<p class='muted' style='margin:0 0 12px'>Documentele sunt semnate electronic de furnizor (semnătură "
             "calificată, MoldSign) și sunt aceleași pentru toate clinicile; clinica este identificată prin acceptarea "
             "Termenilor și condițiilor la activarea programului și la plată. Prețurile sunt cele din "
             f"<a href='{esc(config.SITE_URL.rstrip('/'))}/termeni.html'>Termeni și condiții</a>.</p>")
    prov = (f"<div class='card'>{_chead('file', 'Documentele furnizorului', 'de descărcat și păstrat în evidența clinicii')}"
            f"{about}<ul class='steps' style='margin:0'>{items}</ul></div>")
    acts = fragment or ("<p class='muted' style='margin:0'>Acceptarea Termenilor și condițiilor este înregistrată la "
                        "activarea programului și la fiecare plată; istoricul acceptărilor va apărea aici.</p>")
    all_acts = f"<a class='btn second sm' href='/cont/acceptari{q}'>Toate actele</a>" if fragment else ""
    accept = f"<div class='card'>{_chead('shield', 'Acceptarea termenilor', 'cine și când a acceptat condițiile, în numele clinicii', all_acts)}{acts}</div>"
    opts = "".join(f"<option value='{k}'>{esc(contracts.DOCS[k]['title'])}</option>" for k in contracts.UPLOAD_DOCS)
    form = (f"<form method='post' action='/cont/documente/incarca{q}' enctype='multipart/form-data' style='margin:6px 0 0'>"
            f"<div class='grid'><div><label>Documentul</label><select name='doc'>{opts}</select></div>"
            f"<div><label>Fișierul PDF (până la {contracts.MAX_BYTES // (1024 * 1024)} MB)</label>"
            f"<input type='file' name='file' accept='application/pdf,.pdf' required></div></div>"
            f"<p style='margin:12px 0 0'><button class='primary'>Încarcă exemplarul semnat de clinică</button></p></form>")
    trs = "".join(
        f"<tr><td>{esc(contracts.DOCS[r['doc']]['title'])}</td><td class='mono'>{esc(r['version'] or '—')}</td>"
        f"<td>{_ro(r['uploaded_at'])}</td><td>{max(1, (r['size'] or 0) // 1024)} KB</td>"
        f"<td><a href='/cont/documente/{r['id']}/clinica.pdf'>{_ic('download', 14)} PDF</a></td></tr>" for r in mine)
    have = (f"<table style='margin-top:14px'><tr><th>Documentul</th><th>Versiunea</th><th>Încărcat</th><th>Mărime</th><th></th></tr>"
            f"{trs}</table>" if mine else "")
    upload = (f"<div class='card'>{_chead('user', 'Exemplarul semnat de clinică', 'opțional: același document, semnat și de clinică')}"
              f"<p class='muted' style='margin:0 0 6px'>Dacă contabilitatea clinicii are nevoie de un exemplar semnat de ambele "
              f"părți: descărcați PDF-ul de mai sus, semnați-l cu semnătura electronică a clinicii (MSign) sau tipăriți-l, "
              f"semnați-l și scanați-l, apoi încărcați-l aici. Rămâne în contul clinicii; furnizorul îl vede în fișa clinicii.</p>"
              f"{form}{have}</div>")
    return prov + accept + upload


# Вкладки кабинета (29.10, вариант 1 Олега): ключ, значок, подпись. ⛔ Ключ не равен ни одному id
# страницы — иначе метка адреса прокрутит к элементу (то же правило, что у карточки админки);
# прежние якоря блоков #plati и #date ведут на вкладку (data_href → #clinica). Держит test_cont_tabs.
CONT_TABS = (("licenta", "shield", "Licență și program"), ("plati", "card", "Abonament și plăți"),
             ("clinica", "building", "Clinica"), ("sms", "message", "SMS"), ("documente", "file", "Documente"))


def _cpick(cab: list, cur: str, now: datetime) -> str:
    """Клиники кабинета под заголовком: чипы с состоянием (открытая — бирюзой) и «Adaugă clinică»;
    на телефоне вместо чипов — список `<select>` (переход — страницей, вкладка остаётся меткой)."""
    chips, opts = ["<span class='k'>Clinicile contului:</span>"], []
    for x in cab:
        c, sub, issue = x["c"], x["sub"], x["issue"]
        if issue is None:
            cls, word = ("bad", "închisă") if c["declined_at"] else ("mute", "în lucru")
        else:
            st = license.state(_ts(sub["valid_until"]) if sub else None, sub["grace_days"] if sub else 0, now)
            cls, word = STATE_RO.get(st, ("mute", st))
            if st == "active" and issue["reason"] == pay.ADVANCE:
                cls, word = ADVANCE_TAG
        on = c["id"] == cur
        chips.append(f"<a class='{'on' if on else ''}' href='/cont?c={esc(c['id'])}'>{esc(c['name'])} "
                     f"<span class='tag {cls}'>{esc(word)}</span></a>")
        opts.append(f"<option value='/cont?c={esc(c['id'])}'{' selected' if on else ''}>{esc(c['name'])} · {esc(word)}</option>")
    chips.append(f"<a class='add' href='/cont/clinica-noua?c={esc(cur)}'>{_ic('plus', 15)} Adaugă clinică</a>")
    opts.append(f"<option value='/cont/clinica-noua?c={esc(cur)}'>+ Adaugă clinică</option>")
    return (f"<div class='cpick'>{''.join(chips)}</div>"
            f"<div class='cpick-sel'><label>Clinica</label><select class='gsel' onchange='location.href=this.value'>"
            f"{''.join(opts)}</select></div>")


def cont_page(acc, c, sub, issue, payments: list, release, msg: str = "", devices: list = (),
              smsinfo: dict | None = None, cab: list = (), group=None, scoped: bool = False,
              branch: bool = False, docs: list = (), docs_mine: list = (), docs_fragment: str = "",
              tab: str = "") -> str:
    """Дашборд клиники в кабинете — по вкладкам (29.10): Licență și program · Abonament și plăți · Clinica
    · SMS (когда пакет предложен) · Documente; `tab` — вкладка по умолчанию без метки адреса
    (/cont/documente открывает «Documente»), иначе первая. `scoped` — вошли кнопкой программы (27.10, contlink.py): одна
    клиника, без общей ноты и «Adaugă clinică»; `branch` — она в кабинете с другими (код компьютера —
    из кабинета, как у нескольких клиник, но без их имён). `cab` — клиники учётной записи для списка (26.10): больше
    одной — список «Clinicile mele» сверху, формы несут клинику (?c=), код компьютера на
    панели программы; одна — как прежде, плюс строка «Adaugă clinică». `group` — открытая
    общая нота, где эта клиника."""
    now = datetime.now(timezone.utc)
    st = license.state(_ts(sub["valid_until"]) if sub else None, sub["grace_days"] if sub else 0, now)
    site = config.SITE_URL.rstrip("/")
    lic = _lic_parts(c, sub, issue, st, now)
    ver = f" {esc(release.version)}" if release else ""
    setup = f"DentPilot-Setup{('-' + esc(release.version)) if release else ''}.exe"
    payments = list(payments)
    cab = list(cab)
    multi = len(cab) > 1
    q = f"?c={esc(c['id'])}" if multi else ""
    pending = any(p["status"] == "pending" and p["clinic_id"] == c["id"] and (p["kind"] or "license") == "license"
                  for p in payments)
    # действие по оплате на панели программы — те же условия, что у формы ноты ниже
    if group is not None:
        act = "" if scoped else "<a class='btn ghost' href='/cont/nota-comuna'>Vezi nota comună</a>"
    elif pending:
        act = "<a class='btn ghost' href='#plati'>Vezi nota de plată</a>"
    elif len(c["idno"] or "") == 13 and issue is not None:
        act = f"<a class='btn ghost' href='#plati'>{_subscribe_label(sub)}</a>"
    else:
        act = ""
    # Клиника кабинета уже на сервере: программа на любом её компьютере активируется кодом на
    # e-mail (заявка с теми же данными — «повтор», main._trial_program), а не «сама» (23.10)
    how = (f"<p class='muted' style='margin:14px 0 0'>La prima pornire programul cere datele clinicii și "
           f"codul pe care îl trimitem pe e-mailul clinicii — așa se activează pe orice calculator al ei. "
           f"Înainte de instalare citiți <a href='{esc(site)}/descarca.html'>ce cere Legea 195</a>.</p>")
    code_btn = ""
    if multi:
        # клиник несколько (26.10): код из письма привязывает к главной (её находит заявка) —
        # компьютер ЭТОЙ клиники активируется кодом из кабинета
        how = (f"<p class='muted' style='margin:14px 0 0'>Pe un calculator nou al acestei clinici: la prima pornire "
               f"programul cere datele clinicii, apoi un cod — introduceți codul din acest cont («Cod de activare», "
               f"în panoul Programul). Codul de 6 cifre din e-mail leagă calculatorul de prima clinică a contului, "
               f"{esc(cab[0]['c']['name'])}. Înainte de instalare citiți "
               f"<a href='{esc(site)}/descarca.html'>ce cere Legea 195</a>.</p>")
        code_btn = (f"<form class='side-code' method='post' action='/cont/cod{q}'>"
                    f"<button>Cod de activare pentru un calculator</button></form>")
    elif branch:
        how = (f"<p class='muted' style='margin:14px 0 0'>Pe un calculator nou al acestei clinici: la prima pornire "
               f"programul cere datele clinicii, apoi un cod — introduceți codul din acest cont («Cod de activare», "
               f"în panoul Programul). Codul de 6 cifre din e-mail leagă calculatorul de prima clinică a contului. "
               f"Înainte de instalare citiți <a href='{esc(site)}/descarca.html'>ce cere Legea 195</a>.</p>")
        code_btn = ("<form class='side-code' method='post' action='/cont/cod'>"
                    "<button>Cod de activare pentru un calculator</button></form>")
    hero = (f"<div class='card hero'><div class='main'><p class='eyebrow'>Licența</p>"
            f"<p class='lic'>{lic['text']}</p>{lic['bar']}"
            f"{('<p class=' + chr(39) + 'muted' + chr(39) + ' style=' + chr(39) + 'margin:14px 0 0' + chr(39) + '>' + lic['check'] + '</p>') if lic['check'] else ''}"
            f"{how}</div><div class='side'><p class='eyebrow'>Programul</p>"
            f"<div class='big'>DentPilot{ver}</div>"
            f"<p class='small'>Instalator semnat digital — arhivă zip cu {setup}.</p>"
            f"<div class='actions'><a class='btn' href='/descarca'>{_ic('download')} Descarcă DentPilot{ver}</a>{code_btn}{act}</div>"
            f"</div></div>")
    devs = (f"<div class='card'>{_chead('monitor', 'Calculatoare cu DentPilot', 'versiunea programului și ultima verificare a licenței')}"
            f"{_cont_devices(list(devices), release.version if release else '')}</div>")
    if scoped:
        who = ("<p style='margin:0 0 6px'>Ați intrat din <b>programul DentPilot al acestei clinici</b>, fără cod.</p>"
               "<p class='muted' style='margin:0 0 14px'>Vedeți doar această clinică. Celelalte clinici ale contului, "
               "nota comună și adăugarea unei clinici — după <a href='/cont/login'>intrarea cu Google sau cu codul pe "
               "e-mail</a>.</p>")
    elif acc["provider"] == "google":
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
    # одна клиника: «Adaugă clinică» — карточкой «Filiale» во вкладке Clinica (у кабинета с несколькими —
    # список «Clinicile mele» там же, кнопка в нём и в чипах под заголовком)
    branches = "" if multi or scoped else (
        f"<div class='card'>{_chead('building', 'Filiale', 'fiecare sediu — o clinică în acest cont')}"
        f"<div class='addline' style='border-top:0;margin-top:0;padding-top:0'><p><b>Clinica are și alte sedii?</b> "
        f"Adăugați fiecare filială ca o clinică nouă în acest cont: cu licența și abonamentul ei, aceeași intrare.</p>"
        f"<a class='btn second sm' href='/cont/clinica-noua'>{_ic('plus')} Adaugă clinică</a></div></div>")
    cur = tiers.current(sub)
    chip = (f"<span class='price'>perioada de probă · {tiers.NAME[cur]}</span>" if sub is None or sub["plan"] == "trial"
            else f"<span class='price'>{tiers.NAME[cur]} · {_mdl(tiers.price(sub, cur))} MDL / lună</span>")
    pays = (f"<div class='card'>{_chead('card', 'Abonament și plăți', 'abonamentul acestei clinici' if multi else 'un singur abonament pentru toată clinica', chip)}"
            f"{_cont_payments(c, sub, payments, q, group, group_link=not scoped)}</div>")
    data = (f"<div class='card'>{_chead('building', 'Datele clinicii', 'apar în nota de plată și în licență')}"
            f"<form method='post' action='/cont/date{q}'><div class='grid'>"
            f"<div><label>Denumirea clinicii *</label><input name='name' value='{esc(c['name'])}' required maxlength='{trial.NAME_MAX}'></div>"
            f"<div><label>IDNO (13 cifre)</label><input name='idno' value='{esc(c['idno'])}' maxlength='13' inputmode='numeric'></div>"
            f"<div><label>Persoana de contact</label><input name='contact_name' value='{esc(c['contact_name'])}' maxlength='{trial.CONTACT_MAX}'></div>"
            f"<div><label>Telefon</label><input name='phone' value='{esc(c['phone'])}' maxlength='{trial.PHONE_MAX}'></div>"
            f"<div><label>Adresa</label><input name='address' value='{esc(c['address'])}' maxlength='200'></div>"
            f"<div><label>E-mail</label><div class='mono' style='padding:8px 0'>{esc(c['email'] or '—')}</div>"
            f"<span class='muted'>pentru schimbare scrieți-ne</span></div></div>"
            f"<p style='margin:16px 0 0'><button class='primary'>Salvează</button></p></form></div>")
    sms_card = _cont_sms(smsinfo.get("clinic") or c, smsinfo, q) if smsinfo is not None else ""
    panes = {"licenta": hero + f"<div class='grid2'>{devs}{acct}</div>", "plati": pays,
             "clinica": data + (_clinics_card(cab, c["id"], now) if multi else "") + branches,
             "sms": sms_card, "documente": _cont_docs_body(c, list(docs), docs_mine, docs_fragment, q)}
    # счётчик «ждёт вас» у вкладки: открытая нота (своя или общая); имя SMS запрошено, заявление не загружено
    counts = {"plati": 1 if (pending or group is not None) else 0,
              "sms": 1 if (smsinfo is not None and smsinfo["acc"] is not None
                           and smsinfo["acc"]["sender_state"] == "requested" and not smsinfo.get("paper")) else 0}
    tabs = [(k, i, t) for k, i, t in CONT_TABS if panes[k]]
    nav = "".join(f"<a href='#{k}' data-tab='{k}' role='tab'>{_ic(i, 17)}<span>{t}</span>{_n(counts.get(k, 0))}</a>"
                  for k, i, t in tabs)
    body = "".join(f"<section class='pane' data-pane='{k}'>{panes[k]}</section>" for k, _, _ in tabs)
    default = f" data-default='{tab}'" if tab in panes and panes[tab] else ""
    inner = (f"<div class='tabbed'{default}><nav class='ctabs' role='tablist'>{nav}</nav>{body}</div>"
             f"<script>{_TABS_JS}</script>")
    top = _cpick(cab, c["id"], now) if multi else ""
    eyebrow = f"Contul clinicii · {len(cab)} clinici" if multi else "Contul clinicii"
    return _cont_shell(c["name"], top + inner, acc, msg, eyebrow=eyebrow)


# ---------- кабинет: клиника в кабинет, код компьютера, общая нота (26.10) ----------


ADD_PAY_DAYS = 14         # = jobs.INVOICE_DAYS: срок на оплату первой ноты клиники из кабинета (jobs сюда не импортируется)


def _add_tier_pick(tier: str, months: str) -> str:
    """Вариант и срок абонемента новой клиники кабинета — карточки и сегмент той же формы, что у
    ноты (tier_form), с итогом; цена — прайс варианта (у новой клиники подписки нет)."""
    sold = tiers.offered(None)
    if not sold:
        return ("<p class='empty'>Abonamentul nu se poate plăti acum online — scrieți-ne și adăugăm clinica "
                "noi.</p>")
    t = tiers.pick(None, tier)
    m = 12 if months == "12" else 1

    def seg(n: int, text: str, gift: str = "") -> str:
        return (f"<label><input type='radio' name='months' value='{n}'{' checked' if n == m else ''} required> {text}"
                f"{(' <span class=gift>' + gift + '</span>') if gift else ''}</label>")
    return (f"<span class='lbl'>Abonamentul clinicii noi</span>"
            f"<div class='tiers'>{''.join(_tier_card(None, x, x == t) for x in sold)}</div>"
            f"<span class='lbl'>Termen</span><div class='seg'>{seg(1, 'O lună')}"
            f"{seg(12, 'Un an (12 luni)', 'o lună gratuită')}</div>"
            f"<div class='total'><span class='t'><b>{esc(tiers.NAME[t])}</b> · {'un an (12 luni)' if m == 12 else 'o lună'}"
            f"</span><span class='s'>{_mdl(pay.amount_for(None, t, m))} MDL</span></div>"
            f"<p class='note'>Nota de plată vine pe e-mailul clinicii noi imediat după adăugare. Varianta și termenul "
            f"le puteți schimba până la plată.</p>")


def cont_add_page(acc, cur, msg: str = "", values: dict | None = None) -> str:
    """«Adaugă o clinică»: данные новой клиники кабинета (e-mail и IDNO — открытой, «можно тот
    же»), вариант и срок абонемента — она сразу платная (Олег 27.10: пробный только у главной;
    нота первого периода выставляется по этому выбору) — и что она получает; галочка условий —
    как у заявки на пробный."""
    v = values or {}
    site = config.SITE_URL.rstrip("/")

    def val(k: str, default: str = "") -> str:
        return esc(v.get(k, default) or "")
    perks = _perks([
        "<b>Licența ei</b>: programul de pe calculatorul filialei are baza lui de date, separată de celelalte "
        "clinici.",
        "<b>Pornește imediat</b>, fără să aștepte aprobarea noastră. Luna gratuită de probă este doar pentru "
        "prima clinică din cont — clinica nouă intră direct pe abonament.",
        f"<b>Nota pentru prima perioadă</b> vine imediat, cu {ADD_PAY_DAYS} zile pentru plată; perioada plătită se "
        f"numără din ziua adăugării. Apoi fiecare clinică se plătește din lista «Clinicile mele» sau toate odată, "
        f"cu o notă comună.",
        "<b>Aceeași intrare</b> în cont pentru toate clinicile — Google sau codul pe e-mail.",
        f"<b>Activarea</b> pe calculatorul filialei — cu un cod din acest cont, din {CODE_DIGITS} cifre.",
    ])
    form = (f"<div class='card'>{_chead('building', 'Datele clinicii noi', 'apar în licența ei, în notele de plată și în scrisori')}"
            f"<form method='post' action='/cont/clinica-noua?c={esc(cur['id'])}' class='pick'><div class='grid'>"
            f"<div><label>Denumirea clinicii *</label><input name='name' value='{val('name')}' "
            f"placeholder='ex.: {esc(cur['name'][:60])} — filiala Centru' required maxlength='{trial.NAME_MAX}'></div>"
            f"<div><label>Adresa *</label><input name='address' value='{val('address')}' placeholder='strada, numărul, orașul' "
            f"required maxlength='200'></div>"
            f"<div><label>Telefon</label><input name='phone' value='{val('phone')}' maxlength='{trial.PHONE_MAX}'></div>"
            f"<div><label>Persoana de contact</label><input name='contact_name' value='{val('contact_name', cur['contact_name'])}' "
            f"maxlength='{trial.CONTACT_MAX}'></div>"
            f"<div><label>E-mail *</label><input name='email' value='{val('email', cur['email'])}' required "
            f"maxlength='{trial.EMAIL_MAX}'><p class='hint'>Poate fi același ca la {esc(cur['name'])}. Pe el vin notele "
            f"de plată și scrisorile acestei clinici.</p></div>"
            f"<div><label>IDNO (13 cifre) *</label><input name='idno' value='{val('idno', cur['idno'])}' maxlength='13' "
            f"inputmode='numeric' required><p class='hint'>Același IDNO este permis pentru clinicile din contul dvs.</p>"
            f"</div></div>{_add_tier_pick(v.get('tier', ''), v.get('months', ''))}"
            f"<label class='chk'><input type='checkbox' name='consent' value='1' required> <span>Am citit și accept "
            f"<a href='{esc(site)}/termeni.html' target='_blank' rel='noopener'>Termenii și condițiile</a> și "
            f"<a href='{esc(site)}/privacy.html' target='_blank' rel='noopener'>Politica de confidențialitate</a> "
            f"pentru clinica nouă.</span></label>"
            f"<p style='margin:18px 0 0'><button class='primary'>Adaugă clinica și primește codul</button></p></form>"
            f"<script>{_TOTAL_JS}</script></div>")
    side = f"<div class='card'>{_chead('list', 'Ce primește clinica nouă')}{perks}</div>"
    return _cont_shell("Adaugă o clinică", f"<div class='split'>{form}{side}</div>", acc, msg,
                       eyebrow="Contul clinicii · clinică nouă",
                       lead=f"Filiala sau al doilea sediu se adaugă aici, ca o clinică nouă în același cont. "
                            f"<a href='/cont?c={esc(cur['id'])}'>Înapoi la clinicile mele</a>")


CODE_DIGITS = 7           # = account.CODE_DIGITS (account не импортируется сюда: views — только разметка)


def cont_activation_page(acc, c, code: str, until: str, main, release, msg: str = "") -> str:
    """Код компьютера клиники из кабинета — показывается один раз: цифры клетками (без пробела:
    поле программы — 7 знаков), срок, три шага, предупреждение о коде из письма."""
    boxes = "".join(f"<span>{esc(ch)}</span>" for ch in code)
    ver = f" {esc(release.version)}" if release else ""
    idno = f"IDNO <b>{esc(c['idno'])}</b> și " if c["idno"] else ""
    steps = ("<ol class='steps'>"
             "<li><b>Instalați DentPilot</b> pe calculatorul clinicii — butonul de mai jos.</li>"
             f"<li><b>La prima pornire</b> completați datele clinicii cu {idno}e-mailul <b>{esc(c['email'])}</b>. "
             "Programul răspunde că clinica este deja înregistrată și arată câmpul pentru cod.</li>"
             f"<li><b>Introduceți codul de mai sus</b>, cele {len(code)} cifre, în câmpul «Codul din e-mail» și apăsați "
             f"«Activează programul». Calculatorul se leagă de <b>{esc(c['name'])}</b>, cu licența ei.</li></ol>")
    warn = ""
    if main is not None and main["id"] != c["id"]:
        warn = (f"<div class='warnbox'>În același timp pe e-mailul <b>{esc(main['email'] or '—')}</b> vine un cod de 6 "
                f"cifre — acela activează calculatorul pentru prima clinică a contului, {esc(main['name'])}. Pentru "
                f"această clinică folosiți codul de aici.</div>")
    card = (f"<div class='card narrow' style='max-width:640px'>"
            f"{_chead('key', esc(c['name']), 'codul de activare pentru un calculator al acestei clinici')}"
            f"<div class='code' aria-label='Codul de activare'>{boxes}</div>"
            f"<p class='code-sub'>Valabil până la <b style='color:var(--ink)'>{_ro(until)}</b> · o singură dată · "
            f"un singur calculator</p>{steps}{warn}"
            f"<div class='btns' style='margin-top:18px'><a class='btn' href='/descarca'>{_ic('download')} Descarcă "
            f"DentPilot{ver}</a><a class='btn second' href='/cont?c={esc(c['id'])}'>Înapoi la clinicile mele</a></div>"
            f"<p class='note'>Codul nu se mai poate vedea după ce închideți pagina. Pentru încă un calculator sau dacă "
            f"l-ați pierdut — «Cod de activare» din nou; codul vechi nefolosit nu mai este valabil.</p></div>")
    return _cont_shell("Codul de activare", card, acc, msg, eyebrow="Contul clinicii · cod de activare")


_GROUP_JS = ("(function(){var f=document.querySelector('form.group');if(!f)return;"
             "function sp(v){return String(v).replace(/\\B(?=(\\d{3})+(?!\\d))/g,' ')}"
             "function up(){var s=0,n=0;f.querySelectorAll('tr[data-c]').forEach(function(r){"
             "var t=r.querySelector('select.t'),m=r.querySelector('select.m');var o=t.options[t.selectedIndex];"
             "if(!o||!o.value)return;n++;s+=+o.getAttribute(m.value=='12'?'data-y':'data-m')});"
             "document.getElementById('gs').textContent=sp(s)+' MDL';"
             "document.getElementById('gn').textContent=n+(n==1?' clinică':' clinici')}"
             "f.addEventListener('change',up);up()})();")


def group_form(rows: list, card_on: bool, replace: str = "") -> str:
    """Выбор общей ноты: у каждой клиники вариант (или «nu se include») и срок, итог, галочка
    условий, кнопки. `rows` — [(клиника, подписка, держит ли её своя нота)]."""
    trs = []
    total, picked = 0, 0
    for c, sub, _ in rows:
        cid = esc(c["id"])
        sold = tiers.offered(sub)
        if tiers.pick(sub) in sold:            # выбор по умолчанию: вариант клиники, месяц
            total, picked = total + pay.amount_for(sub, tiers.pick(sub), 1), picked + 1
        opts = "<option value=''>— nu se include —</option>" + "".join(
            f"<option value='{t}'{' selected' if t == tiers.pick(sub) else ''} "
            f"data-m='{pay.amount_for(sub, t, 1)}' data-y='{pay.amount_for(sub, t, 12)}'>"
            f"{esc(tiers.NAME[t])} — {_mdl(pay.amount_for(sub, t, 1))} MDL / lună</option>" for t in sold)
        months = ("<option value='1'>o lună</option><option value='12'>un an (12 luni) — o lună gratuită</option>")
        trs.append(f"<tr data-c='{cid}'><td><b>{esc(c['name'])}</b><div class='muted'>{esc(c['address'] or '—')}</div></td>"
                   f"<td><select class='gsel t' name='t_{cid}'>{opts}</select></td>"
                   f"<td><select class='gsel m' name='m_{cid}'>{months}</select></td></tr>")
    note = (f"<p class='note'>Nota {esc(replace)} se anulează și primiți una nouă, cu altă referință — nu mai plătiți "
            f"nota veche.</p>" if replace else
            "<p class='note'>Notele în așteptare ale clinicilor incluse se înlocuiesc cu nota comună: datoria fiecărei "
            "clinici rămâne una. Varianta o alegeți la fiecare plată; SMS-urile se plătesc separat, în pachete.</p>")
    buttons = _buttons(card_on, "Înlocuiește nota comună" if replace else "Transfer bancar — primesc nota comună",
                       online_prefix="Înlocuiește și " if replace else "")
    return (f"<form method='post' action='/cont/nota-comuna' class='group'><div class='tscroll'><table>"
            f"<tr><th>Clinica</th><th>Varianta</th><th>Termen</th></tr>{''.join(trs)}</table></div>"
            # итог — сразу сервером (без скрипта тоже верный), скрипт пересчитывает при выборе
            f"<div class='total'><span class='t'><b>Notă comună</b> · <span id='gn'>{picked} "
            f"{'clinică' if picked == 1 else 'clinici'}</span></span>"
            f"<span class='s' id='gs'>{_mdl(total)} MDL</span></div>{note}{_terms_box()}{buttons}</form>"
            f"<script>{_GROUP_JS}</script>")


def cont_group_page(acc, rows: list, pending, lines: list, msg: str = "", card_on: bool = False) -> str:
    """Общая нота на клиники кабинета (Олег 26.10: «Нужен и общий счёт»). Открытая — строки
    (клиника, вариант, срок, сумма), итог, карта за галочкой, реквизиты, отмена и замена; нет —
    выбор. Одна нота, один reference; после оплаты каждая клиника — своим файлом."""
    if pending is not None:
        trs = "".join(f"<tr><td><b>{esc(ln['name'])}</b><div class='muted'>{esc(ln['address'] or '—')}</div></td>"
                      f"<td>{esc(tiers.NAME.get(ln['tier'], ln['tier']))}</td><td>{esc(mail.luni(int(ln['months'])))}</td>"
                      f"<td>{_mdl(ln['amount'])} MDL</td></tr>" for ln in lines)
        try:
            ways = f"<pre class='pay'>{esc(mail.ways_to_pay(pending['reference'], pending['amount'], None))}</pre>"
        except RuntimeError:
            ways = "<p>Datele pentru transfer bancar le primiți pe e-mail.</p>"
        card = (f"<form method='post' action='/cont/nota-comuna'><input type='hidden' name='ref' "
                f"value='{esc(pending['reference'])}'>{_terms_box()}{_buttons(card_on)}</form>") if _online(card_on) else ""
        cancel = (f"<form method='post' action='/cont/nota-comuna/anuleaza' style='margin:0'>"
                  f"<input type='hidden' name='ref' value='{esc(pending['reference'])}'>"
                  f"<button>Anulează nota comună</button></form>")
        body = (f"<p><b>Nota comună {esc(pending['reference'])}</b>: <b>{_mdl(pending['amount'])} MDL</b> "
                f"<span class='tag warn'>în așteptare</span></p>"
                f"<div class='tscroll'><table><tr><th>Clinica</th><th>Varianta</th><th>Termen</th><th>Suma</th></tr>"
                f"{trs}</table></div>{card}{ways}"
                f"<p class='muted' style='margin:0'>După confirmarea plății fiecare clinică primește termenul ei — "
                f"programul fiecăreia îl preia singur; contul de plată este unul, cu un rând pentru fiecare clinică.</p>"
                f"<details class='more'><summary>Altă alegere?</summary>"
                f"{group_form(rows, card_on, replace=pending['reference'])}</details>"
                f"<p class='btns'>{cancel}</p>")
    else:
        body = ("<p class='muted' style='margin:0 0 12px'>O singură notă și o singură plată pentru mai multe clinici "
                "din cont: alegeți varianta și termenul fiecăreia. După plată fiecare clinică primește termenul ei.</p>"
                + group_form(rows, card_on))
    card_html = f"<div class='card'>{_chead('card', 'Nota comună', 'pentru clinicile din acest cont')}{body}</div>"
    return _cont_shell("Notă comună de plată", card_html, acc, msg, eyebrow="Contul clinicii · notă comună",
                       lead="<a href='/cont'>Înapoi la clinicile mele</a>")
