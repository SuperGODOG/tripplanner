"""应用配置管理

读取顺序:
  1. 环境变量 (最高优先级)
  2. backend/venv/.env
  3. backend/.env
  4. 根目录 .env
"""
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


def _find_env_file() -> str:
    """寻找首个存在的 .env 文件"""
    backend_dir = Path(__file__).parent.parent
    candidates = [
        backend_dir / "venv" / ".env",
        backend_dir / ".env",
        Path.cwd() / "backend" / ".env",
        Path.cwd() / ".env",
    ]
    for p in candidates:
        if p.is_file():
            return str(p)
    return str(backend_dir / ".env")


class Settings(BaseSettings):
    # LLM 配置
    llm_api_key: str = ""
    llm_model_id: str = "glm-5.3-flash"
    llm_base_url: str = "https://ark.cn-beijing.volces.com/api/plan"
    llm_protocol: str = "anthropic"  # "anthropic" | "openai"

    # 高德地图
    amap_api_key: str = ""

    # Tavily Web Search API
    tavily_api_key: str = ""

    # 服务
    host: str = "0.0.0.0"
    port: int = 8000
    app_name: str = "TripPlanner"
    app_version: str = "1.0.0"

    # Redis 依赖指纹缓存
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str = ""
    redis_db: int = 0
    redis_enabled: bool = True

    model_config = SettingsConfigDict(
        env_file=_find_env_file(),
        env_file_encoding="utf-8",
        extra="ignore",
    )


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
        if not _settings.llm_api_key:
            raise ValueError(
                "API Key 未配置！\n"
                "请将 backend/.env.example 复制为 backend/.env 并填入真实 Key:\n"
                "  cp backend/.env.example backend/.env\n"
                "  nano backend/.env"
            )
    return _settings


def reset_settings() -> Settings:
    """重置单例并重新读取环境配置"""
    global _settings
    _settings = None
    return get_settings()
