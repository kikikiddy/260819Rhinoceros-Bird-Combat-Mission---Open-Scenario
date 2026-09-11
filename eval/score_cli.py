"""对单个/全部样本跑 7 维 rubric（T04 验证 / T05 预演 / T07 判别力基础）。

用法：
    # 全部样本：用 golden 当"好档"审阅结果，配 reference + 原文
    python eval/score_cli.py --all

    # 单样本
    python eval/score_cli.py --name sample_labor_contract

    # 自定义审阅结果（如模型真实输出）
    python eval/score_cli.py --name sample_labor_contract --review path/to/review.json

说明：
    D4/D6 默认走内置启发式代理（标注 scored(heuristic)），离线即可出完整综合分；
    注入真 LLM-judge（T06）后分数更权威。D1/D2 需对应 reference，缺失则 needs_reference。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval.rubric import DIMENSIONS, score_all  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "samples"
NAMES = [p.stem.replace(".golden", "") for p in sorted((SAMPLES / "reviews").glob("*.golden.json"))]


def _load(name: str, review_path: str | None) -> tuple[dict, dict | None, str]:
    if review_path:
        review = json.loads(Path(review_path).read_text(encoding="utf-8"))
    else:
        review = json.loads((SAMPLES / "reviews" / f"{name}.golden.json").read_text(encoding="utf-8"))
    ref_path = SAMPLES / "references" / f"{name}.reference.json"
    reference = json.loads(ref_path.read_text(encoding="utf-8")) if ref_path.exists() else None
    src = SAMPLES / f"{name}.md"
    contract_text = src.read_text(encoding="utf-8") if src.exists() else ""
    return review, reference, contract_text


def print_report(name: str, result: dict) -> None:
    print(f"\n=== {name} ===")
    print(f"综合分(已评维度): {result['overall_pct']}  | 已评 {result['scored_count']}/7 | 待评: {result['pending'] or '无'}")
    for d in result["details"]:
        print(f"  {d['id']} [{d['status']:>16}] {d['score']}/{d['max']}  {d['name']}")
        print(f"        {d['rationale']}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="遍历全部样本")
    ap.add_argument("--name", help="单个样本名（不含扩展名）")
    ap.add_argument("--review", help="自定义审阅 JSON（默认用 golden）")
    args = ap.parse_args()

    names = NAMES if args.all else ([args.name] if args.name else [])
    if not names:
        ap.error("需 --all 或 --name")

    for name in names:
        review, reference, text = _load(name, args.review)
        result = score_all(review, reference=reference, contract_text=text)
        print_report(name, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
