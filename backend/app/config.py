"""应用配置管理

读取顺序:
  1. venv/.env（真实 Key，gitignored）  ← 本地开发
  2. .env（模板占位符，可提交 Git）     ← 新克隆者复制到 venv/.env 后填入
"""
from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # LLM
    llm_api_key: str = ""
    llm_model_id: str = "deepseek-chat"
    llm_base_url: str = "https://api.deepseek.com/v1"

    # 高德地图
    amap_api_key: str = ""

    # 服务
    host: str = "0.0.0.0"
    port: int = 8000
    app_name: str = "TripPlanner"
    app_version: str = "1.0.0"

    class Config:
        # 优先读 venv/.env（gitignored），fallback 到 .env
        env_file = str(Path(__file__).parent.parent / "venv" / ".env")
        env_file_encoding = "utf-8"


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
        if not _settings.llm_api_key:
            raise ValueError(
                "API Key 未配置！\n"
                "请将 backend/.env.example 复制为 backend/venv/.env 并填入真实 Key:\n"
                "  cp backend/.env.example backend/venv/.env\n"
                "  nano backend/venv/.env"
            )
    return _settings
