FROM python:3.13-slim
WORKDIR /srv/cloud
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
# База и ключ приходят томами; секреты — окружением (см. README.md)
ENV DP_CLOUD_DB=/srv/data/cloud.db
EXPOSE 8090
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8090", "--proxy-headers"]
