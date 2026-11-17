
from fastapi import FastAPI
from app.gateway.routes import router as gateway_router

app = FastAPI(
    title="YantGuard Security Orchestrator",
    description="AI Gateway for Gemini and Groq",
    version="0.1.0"
)

app.include_router(gateway_router)


@app.get("/health")
def health_check():
    return {
        "status": "running",
        "service": "YantGuard"
    }
