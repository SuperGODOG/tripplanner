# Phase 1: 环境搭建与 MCP 工具集成

**目标**：建好 Python 项目骨架，调通 amap-mcp-server，验证能通过 MCP 调用高德地图 API。

**前置条件**：已申请高德地图 API Key（Web 服务），系统有 Python 3.10+

**预计时间**：3-4 天 | **代码量**：~200 行

---

## 1.1 项目目录结构

```
backend/
├── app/
│   ├── __init__.py          # 让 app/ 成为 Python 包
│   ├── config.py            # 配置管理（API Key, 端口等）
│   ├── agents/              # Agent 定义（Phase 2 用）
│   │   └── __init__.py
│   ├── services/            # MCP 封装、工具
│   │   └── __init__.py
│   ├── tools/               # 本地 Tool（Phase 4 用）
│   │   └── __init__.py
│   ├── models/              # Pydantic 数据模型（Phase 5 用）
│   │   └── __init__.py
│   └── api/                 # FastAPI 路由（Phase 5 用）
│       └── __init__.py
├── .env                     # API Key（不提交 Git）
├── .env.example             # 模板（提交 Git）
├── requirements.txt         # 依赖清单
└── run.py                   # 启动入口
```

### 为什么每个目录要放 `__init__.py`？

Python 把包含 `__init__.py` 的目录当作**包（package）**。有了它：
- 可以用 `from app.config import settings` 而非写 sys.path  hack
- `__init__.py` 可以写包的公开接口（控制 `from package import *` 的行为）
- 即使是空文件也必须放，否则 Python 不会把目录识别为包

创建命令（先别跑，后面给你完整脚本）：

```bash
mkdir -p backend/app/{agents,services,tools,models,api}
touch backend/app/__init__.py
touch backend/app/{agents,services,tools,models,api}/__init__.py
```

---

## 1.2 Python 虚拟环境

### 为什么需要 venv？

Python 全局安装的包是所有项目共用的。不同项目可能依赖同一个包的不同版本（比如项目 A 要 fastapi 0.100，项目 B 要 0.115）。venv 给每个项目一个**隔离的 Python 环境**，互不干扰。

```bash
# 在 backend/ 目录下创建虚拟环境
cd backend
python3 -m venv venv

# 激活（每次打开新终端都要执行）
source venv/bin/activate

# 你的终端提示符会变成 (venv) ...——说明已激活
```

### `python3 -m venv venv` 做了什么？

1. 在 `backend/venv/` 下复制了一份 Python 解释器
2. 创建独立的 `site-packages/` 目录
3. 之后 `pip install` 的包都装到这里，不影响系统 Python

---

## 1.3 依赖安装

创建 `backend/requirements.txt`：

```txt
# HelloAgents 框架
hello-agents[protocols]>=0.2.4,<=0.2.9

# FastAPI（Phase 5 才用，先装上）
fastapi>=0.115.0
uvicorn[standard]>=0.32.0
pydantic>=2.0.0
pydantic-settings>=2.0.0

# HTTP 客户端
httpx>=0.27.0

# 环境变量管理
python-dotenv>=1.0.0

# CORS
python-multipart>=0.0.9

# 日志
loguru>=0.7.0

# MCP
fastmcp>=2.0.0
uv>=0.8.0

# 工具
python-dateutil>=2.8.2
```

安装：

```bash
pip install -r requirements.txt
```

---

## 1.4 环境变量配置

创建 `backend/.env`（**不提交 Git**，放 API Key）：

```bash
# LLM
LLM_API_KEY=你的DeepSeek_API_Key
LLM_MODEL_ID=deepseek-chat
LLM_BASE_URL=https://api.deepseek.com/v1

# 高德地图
AMAP_API_KEY=你的高德地图Web服务Key

# 服务
HOST=0.0.0.0
PORT=8000
```

创建 `backend/.env.example`（**提交 Git**，不含真实 Key）：

```bash
LLM_API_KEY=your_deepseek_api_key_here
LLM_MODEL_ID=deepseek-chat
LLM_BASE_URL=https://api.deepseek.com/v1
AMAP_API_KEY=your_amap_api_key_here
HOST=0.0.0.0
PORT=8000
```

---

## 1.5 配置管理模块

创建 `backend/app/config.py`：

```python
"""应用配置管理"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # LLM 配置
    llm_api_key: str
    llm_model_id: str = "deepseek-chat"
    llm_base_url: str = "https://api.deepseek.com/v1"

    # 高德地图
    amap_api_key: str

    # 服务配置
    host: str = "0.0.0.0"
    port: int = 8000
    app_name: str = "TripPlanner"
    app_version: str = "1.0.0"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


# 全局单例
_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
```

**为什么用 pydantic-settings？**
- 自动从 `.env` 文件读取环境变量
- 类型校验（port 必须是 int，写错成字符串会报错）
- IDE 有自动补全

---

## 1.6 MCP 工具连接验证

