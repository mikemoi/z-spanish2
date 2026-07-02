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
    seed_dir = config.DATA_SEED_DIR if config.DATA_SEED_DIR.exists() else config.REPO_SEED_DIR
    if not seed_dir.exists():
        return
    # 读目录下所有 *.json，按文件名排序后合并，跨文件按 id 去重
    entries = []
    seen = set()
    files = sorted(seed_dir.glob("*.json"))
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError as ex:
            print(f"[z-spanish] 跳过无法解析的种子文件 {f.name}: {ex}")
            continue
        for e in data:
            eid = e.get("id")
            if eid and eid not in seen:
                seen.add(eid)
                entries.append(e)
    if not entries:
        return
    from .importer import insert_entries  # 延迟导入避免环
    inserted = insert_entries(conn, entries)
    conn.commit()
    print(f"[z-spanish] 种子导入完成：{inserted} 条，来自 {len(files)} 个文件")


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
