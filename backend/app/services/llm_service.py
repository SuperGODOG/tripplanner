"""LLM 服务"""
import time
import random
from hello_agents import HelloAgentsLLM
from ..config import get_settings

_llm: HelloAgentsLLM | None = None


def retry_with_backoff(fn, max_retries=3, base_delay=1):
    """指数退避重试：LLM API 临时故障自动重试。

    重试间隔: base_delay * 2^i + random(0, 0.5) 秒。
    例如 base_delay=1: 1s → 2s → 4s（均加抖动）。
    """
    for i in range(max_retries):
        try:
            return fn()
        except Exception as e:
            if i == max_retries - 1:
                raise
            delay = base_delay * (2 ** i) + random.uniform(0, 0.5)
            print(f"⚠️  LLM 调用失败 (尝试 {i + 1}/{max_retries}): {e}，{delay:.1f}s 后重试...")
            time.sleep(delay)


def get_llm() -> HelloAgentsLLM:
    """获取 LLM 实例（单例模式）

    与 HelloAgents 框架交互的唯一入口。
    所有 Agent 共用同一个 LLM 实例。
    """
    global _llm

    if _llm is None:
        settings = get_settings()
        _llm = HelloAgentsLLM(
            api_key=settings.llm_api_key,
            model=settings.llm_model_id,
            base_url=settings.llm_base_url,
        )

    return _llm