创建 `backend/app/services/amap_service.py`：

```python
"""高德地图 MCP 服务封装"""
from hello_agents.tools import MCPTool
from ..config import get_settings

_amap_mcp_tool: MCPTool | None = None


def get_amap_mcp_tool() -> MCPTool:
    """获取高德地图 MCP 工具实例（单例模式）"""
    global _amap_mcp_tool

    if _amap_mcp_tool is None:
        settings = get_settings()

        # MCPTool 连接 amap-mcp-server
        # server_command=["uvx", "amap-mcp-server"] 表示用 uvx 启动
        # auto_expand=True: MCP 服务器提供的多个工具自动展开为独立方法
        _amap_mcp_tool = MCPTool(
            name="amap",
            description="高德地图服务，支持 POI 搜索、路线规划、天气查询",
            server_command=["uvx", "amap-mcp-server"],
            env={"AMAP_MAPS_API_KEY": settings.amap_api_key},
            auto_expand=True,
        )

    return _amap_mcp_tool
```

**MCPTool 工作原理**：
1. `server_command=["uvx", "amap-mcp-server"]` — 通过 uvx 启动 amap-mcp-server 子进程
2. MCPTool 通过 stdio（标准输入输出）与子进程通信（JSON-RPC 协议）
3. `auto_expand=True` — 子进程提供的 maps_text_search、maps_weather 等方法自动注册为可调用方法
4. 每次 `mcp_tool.run(...)` 实际上是：序列化参数 → 发给子进程 → 子进程调高德 API → 返回结果

---

## 1.7 验证脚本

创建 `backend/test_mcp.py`（验证用，Phase 完成后可删除）：

```python
"""验证 MCP 连接和基本工具调用"""
import sys
sys.path.insert(0, ".")

from app.services.amap_service import get_amap_mcp_tool

def test_mcp_connection():
    """测试 1: 验证 MCP 连接"""
    print("=" * 50)
    print("测试 1: MCP 连接")
    print("=" * 50)

    tool = get_amap_mcp_tool()
    print(f"✅ MCP 工具连接成功")
    print(f"   可用工具数量: {len(tool._available_tools)}")

    if tool._available_tools:
        print("   可用工具列表:")
        for t in tool._available_tools[:10]:
            print(f"     - {t.get('name', 'unknown')}")

    return True


def test_poi_search():
    """测试 2: 景点搜索"""
    print("\n" + "=" * 50)
    print("测试 2: POI 搜索（北京景点）")
    print("=" * 50)

    tool = get_amap_mcp_tool()
    result = tool.run({
        "action": "call_tool",
        "tool_name": "maps_text_search",
        "arguments": {
            "keywords": "景点",
            "city": "北京",
            "citylimit": "true"
        }
    })

    print(f"✅ POI 搜索成功")
    print(f"   返回数据长度: {len(str(result))} 字符")
    print(f"   前 300 字符: {str(result)[:300]}")
    return True


def test_weather():
    """测试 3: 天气查询"""
    print("\n" + "=" * 50)
    print("测试 3: 天气查询（北京）")
    print("=" * 50)

    tool = get_amap_mcp_tool()
    result = tool.run({
        "action": "call_tool",
        "tool_name": "maps_weather",
        "arguments": {
            "city": "北京"
        }
    })

    print(f"✅ 天气查询成功")
    print(f"   返回数据长度: {len(str(result))} 字符")
    print(f"   前 300 字符: {str(result)[:300]}")
    return True


if __name__ == "__main__":
    try:
        test_mcp_connection()
        test_poi_search()
        test_weather()
        print("\n" + "=" * 50)
        print("🎉 全部测试通过！MCP 集成成功。")
        print("=" * 50)
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
```

---

## 1.8 验证标准

在 `backend/` 目录下执行：

```bash
source venv/bin/activate
python test_mcp.py
```

**Phase 1 通过标准**：
- [ ] `test_mcp_connection()` 输出"✅ MCP 工具连接成功"并列出可用工具
- [ ] `test_poi_search()` 输出"✅ POI 搜索成功"并返回景点数据
- [ ] `test_weather()` 输出"✅ 天气查询成功"并返回天气数据

---

## 1.9 常见问题

| 问题 | 原因 | 解决 |
|------|------|------|
| `ModuleNotFoundError: No module named 'hello_agents'` | venv 未激活或未安装 | `source venv/bin/activate && pip install -r requirements.txt` |
| MCPTool 连接超时 | 首次运行 `uvx amap-mcp-server` 需下载 | 等 1-2 分钟，uvx 在自动安装 |
| `AMAP_API_KEY 未配置` | Key 格式不对 | 高德 Key 需要是"Web 服务"类型，不是"JS API"类型 |
| `maps_text_search` 返回空 | city 参数或 keywords 不对 | 先用 curl 验证 Key：`curl "https://restapi.amap.com/v3/place/text?keywords=景点&city=北京&key=你的KEY"` |
