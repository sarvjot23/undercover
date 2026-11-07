"""The UnderCover backend: uv run -m uvicorn backend.api:app."""

import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend import agent_api, db, static
from backend.routes import (
    claims,
    configuration,
    documents,
    evaluations,
    library,
    records,
    rounds,
    runs,
    settings,
    usage,
)
from backend.turns import TakingTurns


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Create and seed the database."""
    db.init()
    threading.Thread(target=db.warm_up, daemon=True).start()
    yield


app = FastAPI(title="UnderCover", lifespan=lifespan)
app.add_middleware(TakingTurns)
app.include_router(claims.router)
app.include_router(documents.router)
app.include_router(library.router)
app.include_router(runs.router)
app.include_router(usage.router)
app.include_router(evaluations.router)
app.include_router(configuration.router)
app.include_router(settings.router)
app.include_router(rounds.router)
app.include_router(records.router)
app.include_router(agent_api.router)


@app.get("/api/health", operation_id="health")
def health() -> dict[str, str]:
    """Check that the backend is running."""
    return {"status": "ok"}


static.serve_dashboard(app)
