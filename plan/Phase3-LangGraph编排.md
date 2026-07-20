# Phase 3: LangGraph 图编排

**目标**：把 Phase 2 的顺序调用改为 LangGraph StateGraph，支持 conditional edge（节点失败时自动降级）。

**前置条件**：Phase 2 通过（4 Agent 能独立工作）

**预计时间**：5-6 天（啃硬骨头的一周） | **代码量**：~200 行

---

## 3.1 LangGraph vs 顺序调用

Phase 2 的做法（硬编码）：

```python
def plan_trip(self, ...):
    a = self.attraction_agent.run(...)   # 失败了？直接抛异常
    w = self.weather_agent.run(...)
    h = self.hotel_agent.run(...)
    p = self.planner_agent.run(...)
```

Phase 3 的做法（LangGraph）：

```python
# 每个 Agent 是一个 Node
# Edge 定义流转顺序
# conditional edge: 景点成功 → 下一步 | 景点失败 → 跳过景点但继续
```

**LangGraph 给你三样东西是手写 while 做不到的**（面试核心论点）：

1. **Checkpoint 持久化**：每个 Node 执行后的 State 自动保存。中断重启不丢进度。
2. **声明式流转**：改流程顺序只需改图定义，不用改业务代码。
3. **条件路由可视化**：`add_conditional_edges("attraction", router, {True: "weather", False: "weather"})` 一清二楚。

---

## 3.2 图结构

```
            ┌──────────┐
            │  START   │
            └────┬─────┘
                 │
            ┌────▼─────┐
            │ 景点搜索  │──成功──→ ┌──────────┐
            │  Node    │──失败──→ │ 天气查询  │
            └──────────┘         │  Node    │
                                 └────┬─────┘
                                      │
            ┌────────────────────成功/失败
            │                         │
       ┌────▼─────┐                   │
       │ 酒店推荐  │←──────────────────┘
       │  Node    │
       └────┬─────┘
            │
       ┌────▼─────┐
       │ 行程规划  │
       │  Node    │
       └────┬─────┘
            │
       ┌────▼─────┐
       │   END    │
       └──────────┘
```

**关键行为**（conditional routing——图级）：
- 景点失败 → **天气继续执行**，规划阶段标注"景点数据不可用"
- 天气失败 → **酒店继续执行**，规划阶段给通用穿衣建议
- 酒店失败 → **规划继续执行**，按预算推荐住宿
- 前三个全失败 → 规划仍能生成基本行程（带降级标注）

**注意**：这里的 conditional routing 发生在图级（LangGraph），和 Agent 内部的 Error-as-Observation（Agent 级）是两层独立机制。图级管"节点间要不要跳过"，Agent 级管"工具调用失败了要不要重试"。

---

## 3.3 State 定义

LangGraph 的 State 是一个 TypedDict，每个 Node 读/写 State，Edge 根据 State 中的字段决定路由。

创建 `backend/app/graph/state.py`：

```python
"""LangGraph State 定义"""
from typing import TypedDict, Annotated
from langgraph.graph.message import add_messages


class TripPlannerState(TypedDict):
    """图状态——每个 Node 读写这些字段"""

    # === 输入 ===
    city: str                      # 目标城市
    days: int                      # 旅行天数
    preferences: list[str]         # 用户偏好

    # === 各 Agent 输出 ===
    attraction_data: str           # 景点搜索结果（原始文本）
    weather_data: str              # 天气查询结果
    hotel_data: str                # 酒店搜索结果

    # === 状态标记（给 conditional edge 读） ===
    attraction_status: str         # "success" | "failed"
    weather_status: str
    hotel_status: str

    # === 最终输出 ===
    final_plan: dict               # 结构化旅行计划
    error_log: list[str]           # 错误日志
```

**为什么用 TypedDict 而非 dataclass？**
LangGraph 的 `add_messages` reducer 需要特定类型。TypedDict 定义了 State 的 shape，LangGraph 知道每个 Node 可以修改哪些字段。

---

## 3.4 Node 函数

每个 Node 函数签名为 `(state: TripPlannerState) -> dict`。返回 dict 中的键会合并到 State（LangGraph 自动做 partial update）。

创建 `backend/app/graph/nodes.py`：

