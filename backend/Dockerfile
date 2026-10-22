FROM node:20-alpine AS frontend-builder

WORKDIR /workspace/frontend

COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build


FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DATABASE_URL=sqlite:////data/targethub.db

WORKDIR /app

COPY backend/ /app
COPY --from=frontend-builder /workspace/frontend/dist /app/app/web/react

RUN pip install --upgrade pip \
    && pip install -r requirements.txt

VOLUME ["/data"]

EXPOSE 8000

CMD ["sh", "./entrypoints/run_api.sh"]
