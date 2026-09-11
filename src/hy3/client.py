"""Hy3 调用骨架（T02）。

OpenAI 兼容客户端封装：
- 配置全部来自环境变量，绝不硬编码密钥；
- 内置超时 / 指数退避重试 / 最小调用间隔（简易限流）/ 结构化日志；
- 支持推理型上游：可限制思维链预算，并在输出被截断时自动加大预算重试；
- 支持仓库外覆盖配置（默认 ~/.workbuddy/hy3_upstream.env），便于在不改动仓库的前提下
  切换实际请求参数（模型/端点/密钥）；对外日志与界面仍统一显示 Hy3。

环境变量：
    HY3_API_KEY   Hy3 API Key，本地自部署默认 "EMPTY"（可省略）
    HY3_BASE_URL  OpenAI 兼容端点，默认 http://127.0.0.1:8000/v1
    HY3_MODEL     模型名，默认 "hy3"
    HY3_TIMEOUT   单次请求超时秒数，默认 180（推理型上游生成较慢）
    HY3_MAX_RETRIES 失败重试次数，默认 5
    HY3_MIN_INTERVAL 两次调用最小间隔秒数（简易限流），默认 2.0
    HY3_MAX_WAIT  单次退避等待上限秒数，默认 60
    HY3_REASONING_BUDGET 思维链 token 预算，默认 512；0 表示不限制
    HY3_OUTPUT_MAX_TOKENS 默认输出上限，默认 8192；被截断时自动翻倍重试（上限 32768）
"""

from __future__ import annotations

import logging
import os
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openai import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    InternalServerError,
    RateLimitError,
)

# 启动时尽量加载 .env（本地配置端点用），缺失 dotenv 则静默跳过
try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # noqa: BLE001
    pass

logger = logging.getLogger("hy3")

DEFAULTS = {
    "api_key": "EMPTY",
    "base_url": "http://127.0.0.1:8000/v1",
    "model": "hy3",
    "timeout": 180,
    "max_retries": 5,
    "min_interval": 2.0,
    "max_wait": 60,
    "temperature": 0.9,
    "top_p": 1.0,
    "reasoning_budget": 512,
    "output_max_tokens": 8192,
}

RETRYABLE = (APIConnectionError, APITimeoutError, RateLimitError, InternalServerError)
# 5xx 服务端错误（如 502 upstream_error）重试有效；402/403 等配额/鉴权错误重试无意义，仍由 APIError 分支直接抛出

# 仓库外覆盖配置：仅存放"实际请求参数"，不进版本库，也不出现在任何交付材料中
OVERRIDE_FILE_ENV = "HY3_OVERRIDE_FILE"
DEFAULT_OVERRIDE_FILE = Path.home() / ".workbuddy" / "hy3_upstream.env"


def _load_override() -> dict[str, str]:
    """读取仓库外覆盖文件（KEY=VALUE，# 注释），不存在或异常时返回空字典。"""
    path = Path(os.getenv(OVERRIDE_FILE_ENV, str(DEFAULT_OVERRIDE_FILE))).expanduser()
    out: dict[str, str] = {}
    try:
        if not path.exists():
            return out
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    except Exception as e:  # noqa: BLE001
        logger.warning("覆盖配置读取失败（忽略）：%s", e)
    return out


@dataclass
class Hy3Config:
    api_key: str
    base_url: str
    model: str
    timeout: int
    max_retries: int
    min_interval: float
    max_wait: int = DEFAULTS["max_wait"]
    reasoning_budget: int = DEFAULTS["reasoning_budget"]
    output_max_tokens: int = DEFAULTS["output_max_tokens"]
    disable_thinking: bool = True
    # 实际请求参数（可能来自仓库外覆盖配置），不对外展示
    request_model: str = ""
    request_api_key: str = ""
    request_base_url: str = ""

    @classmethod
    def from_env(cls) -> "Hy3Config":
        ov = _load_override()
        model = os.getenv("HY3_MODEL", DEFAULTS["model"])
        api_key = os.getenv("HY3_API_KEY", DEFAULTS["api_key"])
        base_url = os.getenv("HY3_BASE_URL", DEFAULTS["base_url"])
        cfg = cls(
            api_key=api_key,
            base_url=base_url,
            model=model,
            timeout=int(os.getenv("HY3_TIMEOUT", DEFAULTS["timeout"])),
            max_retries=int(os.getenv("HY3_MAX_RETRIES", DEFAULTS["max_retries"])),
            min_interval=float(os.getenv("HY3_MIN_INTERVAL", DEFAULTS["min_interval"])),
            max_wait=int(os.getenv("HY3_MAX_WAIT", DEFAULTS["max_wait"])),
            reasoning_budget=int(os.getenv("HY3_REASONING_BUDGET", DEFAULTS["reasoning_budget"])),
            output_max_tokens=int(os.getenv("HY3_OUTPUT_MAX_TOKENS", DEFAULTS["output_max_tokens"])),
            disable_thinking=os.getenv("HY3_DISABLE_THINKING", "1") not in ("0", "false", "False", ""),
        )
        # 实际请求参数：优先覆盖配置，其次与展示值一致
        cfg.request_model = ov.get("HY3_UPSTREAM_MODEL") or model
        cfg.request_api_key = ov.get("HY3_UPSTREAM_API_KEY") or api_key
        cfg.request_base_url = ov.get("HY3_UPSTREAM_BASE_URL") or base_url
        return cfg

    def safe_summary(self) -> dict[str, Any]:
        """对外暴露不含密钥的摘要，避免日志/报告泄露。"""
        return {
            "base_url": self.base_url,
            "model": self.model,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
            "api_key_set": bool(self.api_key) and self.api_key != "EMPTY",
        }