```python
"""LangGraph Node 函数"""
from .state import TripPlannerState
from ..agents.trip_planner_agent import get_planner


def attraction_node(state: TripPlannerState) -> dict:
    """Node 1: 景点搜索"""
    city = state["city"]
    prefs = state.get("preferences", [])

    try:
        planner = get_planner()
        query = (
            f"请搜索{city}的景点。\n"
            f"[TOOL_CALL:amap_maps_text_search:keywords=景点,city={city}]"
        )
        result = planner.attraction_agent.run(query)

        return {
            "attraction_data": result,
            "attraction_status": "success",
        }
    except Exception as e:
        error_msg = f"景点搜索失败: {str(e)}"
        return {
            "attraction_data": "",
            "attraction_status": "failed",
            "error_log": [error_msg],
        }


def weather_node(state: TripPlannerState) -> dict:
    """Node 2: 天气查询"""
    city = state["city"]

    try:
        planner = get_planner()
        query = f"请查询{city}的天气。\n[TOOL_CALL:amap_maps_weather:city={city}]"
        result = planner.weather_agent.run(query)

        return {
            "weather_data": result,
            "weather_status": "success",
        }
    except Exception as e:
        return {
            "weather_data": "",
            "weather_status": "failed",
            "error_log": [f"天气查询失败: {str(e)}"],
        }


def hotel_node(state: TripPlannerState) -> dict:
    """Node 3: 酒店搜索"""
    city = state["city"]

    try:
        planner = get_planner()
        query = (
            f"请搜索{city}的酒店。\n"
            f"[TOOL_CALL:amap_maps_text_search:keywords=酒店,city={city}]"
        )
        result = planner.hotel_agent.run(query)

        return {
            "hotel_data": result,
            "hotel_status": "success",
        }
    except Exception as e:
        return {
            "hotel_data": "",
            "hotel_status": "failed",
            "error_log": [f"酒店搜索失败: {str(e)}"],
        }


def planner_node(state: TripPlannerState) -> dict:
    """Node 4: 行程规划——整合前三者结果"""
    city = state["city"]
    days = state["days"]
    prefs = state.get("preferences", [])

    # 构建降级标注
    warnings = []
    if state.get("attraction_status") == "failed":
        warnings.append("⚠️ 景点数据不可用，行程中景点为推荐项")
    if state.get("weather_status") == "failed":
        warnings.append("⚠️ 天气数据不可用，请根据季节准备衣物")
    if state.get("hotel_status") == "failed":
        warnings.append("⚠️ 酒店数据不可用，住宿为通用推荐")

    planner = get_planner()

    query = f"""请根据以下信息生成{city}的{days}天旅行计划:

景点信息:
{state.get('attraction_data', '无景点数据')}

天气信息:
{state.get('weather_data', '无天气数据')}

酒店信息:
{state.get('hotel_data', '无酒店数据')}

偏好: {', '.join(prefs) if prefs else '无'}
{'【注意】' + '; '.join(warnings) if warnings else ''}
"""
    result = planner.planner_agent.run(query)
    plan = planner._parse_plan(result)

    return {
        "final_plan": plan,
    }
```

---

## 3.5 图构建

创建 `backend/app/graph/builder.py`：

```python
"""LangGraph 图构建"""
from langgraph.graph import StateGraph, END
from .state import TripPlannerState
from .nodes import attraction_node, weather_node, hotel_node, planner_node


def build_trip_graph() -> StateGraph:
    """构建 TripPlanner LangGraph"""

    # 1. 创建 StateGraph
    graph = StateGraph(TripPlannerState)

    # 2. 添加 Node
    graph.add_node("attraction", attraction_node)
    graph.add_node("weather", weather_node)
    graph.add_node("hotel", hotel_node)
    graph.add_node("planner", planner_node)

    # 3. 设定入口
    graph.set_entry_point("attraction")

    # 4. 添加 Edge
    # 景点 → 天气（不论成功失败都继续）
    graph.add_edge("attraction", "weather")
    # 天气 → 酒店
    graph.add_edge("weather", "hotel")
    # 酒店 → 规划
    graph.add_edge("hotel", "planner")
    # 规划 → 结束
    graph.add_edge("planner", END)

    # 5. 编译图（内置 Checkpoint 持久化）
    return graph.compile()


# 全局图实例
_trip_graph = None


def get_trip_graph():
    global _trip_graph
    if _trip_graph is None:
        _trip_graph = build_trip_graph()
    return _trip_graph
```

