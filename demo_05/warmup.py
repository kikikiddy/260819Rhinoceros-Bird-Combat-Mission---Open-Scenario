"""演示预热脚本：把合同库内所有示例合同的审阅结果预先跑出来，写入 demo_05/.cache。

录屏前先跑一次，正式演示时点击任意示例都能即时出结果，且不会重复消耗 token。

用法：
    python demo_05/warmup.py                 # 预热全部示例（缺哪个跑哪个）
    python demo_05/warmup.py --force          # 忽略已有缓存，全部重跑
    python demo_05/warmup.py --only sample_labor_contract,sample_lease_contract
"""

from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import server as demo  # noqa: E402  （复用同一套审阅链路与缓存路径）


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="忽略已有缓存，全部重跑")
    ap.add_argument("--only", default="", help="逗号分隔的样本 id 白名单")
    args = ap.parse_args()

    only = [s.strip() for s in args.only.split(",") if s.strip()]
    client = None
    done = 0
    for item in demo.CONTRACT_DB:
        if only and item["id"] not in only:
            continue
        if not args.force and demo.cache_get(item["text"]) is not None:
            print(f"[skip] {item['id']} 已有缓存")
            continue
        if client is None:
            client = demo.build_client()
        t0 = time.time()
        try:
            r = demo.review_with_client(item["text"], client, max_tokens=demo.MAX_TOKENS)
        except Exception as exc:  # noqa: BLE001
            print(f"[fail] {item['id']}: {type(exc).__name__}: {str(exc)[:160]}")
            continue
        if r.source == "live":
            demo.cache_put(item["text"], r.to_dict())
        done += 1
        print(f"[ok] {item['id']} {time.time() - t0:.1f}s "
              f"type={r.contract_type} 条款={len(r.key_clauses)} 风险={len(r.risks)}")
    print(f"\n[done] 新增/更新 {done} 份缓存 → {demo.CACHE_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
