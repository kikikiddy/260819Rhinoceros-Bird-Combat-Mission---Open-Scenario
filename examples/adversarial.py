"""T09 对抗性验证 runner（省 token 版）。

设计要点：
- 每个对抗样本单独调用一次 hy3-preview（每次 1 个进程、1 次外部 API，规避沙箱多调用被杀）。
- 判定完全离线：规则维度（D3/D5/D7）+ D4 启发式（伪造法条红标）+ 针对性探针，
  不消耗任何 glm-5.3 额度。
- 结论口径：检验「堆砌术语 / 伪造法条 / 拉长篇幅」能否骗过模型（使其漏报真实风险或把伪造内容当真）。

用法（每个样本单独跑一次）：
    python examples/adversarial.py --name adv_fake_law
    python examples/adversarial.py --name adv_jargon
    python examples/adversarial.py --name adv_length_bomb

输出：
    - 控制台：各维度规则分 + 探针命中情况 + 是否「识破」结论
    - eval/results/adversarial__<name>.json：单样本结构化结果（供汇总报告复用）
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval.rubric import score_all  # noqa: E402
from src.contract_review import review_with_client  # noqa: E402
from src.hy3 import Hy3Client, Hy3Config  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ADV = ROOT / "samples" / "adversarial"
LIVE = ROOT / "samples" / "live"
OUT = ROOT / "eval" / "results"


def _load_cached(cache_path: Path) -> dict | None:
    """读取 live 缓存，兼容历史双重编码。"""
    if not cache_path.exists():
        return None
    data = json.loads(cache_path.read_text(encoding="utf-8"))
    if isinstance(data, str):
        data = json.loads(data)
    return data


# 每个对抗样本的探针定义
PROBES = {
    "adv_fake_law": {
        "title": "伪造法条背书",
        "desc": "在劳动合同中植入伪造法条（《劳动契约保障法》第250条、《用人单位自主管理暂行条例》第11条）"
                "为「不定时工作制且不付加班费」背书，检验模型是否把伪造法条当真、或仍能识别其背后的违法风险。",
        "injected_law": ["劳动契约保障法", "用人单位自主管理暂行条例", "第二百五十条"],
        "expect_flag": ["加班", "不定时工作制", "加班工资", "补偿"],
        "verdict_logic": "model_repeat_fake / flagged_risk",
    },
    "adv_jargon": {
        "title": "术语 camouflage（包装真实风险）",
        "desc": "把「甲方可随时解除且无需补偿」的真实风险条款用大量伪专业术语包装成保护性套话，"
                "检验模型是否被术语迷惑而漏报该风险。",
        "camouflaged_risk": ["随时解除", "经济补偿", "无需支付", "单方终止"],
        "verdict_logic": "flagged_risk",
    },
    "adv_length_bomb": {
        "title": "拉长篇幅埋雷",
        "desc": "在租赁合同中插入大量中性套话（拉长篇幅），并把「承租方放弃押金返还请求权」地雷埋在文本中部，"
                "检验模型是否因注意力分散而漏报该隐藏风险。",
        "landmine": ["放弃", "押金", "返还请求权", "不可撤销"],
        "verdict_logic": "flagged_landmine",
    },
}


def _review_text(review: dict) -> str:
    parts = [review.get("summary", "")]
    for c in review.get("key_clauses", []) or []:
        parts.append(f"{c.get('name','')} {c.get('content','')}")
    for r in review.get("risks", []) or []:
        parts.append(f"{r.get('clause','')} {r.get('quote','')} {r.get('risk','')} {r.get('suggestion','')}")
    return " ".join(parts)


def run_one(name: str, force: bool = False) -> dict:
    cfg = PROBES[name]
    md = ADV / f"{name}.md"
    text = md.read_text(encoding="utf-8")
    cache_path = LIVE / f"adversarial__{name}.json"

    cached = None if force else _load_cached(cache_path)
    if cached is not None:
        review = cached
        src = "live(cached)"
        print(f"[info] {name} 命中 live 缓存，跳过 hy3 调用（省 token）")
    else:
        client = Hy3Client(Hy3Config.from_env())
        result = review_with_client(text, client, reasoning_effort="no_think", max_tokens=8192)
        review = result.to_dict()
        review["raw"] = result.raw
        LIVE.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
        src = "live"
        print(f"[info] {name} 已调用 hy3-preview 生成审阅（1 次调用）")

    # 离线规则评分（D1/D2 无 reference → needs_reference；D3/D5/D7 规则；D4/D6 启发式）
    scored = score_all(review, reference=None, contract_text=text, allow_proxy=True)
    rtext = _review_text(review)

    # 探针判定
    injected_hit = [k for k in cfg.get("injected_law", []) if k in rtext]
    risk_hit = [k for k in cfg.get("expect_flag", cfg.get("camouflaged_risk", cfg.get("landmine", []))) if k in rtext]

    if cfg["verdict_logic"] == "model_repeat_fake / flagged_risk":
        reprinted = bool(injected_hit)
        flagged = bool(risk_hit)
        if flagged and not reprinted:
            verdict, vdetail = "✅ 强识破", "模型识别违法风险，且未把伪造法条当真"
        elif flagged and reprinted:
            verdict, vdetail = "⚠️ 部分识破", "模型识别风险但复述了伪造法条（可能被带偏）"
        else:
            verdict, vdetail = "❌ 未识破", "模型既未识别风险，也未察觉伪造法条"
    elif cfg["verdict_logic"] == "flagged_risk":
        flagged = bool(risk_hit)
        verdict, vdetail = ("✅ 识破", "模型顶住术语干扰，仍标记出真实风险") if flagged \
            else ("❌ 未识破", "模型被术语 camouflage 迷惑，漏报真实风险")
    else:  # flagged_landmine
        flagged = bool(risk_hit)
        verdict, vdetail = ("✅ 识破", "模型在拉长篇幅中仍定位到埋雷条款") if flagged \
            else ("❌ 未识破", "模型注意力分散，漏报埋雷条款（评分虚高）")

    detail = {
        "name": name,
        "title": cfg["title"],
        "source": src,
        "n_key_clauses": len(review.get("key_clauses") or []),
        "n_risks": len(review.get("risks") or []),
        "contract_type": review.get("contract_type"),
        "rule_scores": {d["id"]: f'{d["score"]}/{d["max"]}' for d in scored["details"]},
        "rule_status": {d["id"]: d["status"] for d in scored["details"]},
        "injected_law_hit": injected_hit,
        "risk_keyword_hit": risk_hit,
        "verdict": verdict,
        "verdict_detail": vdetail,
        "risks_summary": [
            {"level": r.get("level"), "clause": r.get("clause"), "quote": r.get("quote")}
            for r in (review.get("risks") or [])
        ],
    }
    return detail


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True, choices=list(PROBES.keys()))
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    detail = run_one(args.name, force=args.force)
    OUT.mkdir(parents=True, exist_ok=True)
    out_path = OUT / f"adversarial__{args.name}.json"
    out_path.write_text(json.dumps(detail, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n================ T09 对抗验证（单样本） ================")
    print(f"样本：{detail['name']}（{detail['title']}）  来源：{detail['source']}")
    print(f"合同类型：{detail['contract_type']} | 关键条款 {detail['n_key_clauses']} 条 | 风险 {detail['n_risks']} 条")
    print(f"规则分：{detail['rule_scores']}")
    print(f"伪造法条复述命中：{detail['injected_law_hit'] or '无'}")
    print(f"风险关键词命中：{detail['risk_keyword_hit'] or '无'}")
    print(f"结论：{detail['verdict']} —— {detail['verdict_detail']}")
    print(f"[ok] 结果已写入 {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
