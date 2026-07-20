#!/bin/bash
# 启动 TripPlanner 后端 + 打开前端
cd "$(dirname "$0")"
source venv/bin/activate

PORT=8000

# 杀掉旧进程
kill $(lsof -ti:$PORT) 2>/dev/null

echo "🚀 启动 TripPlanner..."
python run.py &
sleep 3

# 健康检查
if curl -s http://localhost:$PORT/health > /dev/null 2>&1; then
    echo "✅ 服务已启动: http://localhost:$PORT"
    echo "📱 前端界面: http://localhost:$PORT/app/"
    echo "📖 API 文档: http://localhost:$PORT/docs"
    # 尝试打开浏览器
    xdg-open http://localhost:$PORT/app/ 2>/dev/null || echo "   请手动打开浏览器"
else
    echo "❌ 启动失败，查看日志"
fi
