from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database import close_pool, get_pool
from app.routes.verify import router as verify_router
from app.utils.cache import close_redis, get_redis


@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_pool()
    await get_redis()
    yield
    await close_pool()
    await close_redis()


app = FastAPI(
    title="NonprofitVerify API",
    description="Verify any US nonprofit in one API call. Returns 501(c)(3) status, financials, personnel, and state registrations.",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(verify_router, prefix="/api/v1", tags=["Verify"])


@app.get("/health", tags=["System"])
async def health():
    return {"status": "ok"}
