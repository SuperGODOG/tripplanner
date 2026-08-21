# TripPlanner Project

## Environment

- **conda 劫持 git/npm/pip**，需用完整路径绕过：
  - `/usr/bin/git -c http.proxy=http://127.0.0.1:7897 push`
  - `/home/caoruixin/.local/bin/npm --registry https://registry.npmmirror.com`
  - `python -m pip -i https://pypi.tuna.tsinghua.edu.cn/simple`
- **API Key**: 放在 `venv/.env`（gitignored），`config.py` 通过 `env_file` 读取
- **端口**: 后端 `:8000`，前端 `:5173`
- **高德 API**: geo 返回 `"lng,lat"` 格式，`maps_distance` 也统一用 `"lng,lat"`

## Architecture

- **v3 分日并发拓扑** (2026-08-21): `START → [attraction, memory] → hotel → _fan_out(Send×days) → day_node × N → merge_node → END`
  - 全图**无回环**（v2 retry_planner 已删）——景点集合/顺序/预算全部本地确定，硬伤在结构上不可能由 LLM 引入
  - `attraction`/`hotel` 确定性检索节点（`AmapToolWrapper.search_pois` 直连，无 LLM）；`attraction` 检索后 **K-Means 聚簇分天**（`services/clustering.py`，每 POI 只属一天，跨天重复结构上不可能；远郊日/自由活动日边界）
  - `_fan_out` 用 **Send API** 按 days 运行时 fan-out（`langgraph.types.Send`）；**Send 分支 state 只含 payload**——共享上下文必须显式注入；多分支汇聚到 merge_node **只触发 1 次**（与跨 superstep fan-in 双触发是不同语义，实测确认）
  - `day_node`：本地路径求解（`services/route_solver.py` 贪心+2-opt+时间窗，Haversine×1.4）+ 单天文案 LLM（JSON mode，失败本地模板兜底，leisure 天零 LLM）
  - `merge_node`：聚合 + 天气正则解析 + 全程酒店 + 三餐真实 POI + 本地预算 + 校验
  - 酒店：**城市中心 geocode 搜索（10km）+ minimax 通勤选址**（`_select_hotel`，替代几何质心——center_*/urban_* 字段已删）
  - 记忆纯本地 SQLite 读（ms 级），与 attraction 并行；memory 结果经共享 state 传递（无 join 边）
- **全局 MCP 并发闸**: `amap_service.get_mcp_executor()` 单例池 max_workers=10，所有高德调用统一经 `run_mcp()`（只提交叶子任务，防死锁）；`geo_cached` LRU(256) 三处共用
- **结构化候选链路** (2026-08-21): `PoiCandidate`/`HotelCandidate` 字段化传递（坐标/来源/价格），不再经过 Markdown/📍 正则/LLM 转发；多偏好全量召回 + 稳定 ID 去重；远郊（>80km）标记 `excursion` 一日游不删除；三餐由 `_enrich_meals` 用景点周边 500m 真实美食 POI 填充
- **Thick Node 原则**: 每个 Node 独立完成「搜索 → 增强 → 计算」闭环，不是薄 API 转接头
  - 数据增强归 Node（Wrapper 接入 Agent 坐标增强）
  - 纯工程计算（城际交通、日期）放 API 层预处理
- **无锁并发**: `MCPTool.run()` 每次调用内部新建独立 event loop + MCPClient 连接，无共享 mutable state；`error_log: Annotated[list, add]` reducer 自动合并 —— 并发均无需应用层 Lock
- **断点续传**: SqliteSaver 持久化 `data/checkpoints.db`（`open_trip_graph()` 返回 (graph, conn)，调用方 finally 必须 conn.close()）；thread_id 由 RequestContext 每次生成 uuid4——机制在但请求间不可续传（已知缺口）
- **前端**: POST 替代 SSE 的历史已废弃（真 SSE 流式）；Vue 3 单文件，无 UI/动画库依赖

## Branch Workflow

- 实验性改动先在 `preview` 分支做，验证通过再合 `master`
- 主分支始终保持可运行状态
- 讨论架构时偏好多 subagent 并行出方案再对比

## Design Principles

- 统计方法优于任意阈值（标准差法而非简单倍数，IQR 用于记忆异常检测）
- 本地计算优于 LLM（日期、中心点、校验）
- State 传递混合策略: LLM 原始输出（全文）+ 节点本地提取（结构化数据）并存
- 文档必须与代码同步更新

## UX Design

- 降级/fallback 必须在每一层透明可见（前端展示降级列表，非单一横幅）
- 用户画像从零渐进构建（trip_count 计数，≥5 次才显示），不接受预设默认值
- 会主动质疑架构决策，偏好务实而非过度设计
