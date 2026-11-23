
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from app.dashboard.routes import api as dashboard_api, router as dashboard_router
from app.gateway.routes import router as gateway_router
from app.governance.db import init_db
from app.governance.request_log import GATEWAY_PATH, RequestLogMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()  # create yantguard.db and its tables on server start
    yield


app = FastAPI(
    title="YantGuard Security Orchestrator",
    description="AI Gateway for Gemini and Groq",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(RequestLogMiddleware)
app.include_router(gateway_router)
app.include_router(dashboard_router)
app.include_router(dashboard_api)


def custom_openapi():
    """Add an 'Authorize' button to /docs for the X-API-Key header."""
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title, version=app.version,
        description=app.description, routes=app.routes,
    )
    schema.setdefault("components", {}).setdefault("securitySchemes", {})["ApiKeyAuth"] = {
        "type": "apiKey", "in": "header", "name": "X-API-Key",
    }
    post = schema.get("paths", {}).get(GATEWAY_PATH, {}).get("post")
    if post is not None:
        post["security"] = [{"ApiKeyAuth": []}]
    app.openapi_schema = schema
    return schema


app.openapi = custom_openapi


@app.get("/health")
def health_check():
    return {
        "status": "running",
        "service": "YantGuard"
    }
