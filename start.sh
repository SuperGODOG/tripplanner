#!/bin/bash
# ==============================================================================
# TripPlanner 一键启动管理脚本
# 支持组件: Redis 缓存 (:6379) + FastAPI 后端 (:8000) + Vite 前端 (:5173) + SQLite 存储
# 兼容平台: macOS / Linux
# 用法:
#   ./start.sh              # 默认全量启动
#   ./start.sh --backend    # 仅启动后端与 Redis
#   ./start.sh --status     # 仅查看各组件运行状态
#   ./start.sh --no-open    # 启动后不自动打开浏览器
# ==============================================================================

set -e

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend"
FRONTEND_DIR="$PROJECT_ROOT/frontend"
DATA_DIR="$PROJECT_ROOT/data"
BACKEND_PORT=8000
FRONTEND_PORT=5173
REDIS_PORT=6379

BACKEND_LOG="$BACKEND_DIR/server.log"
FRONTEND_LOG="$FRONTEND_DIR/dev.log"

# ── 彩色终端样式 ──
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${BLUE}▸${NC} $1"; }
ok()    { echo -e "${GREEN}✅${NC} $1"; }
warn()  { echo -e "${YELLOW}⚠${NC}  $1"; }
fail()  { echo -e "${RED}❌${NC} $1"; }

# ── 参数解析 ──
ONLY_BACKEND=false
NO_OPEN=false
CHECK_STATUS_ONLY=false

for arg in "$@"; do
    case "$arg" in
        --backend|-b)
            ONLY_BACKEND=true
            ;;
        --no-open)
            NO_OPEN=true
            ;;
        --status|-s)
            CHECK_STATUS_ONLY=true
            ;;
        --help|-h)
            echo "用法: $0 [选项]"
            echo "  --backend, -b   仅启动 Redis 与后端 FastAPI 服务"
            echo "  --status, -s    查看当前各组件运行状态"
            echo "  --no-open       启动后不自动打开默认浏览器"
            echo "  --help, -h      显示帮助信息"
            exit 0
            ;;
    esac
done

# ══════════════════════════════════════════════
# 状态检查模式 (--status)
# ══════════════════════════════════════════════
if [ "$CHECK_STATUS_ONLY" = true ]; then
    if [ -f "$PROJECT_ROOT/status.sh" ]; then
        bash "$PROJECT_ROOT/status.sh"
    else
        echo "正在检查系统组件状态..."
        lsof -i :$REDIS_PORT || true
        lsof -i :$BACKEND_PORT || true
        lsof -i :$FRONTEND_PORT || true
    fi
    exit 0
fi

echo -e "${BOLD}🚀 正在启动 TripPlanner 智能旅行系统...${NC}"
echo "───────────────────────────────────────────"

# ══════════════════════════════════════════════
# 1. 环境依赖自检与路径推断
# ══════════════════════════════════════════════
# 探测 Python
PYTHON=""
if [ -f "$PROJECT_ROOT/.venv/bin/python" ]; then
    PYTHON="$PROJECT_ROOT/.venv/bin/python"
elif [ -f "$BACKEND_DIR/venv/bin/python" ]; then
    PYTHON="$BACKEND_DIR/venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON="$(command -v python3)"
else
    fail "未找到有效的 Python 运行环境！请在根目录创建虚拟环境：python3 -m venv .venv"
    exit 1
fi

# 探测 npm
NPM=""
if command -v npm >/dev/null 2>&1; then
    NPM="$(command -v npm)"
elif [ -f "/opt/homebrew/bin/npm" ]; then
    NPM="/opt/homebrew/bin/npm"
elif [ -f "/usr/local/bin/npm" ]; then
    NPM="/usr/local/bin/npm"
fi

if [ "$ONLY_BACKEND" = false ] && [ -z "$NPM" ]; then
    fail "未找到 npm 可执行程序！请安装 Node.js (推荐通过 brew install node)"
    exit 1
fi

