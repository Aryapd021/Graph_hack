# Multi-stage Dockerfile for Company Brain Production Deployment
# Builds React frontend SPA and runs FastAPI backend serving both API and static UI

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
    SERVE_STATIC=true \
    PORT=8000

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY backend/pyproject.toml ./backend/
RUN pip install --no-cache-dir -e ./backend

COPY backend/ ./backend/
COPY data/ ./data/

# Copy built frontend static files to /app/static
COPY --from=frontend-builder /app/web/dist /app/static

EXPOSE 8000

CMD ["sh", "-c", "python -m uvicorn brain_api.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
