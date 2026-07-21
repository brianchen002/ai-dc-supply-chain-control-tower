"""SQLite loading + access for the dashboard.

Robustness notes:
  * Writes go to a local temp file, then land via atomic os.replace — live
    readers keep the old file; new connections see the new one. No reader
    ever observes a half-written database.
  * get_connection() validates the database (not just its existence) and
    rebuilds automatically if the file is missing OR corrupt, so a bad file
    can never wedge the app permanently.
  * DB path overridable via CT_DB env var.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
from pathlib import Path

import pandas as pd

from config.settings import DB_PATH


def write_tables(tables: dict[str, pd.DataFrame], db_path: Path = DB_PATH) -> None:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    tmp = Path(tmp_name)
    conn = sqlite3.connect(tmp)
    for name, df in tables.items():
        df.to_sql(name, conn, index=False, if_exists="replace")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_po_site ON purchase_orders(destination_site)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_po_supplier ON purchase_orders(supplier_name)")
    conn.commit()
    conn.close()

    # Land atomically: stage next to the destination, then os.replace (atomic
    # on the same filesystem). Fall back to plain copy on filesystems that
    # refuse the rename.
    staged = db_path.with_suffix(".db.new")
    shutil.copyfile(tmp, staged)
    try:
        os.replace(staged, db_path)
    except OSError:
        shutil.copyfile(staged, db_path)
        try:
            staged.unlink()
        except OSError:
            pass
    try:
        tmp.unlink()
    except OSError:
        pass


def _db_is_valid(db_path: Path) -> bool:
    """Cheap sanity check: file opens and contains the core table."""
    if not db_path.exists() or db_path.stat().st_size == 0:
        return False
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name='purchase_orders'").fetchone()
            if row is None:
                return False
            conn.execute("SELECT COUNT(*) FROM purchase_orders").fetchone()
            return True
        finally:
            conn.close()
    except sqlite3.Error:
        return False


def get_connection(db_path: Path = DB_PATH, ensure: bool = True) -> sqlite3.Connection:
    db_path = Path(db_path)
    if ensure and not _db_is_valid(db_path):
        # Missing OR corrupt: clear the bad file and rebuild everything.
        try:
            db_path.unlink()
        except OSError:
            pass
        from src.pipeline import run_pipeline
        run_pipeline(verbose=False)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=OFF")
    conn.row_factory = sqlite3.Row
    return conn


def query_df(conn: sqlite3.Connection, sql: str, params: tuple | dict = ()) -> pd.DataFrame:
    return pd.read_sql_query(sql, conn, params=params)
