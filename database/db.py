
from pathlib import Path
import sqlite3
from contextlib import contextmanager


# database/db.py -> database/ -> project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "app.db"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def get_connection():
    """Create and return a configured SQLite connection."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(
        DB_PATH,
        timeout=10
    )

    # Return rows that can be accessed by column name.
    connection.row_factory = sqlite3.Row

    # Enable foreign-key checks for this connection.
    connection.execute("PRAGMA foreign_keys = ON")

    # Wait briefly if another connection is writing.
    connection.execute("PRAGMA busy_timeout = 10000")

    return connection


def init_db():
    """Create database tables and indexes if they do not exist."""
    if not SCHEMA_PATH.exists():
        raise FileNotFoundError(
            f"Schema file not found: {SCHEMA_PATH}"
        )

    connection = get_connection()

    try:
        schema = SCHEMA_PATH.read_text(encoding="utf-8")
        connection.executescript(schema)
    finally:
        connection.close()


@contextmanager
def get_db():
    """
    Provide a database connection for one unit of work.

    Commit on success, roll back on failure, and always close.
    """
    connection = get_connection()

    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    init_db()
    print(f"Database initialized at: {DB_PATH}")
