"""T12 交互式演示服务 · 版本 demo_01（仅依赖标准库 + 项目既有依赖，无需额外安装）。

启动方式：
    python demo_01/server.py                 # 默认 http://127.0.0.1:8001
    python demo_01/server.py --port 9000    # 指定端口
    HY3_API_KEY=xxx python demo_01/server.py

说明：
    - 复用项目既有审阅链路 src.contract_review.review_with_client，保证与评测口径一致。
    - API 密钥来自环境变量 / .env（由服务端加载），绝不出现在前端，也不经浏览器转发。
    - 开放 CORS，因此即使直接用浏览器打开 index.html（file://）也能调用本服务。
    - 单次评测 1 次 hy3-preview 调用；max_tokens 默认 1800（可在环境变量 DEMO_MAX_TOKENS 调小以省 token）。
    - 本版本（demo_01）为「可自由输入合同文本、按用户输入实时评测」的交互式实现；原 demo/ 目录作为历史版本保留，不在其基础上直接修改。
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

HOST = os.environ.get("DEMO_HOST", "127.0.0.1")
PORT = int(os.environ.get("DEMO_PORT", "8001"))
MAX_TOKENS = int(os.environ.get("DEMO_MAX_TOKENS", "1800"))

HTML_PATH = os.path.join(ROOT, "demo_01", "index.html")


def build_client() -> Hy3Client:
    return Hy3Client(Hy3Config.from_env())


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
            self._send_json({"ok": True, "result": result.to_dict(), "source": result.source})
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
    print(f"[demo_01] 服务已启动： http://{args.host}:{args.port}/")
    print(f"[demo_01] 评测模型： {model} | 密钥： {key_state} | max_tokens： {MAX_TOKENS}")
    print("[demo_01] 按 Ctrl+C 停止。")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[demo_01] 已停止。")


if __name__ == "__main__":
    main()
