"""z-spanish 后端：FastAPI + SQLite。单用户自用工具。"""
import json
import secrets
from datetime import date, datetime, timezone

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, review
from .db import get_conn, init_db, utcnow_iso
from .grading import RESULT_FORGOT, grade
from .importer import insert_entries, validate

app = FastAPI(title="z-spanish", docs_url=None, redoc_url=None)


@app.on_event("startup")
def _startup():
    init_db()


# ---------------------------------------------------------------------------
# 鉴权
# ---------------------------------------------------------------------------

def require_auth(authorization: str = Header(default="")) -> None:
    token = authorization.replace("Bearer ", "").strip()
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT 1 FROM sessions WHERE token = ?", (token,)
        ).fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(status_code=401, detail="登录已失效")


class LoginBody(BaseModel):
    pin: str


@app.post("/api/login")
def login(body: LoginBody):
    if body.pin != config.PIN:
        raise HTTPException(status_code=401, detail="PIN 不正确")
    token = secrets.token_urlsafe(24)
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO sessions (token, created_at) VALUES (?, ?)",
            (token, utcnow_iso()),
        )
        conn.commit()
    finally:
        conn.close()
    return {"token": token}


# ---------------------------------------------------------------------------
# 序列化辅助
# ---------------------------------------------------------------------------

def _entry_public(row) -> dict:
    """训练用：绝不含熟练度阶段（会提前暴露答案，破坏主动回忆）。"""
    return {
        "id": row["id"],
        "zh": row["zh"],
        "type_zh": row["type_zh"],
        "type_es": row["type_es"],
        "category": row["category"],
        "subtype": row["subtype"],
    }


def _entry_feedback(row) -> dict:
    return {
        "id": row["id"],
        "es": row["es"],
        "example_es": row["example_es"],
        "example_zh": row["example_zh"],
        "note": row["note"],
        "accepted_answers": json.loads(row["accepted_answers"] or "[]"),
        "confusion_group": row["confusion_group"],
    }


def _fetch_entries(conn, ids):
    if not ids:
        return {}
    qmarks = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT * FROM entries WHERE id IN ({qmarks})", ids
    ).fetchall()
    return {r["id"]: r for r in rows}


# ---------------------------------------------------------------------------
# 首页 / 今日题集
# ---------------------------------------------------------------------------

def _get_or_create_daily(conn, today: date) -> dict:
    day_iso = today.isoformat()
    row = conn.execute("SELECT * FROM daily_log WHERE day = ?", (day_iso,)).fetchone()
    if row:
        return dict(row)
    gen = review.generate_daily_set(conn, today)
    conn.execute(
        """INSERT INTO daily_log
           (day, item_ids, new_count, review_count, reinforce_count, total, completed)
           VALUES (?, ?, ?, ?, ?, ?, 0)""",
        (day_iso, json.dumps(gen["item_ids"]), gen["new_count"],
         gen["review_count"], gen["reinforce_count"], gen["total"]),
    )
    conn.commit()
    return {"day": day_iso, "item_ids": json.dumps(gen["item_ids"]),
            "new_count": gen["new_count"], "review_count": gen["review_count"],
            "reinforce_count": gen["reinforce_count"], "total": gen["total"],
            "completed": 0}


@app.get("/api/today", dependencies=[Depends(require_auth)])
def today():
    conn = get_conn()
    try:
        d = date.today()
        daily = _get_or_create_daily(conn, d)
        item_ids = json.loads(daily["item_ids"])
        # 已答（今日、属于题集）的数量，用于进度
        done_ids = set()
        if item_ids:
            qmarks = ",".join("?" * len(item_ids))
            rows = conn.execute(
                f"""SELECT DISTINCT entry_id FROM attempts
                    WHERE day = ? AND entry_id IN ({qmarks})""",
                [d.isoformat()] + item_ids,
            ).fetchall()
            done_ids = {r["entry_id"] for r in rows}

        entries = _fetch_entries(conn, item_ids)
        items = []
        for eid in item_ids:
            r = entries.get(eid)
            if not r:
                continue
            pub = _entry_public(r)
            pub["done"] = eid in done_ids
            items.append(pub)

        return {
            "date": d.isoformat(),
            "date_label": _date_label(d),
            "new_count": daily["new_count"],
            "review_count": daily["review_count"],
            "reinforce_count": daily["reinforce_count"],
            "total": daily["total"],
            "done": len(done_ids),
            "items": items,
            # 本月概览
            "month_days": _month_completed_days(conn, d),
            "longterm_count": _longterm_count(conn),
            "reinforce_pool": _reinforce_pool_size(conn),
        }
    finally:
        conn.close()


