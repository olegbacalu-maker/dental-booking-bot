# Юридические страницы сайта dentpilot.md — исходники (L11)

Сайт живёт отдельным репозиторием (GitHub Pages, статика без зависимостей);
здесь лежат две его страницы, потому что их текст **сторожат тесты** этого
репозитория: `tests/test_structure.py` («договор согласован с программой
дословно») и `cloud/tests/test_contract.py`. Правишь тексты — правь здесь,
прогони тесты, потом копируй на сайт.

```
termeni.html   Termeni și condiții — заменяет прежний файл сайта ЦЕЛИКОМ
privacy.html   Politica de confidențialitate — версия 24.09 с разделом 5
               «Datele contului clinicii»; прежние разделы 5–6 стали 6–7
```

Как выложить: скопировать оба файла в корень репозитория сайта как есть.
Ссылки из футера `index.html`/`ru.html` на `termeni.html` и `privacy.html`
уже стоят, в `sitemap.xml` оба адреса есть — поправить только `<lastmod>`.
Плейсхолдер `IDNO [____]` — заполнить тем же номером, что в футере сайта
(три места: футер, privacy, termeni).

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

Русской версии юр-страниц нет намеренно: румынский — опорный язык
юридических текстов сайта (README сайта), `ru.html` ссылается на те же
страницы.
