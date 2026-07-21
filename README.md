# 🧳 TripPlanner

> 基于 LangGraph + ReAct 自研编排的多智能体旅行规划系统
> 4 Node StateGraph · MCP 协议 · 五因子权重记忆 · 双轨异常检测

[![Python](https://img.shields.io/badge/Python-3.10+-blue)](https://python.org)
[![LangGraph](https://img.shields.io/badge/LangGraph-1.2-purple)](https://langchain-ai.github.io/langgraph/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.139-green)](https://fastapi.tiangolo.com/)

输入出发地 + 目的地 + 偏好 → 3 个 Agent 协作生成完整旅行计划（景点/酒店/预算），天气+城际交通在 API 层预处理，景点离群检测自动过滤远郊景点，用户画像随使用次数渐进构建。

---

## 🚀 快速部署

### 1. 克隆项目

```bash
git clone https://github.com/你的用户名/tripplanner.git
cd tripplanner/backend
```

### 2. 创建虚拟环境

```bash
python3 -m venv venv
source venv/bin/activate       # Linux/macOS
# venv\Scripts\activate        # Windows
```

### 3. 配置 API Key

```bash
cp .env.example venv/.env
nano venv/.env
```

填入你的 Key：

```ini
LLM_API_KEY=sk-your-deepseek-key
LLM_MODEL_ID=deepseek-chat
LLM_BASE_URL=https://api.deepseek.com/v1
AMAP_API_KEY=your-amap-web-service-key
```

> **高德 Key 申请**：https://console.amap.com/dev/key/app → 选择「Web 服务」类型
>
> **DeepSeek Key 申请**：https://platform.deepseek.com/api_keys

### 4. 安装依赖并启动

```bash
# 配置国内镜像加速（可选）
pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

pip install -r requirements.txt
python run.py
```

浏览器打开：
- **前端界面**：http://localhost:8000/app/
- **API 文档**：http://localhost:8000/docs

### 5. 启动 / 关闭

```bash
# 启动（前台，Ctrl+C 关闭）
cd backend && source venv/bin/activate && python run.py

# 后台启动
nohup python run.py > server.log 2>&1 &

# 关闭
kill $(lsof -ti:8000)
```

---

## 🗑 重置记忆模块

记忆数据存储在 `data/memory.json`，包含用户画像和行程计数。

```bash
# 完全重置（画像归零）
rm -f backend/data/memory.json

# 或只清空行程计数（保留偏好标签）
python -c "
from app.memory.manager import get_memory
m = get_memory()
m.trip_count = 0
m._save()
print('行程计数已重置')
"
```

画像构建需要至少 5 次行程。重置后前端显示 `0 / 5 — 正在构建画像...`。

---

## 🏗 架构设计

### 分层架构

```
第 5 层  多智能体编排     ← 4 Node LangGraph + Conditional Edge
第 4 层  图编排框架       ← StateGraph / Edge / Conditional / Checkpoint
第 3 层  框架封装         ← HelloAgents SimpleAgent
第 2 层  Agent 内循环     ← ReAct (Error-as-Observation)
第 1 层  裸 LLM 调用      ← DeepSeek API
第 0 层  API 预处理       ← 日期计算 / 天气查询 / 城际交通 / 记忆写入
```

### 数据流向

```
POST /api/trip
  │
  ├─ API 预处理层
  │   ├─ 日期列表本地计算（Python，不交 LLM）
  │   ├─ 天气查询（maps_weather 直接调用）
  │   ├─ 城际交通（maps_geo → maps_distance → 费用估算）
  │   └─ 写入记忆（trip_count++）
  │
  └─ graph.invoke(state)
       │
       ├─ Node 1: attraction    ① maps_geo → 城市中心  ② maps_around 20km 搜索景点  ③ 本地 Python 计算景点群质心
       ├─ Node 2: hotel         使用景点质心 nearby 搜索酒店
       ├─ Node 3: memory        加载用户画像（纯本地）
       └─ Node 4: planner       整合数据 + 本地校验（硬伤/软伤/离群检测）→ JSON
            │
            ├─ retry_planner: 硬伤重生成（最多 3 次）
            ├─ retry_hotel:   离群景点 → 重算中心 → 回酒店重搜（最多 2 次）
            └─ done:          输出最终计划
            │
            └─ 降级检测: 所有 error_log 累积 → 前端列表展示
```

### 技术栈

| 组件 | 选型 |
|------|------|
| 编排引擎 | LangGraph StateGraph |
| Agent 框架 | HelloAgents SimpleAgent |
| 工具协议 | MCP (amap-mcp-server, 16 个工具) |
| LLM | DeepSeek (via HelloAgentsLLM) |
| Web 框架 | FastAPI + Pydantic v2 |
| 记忆 | 自定义五因子权重 + 双轨异常检测 |
| 前端 | 单文件 HTML (零依赖) |

### 工具架构

```
Agent 视角:  只看到 1 个 Tool (AmapToolWrapper)

内部 3 层处理:
  第 1 层  MCP 调用    maps_text_search / maps_weather
  第 2 层  Format       JSON → 结构化文本（纯 Python）
  第 3 层  Validate     完整性检查 + 默认值
```

### 记忆系统

**五因子权重公式：**

```
final_weight = domain × decay × interaction × frequency_boost × outlier_penalty
```

**双轨异常检测：**

| 轨道 | 数据类型 | 算法 | 示例 |
|------|---------|------|------|
| 数值型 | 价格标签 | IQR 四分位距 | 5 次 ¥300-500 → 1 次 ¥1500 → outlier |
| 分类型 | 偏好标签 | 频率比 | 5 次"不吃辣" → 1 次"爱吃辣" → outlier |

**画像维度（8 维）：** 出行方式 / 距离偏好 / 住宿 / 预算 / 饮食 / 交通 / 节奏 / 兴趣

### 扩展: Agent 反馈环与离群检测

当前图是 4 Node + Conditional Edge 流: `attraction → hotel → memory → planner → [retry_planner / retry_hotel / done]`。

**已实现的 Conditional Edge 路由：**

| 路由 | 触发条件 | 行为 | 上限 |
|------|---------|------|------|
| `retry_planner` | 硬伤（缺字段/景点<2/预算超30%） | planner 自回环重生成 | MAX_RETRY=3 |
| `retry_hotel` | 离群景点（标准差 > mean+1.5σ 或 >80km） | 重算中心 → hotel 重搜 | MAX_HOTEL_RETRY=2 |
| `done` | 校验通过或重试耗尽 | → END | — |

**离群检测双轮过滤：**
1. **硬上限（80km）**：景点到群中心距离 >80km → 直接排除（非城市景点）
2. **标准差法（1.5σ）**：距离 > mean + 1.5×σ → 标记离群 → 排除后重算质心 → 触发 retry_hotel

LangGraph 的 conditional edge 机制让这种 Agent 间闭环反馈只需图拓扑层面的路由配置，无需改动 Node 内部逻辑。

---

## 🔮 后续更新计划

- [x] **Conditional Edge 实现**：retry_planner（硬伤重生成 3 次）+ retry_hotel（离群重算 2 次）已上线
- [ ] **多用户支持**：记忆模块加入用户隔离（当前为单用户模式）
- [ ] **向量化记忆检索**：当前为关键词匹配，升级为 embedding + 向量相似度（适合"用户之前去杭州时喜欢什么类型"这类语义查询）
- [ ] **流式响应 (SSE)**：API 改为 Server-Sent Events，前端实时展示每个 Node 的进度
- [ ] **多 LLM 提供商**：支持 OpenAI / Claude / 本地模型切换
- [ ] **A2A 协议集成**：Agent-to-Agent 通信，支持跨系统 Agent 协作
- [ ] **前端重构**：从单文件 HTML 迁移到 React/Vue 组件化
- [ ] **Docker 部署**：提供 Dockerfile + docker-compose，一键启动全部服务
- [ ] **自动化测试**：pytest 覆盖各 Node 的单元测试 + 集成测试

---

## 📁 项目结构

```
tripplanner/
├── README.md                    # 本文件
├── PROJECT.md                   # 项目总文档（541 行）
├── ARCHITECTURE.md              # 7 张 Mermaid 架构图
├── plan/                        # Phase 1-7 计划 + 面试文档
└── backend/
    ├── app/
    │   ├── agents/              # 4 SimpleAgent
    │   ├── graph/               # 4 Node StateGraph + Conditional Edge
    │   ├── tools/               # AmapToolWrapper + FallbackTool
    │   ├── memory/              # 五因子 + 双轨异常检测
    │   ├── api/                 # FastAPI + 城际交通预处理
    │   ├── models/              # Pydantic 模型
    │   └── services/            # MCP + LLM 单例
    ├── static/index.html        # MVP 前端
    ├── run.py                   # 一键启动
    ├── .env.example             # 配置模板
    ├── .gitignore
    └── requirements.txt
```

---

## 🖥 前端功能

| 功能 | 说明 |
|------|------|
| 8 维度偏好标签 | 景点/饮食/交通/节奏/住宿/预算/出行方式 |
| 出行方式选择 | 高铁/飞机/自驾 |
| 用户画像面板 | 0/5 渐进构建 → 5 次后展示 8 维画像 |
| 降级列表面板 | 实时展示各步骤的降级信息 |
| 预算可视化 | 堆叠条形图 |
| 天气预报卡片 | 7 日预报 |

---

## 📄 License

MIT