class AnswerBody(BaseModel):
    entry_id: str
    user_answer: str = ""
    action: str = "check"  # check | forgot


@app.post("/api/answer", dependencies=[Depends(require_auth)])
def answer(body: AnswerBody):
    conn = get_conn()
    try:
        d = date.today()
        row = conn.execute(
            "SELECT * FROM entries WHERE id = ?", (body.entry_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="词条不存在")

        if body.action == "forgot":
            result = RESULT_FORGOT
        else:
            result = grade(body.user_answer, row["es"], row["accepted_answers"])
            if result is None:
                raise HTTPException(status_code=400, detail="请输入答案或点“我不会”")

        # 记录流水 + 推进复习/阶段
        conn.execute(
            """INSERT INTO attempts (entry_id, ts, result, user_answer, day)
               VALUES (?, ?, ?, ?, ?)""",
            (body.entry_id, utcnow_iso(), result, body.user_answer, d.isoformat()),
        )
        review.apply_result(conn, body.entry_id, result, d)
        _refresh_completion(conn, d)
        conn.commit()

        fb = _entry_feedback(row)
        fb["result"] = result
        fb["your_answer"] = body.user_answer
        return fb
    finally:
        conn.close()


@app.post("/api/again", dependencies=[Depends(require_auth)])
def again():
    """再来一组：只从到期复习 + 需要加强抽取，不影响明天排期。"""
    conn = get_conn()
    try:
        d = date.today()
        ids = review.extra_set(conn, d)
        entries = _fetch_entries(conn, ids)
        items = [_entry_public(entries[i]) for i in ids if i in entries]
        return {"items": items, "total": len(items)}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 基础库
# ---------------------------------------------------------------------------

@app.get("/api/library", dependencies=[Depends(require_auth)])
def library(category: str = "", q: str = ""):
    conn = get_conn()
    try:
        sql = "SELECT * FROM entries WHERE is_active = 1"
        params = []
        if category and category != "全部":
            sql += " AND category = ?"
            params.append(category)
        if q:
            sql += " AND (zh LIKE ? OR es LIKE ? OR example_es LIKE ?)"
            like = f"%{q}%"
            params += [like, like, like]
        sql += " ORDER BY category, id"
        rows = conn.execute(sql, params).fetchall()

        # 阶段（只在基础库/统计显示）
        states = {r["entry_id"]: r for r in conn.execute(
            "SELECT entry_id, stage FROM review_state"
        ).fetchall()}

        items = []
        for r in rows:
            st = states.get(r["id"])
            items.append({
                "id": r["id"], "zh": r["zh"], "es": r["es"],
                "type_zh": r["type_zh"], "type_es": r["type_es"],
                "subtype": r["subtype"], "category": r["category"],
                "example_es": r["example_es"], "example_zh": r["example_zh"],
                "note": r["note"], "confusion_group": r["confusion_group"],
                "stage": st["stage"] if st else "未开始",
            })

        cats = [r["category"] for r in conn.execute(
            "SELECT DISTINCT category FROM entries WHERE is_active = 1 ORDER BY category"
        ).fetchall()]
        total = conn.execute(
            "SELECT COUNT(*) AS c FROM entries WHERE is_active = 1"
        ).fetchone()["c"]
        return {"items": items, "categories": cats, "total": total}
    finally:
        conn.close()


class ImportBody(BaseModel):
    action: str  # validate | confirm
    json_text: str


@app.post("/api/import", dependencies=[Depends(require_auth)])
def import_entries(body: ImportBody):
    try:
        data = json.loads(body.json_text)
    except json.JSONDecodeError as ex:
        raise HTTPException(status_code=400, detail=f"JSON 解析失败：{ex}")

    conn = get_conn()
    try:
        existing = {r["id"] for r in conn.execute("SELECT id FROM entries").fetchall()}
        res = validate(data, existing_ids=existing)
        if body.action == "validate":
            return {
                "ok": res["ok"],
                "errors": res["errors"],
                "warnings": res["warnings"],
                "preview": res["preview"],
                "count": len(res["valid"]),
            }
        # confirm：只有硬校验全过才导入
        if not res["ok"]:
            raise HTTPException(status_code=400, detail="存在硬错误，未导入")
        inserted = insert_entries(conn, res["valid"])
        conn.commit()
        return {"imported": inserted, "warnings": res["warnings"]}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 统计 / 时长 / 复制给 GPT
# ---------------------------------------------------------------------------

@app.get("/api/stats", dependencies=[Depends(require_auth)])
def stats(period: str = "day"):
    conn = get_conn()
    try:
        d = date.today()
        # 今日四档分布（按 entry 最后一次结果，去重更贴近"今天答成什么样"）
        breakdown = {"correct": 0, "near_correct": 0, "wrong": 0, "forgot": 0}
        rows = conn.execute(
            """SELECT entry_id, result FROM attempts
               WHERE day = ? AND id IN (
                   SELECT MAX(id) FROM attempts WHERE day = ? GROUP BY entry_id)""",
            (d.isoformat(), d.isoformat()),
        ).fetchall()
        for r in rows:
            if r["result"] in breakdown:
                breakdown[r["result"]] += 1
        done_today = len(rows)

        return {
            "done_today": done_today,
            "breakdown": breakdown,
            "month_days": _month_completed_days(conn, d),
            "longterm_count": _longterm_count(conn),
            "total_entries": conn.execute(
                "SELECT COUNT(*) AS c FROM entries WHERE is_active = 1").fetchone()["c"],
            "minutes": _timer_minutes(conn, d, period),
            "period": period,
        }
    finally:
        conn.close()


class TimerBody(BaseModel):
    start_ts: str
    last_activity_ts: str


@app.post("/api/timer/end", dependencies=[Depends(require_auth)])
def timer_end(body: TimerBody):
    """静默计时结束。兜底：以最后一次答题时间为准，避免忘记结束导致时长虚高。"""
    try:
        start = _parse_ts(body.start_ts)
        end = _parse_ts(body.last_activity_ts)
    except ValueError:
        raise HTTPException(status_code=400, detail="时间戳格式错误")
    minutes = max(1, round((end - start).total_seconds() / 60))
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO time_log (day, minutes, start_ts, end_ts) VALUES (?, ?, ?, ?)",
            (date.today().isoformat(), minutes, body.start_ts, body.last_activity_ts),
        )
        conn.commit()
    finally:
        conn.close()
    return {"minutes": minutes}


