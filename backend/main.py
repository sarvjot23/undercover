"""The app as it's deployed: a web server runs backend.main:app, and Lambda runs
backend.main.handler, with the startup hook off so nothing seeds the database."""

from mangum import Mangum

from backend.api import app

handler = Mangum(app, lifespan="off")

__all__ = ["app", "handler"]
