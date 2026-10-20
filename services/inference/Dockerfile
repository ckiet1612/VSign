FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY services/inference/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY services/inference/app ./app
COPY services/inference/alembic.ini ./alembic.ini
COPY services/inference/migrations ./migrations
COPY contracts ./contracts

EXPOSE 8000
CMD ["sh", "-c", "python -m app.migrate && uvicorn app.main:app --host 0.0.0.0 --port 8000 --ws-max-size 6291456"]
