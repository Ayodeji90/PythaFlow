from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import models  # noqa: F401 — register tables
from .database import Base, SessionLocal, engine
from .routers import dashboard, guests, menu, misc, orders
from .seed import seed_if_empty


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed_if_empty(db)
    yield


app = FastAPI(
    title="PythaFlow — Graycliff AI Platform",
    description="Five AI solutions for Graycliff Hotel & Restaurant, Nassau.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(menu.router)
app.include_router(orders.router)
app.include_router(guests.router)
app.include_router(misc.router)
app.include_router(dashboard.router)


@app.get("/api/health")
def health():
    return {"status": "ok", "platform": "PythaFlow Graycliff demo"}
