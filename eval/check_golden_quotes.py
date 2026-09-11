"""校验 golden 中每条 risk.quote 是否逐字命中对应合同原文（T05 质量门禁）。

运行：python eval/check_golden_quotes.py
退出码非 0 表示存在未命中 quote（需修正 golden 或样本）。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "samples"
REVIEWS = SAMPLES / "reviews"


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def main() -> int:
    failures = 0
    total = 0
    for gold_path in sorted(REVIEWS.glob("*.golden.json")):
        name = gold_path.stem.replace(".golden", "")
        src = SAMPLES / f"{name}.md"
        golden = json.loads(gold_path.read_text(encoding="utf-8"))
        text = src.read_text(encoding="utf-8") if src.exists() else ""
        norm_text = _norm(text)
        n_risks = len(golden.get("risks") or [])
        for i, r in enumerate(golden.get("risks") or []):
            total += 1
            q = r.get("quote", "")
            if not q:
                print(f"[EMPTY]  {name} risk#{i+1} 缺少 quote")
                failures += 1
                continue
            if _norm(q) not in norm_text:
                print(f"[MISS]   {name} risk#{i+1} quote 未命中原文: {q[:40]}...")
                failures += 1
        # unknown/negative 不应抽条款或风险
        ctype = golden.get("contract_type")
        if ctype == "unknown":
            if golden.get("key_clauses") or golden.get("risks"):
                print(f"[WARN]   {name} 为 unknown 却含条款/风险")
                failures += 1
        print(f"[ok]     {name}: {n_risks} 条风险 quote 校验完成")

    print(f"\n总计 {total} 条 quote，失败 {failures} 条。")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