@app.get("/api/copy-gpt", dependencies=[Depends(require_auth)])
def copy_gpt():
    """生成给 GPT 的今日记忆状态摘要，用于设计明天让已背/不稳词块复现的小课文。"""
    conn = get_conn()
    try:
        d = date.today()
        rows = conn.execute(
            """SELECT a.result, e.zh, e.es FROM attempts a
               JOIN entries e ON e.id = a.entry_id
               WHERE a.day = ? AND a.id IN (
                   SELECT MAX(id) FROM attempts WHERE day = ? GROUP BY entry_id)
               ORDER BY a.result""",
            (d.isoformat(), d.isoformat()),
        ).fetchall()
        buckets = {"correct": [], "near_correct": [], "wrong": [], "forgot": []}
        for r in rows:
            buckets.setdefault(r["result"], []).append(f"{r['zh']} → {r['es']}")

        def block(title, items):
            if not items:
                return f"【{title}】无\n"
            return f"【{title}】\n" + "\n".join(f"- {x}" for x in items) + "\n"

        text = (
            f"我在用 z-spanish 背西语（中文→西语主动输出）。这是我 {d.isoformat()} 的训练情况，"
            "请据此设计一篇明天用的生活化西语小课文（A1-A2，8-12 句），"
            "让下面【已背对】的词块自然复现巩固，并重点把【接近/需要加强/没想起来】的词块编进上下文里再练一遍。"
            "课文用西语，句子下配中文，不要讲语法。\n\n"
            + block("已背对", buckets["correct"])
            + block("接近正确(差重音/大小写)", buckets["near_correct"])
            + block("需要加强(答错)", buckets["wrong"])
            + block("没想起来", buckets["forgot"])
        )
        return {"text": text}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 内部小工具
