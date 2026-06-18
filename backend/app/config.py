"""Central configuration. Everything is driven by env vars with local-dev defaults.

Settings are loaded once and shared across the web process and the RQ worker so
both halves of the system agree on storage, DB, and reel parameters.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/config.py -> backend/
BACKEND_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = BACKEND_DIR / "assets"
MUSIC_DIR = ASSETS_DIR / "music"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.environ.get("ENV_FILE", str(BACKEND_DIR / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Core
    env: str = "local"
    app_name: str = "ReelMagic"
    log_level: str = "INFO"

    # Database
    database_url: str = "sqlite:///./data/reelmagic.db"

    # Redis / queue
    redis_url: str = "redis://localhost:6379/0"
    run_jobs_inline: bool = False

    # Storage
    storage_backend: str = "local"  # local | r2
    storage_local_dir: str = "./storage"
    storage_public_base_url: str = "http://localhost:8000/files"
    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket: str = "reelmagic"
    r2_endpoint_url: str = ""
    r2_public_base_url: str = ""

    # Edit brain
    anthropic_api_key: str = ""
    edit_brain_model: str = "claude-sonnet-4-6"
    edit_brain_max_tokens: int = 8000

    # Scoring
    scoring_backend: str = "auto"  # auto | clip | heuristic
    scoring_device: str = "cpu"

    # Reel parameters
    target_duration_s: float = 29.0
    min_duration_s: float = 25.0
    max_duration_s: float = 35.0

    # Guardrails
    max_files_per_job: int = 60
    max_upload_mb: int = 500
    max_video_seconds: int = 120
    max_reels_per_session_per_day: int = 10
    asset_ttl_hours: int = 48
    daily_spend_ceiling_usd: float = 0.0
    watermark_text: str = "ReelMagic"

    # CORS
    frontend_origin: str = "http://localhost:3000"

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def sqlite_path(self) -> Path | None:
        if not self.is_sqlite:
            return None
        # sqlite:///./data/x.db  ->  ./data/x.db
        raw = self.database_url.split("///", 1)[-1]
        return (BACKEND_DIR / raw).resolve() if not os.path.isabs(raw) else Path(raw)

    @property
    def local_storage_path(self) -> Path:
        p = Path(self.storage_local_dir)
        return p if p.is_absolute() else (BACKEND_DIR / p).resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
