FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY . /app

RUN pip install --upgrade pip \
    && pip install .

RUN adduser --disabled-password --gecos "" appuser || true
RUN chown -R appuser /app || true
USER appuser

EXPOSE 8000

CMD ["sh", "./entrypoints/run_api.sh"]
