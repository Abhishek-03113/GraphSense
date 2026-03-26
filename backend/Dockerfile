FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

# Build deps for compiled packages (asyncpg, psycopg2-binary, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies first (better layer caching)
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-install-project

# Copy source and install the project
COPY backend/ .
RUN uv sync --frozen

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

ENV PORT=8080
EXPOSE 8080

CMD ["sh", "-c", "uvicorn src.main:app --host 0.0.0.0 --port ${PORT}"]
