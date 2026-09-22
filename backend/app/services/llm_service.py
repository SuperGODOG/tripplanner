"""LLM 服务与多协议适配层 (LLM Protocol Adapter)

支持:
1. OpenAI 兼容协议 (Chat Completions)
2. Anthropic A社协议 (/v1/messages, 支持火山方舟 Coding Plan 与 GLM-5.3-Flash)
   - x-api-key 头鉴权
   - system 参数顶层剥离与注入
   - thinking 思考块与 text 文本块智能解析
"""
from __future__ import annotations

import json
import logging
import random
import time
import urllib.error
import urllib.request
from typing import Any, Iterator

from hello_agents import HelloAgentsLLM
from ..config import get_settings

logger = logging.getLogger(__name__)

_llm: Any | None = None


def retry_with_backoff(fn, max_retries=3, base_delay=1):
    """指数退避重试：LLM API 临时故障自动重试。"""
    for i in range(max_retries):
        try:
            return fn()
        except Exception as e:
            if i == max_retries - 1:
                raise
            delay = base_delay * (2 ** i) + random.uniform(0, 0.5)
            logger.warning("⚠️ LLM 调用失败 (尝试 %d/%d): %s，%.1fs 后重试...", i + 1, max_retries, e, delay)
            time.sleep(delay)


class AnthropicCompatibleLLM:
    """兼容 Anthropic Messages 协议的 LLM 客户端

    原生支持火山方舟 /api/plan 节点与 GLM-5.3-Flash。
    提供与 HelloAgentsLLM 完全一致的 .invoke(messages) 接口。
    """

    def __init__(
        self,
        api_key: str,
        model: str = "glm-5.3-flash",
        base_url: str = "https://ark.cn-beijing.volces.com/api/plan",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        timeout: int = 60,
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout

        # 归一化 endpoint 路径
        if self.base_url.endswith("/v1/messages") or self.base_url.endswith("/messages"):
            self.endpoint_url = self.base_url
        else:
            self.endpoint_url = f"{self.base_url}/v1/messages"

    def invoke(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        """非流式调用，返回清洗后的模型正文响应"""
        system_prompts: list[str] = []
        clean_messages: list[dict[str, str]] = []

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                system_prompts.append(content)
            else:
                # Anthropic 仅接受 user 与 assistant 角色
                clean_role = "assistant" if role == "assistant" else "user"
                clean_messages.append({"role": clean_role, "content": content})

        if not clean_messages:
            clean_messages = [{"role": "user", "content": "请开始"}]

        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            "messages": clean_messages,
        }
        if system_prompts:
            payload["system"] = "\n\n".join(system_prompts)
        if self.temperature is not None:
            payload["temperature"] = kwargs.get("temperature", self.temperature)

        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        }

        req_data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.endpoint_url,
            data=req_data,
            headers=headers,
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                resp_bytes = response.read()
                data = json.loads(resp_bytes.decode("utf-8"))
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", errors="ignore")
            logger.error("Anthropic API 调用失败 [%d]: %s", e.code, error_body)
            raise RuntimeError(f"Anthropic API 请求错误 [{e.code}]: {error_body}") from e
        except Exception as e:
            logger.error("Anthropic API 连接异常: %s", e)
            raise

        # 解析 content 列表（过滤 thinking，只提取 text）
        content_items = data.get("content", [])
        text_chunks: list[str] = []
        for item in content_items:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    text_chunks.append(item.get("text", ""))
            elif isinstance(item, str):
                text_chunks.append(item)

        final_text = "".join(text_chunks).strip()
        if not final_text and content_items:
            # 容错提取
            logger.warning("未能通过 text 块解析到内容，尝试提取原始文本: %s", content_items)
            final_text = str(content_items)

        return final_text

    def stream_invoke(self, messages: list[dict[str, str]], **kwargs: Any) -> Iterator[str]:
        """流式调用（当前包装为块式输出）"""
        result = self.invoke(messages, **kwargs)
        yield result

    def think(self, messages: list[dict[str, str]], **kwargs: Any) -> Iterator[str]:
        """思考流式调用接口"""
        return self.stream_invoke(messages, **kwargs)


def get_llm() -> Any:
    """获取全局 LLM 客户端单例（自动按配置协议路由）"""
    global _llm
    if _llm is None:
        settings = get_settings()
        is_anthropic = (
            settings.llm_protocol.lower() == "anthropic"
            or "/api/plan" in settings.llm_base_url
            or settings.llm_api_key.startswith("ark-")
        )

        if is_anthropic:
            logger.info("启用 Anthropic A社协议客户端 (Target: %s, Model: %s)", settings.llm_base_url, settings.llm_model_id)
            _llm = AnthropicCompatibleLLM(
                api_key=settings.llm_api_key,
                model=settings.llm_model_id,
                base_url=settings.llm_base_url,
            )
        else:
            logger.info("启用标准 OpenAI 兼容客户端 (Target: %s, Model: %s)", settings.llm_base_url, settings.llm_model_id)
            _llm = HelloAgentsLLM(
                api_key=settings.llm_api_key,
                model=settings.llm_model_id,
                base_url=settings.llm_base_url,
            )

    return _llm


def reset_llm() -> Any:
    """重置 LLM 实例"""
    global _llm
    _llm = None
    return get_llm()
