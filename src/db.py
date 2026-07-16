"""SQLite loading + access for the dashboard.

Retained from the OpsPilot build: SQLite is written to a local temp file and
byte-copied over the destination — atomic-ish, and immune to locking quirks
on mounted/network filesystems. DB path overridable via CT_DB env var.
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
    shutil.copyfile(tmp, db_path)
    try:
        tmp.unlink()
    except OSError:
        pass


def get_connection(db_path: Path = DB_PATH, ensure: bool = True) -> sqlite3.Connection:
    db_path = Path(db_path)
    if ensure and not db_path.exists():
        from src.pipeline import run_pipeline
        run_pipeline(verbose=False)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=OFF")
    conn.row_factory = sqlite3.Row
    return conn


def query_df(conn: sqlite3.Connection, sql: str, params: tuple | dict = ()) -> pd.DataFrame:
    return pd.read_sql_query(sql, conn, params=params)
