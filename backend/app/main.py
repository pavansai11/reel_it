"""FastAPI app: routes, CORS, DB init, and (in local dev) static file serving."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import settings
from .db import init_db
from .routes import feedback, job, upload

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin, "http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Reelmagic-Job"],
)


# In local/filesystem mode, serve generated media back to the browser.
if settings.storage_backend == "local":
    settings.local_storage_path.mkdir(parents=True, exist_ok=True)
    app.mount(
        "/files",
        StaticFiles(directory=str(settings.local_storage_path)),
        name="files",
    )


@app.get("/health")
def health():
    from .guards import spend_ceiling_exceeded, today_spend_usd

    return {
        "status": "ok",
        "app": settings.app_name,
        "storage": settings.storage_backend,
        "scoring": settings.scoring_backend,
        "edit_brain": "claude" if settings.anthropic_api_key else "heuristic",
        "today_spend_usd": round(today_spend_usd(), 4),
        "paused": spend_ceiling_exceeded(),
    }


app.include_router(upload.router, tags=["upload"])
app.include_router(job.router, tags=["job"])
app.include_router(feedback.router, tags=["feedback"])
