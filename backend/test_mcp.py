"""Phase 1 验证：MCP 连接测试

用法:
    cd backend
    source venv/bin/activate
    python test_mcp.py
"""
import sys
sys.path.insert(0, ".")

from app.services.amap_service import get_amap_mcp_tool


def test_mcp_connection():
    """测试 1: 验证 MCP 工具连接并列出可用工具"""
    print("=" * 60)
    print("测试 1: MCP 连接 + 工具发现")
    print("=" * 60)

    tool = get_amap_mcp_tool()
    tool_count = len(tool._available_tools)

    print(f"✅ MCP 连接成功！")
    print(f"   发现 {tool_count} 个可用工具:")

    for t in tool._available_tools[:15]:
        name = t.get("name", "unknown")
        desc = t.get("description", "")
        # 截断过长的描述
        desc_short = desc[:60] + "..." if len(desc) > 60 else desc
        print(f"   • {name}")
        if desc_short:
            print(f"     {desc_short}")

    if tool_count > 15:
        print(f"   ... 还有 {tool_count - 15} 个工具")

    print()
    return True


def test_poi_search():
    """测试 2: 景点搜索"""
    print("=" * 60)
    print("测试 2: POI 搜索（北京景点）")
    print("=" * 60)

    tool = get_amap_mcp_tool()
    result = tool.run({
        "action": "call_tool",
        "tool_name": "maps_text_search",
        "arguments": {
            "keywords": "景点",
            "city": "北京",
            "citylimit": "true",
        },
    })

    result_str = str(result)
    print(f"✅ POI 搜索成功")
    print(f"   返回数据: {len(result_str)} 字符")
    # 显示前几个结果
    print(f"   预览:\n{result_str[:400]}")
    print()
    return True


def test_weather():
    """测试 3: 天气查询"""
    print("=" * 60)
    print("测试 3: 天气查询（北京）")
    print("=" * 60)

    tool = get_amap_mcp_tool()
    result = tool.run({
        "action": "call_tool",
        "tool_name": "maps_weather",
        "arguments": {
            "city": "北京",
        },
    })

    result_str = str(result)
    print(f"✅ 天气查询成功")
    print(f"   返回数据: {len(result_str)} 字符")
    print(f"   预览:\n{result_str[:400]}")
    print()
    return True


if __name__ == "__main__":
    print()
    print("╔══════════════════════════════════════════════════════╗")
    print("║     TripPlanner MCP 集成验证                         ║")
    print("╚══════════════════════════════════════════════════════╝")
    print()

    try:
        test_mcp_connection()
        test_poi_search()
        test_weather()

        print("=" * 60)
        print("🎉 全部测试通过！")
        print("   MCP 连接正常，可搜索景点，可查询天气。")
        print("   Phase 1 完成 ✓")
        print("=" * 60)
    except ValueError as e:
        print(f"\n❌ 配置错误: {e}")
        print("\n请先编辑 backend/.env 填入 API Key:")
        print("  cp backend/.env.example backend/.env")
        print("  nano backend/.env")
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
