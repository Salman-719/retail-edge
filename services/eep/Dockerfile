FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libffi-dev \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Explicit copies instead of COPY . . to avoid placing alembic/ at /app/alembic/,
# which would shadow the installed alembic pip package on sys.path and cause
# ModuleNotFoundError: No module named 'alembic.config' at runtime.
COPY app/ ./app/
COPY alembic.ini .
# Migrations live at db_migrations/ — matches script_location in alembic.ini.
COPY alembic/ ./db_migrations/
COPY schema.sql .
COPY proto/ ./proto/

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
