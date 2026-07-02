"""四档判定：correct / near_correct / wrong / forgot。

判定宽松化（调整补充文档第四节）：
- 大小写、重音符号(á->a)、标点差异 -> near_correct（算通过，不算 wrong）
- correct 与 near_correct 都算"通过"（用于阶段推进），区别只是反馈标签
- 空输入返回 None，由调用方处理（不应发生，前端拦截）

技术性错误判太严会造成"明明会但系统说我错"的挫败，对长期使用的伤害
大于宽松判定带来的准确性损失。
"""
import json
import re
import unicodedata

RESULT_CORRECT = "correct"
RESULT_NEAR = "near_correct"
RESULT_WRONG = "wrong"
RESULT_FORGOT = "forgot"

PASS_RESULTS = {RESULT_CORRECT, RESULT_NEAR}

# 西语重音需要保留的语义区分本可细分，但按文档宽松处理：统一去掉重音。
_PUNCT_RE = re.compile(r"[¿?¡!.,;:]")
_SPACE_RE = re.compile(r"\s+")


def _strip_accents(s: str) -> str:
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _strict(s: str) -> str:
    """严格规范化：只去首尾空白与内部多余空格，保留大小写/重音/标点。"""
    return _SPACE_RE.sub(" ", s.strip())


def _loose(s: str) -> str:
    """宽松规范化：小写 + 去重音 + 去标点 + 折叠空格。"""
    s = _strip_accents(s.lower())
    s = _PUNCT_RE.sub("", s)
    return _SPACE_RE.sub(" ", s).strip()


def grade(user_answer: str, es: str, accepted_answers) -> str | None:
    """返回四档之一（不含 forgot；forgot 由前端"我不会"直接传）。"""
    user = (user_answer or "").strip()
    if not user:
        return None

    if isinstance(accepted_answers, str):
        try:
            accepted_answers = json.loads(accepted_answers)
        except (json.JSONDecodeError, TypeError):
            accepted_answers = []
    candidates = [es] + [a for a in (accepted_answers or []) if a]

    strict_set = {_strict(c) for c in candidates}
    if _strict(user) in strict_set:
        return RESULT_CORRECT

    loose_set = {_loose(c) for c in candidates}
    if _loose(user) in loose_set:
        return RESULT_NEAR

    return RESULT_WRONG
