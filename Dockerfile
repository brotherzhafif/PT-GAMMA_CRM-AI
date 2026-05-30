# ==========================================
# STAGE 1: Builder
# ==========================================
FROM python:3.12-slim AS builder

WORKDIR /app

# Install build essentials jika ada library python yang butuh di-compile (C extensions)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements dan buat Python Wheels (binary package siap install)
COPY requirements.txt .
RUN pip wheel --no-cache-dir --no-deps --wheel-dir /app/wheels -r requirements.txt


# ==========================================
# STAGE 2: Production (Final Image)
# ==========================================
FROM python:3.12-slim

WORKDIR /app

# Salinkan wheels dari stage builder
COPY --from=builder /app/wheels /wheels
COPY --from=builder /app/requirements.txt .

RUN pip install --no-cache-dir --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels

# Copy seluruh source code utama
COPY . .

EXPOSE 5000

# Set environment agar python tidak menulis file .pyc ke disk dan langsung flush log
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

CMD ["uvicorn", "App.app:app", "--host", "0.0.0.0", "--port", "5000"]