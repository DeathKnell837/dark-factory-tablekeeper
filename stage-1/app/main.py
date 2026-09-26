from fastapi import FastAPI
from contextlib import asynccontextmanager
from db import init_db
from routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title="tablekeeper",
    description="Restaurant reservation system - a table is never double-booked",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(router)


@app.get("/health")
async def health():
    return {"status": "ok"}
