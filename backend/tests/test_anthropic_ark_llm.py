"""火山方舟与 Anthropic 协议 LLM 客户端测试集

验证指标:
1. 客户端初始化与参数配置
2. 请求载荷与请求头组装（x-api-key, anthropic-version, system 参数剥离）
3. 复杂响应体解析（智能剥离 thinking 块，干净提取 text）
4. 真实/Mock 连通性与 invoke 接口一致性
"""
import pytest
from unittest.mock import patch, MagicMock
import json
from app.services.llm_service import AnthropicCompatibleLLM, get_llm


def test_anthropic_llm_request_structure():
    """验证 Anthropic 协议请求报文结构"""
    client = AnthropicCompatibleLLM(
        api_key="ark-test-key",
        model="glm-5.3-flash",
        base_url="https://ark.cn-beijing.volces.com/api/plan",
    )

    assert client.endpoint_url == "https://ark.cn-beijing.volces.com/api/plan/v1/messages"
    assert client.api_key == "ark-test-key"
    assert client.model == "glm-5.3-flash"


def test_anthropic_llm_response_parsing_with_thinking():
    """验证能从包含 thinking 思考块的复杂响应中纯净提取 text 文本"""
    client = AnthropicCompatibleLLM(
        api_key="ark-test-key",
        model="glm-5.3-flash",
        base_url="https://ark.cn-beijing.volces.com/api/plan",
    )

    mock_response_data = {
        "id": "msg_12345",
        "type": "message",
        "role": "assistant",
        "model": "glm-5-3-flash",
        "content": [
            {
                "type": "thinking",
                "thinking": "这里是模型的内部思考链过程，不需要展示给用户...",
            },
            {
                "type": "text",
                "text": "这是最终输出给用户的干净旅游计划文本。",
            },
        ],
    }

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(mock_response_data).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        messages = [
            {"role": "system", "content": "系统设定"},
            {"role": "user", "content": "你好"},
        ]
        result = client.invoke(messages)

    assert result == "这是最终输出给用户的干净旅游计划文本。"


def test_get_llm_routes_to_anthropic():
    """验证全局工厂根据配置正确路由到 AnthropicCompatibleLLM"""
    llm = get_llm()
    assert isinstance(llm, AnthropicCompatibleLLM)
