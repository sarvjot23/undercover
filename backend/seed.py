"""Start the database again from data/: uv run -m backend.seed."""

from dotenv import load_dotenv

from backend import db

load_dotenv(override=True)
db.reseed()
print(f"Seeded {'Supabase' if db.database_url() else 'SQLite'} from data/")
