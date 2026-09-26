# Юридические страницы сайта dentpilot.md — исходники (L11)

Сайт живёт отдельным репозиторием (GitHub Pages, статика без зависимостей);
здесь лежат его страницы с юридическим текстом, потому что их текст
**сторожат тесты** этого репозитория: `tests/test_structure.py` («договор
согласован с программой дословно», «текст перед скачиванием называет кнопки
программы её словами») и `cloud/tests/test_contract.py`. Правишь тексты —
правь здесь, прогони тесты, потом копируй на сайт.

```
termeni.html       Termeni și condiții — заменяет прежний файл сайта ЦЕЛИКОМ
privacy.html       Politica de confidențialitate — версия 24.09 с разделом 5
                   «Datele contului clinicii»; прежние разделы 5–6 стали 6–7
descarca.html      Înainte de descărcare: Legea 195/2024 — текст перед кнопкой
                   «Descarcă» (L15); новая страница
descarca-ru.html   она же по-русски (перевод; опорная — румынская)
```

Как выложить: скопировать оба файла в корень репозитория сайта как есть.
Ссылки из футера `index.html`/`ru.html` на `termeni.html` и `privacy.html`
уже стоят, в `sitemap.xml` оба адреса есть — поправить только `<lastmod>`.
Плейсхолдер `IDNO [____]` — заполнить тем же номером, что в футере сайта
(три места: футер, privacy, termeni).

Форма пробного периода (L14) живёт на сервере лицензий, а не на сайте:
поставить на `index.html`/`ru.html` ссылку «Perioadă de probă 14 zile» →
`https://cloud.dentpilot.md/proba` (ссылка, не форма: без CORS и без второго
origin). Страница сама ссылается на `termeni.html` и `privacy.html` сайта.

Что в этих текстах привязано к коду и проверяется:

| Текст на странице | Откуда в коде |
|---|---|
| «perioadă de probă de 14 zile» | `cloud/app/license.py` `TRIAL_DAYS` |
| «încă 3 zile (perioada pentru abonare)» | `TRIAL_GRACE_DAYS` |
| «încă 14 zile (perioada de plată)» | `GRACE_DAYS` |
| «14 zile de la prima pornire» | `bot/app/core/license_state.py` `NO_FILE_GRACE` |
| «Datele se pot consulta, tipări și exporta» | баннер `license_readonly` в `bot/app/core/layout.py` |
| «Datele pacienților se pot consulta, tipări și exporta, iar copia de rezervă…» | письма `cloud/app/mail.py` |
| «1, 3, 6 sau 12 luni» | `cloud/app/payments.py` `MONTHS` |
| «oricare este mai târzie» — правило продления | `payments.extend_from` |
| `cloud.dentpilot.md` в privacy | `DP_BASE_URL` в `cloud/app/config.py` |
| «…» на `descarca*.html` — надписи экранов | исходники клиента `frontend/src` |
| `Setări › X` на `descarca*.html` | плитки `_hub_tiles` в `bot/app/modules/settings/routes.py` |
| телефон, почта, `…/proba` на `descarca*.html` | `cloud/app/config.py` |

Русской версии юр-страниц нет намеренно: румынский — опорный язык
юридических текстов сайта (README сайта), `ru.html` ссылается на те же
страницы. `descarca-ru.html` — исключение: это не договор, а памятка перед
установкой, и с `ru.html` клиника должна прочесть её по-русски; строка на
странице говорит, что опорная — румынская.

## Текст перед скачиванием (закон 195)

Клиника, которая скачивает программу сама, минует звонок и шаг «Documentele
Legea 195 — vă ghidăm pas cu pas» из «Cum începem»: закон 195 ей объясняет
только эта страница. Что в ней: оператор данных — клиника; что сделать до
первого пациента (BitLocker, PIN каждому, информирование, реестр, копии);
кнопки фиши для запросов пациента; что остаётся за клиникой (72 часа на
уведомление CNPDCP); где взять шаблоны. Всё, что она говорит о программе, —
то, что программа делает сейчас; факты закона сверены по публикациям CNPDCP
(закон от 25.07.2024, в силе с 23.08.2026).

Как выложить — **вместе с L15, не раньше**:

- кнопка «Descarcă» на `index.html` ведёт на `descarca.html`, на `ru.html` —
  на `descarca-ru.html`; сам файл скачивается кнопкой в конце страницы;
- `[LINK-DESCARCARE]` на обеих страницах — заменить ссылкой на подписанный
  установщик из GitHub Releases (L15);
- в `sitemap.xml` — две записи с `hreflang`, как у `index.html`/`ru.html`.

Правило записи, которое читает `tests/test_structure.py`: в «ёлочках» — только
надписи экранов программы (каждая обязана найтись в клиенте целиком), путь
настроек — `<b>Setări › X</b>`, где X — плитка хаба; прочие кавычки — „…”.
Обе версии называют одни и те же кнопки. Переименовал кнопку в программе —
прогон покажет, какую строку сайта поправить.

⚠️ Обещание, которое держится руками: «Vi le trimitem pe e-mail la începutul
perioadei de probă» — шаблоны из папки lege-195 уходят клинике письмом в
начале пробного. Сервер этого не делает: письмо с файлом лицензии
(`mail.license_letter`) несёт только `license.json`.
