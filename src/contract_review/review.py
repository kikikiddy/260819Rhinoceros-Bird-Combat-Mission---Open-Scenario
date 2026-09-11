"""合同审阅核心链路（T03）。

输入合同文本 → 调用 Hy3 → 解析为结构化审阅结果 → 可输出 JSON / Markdown。
含 mock 模式：无真实 Hy3 端点时也能端到端验证链路与输出结构。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from ..hy3 import Hy3Client
from .prompts import build_messages

VALID_TYPES = {"labor", "lease", "unknown"}
VALID_LEVELS = {"高", "中", "低"}
DEFAULT_DISCLAIMER = "本结果由 AI 辅助生成，仅供参考，不构成法律意见，建议由执业律师最终把关。"


@dataclass
class ReviewResult:
    """结构化审阅结果。"""

    contract_type: str = "unknown"
    summary: str = ""
    key_clauses: list[dict[str, str]] = field(default_factory=list)
    risks: list[dict[str, str]] = field(default_factory=list)
    disclaimer: str = DEFAULT_DISCLAIMER
    raw: str = ""  # 模型原始输出（调试/归因用）
    source: str = "live"  # live | mock

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_type": self.contract_type,
            "summary": self.summary,
            "key_clauses": self.key_clauses,
            "risks": self.risks,
            "disclaimer": self.disclaimer,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)


def extract_json(text: str) -> dict[str, Any]:
    """从模型输出中抽取 JSON 对象，兼容裸 JSON 与 ```json 代码块。"""
    text = text.strip()
    # 1. 直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 2. ```json ... ``` 代码块
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # 3. 取第一个 { ... } 片段（贪婪到最外层）
    start = text.find("{")
    if start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break
    raise ValueError("无法从模型输出中解析 JSON")


def normalize(parsed: dict[str, Any]) -> ReviewResult:
    """校验并归一化模型输出，确保 D7 格式规范性。"""
    contract_type = parsed.get("contract_type", "unknown")
    if contract_type not in VALID_TYPES:
        contract_type = "unknown"

    key_clauses = []
    for c in parsed.get("key_clauses", []) or []:
        if isinstance(c, dict) and c.get("name"):
            key_clauses.append(
                {"name": str(c["name"]), "content": str(c.get("content", "")).strip()}
            )

    risks = []
    for r in parsed.get("risks", []) or []:
        if not isinstance(r, dict):
            continue
        level = r.get("level", "中")
        if level not in VALID_LEVELS:
            level = "中"
        risks.append(
            {
                "level": level,
                "clause": str(r.get("clause", "")).strip(),
                "quote": str(r.get("quote", "")).strip(),
                "risk": str(r.get("risk", "")).strip(),
                "suggestion": str(r.get("suggestion", "")).strip(),
            }
        )

    disclaimer = parsed.get("disclaimer") or DEFAULT_DISCLAIMER

    return ReviewResult(
        contract_type=contract_type,
        summary=str(parsed.get("summary", "")).strip(),
        key_clauses=key_clauses,
        risks=risks,
        disclaimer=disclaimer,
    )


def review_with_client(contract_text: str, client: Hy3Client, *, reasoning_effort: str = "no_think",
                        max_tokens: int | None = None) -> ReviewResult:
    """用真实 Hy3 客户端审阅合同。

    max_tokens 控制输出上限，默认 None 表示交给客户端配置（HY3_OUTPUT_MAX_TOKENS，默认 8192）。
    注意：上游为推理型模型时会把思维链计入同一预算，预算过小会导致正文被截断为空，
    客户端已内置"空输出自动加倍预算重试"的保护。
    """
    raw = client.chat(build_messages(contract_text), reasoning_effort=reasoning_effort,
                      max_tokens=max_tokens)
    try:
        parsed = extract_json(raw)
        result = normalize(parsed)
    except ValueError:
        # 输出非 JSON：返回带说明的 unknown，保留原文供归因
        if not (raw or "").strip():
            hint = "模型输出为空（多因推理预算被思维链占满），可增大 HY3_OUTPUT_MAX_TOKENS 后重试"
        else:
            hint = "模型未输出合法 JSON，请检查模型/参数"
        result = ReviewResult(
            contract_type="unknown",
            summary=f"[解析失败] {hint}。",
            disclaimer=DEFAULT_DISCLAIMER,
        )
    result.raw = raw
    result.source = "live"
    return result


def to_markdown(result: ReviewResult) -> str:
    """将审阅结果渲染为面向用户的 Markdown。"""
    type_label = {"labor": "劳动合同", "lease": "商铺/办公租赁合同", "unknown": "未识别合同类型"}.get(
        result.contract_type, result.contract_type
    )
    lines = [
        f"# 合同审阅结果（{type_label}）",
        "",
        f"**整体概况**：{result.summary or '—'}",
        "",
        "## 关键条款",
        "",
    ]
    if result.key_clauses:
        for c in result.key_clauses:
            lines.append(f"- **{c['name']}**：{c['content'] or '—'}")
    else:
        lines.append("- （未抽取到关键条款）")

    lines += ["", "## 风险提示", ""]
    if result.risks:
        order = {"高": 0, "中": 1, "低": 2}
        for i, r in enumerate(sorted(result.risks, key=lambda x: order.get(x["level"], 9)), 1):
            lines.append(f"### {i}. 【{r['level']}风险】{r['clause'] or '—'}")
            lines.append(f"> 原文：{r['quote'] or '—'}")
            lines.append("")
            lines.append(f"- **风险**：{r['risk'] or '—'}")
            lines.append(f"- **建议**：{r['suggestion'] or '—'}")
            lines.append("")
    else:
        lines.append("未发现明显风险。")

    lines += ["---", "", f"*{result.disclaimer}*"]
    return "\n".join(lines)
