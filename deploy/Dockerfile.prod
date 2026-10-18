# Multi-stage Dockerfile for Company Brain Production Deployment
# Per ARCHITECTURE.md Section 18b:
# 1. Node stage: build frontend web/dist
# 2. Python stage: install backend, copy web/dist to /app/static, start uvicorn

# --- Stage 1: Build Frontend SPA ---
FROM node:20-alpine AS frontend-builder
WORKDIR /app/web

COPY web/package.json web/package-lock.json* ./
RUN npm install

COPY web/ ./
RUN npm run build

# --- Stage 2: Production Python API Service ---
FROM python:3.11-slim AS production

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/backend \
    SERVE_STATIC=true \
    PORT=8000

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY backend/ ./backend/
RUN pip install --no-cache-dir ./backend

COPY data/ ./data/

# Copy built frontend static files to /app/static
COPY --from=frontend-builder /app/web/dist /app/static

EXPOSE 8000

CMD ["sh", "-c", "python -m uvicorn brain_api.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
