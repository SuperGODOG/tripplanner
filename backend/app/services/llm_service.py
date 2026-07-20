"""LLM 服务"""
from hello_agents import HelloAgentsLLM
from ..config import get_settings

_llm: HelloAgentsLLM | None = None


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
