# Серверный запуск программы (SQLite в томе, вход по ADMIN_KEY) — тот же код,
# что у клиники. Контекст сборки — КОРЕНЬ репозитория (docker-compose.yml):
#     docker compose up -d --build
# Клиент React собирается здесь, как в Build-Engine и demo/Dockerfile: бандл в
# репозитории не лежит (.gitignore), и образ без этого шага открывал бы пустые
# экраны — так и было до 03.11.2026.

FROM node:24-alpine AS client
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
# vite пишет в ../bot/app/static (vite.config.ts): бандл, three.js, модели
# зубов. tsc -b не нужен — типы проверяет CI, здесь нужен только бандл.
RUN mkdir -p /src/bot/app/static/js /src/bot/app/static/css \
    && node node_modules/vite/bin/vite.js build

FROM python:3.14.6-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
# Те же версии, что едут клинике, с хешами. sqlcipher3 помечен win32 и сюда
# не ставится: ключ картотеки живёт под DPAPI Windows, на сервере шифрования нет.
COPY bot/requirements-desktop.lock /tmp/requirements.lock
RUN pip install --no-cache-dir --require-hashes --no-deps -r /tmp/requirements.lock \
    && rm /tmp/requirements.lock
COPY bot/app ./app
# Вся папка, а не список файлов: что положила сборка клиента, то и едет.
COPY --from=client /src/bot/app/static/ ./app/static/
# ⚠️ Процесс — root: clinic.json приходит томом С ХОСТА на запись (страница
# настроек пишет его обратно), и на Linux-хосте пользователь образа без
# совпадающего uid не смог бы сохранить настройки.
EXPOSE 8088
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8088/health', timeout=4).status == 200 else 1)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8088"]
