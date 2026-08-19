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

- **4 Node 图 + fan-out 拓扑** (2026-08-21 更新): `START → [attraction, memory] → hotel → planner`
  - `attraction`/`hotel` 是确定性检索节点（`AmapToolWrapper.search_pois` 直连，无 LLM），只留 `planner` 一个 LLM 节点
  - `memory` 与 `attraction` 并行入口（memory 纯本地 SQLite 读，不阻塞 LLM+MCP 长任务）
  - **无 join 边**：LangGraph 1.2.9 跨 superstep fan-in 是"每条入边各触发一次"而非 join，planner 若挂两条入边会被执行两次（LLM 调用双倍，实测确认）。memory 结果经共享 state 传递，planner 只挂 hotel 单入边
  - 天气 + 城际交通已移入 API 层预处理（`_fetch_weather ∥ _compute_intercity` 也并发提交）
- **结构化候选链路** (2026-08-21): `PoiCandidate`/`HotelCandidate` 字段化传递（坐标/来源/价格），不再经过 Markdown/📍 正则/LLM 转发；多偏好全量召回 + 稳定 ID 去重；远郊（>80km）标记 `excursion` 一日游不删除，酒店选址用市区质心（`urban_lng/lat`）；三餐由 `_enrich_meals` 用景点周边 500m 真实美食 POI 填充
- **Thick Node 原则**: 每个 Node 独立完成「搜索 → 增强 → 计算」闭环，不是薄 API 转接头
  - 数据增强归 Node（Wrapper 接入 Agent 坐标增强）
  - 纯工程计算（城际交通、日期）放 API 层预处理
- **无锁并发**: `MCPTool.run()` 每次调用内部新建独立 event loop + MCPClient 连接，无共享 mutable state；`error_log: Annotated[list, add]` reducer 自动合并 —— 三处并发（API 层双任务 / maps_geo 双查 / 图内 fan-out）均无需应用层 Lock
- **离群检测**: 标准差法 1.5σ + 80km 硬上限
- **酒店回环检测**: ≤2 次
- **前端**: POST 替代 SSE；Vue 3 单文件，无 UI/动画库依赖

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
