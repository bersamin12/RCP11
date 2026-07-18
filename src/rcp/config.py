from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openrouter_api_key: str = ""
    rcp_model: str = "deepseek/deepseek-v4-flash"
    rcp_base_url: str = "https://openrouter.ai/api/v1"
    rcp_reasoning: bool = False
    rcp_temperature: float = 0.2

    rcp_data_dir: Path = Path("data")
    rcp_om_image: str = "openmodelica/openmodelica:v1.25.0-minimal"
    rcp_om_backend: str = "auto"  # auto | docker | local
    rcp_mailto: str = ""  # OpenAlex polite-pool email


@lru_cache
def get_settings() -> Settings:
    return Settings()


def data_dir() -> Path:
    d = get_settings().rcp_data_dir
    d.mkdir(parents=True, exist_ok=True)
    return d
