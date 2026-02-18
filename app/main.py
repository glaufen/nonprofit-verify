from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from app.database import close_pool, get_pool
from app.routes.billing import router as billing_router
from app.routes.public import router as public_router
from app.routes.verify import router as verify_router
from app.utils.cache import close_redis, get_redis

STATIC_DIR = Path(__file__).parent / "static"


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

app.include_router(public_router, prefix="/api/v1", tags=["Public"])
app.include_router(verify_router, prefix="/api/v1", tags=["Verify"])
app.include_router(billing_router, prefix="/api/v1", tags=["Billing"])


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def landing_page():
    return (STATIC_DIR / "index.html").read_text()


@app.get("/success", response_class=HTMLResponse, include_in_schema=False)
async def success_page():
    return (STATIC_DIR / "success.html").read_text()


@app.get("/health", tags=["System"])
async def health():
    return {"status": "ok"}
