# Stage: builder — install deps and package the app
FROM python:3.12-alpine AS builder
WORKDIR /app

# Build deps needed to compile certain packages (psycopg2, asyncpg, etc.)
RUN apk add --no-cache gcc musl-dev libpq-dev

# Install uv for fast dependency resolution
RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
RUN uv pip install --system --no-cache -r pyproject.toml

COPY . .

# Stage: production
FROM python:3.12-alpine AS production
WORKDIR /app

# Runtime-only system libraries
RUN apk add --no-cache libpq && \
    addgroup -g 1001 -S appgroup && \
    adduser -S appuser -u 1001

# Copy installed packages and app source from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin/uvicorn /usr/local/bin/uvicorn
COPY --from=builder /app/src ./src
COPY --from=builder /app/migrations ./migrations
COPY --from=builder /app/migrate.py ./migrate.py

USER appuser

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD wget -qO- http://localhost:8000/health || exit 1
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
