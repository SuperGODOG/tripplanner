# 🧳 TripPlanner

> 多日旅行规划 AI Agent — 确定性优先 + LLM 最小职责的分日并行架构

基于 LangGraph 自研图编排的多日旅行规划系统。输入出发地 + 目的地 + 天数 + 偏好，输出完整行程（景点/顺序/时间/酒店/三餐/预算/天气），行程计划端到端可观测、可降级。

**v3 核心设计**：景点互斥由数据层保证（K-Means 聚簇分天），路径顺序本地求解（贪心 + 2-opt + 时间窗），全程酒店目标函数选址（minimax 通勤），LLM 职责收缩到"每天一段文案"。

## 架构（v3：动态分日并发）

```
START → [attraction, memory]（并行）→ hotel → Send fan-out × days
      → day_node × N（并行）→ merge_node → END
```

| 层 | 职责 |
|----|------|
| API 预处理 | 天气 / 城际交通 / 日期计算（不占图节点） |
| 确定性检索 | 高德 MCP 直连：景点多偏好召回 + 稳定 ID 去重 + 远郊标记 |
| 聚类分天 | 手写 K-Means（k-means++ 初始化）：每个 POI 只属于一天，跨天重复在结构上不可能发生；景点不足自动生成自由活动日 |
| 路径求解 | 贪心最近邻 + 2-opt + 时间窗硬检查（Haversine × 绕路系数，零 API 调用） |
| 酒店选址 | minimax 通勤打分（替代几何质心），远郊排除 + 住宿偏好过滤 |
| 分日并发 | LangGraph Send API 按 days 参数运行时 fan-out，N 天并行时延 ≈ 单天 |
| LLM 文案 | 每天一次（JSON mode），只写 description/transportation/tips；失败本地模板兜底 |
| 聚合 | 天气正则解析 / 三餐真实 POI / 本地预算 / 校验 → final_plan |

**韧性**：SQLite checkpoint 断点续传、LLM 指数退避、SSE 断开取消、MCP 超时保护、全链路 error_log 降级透明（计划永不中断）。

**记忆**：SQLite 租户隔离 + 频率加成 / IQR 异常检测的画像渐进构建（≥5 次行程才启用）。

## 快速启动

```bash
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# API Key（高德 + DeepSeek）
cp .env.example venv/.env && nano venv/.env

# 后端 :8000 + 前端 :5173
cd .. && bash start.sh
```

前端：`http://localhost:5173`（POST/SSE 双路径，默认真 SSE 流式）

## 测试

```bash
cd backend && ./venv/bin/python -m pytest tests -q
# 50 用例，无网络无 LLM（Fake 组件注入），基线一次捕获 5 个真实 bug
```

## 项目结构

```
backend/
  app/
    api/trip.py           # POST /api/trip + GET /api/trip/stream（真 SSE）
    graph/                # LangGraph 图：builder / nodes / state / context
    services/             # clustering（K-Means 分天）/ route_solver（路径）/ amap_service（MCP 池+缓存）/ llm_service
    tools/amap_wrapper.py # 高德 MCP 包装器（结构化候选 + 坐标增强）
    memory/               # 记忆：分类器 / 管理器 / SQLite 仓库
    agents/               # day_agent（单天文案，JSON mode）
  tests/                  # 50 用例（conftest 全 Fake 注入）
frontend/                 # Vue 3 单文件（SSE 流式进度 + 降级面板）
```

## 版本演进（面试叙事）

- **v1**（master）：ReAct 内循环，4 感知 Agent 共享 MCP 工具
- **v2**（preview）：attraction/hotel 改确定性检索节点，LLM 调用 3→1 次/请求
- **v3**（preview）：分日并行（Send fan-out）+ 数据层互斥 + 路径/选址本地化，LLM 只剩文案

git log 的迭代提交就是完整证据：`isolate requests → 结构化候选链路 → 分日并发重构`。