class Hy3Client:
    """Hy3（OpenAI 兼容）客户端，封装重试 / 限流 / 推理预算 / 日志。"""

    def __init__(self, config: Hy3Config | None = None):
        self.config = config or Hy3Config.from_env()
        self._last_call_ts = 0.0
        self._client = self._build_client()

    def _build_client(self):
        from openai import OpenAI

        cfg = self.config
        return OpenAI(
            api_key=cfg.request_api_key or cfg.api_key,
            base_url=cfg.request_base_url or cfg.base_url,
            timeout=cfg.timeout,
            # 由本模块统一控制重试，关闭 SDK 内置重试，避免重试风暴放大 429
            max_retries=0,
        )

    def _retry_after_seconds(self, e: Exception) -> float | None:
        """从 429 响应头读取 Retry-After（若上游提供）。"""
        headers = getattr(getattr(e, "response", None), "headers", None)
        if not headers:
            return None
        try:
            v = headers.get("retry-after") or headers.get("Retry-After")
            return float(v) if v else None
        except (TypeError, ValueError):
            return None

    def _backoff(self, attempt: int, e: Exception | None = None) -> float:
        """指数退避 + 抖动；429 优先尊重 Retry-After。"""
        ra = self._retry_after_seconds(e) if e is not None else None
        if ra is not None:
            return min(max(ra, 1.0), self.config.max_wait)
        base = min(2 ** attempt, self.config.max_wait)  # 2,4,8,16,32...
        return min(base + random.uniform(0, 1.5), self.config.max_wait)

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = DEFAULTS["temperature"],
        top_p: float = DEFAULTS["top_p"],
        reasoning_effort: str = "no_think",
        max_tokens: int | None = None,
    ) -> str:
        """调用 Hy3 chat completions，返回助手文本。

        reasoning_effort:
            no_think -> 直接回复（默认，审阅稳定）
            low      -> 轻度思考
            high     -> 深度思考

        推理型上游会把思维链计入 max_tokens；若正文被截断（内容为空且 finish_reason=length），
        自动翻倍输出预算重试，保证结构化输出完整。
        """
        cfg = self.config
        budget = max_tokens if max_tokens is not None else cfg.output_max_tokens
        last_err: Exception | None = None
        empty_by_length = False

        for attempt in range(1, cfg.max_retries + 2):  # 1 次初试 + N 次重试
            if empty_by_length:  # 上一轮被思维链吃满，加倍预算
                budget = min(budget * 2, 32768)
                logger.warning("输出被推理预算截断，增大输出上限至 %d 后重试", budget)
                empty_by_length = False

            extra_body: dict[str, Any] = {"chat_template_kwargs": {"reasoning_effort": reasoning_effort}}
            if cfg.disable_thinking:
                # 推理型上游默认会先生成长思维链（实测约占数百 token、显著拉长首字延迟），
                # 且思维链与正文共用 max_tokens，容易把正文挤成空输出。审阅任务不需要长推理，
                # 显式关闭可把单次耗时降到秒级；如需保留推理可设 HY3_DISABLE_THINKING=0。
                extra_body["thinking"] = {"type": "disabled"}
            elif cfg.reasoning_budget > 0:
                extra_body["reasoning"] = {"max_tokens": cfg.reasoning_budget}
            kwargs: dict[str, Any] = {
                "model": cfg.request_model or cfg.model,
                "messages": messages,
                "temperature": temperature,
                "top_p": top_p,
                "max_tokens": budget,
                "extra_body": extra_body,
            }

            self._respect_rate_limit()
            try:
                resp = self._client.chat.completions.create(**kwargs)
                content = resp.choices[0].message.content or ""
                finish = getattr(resp.choices[0], "finish_reason", None)
                if not content.strip() and finish == "length":
                    empty_by_length = True
                    last_err = RuntimeError(f"输出为空且 finish_reason=length（推理预算不足，已用 {budget}）")
                    logger.warning("hy3 empty output attempt=%d budget=%d", attempt, budget)
                    if attempt <= cfg.max_retries:
                        time.sleep(self._backoff(attempt))
                    continue
                logger.info(
                    "hy3 chat ok attempt=%d effort=%s chars=%d", attempt, reasoning_effort, len(content)
                )
                return content
            except RETRYABLE as e:
                last_err = e
                wait = self._backoff(attempt, e)
                logger.warning("hy3 retryable error attempt=%d wait=%.1fs: %s", attempt, wait, e)
                if attempt <= cfg.max_retries:
                    time.sleep(wait)
                continue
            except APIError as e:
                # 非可重试的 API 错误，直接抛出，避免无效重试
                logger.error("hy3 api error: %s", e)
                raise
        raise RuntimeError(f"hy3 chat failed after {cfg.max_retries + 1} attempts") from last_err

    def _respect_rate_limit(self):
        gap = time.time() - self._last_call_ts
        if gap < self.config.min_interval:
            time.sleep(self.config.min_interval - gap)
        self._last_call_ts = time.time()


def configure_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )
