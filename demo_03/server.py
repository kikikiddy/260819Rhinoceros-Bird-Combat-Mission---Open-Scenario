"""T12 交互式演示服务 · 版本 demo_03（仅依赖标准库 + 项目既有依赖，无需额外安装）。

启动方式：
    python demo_03/server.py                 # 默认 http://127.0.0.1:8003
    python demo_03/server.py --port 9000    # 指定端口
    HY3_API_KEY=xxx python demo_03/server.py

说明：
    - 复用项目既有审阅链路 src.contract_review.review_with_client，保证与评测口径一致。
    - API 密钥来自环境变量 / .env（由服务端加载），绝不出现在前端，也不经浏览器转发。
    - 开放 CORS，因此即使直接用浏览器打开 index.html（file://）也能调用本服务。
    - 单次评测 1 次 hy3-preview 调用；max_tokens 默认 1800（可在环境变量 DEMO_MAX_TOKENS 调小以省 token）。

本版本（demo_03）相对 demo_02 的改动（按用户"第三版"要求，新建版本、保留 demo_02 作历史）：
    ① 输入板块「加载示例合同」改为**从合同库随机抽一份**（库 = 项目 samples/*.md + 对应 references/*.reference.json），
       每次点击出现不同合同，不再固定同一份。
    ② 评估示例的综合分与 D1–D7 改为**真实客观评分**：
       - 当输入文本命中库内某样本时，用该样本的金标准 reference 走真 rubric score_D1/D2（召回 + 误报扣分），
         D3/D5/D7 规则校验、D4 法条启发式；过度识别会被扣 D2，故常见样本如 labor_contract 会打出客观分（≈T10 的 88.2%）而非满分。
       - 自由粘贴无参考文本时，D1/D2 明确标"未评"且不计入综合分（不再白送满分）。
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import random
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# 加载 .env（若存在），密钥仅服务端使用
try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(ROOT, ".env"))
except Exception:  # pragma: no cover - 无 dotenv 时回退到环境变量
    pass

from src.contract_review import review_with_client  # noqa: E402
from src.hy3 import Hy3Client, Hy3Config  # noqa: E402

# 7 维 rubric 自评（demo 用）：D1/D2 走金标准参考（若有），D3/D5/D7 走精确规则，D4 走启发式
sys.path.insert(0, os.path.join(ROOT, "eval"))
from rubric import (  # noqa: E402
    score_D1, score_D2, score_D3, score_D5, score_D6, score_D7,
    _SUSPICIOUS_LAW, _text_of,
)

HOST = os.environ.get("DEMO_HOST", "127.0.0.1")
PORT = int(os.environ.get("DEMO_PORT", "8003"))
MAX_TOKENS = int(os.environ.get("DEMO_MAX_TOKENS", "1800"))

HTML_PATH = os.path.join(ROOT, "demo_03", "index.html")


def build_client() -> Hy3Client:
    return Hy3Client(Hy3Config.from_env())


# ----------------- 合同库（项目 samples + references） -----------------
def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "").strip()


def load_db() -> list[dict]:
    """启动时扫描 samples/*.md，配对同名的 references/*.reference.json。"""
    db: list[dict] = []
    sd = os.path.join(ROOT, "samples")
    for md in sorted(glob.glob(os.path.join(sd, "*.md"))):
        base = os.path.splitext(os.path.basename(md))[0]
        if base.upper() == "MANIFEST":
            continue
        ref_path = os.path.join(sd, "references", base + ".reference.json")
        ref = None
        if os.path.exists(ref_path):
            try:
                ref = json.loads(open(ref_path, encoding="utf-8").read())
            except Exception:
                ref = None
        try:
            text = open(md, encoding="utf-8").read()
        except Exception:
            continue
        db.append({
            "id": base,
            "name": base.replace("sample_", "").replace("_", " "),
            "text": text,
            "reference": ref,
        })
    return db


CONTRACT_DB = load_db()


# ----------------- 7 维 rubric 自评 -----------------
def _demo_score_D4(review: dict) -> dict:
    """法律依据正确性：启发式代理（演示不接入 LLM-judge）。

    检测到 3 位/999/888/666 等可疑法条编号 → 红标 0 分；否则按"风险是否都附法条依据"评分。
    """
    txt = _text_of(review)
    bad = _SUSPICIOUS_LAW.findall(txt)
    if bad:
        return {"id": "D4", "name": "法律依据正确性", "score": 0, "max": 3,
                "status": "scored(heuristic)", "rationale": f"启发式检测到可疑法条编号：第{bad[0]}条（疑伪造）"}
    risks = review.get("risks") or []
    if not risks:
        return {"id": "D4", "name": "法律依据正确性", "score": 3, "max": 3,
                "status": "scored(heuristic)", "rationale": "无风险结论，无需引用法条"}
    ok = sum(1 for r in risks if (r.get("risk") or "").strip())
    rate = ok / len(risks)
    if rate >= 0.9:
        s, rat = 3, f"{ok}/{len(risks)} 条风险附法条依据"
    elif rate >= 0.5:
        s, rat = 2, f"{ok}/{len(risks)} 条风险附法条依据"
    else:
        s, rat = 1, f"仅 {ok}/{len(risks)} 条风险附法条依据"
    return {"id": "D4", "name": "法律依据正确性", "score": s, "max": 3,
            "status": "scored(heuristic)", "rationale": rat}


def demo_score_review(review: dict, contract_text: str, reference: dict | None = None) -> dict:
    """对本次审阅结果做 7 维 rubric 自评。

    reference 不为 None（输入命中库内样本）→ 客观评分：D1/D2 对照金标准算召回与误报扣分，
    D3/D5/D7 规则校验，D4 启发式；综合分基于全部 7 维（mode=reference）。
    reference 为 None（自由输入）→ D1/D2 无金标准无法客观评，标记 needs_reference 不计入综合分，
    综合分仅基于 D3/D4/D5/D6/D7（mode=free），避免白送满分。
    """
    d3 = score_D3(review, contract_text).as_dict()
    d4 = _demo_score_D4(review)
    d5 = score_D5(review).as_dict()
    d6 = score_D6(review, allow_proxy=True).as_dict()
    d7 = score_D7(review).as_dict()

    if reference is not None:
        d1 = score_D1(review, reference).as_dict()
        exp_risks = reference.get("expected_risks") or []
        if exp_risks:
            d2 = score_D2(review, reference).as_dict()
        else:
            # 负例 / clean 合同：期望无风险，模型识别到风险即过度识别
            n = len(review.get("risks") or [])
            if n == 0:
                s, rat = 3, "无风险结论，与期望（clean）一致"
            elif n == 1:
                s, rat = 2, "识别 1 项风险（期望为 0，疑似误报）"
            elif n == 2:
                s, rat = 1, f"识别 {n} 项风险（期望为 0，过度识别）"
            else:
                s, rat = 0, f"识别 {n} 项风险（期望为 0，严重过度识别）"
            d2 = {"id": "D2", "name": "风险识别正确性", "score": s, "max": 3,
                   "status": "scored(proxy)", "rationale": rat}
        details = [d1, d2, d3, d4, d5, d6, d7]
        mode = "reference"
    else:
        d1 = {"id": "D1", "name": "条款抽取准确性", "score": 0, "max": 3,
               "status": "needs_reference", "rationale": "自由输入无金标准参考，D1 不计入综合分"}
        d2 = {"id": "D2", "name": "风险识别正确性", "score": 0, "max": 3,
               "status": "needs_reference", "rationale": "自由输入无金标准参考，D2 不计入综合分"}
        details = [d1, d2, d3, d4, d5, d6, d7]
        mode = "free"

    scored = [d for d in details if d["status"].startswith("scored")]
    total = sum(d["score"] for d in scored)
    maxv = sum(d["max"] for d in scored)
    overall = round(total / maxv * 100, 1) if maxv else 0.0
    return {
        "overall_pct": f"{overall}%",
        "scored_count": len(scored),
        "mode": mode,
        "pending": [d["id"] for d in details if not d["status"].startswith("scored")],
        "details": details,
    }


class Handler(BaseHTTPRequestHandler):
    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send_json(self, obj: dict, status: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._cors()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._serve_html()
        elif path == "/health":
            self._send_json({"ok": True, "configured": bool(os.environ.get("HY3_API_KEY")),
                             "db_size": len(CONTRACT_DB)})
        elif path == "/api/sample":
            self._send_sample()
        else:
            self._send_json({"ok": False, "error": "not found"}, status=404)

    def _serve_html(self) -> None:
        try:
            data = open(HTML_PATH, "rb").read()
        except OSError:
            self._send_json({"ok": False, "error": "demo html 未找到"}, status=500)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self._cors()
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_sample(self) -> None:
        if not CONTRACT_DB:
            self._send_json({"ok": False, "error": "无可用示例合同"}, status=404)
            return
        item = random.choice(CONTRACT_DB)  # 每次随机抽一份
        self._send_json({"ok": True, "id": item["id"], "name": item["name"], "text": item["text"]})

    def do_POST(self):
        path = urlparse(self.path).path
        if path != "/api/review":
            self._send_json({"ok": False, "error": "not found"}, status=404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
            raw = self.rfile.read(length) if length else b"{}"
            payload = json.loads(raw.decode("utf-8") or "{}")
            text = (payload.get("text") or "").strip()
            if not text:
                self._send_json({"ok": False, "error": "缺少合同文本 text"}, status=400)
                return

            client = build_client()
            result = review_with_client(text, client, max_tokens=MAX_TOKENS)

            # 文本与库内样本完全一致时，用其金标准 reference 做客观评分；否则自由输入模式
            reference = None
            matched_id = None
            norm = _norm(text)
            for it in CONTRACT_DB:
                if _norm(it["text"]) == norm:
                    reference = it["reference"]
                    matched_id = it["id"]
                    break
            evaluation = demo_score_review(result.to_dict(), text, reference)
            self._send_json({"ok": True, "result": result.to_dict(),
                             "source": result.source, "evaluation": evaluation,
                             "matched_sample": matched_id})
        except Exception as exc:  # noqa: BLE001 - 统一以 JSON 返回，便于前端展示
            self._send_json({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, status=200)

    def log_message(self, *args):  # 静默访问日志
        pass


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=HOST)
    ap.add_argument("--port", type=int, default=PORT)
    args = ap.parse_args()

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    model = os.environ.get("HY3_MODEL", "tencent/hy3-preview")
    key_state = "已配置" if os.environ.get("HY3_API_KEY") else "未配置（请在 .env 或环境变量中设置 HY3_API_KEY）"
    print(f"[demo_03] 服务已启动： http://{args.host}:{args.port}/")
    print(f"[demo_03] 合同库样本数： {len(CONTRACT_DB)} | 评测模型： {model}")
    print(f"[demo_03] 密钥： {key_state} | max_tokens： {MAX_TOKENS}")
    print("[demo_03] 按 Ctrl+C 停止。")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[demo_03] 已停止。")


if __name__ == "__main__":
    main()
