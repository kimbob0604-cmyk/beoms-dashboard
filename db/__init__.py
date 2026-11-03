import sqlite3
from pathlib import Path

DB_DIR = Path(__file__).parent
DB_PATH = DB_DIR / 'dashboard.db'
SCHEMA_PATH = DB_DIR / 'schema.sql'


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_PATH.read_text(encoding='utf-8'))
    return conn
