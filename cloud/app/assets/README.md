# Шрифт для PDF (cont de plată)

Здесь лежат `Inter-Regular.ttf` и `Inter-SemiBold.ttf` из релиза Inter 4.1
(https://github.com/rsms/inter/releases, `extras/ttf`; 17.10.2026) — тот же
шрифт, что на сайте и в программе. Лицензия SIL OFL 1.1 — `Inter-LICENSE.txt`
рядом, как она требует. ⛔ Только TrueType (`.ttf` с таблицей `glyf`):
OpenType-CFF (`.otf`) и `woff2` генератор (`app/pdf.py`) не разбирает.

Без файла `app/pdf.py` набирает документ Helvetica и снимает диакритику
(ă→a, ș→s, ț→t) — об этом говорит `python -m app.tools check`. Dockerfile
копирует `app` целиком, поэтому положенный сюда файл едет в образ сам.

# Образцы закона 195 для клиники (`modele/`, 31.10.2026)

HTML-листы «Modele pentru clinică» вкладки «Documente» кабинета: `informare-pacienti`, `registru-prelucrare`,
`bitlocker`, `lista-verificare`. Открывает их `/cont/modele/{key}` (`app/modele.py`) с реквизитами клиники;
жёлтые поля заполняются в странице, Ctrl+P. Правка листа = новая дата «redacția din …» в файле и в
`modele.MODELE` (держит `tests/test_modele.py`). Комментариев разработчика в листах нет: клиника видит
«Просмотр кода». Прежние редакции — архив `clinics\lege-195\arhiva\` корня проекта.
