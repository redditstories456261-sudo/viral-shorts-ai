"""Central configuration for the Viral Shorts AI worker and shared library.

All values come from the environment (optionally via a local ``.env`` file).
Field names map to the exact env var names listed below (pydantic-settings
matches them case-insensitively).
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- required infrastructure ---
    database_url: str          # DATABASE_URL, e.g. postgresql+psycopg2://user:pw@host/db
    redis_url: str = "redis://localhost:6379/0"  # REDIS_URL

    # --- object storage (S3-compatible) ---
    s3_endpoint: str = ""      # S3_ENDPOINT
    s3_bucket: str             # S3_BUCKET
    s3_access_key: str = ""    # S3_ACCESS_KEY
    s3_secret_key: str = ""    # S3_SECRET_KEY
    s3_region: str = "us-east-1"  # S3_REGION

    # --- ML ---
    whisper_model: str = "large-v3"  # WHISPER_MODEL (faster-whisper model size)

    # --- pluggable LLM for titles/hooks ("none" = local template logic) ---
    llm_provider: str = "none"  # LLM_PROVIDER: "none" | "openai"
    llm_base_url: str = ""      # LLM_BASE_URL
    llm_api_key: str = ""       # LLM_API_KEY (never logged)
    llm_model: str = ""         # LLM_MODEL

    # --- render / limits ---
    max_upload_gb: int = 5      # MAX_UPLOAD_GB
    video_codec: str = "auto"   # VIDEO_CODEC: "auto" | "h264_nvenc" | "libx264"
    video_crf: int = 20         # VIDEO_CRF

    # --- misc ---
    frontend_url: str = ""            # FRONTEND_URL
    upload_tmp_dir: str = "/tmp/uploads"  # UPLOAD_TMP_DIR
    # DOWNLOAD_MODE: "redirect" (S3 presigned URL, default) ya "stream"
    # (backend khud file bhejta hai — pod/MinIO setup ke liye).
    download_mode: str = "redirect"  # DOWNLOAD_MODE


settings = Settings()
