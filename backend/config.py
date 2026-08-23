from pathlib import Path

from dotenv import dotenv_values

ENV_PATH = Path(__file__).resolve().parent / ".env"


def load_settings() -> dict[str, str]:
    """只从 backend/.env 读取配置，不读系统环境变量。"""
    if not ENV_PATH.exists():
        return {}
    return {
        key: value
        for key, value in dotenv_values(ENV_PATH).items()
        if key is not None and value is not None
    }


settings = load_settings()
