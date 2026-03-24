from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.api.graph import router as graph_router
from src.api.ingest import router as ingest_router

app = FastAPI(
    title="DodgeAI",
    description="Graph-Based Data Modeling and Query System",
    version="0.1.0",
)

# Setup CORS middleware to allow frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(graph_router)
app.include_router(ingest_router)


@app.get("/health")
async def health_check():
    return {"status": "ok"}
