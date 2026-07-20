#!/bin/bash
# 启动 TripPlanner 后端 + 前端 Vue dev server
set -e

SCRIPT_DIR="$(dirname "$0")"
BACKEND_DIR="$SCRIPT_DIR"
FRONTEND_DIR="$SCRIPT_DIR/../frontend"
NPM="/home/caoruixin/.local/bin/npm"

BACKEND_PORT=8000
FRONTEND_PORT=5173

# ============================================================
# 启动后端
# ============================================================
echo "🔧 启动后端..."
cd "$BACKEND_DIR"
source venv/bin/activate

# 杀掉旧后端进程
kill $(lsof -ti:$BACKEND_PORT) 2>/dev/null || true

python run.py &
BACKEND_PID=$!
sleep 3

# 健康检查
if curl -s http://localhost:$BACKEND_PORT/health > /dev/null 2>&1; then
    echo "✅ 后端已启动: http://localhost:$BACKEND_PORT"
    echo "   📖 API 文档: http://localhost:$BACKEND_PORT/docs"
else
    echo "❌ 后端启动失败，查看日志"
fi

# ============================================================
# 启动前端
# ============================================================
echo ""
echo "🔧 启动前端 (Vue dev server)..."
cd "$FRONTEND_DIR"

# 杀掉旧前端进程
kill $(lsof -ti:$FRONTEND_PORT) 2>/dev/null || true

$NPM run dev &
FRONTEND_PID=$!
sleep 4

# 检查前端是否启动
if lsof -ti:$FRONTEND_PORT > /dev/null 2>&1; then
    echo "✅ 前端已启动: http://localhost:$FRONTEND_PORT"
else
    echo "❌ 前端启动失败，查看日志"
fi

# ============================================================
# 打开浏览器
# ============================================================
echo ""
echo "🌐 打开浏览器..."
xdg-open http://localhost:$FRONTEND_PORT 2>/dev/null || echo "   请手动打开 http://localhost:$FRONTEND_PORT"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  后端: http://localhost:$BACKEND_PORT"
echo "  前端: http://localhost:$FRONTEND_PORT"
echo "  关闭: bash $SCRIPT_DIR/stop.sh"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
