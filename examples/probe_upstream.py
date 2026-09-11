"""上游健康探测（零/极低成本诊断工具）。

用途：当评测报 502/429 时，用它区分「网关整体故障」「单个模型上游故障」「RPM 限流」。

用法：
    python examples/probe_upstream.py                 # 列模型 + 逐个最小连通测试
    python examples/probe_upstream.py --models tencent/hy3-preview,tencent/hy3
    python examples/probe_upstream.py --no-list       # 跳过 /v1/models，只测指定模型

设计要点：
- openai SDK 的 max_retries 设为 0，避免 SDK 内部重试掩盖真实错误、也避免重试风暴加剧 429；
- 每个模型只发 1 次最小请求（max_tokens=16），token 开销可忽略；
- 密钥只从环境变量/.env 读取，输出中绝不打印。
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

DEFAULT_MODELS = [
    "tencent/hy3-preview",
    "tencent/hy3",
    "z-ai/glm-5.3",
]


def list_models(api_key: str, base_url: str) -> list[str] | None:
    """用 openai SDK 拉 /v1/models（本机未单独安装 httpx，走 SDK 更稳）。"""
    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url=base_url, timeout=30, max_retries=0)
    try:
        data = client.models.list().data
    except Exception as e:  # noqa: BLE001
        print(f"[models] 请求失败: {type(e).__name__}: {str(e)[:200]}")
        return None
    ids = sorted(m.id for m in data if getattr(m, "id", None))
    print(f"[models] 共 {len(ids)} 个模型")
    kw = [i for i in ids if "hy3" in i or "hunyuan" in i or "hy-" in i]
    print(f"[models] hy3/hunyuan 相关({len(kw)}): {kw[:40]}")
    return ids


def probe(api_key: str, base_url: str, model: str, timeout: int) -> tuple[str, str]:
    """返回 (状态, 详情)。状态 ∈ ok / 502 / 429 / other。"""
    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout, max_retries=0)
    t0 = time.time()
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "说“OK”两个字。"}],
            max_tokens=16,
        )
        content = (resp.choices[0].message.content or "").strip()
        return "ok", f"{time.time() - t0:.1f}s 返回: {content[:40]!r}"
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        code = "other"
        if "502" in msg or "503" in msg or "upstream" in msg.lower():
            code = "502"
        elif "429" in msg or "rate_limit" in msg.lower():
            code = "429"
        elif "404" in msg:
            code = "404"
        elif "402" in msg:
            code = "402"
        return code, f"{type(e).__name__}: {msg[:180]}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="", help="逗号分隔的模型列表，默认探测 hy3 系列与裁判模型")
    ap.add_argument("--no-list", action="store_true", help="不调用 /v1/models")
    ap.add_argument("--timeout", type=int, default=45)
    args = ap.parse_args()

    api_key = os.getenv("HY3_API_KEY", "")
    base_url = os.getenv("HY3_BASE_URL", "https://api.qnaigc.com/v1")
    print(f"[config] base_url={base_url} api_key_set={bool(api_key) and api_key != 'EMPTY'}")

    if not args.no_list:
        list_models(api_key, base_url)
        print()

    models = [m.strip() for m in args.models.split(",") if m.strip()] or DEFAULT_MODELS
    results = {}
    for m in models:
        code, detail = probe(api_key, base_url, m, args.timeout)
        results[m] = code
        print(f"[probe] {m:28} -> {code:6} | {detail}")
        time.sleep(1.0)  # 避免探测自身触发 RPM

    print("\n[诊断]")
    if all(v == "502" for v in results.values()):
        print("  所有模型 502 → 网关/上游整体不可用，等待恢复或联系服务商。")
    elif results.get("tencent/hy3-preview") == "502" and "ok" in results.values():
        print("  仅 hy3-preview 502，其他模型可用 → 单模型上游故障；可临时切换 HY3_MODEL 到可用模型。")
    if any(v == "429" for v in results.values()):
        print("  出现 429 → RPM 已达上限；请降低并发、加大调用间隔，稍后重试。")
    if any(v == "402" for v in results.values()):
        print("  出现 402 → 额度耗尽/未开启按量计费，需充值或换 key。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
