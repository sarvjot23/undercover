"""The UnderCover backend: uv run -m uvicorn backend.api:app."""

import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend import db
from backend.routes import claims, documents, library, runs, usage


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Create and seed the database."""
    db.init()
    threading.Thread(target=db.warm_up, daemon=True).start()
    yield


app = FastAPI(title="UnderCover", lifespan=lifespan)
app.include_router(claims.router)
app.include_router(documents.router)
app.include_router(library.router)
app.include_router(runs.router)
app.include_router(usage.router)


@app.get("/api/health", operation_id="health")
def health() -> dict[str, str]:
    """Check that the backend is running."""
    return {"status": "ok"}
