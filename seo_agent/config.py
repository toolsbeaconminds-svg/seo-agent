import os
import tempfile
from pydantic_settings import BaseSettings
from typing import Optional


def _maybe_write_google_credentials():
    """Write GOOGLE_SERVICE_ACCOUNT_JSON env var to a temp file for Railway/production.

    On Railway there is no filesystem for credential files, so the full JSON
    is passed as an env var string.  This runs once at import time so that
    pydantic-settings picks up the resulting path via GOOGLE_SERVICE_ACCOUNT_KEY_PATH.
    """
    json_str = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if json_str and not os.environ.get("GOOGLE_SERVICE_ACCOUNT_KEY_PATH"):
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, prefix="google_sa_"
        )
        tmp.write(json_str)
        tmp.close()
        os.environ["GOOGLE_SERVICE_ACCOUNT_KEY_PATH"] = tmp.name


_maybe_write_google_credentials()


class Settings(BaseSettings):
    ANTHROPIC_API_KEY: str = ""
    GOOGLE_SERVICE_ACCOUNT_KEY_PATH: Optional[str] = None
    GA4_PROPERTY_ID: Optional[str] = None
    AHREFS_API_KEY: Optional[str] = None

    # WordPress (Application Password auth)
    WP_URL: Optional[str] = None
    WP_USERNAME: Optional[str] = None
    WP_APP_PASSWORD: Optional[str] = None

    # Models
    LLM_ANALYSIS_MODEL: str = "claude-sonnet-4-20250514"
    LLM_EXTRACTION_MODEL: str = "claude-haiku-4-5-20251001"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()


def override_ga4_property(property_id: str | None):
    """Override the GA4 property ID for the current run."""
    if property_id:
        settings.GA4_PROPERTY_ID = property_id
