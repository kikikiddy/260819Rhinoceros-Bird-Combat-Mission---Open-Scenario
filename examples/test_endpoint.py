"""端点连通性测试（配真实 Hy3 前先用它验证）。

用法：
    # 1) 把真实值写入 .env（不要提交）
    # 2) 运行
    python examples/test_endpoint.py

它会：
    - 打印脱敏后的配置（不泄露密钥）
    - 发起一次最小 chat 调用，确认端点可达 + 模型名有效
    - 若失败，明确区分：连接错误 / 402 额度 / 400 模型名 / 其他
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.hy3 import Hy3Client, Hy3Config, configure_logging  # noqa: E402

configure_logging()


def main() -> int:
    cfg = Hy3Config.from_env()
    summary = cfg.safe_summary()
    print("[config] (密钥已脱敏)")
    for k, v in summary.items():
        print(f"  {k}: {v}")

    if not summary["api_key_set"] and cfg.base_url.startswith("http://127.0.0.1"):
        print("\n[warn] 仍是默认值（本地 EMPTY + 127.0.0.1），请确认 .env 已填写真实 TokenHub 值。")
        return 2

    client = Hy3Client(cfg)
    print(f"\n[test] 向 {cfg.base_url} 发起最小调用 (model={cfg.model}) ...")
    try:
        out = client.chat(
            [{"role": "user", "content": "请用一句话自我介绍。"}],
            reasoning_effort="no_think",
            max_tokens=64,
        )
        print("[ok] 端点连通成功！模型返回：")
        print("  ", out[:200].replace("\n", " "))
        print("\n=> 现在可运行：python examples/eval_samples.py --all --review-source live")
        return 0
    except Exception as e:  # noqa: BLE001
        cls = type(e).__name__
        msg = str(e)
        print(f"[fail] {cls}: {msg[:300]}")
        if "402" in msg:
            print("  诊断：402 = 免费额度耗尽且未开启按量计费。请到云控制台开启按量计费后重试。")
        elif "400" in msg or "model" in msg.lower():
            print("  诊断：400 = 模型名无效。请把控制台里确切的模型 ID 填进 HY3_MODEL（官方自部署是 hy3，TokenHub 可能不同）。")
        elif "Connection" in cls or "Connect" in msg:
            print("  诊断：连接失败。请检查 HY3_BASE_URL 是否正确、网络/代理是否可达。")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
