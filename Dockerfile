FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY service/pyproject.toml .
RUN uv pip install --system --no-cache -e "." && \
    uv pip install --system --no-cache asyncpg psycopg2-binary

COPY service/app ./app
COPY service/templates ./templates
COPY service/seed.py ./seed.py
COPY marketplace-src ./marketplace-src
COPY luna-plugin-dev-kit ./luna-plugin-dev-kit

RUN mkdir -p ./static

# Core-plugin source + durable artifact storage (Render persistent disk at /data).
ENV MARKETPLACE_SRC=/app/marketplace-src
ENV ARTIFACTS_DIR=/data/artifacts
ENV DEV_KIT_DIR=/app/luna-plugin-dev-kit

EXPOSE 10000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "10000"]
