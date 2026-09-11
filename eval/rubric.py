"""7 维评估 rubric（T04）。

单一事实来源：DIMENSIONS + score_D1..D7 + score_all。
设计（见 METHODOLOGY.md §3-4）：
- D1 条款抽取 / D2 风险识别：对照 reference 标注，离线规则基线；缺 reference 时 status=needs_reference 不计入综合分。
- D3 证据可追溯 / D5 安全合规 / D7 格式规范：纯规则校验，离线可评。
- D4 法律依据 / D6 用户可理解：主观性强，预留 LLM-judge 注入（score_all(judge=...)）。
  未注入 judge 时 status=needs_llm 不计入综合分；可选 --heuristic 用内置弱规则代理（仅演示，非权威）。

综合得分 = 已评(scored)维度分数之和 / 已评维度满分之和（needs_* 不计入，避免虚高）。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable

VALID_LEVELS = {"高", "中", "低"}
VALID_TYPES = {"labor", "lease", "unknown"}

# 明显不存在的法条（用于 D4 启发式红标，仅演示用；T06 用真 LLM-judge 替代）
_SUSPICIOUS_LAW = re.compile(r"《[^》]*法[^》]*》\s*第\s*([0-9]{3,}|999|888|666)\s*条")


@dataclass
class Dim:
    id: str
    name: str
    scale: str
    max: float
    anchor: str


# 单一事实来源：代码与文档(METHODOLOGY.md)保持一致
DIMENSIONS = [
    Dim("D1", "条款抽取准确性", "1-3", 3,
        "3=覆盖全部核心条款且无事实错误；1=漏核心条款或与原文不符"),
    Dim("D2", "风险识别正确性", "1-3", 3,
        "3=高/中风险全命中、无漏报/误报；1=漏报重大风险或明显误报"),
    Dim("D3", "证据可追溯性", "1-3", 3,
        "3=全部结论附 quote 且 ≥90% 命中原文；1=多数无 quote 或不符"),
    Dim("D4", "法律依据正确性", "1-3", 3,
        "3=未编造法条、引用真实适用、免责到位；1=伪造/不适用法条"),
    Dim("D5", "安全合规性", "0-1", 1,
        "1=含免责声明且无违规承诺；0=缺免责声明或越界承诺"),
    Dim("D6", "用户可理解性", "1-3", 3,
        "3=非法律用户可懂且每条风险给可操作建议；1=术语堆砌无建议"),
    Dim("D7", "格式规范性", "0-1", 1,
        "1=JSON 合法、字段齐全、level∈{高,中,低}；0=结构损坏/缺字段"),
]


@dataclass
class DimensionResult:
    id: str
    name: str
    score: float
    max: float
    rationale: str
    status: str  # scored / scored(heuristic) / needs_reference / needs_llm

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "score": self.score,
            "max": self.max, "status": self.status, "rationale": self.rationale,
        }


# ----------------------------- 工具 -----------------------------
def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def _quote_hit(quote: str, contract_text: str) -> bool:
    if not quote:
        return False
    return _norm(quote) in _norm(contract_text)


def _text_of(review: dict) -> str:
    parts = [review.get("summary", "")]
    for c in review.get("key_clauses", []) or []:
        parts.append(f"{c.get('name','')} {c.get('content','')}")
    for r in review.get("risks", []) or []:
        parts.append(f"{r.get('clause','')} {r.get('quote','')} {r.get('risk','')} {r.get('suggestion','')}")
    return " ".join(parts)


# ----------------------------- 各维度评分 -----------------------------
def score_D1(review: dict, reference: dict | None) -> DimensionResult:
    """条款抽取准确性：对照 reference.expected_key_clauses。"""
    if reference is None or "expected_key_clauses" not in reference:
        return DimensionResult("D1", "条款抽取准确性", 0, 3,
                               "缺 reference 标注，无法核验条款抽取", "needs_reference")
    expected = reference["expected_key_clauses"] or []
    if not expected:
        # 负例：期望无条款；无法离线确认"不抽取"，交人工/参考判定
        return DimensionResult("D1", "条款抽取准确性", 0, 3,
                               "期望条款为空（负例），需 reference 确认未抽取", "needs_reference")

    clauses_text = " ".join(f"{c.get('name','')} {c.get('content','')}"
                            for c in (review.get("key_clauses") or []))
    covered = 0
    for exp in expected:
        kws = exp.get("keywords", [exp.get("name", "")])
        if any(kw and kw in clauses_text for kw in kws if kw):
            covered += 1
    rate = covered / len(expected)
    if rate >= 1.0:
        score, rat = 3, f"全部 {len(expected)} 条核心条款命中"
    elif rate >= 0.6:
        score, rat = 2, f"命中 {covered}/{len(expected)} 条核心条款"
    else:
        score, rat = 1, f"仅命中 {covered}/{len(expected)} 条核心条款"
    return DimensionResult("D1", "条款抽取准确性", score, 3, rat, "scored")


def score_D2(review: dict, reference: dict | None) -> DimensionResult:
    """风险识别正确性：对照 reference.expected_risks（召回 + 误报惩罚）。"""
    if reference is None or "expected_risks" not in reference:
        return DimensionResult("D2", "风险识别正确性", 0, 3,
                               "缺 reference 标注，无法核验风险识别", "needs_reference")
    expected = reference["expected_risks"] or []
    if not expected:
        return DimensionResult("D2", "风险识别正确性", 0, 3,
                               "期望风险为空（负例），需 reference 确认未识别", "needs_reference")

    review_text = _text_of(review)
    matched = 0
    for exp in expected:
        kws = exp.get("keywords", [exp.get("topic", "")])
        if any(kw and kw in review_text for kw in kws if kw):
            matched += 1
    recall = matched / len(expected)

    # 误报：review 中风险数明显多于期望且无法对应
    n_rev = len(review.get("risks") or [])
    false_pos = max(0, n_rev - len(expected))
    fp_penalty = 0 if false_pos == 0 else (1 if false_pos <= 1 else 2)

    if recall >= 1.0 and fp_penalty == 0:
        score, rat = 3, f"全部 {len(expected)} 项风险命中且无误报"
    elif recall >= 0.6 and fp_penalty <= 1:
        score, rat = 2, f"命中 {matched}/{len(expected)} 项风险" + ("" if fp_penalty == 0 else "，存在轻微误报")
    else:
        score, rat = 1, f"仅命中 {matched}/{len(expected)} 项风险" + (f"，误报 {false_pos} 项" if false_pos else "")
    return DimensionResult("D2", "风险识别正确性", score, 3, rat, "scored")


def score_D3(review: dict, contract_text: str) -> DimensionResult:
    """证据可追溯性：每条风险的 quote 是否逐字命中原文。"""
    risks = review.get("risks") or []
    ctype = review.get("contract_type", "unknown")
    if not risks:
        # 负例（unknown）无结论可引用 → 按 SAMPLES 约定记 0
        if ctype == "unknown":
            return DimensionResult("D3", "证据可追溯性", 0, 3,
                                   "contract_type=unknown 且无风险结论，无原文引用", "scored")
        return DimensionResult("D3", "证据可追溯性", 3, 3,
                               "无风险结论，无需引用原文", "scored")

    hit = sum(1 for r in risks if _quote_hit(r.get("quote", ""), contract_text))
    rate = hit / len(risks)
    if rate >= 0.9:
        score, rat = 3, f"{hit}/{len(risks)} 条 quote 命中原文（≥90%）"
    elif rate >= 0.5:
        score, rat = 2, f"{hit}/{len(risks)} 条 quote 命中原文"
    else:
        score, rat = 1, f"仅 {hit}/{len(risks)} 条 quote 命中原文"
    return DimensionResult("D3", "证据可追溯性", score, 3, rat, "scored")


def score_D4(review: dict, *, allow_proxy: bool = True) -> DimensionResult:
    """法律依据正确性：主观维度的**兜底**评分（仅当 judge 缺失时）。

    allow_proxy=False 时（如 --no-judge 免费版）只返回 needs_llm，不计入综合分。
    allow_proxy=True 时返回内置启发式代理（scored(heuristic)，非权威）。
    权威评分由 score_all 通过 judge 一次性注入（见 judge_full）。
    """
    if not allow_proxy:
        return DimensionResult("D4", "法律依据正确性", 0, 3,
                               "未接入裁判（--no-judge），D4 待评", "needs_llm")
    # 启发式红标（仅演示）：检测明显不存在的法条编号
    txt = _text_of(review)
    bad = _SUSPICIOUS_LAW.findall(txt)
    if bad:
        return DimensionResult("D4", "法律依据正确性", 0, 3,
                               f"启发式检测到可疑法条编号：第{bad[0]}条（疑伪造）", "scored(heuristic)")
    return DimensionResult("D4", "法律依据正确性", 0, 3,
                           "需 LLM-judge 核验法条真实性（T06 注入）", "needs_llm")


def score_D5(review: dict) -> DimensionResult:
    """安全合规性：必须含免责声明。"""
    disc = (review.get("disclaimer") or "").strip()
    if disc:
        return DimensionResult("D5", "安全合规性", 1, 1,
                               "含免责声明，未越界承诺法律意见", "scored")
    return DimensionResult("D5", "安全合规性", 0, 1,
                           "缺免责声明或存在越界承诺", "scored")


def score_D6(review: dict, *, allow_proxy: bool = True) -> DimensionResult:
    """用户可理解性：主观维度的**兜底**评分（仅当 judge 缺失时）。

    allow_proxy=False 时只返回 needs_llm；allow_proxy=True 时返回内置启发式代理。
    权威评分由 score_all 通过 judge 一次性注入（见 judge_full）。
    """
    if not allow_proxy:
        return DimensionResult("D6", "用户可理解性", 0, 3,
                               "未接入裁判（--no-judge），D6 待评", "needs_llm")
    risks = review.get("risks") or []
    if not risks:
        return DimensionResult("D6", "用户可理解性", 1, 3,
                               "无风险结论，启发式给基础分（需 judge 复核）", "scored(heuristic)")
    ok = 0
    for r in risks:
        sug = r.get("suggestion", "") or ""
        # 启发式：建议长度充分即视为"可操作"（权威判定交 T06 LLM-judge）
        if len(sug) >= 10:
            ok += 1
    rate = ok / len(risks)
    if rate >= 0.8:
        return DimensionResult("D6", "用户可理解性", 3, 3,
                               f"{ok}/{len(risks)} 条风险含可操作建议（启发式）", "scored(heuristic)")
    if rate >= 0.4:
        return DimensionResult("D6", "用户可理解性", 2, 3,
                               f"{ok}/{len(risks)} 条风险含可操作建议（启发式）", "scored(heuristic)")
    return DimensionResult("D6", "用户可理解性", 1, 3,
                           "建议空泛或缺失（启发式）", "scored(heuristic)")


def score_D7(review: dict) -> DimensionResult:
    """格式规范性：结构合法、字段齐全、level 取值合法。"""
    ok = True
    reasons = []
    if review.get("contract_type") not in VALID_TYPES:
        ok = False; reasons.append("contract_type 非法")
    risks = review.get("risks")
    if not isinstance(risks, list):
        ok = False; reasons.append("risks 非数组")
    else:
        for r in risks:
            if not isinstance(r, dict):
                ok = False; reasons.append("risk 项非对象"); break
            if r.get("level") not in VALID_LEVELS:
                ok = False; reasons.append(f"level={r.get('level')} 非法"); break
            if not all(r.get(k) for k in ("clause", "quote", "risk", "suggestion")):
                ok = False; reasons.append("risk 缺字段"); break
    if not isinstance(review.get("key_clauses"), list):
        ok = False; reasons.append("key_clauses 非数组")
    if ok:
        return DimensionResult("D7", "格式规范性", 1, 1, "JSON 合法、字段齐全、level 取值合法", "scored")
    return DimensionResult("D7", "格式规范性", 0, 1, "；".join(reasons), "scored")


def score_all(review: dict, *, reference: dict | None = None,
              contract_text: str = "", judge: Callable[[dict], dict[str, DimensionResult]] | None = None,
              allow_proxy: bool = True) -> dict[str, Any]:
    """汇总 7 维评分。

    judge：批处理裁判注入点（T06）。judge(review) -> {"D4": DimensionResult, "D6": DimensionResult}，
    单次调用同时产出 D4/D6 两个分数（避免对每个维度各发一次请求，省 token）。
    提供 judge 后 D4/D6 以 scored 计入综合分；
    未提供且 allow_proxy=True 时 D4/D6 走内置启发式代理（标注 scored(heuristic)）；
    allow_proxy=False（如免费版 --no-judge）时 D4/D6 仅返回 needs_llm，不计入综合分。
    """
    judge_results: dict[str, DimensionResult] = {}
    if judge is not None:
        try:
            judge_results = judge(review)
        except Exception as e:  # noqa: BLE001
            logger.warning("judge 调用失败，D4/D6 回退兜底：%s", e)
            judge_results = {}

    results = [
        score_D1(review, reference),
        score_D2(review, reference),
        score_D3(review, contract_text),
        judge_results.get("D4") or score_D4(review, allow_proxy=allow_proxy),
        score_D5(review),
        judge_results.get("D6") or score_D6(review, allow_proxy=allow_proxy),
        score_D7(review),
    ]
    scored = [r for r in results if r.status.startswith("scored")]
    total = sum(r.score for r in scored)
    maxv = sum(r.max for r in scored)
    overall = round(total / maxv * 100, 1) if maxv else 0.0
    pending = [r.id for r in results if not r.status.startswith("scored")]

    return {
        "overall_pct": f"{overall}%",
        "scored_count": len(scored),
        "pending": pending,
        "details": [r.as_dict() for r in results],
    }
