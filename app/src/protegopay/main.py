from contextlib import asynccontextmanager

from fastapi import FastAPI

from .api.v1.auth import router as auth_router
from .db.session import init_db


@asynccontextmanager
async def _lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="ProtegoPay API",
    version="0.1.0",
    docs_url=None,   # disable Swagger UI in production
    redoc_url=None,
    lifespan=_lifespan,
)

app.include_router(auth_router)
