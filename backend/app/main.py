from fastapi import FastAPI

app = FastAPI(
    title="TargetHub",
    version="0.1.0",
    description="Embedded Lab Orchestration Platform",
)

@app.get("/")
async def root():
    return {
        "application": "TargetHub",
        "status": "running"
    }

@app.get("/health")
async def health():
    return {
        "status": "healthy"
    }
