import os
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutTimeout
from functools import lru_cache
from typing import Any
from ..config import get_settings
from .amap_native import AmapNativeTool

_amap_mcp_tool: Any = None

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


@lru_cache(maxsize=512)
def geo_cached(address: str, city: str = "") -> tuple[float, float] | None:
    """maps_geo 结果缓存（内存 LRU，最简单形态）。

    城市中心 / POI 坐标增强 / 城际地理编码三处共用。
    若传入 city 且 address 中未包含，强制前置城市名，彻底杜绝全国重名地址漂移至外省。
    """
    try:
        clean_addr = address.strip()
        if city and city not in clean_addr:
            query_addr = f"{city} {clean_addr}".strip()
        else:
            query_addr = clean_addr

        args: dict[str, Any] = {"address": query_addr}
        if city:
            args["city"] = city.strip()
        r = str(run_mcp({
            "action": "call_tool", "tool_name": "maps_geo",
            "arguments": args,
        }))
        m = re.search(r'"location"\s*:\s*"([\d.]+),([\d.]+)"', r)
        if m:
            return float(m.group(1)), float(m.group(2))
    except Exception:
        pass
    return None


def get_amap_mcp_tool() -> Any:
    """获取高德地图工具实例（单例模式）

    默认优先采用原生进程内连接池工具 AmapNativeTool（0 外部子进程、毫秒级响应、零发热）；
    若设置环境变量 AMAP_USE_LEGACY_MCP=true，则降级使用外部 uvx amap-mcp-server 子进程。
    """
    global _amap_mcp_tool

    if _amap_mcp_tool is None:
        settings = get_settings()

        if not settings.amap_api_key:
            raise ValueError(
                "高德地图 API Key 未配置，请在 .env 文件中设置 AMAP_API_KEY\n"
                "申请地址: https://console.amap.com/dev/key/app"
            )

        if os.environ.get("AMAP_USE_LEGACY_MCP", "").lower() in ("true", "1"):
            from hello_agents.tools import MCPTool
            _amap_mcp_tool = MCPTool(
                name="amap",
                description="高德地图服务，支持 POI 搜索、路线规划、天气查询",
                server_command=["uvx", "amap-mcp-server"],
                env={"AMAP_MAPS_API_KEY": settings.amap_api_key},
                auto_expand=True,
            )
        else:
            _amap_mcp_tool = AmapNativeTool(settings.amap_api_key)

    return _amap_mcp_tool
