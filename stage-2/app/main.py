from fastapi import FastAPI
from contextlib import asynccontextmanager
from db import init_db
from routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title="tablekeeper - Stage 2",
    description="Timezone-aware restaurant reservations with safe idempotent retries and zero double-booking",
    version="2.0.0",
    lifespan=lifespan,
)

app.include_router(router)


@app.get("/health")
async def health():
    return {"status": "ok", "stage": 2, "timezones_supported": True}
