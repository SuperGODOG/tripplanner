#!/bin/bash
# ==============================================================================
# TripPlanner 系统组件状态巡检脚本
# 检查项: Redis (:6379), FastAPI (:8000), Vite (:5173), SQLite 数据库, 孤儿进程
# 用法:
#   ./status.sh
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

echo -e "${BOLD}📊 TripPlanner 全组件运行状态巡检${NC}"
echo "════════════════════════════════════════════════════════════════"

# 1. Redis 巡检
echo -e "${BOLD}[1/4] ⚡ Redis 高速指纹缓存 (:6379)${NC}"
if command -v redis-cli >/dev/null 2>&1 && redis-cli ping 2>/dev/null | grep -q "PONG"; then
    REDIS_KEYS=$(redis-cli dbsize 2>/dev/null | awk '{print $1}')
    REDIS_MEM=$(redis-cli info memory 2>/dev/null | grep "used_memory_human:" | cut -d: -f2 | tr -d '\r')
    echo -e "  状态: ${GREEN}● 正常运行中${NC}"
    echo -e "  指标: 当前缓存键总数: ${GREEN}${REDIS_KEYS:-0}${NC} 个 | 内存占用: ${BLUE}${REDIS_MEM:-未知}${NC}"
else
    echo -e "  状态: ${RED}○ 未运行 / 离线${NC} (系统将降级为无缓存模式，规划速度较慢)"
fi
echo ""

# 2. 后端 FastAPI 巡检
echo -e "${BOLD}[2/4] 📡 后端 API 引擎 (:8000)${NC}"
BACKEND_PIDS=$(lsof -ti:$BACKEND_PORT 2>/dev/null || true)
if [ -n "$BACKEND_PIDS" ]; then
    HEALTH_RESP=$(curl -s -m 2 http://localhost:$BACKEND_PORT/health 2>/dev/null || true)
    if [[ "$HEALTH_RESP" == *"healthy"* ]]; then
        echo -e "  状态: ${GREEN}● 健康在线${NC} (PID: $(echo $BACKEND_PIDS | tr '\n' ' '))"
        echo -e "  自检: ${BLUE}GET /health -> $HEALTH_RESP${NC}"
        echo -e "  接口: http://localhost:$BACKEND_PORT | 文档: http://localhost:$BACKEND_PORT/docs"
    else
        echo -e "  状态: ${YELLOW}▲ 端口监听中但健康接口未响应${NC} (PID: $(echo $BACKEND_PIDS | tr '\n' ' '))"
    fi
else
    echo -e "  状态: ${RED}○ 未运行 (端口 $BACKEND_PORT 空闲)${NC}"
fi
echo ""

# 3. 前端 Vite 工作台巡检
echo -e "${BOLD}[3/4] 🌐 前端 Vite 工作台 (:5173)${NC}"
FRONTEND_PIDS=$(lsof -ti:$FRONTEND_PORT 2>/dev/null || true)
if [ -n "$FRONTEND_PIDS" ]; then
    echo -e "  状态: ${GREEN}● 正常运行中${NC} (PID: $(echo $FRONTEND_PIDS | tr '\n' ' '))"
    echo -e "  访问: ${GREEN}http://localhost:$FRONTEND_PORT${NC}"
else
    echo -e "  状态: ${RED}○ 未运行 (端口 $FRONTEND_PORT 空闲)${NC}"
fi
echo ""

# 4. 数据存储与持久化巡检
echo -e "${BOLD}[4/4] 💾 数据持久化与数据库环境${NC}"
DATA_DIR="$PROJECT_ROOT/data"
if [ -d "$DATA_DIR" ]; then
    DB_FILES=$(find "$DATA_DIR" -type f -name "*.db" 2>/dev/null || true)
    if [ -n "$DB_FILES" ]; then
        echo -e "  数据目录: ${GREEN}$DATA_DIR${NC}"
        for f in $DB_FILES; do
            SIZE=$(ls -lh "$f" | awk '{print $5}')
            echo -e "  - 数据库文件: $(basename "$f") (大小: $SIZE)"
        done
    else
        echo -e "  数据目录: ${GREEN}$DATA_DIR${NC} (目录已初始化就绪，数据库待首批会话自动写入)"
    fi
else
    echo -e "  数据目录: ${YELLOW}$DATA_DIR (尚未创建，将在首次启动时自动初始化)${NC}"
fi
echo ""

# 5. 孤儿进程巡检 (防电脑发烫)
echo -e "${BOLD}[附加] 🛡️ 异常与孤儿子进程检查${NC}"
ZOMBIE_UVX=$(pgrep -f "uvx amap-mcp-server" 2>/dev/null || true)
if [ -n "$ZOMBIE_UVX" ]; then
    echo -e "  ${YELLOW}⚠ 发现后台存在挂起的 MCP 解释器进程: PID $ZOMBIE_UVX (建议执行 ./stop.sh 清理)${NC}"
else
    echo -e "  ${GREEN}● 无挂起的 MCP 孤儿进程，系统负载健康${NC}"
fi
echo "════════════════════════════════════════════════════════════════"
