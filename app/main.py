"""ASGI entry point: uvicorn app.main:app --reload."""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes.conversations import router as conversations_router
from app.api.routes.health import router as health_router
from app.api.routes.orders import router as orders_router
from app.api.routes.status import router as status_router
from app.core.config import settings
from app.services.workspace import WorkspaceNotFound

app = FastAPI(title="Yefhamak API")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins,
                   allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type"])
app.include_router(health_router)
app.include_router(conversations_router)
app.include_router(orders_router)
app.include_router(status_router)


@app.exception_handler(WorkspaceNotFound)
async def resource_not_found(request: Request, error: WorkspaceNotFound):
    return JSONResponse(status_code=404, content={"detail": str(error)})
