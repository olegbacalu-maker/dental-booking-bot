# «Rechemări» — контракт API (29.10.2026)

Мини-CRM регистратуры: список пациентов, которым пора на повторную процедуру
(срок задаётся у услуги — `clinic.json › services[].recall`), для звонка или
письма. План — `D:\DentProject\review\plan-crm-rechemari-2026-10-29.md`;
решения Олега 29.10: В1–В5 = вариант А (врач список не видит, строку срока в
фише видит; строка за 14 дней до срока; галочка «Vizita a avut loc» в окне
записи на прошедший день; статистики в v1 нет; раздел в «La recepție» после
«Plan fără programare»). Этот файл фиксируется ПЕРВЫМ коммитом Ш1: по нему
клиент (Ш2) пишется на моках.

Всё вычисляется при каждом запросе из визитов и конфига (`core/recall.py`);
хранится только отметка регистратуры (`recall_marks`, шаг схемы 8).

**SMS из списка (30.10.2026, план `review/plan-recall-sms-2026-10-29.md`,
Олег 30.10: «все А»)** — кнопка «SMS» в строке, одна SMS на цикл услуги,
текст без услуги и месяцев, синхронная отправка с записью в `sms_log`
(`kind = recall`, `appt_id NULL`), отметка `sms` в `recall_marks`,
недоставленная возвращает строку в «De sunat», галочка «Buton SMS în
Rechemări» в Setări › SMS (включена по умолчанию), SMS считается в
«contactați». Раздел «SMS из списка» ниже.

## Право

`PERM_RECALL` в `PERMS` — директор и регистратура. Без права: `/api/recall*`
→ 403 `no_access`, `desk.recall` → `null`, пункта меню нет; строка срока в
фише видна любой роли (`can_clear` — только с правом).

## `GET /api/recall`

```
{ok, data: {
  services: [{id, ro, months, since}],          // только услуги со сроком
  rows: [{
    pid, name, phone, email, lang,              // lang: "ro" | "ru" — язык письма
    service_id, service, months,
    last_at: "YYYY-MM-DD", doctor,              // последний done-визит (дата клиники)
    due: "YYYY-MM-DD", late_days: int,          // срок; >0 просрочен, <0 ещё не наступил
    late: "întârziere 3 săpt." | "peste 9 zile" | "azi" | "mâine",   // слово сервера
    booked: {date: "DD.MM", service} | null,    // записан вперёд на ДРУГУЮ услугу
    mark: {result, word, until: "YYYY-MM-DD" | "", n_noanswer, at: "DD.MM", actor,
           sms: {state, word} | null} | null,   // у отметки `sms`: состояние доставки (sms_log) и его слово
    tab: "due" | "snoozed" | "stop",
    sms: {can: bool, why: "" | "phone" | "sms_off" | "no_clinic_phone" | "quiet",
          text, segments} | null             // кнопка «SMS»: null — пакет не пускает (`sms` ниже null)
                                             // или SMS этого цикла уже ушла (тогда смотри mark.sms)
  }],
  counts: {due, snoozed, stop},
  clinic: {name, phone},                        // для текста письма
  can_settings: bool,                           // пустой экран: кнопка в Setări › Servicii (директор) или слово
  sms: {on: true, balance: int, quiet: bool} | null,   // null — `sms_loop.recall_on()` false:
                                                        // Basic, выключено, без лицензии, галочка снята
  stats: {month: {contacted, booked}, prev: {contacted, booked}} | null
    // В4 → Б (Олег 29.10 ~18:55): одной строкой «Luna aceasta: contactați N · programați M»
    // за текущий и прошлый календарный месяц (день клиники). N — пациенты с отметкой
    // contacted/emailed в периоде, M — из них те, у кого ПОСЛЕ отметки создана запись
    // на ту же услугу (живая или done). null — ни одной такой отметки за оба месяца:
    // строки нет, нули не рисуются (Олег: у новой клиники экран был бы в нулях).
}}
```

Порядок `rows`: без отметки сверху, самые просроченные первыми; «nu răspunde»
— вниз. Тело детерминировано в пределах дня (ни одного «сейчас»); ⚠️ блок
`sms` (тихие часы `quiet`) — единственное, что зависит от часа, и он есть
ТОЛЬКО у экрана: `desk.recall` и модель фиши его не несут.

## `POST /api/recall/mark`

