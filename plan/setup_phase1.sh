#!/bin/bash
# Phase 1 环境搭建脚本
# 用法: bash setup_phase1.sh

set -e

PROJECT_DIR="/home/caoruixin/projects/tripplanner/backend"

echo "========================================"
echo " Phase 1: TripPlanner 环境搭建"
echo "========================================"

# ---------- Step 1: 目录结构 ----------
echo ""
echo "[1/5] 创建项目目录结构..."

mkdir -p "$PROJECT_DIR"/app/{agents,services,tools,models,api,graph,memory}
mkdir -p "$PROJECT_DIR"/data

# 给每个包目录放 __init__.py
for dir in app app/agents app/services app/tools app/models app/api app/graph app/memory; do
    touch "$PROJECT_DIR/$dir/__init__.py"
done

echo "  ✅ 目录结构创建完成"
echo ""
echo "  目录树:"
echo "  backend/"
echo "  ├── app/"
echo "  │   ├── __init__.py"
echo "  │   ├── agents/__init__.py"
echo "  │   ├── services/__init__.py"
echo "  │   ├── tools/__init__.py"
echo "  │   ├── models/__init__.py"
echo "  │   ├── api/__init__.py"
echo "  │   ├── graph/__init__.py"
echo "  │   └── memory/__init__.py"
echo "  └── data/         (记忆持久化文件)"

# ---------- Step 2: Python 虚拟环境 ----------
echo ""
echo "[2/5] 创建 Python 虚拟环境..."

cd "$PROJECT_DIR"

if [ -d "venv" ]; then
    echo "  ⚠️  venv 已存在，跳过创建"
else
    python3 -m venv venv
    echo "  ✅ venv 创建完成"
fi

# 激活并验证
source venv/bin/activate
echo "  Python 路径: $(which python)"
echo "  Python 版本: $(python --version)"

# ---------- Step 3: 依赖安装 ----------
echo ""
echo "[3/5] 安装依赖..."

# 先升级 pip
pip install --quiet --upgrade pip

# 安装依赖
pip install --quiet \
    "hello-agents[protocols]>=0.2.4,<=0.2.9" \
    "fastapi>=0.115.0" \
    "uvicorn[standard]>=0.32.0" \
    "pydantic>=2.0.0" \
    "pydantic-settings>=2.0.0" \
    "httpx>=0.27.0" \
    "python-dotenv>=1.0.0" \
    "python-multipart>=0.0.9" \
    "loguru>=0.7.0" \
    "fastmcp>=2.0.0" \
    "uv>=0.8.0" \
    "python-dateutil>=2.8.2" \
    "langgraph>=0.2.0" \
    "langgraph-checkpoint>=2.0.0"

echo "  ✅ 依赖安装完成"

# ---------- Step 4: 配置文件 ----------
echo ""
echo "[4/5] 创建配置文件..."

# .env.example（模板，可提交 Git）
cat > "$PROJECT_DIR/.env.example" << 'EOF'
# DeepSeek
LLM_API_KEY=your_deepseek_api_key_here
LLM_MODEL_ID=deepseek-chat
LLM_BASE_URL=https://api.deepseek.com/v1

# 高德地图 Web服务 Key
AMAP_API_KEY=your_amap_web_service_key_here

# 服务
HOST=0.0.0.0
PORT=8000
EOF

# .env（真实配置，不提交 Git）
if [ ! -f "$PROJECT_DIR/.env" ]; then
    cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
    echo "  ✅ .env 已创建（请编辑填入真实 API Key）"
    echo ""
    echo "  ⚠️  重要: 请执行以下命令编辑 .env 文件:"
    echo "     nano $PROJECT_DIR/.env"
    echo "     或在 VSCode 中打开并填入你的 DeepSeek 和高德 Key"
else
    echo "  ⚠️  .env 已存在，跳过"
fi

# config.py
cat > "$PROJECT_DIR/app/config.py" << 'EOF'
"""应用配置管理"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # LLM 配置
    llm_api_key: str
    llm_model_id: str = "deepseek-chat"
    llm_base_url: str = "https://api.deepseek.com/v1"

    # 高德地图
    amap_api_key: str

    # 服务配置
    host: str = "0.0.0.0"
    port: int = 8000
    app_name: str = "TripPlanner"
    app_version: str = "1.0.0"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
EOF

echo "  ✅ 配置文件创建完成"

# ---------- Step 5: 验证 MCP 连接 ----------
echo ""
echo "[5/5] 验证 MCP 连接..."

# 先检查 API Key 是否已设置
if grep -q "your_deepseek_api_key_here" "$PROJECT_DIR/.env" 2>/dev/null; then
    echo ""
    echo "  ⚠️  检测到 .env 中还是默认占位符，请先填入 API Key"
    echo "  编辑: nano $PROJECT_DIR/.env"
    echo ""
    echo "  然后手动运行验证:"
    echo "    cd $PROJECT_DIR"
    echo "    source venv/bin/activate"
    echo "    python test_mcp.py"
else
    echo "  ⚠️  .env 看起来已配置，可以运行验证脚本"
fi

echo ""
echo "========================================"
echo " Phase 1 环境搭建完成"
echo "========================================"
echo ""
echo "下一步:"
echo "  1. 编辑 $PROJECT_DIR/.env 填入 API Key"
echo "  2. cd $PROJECT_DIR && source venv/bin/activate"
echo "  3. python test_mcp.py"
