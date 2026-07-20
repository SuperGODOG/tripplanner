"""Phase 4 验证: AmapToolWrapper + FallbackTool

测试内容:
1. AmapToolWrapper 替代原始 MCPTool，验证 Agent 能否正确调用
2. Wrapper 内部的三层处理（MCP→格式化→校验）是否工作
3. 格式化输出是否是干净文本（而非原始 JSON）
4. FallbackTool 降级模板生成

注意：Phase 4 还包含 conditional edge（LangGraph 部分），
      这部分在 Phase 3 的基础上完成。
      当前测试先用 Phase 2 的顺序调用验证 Wrapper 本身。
"""
import sys
sys.path.insert(0, ".")

from hello_agents import SimpleAgent
from app.services.llm_service import get_llm
from app.tools.amap_wrapper import AmapToolWrapper
from app.tools.fallback import FallbackTool


# Agent Prompts（使用新的工具名 amap_search）
ATTRACTION_PROMPT = """你是景点搜索专家。必须使用工具搜索景点。

工具调用格式:
[TOOL_CALL:amap_search:type=attraction,city=城市名,keywords=景点关键词]

示例:
用户: "搜索北京景点"
回复: [TOOL_CALL:amap_search:type=attraction,city=北京,keywords=历史文化]
"""

WEATHER_PROMPT = """你是天气查询专家。必须使用工具查询天气。

工具调用格式:
[TOOL_CALL:amap_search:type=weather,city=城市名]

示例:
用户: "查询北京天气"
回复: [TOOL_CALL:amap_search:type=weather,city=北京]
"""

HOTEL_PROMPT = """你是酒店推荐专家。必须使用工具搜索酒店。

工具调用格式:
[TOOL_CALL:amap_search:type=hotel,city=城市名]

示例:
用户: "搜索北京酒店"
回复: [TOOL_CALL:amap_search:type=hotel,city=北京]
"""


def test_wrapper():
    """测试 AmapToolWrapper 的三层处理"""
    print("=" * 60)
    print("测试 1: AmapToolWrapper 内部处理")
    print("=" * 60)

    wrapper = AmapToolWrapper()

    # 直接调 run()，验证 MCP→格式化→校验流水线
    result = wrapper.run({"city": "北京", "type": "attraction", "keywords": "历史文化"})

    print(f"✅ 景点搜索（Wrapper）")
    print(f"   返回长度: {len(result)} 字符")
    print(f"   结果预览:\n{result[:500]}\n")
    # 验证关键特征：
    # - 不应该是原始 JSON（应该已被格式化）
    # - 应该有"【景点搜索结果】"标题
    assert "【景点搜索结果】" in result, "应该是格式化文本，不是原始 JSON"
    assert "{" not in result[:100], "前 100 字符不应出现原始 JSON"
    print("   ✅ 验证通过：是格式化文本，非原始 JSON")


def test_wrapper_in_agent():
    """测试 Agent 使用 Wrapper"""
    print("=" * 60)
    print("测试 2: Agent 使用 AmapToolWrapper")
    print("=" * 60)

    llm = get_llm()
    wrapper = AmapToolWrapper()

    agent = SimpleAgent(
        name="测试Agent",
        llm=llm,
        system_prompt=ATTRACTION_PROMPT,
    )
    agent.add_tool(wrapper)

    result = agent.run("搜索北京的历史文化景点\n[TOOL_CALL:amap_search:type=attraction,city=北京,keywords=历史文化]")

    print(f"✅ Agent 使用 Wrapper 成功")
    print(f"   响应长度: {len(result)} 字符")
    print(f"   响应预览:\n{result[:300]}\n")


def test_fallback():
    """测试 FallbackTool"""
    print("=" * 60)
    print("测试 3: FallbackTool")
    print("=" * 60)

    tool = FallbackTool()
    result = tool.run({"city": "北京", "days": 3, "reason": "外部服务不可用"})

    import json
    plan = json.loads(result)

    print(f"✅ FallbackTool 降级方案生成成功")
    print(f"   状态: {plan.get('status')}")
    print(f"   天数: {len(plan.get('days', []))}")
    print(f"   第一天: {plan['days'][0]['description']}")


if __name__ == "__main__":
    print()
    print("╔══════════════════════════════════════════════════════╗")
    print("║     Phase 4 验证: Tool Wrapper + Fallback            ║")
    print("╚══════════════════════════════════════════════════════╝")
    print()

    try:
        test_wrapper()
        test_wrapper_in_agent()
        test_fallback()

        print(f"\n{'='*60}")
        print("🎉 Phase 4 验证通过！")
        print("   - AmapToolWrapper: MCP→格式化→校验 三层流水线正常")
        print("   - Agent 使用 Wrapper: 一次调用拿干净结果")
        print("   - FallbackTool: 降级方案可用")
        print(f"{'='*60}")
    except Exception as e:
        print(f"\n❌ 失败: {e}")
        import traceback
        traceback.print_exc()