Тело `{pid, service_id, result, until?}`; `result` ∈ `contacted` («Sunat —
revine», прячет 14 дней) · `emailed` («E-mail trimis», 14 дней) · `sms`
(ставит только `POST /api/recall/sms` после ответа сервера, руками не
ставится — 422; 14 дней, а при `undelivered`/`failed` строка сразу в `due`) · `noanswer`
(остаётся, считает попытки) · `later` (`until` — голая дата ISO, прячет до
неё) · `stop` («Nu mai reaminti», навсегда для услуги) · `clear` (отменяет
последнюю отметку). Ответ — `msg_json`: `ok_recall` / 422 `bad_recall`
(незнакомый результат, `later` без даты) / 409 `recall_gone` (у пары
пациент–услуга нет завершённого визита: отмечать нечего). Состояния не
возвращает — экран перечитывает `GET /api/recall`, главная — живой канал.
Каждая отметка пишет строку в летопись пациента готовой строкой.

## `desk.recall` в конверте живого канала (`/api/schedule/live` › `desk`)

`{n, items: [первые 3 строки tab=due]}` или `null` без права. Строки — той же
формы, что `rows` выше.

## Модель фиши (`GET /api/patients/{pid}` › `recall`)

```
recall: [{service, service_id, last: "DD.MM.YYYY", next: "DD.MM.YYYY",
          late_days, late, stop: bool, can_clear: bool,
          mark: {result, word, at, actor} | null}]
```
Строка на каждую услугу со сроком, по которой у пациента есть `done`-визит.

## Настройки услуг (`/api/settings/services`)

Строка услуги несёт `recall: int` месяцев (0 — не участвует); `recalls` —
белый список `[0, 3, 4, 6, 9, 12, 24]`. В теле сохранения ключа `recall` нет
= «не сообщали» (значение из текущего конфига по id); `since` ставит сервер,
когда срок появляется; смена числа месяцев дату не трогает; 0 снимает обе.

## Окно записи

`POST /api/schedule/appointments` принимает `done: true` — только на
прошедший день (`eng.is_past_day`) визит ложится сразу `done`; ответ
`ok_past_done`. На день не в прошлом поле игнорируется.

## SMS из списка (30.10.2026)

Гейт — `sms_loop.recall_on()` = `enabled()` (сервер лицензий пускает:
предлагается, включён, не Basic, имя одобрено, план активен — ⛔ не
`offered()`: у Basic он тоже `true`) ∧ галочка `clinic.json › sms.recall.on`.
Без гейта `sms: null` в конверте и ни слова об SMS на экране.

### `POST /api/recall/sms`

Тело `{pid, service_id}`. Сервер программы сам строит текст
(`sms_plan.recall_text(lang, variant, clinic, phone)` — язык из фиши,
вариант из настроек, подстановки только `{clinica}` и `{telefon}`), ключ
`recall:{pid}:{service_id}:{cycle_appt_id}` (`sms_plan.recall_idem`), шлёт
синхронно (`wire.send`, в потоке, таймаут 10 с) мимо очереди напоминаний и
на `OK` пишет: строку `sms_log` (`kind recall`, `appt_id NULL`, `state
sent`, `cloud_id`), отметку `recall_marks(result='sms')`, летопись «SMS
trimis (rechemare <услуга>)» от имени вошедшего. Доставку опрашивает
штатный цикл (`_poll_status`), слова состояния — `sms_loop.EVENT`.

Ответы (`msg_json`): `ok_recall_sms` + `data: {state: "sent", balance}`;
422 `bad_recall`; 409 `recall_gone` (нет done-визита); 409 `recall_sms_off`
(гейт); 409 `recall_sms_refused` (`patients.sms_off`); 409 `recall_sms_phone`
(не мобильный РМ); 409 `recall_no_phone` (пустой телефон клиники); 409
`recall_sms_quiet` (21:00–08:00 по часам клиники, `sms_plan.awake`); 409
`recall_sms_dup` (строка `sms_log` с этим ключом уже есть — экран устарел);
409 `sms_denied` + `text` словами `sms_loop.WHY` по коду сервера
(`sms_balance`, `sms_cap`, `sms_quiet`…); 503 `sms_offline` / `sms_token`.
При любом отказе ни строки, ни отметки не пишется.

### `clinic.json › sms.recall`

`{on: bool, variant: "standard" | "scurt"}` в нормализаторе
`sms_plan.settings` (умолчание `on: true`, `standard`); экран Setări › SMS
получает `settings.recall`, `options.recall_variants`, `previews.recall`
(вариант → язык → `{text, segments}`). `sms_loop.active()` = `enabled()` ∧
(событие включено ∨ `recall.on`): лист acord, точка меню и галочка окна
записи следуют и за рекламациями.

### Сервер лицензий

`cloud/app/sms.KINDS` получает `recall`; остальное без изменений (ключ,
баланс, потолок, тихие часы, дедупликация по `(clinic_id, idem)`).