# 检查 .env 配置文件
if [ ! -f "$PROJECT_ROOT/.env" ] && [ ! -f "$BACKEND_DIR/.env" ]; then
    warn "未检测到 .env 配置文件！"
    if [ -f "$BACKEND_DIR/.env.example" ]; then
        info "正在自动从 backend/.env.example 生成 backend/.env 模板..."
        cp "$BACKEND_DIR/.env.example" "$BACKEND_DIR/.env"
        warn "请注意：请在 backend/.env 中填入有效的 LLM_API_KEY 与 AMAP_API_KEY 以开启完整大模型规划功能"
    fi
fi

# 确保数据持久化目录存在
mkdir -p "$DATA_DIR"

# ══════════════════════════════════════════════
# 2. Redis 内存缓存组件管理 (:6379)
# ══════════════════════════════════════════════
info "检查 Redis 缓存服务 (:6379)..."
REDIS_READY=false

if command -v redis-cli >/dev/null 2>&1 && redis-cli ping 2>/dev/null | grep -q "PONG"; then
    REDIS_READY=true
    ok "Redis 缓存服务已在运行 (:6379)"
else
    info "Redis 未运行，尝试自动拉起..."
    if command -v brew >/dev/null 2>&1 && brew services list 2>/dev/null | grep -q "redis"; then
        brew services start redis >/dev/null 2>&1 || true
    elif command -v redis-server >/dev/null 2>&1; then
        redis-server --daemonize yes >/dev/null 2>&1 || true
    fi

    for i in $(seq 1 5); do
        if command -v redis-cli >/dev/null 2>&1 && redis-cli ping 2>/dev/null | grep -q "PONG"; then
            REDIS_READY=true
            ok "Redis 缓存服务启动成功 (:6379)"
            break
        fi
        sleep 0.5
    done
fi

if [ "$REDIS_READY" = false ]; then
    warn "Redis 未能自动启动，系统将降级为无缓存模式（推荐安装并启动 Redis 以获得 7000x 加速与防发烫保护）"
fi

# ══════════════════════════════════════════════
# 3. 端口预清理 (防止僵尸进程叠加)
# ══════════════════════════════════════════════
info "清理残留端口与进程..."
OLD_BACKEND_PIDS=$(lsof -ti:$BACKEND_PORT 2>/dev/null || true)
if [ -n "$OLD_BACKEND_PIDS" ]; then
    kill -9 $OLD_BACKEND_PIDS 2>/dev/null || true
fi

if [ "$ONLY_BACKEND" = false ]; then
    OLD_FRONTEND_PIDS=$(lsof -ti:$FRONTEND_PORT 2>/dev/null || true)
    if [ -n "$OLD_FRONTEND_PIDS" ]; then
        kill -9 $OLD_FRONTEND_PIDS 2>/dev/null || true
    fi
fi
sleep 0.3

# ══════════════════════════════════════════════
# 4. 启动后端 FastAPI 引擎 (:8000)
# ══════════════════════════════════════════════
info "启动后端 FastAPI 引擎 on :$BACKEND_PORT..."
cd "$PROJECT_ROOT"

