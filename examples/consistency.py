"""T08 一致性验证：评测管线确定性 + 模型输出稳定性。

用法：
    # Part 1（零 token）：对缓存 live 审阅跑 3 轮评分，验证分数完全一致
    python examples/consistency.py

    # Part 2（2 次 hy3-preview 调用）：重新生成 1 份样本，与缓存版本结构对比
    python examples/consistency.py --with-model --name sample_labor_contract

输出：
    - 控制台：一致性结论表
    - T08_一致性验证.md：完整报告（项目根目录）
    - Part 2 另存 eval/results/consistency_<name>_run{1,2}.json（重生成证据）

省 token 设计：
    - Part 1 纯本地计算（judge 结果全部命中缓存，无 API 调用）。
    - Part 2 仅调用 hy3-preview 2 次（同一合同重新生成），对比与评分均免费；
      重生成版本用 --no-judge 规则评分（5 维），不消耗 glm-5.3 额度。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval.rubric import _quote_hit, score_all  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "samples"
RESULTS = ROOT / "eval" / "results"

NAMES = [p.stem.replace(".golden", "") for p in sorted((SAMPLES / "reviews").glob("*.golden.json"))]


def _load(name: str) -> tuple[dict, dict | None, str]:
    review = json.loads((SAMPLES / "live" / f"{name}.json").read_text(encoding="utf-8"))
    ref_path = SAMPLES / "references" / f"{name}.reference.json"
    reference = json.loads(ref_path.read_text(encoding="utf-8")) if ref_path.exists() else None
    text_path = SAMPLES / f"{name}.md"
    text = text_path.read_text(encoding="utf-8") if text_path.exists() else ""
    return review, reference, text


# ----------------------------- Part 1：管线确定性 -----------------------------
def part1_pipeline(n_rounds: int = 3) -> dict:
    """对每份缓存 live 审阅跑 n_rounds 轮评分，验证逐维分数完全一致。"""
    from eval.llm_judge import make_judge

    judge, mode, model = make_judge(use_cache=True)
    print(f"[info] Part1 管线确定性：{n_rounds} 轮 × {len(NAMES)} 样本 | judge={mode}({model})，缓存命中无 API 调用")

    rows = []
    all_stable = True
    for name in NAMES:
        review, reference, text = _load(name)
        runs = []
        for _ in range(n_rounds):
            result = score_all(review, reference=reference, contract_text=text, judge=judge)
            # 只比较分数与状态（rationale 可能因缓存字典序等非确定性来源微变，不计入）
            runs.append([(d["id"], d["score"], d["status"]) for d in result["details"]])
        stable = all(r == runs[0] for r in runs)
        overall = score_all(review, reference=reference, contract_text=text, judge=judge)["overall_pct"]
        all_stable = all_stable and stable
        rows.append({"name": name, "stable": stable, "overall": overall, "rounds": n_rounds})
        mark = "✓ 一致" if stable else "✗ 不一致"
        print(f"  {name:28} {mark}  综合分={overall}")
    print(f"[result] Part1 结论：{'全部样本 ' + str(n_rounds) + ' 轮评分完全一致（管线确定性 ✓）' if all_stable else '存在不一致样本（需排查）'}")
    return {"rows": rows, "all_stable": all_stable, "rounds": n_rounds}


# ----------------------------- Part 2：模型输出稳定性 -----------------------------
def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _profile(review: dict, contract_text: str) -> dict:
    """提取 review 的可比结构特征。"""
    risks = review.get("risks") or []
    return {
        "contract_type": review.get("contract_type"),
        "n_key_clauses": len(review.get("key_clauses") or []),
        "clause_names": {c.get("name", "") for c in (review.get("key_clauses") or [])},
        "n_risks": len(risks),
        "risk_clauses": {r.get("clause", "") for r in risks},
        "risk_levels": sorted(r.get("level", "") for r in risks),
        "quote_hits": sum(1 for r in risks if _quote_hit(r.get("quote", ""), contract_text)),
        "quote_total": len(risks),
        "has_disclaimer": bool((review.get("disclaimer") or "").strip()),
        "summary_len": len(review.get("summary") or ""),
    }


def part2_model(name: str, reuse_saved: bool = True) -> dict:
    """重新生成同一合同 2 次，与缓存版本做结构对比（仅 2 次 hy3-preview 调用）。

    reuse_saved=True 时，若 eval/results/consistency_<name>_run{1,2}.json 已存在则直接复用
    （兼容历史双重编码格式），不再消耗 token。
    """
    from src.contract_review import review_with_client
    from src.hy3 import Hy3Client, Hy3Config

    text = (SAMPLES / f"{name}.md").read_text(encoding="utf-8")
    cached = json.loads((SAMPLES / "live" / f"{name}.json").read_text(encoding="utf-8"))

    def _read_saved(path: Path) -> dict | None:
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, str):  # 双重编码的历史文件
            data = json.loads(data)
        return data if isinstance(data, dict) else None

    regen = []
    client = None
    for i in (1, 2):
        out = RESULTS / f"consistency_{name}_run{i}.json"
        saved = _read_saved(out) if reuse_saved else None
        if saved is not None:
            print(f"[info] Part2 复用已保存的 run{i}（零 token）")
            regen.append(saved)
            continue
        if client is None:
            client = Hy3Client(Hy3Config.from_env())
        print(f"[info] Part2 重生成 {name} 第 {i} 次（hy3-preview 调用 {i}/2）...")
        review = review_with_client(text, client).to_dict()
        out.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  已保存 {out.name}")
        regen.append(review)

    versions = [("cached", cached)] + [(f"run{i+1}", r) for i, r in enumerate(regen)]
    profiles = {label: _profile(rv, text) for label, rv in versions}

    print(f"\n[info] Part2 结构对比（{name}，{len(versions)} 个版本）：")
    print(f"  {'特征':24} " + " ".join(f"{lb:>8}" for lb, _ in versions))
    for feat in ("contract_type", "n_key_clauses", "n_risks", "quote_hits", "has_disclaimer"):
        vals = [profiles[lb][feat] for lb, _ in versions]
        print(f"  {feat:24} " + " ".join(f"{str(v):>8}" for v in vals))

    # 两两相似度（缓存 vs run1 / run2；run1 vs run2）
    pairs = [("cached", "run1"), ("cached", "run2"), ("run1", "run2")]
    sims = {}
    for a, b in pairs:
        pa, pb = profiles[a], profiles[b]
        sims[f"{a}-vs-{b}"] = {
            "type_same": pa["contract_type"] == pb["contract_type"],
            "clause_name_jaccard": round(_jaccard(pa["clause_names"], pb["clause_names"]), 3),
            "risk_clause_jaccard": round(_jaccard(pa["risk_clauses"], pb["risk_clauses"]), 3),
            "risk_count_diff": abs(pa["n_risks"] - pb["n_risks"]),
        }
    print(f"\n  {'版本对':16} {'类型':>4} {'条款J':>6} {'风险J':>6} {'风险数差':>6}")
    for pair, s in sims.items():
        print(f"  {pair:16} {'同' if s['type_same'] else '异':>4} {s['clause_name_jaccard']:>6} {s['risk_clause_jaccard']:>6} {s['risk_count_diff']:>6}")

    # 对 3 个版本分别跑免费 5 维评分（--no-judge 等价），比较分数稳定性
    reference = json.loads((SAMPLES / "references" / f"{name}.reference.json").read_text(encoding="utf-8"))
    scores = {}
    print(f"\n[info] 免费规则评分（D1/D2/D3/D5/D7，无 API 调用）：")
    for label, rv in versions:
        result = score_all(rv, reference=reference, contract_text=text, judge=None, allow_proxy=False)
        rule = {d["id"]: d["score"] for d in result["details"] if d["id"] in ("D1", "D2", "D3", "D5", "D7")}
        scores[label] = {"overall": result["overall_pct"], "rule": rule}
        print(f"  {label:8} 综合(5维)={result['overall_pct']:>7}  {rule}")

    rule_stable = scores["cached"]["rule"] == scores["run1"]["rule"] == scores["run2"]["rule"]
    avg_risk_j = sum(sims[p]["risk_clause_jaccard"] for p in sims) / len(sims)
    verdict = {
        "versions": [lb for lb, _ in versions],
        "profiles": profiles,
        "similarities": sims,
        "rule_scores": scores,
        "rule_score_stable": rule_stable,
        "avg_risk_clause_jaccard": round(avg_risk_j, 3),
        "type_consistent": all(s["type_same"] for s in sims.values()),
    }
    print(f"\n[result] Part2 结论：类型{'一致' if verdict['type_consistent'] else '不一致'} | "
          f"风险条款平均 Jaccard={verdict['avg_risk_clause_jaccard']} | "
          f"5维规则分{'完全一致' if rule_stable else '存在波动'}")
    return verdict


# ----------------------------- 报告 -----------------------------
def write_report(p1: dict, p2: dict | None, name: str | None) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    lines = ["# T08 一致性验证报告", ""]
    lines.append(f"- 生成时间：{ts}")
    lines.append(f"- Part1：评测管线确定性（{p1['rounds']} 轮重跑，零 token）")
    lines.append(f"- Part2：模型输出稳定性（{name or '-'}，2 次 hy3-preview 调用）")
    lines.append("")

    lines.append("## 1. Part1 评测管线确定性")
    lines.append("")
    lines.append(f"对 {len(p1['rows'])} 份缓存 live 审阅各跑 {p1['rounds']} 轮 7 维评分（judge 结果全部命中缓存），"
                 f"逐维分数与状态完全一致即为稳定。")
    lines.append("")
    lines.append("| 样本 | 轮数 | 综合分 | 结果 |")
    lines.append("|---|---|---|---|")
    for r in p1["rows"]:
        lines.append(f"| {r['name']} | {r['rounds']} | {r['overall']} | {'✓ 一致' if r['stable'] else '✗ 不一致'} |")
    lines.append("")
    lines.append(f"**结论**：{'全部样本多轮评分完全一致，评测管线（规则引擎 + judge 缓存）具备确定性 ✓' if p1['all_stable'] else '存在不一致样本，需排查非确定性来源 ✗'}")
    lines.append("")

    if p2:
        lines.append("## 2. Part2 模型输出稳定性")
        lines.append("")
        lines.append(f"对 `{name}` 用 hy3-preview 重新生成 2 次，与缓存版本（共 3 个版本）做结构对比：")
        lines.append("")
        lines.append("| 特征 | " + " | ".join(p2["versions"]) + " |")
        lines.append("|---|" + "---|" * len(p2["versions"]))
        feats = ["contract_type", "n_key_clauses", "n_risks", "quote_hits", "has_disclaimer"]
        for f in feats:
            vals = [str(p2["profiles"][lb][f]) for lb in p2["versions"]]
            lines.append(f"| {f} | " + " | ".join(vals) + " |")
        lines.append("")
        lines.append("### 版本对相似度")
        lines.append("")
        lines.append("| 版本对 | 类型 | 条款名 Jaccard | 风险条款 Jaccard | 风险数差 |")
        lines.append("|---|---|---|---|---|")
        for pair, s in p2["similarities"].items():
            lines.append(f"| {pair} | {'同' if s['type_same'] else '异'} | {s['clause_name_jaccard']} | {s['risk_clause_jaccard']} | {s['risk_count_diff']} |")
        lines.append("")
        lines.append("### 免费 5 维规则评分对比")
        lines.append("")
        lines.append("| 版本 | D1 | D2 | D3 | D5 | D7 | 综合(5维) |")
        lines.append("|---|---|---|---|---|---|---|")
        for lb in p2["versions"]:
            r = p2["rule_scores"][lb]["rule"]
            lines.append(f"| {lb} | {r['D1']}/3 | {r['D2']}/3 | {r['D3']}/3 | {r['D5']}/1 | {r['D7']}/1 | {p2['rule_scores'][lb]['overall']} |")
        lines.append("")
        lines.append(f"**结论**：合同类型{'一致' if p2['type_consistent'] else '不一致'}；"
                     f"风险条款平均 Jaccard 相似度 {p2['avg_risk_clause_jaccard']}；"
                     f"5 维规则分{'完全一致（输出稳定）' if p2['rule_score_stable'] else '存在波动（输出有差异）'}。")
        lines.append("")

    lines.append("## 3. token 消耗")
    lines.append("")
    lines.append("| 部分 | hy3-preview 调用 | glm-5.3 调用 | 说明 |")
    lines.append("|---|---|---|---|")
    lines.append(f"| Part1 管线确定性 | 0 | 0 | 本地计算 + judge 缓存命中 |")
    lines.append(f"| Part2 模型稳定性 | {2 if p2 else 0} | 0 | 重生成 2 次；对比与评分均免费 |")
    lines.append("")

    path = ROOT / "T08_一致性验证.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n[ok] 报告已写入 {path}")
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-model", action="store_true", help="启用 Part2（消耗 2 次 hy3-preview 调用）")
    ap.add_argument("--name", default="sample_labor_contract", help="Part2 用于重生成的样本名")
    ap.add_argument("--rounds", type=int, default=3, help="Part1 重跑轮数")
    args = ap.parse_args()

    p1 = part1_pipeline(n_rounds=args.rounds)
    p2 = part2_model(args.name) if args.with_model else None
    write_report(p1, p2, args.name if args.with_model else None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
