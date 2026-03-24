from fastapi import FastAPI
from src.api.ingest import router as ingest_router

app = FastAPI(title="DodgeAI", description="Graph-Based Data Modeling and Query System", version="0.1.0")

app.include_router(ingest_router)

@app.get("/health")
async def health_check():
    return {"status": "ok"}
