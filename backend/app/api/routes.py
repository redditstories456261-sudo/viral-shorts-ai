"""API routes for the Viral Shorts AI backend.

Endpoints:
  - GET    /api/health
  - POST   /api/upload/init
  - PUT    /api/upload/{upload_id}/chunk?offset=N
  - GET    /api/upload/{upload_id}/status
  - POST   /api/upload/{upload_id}/complete
  - POST   /api/jobs
  - GET    /api/jobs/{job_id}/progress
  - GET    /api/jobs/{job_id}/clips
  - GET    /api/clips/{clip_id}/download
  - DELETE /api/jobs/{job_id}
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from shared.config import settings
from shared.schemas import JobCreateRequest
from shared.storage import StorageClient

from ..celery_client import enqueue_video_job
from ..db import get_db
from ..models import Clip, Job

logger = logging.getLogger("viral_shorts_ai.api")

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)

CHUNK_SIZE = 5 * 1024 * 1024  # 5 MB per chunk
_GB = 1024**3

_ALLOWED_LANGUAGES = {"auto", "en", "hi", "ur"}
_ALLOWED_DURATIONS = {30, 45, 60, 75, 90}
_UPLOAD_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_CONTENT_RANGE_RE = re.compile(r"^bytes (\d+)-(\d+)/(\d+)$")
_COMPLETED_REGISTRY = "_completed.json"
_META_NAME = "meta.json"
_DATA_NAME = "data.part"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_storage: StorageClient | None = None


def get_storage() -> StorageClient:
    """Return the shared StorageClient singleton."""
    global _storage
    if _storage is None:
        _storage = StorageClient()
    return _storage


def secure_filename(filename: str) -> str:
    """Return a filesystem-safe version of ``filename``.

    Local implementation (no extra dependency): strips any directory
    components, replaces characters outside ``[A-Za-z0-9._-]`` with
    underscores, and guards against empty or dot-only names.
    """
    name = str(filename).replace("\\", "/").split("/")[-1].strip()
    name = "".join(ch if (ch.isalnum() or ch in "._-") else "_" for ch in name)
    name = name.lstrip(".")
    if not name or name in {".", ".."}:
        name = "file"
    if len(name) > 200:
        stem, dot, ext = name.rpartition(".")
        if dot and ext and len(ext) < 200:
            name = stem[: 200 - len(ext) - 1] + dot + ext
        else:
            name = name[:200]
    return name


def _tmp_root() -> Path:
    root = Path(settings.upload_tmp_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _upload_dir(upload_id: str) -> Path:
    return _tmp_root() / upload_id


def _require_upload_id(upload_id: str) -> str:
    if not upload_id or not _UPLOAD_ID_RE.match(upload_id):
        raise HTTPException(status_code=404, detail="Upload not found")
    return upload_id


def _meta_path(upload_id: str) -> Path:
    return _upload_dir(upload_id) / _META_NAME


def _data_path(upload_id: str) -> Path:
    return _upload_dir(upload_id) / _DATA_NAME


def _load_meta(upload_id: str) -> dict:
    path = _meta_path(upload_id)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Upload not found")
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise HTTPException(status_code=500, detail="Upload metadata is unreadable")
    if not isinstance(meta, dict):
        raise HTTPException(status_code=500, detail="Upload metadata is unreadable")
    return meta


def _save_meta(upload_id: str, meta: dict) -> None:
    dest = _meta_path(upload_id)
    fd, tmp_name = tempfile.mkstemp(dir=str(dest.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(meta, fh)
        os.replace(tmp_name, dest)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _merge_ranges(ranges: list[list[int]]) -> list[list[int]]:
    """Merge [start, end) byte ranges into a sorted, non-overlapping list."""
    merged: list[list[int]] = []
    for start, end in sorted((int(s), int(e)) for s, e in ranges):
        if end <= start:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def _received_bytes(meta: dict) -> int:
    return sum(end - start for start, end in _merge_ranges(meta.get("ranges", [])))


def _registry_path() -> Path:
    return _tmp_root() / _COMPLETED_REGISTRY


def _read_registry() -> dict:
    path = _registry_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_registry(registry: dict) -> None:
    dest = _registry_path()
    fd, tmp_name = tempfile.mkstemp(dir=str(dest.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(registry, fh)
        os.replace(tmp_name, dest)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _get_job(db: Session, job_id: str) -> Job:
    try:
        jid = uuid.UUID(str(job_id))
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(status_code=404, detail="Job not found")
    job = db.get(Job, jid)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


def _clip_to_dict(clip: Clip) -> dict:
    return {
        "id": str(clip.id),
        "job_id": str(clip.job_id),
        "start_time": clip.start_time,
        "end_time": clip.end_time,
        "duration": clip.duration,
        "score": clip.score,
        "title": clip.title,
        "hook": clip.hook,
        "description": clip.description,
        "storage_key": clip.storage_key,
    }


class UploadInitRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=512)
    total_size: int = Field(gt=0)
    mime_type: str = Field(min_length=1, max_length=128)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Chunked upload
# ---------------------------------------------------------------------------


@router.post("/upload/init")
@limiter.limit("20/minute")
def upload_init(payload: UploadInitRequest, request: Request) -> dict:
    if not payload.mime_type.lower().startswith("video/"):
        raise HTTPException(status_code=422, detail="mime_type must be a video type")
    max_bytes = int(settings.max_upload_gb * _GB)
    if payload.total_size > max_bytes:
        raise HTTPException(
            status_code=422,
            detail=f"total_size exceeds the {settings.max_upload_gb} GB limit",
        )
    filename = secure_filename(payload.filename)
    upload_id = uuid.uuid4().hex
    updir = _upload_dir(upload_id)
    updir.mkdir(parents=True, exist_ok=False)
    meta = {
        "original_filename": payload.filename,
        "filename": filename,
        "total_size": payload.total_size,
        "mime_type": payload.mime_type,
        "ranges": [],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _save_meta(upload_id, meta)
    _data_path(upload_id).touch(exist_ok=False)
    logger.info("upload initialized: id=%s size=%d", upload_id, payload.total_size)
    return {"upload_id": upload_id, "chunk_size": CHUNK_SIZE}


@router.put("/upload/{upload_id}/chunk")
@limiter.limit("20/minute")
async def upload_chunk(
    upload_id: str,
    request: Request,
    offset: int = Query(ge=0),
    content_range: str | None = Header(default=None, alias="Content-Range"),
) -> dict:
    _require_upload_id(upload_id)
    meta = _load_meta(upload_id)
    total_size = int(meta["total_size"])

    if content_range is None:
        raise HTTPException(status_code=400, detail="Content-Range header is required")
    match = _CONTENT_RANGE_RE.match(content_range.strip())
    if match is None:
        raise HTTPException(status_code=400, detail="Invalid Content-Range header")
    start, end, total = (int(g) for g in match.groups())
    if total != total_size:
        raise HTTPException(
            status_code=400,
            detail="Content-Range total does not match the declared upload size",
        )
    if start != offset:
        raise HTTPException(
            status_code=400, detail="offset query param must match Content-Range start"
        )
    if end < start or end >= total_size:
        raise HTTPException(status_code=400, detail="Content-Range is out of bounds")

    body = await request.body()
    if len(body) != end - start + 1:
        raise HTTPException(
            status_code=400, detail="Chunk body length does not match Content-Range"
        )
    if len(body) > CHUNK_SIZE:
        raise HTTPException(
            status_code=413, detail=f"Chunk exceeds the {CHUNK_SIZE} byte limit"
        )

    path = _data_path(upload_id)
    with open(path, "r+b") as fh:
        fh.seek(start)
        fh.write(body)
        fh.flush()
        os.fsync(fh.fileno())

    ranges = _merge_ranges(meta.get("ranges", []) + [[start, end + 1]])
    meta["ranges"] = ranges
    _save_meta(upload_id, meta)
    return {"received_bytes": sum(e - s for s, e in ranges)}


@router.get("/upload/{upload_id}/status")
def upload_status(upload_id: str) -> dict:
    _require_upload_id(upload_id)
    meta = _load_meta(upload_id)
    return {"received_bytes": _received_bytes(meta), "total_size": int(meta["total_size"])}


@router.post("/upload/{upload_id}/complete")
@limiter.limit("20/minute")
def upload_complete(
    upload_id: str,
    request: Request,
    x_content_checksum: str | None = Header(default=None, alias="X-Content-Checksum"),
) -> dict:
    _require_upload_id(upload_id)
    meta = _load_meta(upload_id)
    total_size = int(meta["total_size"])

    if _merge_ranges(meta.get("ranges", [])) != [[0, total_size]]:
        raise HTTPException(status_code=400, detail="Upload is incomplete")

    path = _data_path(upload_id)
    if x_content_checksum:
        actual = _sha256_file(path)
        if not hmac.compare_digest(actual, x_content_checksum.strip().lower()):
            raise HTTPException(status_code=400, detail="Checksum mismatch")

    storage_key = f"uploads/{upload_id}/{meta['filename']}"
    try:
        get_storage().upload_file(str(path), storage_key)
    except Exception:
        logger.exception("S3 upload failed for upload_id=%s", upload_id)
        raise HTTPException(status_code=502, detail="Failed to store the upload")

    registry = _read_registry()
    registry[upload_id] = {
        "storage_key": storage_key,
        "filename": meta["filename"],
        "original_filename": meta.get("original_filename"),
        "size": total_size,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_registry(registry)
    shutil.rmtree(_upload_dir(upload_id), ignore_errors=True)
    logger.info("upload completed: id=%s", upload_id)
    return {"upload_id": upload_id, "storage_key": storage_key}


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------


@router.post("/jobs")
@limiter.limit("20/minute")
def create_job(
    payload: JobCreateRequest, request: Request, db: Session = Depends(get_db)
) -> dict:
    upload_id = str(getattr(payload, "upload_id", "") or "")
    if not _UPLOAD_ID_RE.match(upload_id):
        raise HTTPException(status_code=422, detail="Invalid upload_id")

    entry = _read_registry().get(upload_id)
    if entry is None:
        raise HTTPException(status_code=422, detail="Upload not found or not completed")
    try:
        stored = get_storage().key_exists(entry["storage_key"])
    except Exception:
        logger.exception("Storage availability check failed")
        raise HTTPException(status_code=502, detail="Storage is unavailable")
    if not stored:
        raise HTTPException(status_code=422, detail="Upload not found in storage")

    language = str(getattr(payload, "language", "") or "").lower()
    if language not in _ALLOWED_LANGUAGES:
        raise HTTPException(
            status_code=422,
            detail=f"language must be one of {sorted(_ALLOWED_LANGUAGES)}",
        )
    num_shorts = getattr(payload, "num_shorts", None)
    if not isinstance(num_shorts, int) or not 1 <= num_shorts <= 20:
        raise HTTPException(status_code=422, detail="num_shorts must be between 1 and 20")
    clip_min = getattr(payload, "clip_duration_min", None)
    clip_max = getattr(payload, "clip_duration_max", None)
    for value, name in ((clip_min, "clip_duration_min"), (clip_max, "clip_duration_max")):
        if value not in _ALLOWED_DURATIONS:
            raise HTTPException(
                status_code=422,
                detail=f"{name} must be one of {sorted(_ALLOWED_DURATIONS)}",
            )
    if clip_min > clip_max:
        raise HTTPException(
            status_code=422, detail="clip_duration_min must not exceed clip_duration_max"
        )

    job = Job(
        source_filename=entry["filename"],
        status="queued",
        progress=0.0,
        current_stage="queued",
        language=language,
        num_shorts=num_shorts,
        clip_duration_min=clip_min,
        clip_duration_max=clip_max,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    job_id = str(job.id)
    try:
        enqueue_video_job(job_id)
    except Exception:
        logger.exception("Failed to enqueue job")
        job.status = "failed"
        job.error = "Failed to enqueue the video job"
        db.commit()
        raise HTTPException(status_code=502, detail="Failed to enqueue the video job")

    logger.info("job created: job_id=%s", job_id)
    return {"job_id": job_id}


@router.get("/jobs/{job_id}/progress")
def job_progress(job_id: str, db: Session = Depends(get_db)) -> dict:
    job = _get_job(db, job_id)
    return {
        "job_id": str(job.id),
        "status": job.status,
        "progress": job.progress,
        "current_stage": job.current_stage,
        "error": job.error,
    }


@router.get("/jobs/{job_id}/clips")
def job_clips(job_id: str, db: Session = Depends(get_db)) -> dict:
    job = _get_job(db, job_id)
    if job.status != "completed":
        raise HTTPException(
            status_code=404, detail="Clips are not available until the job is completed"
        )
    clips = (
        db.query(Clip)
        .filter(Clip.job_id == job.id)
        .order_by(Clip.score.desc(), Clip.start_time.asc())
        .all()
    )
    return {"clips": [_clip_to_dict(clip) for clip in clips]}


@router.delete("/jobs/{job_id}")
def delete_job(job_id: str, db: Session = Depends(get_db)) -> dict:
    job = _get_job(db, job_id)
    jid = str(job.id)
    storage = get_storage()
    for prefix in (f"jobs/{jid}/", f"clips/{jid}/"):
        try:
            storage.delete_prefix(prefix)
        except Exception:
            logger.exception("Failed to delete storage prefix for job_id=%s", jid)
    db.delete(job)
    db.commit()
    logger.info("job deleted: job_id=%s", jid)
    return {"deleted": True}


# ---------------------------------------------------------------------------
# Clips
# ---------------------------------------------------------------------------


@router.get("/clips/{clip_id}/download")
def clip_download(clip_id: str, db: Session = Depends(get_db)) -> RedirectResponse:
    try:
        cid = uuid.UUID(str(clip_id))
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(status_code=404, detail="Clip not found")
    clip = db.get(Clip, cid)
    if clip is None:
        raise HTTPException(status_code=404, detail="Clip not found")
    if settings.download_mode == "stream":
        # Pod/MinIO setup: presigned URL me andaruni hostname hota hai jo
        # browser tak nahi pahunchta — is liye backend khud file stream kare.
        try:
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
            tmp.close()
            get_storage().download_file(clip.storage_key, tmp.name)
        except Exception:
            logger.exception("Failed to fetch clip for streaming")
            raise HTTPException(status_code=502, detail="Failed to fetch clip")
        return FileResponse(
            tmp.name, media_type="video/mp4", filename=f"short-{clip_id}.mp4"
        )
    try:
        url = get_storage().presigned_url(clip.storage_key)
    except Exception:
        logger.exception("Failed to generate download URL")
        raise HTTPException(status_code=502, detail="Failed to generate download URL")
    return RedirectResponse(url=url, status_code=302)
