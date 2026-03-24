from fastapi import FastAPI

app = FastAPI(title="DodgeAI", description="Graph-Based Data Modeling and Query System", version="0.1.0")

@app.get("/health")
async def health_check():
    return {"status": "ok"}