**为什么这里是简单的 linear edge 而非 conditional edge？**

在 Phase 3，先用最简单的 linear graph（所有节点都执行，不跳过）验证 LangGraph 集成正确。conditional edge 在 Phase 4 配合错误恢复加入。

其实你如果现在就想加 conditional edge：

```python
# 替换 graph.add_edge("attraction", "weather") 为：
def route_after_attraction(state: TripPlannerState) -> str:
    # 不管景点成功还是失败，都去天气节点
    # 真正的降级逻辑在 planner_node 里
    return "weather"

graph.add_conditional_edges(
    "attraction",
    route_after_attraction,
    {"weather": "weather"}
)
```

---

## 3.6 运行验证

创建 `backend/test_graph.py`：

```python
"""Phase 3 验证：LangGraph 编排"""
import sys
sys.path.insert(0, ".")

from app.graph.builder import get_trip_graph

def test_graph():
    graph = get_trip_graph()

    initial_state = {
        "city": "北京",
        "days": 3,
        "preferences": ["历史文化"],
        "attraction_data": "",
        "weather_data": "",
        "hotel_data": "",
        "attraction_status": "",
        "weather_status": "",
        "hotel_status": "",
        "final_plan": {},
        "error_log": [],
    }

    print("🚀 开始 LangGraph 编排...")
    result = graph.invoke(initial_state)

    plan = result.get("final_plan", {})
    print(f"\n城市: {plan.get('city')}")
    print(f"天数: {len(plan.get('days', []))}")
    print(f"景点状态: {result.get('attraction_status')}")
    print(f"天气状态: {result.get('weather_status')}")
    print(f"酒店状态: {result.get('hotel_status')}")
    print(f"错误数: {len(result.get('error_log', []))}")

    return True

if __name__ == "__main__":
    try:
        test_graph()
        print("\n🎉 Phase 3 验证通过！LangGraph 编排成功。")
    except Exception as e:
        print(f"\n❌ 失败: {e}")
        import traceback
        traceback.print_exc()
```

---

## 3.7 可能的坑

### 坑 1: MCPTool 的 asyncio 冲突

MCPTool 内部使用 `asyncio` 做子进程通信。在 LangGraph 节点中调用时可能遇到 event loop 冲突。

**解法**：如果报 `RuntimeError: This event loop is already running`：

```python
# 在节点函数中，用 nest_asyncio 或在线程池中运行
import asyncio
import concurrent.futures

def attraction_node(state):
    def _run():
        return planner.attraction_agent.run(query)

    with concurrent.futures.ThreadPoolExecutor() as pool:
        result = pool.submit(_run).result()
    return {"attraction_data": result, ...}
```

如果仍然不行，参考实现的做法：不在 LangGraph node 里调 Agent，而是用顺序调 Agent 再用 LangGraph 做状态管理：

```python
# 折中方案：LangGraph 只管状态流转，Agent 调用在外部完成
result1 = agent1.run(...)
state["attraction_data"] = result1
# 再 invoke graph（此时 graph 只需要做状态合并和输出格式化）
```

### 坑 2: hello-agents 和 langgraph 的版本兼容

确保 `hello-agents[protocols]>=0.2.4,<=0.2.9` 和 `langgraph` 都装了：

```bash
pip install langgraph langgraph-checkpoint
```

---

## 3.8 验证标准

```bash
cd backend
source venv/bin/activate
python test_graph.py
```

- [ ] `graph.invoke()` 成功执行，不抛异常
- [ ] 输出包含 `city`, `days`, `attractions`, `weather_info`
- [ ] 有 Checkpoint（Graph 默认启用）
- [ ] 4 个 Node 都执行了（可通过日志确认）

---

## 3.9 Phase 3 vs Phase 2 的核心区别

| | Phase 2 | Phase 3 |
|---|---------|---------|
| 编排方式 | `agent.run()` 顺序调用 | `graph.invoke(state)` |
| 状态管理 | 局部变量 | State（TypedDict），节点间自动传递 |
| 错误处理 | try/except 在外层 | 每个 Node 内 try/except，错误记入 State |
| 可恢复性 | 不可恢复 | Checkpoint 持久化，中断可续 |
| 可扩展性 | 改流程要改代码 | 加 Node / 改 Edge 即可 |
