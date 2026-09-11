"""T07 判别力实验（免费 · 规则维度版，不调任何模型）。

设计：同一份合同，对比两组审阅结果在 5 个规则/标注维度（D1/D2/D3/D5/D7）上的得分：
  - 好档 (golden)：专家标注的理想答卷
  - 坏档 (degraded)：人为退化的审阅（删 quote、删风险、删免责声明、破结构）

若 好档综合分 显著 > 坏档综合分，则证明本评测方法**具备判别力**——
即使不调用 Hy3，也能区分"优质审阅"与"劣质审阅"。

用法：
    python examples/discriminability.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval.rubric import DIMENSIONS, score_all  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "samples"
NAMES = [p.stem.replace(".golden", "") for p in sorted((SAMPLES / "reviews").glob("*.golden.json"))]
# 规则维度（不依赖 LLM-judge）
RULE_IDS = {"D1", "D2", "D3", "D5", "D7"}


def _degrade(golden: dict) -> dict:
    """构造一份刻意劣化的审阅，用于判别力下界。"""
    bad = json.loads(json.dumps(golden))  # 深拷贝
    risks = bad.get("risks") or []
    if risks:
        # 1) 删掉一半风险（D2 风险识别下降）
        kept = risks[: max(1, len(risks) // 2)]
        # 2) 剩余风险的 quote 清空（D3 证据可追溯归零）
        for r in kept:
            r["quote"] = ""
        bad["risks"] = kept
    # 3) 删掉免责声明（D5 安全合规归零）
    bad.pop("disclaimer", None)
    bad["disclaimer"] = None
    # 4) level 写成非法值（D7 格式规范扣分）
    for r in bad.get("risks") or []:
        r["level"] = "极高"
    return bad


def _rule_score(result: dict) -> tuple[float, int, int]:
    scored = [d for d in result["details"] if d["id"] in RULE_IDS]
    s = sum(d["score"] for d in scored)
    m = sum(d["max"] for d in scored)
    return round(100 * s / m, 1), s, m


def main() -> int:
    print(f"{'样本':26} {'好档(规则分)':>14} {'坏档(规则分)':>14} {'差值':>8}  判别力")
    print("-" * 82)
    all_ok = True
    for name in NAMES:
        golden = json.loads((SAMPLES / "reviews" / f"{name}.golden.json").read_text(encoding="utf-8"))
        ref_path = SAMPLES / "references" / f"{name}.reference.json"
        reference = json.loads(ref_path.read_text(encoding="utf-8")) if ref_path.exists() else None
        text = (SAMPLES / f"{name}.md").read_text(encoding="utf-8") if (SAMPLES / f"{name}.md").exists() else ""

        good = score_all(golden, reference=reference, contract_text=text, judge=None, allow_proxy=False)
        bad = score_all(_degrade(golden), reference=reference, contract_text=text, judge=None, allow_proxy=False)

        gs, gn, gm = _rule_score(good)
        bs, bn, bm = _rule_score(bad)
        diff = round(gs - bs, 1)
        ok = gs > bs
        all_ok = all_ok and ok
        print(f"{name:26} {gs:>7}/{gm:<6} {bs:>7}/{bm:<6} {diff:>7}   {'✓ 可区分' if ok else '✗ 失效'}")

    print("-" * 82)
    print(f"判别力结论：{'全部样本好档>坏档，rubric 规则维度具备判别力 ✓' if all_ok else '存在失效样本，需复查 rubric'}")
    print("（说明：本实验仅用 D1/D2/D3/D5/D7 规则维度，未调用任何 LLM，零 token 消耗。）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
