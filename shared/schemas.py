"""Pydantic v2 API schemas shared by backend, frontend contracts, and worker."""

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


class JobCreateRequest(BaseModel):
    upload_id: str = Field(min_length=1)
    language: Literal["auto", "en", "hi", "ur"] = "auto"
    num_shorts: int = Field(default=3, ge=1, le=20)
    clip_duration_min: int = Field(default=30, ge=5)
    clip_duration_max: int = Field(default=60, ge=5)

    @field_validator("clip_duration_max")
    @classmethod
    def _max_gte_min(cls, v: int, info) -> int:
        min_d = (info.data or {}).get("clip_duration_min")
        if min_d is not None and v < min_d:
            raise ValueError("clip_duration_max must be >= clip_duration_min")
        return v


class JobResponse(BaseModel):
    job_id: str
    status: str
    progress: int
    current_stage: str
    num_shorts: int


class ClipResponse(BaseModel):
    clip_id: str
    title: str
    hook: str
    description: str
    score: float
    duration: float
    start_time: float
    end_time: float
    download_url: Optional[str] = None


class ProgressResponse(BaseModel):
    job_id: str
    status: str
    progress: int
    current_stage: str
    error: Optional[str] = None
