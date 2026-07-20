#!/bin/bash
# 关闭 TripPlanner 后端 + 前端
BACKEND_PORT=8000
FRONTEND_PORT=5173

# 关闭后端
BACKEND_PID=$(lsof -ti:$BACKEND_PORT 2>/dev/null)
if [ -n "$BACKEND_PID" ]; then
    kill $BACKEND_PID
    echo "✅ 后端已关闭 (PID: $BACKEND_PID)"
else
    echo "⚠️  没有运行中的后端 (端口 $BACKEND_PORT)"
fi

# 关闭前端
FRONTEND_PID=$(lsof -ti:$FRONTEND_PORT 2>/dev/null)
if [ -n "$FRONTEND_PID" ]; then
    kill $FRONTEND_PID
    echo "✅ 前端已关闭 (PID: $FRONTEND_PID)"
else
    echo "⚠️  没有运行中的前端 (端口 $FRONTEND_PORT)"
fi