BACKEND_PID=$("$PYTHON" -c "
import os, subprocess
p = subprocess.Popen(
    ['$PYTHON', '-m', 'uvicorn', 'app.api.main:app', '--host', '0.0.0.0', '--port', '$BACKEND_PORT', '--reload'],
    cwd='$PROJECT_ROOT',
    env=dict(os.environ, PYTHONPATH='$BACKEND_DIR'),
    stdin=subprocess.DEVNULL,
    stdout=open('$BACKEND_LOG', 'w'),
    stderr=subprocess.STDOUT,
    start_new_session=True
)
print(p.pid)
")
echo "$BACKEND_PID" > "$PROJECT_ROOT/.backend.pid"

# 健康检查轮询
BACKEND_ONLINE=false
for i in $(seq 1 15); do
    if curl -sf http://localhost:$BACKEND_PORT/health > /dev/null 2>&1; then
        BACKEND_ONLINE=true
        ok "后端服务就绪: http://localhost:$BACKEND_PORT (PID=$BACKEND_PID)"
        break
    fi
    sleep 0.8
done

if [ "$BACKEND_ONLINE" = false ]; then
    fail "后端服务在 12 秒内未就绪，尾部日志如下："
    tail -n 12 "$BACKEND_LOG"
    exit 1
fi

# ══════════════════════════════════════════════
# 5. 启动前端 Vite 工作台 (:5173)
# ══════════════════════════════════════════════
if [ "$ONLY_BACKEND" = false ]; then
    info "启动前端 Vite 工作台 on :$FRONTEND_PORT..."
    cd "$FRONTEND_DIR"
    if [ ! -d "node_modules" ]; then
        warn "检测到 node_modules 缺失，正在自动执行 npm install..."
        "$NPM" install
    fi

    FRONTEND_PID=$("$PYTHON" -c "
import subprocess
p = subprocess.Popen(
    ['$NPM', 'run', 'dev'],
    cwd='$FRONTEND_DIR',
    stdin=subprocess.DEVNULL,
    stdout=open('$FRONTEND_LOG', 'w'),
    stderr=subprocess.STDOUT,
    start_new_session=True
)
print(p.pid)
")
    echo "$FRONTEND_PID" > "$PROJECT_ROOT/.frontend.pid"

    FRONTEND_ONLINE=false
    for i in $(seq 1 15); do
        if lsof -ti:$FRONTEND_PORT > /dev/null 2>&1; then
            FRONTEND_ONLINE=true
            ok "前端工作台就绪: http://localhost:$FRONTEND_PORT (PID=$FRONTEND_PID)"
            break
        fi
        sleep 0.8
    done

    if [ "$FRONTEND_ONLINE" = false ]; then
        fail "前端工作台在 12 秒内未能启动监听，尾部日志如下："
        tail -n 12 "$FRONTEND_LOG"
        exit 1
    fi
fi

# ══════════════════════════════════════════════
# 6. 完成面板与浏览器自动打开
# ══════════════════════════════════════════════
echo ""
echo -e "${BOLD}══════════════════════════════════════════════════${NC}"
echo -e "  🎉 ${GREEN}${BOLD}TripPlanner 智能旅行系统全部就绪！${NC}"
echo -e "──────────────────────────────────────────────────"
if [ "$ONLY_BACKEND" = false ]; then
echo -e "  🌐 ${BOLD}前端用户端${NC}   ${GREEN}http://localhost:$FRONTEND_PORT${NC}"
fi
echo -e "  📡 ${BOLD}后端 API${NC}     ${GREEN}http://localhost:$BACKEND_PORT${NC}"
echo -e "  🩺 ${BOLD}健康自检${NC}     ${BLUE}http://localhost:$BACKEND_PORT/health${NC}"
echo -e "  📄 ${BOLD}Swagger 文档${NC} ${BLUE}http://localhost:$BACKEND_PORT/docs${NC}"
echo -e "  ⚡ ${BOLD}Redis 缓存${NC}   $([ "$REDIS_READY" = true ] && echo -e "${GREEN}在线 (localhost:$REDIS_PORT)${NC}" || echo -e "${YELLOW}离线 (降级运行)${NC}")"
echo -e "  💾 ${BOLD}数据存储${NC}     $DATA_DIR"
echo -e "  📜 ${BOLD}运行日志${NC}     $BACKEND_LOG"
if [ "$ONLY_BACKEND" = false ]; then
echo -e "                   $FRONTEND_LOG"
fi
echo -e "──────────────────────────────────────────────────"
echo -e "  🛑 ${BOLD}关闭系统指令${NC} ${YELLOW}./stop.sh${NC} (或 ./stop.sh --all)"
echo -e "  📊 ${BOLD}状态查看指令${NC} ${BLUE}./status.sh${NC}"
echo -e "${BOLD}══════════════════════════════════════════════════${NC}"

# 唤起浏览器
if [ "$ONLY_BACKEND" = false ] && [ "$NO_OPEN" = false ]; then
    if command -v open >/dev/null 2>&1; then
        open "http://localhost:$FRONTEND_PORT" 2>/dev/null || true
    elif command -v xdg-open >/dev/null 2>&1; then
        xdg-open "http://localhost:$FRONTEND_PORT" 2>/dev/null || true
    fi
fi
