FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini .
COPY migrations ./migrations

RUN useradd --system --no-create-home appuser
USER appuser

# Job a usage unique : applique les migrations puis s'arrete
CMD ["alembic", "upgrade", "head"]
