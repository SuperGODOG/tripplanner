#!/bin/bash
# TripPlanner 一键关闭 — 后端 :8000 + 前端 :5173
# 用法: bash stop.sh

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND_PORT=8000
FRONTEND_PORT=5173

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;36m'; NC='\033[0m'
info() { echo -e "${BLUE}▸${NC} $1"; }
ok()   { echo -e "${GREEN}✅${NC} $1"; }
warn() { echo -e "${YELLOW}⚠${NC}  $1"; }

_kill_port() {
    local port=$1 name=$2 pidfile=$3
    local pids
    pids=$(lsof -ti:$port 2>/dev/null)
    if [ -z "$pids" ]; then
        warn "$name 未运行（端口 $port 空闲）"
    else
        kill $pids 2>/dev/null
        sleep 0.3
        # SIGKILL 兜底
        local remain
        remain=$(lsof -ti:$port 2>/dev/null)
        [ -n "$remain" ] && kill -9 $remain 2>/dev/null
        ok "$name 已关闭 (PID: $(echo $pids | tr '\n' ' '))"
    fi
    [ -f "$pidfile" ] && rm -f "$pidfile"
}

_kill_port $BACKEND_PORT  "后端" "$PROJECT_ROOT/.backend.pid"
_kill_port $FRONTEND_PORT "前端" "$PROJECT_ROOT/.frontend.pid"

# vite dev 可能残余子进程（esbuild、chokidar 等），兜底清理
if pkill -f "vite.*dev" 2>/dev/null; then
    ok "清理 vite 残余子进程"
fi
if pkill -f "uvx amap-mcp-server" 2>/dev/null; then
    ok "清理 amap-mcp-server 子进程"
fi
