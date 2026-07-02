"""SQLite 连接与初始化。用标准库 sqlite3，零额外依赖。"""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from . import config

_SCHEMA = Path(__file__).resolve().parent / "schema.sql"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """建表 + 首次灌入种子。"""
    conn = get_conn()
    try:
        conn.executescript(_SCHEMA.read_text(encoding="utf-8"))
        conn.commit()
        _seed_if_empty(conn)
    finally:
        conn.close()


def _seed_if_empty(conn: sqlite3.Connection) -> None:
    count = conn.execute("SELECT COUNT(*) AS c FROM entries").fetchone()["c"]
    if count > 0:
        return
    seed_path = config.SEED_PATH if config.SEED_PATH.exists() else config.REPO_SEED_PATH
    if not seed_path.exists():
        return
    entries = json.loads(seed_path.read_text(encoding="utf-8"))
    from .importer import insert_entries  # 延迟导入避免环
    inserted = insert_entries(conn, entries)
    conn.commit()
    print(f"[z-spanish] 种子导入完成：{inserted} 条来自 {seed_path.name}")


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
