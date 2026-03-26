FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

# Build deps for compiled packages (asyncpg, psycopg2-binary, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies first (better layer caching)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

# Copy source and install the project
COPY . .
RUN uv sync --frozen

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

# Use PORT env variable (Railway sets this dynamically)
ENV PORT=8000
EXPOSE 8000

# Use $PORT environment variable for Railway compatibility
CMD ["sh", "-c", "uvicorn src.main:app --host 0.0.0.0 --port ${PORT}"]
