"""词条 JSON schema 定义 + 导入校验。

校验分两级：
- ERROR（硬错，拦截该条不导入）：缺必填字段、example_es 为空、id 重复
- WARNING（软警告，允许导入但标记"未完成收录"）：词块不孤立规则
    * 动词类：同一 verb_lemma 至少 2 条（人称块 + 搭配/例句）
    * 名词类：同一 noun_lemma 至少 2 条（冠词块 + 搭配句）
    * 介词类：同一 prep_lemma 至少 2 条不同短语

"宁少勿错"：硬错拦截；软警告交给人工在预览里决定是否仍导入。
"""
import json
import sqlite3
from collections import Counter

from .db import utcnow_iso

REQUIRED_FIELDS = ["id", "category", "zh", "es", "example_es"]

# 入库字段白名单（与 schema 对应）
_COLUMNS = [
    "id", "category", "type_zh", "type_es", "subtype", "zh", "es",
    "accepted_answers", "example_es", "example_zh", "note", "tags",
    "confusion_group", "verb_lemma", "noun_lemma", "prep_lemma", "is_active",
]


def _as_json_text(v, default="[]") -> str:
    if v is None:
        return default
    if isinstance(v, str):
        # 已是字符串：尝试确认是合法 JSON，否则包成单元素数组
        try:
            json.loads(v)
            return v
        except (json.JSONDecodeError, TypeError):
            return json.dumps([v], ensure_ascii=False)
    return json.dumps(v, ensure_ascii=False)


def validate(entries, existing_ids=None) -> dict:
    """校验一批词条。返回 {ok, errors, warnings, valid, preview}。

    valid = 通过硬校验、可以导入的条目（软警告不拦截）。
    """
    existing_ids = set(existing_ids or [])
    errors = []
    warnings = []
    valid = []
    seen_ids = set()

    if not isinstance(entries, list):
        return {
            "ok": False,
            "errors": ["顶层必须是 JSON 数组 [ ... ]"],
            "warnings": [], "valid": [], "preview": [],
        }

    # 先做逐条硬校验
    for i, e in enumerate(entries):
        label = f"第 {i + 1} 条"
        if not isinstance(e, dict):
            errors.append(f"{label}: 不是对象")
            continue
        missing = [f for f in REQUIRED_FIELDS if not str(e.get(f, "")).strip()]
        if missing:
            errors.append(f"{label} (id={e.get('id', '?')}): 缺少或为空字段 {missing}")
            continue
        eid = str(e["id"]).strip()
        if eid in seen_ids:
            errors.append(f"{label}: id 重复 {eid}")
            continue
        if eid in existing_ids:
            errors.append(f"{label}: id 已存在于库中 {eid}")
            continue
        seen_ids.add(eid)
        valid.append(e)

    # 跨条软校验：词块不孤立（只在通过硬校验的集合内统计）
    verb_counts = Counter(e.get("verb_lemma") for e in valid if e.get("verb_lemma"))
    noun_counts = Counter(e.get("noun_lemma") for e in valid if e.get("noun_lemma"))
    prep_counts = Counter(e.get("prep_lemma") for e in valid if e.get("prep_lemma"))

    for lemma, c in verb_counts.items():
        if c < 2:
            warnings.append(f"动词 “{lemma}” 只有 {c} 条：需人称块 + 搭配/例句，视为未完成收录")
    for lemma, c in noun_counts.items():
        if c < 2:
            warnings.append(f"名词 “{lemma}” 只有 {c} 条：需冠词块 + 搭配句，视为未完成收录")
    for lemma, c in prep_counts.items():
        if c < 2:
            warnings.append(f"介词 “{lemma}” 只有 {c} 条：需 ≥2 条不同短语，视为未完成收录")

    preview = [
        {"id": e["id"], "zh": e["zh"], "es": e["es"], "category": e["category"]}
        for e in valid
    ]
    return {
        "ok": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "valid": valid,
        "preview": preview,
    }


def insert_entries(conn: sqlite3.Connection, entries) -> int:
    """把已校验的条目写入 entries 表。返回写入条数。"""
    now = utcnow_iso()
    rows = []
    for e in entries:
        row = {c: e.get(c) for c in _COLUMNS}
        row["accepted_answers"] = _as_json_text(e.get("accepted_answers"), "[]")
        row["tags"] = _as_json_text(e.get("tags"), "[]")
        row["is_active"] = int(e.get("is_active", 1))
        rows.append(row)

    placeholders = ", ".join(f":{c}" for c in _COLUMNS) + ", :created_at"
    cols = ", ".join(_COLUMNS) + ", created_at"
    sql = f"INSERT OR IGNORE INTO entries ({cols}) VALUES ({placeholders})"
    for row in rows:
        row["created_at"] = now
        conn.execute(sql, row)
    return len(rows)
