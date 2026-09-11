"""T12 交互式演示服务 · 版本 demo_02（仅依赖标准库 + 项目既有依赖，无需额外安装）。

启动方式：
    python demo_02/server.py                 # 默认 http://127.0.0.1:8002
    python demo_02/server.py --port 9000    # 指定端口
    HY3_API_KEY=xxx python demo_02/server.py

说明：
    - 复用项目既有审阅链路 src.contract_review.review_with_client，保证与评测口径一致。
    - API 密钥来自环境变量 / .env（由服务端加载），绝不出现在前端，也不经浏览器转发。
    - 开放 CORS，因此即使直接用浏览器打开 index.html（file://）也能调用本服务。
    - 单次评测 1 次 hy3-preview 调用；max_tokens 默认 1800（可在环境变量 DEMO_MAX_TOKENS 调小以省 token）。
    - 本版本（demo_02）相对 demo_01 的改动：输出板块改为「风险标注 + 法条依据 + 修改建议」三段式；
      ③ 评估示例 板块改为「动态」——综合分与 D1–D7 由 7 维 rubric 对本次审阅结果实时算得（服务端 demo_score_review），
      仅在用户点「开始评测」后出现，初始页面只显示①输入。
      输入板块保持 demo_01 的交互式实现不变。原 demo/、demo_01/ 作为历史版本保留。
"""
from __future__ import annotations

import argparse
import json
import os
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

# 7 维 rubric 自评（demo 用：对任意用户输入，无金标准参考，采用 rubric 规则 + 代理）
sys.path.insert(0, os.path.join(ROOT, "eval"))
from rubric import (  # noqa: E402
    score_D3, score_D5, score_D6, score_D7,
    _SUSPICIOUS_LAW, _text_of,
)

HOST = os.environ.get("DEMO_HOST", "127.0.0.1")
PORT = int(os.environ.get("DEMO_PORT", "8002"))
MAX_TOKENS = int(os.environ.get("DEMO_MAX_TOKENS", "1800"))

HTML_PATH = os.path.join(ROOT, "demo_02", "index.html")


def build_client() -> Hy3Client:
    return Hy3Client(Hy3Config.from_env())


# ----------------- 7 维 rubric 自评（demo：对任意用户输入，无金标准参考） -----------------
def _demo_score_D1(review: dict) -> dict:
    """条款抽取准确性：reference-free 数量代理（无金标准，演示用）。"""
    n = len(review.get("key_clauses") or [])
    if n >= 4:
        s, rat = 3, f"抽取关键条款 {n} 条（覆盖充分）"
    elif n >= 3:
        s, rat = 2, f"抽取关键条款 {n} 条（基本覆盖）"
    elif n == 1:
        s, rat = 1, "仅抽取 1 条关键条款"
    else:
        s, rat = 0, "未抽取到关键条款"
    return {"id": "D1", "name": "条款抽取准确性", "score": s, "max": 3,
            "status": "scored(proxy)", "rationale": rat}


def _demo_score_D2(review: dict) -> dict:
    """风险识别正确性：reference-free 数量代理（无金标准，演示用）。"""
    n = len(review.get("risks") or [])
    if n >= 3:
        s, rat = 3, f"识别风险 {n} 项（识别充分）"
    elif n == 2:
        s, rat = 2, f"识别风险 {n} 项"
    elif n == 1:
        s, rat = 1, "仅识别 1 项风险"
    else:
        s, rat = 0, "未识别到风险"
    return {"id": "D2", "name": "风险识别正确性", "score": s, "max": 3,
            "status": "scored(proxy)", "rationale": rat}


def _demo_score_D4(review: dict) -> dict:
    """法律依据正确性：启发式代理（演示不接入 LLM-judge）。"""
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


def demo_score_review(review: dict, contract_text: str) -> dict:
    """对本次审阅结果做 7 维 rubric 自评（D3/D5/D6/D7 用 rubric 精确规则；D1/D2/D4 用代理）。"""
    d1 = _demo_score_D1(review)
    d2 = _demo_score_D2(review)
    d3 = score_D3(review, contract_text).as_dict()
    d4 = _demo_score_D4(review)
    d5 = score_D5(review).as_dict()
    d6 = score_D6(review, allow_proxy=True).as_dict()
    d7 = score_D7(review).as_dict()
    details = [d1, d2, d3, d4, d5, d6, d7]
    total = sum(d["score"] for d in details)
    maxv = sum(d["max"] for d in details)
    overall = round(total / maxv * 100, 1) if maxv else 0.0
    return {"overall_pct": f"{overall}%", "scored_count": len(details),
            "pending": [], "details": details}


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
            self._send_json({"ok": True, "configured": bool(os.environ.get("HY3_API_KEY"))})
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
            evaluation = demo_score_review(result.to_dict(), text)
            self._send_json({"ok": True, "result": result.to_dict(),
                             "source": result.source, "evaluation": evaluation})
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
    print(f"[demo_02] 服务已启动： http://{args.host}:{args.port}/")
    print(f"[demo_02] 评测模型： {model} | 密钥： {key_state} | max_tokens： {MAX_TOKENS}")
    print("[demo_02] 按 Ctrl+C 停止。")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[demo_02] 已停止。")


if __name__ == "__main__":
    main()
