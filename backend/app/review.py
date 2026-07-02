"""间隔复习引擎 + 熟练度阶段 + 每日生成算法。

间隔节奏：今天/第2/第4/第7/第14/第30/第60/第90 天 -> interval_idx 0..7
熟练度阶段（复用间隔节奏，不做百分比/评分）：
    idx 0,1 -> 初识 / idx 2,3 -> 巩固中 / idx 4,5 -> 稳固 / idx 6,7 -> 长期记忆
阶段规则：
    到达该间隔答对（correct 或 near_correct）才通过、进下一阶段；
    答错或"我不会" -> 阶段回退一级（不清零）。
"""
from datetime import date, timedelta

from . import config
from .grading import PASS_RESULTS, RESULT_FORGOT

STAGE_NEW = "初识"
STAGE_BUILDING = "巩固中"
STAGE_SOLID = "稳固"
STAGE_LONGTERM = "长期记忆"


def stage_for_idx(idx: int) -> str:
    if idx <= 1:
        return STAGE_NEW
    if idx <= 3:
        return STAGE_BUILDING
    if idx <= 5:
        return STAGE_SOLID
    return STAGE_LONGTERM


def _today() -> date:
    return date.today()


def _iso(d: date) -> str:
    return d.isoformat()


# ---------------------------------------------------------------------------
# 状态更新
# ---------------------------------------------------------------------------

def ensure_state(conn, entry_id: str, today: date) -> None:
    """新词第一次进入训练：建 review_state，当天到期，初识。"""
    exists = conn.execute(
        "SELECT 1 FROM review_state WHERE entry_id = ?", (entry_id,)
    ).fetchone()
    if exists:
        return
    conn.execute(
        """INSERT INTO review_state
           (entry_id, interval_idx, due_date, stage, in_reinforce, first_seen)
           VALUES (?, 0, ?, ?, 0, ?)""",
        (entry_id, _iso(today), STAGE_NEW, _iso(today)),
    )


def apply_result(conn, entry_id: str, result: str, today: date) -> dict:
    """根据答题结果推进/回退间隔与阶段，写回 review_state。返回新状态。"""
    ensure_state(conn, entry_id, today)
    row = conn.execute(
        "SELECT interval_idx FROM review_state WHERE entry_id = ?", (entry_id,)
    ).fetchone()
    idx = row["interval_idx"]

    if result in PASS_RESULTS:
        new_idx = min(idx + 1, config.MAX_IDX)
        gap = config.GAP_TO_IDX[new_idx] or 1  # idx 保持 7 时 gap 用 30
        due = today + timedelta(days=gap)
        in_reinforce = 0
    else:  # wrong / forgot
        new_idx = max(idx - 1, 0)          # 回退一级，不清零
        due = today + timedelta(days=1)    # 明天再出现
        in_reinforce = 1

    stage = stage_for_idx(new_idx)
    conn.execute(
        """UPDATE review_state
           SET interval_idx = ?, due_date = ?, stage = ?, in_reinforce = ?,
               last_result = ?, last_reviewed = ?
           WHERE entry_id = ?""",
        (new_idx, _iso(due), stage, in_reinforce, result, _iso(today), entry_id),
    )
    return {"interval_idx": new_idx, "due_date": _iso(due), "stage": stage,
            "in_reinforce": bool(in_reinforce)}


# ---------------------------------------------------------------------------
# 每日生成
# ---------------------------------------------------------------------------

def _fetch_ids(conn, sql, params=()):
    return [r["entry_id"] if "entry_id" in r.keys() else r["id"]
            for r in conn.execute(sql, params).fetchall()]


