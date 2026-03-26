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

# Copy source and install the project (editable install via hatchling)
COPY src/ src/
COPY migrations/ migrations/
COPY migrate.py README.md ./
RUN uv sync --frozen

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