# ---------------------------------------------------------------------------

def _refresh_completion(conn, d: date):
    row = conn.execute(
        "SELECT item_ids, total FROM daily_log WHERE day = ?", (d.isoformat(),)
    ).fetchone()
    if not row:
        return
    ids = json.loads(row["item_ids"])
    if not ids:
        return
    qmarks = ",".join("?" * len(ids))
    done = conn.execute(
        f"""SELECT COUNT(DISTINCT entry_id) AS c FROM attempts
            WHERE day = ? AND entry_id IN ({qmarks})""",
        [d.isoformat()] + ids,
    ).fetchone()["c"]
    completed = 1 if done >= row["total"] and row["total"] > 0 else 0
    conn.execute(
        "UPDATE daily_log SET completed = ? WHERE day = ?", (completed, d.isoformat())
    )


def _month_completed_days(conn, d: date) -> int:
    prefix = d.strftime("%Y-%m")
    return conn.execute(
        "SELECT COUNT(*) AS c FROM daily_log WHERE completed = 1 AND day LIKE ?",
        (prefix + "%",),
    ).fetchone()["c"]


def _longterm_count(conn) -> int:
    return conn.execute(
        "SELECT COUNT(*) AS c FROM review_state WHERE stage = ?",
        (review.STAGE_LONGTERM,),
    ).fetchone()["c"]


def _reinforce_pool_size(conn) -> int:
    return conn.execute(
        "SELECT COUNT(*) AS c FROM review_state WHERE in_reinforce = 1"
    ).fetchone()["c"]


def _timer_minutes(conn, d: date, period: str) -> int:
    if period == "day":
        like = d.isoformat()
        sql = "SELECT COALESCE(SUM(minutes),0) AS m FROM time_log WHERE day = ?"
        return conn.execute(sql, (like,)).fetchone()["m"]
    if period == "week":
        iso_year, iso_week, _ = d.isocalendar()
        rows = conn.execute("SELECT day, minutes FROM time_log").fetchall()
        total = 0
        for r in rows:
            try:
                rd = date.fromisoformat(r["day"])
            except ValueError:
                continue
            y, w, _ = rd.isocalendar()
            if y == iso_year and w == iso_week:
                total += r["minutes"]
        return total
    if period == "month":
        prefix = d.strftime("%Y-%m")
    else:  # year
        prefix = d.strftime("%Y")
    return conn.execute(
        "SELECT COALESCE(SUM(minutes),0) AS m FROM time_log WHERE day LIKE ?",
        (prefix + "%",),
    ).fetchone()["m"]


_WEEK_ZH = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def _date_label(d: date) -> str:
    return f"{d.month} 月 {d.day} 日 · {_WEEK_ZH[d.weekday()]}"


def _parse_ts(s: str) -> datetime:
    # 接受毫秒时间戳或 ISO
    s = s.strip()
    if s.isdigit():
        return datetime.fromtimestamp(int(s) / 1000, tz=timezone.utc)
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


# ---------------------------------------------------------------------------
# 前端静态文件（放最后，避免吃掉 /api 路由）
# ---------------------------------------------------------------------------

@app.get("/")
def index():
    return FileResponse(config.FRONTEND_DIR / "index.html")


if config.FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(config.FRONTEND_DIR), html=True), name="static")
