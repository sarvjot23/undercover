"""The UnderCover backend: uv run -m uvicorn backend.api:app."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend import db
from backend.routes import claims, documents, library, runs
from backend.rules import recover


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Create and seed the database, and recover any claim a crash left stuck."""
    db.init()
    with db.engine().connect() as conn:
        recover(conn)
    yield


app = FastAPI(title="UnderCover", lifespan=lifespan)
app.include_router(claims.router)
app.include_router(documents.router)
app.include_router(library.router)
app.include_router(runs.router)


@app.get("/api/health", operation_id="health")
def health() -> dict[str, str]:
    """Check that the backend is running."""
    return {"status": "ok"}
