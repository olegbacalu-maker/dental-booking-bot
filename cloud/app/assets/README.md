# Шрифт для PDF (cont de plată)

Здесь лежат `Inter-Regular.ttf` и `Inter-SemiBold.ttf` из релиза Inter 4.1
(https://github.com/rsms/inter/releases, `extras/ttf`; 17.10.2026) — тот же
шрифт, что на сайте и в программе. Лицензия SIL OFL 1.1 — `Inter-LICENSE.txt`
рядом, как она требует. ⛔ Только TrueType (`.ttf` с таблицей `glyf`):
OpenType-CFF (`.otf`) и `woff2` генератор (`app/pdf.py`) не разбирает.

Без файла `app/pdf.py` набирает документ Helvetica и снимает диакритику
(ă→a, ș→s, ț→t) — об этом говорит `python -m app.tools check`. Dockerfile
копирует `app` целиком, поэтому положенный сюда файл едет в образ сам.
