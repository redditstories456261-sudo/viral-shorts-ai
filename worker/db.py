"""SQLAlchemy models + engine for the worker.

The worker only needs to read the Job row enqueued by the backend and write
back stage/progress, plus insert one Clip row per rendered short. Table
definitions here mirror the backend's schema; migrations remain backend-owned.
"""

from __future__ import annotations

import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from shared.config import settings

Base = declarative_base()


class Job(Base):
    __tablename__ = "jobs"

    id = Column(String, primary_key=True)
    status = Column(String, default="queued", nullable=False)  # queued|processing|done|failed
    stage = Column(String, default="UPLOADED", nullable=False)
    progress = Column(Integer, default=0, nullable=False)
    error = Column(Text, nullable=True)
    upload_id = Column(String, nullable=True)
    language = Column(String, default="auto", nullable=False)
    num_shorts = Column(Integer, default=3, nullable=False)
    clip_duration_min = Column(Integer, default=30, nullable=False)
    clip_duration_max = Column(Integer, default=60, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)


class Clip(Base):
    __tablename__ = "clips"

    id = Column(String, primary_key=True)
    job_id = Column(String, ForeignKey("jobs.id"), index=True, nullable=False)
    title = Column(String, default="", nullable=False)
    hook = Column(String, default="", nullable=False)
    description = Column(Text, default="", nullable=False)
    score = Column(Float, default=0.0, nullable=False)
    duration = Column(Float, default=0.0, nullable=False)
    start_time = Column(Float, default=0.0, nullable=False)
    end_time = Column(Float, default=0.0, nullable=False)
    s3_key = Column(String, default="", nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)


engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
