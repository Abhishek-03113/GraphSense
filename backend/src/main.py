import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.chat import router as chat_router
from src.api.errors import install_error_handling
from src.api.graph import router as graph_router
from src.api.ingest import router as ingest_router
from src.db.engine import dispose_engine
from src.utils.logger import get_logger

logger = get_logger(__name__)


def _cors_origins() -> list[str]:
    """Allowed origins from ``CORS_ALLOW_ORIGINS`` (comma separated).

    ``*`` is only honoured outside production: with ``GRAPHSENSE_ENV=production``
    and no explicit list, no cross-origin access is granted.
    """
    raw = os.environ.get("CORS_ALLOW_ORIGINS", "").strip()
    production = os.environ.get("GRAPHSENSE_ENV", "dev").strip().lower() == "production"
    origins = [o.strip() for o in raw.split(",") if o.strip()]
    if production:
        if "*" in origins:
            logger.warning("CORS_ALLOW_ORIGINS=* is ignored in production")
        return [o for o in origins if o != "*"]
    return origins or ["*"]


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await dispose_engine()


app = FastAPI(
    title="GraphSense",
    description="Graph-Based Data Modeling and Query System",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)
# Added last so it is the outermost layer: every response, including CORS
# preflights and errors, carries a request id.
install_error_handling(app)

# Register routers
app.include_router(graph_router)
app.include_router(ingest_router)
app.include_router(chat_router)


@app.get("/api/health")
async def health_check():
    return {"status": "ok"}
