FROM node:20-alpine AS frontend-builder

WORKDIR /workspace/frontend

COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build


FROM python:3.12-slim

ARG APP_VERSION=0.1.0

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_VERSION=${APP_VERSION} \
    DATABASE_URL=sqlite:////data/targethub.db

WORKDIR /app

COPY backend/requirements.txt /app/requirements.txt
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

COPY backend/ /app
COPY --from=frontend-builder /workspace/frontend/dist /app/app/web/react

RUN useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin targethub \
    && mkdir -p /data /app/app/logs \
    && chown -R targethub:targethub /data /app/app/logs

USER targethub

VOLUME ["/data"]

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=4).status == 200 else 1)"

CMD ["sh", "./entrypoints/run_api.sh"]
