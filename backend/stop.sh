#!/bin/bash
# 关闭 TripPlanner
PORT=8000
PID=$(lsof -ti:$PORT 2>/dev/null)
if [ -n "$PID" ]; then
    kill $PID
    echo "✅ TripPlanner 已关闭 (PID: $PID)"
else
    echo "⚠️  没有运行中的 TripPlanner"
fi
