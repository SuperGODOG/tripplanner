.PHONY: help start stop stop-all restart status logs test benchmark chat clean build

help:
	@echo "TripPlanner 统一运维命令集:"
	@echo "  make start     - 一键启动 Redis + 后端 FastAPI + 前端 Vite 并自动打开浏览器"
	@echo "  make stop      - 优雅停止系统服务 (保留 Redis)"
	@echo "  make stop-all  - 彻底停止系统服务 (连同 Redis 一并停止)"
	@echo "  make restart   - 重启系统服务"
	@echo "  make status    - 查看全组件运行健康度与指标巡检看板"
	@echo "  make logs      - 实时跟踪前后端日志输出"
	@echo "  make test      - 运行全量 206 项自动化测试 (含 Harness 极端边界与容错测试)"
	@echo "  make benchmark - 运行 Harness vs LangGraph 自动化性能基准压测对比"
	@echo "  make build     - 构建前端生产包 (Vite Build)"
	@echo "  make chat      - 发起一次真实端到端对话规划请求"

start:
	@./start.sh

stop:
	@./stop.sh

stop-all:
	@./stop.sh --all

restart:
	@./stop.sh
	@./start.sh

status:
	@./status.sh

logs:
	@tail -f backend/server.log frontend/dev.log

test:
	@PYTHONPATH=backend .venv/bin/pytest backend/tests

benchmark:
	@PYTHONPATH=backend .venv/bin/python scripts/benchmark_comparison.py

build:
	@cd frontend && npm run build

chat:
	@curl -N -X POST http://localhost:8000/api/session/chat \
	  -H "Content-Type: application/json" \
	  -d '{"input_text": "我想去成都玩3天，2026-09-22出发，喜欢人文古迹和地道川菜，预算3000元"}'
