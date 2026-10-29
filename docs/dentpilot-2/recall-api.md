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
    mark: {result, word, until: "YYYY-MM-DD" | "", n_noanswer, at: "DD.MM", actor} | null,
    tab: "due" | "snoozed" | "stop"
  }],
  counts: {due, snoozed, stop},
  clinic: {name, phone},                        // для текста письма
  can_settings: bool                            // пустой экран: кнопка в Setări › Servicii (директор) или слово
}}
```

Порядок `rows`: без отметки сверху, самые просроченные первыми; «nu răspunde»
— вниз. Тело детерминировано в пределах дня (ни одного «сейчас»).

## `POST /api/recall/mark`

Тело `{pid, service_id, result, until?}`; `result` ∈ `contacted` («Sunat —
revine», прячет 14 дней) · `emailed` («E-mail trimis», 14 дней) · `noanswer`
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
