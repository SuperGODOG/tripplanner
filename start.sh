#!/bin/bash
# TripPlanner 一键启动 — 后端 (FastAPI :8000) + 前端 (Vite Dev :5173)
# 用法:   bash start.sh
# 关闭:   bash stop.sh
# 日志:   backend/server.log · frontend/dev.log

set -e
PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend"
FRONTEND_DIR="$PROJECT_ROOT/frontend"
NPM="/home/caoruixin/.local/bin/npm"     # 绕过 conda 劫持
BACKEND_PORT=8000
FRONTEND_PORT=5173
BACKEND_LOG="$BACKEND_DIR/server.log"
FRONTEND_LOG="$FRONTEND_DIR/dev.log"

# ── 彩色输出 ──
GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; BLUE='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${BLUE}▸${NC} $1"; }
ok()    { echo -e "${GREEN}✅${NC} $1"; }
warn()  { echo -e "${YELLOW}⚠${NC}  $1"; }
fail()  { echo -e "${RED}❌${NC} $1"; }

# ── 清理已占用端口（防止重复启动叠加） ──
info "预清理已占用端口..."
kill $(lsof -ti:$BACKEND_PORT)  2>/dev/null || true
kill $(lsof -ti:$FRONTEND_PORT) 2>/dev/null || true
sleep 0.3

# ══════════════════════════════════════════════
# 后端
# ══════════════════════════════════════════════
info "启动后端 FastAPI on :$BACKEND_PORT"
if [ ! -f "$BACKEND_DIR/venv/bin/python" ]; then
    fail "venv 不存在: $BACKEND_DIR/venv"
    echo "   先跑: cd backend && python3 -m venv venv && ./venv/bin/pip install -r requirements.txt"
    exit 1
fi

cd "$BACKEND_DIR"
nohup ./venv/bin/python run.py > "$BACKEND_LOG" 2>&1 &
BACKEND_PID=$!
echo $BACKEND_PID > "$PROJECT_ROOT/.backend.pid"

# 健康检查 retry（最多 15s，用 /docs 因为 FastAPI 自动挂）
for i in $(seq 1 15); do
    if curl -sf http://localhost:$BACKEND_PORT/docs > /dev/null 2>&1; then
        ok "后端 http://localhost:$BACKEND_PORT  (PID=$BACKEND_PID)"
        break
    fi
    if [ $i -eq 15 ]; then
        fail "后端 15s 内未响应，尾部日志："
        tail -8 "$BACKEND_LOG"
        exit 1
    fi
    sleep 1
done

# ══════════════════════════════════════════════
# 前端
# ══════════════════════════════════════════════
info "启动前端 Vite Dev on :$FRONTEND_PORT"
cd "$FRONTEND_DIR"
if [ ! -d "node_modules" ]; then
    warn "node_modules 缺失，先跑 npm install..."
    "$NPM" install
fi

nohup "$NPM" run dev > "$FRONTEND_LOG" 2>&1 &
FRONTEND_PID=$!
echo $FRONTEND_PID > "$PROJECT_ROOT/.frontend.pid"

for i in $(seq 1 15); do
    if lsof -ti:$FRONTEND_PORT > /dev/null 2>&1; then
        ok "前端 http://localhost:$FRONTEND_PORT  (PID=$FRONTEND_PID)"
        break
    fi
    if [ $i -eq 15 ]; then
        fail "前端 15s 内未监听端口，尾部日志："
        tail -8 "$FRONTEND_LOG"
        exit 1
    fi
    sleep 1
done

# ══════════════════════════════════════════════
# 完成
# ══════════════════════════════════════════════
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "  🌐 前端      ${GREEN}http://localhost:$FRONTEND_PORT${NC}"
echo -e "  📡 后端      ${GREEN}http://localhost:$BACKEND_PORT${NC}"
echo -e "  📄 API 文档  ${BLUE}http://localhost:$BACKEND_PORT/docs${NC}"
echo -e "  📜 日志      $BACKEND_LOG  |  $FRONTEND_LOG"
echo -e "  🛑 关闭      ${YELLOW}bash stop.sh${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

xdg-open http://localhost:$FRONTEND_PORT 2>/dev/null || true
