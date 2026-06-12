FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY service/pyproject.toml .
RUN uv pip install --system --no-cache -e "." && \
    uv pip install --system --no-cache asyncpg psycopg2-binary

COPY service/app ./app
COPY service/templates ./templates
COPY service/seed.py ./seed.py

RUN mkdir -p ./static

EXPOSE 10000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "10000"]
