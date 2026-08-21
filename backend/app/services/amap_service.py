"""高德地图 MCP 服务封装"""
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutTimeout
from functools import lru_cache
from typing import Any
from hello_agents.tools import MCPTool
from ..config import get_settings

_amap_mcp_tool: MCPTool | None = None

# ── 全局 MCP 并发闸（2026-08-21 优化）────────────────────────────
# 所有高德 MCP 调用（POI 搜索 / 坐标增强 / 天气 / 城际交通）统一经
# get_mcp_executor() 这一个线程池执行，全局峰值并发 ≤ MCP_MAX_WORKERS。
# 背景: attraction_node 外层多偏好并行 × 内层坐标增强并行，嵌套放大
# 可达 25+ 路并发 MCP，个人 key 的 QPS 撑不住。
# 规则: 全局池只提交「叶子 mcp.run 任务」——池内任务不得再向池内
# 提交并等待（池满时互相等 = 死锁）。外层并行壳（多偏好/geo 增强/
# 城际双查）保持独立线程，内部 MCP 调用全部收敛到本池。
MCP_MAX_WORKERS = 10
_mcp_executor: ThreadPoolExecutor | None = None


def get_mcp_executor() -> ThreadPoolExecutor:
    """获取全局 MCP 线程池（单例，永不 shutdown）。"""
    global _mcp_executor
    if _mcp_executor is None:
        _mcp_executor = ThreadPoolExecutor(max_workers=MCP_MAX_WORKERS)
    return _mcp_executor


def run_mcp(args: dict, timeout: int = 10) -> Any:
    """统一 MCP 调用入口（叶子任务，经全局池限流）。超时返回 {"error": "MCP timeout"}。"""
    mcp = get_amap_mcp_tool()
    future = get_mcp_executor().submit(mcp.run, args)
    try:
        return future.result(timeout=timeout)
    except FutTimeout:
        return {"error": "MCP timeout"}


@lru_cache(maxsize=256)
def geo_cached(address: str) -> tuple[float, float] | None:
    """maps_geo 结果缓存（内存 LRU，最简单形态）。

    城市中心 / POI 坐标增强 / 城际地理编码三处共用。
    高德 POI 坐标几乎不变，同一地址反复查询直接命中。
    失败（None）也会被缓存——失败地址再次出现的概率低，可接受。
    """
    try:
        r = str(run_mcp({
            "action": "call_tool", "tool_name": "maps_geo",
            "arguments": {"address": address},
        }))
        m = re.search(r'"location"\s*:\s*"([\d.]+),([\d.]+)"', r)
        if m:
            return float(m.group(1)), float(m.group(2))
    except Exception:
        pass
    return None


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
