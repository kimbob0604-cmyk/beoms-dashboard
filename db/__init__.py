import sqlite3
from pathlib import Path

DB_DIR = Path(__file__).parent
DB_PATH = DB_DIR / 'dashboard.db'
SCHEMA_PATH = DB_DIR / 'schema.sql'


# 이미 있는 테이블에 나중에 더한 열 (CREATE TABLE IF NOT EXISTS 로는 안 생기므로)
MIGRATIONS = [('ohlc_daily', 'chg', 'REAL'), ('dart_event', 'tm', 'TEXT')]


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_PATH.read_text(encoding='utf-8'))
    for table, col, typ in MIGRATIONS:
        if col not in {r[1] for r in conn.execute(f'PRAGMA table_info({table})')}:
            conn.execute(f'ALTER TABLE {table} ADD COLUMN {col} {typ}')
    return conn
