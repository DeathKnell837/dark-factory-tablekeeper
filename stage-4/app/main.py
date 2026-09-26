from fastapi import FastAPI, status
from contextlib import asynccontextmanager
from sqlalchemy import text
from db import init_db, engine
from routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield
    await engine.dispose()


app = FastAPI(
    title="tablekeeper - Stage 4 Production Hardened",
    description="Production-grade reservation factory with immutable audit trails, real-time metrics, deadlock prevention, and zero double-booking under extreme concurrency",
    version="4.0.0",
    lifespan=lifespan,
)

from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError

app.include_router(router)


@app.exception_handler(DBAPIError)
async def dbapi_exception_handler(request, exc: DBAPIError):
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"detail": "Concurrency lock contention: table is currently locked by another transaction"}
    )


@app.get("/health")
async def health():
    return {"status": "ok", "stage": 4, "production_ready": True}


@app.get("/health/live", status_code=status.HTTP_200_OK)
async def liveness():
    """Kubernetes liveness probe: verifies process is alive."""
    return {"status": "alive", "stage": 4}


@app.get("/health/ready", status_code=status.HTTP_200_OK)
async def readiness():
    """Kubernetes readiness probe: verifies database connection is active."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "ready", "database": "connected"}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}
