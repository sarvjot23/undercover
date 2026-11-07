"""The dashboard's build, served beside the API when it's there, as on Lambda.

Without the build, as with npm run dev, the backend serves only the API.
"""

from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException

DIST = Path(__file__).resolve().parent.parent / "dashboard" / "dist"


def serve_dashboard(app: FastAPI, dist: Path = DIST) -> None:
    """Serve the build's files at their paths, and index.html for any other page.

    Every path under /api/ is left to the API, so an unknown one is still a 404.
    """
    index = dist / "index.html"
    if not index.is_file():
        return
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.exception_handler(HTTPException)
    async def page_or_error(request: Request, error: HTTPException) -> Response:
        path = request.url.path
        if (
            error.status_code != status.HTTP_404_NOT_FOUND
            or request.method != "GET"
            or path.startswith("/api/")
        ):
            return await http_exception_handler(request, error)
        found = (dist / path.lstrip("/")).resolve()
        if found.is_file() and found.is_relative_to(dist):
            return FileResponse(found)
        return FileResponse(index)
