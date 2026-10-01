# Живое демо с сайта — demo.dentpilot.md

Кнопка «Încearcă demo online» на сайте открывает НАСТОЯЩУЮ программу:
каждому посетителю — своя копия демо-клиники на час, с данными «на сегодня»,
потом сброс. Это настольное издание (SQLite, как у клиники) с флагом
`DENTART_DEMO=1` за шлюзом `gate.py`. Код демо лежит здесь, вне `bot/`: в exe
клиники и в облачное издание он не едет.

| Файл | Что |
|---|---|
| `gate.py` | шлюз: пул процессов программы, слот на посетителя, сброс по времени |
| `seed.py` | засев демо-клиники от «сейчас» (визиты, план, долги, одонтограммы…) |
| `clinic.json`, `photos/` | профиль демо-клиники и фото врачей (сгенерированные) |
| `Dockerfile`, `docker-compose.yml` | образ (клиент React собирается внутри) и стек с туннелем |
| `docker-compose.local.yml` | локальная проверка образа на 127.0.0.1:8090 |
| `update.sh` | обновить демо до тега выпуска на сервере |
| `.env.example` | `TUNNEL_TOKEN` и размер пула — вписывает владелец |

Что программа делает иначе в демо — `bot/app/core/demo.py` (один флаг, один
список закрытых адресов, баннер на каждом экране); сторожа —
`tests/test_demo.py` и правило «список демо-отказов не протух» в
`tests/test_structure.py`.

## Как это работает

1. При старте шлюз собирает **шаблон**: папка с `clinic.json` и фото, в
   которой программа запускается один раз (схема, миграции) и гасится.
2. Каждый **слот** = копия шаблона + `seed.py` (даты от текущего момента) +
   свой процесс `uvicorn app.main:app` на 127.0.0.1:91xx со своим случайным
   `ADMIN_KEY`. Шлюз сам входит ключом и подставляет куку входа в каждый
   проксируемый запрос; посетитель видит только куку шлюза `dp_demo`.
3. Посетитель без куки получает свободный слот на `DEMO_TTL_MIN` минут.
   Истёкшие, упавшие и залежавшиеся свободные слоты (30 мин) фоновый цикл
   пересобирает. Все заняты — страница «locurile sunt ocupate» с
   автообновлением.
4. `/demo/reset` — свежая копия («Începe din nou» в баннере),
   `/admin/logout` — на сайт, `/demo/health` — состояние пула (его
   спрашивает healthcheck контейнера).

Память (измерено 01.10 в образе): шлюз + 2 процесса программы ≈ 140 МБ, то
есть ≈ 45–60 МБ на слот; пул из 6 — около 0.4 ГБ при лимите контейнера 2 ГБ.
Данные — tmpfs на 1 ГБ (`mode: 0o1777`: процесс в образе не root): копия
живёт час, диск сервера не трогается. Старт слота — 2–3 с, сброс столько же.

## Локально, без Docker

```powershell
cd D:\DentProject\app
$env:DEMO_PYTHON = "D:\DentProject\app\.venv-desktop\Scripts\python.exe"   # программа — из venv сборки
$env:DEMO_DATA = "$env:LOCALAPPDATA\DentPilot-demo"; $env:DEMO_SLOTS = "2"; $env:DEMO_SECURE_COOKIE = "0"
D:\DentProject\sandbox\demo-venv\Scripts\python.exe -X utf8 -m demo.gate      # шлюз — свой venv (httpx, starlette, tzdata)
```

Бандл React должен быть собран (`frontend`: `node node_modules\vite\bin\vite.js build`).
`http://127.0.0.1:8090/` → журнал демо.

## Локально, образ

```powershell
docker compose -f demo/docker-compose.yml -f demo/docker-compose.local.yml up -d --build
# http://127.0.0.1:8090/ ; docker compose -f demo/docker-compose.yml logs -f demo
```

## На сервере (маркетплейс, 13.140.191.129, пользователь deploy)

Сервер — продакшн маркетплейса: демо стоит рядом своим проектом compose, в
своей сети, с лимитами; их nginx и сертификаты не трогаются. Наружу —
только Cloudflare Tunnel, порт на хост не публикуется.

```bash
git clone https://github.com/olegbacalu-maker/dental-booking-bot.git ~/dentpilot-demo/src
cd ~/dentpilot-demo/src && git checkout v1.36.0        # тег выпуска, в котором есть demo/
cd demo && cp .env.example .env && nano .env            # TUNNEL_TOKEN — владелец
docker compose --profile tunnel up -d --build
curl -s http://127.0.0.1:8090/demo/health || docker compose exec demo python -c "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8090/demo/health').read())"
```

Туннель: Cloudflare Zero Trust › Networks › Tunnels › Create → имя
`dentpilot-demo`, коннектор Docker (токен — в `.env`), Public hostname:
`demo.dentpilot.md` → `http://demo:8090`. Запись DNS Cloudflare создаёт сам
(проксированная; апекс dentpilot.md остаётся DNS-only на GitHub Pages).

Обновление под выпуск: `~/dentpilot-demo/src/demo/update.sh vX.Y.Z`.

## Чего в демо нет (и почему)

Обновление, ключ картотеки, копия и восстановление, PIN и пользователи,
токен бота, сеть клиники, лицензия, раздвоение — всё, что меняет машину
или учётки. Список — `BLOCKED` в `core/demo.py`; и страницы, и JSON, и плитки
хаба закрываются ОДНИМ списком. Сканер в контейнере недоступен (нет WIA),
загрузка файлов — до 8 МБ. Остальное — как у клиники.
