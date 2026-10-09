import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import models  # noqa: F401 — регистрирует таблицы в Base.metadata
from config import BASE_DIR, settings
from database import Base, SessionLocal, engine
from router import api
from seed import seed
from services import PUBLIC_MEDIA_PREFIX

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    (settings.storage_dir / PUBLIC_MEDIA_PREFIX).mkdir(parents=True, exist_ok=True)
    with SessionLocal() as db:
        seed(db)
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api)

(settings.storage_dir / PUBLIC_MEDIA_PREFIX).mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=settings.storage_dir / PUBLIC_MEDIA_PREFIX), name="media")
app.mount("/", StaticFiles(directory=BASE_DIR / "frontend", html=True), name="frontend")
