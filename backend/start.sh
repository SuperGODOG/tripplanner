#!/bin/bash
# 启动 TripPlanner 后端 + 前端 Vue dev server
set -e
SCRIPT_DIR="$(dirname "$0")"
BACKEND_DIR="$SCRIPT_DIR"
FRONTEND_DIR="$SCRIPT_DIR/../frontend"
NPM="/home/caoruixin/.local/bin/npm"
BACKEND_PORT=8000
FRONTEND_PORT=5173

echo "🔧 启动后端..."
cd "$BACKEND_DIR"
source venv/bin/activate
kill $(lsof -ti:$BACKEND_PORT) 2>/dev/null || true
python run.py &
sleep 4
if curl -s http://localhost:$BACKEND_PORT/health > /dev/null 2>&1; then
    echo "✅ 后端: http://localhost:$BACKEND_PORT"
else
    echo "❌ 后端启动失败"
fi

echo ""
echo "🔧 启动前端..."
cd "$FRONTEND_DIR"
kill $(lsof -ti:$FRONTEND_PORT) 2>/dev/null || true
$NPM run dev &
sleep 4
if lsof -ti:$FRONTEND_PORT > /dev/null 2>&1; then
    echo "✅ 前端: http://localhost:$FRONTEND_PORT"
    xdg-open http://localhost:$FRONTEND_PORT 2>/dev/null || true
else
    echo "❌ 前端启动失败"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  后端: http://localhost:$BACKEND_PORT"
echo "  前端: http://localhost:$FRONTEND_PORT"
echo "  关闭: bash $SCRIPT_DIR/stop.sh"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
