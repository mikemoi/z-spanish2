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

# 判定分两层：
#   correct  = 忽略「大小写 + 标点 + 空格」后一致（重音仍需对）——纯排版差异不算错
#   near     = 再忽略「重音/ñ」后才一致——缺重音是真实拼写点，绿色通过但轻提醒
# 手机打字几乎不会打大写开头/句尾句号/开头 ¿，这些一律算对，避免"一直被降级"的挫败。
_PUNCT_RE = re.compile(r"[¿?¡!.,;:…]")
_SPACE_RE = re.compile(r"\s+")


def _strip_accents(s: str) -> str:
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _case_punct(s: str) -> str:
    """忽略大小写 + 标点 + 多余空格，但保留重音。"""
    s = _PUNCT_RE.sub("", s.lower())
    return _SPACE_RE.sub(" ", s).strip()


def _loose(s: str) -> str:
    """在 _case_punct 基础上再去掉重音/ñ。"""
    return _strip_accents(_case_punct(s))


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

    if _case_punct(user) in {_case_punct(c) for c in candidates}:
        return RESULT_CORRECT

    if _loose(user) in {_loose(c) for c in candidates}:
        return RESULT_NEAR

    return RESULT_WRONG
