# Образ живого демо (demo.dentpilot.md): программа как у клиники (SQLite) +
# шлюз demo/gate.py. Контекст сборки — корень репозитория:
#     docker compose -f demo/docker-compose.yml build
# Клиент React собирается ЗДЕСЬ, как и в Build-Installer: бандл в репозитории
# не лежит (.gitignore), и образ без этого шага открывал бы пустые экраны.

FROM node:22-alpine AS client
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
# vite пишет в ../bot/app/static (vite.config.ts); tsc -b не нужен — типы
# проверяет прогон, а здесь нужен только бандл
RUN mkdir -p /src/bot/app/static/js /src/bot/app/static/css \
    && node node_modules/vite/bin/vite.js build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=Europe/Chisinau
WORKDIR /srv
COPY demo/requirements.txt /srv/demo/requirements.txt
RUN pip install --no-cache-dir -r /srv/demo/requirements.txt
COPY bot/app /srv/bot/app
COPY bot/*.py /srv/bot/
COPY --from=client /src/bot/app/static/js/bundle.js /srv/bot/app/static/js/bundle.js
COPY --from=client /src/bot/app/static/css/bundle.css /srv/bot/app/static/css/bundle.css
COPY --from=client /src/bot/app/static/js/three.js /srv/bot/app/static/js/three.js
COPY --from=client /src/bot/app/static/js/three-core.js /srv/bot/app/static/js/three-core.js
COPY demo /srv/demo
RUN useradd --create-home --uid 10001 demo && mkdir -p /data && chown demo:demo /data
USER demo
ENV DEMO_APP_DIR=/srv/bot DEMO_DATA=/data DEMO_HOST=0.0.0.0 DEMO_PORT=8090
EXPOSE 8090
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8090/demo/health', timeout=4).status == 200 else 1)"
CMD ["python", "-m", "demo.gate"]
