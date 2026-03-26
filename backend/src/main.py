from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.api.graph import router as graph_router
from src.api.ingest import router as ingest_router
from src.api.chat import router as chat_router

app = FastAPI(
    title="DodgeAI",
    description="Graph-Based Data Modeling and Query System",
    version="0.1.0",
)

# Setup CORS middleware — allow all origins for now (TODO: restrict for production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(graph_router)
app.include_router(ingest_router)
app.include_router(chat_router)


@app.get("/api/health")
async def health_check():
    return {"status": "ok"}