def generate_daily_set(conn, today: date) -> dict:
    """按优先级生成当日题集：到期复习 -> 需要加强 -> 混淆组 -> 补新内容(<=5)。

    规则：
    - 需要加强池 > 15：当日优先清空该池，不加新内容
    - 旧内容(去重) >= 20：今天不加新内容
    - 新内容硬上限 5
    最终裁到 20 题（旧内容优先）。
    """
    today_iso = _iso(today)

    # 1) 到期复习（不含仍在加强池的，避免重复计数），最早到期优先
    due_ids = _fetch_ids(conn, """
        SELECT entry_id FROM review_state rs
        JOIN entries e ON e.id = rs.entry_id
        WHERE e.is_active = 1 AND rs.in_reinforce = 0 AND rs.due_date <= ?
        ORDER BY rs.due_date ASC, rs.interval_idx ASC
    """, (today_iso,))

    # 2) 需要加强池
    reinforce_ids = _fetch_ids(conn, """
        SELECT entry_id FROM review_state rs
        JOIN entries e ON e.id = rs.entry_id
        WHERE e.is_active = 1 AND rs.in_reinforce = 1
        ORDER BY rs.last_reviewed ASC
    """)

    selected = list(dict.fromkeys(due_ids + reinforce_ids))  # 去重保序

    # 3) 混淆组：加强池里词条所属 confusion_group 的兄弟条，补强区分
    if reinforce_ids:
        qmarks = ",".join("?" * len(reinforce_ids))
        groups = [r["confusion_group"] for r in conn.execute(
            f"""SELECT DISTINCT confusion_group FROM entries
                WHERE id IN ({qmarks}) AND confusion_group IS NOT NULL
                      AND confusion_group != ''""",
            reinforce_ids,
        ).fetchall()]
        if groups:
            gmarks = ",".join("?" * len(groups))
            conf_ids = _fetch_ids(conn, f"""
                SELECT id AS entry_id FROM entries
                WHERE is_active = 1 AND confusion_group IN ({gmarks})
            """, groups)
            for cid in conf_ids:
                if cid not in selected:
                    selected.append(cid)

    old_count = len(selected)
    reinforce_count = len(reinforce_ids)

    # 4) 是否补新内容
    if reinforce_count > config.REINFORCE_SOFT_CAP:
        new_cap = 0
    elif old_count >= config.OLD_BLOCK_NEW:
        new_cap = 0
    else:
        new_cap = min(config.NEW_CAP, config.DAILY_TOTAL - old_count)
        new_cap = max(new_cap, 0)

    new_ids = []
    if new_cap > 0:
        new_ids = _fetch_ids(conn, """
            SELECT e.id AS entry_id FROM entries e
            LEFT JOIN review_state rs ON rs.entry_id = e.id
            WHERE e.is_active = 1 AND rs.entry_id IS NULL
            ORDER BY e.id ASC
            LIMIT ?
        """, (new_cap,))
        selected.extend(new_ids)

    # 裁到每日总量（旧内容在前，天然优先）
    selected = selected[:config.DAILY_TOTAL]

    new_in_set = len([i for i in new_ids if i in selected])
    reinforce_in_set = len([i for i in reinforce_ids if i in selected])
    review_in_set = len(selected) - new_in_set - reinforce_in_set

    return {
        "item_ids": selected,
        "new_count": new_in_set,
        "review_count": review_in_set,
        "reinforce_count": reinforce_in_set,
        "total": len(selected),
    }


def more_set(conn, today: date, batch: int = None) -> list:
    """"继续练"：不设上限地往下喂——先清到期复习/需要加强，再不限量放新词。

    每次返回一批(默认 DAILY_TOTAL 个)，排除今天已答过的，所以反复调用会像
    无限滚动一样一直往后走，直到到期的都清了、新词也学完为止。
    作答照常写回 SRS。
    """
    batch = batch or config.DAILY_TOTAL
    today_iso = _iso(today)
    answered = {r["entry_id"] for r in conn.execute(
        "SELECT DISTINCT entry_id FROM attempts WHERE day = ?", (today_iso,)
    ).fetchall()}

    # 1) 到期复习 + 需要加强（今天还没答的）
    due = _fetch_ids(conn, """
        SELECT entry_id FROM review_state rs
        JOIN entries e ON e.id = rs.entry_id
        WHERE e.is_active = 1 AND (rs.in_reinforce = 1 OR rs.due_date <= ?)
        ORDER BY rs.in_reinforce DESC, rs.due_date ASC
    """, (today_iso,))
    picks = [i for i in due if i not in answered]

    # 2) 不限量补新词（无 review_state 的），按 id 顺序
    if len(picks) < batch:
        new_ids = _fetch_ids(conn, """
            SELECT e.id AS entry_id FROM entries e
            LEFT JOIN review_state rs ON rs.entry_id = e.id
            WHERE e.is_active = 1 AND rs.entry_id IS NULL
            ORDER BY e.id ASC
        """)
        for nid in new_ids:
            if nid not in answered and nid not in picks:
                picks.append(nid)
            if len(picks) >= batch:
                break

    return picks[:batch]


def extra_set(conn, today: date) -> list:
    """"再来一组"：只从到期复习 + 需要加强抽取，用来再练当天没稳的词块。

    排除今天已经答对/接近的词块（没必要重复），保留答错/没想起来的以便再钻一遍。
    不影响明天排期（apply_result 仍照常记录，但不新增今日题集）。
    """
    today_iso = _iso(today)
    passed_today = {r["entry_id"] for r in conn.execute(
        """SELECT DISTINCT entry_id FROM attempts
           WHERE day = ? AND result IN ('correct', 'near_correct')""",
        (today_iso,),
    ).fetchall()}
    ids = _fetch_ids(conn, """
        SELECT entry_id FROM review_state rs
        JOIN entries e ON e.id = rs.entry_id
        WHERE e.is_active = 1 AND (rs.in_reinforce = 1 OR rs.due_date <= ?)
        ORDER BY rs.in_reinforce DESC, rs.due_date ASC
    """, (today_iso,))
    result = [i for i in ids if i not in passed_today][:config.DAILY_TOTAL]
    return result
