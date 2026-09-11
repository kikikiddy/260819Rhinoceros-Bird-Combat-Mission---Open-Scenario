#!/usr/bin/env python
"""合同审阅 CLI 入口（T03）。

用法：
    # 无 Hy3 端点：mock 模式端到端验证链路（默认）
    python run_review.py --input samples/sample_labor_contract.md --mock
    python run_review.py --input samples/sample_noncontract.md --mock

    # 接真实 Hy3（需配置 .env / 环境变量）
    python run_review.py --input samples/sample_labor_contract.md --live
    python run_review.py --text "甲方...乙方...试用期..." --live

输出：
    --format json     默认，输出结构化 JSON
    --format markdown 输出面向用户的 Markdown
    --out PATH        写入文件，否则打印到 stdout
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# 让 `python run_review.py` 在仓库根目录直接运行
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.contract_review import ReviewResult, mock_review, review_with_client, to_markdown  # noqa: E402
from src.hy3 import Hy3Client, Hy3Config, configure_logging  # noqa: E402


def read_input(args) -> str:
    if args.text:
        return args.text
    p = Path(args.input)
    if not p.exists():
        raise FileNotFoundError(f"输入文件不存在: {p}")
    return p.read_text(encoding="utf-8")


def run(contract_text: str, live: bool, reasoning_effort: str, max_tokens: int) -> ReviewResult:
    if live:
        client = Hy3Client(Hy3Config.from_env())
        return review_with_client(contract_text, client, reasoning_effort=reasoning_effort,
                                  max_tokens=max_tokens)
    return mock_review(contract_text)


def main() -> int:
    parser = argparse.ArgumentParser(description="中小企业合同审阅助手 CLI")
    parser.add_argument("--input", "-i", help="合同文件路径（.md/.txt）")
    parser.add_argument("--text", "-t", help="直接传入合同文本")
    parser.add_argument("--mock", action="store_true", help="离线 mock 模式（默认）")
    parser.add_argument("--live", action="store_true", help="调用真实 Hy3 端点")
    parser.add_argument("--reasoning", default="no_think", choices=["no_think", "low", "high"])
    parser.add_argument("--max-tokens", type=int, default=8192,
                        help="live 模式输出 token 上限（默认 8192，为推理型上游的思维链预留预算）")
    parser.add_argument("--format", "-f", default="json", choices=["json", "markdown"])
    parser.add_argument("--out", "-o", help="输出文件路径")
    parser.add_argument("--verbose", "-v", action="store_true", help="开启调试日志")
    args = parser.parse_args()

    configure_logging(logging_level(args.verbose))

    if not args.input and not args.text:
        parser.error("需要 --input 或 --text")

    # 默认 mock；仅当显式 --live 且配置了非空/非默认 key 时才走 live
    live = args.live
    if live:
        key = os.getenv("HY3_API_KEY", Hy3Config().api_key if False else "EMPTY")
        if key in ("", "EMPTY"):
            print("[warn] 未配置 HY3_API_KEY/base_url，回退到 mock 模式。", file=sys.stderr)
            live = False

    contract_text = read_input(args)
    result = run(contract_text, live, args.reasoning, args.max_tokens)

    output = result.to_json() if args.format == "json" else to_markdown(result)
    if args.out:
        Path(args.out).write_text(output, encoding="utf-8")
        print(f"[ok] 已写入 {args.out}（source={result.source}, type={result.contract_type}, risks={len(result.risks)}）")
    else:
        print(output)
    return 0


def logging_level(verbose: bool) -> int:
    import logging

    return logging.DEBUG if verbose else logging.INFO


if __name__ == "__main__":
    raise SystemExit(main())
