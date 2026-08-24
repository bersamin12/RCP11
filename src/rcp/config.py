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
    rcp_om_image: str = "rcp-openmodelica-buildings:13.0.0-om1.26.3"
    rcp_om_backend: str = "auto"  # auto | docker | local
    rcp_mailto: str = ""  # OpenAlex polite-pool email
    rcp_max_batch_cases: int = 18

    # Open-access full text. Only genuinely open records are fetched; "bronze" OA
    # is free to read but states no licence, so it stays off by default.
    rcp_fetch_oa_pdfs: bool = True
    rcp_pdf_allow_bronze: bool = False
    rcp_unpaywall_enabled: bool = True
    rcp_pdf_max_bytes: int = 40_000_000
    rcp_pdf_timeout_seconds: float = 30.0
    rcp_pdf_max_workers: int = 4
    rcp_pdf_max_pages: int = 80
    rcp_fulltext_max_chars: int = 60_000

    # Evaluation rubric (docs/EVALUATION.md). Scores stay concealed until this many
    # reviewers have submitted, so "independently, before discussing" is enforced.
    rcp_min_rubric_reviewers: int = 2
    # 0 keeps acceptance unblocked, so CI and `rcp run --auto` are unaffected.
    rcp_require_rubric_reviews: int = 0

    # HTTP Basic auth for the API and the SPA it serves. An empty password disables
    # the check, which keeps CI and local development unchanged; `rcp serve` is the
    # layer that refuses to start in that state, so a deployment cannot end up
    # unauthenticated by accident. A shared credential is transport protection, not
    # identity: it says nothing about *who* made a request.
    rcp_auth_user: str = "rcp"
    rcp_auth_password: str = ""
    rcp_auth_realm: str = "RCP platform"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def data_dir() -> Path:
    d = get_settings().rcp_data_dir
    d.mkdir(parents=True, exist_ok=True)
    return d


def literature_dir() -> Path:
    """Content-addressed cache of open-access PDFs, shared across topics and runs.

    Deliberately outside both the memory snapshots (which stay frozen) and the run
    directories (which the reproducibility bundle sweeps up).
    """
    d = data_dir() / "literature"
    d.mkdir(parents=True, exist_ok=True)
    return d
