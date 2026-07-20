"""高德地图 MCP 服务封装"""
from hello_agents.tools import MCPTool
from ..config import get_settings

_amap_mcp_tool: MCPTool | None = None


def get_amap_mcp_tool() -> MCPTool:
    """获取高德地图 MCP 工具实例（单例模式）

    只创建一个 MCPTool 实例，所有 Agent 共享。
    每个 MCPTool 启动一个 amap-mcp-server 子进程（约 500ms 握手），
    共用避免重复建连。
    """
    global _amap_mcp_tool

    if _amap_mcp_tool is None:
        settings = get_settings()

        if not settings.amap_api_key:
            raise ValueError(
                "高德地图 API Key 未配置，请在 .env 文件中设置 AMAP_API_KEY\n"
                "申请地址: https://console.amap.com/dev/key/app"
            )

        _amap_mcp_tool = MCPTool(
            name="amap",
            description="高德地图服务，支持 POI 搜索、路线规划、天气查询",
            server_command=["uvx", "amap-mcp-server"],
            env={"AMAP_MAPS_API_KEY": settings.amap_api_key},
            auto_expand=True,
        )

    return _amap_mcp_tool
