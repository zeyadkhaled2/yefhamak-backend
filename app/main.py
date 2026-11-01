"""ASGI entry point: uvicorn app.main:app --reload."""
from fastapi import FastAPI

from app.api.routes.health import router as health_router

app = FastAPI(title="Yefhamak API")
app.include_router(health_router)
