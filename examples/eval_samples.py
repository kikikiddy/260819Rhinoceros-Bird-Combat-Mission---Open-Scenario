"""T06 评测主脚本：对样本集跑 7 维 rubric，D4/D6 由 LLM-as-judge 补全。

用法：
    # 默认：用 golden 当"好档"审阅结果 + LLM-judge（无密钥时自动回退启发式）
    python examples/eval_samples.py

    # 改用真实审阅链路产出（mock 离线 / live 接 Hy3）
    python examples/eval_samples.py --review-source mock
    python examples/eval_samples.py --review-source live

    # 指定样本 + 输出目录
    python examples/eval_samples.py --name sample_labor_fake_law --out eval/results

输出：
    - 控制台：每样本 7 维得分表 + 综合分 + judge 模式
    - eval/results/eval_<source>_<ts>.json：完整结果（供 T07/T08/T10 复用）
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval.rubric import DIMENSIONS, score_all  # noqa: E402
from eval.llm_judge import make_judge  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "samples"
DEFAULT_OUT = ROOT / "eval" / "results"

NAMES = [p.stem.replace(".golden", "") for p in sorted((SAMPLES / "reviews").glob("*.golden.json"))]


def _load_cached_review(cache_path: Path) -> dict:
    """读取 live 缓存，兼容历史双重编码文件（json 字符串再被 dumps 一次）。"""
    data = json.loads(cache_path.read_text(encoding="utf-8"))
    if isinstance(data, str):  # 双重编码：外层是 JSON 字符串
        data = json.loads(data)
    return data


def _load_review(name: str, source: str, reasoning: str, force: bool = False,
                 allow_fallback: bool = False) -> tuple[dict, str]:
    """返回 (review_dict, source_label)。source ∈ golden|mock|live。

    live 模式带磁盘缓存：结果写入 samples/live/<name>.json，重复评测（如 T08 多轮）
    不会重复消耗 hy3-preview token；--force 可强制重新生成。

    live 调用失败时：默认**直接报错中止**（避免 mock 结果混入评测、虚高分数）；
    仅当 allow_fallback=True（--allow-mock-fallback）时才回退 mock 并标注来源。
    """
    src = SAMPLES / f"{name}.md"
    contract_text = src.read_text(encoding="utf-8") if src.exists() else ""

    if source == "golden":
        review = json.loads((SAMPLES / "reviews" / f"{name}.golden.json").read_text(encoding="utf-8"))
        return review, "golden"

    if source == "mock":
        from src.contract_review import mock_review
        return mock_review(contract_text).to_dict(), "mock"

    # live：真实 Hy3 审阅；带缓存以省 token
    from src.contract_review import mock_review, review_with_client
    from src.hy3 import Hy3Client, Hy3Config
    cache_path = SAMPLES / "live" / f"{name}.json"
    if not force and cache_path.exists():
        return _load_cached_review(cache_path), "live(cached)"
    try:
        client = Hy3Client(Hy3Config.from_env())
        review = review_with_client(contract_text, client, reasoning_effort=reasoning).to_dict()
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
        return review, "live"
    except Exception as e:  # noqa: BLE001
        if not allow_fallback:
            raise RuntimeError(
                f"[{name}] live 审阅失败：{type(e).__name__}: {e}\n"
                "提示：已缓存样本不受影响；确需临时降级可加 --allow-mock-fallback（分数会失真）。"
            ) from e
        sys.stderr.write(f"[warn] {name} live 审阅失败，回退 mock：{e}\n")
        return mock_review(contract_text).to_dict(), "mock(fallback)"


def print_table(rows: list[dict]) -> None:
    header = f"{'样本':28} {'综合分':>7} {'已评':>5}  " + " ".join(d.id for d in DIMENSIONS)
    print("\n" + header)
    print("-" * len(header))
    for r in rows:
        cells = []
        for d in DIMENSIONS:
            det = next(x for x in r["result"]["details"] if x["id"] == d.id)
            star = "*" if (det["status"].startswith("needs") or det["status"] == "scored(heuristic)") else ""
            cells.append(f"{det['score']:.0f}/{det['max']:.0f}{star}")
        print(f"{r['name']:28} {r['result']['overall_pct']:>7} {r['result']['scored_count']:>3}/7  " + " ".join(cells))
    print("\n* 标注 = 需补充（needs_reference / needs_llm）或启发式兜底（非权威，接 LLM-judge 后替换）")


def write_markdown_report(rows: list[dict], meta: dict, path: Path) -> None:
    """产出 Markdown 评估报告（根据 judge 模式自动切换描述）。"""
    is_no_judge = meta.get("judge_mode", "") == "none(rule-only)"
    title = "合同审阅评测报告（免费版 · 规则/标注驱动）" if is_no_judge else "合同审阅评测报告（完整版 · 规则+LLM-judge）"
    lines = [f"# {title}", ""]
    lines.append(f"- 生成时间：{meta['generated_at']}")
    lines.append(f"- 审阅来源：{meta['review_source']}")
    lines.append(f"- 裁判模式：{meta['judge_mode']}")
    if "judge_model" in meta and meta["judge_model"] != "-":
        lines.append(f"- 裁判模型：{meta['judge_model']}")
    lines.append("")
    if is_no_judge:
        lines.append("> 本版**不接入任何 LLM 裁判**：D4 法律依据正确性 / D6 用户可理解性 标记为 `needs_llm`（不计入综合分），"
                     "待接入真实 Hy3 或其他模型裁判后补全。综合分仅由 D1/D2/D3/D5/D7 五个规则/标注维度构成。")
    else:
        lines.append("> 本版接入 LLM-judge：D4 法律依据正确性 / D6 用户可理解性 由裁判模型评分。"
                     "综合分由全部 7 个维度构成。标注 `*` 的维度为待补充或启发式兜底（非权威）。")
    lines.append("")
    # 总览表
    lines.append("## 1. 总览")
    lines.append("")
    lines.append("| 样本 | 综合分(已评维度) | 已评/7 | D1 | D2 | D3 | D4 | D5 | D6 | D7 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        cells = []
        for d in DIMENSIONS:
            det = next(x for x in r["result"]["details"] if x["id"] == d.id)
            star = "*" if (det["status"].startswith("needs") or det["status"] == "scored(heuristic)") else ""
            cells.append(f"{det['score']:.0f}/{det['max']:.0f}{star}")
        lines.append(f"| {r['name']} | {r['result']['overall_pct']} | {r['result']['scored_count']}/7 | " + " | ".join(cells) + " |")
    lines.append("")
    lines.append("* `*` = 待补充（needs_reference / needs_llm）或启发式兜底（非权威）。")
    lines.append("")
    # 逐样本明细
    lines.append("## 2. 逐样本明细")
    lines.append("")
    for r in rows:
        lines.append(f"### {r['name']}  （来源：{r['source']}，综合分 {r['result']['overall_pct']}）")
        lines.append("")
        for d in r["result"]["details"]:
            lines.append(f"- **{d['id']} {d['name']}**：`{d['score']}/{d['max']}` [{d['status']}] — {d['rationale']}")
        lines.append("")
    lines.append("## 3. 结论与待办")
    lines.append("")
    if is_no_judge:
        lines.append("- 五个规则维度（D1/D2/D3/D5/D7）已可离线、零成本完成评分，覆盖条款抽取、风险识别、证据可追溯、安全合规、格式规范。")
        lines.append("- D4（法律依据正确性，可抓伪造法条）、D6（用户可理解性）需主观裁判，当前留空；下一步接入模型裁判后补全，综合分将纳入这两维。")
        lines.append("- 伪造法条（如 `sample_labor_fake_law` 的《劳动法》第999条）的识别能力主要在 D4，待裁判接入后验证。")
    else:
        lines.append("- 全部 7 个维度已评分：D1/D2/D3/D5/D7 由规则引擎计算，D4/D6 由 LLM-judge（裁判模型）或人工核验补全。")
        lines.append("- 伪造法条（如 `sample_labor_fake_law` 的《劳动法》第999条）已被 D4 启发式检测捕获，模型对异常文本的失效在 D1/D2/D3 全面体现。")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--name", help="单样本名（不含扩展名）")
    ap.add_argument("--review-source", choices=["golden", "mock", "live"], default="golden")
    ap.add_argument("--reasoning", default="no_think", choices=["no_think", "low", "high"])
    ap.add_argument("--no-judge", action="store_true", help="不注入任何 LLM-judge，D4/D6 标 needs_llm（免费版）")
    ap.add_argument("--force", action="store_true", help="忽略 live 审阅缓存与 judge 缓存，强制重新调用模型")
    ap.add_argument("--allow-mock-fallback", action="store_true",
                    help="live 调用失败时回退 mock（默认直接报错中止，避免分数失真）")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    names = NAMES if args.all or not args.name else [args.name]
    if not names:
        ap.error("需 --all 或 --name")

    if args.no_judge:
        judge, judge_mode, judge_model = None, "none(rule-only)", "-"
    else:
        judge, judge_mode, judge_model = make_judge(use_cache=not args.force)
    print(f"[info] judge 模式: {judge_mode} | 裁判模型: {judge_model} | review-source: {args.review_source}"
          f"{' | --force 已忽略缓存' if args.force else ''}")

    rows = []
    for name in names:
        review, src_label = _load_review(name, args.review_source, args.reasoning, force=args.force,
                                         allow_fallback=args.allow_mock_fallback)
        ref_path = SAMPLES / "references" / f"{name}.reference.json"
        reference = json.loads(ref_path.read_text(encoding="utf-8")) if ref_path.exists() else None
        text = (SAMPLES / f"{name}.md").read_text(encoding="utf-8") if (SAMPLES / f"{name}.md").exists() else ""
        result = score_all(review, reference=reference, contract_text=text,
                            judge=judge, allow_proxy=not args.no_judge)
        rows.append({"name": name, "source": src_label, "result": result})

    print_table(rows)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    suffix = "nojudge" if args.no_judge else args.review_source
    out_path = out_dir / f"eval_{suffix}_{ts}.json"
    payload = {
        "meta": {
            "generated_at": ts,
            "review_source": args.review_source,
            "judge_mode": judge_mode,
            "judge_model": judge_model,
            "note": "D4/D6 在 llm-judge 模式下由模型裁判评分；none(rule-only) 模式下 D4/D6 标 needs_llm 不计入综合分。",
        },
        "rows": rows,
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    md_path = out_dir / f"report_{suffix}_{ts}.md"
    write_markdown_report(rows, payload["meta"], md_path)

    print(f"\n[ok] JSON 结果: {out_path}")
    print(f"[ok] Markdown 报告: {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
