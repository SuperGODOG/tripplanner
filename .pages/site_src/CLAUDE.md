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

- **4 Node 图**: `attraction → hotel → memory → planner`（天气已移入 API 层预处理）
- **Thick Node 原则**: 每个 Node 独立完成「搜索 → 增强 → 计算」闭环，不是薄 API 转接头
  - 数据增强归 Node（Wrapper 接入 Agent 坐标增强）
  - 纯工程计算（城际交通、日期）放 API 层预处理
- **离群检测**: 标准差法 1.5σ + 80km 硬上限
- **酒店回环检测**: ≤2 次
- **前端**: POST 替代 SSE

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
