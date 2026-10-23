from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.admin import mount_admin
from src.api.catalog import router as catalog_router
from src.api.chat import router as chat_router
from src.api.datasets import router as datasets_router
from src.api.errors import install_error_handling
from src.api.graph import router as graph_router
from src.api.ingest import router as ingest_router
from src.config import get_settings
from src.storage.engines import dispose_all
from src.utils.logger import get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await dispose_all()


_settings = get_settings()
_cors_origins = _settings.cors_origins()
if _settings.is_production and "*" in _settings.CORS_ALLOW_ORIGINS:
    logger.warning("CORS_ALLOW_ORIGINS=* is ignored in production")

app = FastAPI(
    title="GraphSense",
    description="Graph-Based Data Modeling and Query System",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
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
app.include_router(datasets_router)
app.include_router(catalog_router)
# Operator routes exist only when ADMIN_TOKEN is set.
mount_admin(app)


@app.get("/api/health")
async def health_check():
    return {"status": "ok"}
