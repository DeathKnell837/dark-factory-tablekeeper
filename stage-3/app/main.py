from fastapi import FastAPI
from contextlib import asynccontextmanager
from db import init_db
from routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title="tablekeeper - Stage 3",
    description="Table capacity optimization, party size matching, and atomic waitlist auto-promotion on cancellation",
    version="3.0.0",
    lifespan=lifespan,
)

app.include_router(router)


@app.get("/health")
async def health():
    return {"status": "ok", "stage": 3, "waitlist_supported": True, "capacity_management": True}
