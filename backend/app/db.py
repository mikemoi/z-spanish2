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
    """建表 + 同步种子（内容以种子文件为准，每次启动刷新，不动复习进度）。"""
    conn = get_conn()
    try:
        conn.executescript(_SCHEMA.read_text(encoding="utf-8"))
        conn.commit()
        _sync_seed(conn)
    finally:
        conn.close()


def _load_seed_entries():
    """读 seed 目录下所有 *.json，合并、跨文件按 id 去重。"""
    seed_dir = config.DATA_SEED_DIR if config.DATA_SEED_DIR.exists() else config.REPO_SEED_DIR
    if not seed_dir.exists():
        return [], 0
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
    return entries, len(files)


def _sync_seed(conn: sqlite3.Connection) -> None:
    """把种子内容 upsert 进库：新条目插入、已存在条目按 id 刷新内容字段，
    绝不触碰 review_state（用户的间隔复习进度保留）。这样修词条能真正生效。"""
    entries, nfiles = _load_seed_entries()
    if not entries:
        return
    from .importer import upsert_seed_entries  # 延迟导入避免环
    n = upsert_seed_entries(conn, entries)
    conn.commit()
    print(f"[z-spanish] 种子同步完成：{n} 条，来自 {nfiles} 个文件")


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
