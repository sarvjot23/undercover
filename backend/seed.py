"""Start the database again from data/: uv run -m backend.seed."""

from backend import db

db.reseed()
print(f"Reseeded {db.path()} from data/")
