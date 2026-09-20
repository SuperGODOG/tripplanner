#!/bin/bash
# ==============================================================================
# TripPlanner 一键停止管理脚本
# 支持组件: FastAPI 后端 (:8000) + Vite 前端 (:5173) + 孤儿子进程清理 + 可选 Redis (:6379)
# 用法:
#   ./stop.sh             # 默认关闭后端与前端，保留系统 Redis 共享服务
#   ./stop.sh --all       # 关闭后端、前端，并一并关闭 Redis 服务
#   ./stop.sh --clean     # 关闭并清理日志文件 (server.log, dev.log)
# ==============================================================================

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND_PORT=8000
FRONTEND_PORT=5173
REDIS_PORT=6379

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;36m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

info() { echo -e "${BLUE}▸${NC} $1"; }
ok()   { echo -e "${GREEN}✅${NC} $1"; }
warn() { echo -e "${YELLOW}⚠${NC}  $1"; }
fail() { echo -e "${RED}❌${NC} $1"; }

STOP_REDIS=false
CLEAN_LOGS=false

for arg in "$@"; do
    case "$arg" in
        --all|-a|--with-redis|-r)
            STOP_REDIS=true
            ;;
        --clean|-c)
            CLEAN_LOGS=true
            ;;
        --help|-h)
            echo "用法: $0 [选项]"
            echo "  --all, -a, -r    一并关闭 Redis 缓存服务（默认保留以防影响系统其他项目）"
            echo "  --clean, -c      关闭系统并清空日志文件 (backend/server.log, frontend/dev.log)"
            echo "  --help, -h       显示帮助信息"
            exit 0
            ;;
    esac
done

echo -e "${BOLD}🛑 正在关闭 TripPlanner 系统服务...${NC}"
echo "───────────────────────────────────────────"

_kill_by_port_and_pidfile() {
    local port=$1
    local name=$2
    local pidfile=$3

    local pids
    pids=$(lsof -ti:$port 2>/dev/null || true)

    if [ -z "$pids" ]; then
        if [ -f "$pidfile" ]; then
            local file_pid
            file_pid=$(cat "$pidfile" 2>/dev/null || true)
            if [ -n "$file_pid" ] && kill -0 "$file_pid" 2>/dev/null; then
                kill "$file_pid" 2>/dev/null || true
                sleep 0.5
                kill -9 "$file_pid" 2>/dev/null || true
                ok "$name 已通过 PID 文件正常停止 (PID: $file_pid)"
            fi
            rm -f "$pidfile"
        fi
        info "$name 未运行（端口 $port 空闲）"
    else
        # 1. 优雅 SIGTERM (允许 FastAPI/SQLite 提交数据)
        kill $pids 2>/dev/null || true
        sleep 0.8
        
        # 2. 检查残留并 SIGKILL 兜底
        local remain
        remain=$(lsof -ti:$port 2>/dev/null || true)
        if [ -n "$remain" ]; then
            kill -9 $remain 2>/dev/null || true
        fi
        ok "$name 已成功关闭 (已释放端口 $port)"
        [ -f "$pidfile" ] && rm -f "$pidfile"
    fi
}

# 1. 关闭后端
_kill_by_port_and_pidfile $BACKEND_PORT "后端 FastAPI" "$PROJECT_ROOT/.backend.pid"

# 2. 关闭前端
_kill_by_port_and_pidfile $FRONTEND_PORT "前端 Vite" "$PROJECT_ROOT/.frontend.pid"

# 3. 清理残余孤儿子进程与僵尸任务 (防 CPU 耗电与发热)
info "正在清理可能残留的开发构建、uvicorn 孤儿子进程与 MCP 子进程..."
pkill -f "uvicorn.*app.api.main:app" 2>/dev/null && ok "已清理残留的 uvicorn 进程" || true
pkill -f "vite.*dev" 2>/dev/null && ok "已清理残留的 vite 构建进程" || true
pkill -f "uvx amap-mcp-server" 2>/dev/null && ok "已清理残留的 amap-mcp-server 解释器" || true
pkill -f "esbuild.*service" 2>/dev/null && ok "已清理残留的 esbuild 编译服务" || true

# 4. 可选关闭 Redis
if [ "$STOP_REDIS" = true ]; then
    info "正在关闭 Redis 缓存服务 (:6379)..."
    if command -v brew >/dev/null 2>&1 && brew services list 2>/dev/null | grep -q "redis.*started"; then
        brew services stop redis >/dev/null 2>&1 || true
        ok "Redis 服务已通过 brew services 安全停止"
    elif command -v redis-cli >/dev/null 2>&1; then
        redis-cli shutdown nosave 2>/dev/null || true
        ok "Redis 服务已通过 redis-cli shutdown 安全停止"
    else
        warn "未找到受管的 Redis 进程"
    fi
else
    info "保留 Redis 缓存服务在后台运行（如需一并关闭请使用: ./stop.sh --all）"
fi

# 5. 可选清理日志
if [ "$CLEAN_LOGS" = true ]; then
    info "正在清空日志文件..."
    [ -f "$PROJECT_ROOT/backend/server.log" ] && : > "$PROJECT_ROOT/backend/server.log"
    [ -f "$PROJECT_ROOT/frontend/dev.log" ] && : > "$PROJECT_ROOT/frontend/dev.log"
    ok "日志文件已清空"
fi

echo "───────────────────────────────────────────"
ok "TripPlanner 服务已全部安全终止。"
