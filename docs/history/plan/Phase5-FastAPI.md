# Phase 5: FastAPI 接口层

**目标**：给 LangGraph 编排引擎套上 REST API，端到端跑通"发 HTTP 请求 → 返回旅行计划 JSON"。

**前置条件**：Phase 4 通过（图编排 + 本地 Tool 正常）

**预计时间**：2-3 天 | **代码量**：~200 行

---

## 5.1 数据模型

创建 `backend/app/models/schemas.py`：

```python
"""Pydantic 数据模型"""
from pydantic import BaseModel, Field
from typing import Optional


class TripRequest(BaseModel):
    """旅行规划请求"""
    city: str = Field(..., description="目标城市", example="北京")
    days: int = Field(..., ge=1, le=14, description="旅行天数", example=3)
    preferences: list[str] = Field(
        default_factory=list,
        description="偏好（历史文化/美食/自然风光/购物）",
        example=["历史文化", "美食"]
    )


class Location(BaseModel):
    """地理位置"""
    longitude: float
    latitude: float


class Attraction(BaseModel):
    """景点"""
    name: str
    address: str = ""
    location: Location | None = None
    visit_duration: int = 120
    description: str = ""
    ticket_price: int = 0


class Meal(BaseModel):
    """餐饮"""
    type: str  # breakfast/lunch/dinner
    name: str
    description: str = ""
    estimated_cost: int = 0


class DayPlan(BaseModel):
    """单日行程"""
    date: str
    day_index: int
    description: str
    attractions: list[Attraction] = []
    meals: list[Meal] = []


class TripPlan(BaseModel):
    """旅行计划（响应）"""
    city: str
    days: list[DayPlan] = []
    weather_info: list[dict] = []
    overall_suggestions: str = ""
    budget: dict = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
```

---

## 5.2 API 路由

创建 `backend/app/api/trip.py`：

```python
"""旅行规划 API"""
from fastapi import APIRouter, HTTPException
from ..models.schemas import TripRequest, TripPlan
from ..graph.builder import get_trip_graph

router = APIRouter(prefix="/api", tags=["trip"])


@router.post("/trip", response_model=TripPlan)
async def plan_trip(request: TripRequest):
    """
    生成旅行计划。

    发送城市、天数、偏好，返回结构化旅行计划。
    """
    try:
        graph = get_trip_graph()

        initial_state = {
            "city": request.city,
            "days": request.days,
            "preferences": request.preferences,
            "attraction_data": "",
            "weather_data": "",
            "hotel_data": "",
            "attraction_status": "",
            "weather_status": "",
            "hotel_status": "",
            "final_plan": {},
            "error_log": [],
        }

        result = graph.invoke(initial_state)

        # 从 graph state 构建响应
        plan_data = result.get("final_plan", {})
        errors = result.get("error_log", [])

        return TripPlan(
            city=plan_data.get("city", request.city),
            days=plan_data.get("days", []),
            weather_info=plan_data.get("weather_info", []),
            overall_suggestions=plan_data.get("overall_suggestions", ""),
            budget=plan_data.get("budget", {}),
            errors=errors,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

---

## 5.3 主应用入口

创建 `backend/app/api/main.py`：

```python
"""FastAPI 主应用"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from ..config import get_settings
from .trip import router as trip_router

settings = get_settings()

app = FastAPI(
    title="TripPlanner",
    version=settings.app_version,
    description="多智能体旅行规划系统 API",
    docs_url="/docs",
)

# CORS（允许前端跨域访问）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(trip_router)


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.get("/")
async def root():
    return {
        "name": "TripPlanner",
        "docs": "/docs",
    }
```

---

## 5.4 启动脚本

创建 `backend/run.py`：

```python
"""启动入口"""
import uvicorn
from app.config import get_settings

if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run(
        "app.api.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )
```

---

## 5.5 验证

```bash
cd backend
source venv/bin/activate
python run.py
```

访问 http://localhost:8000/docs → Swagger UI。

测试请求：

```bash
curl -X POST http://localhost:8000/api/trip \
  -H "Content-Type: application/json" \
  -d '{
    "city": "北京",
    "days": 3,
    "preferences": ["历史文化"]
  }'
```

**Phase 5 通过标准**：
- [ ] `/docs` 能打开 Swagger UI
- [ ] `POST /api/trip` 返回 200 和完整 JSON
- [ ] 响应包含 city, days, attractions, weather_info, budget
- [ ] 如果有错误，errors 字段有内容但不崩溃

---

## 5.6 当前目录结构

Phase 5 完成后：

```
backend/
├── app/
│   ├── __init__.py
│   ├── config.py            # 配置（Phase 1）
│   ├── agents/
│   │   ├── __init__.py
│   │   └── trip_planner_agent.py  # 4 Agent（Phase 2）
│   ├── services/
│   │   ├── __init__.py
│   │   ├── amap_service.py        # MCP 连接（Phase 1）
│   │   └── llm_service.py         # LLM 连接（Phase 2）
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── amap_wrapper.py        # AmapToolWrapper（Phase 4）
│   │   └── fallback.py            # FallbackTool（Phase 4）
│   ├── graph/
│   │   ├── __init__.py
│   │   ├── state.py               # State 定义（Phase 3）
│   │   ├── nodes.py               # Node 函数（Phase 3）
│   │   └── builder.py             # 图构建（Phase 3）
│   ├── models/
│   │   ├── __init__.py
│   │   └── schemas.py             # Pydantic 模型（Phase 5）
│   └── api/
│       ├── __init__.py
│       ├── main.py                # FastAPI app（Phase 5）
│       └── trip.py                # 路由（Phase 5）
├── venv/
├── .env
├── .env.example
├── requirements.txt
└── run.py
```
