"""LLM-as-judge（T06）：用可配置的 LLM 作为评测裁判，补全 D4/D6 主观维度。

设计要点：
- make_judge() 返回批处理裁判 judge_full(review) -> {"D4": DimensionResult, "D6": DimensionResult}。
- 优先「一次请求同时产出 D4+D6」（省 token，适合支持批输出的模型）；
  若批处理失败（如 glm-5.3 对长 prompt 易返回空），自动退化为逐维度两次请求，
  保证在免费模型上也能拿到权威分，且不影响 hy3-preview 节省策略。
- 评测者与被评者分离：独立 system prompt，要求只输出 JSON（分数+理由），不得编造法律依据。
- 裁判模型与被评模型解耦：JUDGE_MODEL / JUDGE_BASE_URL / JUDGE_API_KEY 单独配置，
  默认回退到 HY3_*。默认用免费 glm-5.3 充当裁判（不消耗 hy3-preview 额度）。
- 结果缓存：相同 (模型+审阅内容) 的裁判结果写入 eval/results/.judge_cache.json，
  重复评测（T08 多轮、调试）不会重复消耗 token。
- 鲁棒性：未配置/不可达/解析失败 → 回退 rubric 内置启发式（scored(heuristic)），评测不中断。
- 密钥只经环境变量传入，模块本身不持有明文。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # noqa: BLE001
    pass

from eval.rubric import DimensionResult, score_D4, score_D6  # noqa: E402

logger = logging.getLogger("llm_judge")

_CACHE_PATH = Path(__file__).resolve().parent / "results" / ".judge_cache.json"
_CACHE: dict[str, Any] = {}

_SYSTEM = (
    "你是严谨的法律 AI 评测裁判。你的任务是对「合同审阅结果」在指定评估维度上打分。"
    "只输出一个 JSON 对象，不要任何额外文字或代码块标记。"
    'JSON 结构：{"score": <1-3 整数>, "rationale": "<简短中文理由>"}。'
    "评分必须基于被评文本事实，不得编造法律依据或夸大问题。"
)

_D4_DESC = (
    "D4 法律依据正确性。标尺：3=未编造法条、引用真实且适用、免责到位；"
    "2=部分引用存疑或依据不充分；1=伪造法条或引用明显不适用的法律。"
    "重点检查是否引用了真实存在的法条、是否存在编造的法律条文编号（如不存在的「第999条」）。"
)
_D6_DESC = (
    "D6 用户可理解性。标尺：3=非法律专业用户可读懂，且每条风险都给出可操作修改建议；"
    "2=基本可懂但部分建议空泛或缺失；1=术语堆砌、无实质建议。"
    "重点检查风险描述是否通俗易懂、是否每条都给出可操作的修改建议。"
)


def _load_cache() -> None:
    global _CACHE
    if _CACHE or not _CACHE_PATH.exists():
        return
    try:
        _CACHE = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        _CACHE = {}


def _save_cache() -> None:
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_PATH.write_text(json.dumps(_CACHE, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        logger.warning("judge 缓存写入失败（不影响评测）：%s", e)


def _extract_json(text: str) -> dict[str, Any] | None:
    text = (text or "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return None


def _clamp_score(v: Any) -> int:
    try:
        s = int(round(float(v)))
    except (TypeError, ValueError):
        return 2
    return max(1, min(3, s))


def _heuristic_fallback(review: dict, dim_id: str) -> DimensionResult:
    if dim_id == "D4":
        return score_D4(review)
    return score_D6(review)


def make_judge(use_cache: bool = True) -> tuple[Callable[[dict], dict[str, DimensionResult]], str, str]:
    """构造批处理裁判 judge_full(review) -> {"D4": DimensionResult, "D6": DimensionResult}。

    返回 (judge_full, mode, model)。mode ∈ {"llm-judge", "heuristic"}。
    裁判配置（省 hy3-preview 额度）：
        JUDGE_API_KEY   默认回退 HY3_API_KEY
        JUDGE_BASE_URL  默认回退 HY3_BASE_URL
        JUDGE_MODEL     默认回退 HY3_MODEL（本项目默认免费 glm-5.3）
        JUDGE_MAX_TOKENS 裁判单次输出上限，默认 2048。
            注意：若裁判模型为推理型（如 z-ai/glm-5.3，会消耗 reasoning_tokens），
            1024 容易被思维链吃满导致正文被截断、JSON 解析失败，故放宽至 2048。
    """
    api_key = os.getenv("JUDGE_API_KEY") or os.getenv("HY3_API_KEY", "EMPTY")
    base_url = os.getenv("JUDGE_BASE_URL") or os.getenv("HY3_BASE_URL", "")
    model = os.getenv("JUDGE_MODEL") or os.getenv("HY3_MODEL", "hy3")
    max_tokens = int(os.getenv("JUDGE_MAX_TOKENS", "2048"))
    if not api_key or api_key == "EMPTY" or not base_url:
        logger.warning("未检测到裁判密钥/端点，D4/D6 将使用启发式兜底（非 LLM-judge）。")
        return (lambda r: {"D4": _heuristic_fallback(r, "D4"), "D6": _heuristic_fallback(r, "D6")},
                "heuristic", model)

    try:
        from openai import APIConnectionError, APITimeoutError, OpenAI, RateLimitError
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=60)
    except Exception as e:  # noqa: BLE001
        logger.warning("裁判客户端初始化失败，D4/D6 回退启发式：%s", e)
        return (lambda r: {"D4": _heuristic_fallback(r, "D4"), "D6": _heuristic_fallback(r, "D6")},
                "heuristic", model)

    if use_cache:
        _load_cache()

    def _call_dim(dim_id: str, review_json: str) -> DimensionResult | None:
        """对单个维度发一次请求；成功返回 DimensionResult，失败/空返回 None。"""
        user = (
            f"评估维度：{_D4_DESC if dim_id == 'D4' else _D6_DESC}\n\n"
            f"待评合同审阅结果：\n{review_json}\n\n请输出 JSON 评分。"
        )
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": _SYSTEM},
                          {"role": "user", "content": user}],
                temperature=0.3,
                max_tokens=max_tokens,
            )
            raw = (resp.choices[0].message.content or "").strip()
            parsed = _extract_json(raw) if raw else None
            if not parsed:
                logger.warning("judge[%s] 空或无法解析：%r", dim_id, raw[:120])
                return None
            return DimensionResult(
                dim_id, "法律依据正确性" if dim_id == "D4" else "用户可理解性",
                _clamp_score(parsed.get("score")), 3,
                str(parsed.get("rationale", ""))[:200] or "LLM-judge 未给理由", "scored(llm-judge)",
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("judge[%s] 调用失败：%s", dim_id, e)
            return None

    def judge_full(review: dict) -> dict[str, DimensionResult]:
        compact = {
            "contract_type": review.get("contract_type"),
            "risks": review.get("risks") or [],
            "disclaimer": review.get("disclaimer"),
        }
        review_json = json.dumps(compact, ensure_ascii=False)
        cache_key = model + ":" + hashlib.md5(review_json.encode("utf-8")).hexdigest()
        if use_cache and cache_key in _CACHE:
            cached = _CACHE[cache_key]
            return {
                "D4": DimensionResult("D4", "法律依据正确性", cached["D4"]["score"], 3,
                                      cached["D4"]["rationale"], "scored(llm-judge)"),
                "D6": DimensionResult("D6", "用户可理解性", cached["D6"]["score"], 3,
                                      cached["D6"]["rationale"], "scored(llm-judge)"),
            }

        # 1) 优先「一次请求产出 D4+D6」省 token（单次尝试，失败即转逐维，减少外部调用）
        batched_user = (
            "请对以下合同审阅结果在 D4、D6 两个维度分别打分。\n\n"
            f"【D4】{_D4_DESC}\n\n【D6】{_D6_DESC}\n\n"
            f"待评合同审阅结果：\n{review_json}\n\n请输出 JSON 评分。"
        )
        raw = ""
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": _SYSTEM},
                          {"role": "user", "content": batched_user}],
                temperature=0.3,
                max_tokens=max_tokens,
            )
            raw = (resp.choices[0].message.content or "").strip()
        except Exception as e:  # noqa: BLE001
            logger.warning("judge 批处理失败，转逐维：%s", e)
        parsed = _extract_json(raw) if raw else None
        result: dict[str, DimensionResult] | None = None
        if parsed and "D4" in parsed and "D6" in parsed:
            result = {
                "D4": DimensionResult("D4", "法律依据正确性", _clamp_score(parsed["D4"].get("score")), 3,
                                      str(parsed["D4"].get("rationale", ""))[:200] or "LLM-judge 未给理由",
                                      "scored(llm-judge)"),
                "D6": DimensionResult("D6", "用户可理解性", _clamp_score(parsed["D6"].get("score")), 3,
                                      str(parsed["D6"].get("rationale", ""))[:200] or "LLM-judge 未给理由",
                                      "scored(llm-judge)"),
            }

        # 2) 批处理失败 → 逐维度两次请求（免费模型走此路径，仍可拿到权威分）
        if result is None:
            logger.info("批处理未成功，改用逐维度裁判（2 次请求）")
            out: dict[str, DimensionResult] = {}
            for dim_id in ("D4", "D6"):
                r = _call_dim(dim_id, review_json)
                out[dim_id] = r if r is not None else _heuristic_fallback(review, dim_id)
            result = out

        if use_cache:
            _CACHE[cache_key] = {
                "D4": {"score": result["D4"].score, "rationale": result["D4"].rationale},
                "D6": {"score": result["D6"].score, "rationale": result["D6"].rationale},
            }
            _save_cache()
        return result

    return judge_full, "llm-judge", model
