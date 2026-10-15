"""Celery task: end-to-end processing of one video job.

Stage / progress map (UPLOAD is done at enqueue time by the backend):
    TRANSCRIBE            5 -> 35   download source, extract audio, whisper
    CANDIDATE_GENERATION 35 -> 40   sentence-aligned candidates
    VIRAL_SCORING        40 -> 50   score every candidate
    FACE_TRACKING        50 -> 65   sample frames, MediaPipe, speaker track
    REFRAIMING           65 -> 70   per-frame 9:16 crop plan
    CAPTIONS             70 -> 75   ASS karaoke captions
    RENDER               75 -> 95   ffmpeg per clip
    FINALIZE             95 -> 100  upload + Clip rows, mark done

On any exception the job is marked failed with a user-friendly error message
and the full traceback is logged. Temp files are always cleaned up.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import time
import traceback
import uuid

import cv2

from shared.config import settings
from shared.storage import StorageClient
from worker.celery_app import celery_app
from worker.db import Clip, Job, SessionLocal
from worker.pipeline.audio import audio_energy, extract_audio
from worker.pipeline.captions import build_ass, write_ass
from worker.pipeline.faces import detect_faces_bgr, pick_speaker_track
from worker.pipeline.reframe import plan_crop
from worker.pipeline.render import build_ffmpeg_cmd, run as run_ffmpeg
from worker.pipeline.titles import generate_title_hook
from worker.pipeline.transcribe import transcribe_audio
from worker.pipeline.viral import generate_candidates, score_candidate, select_top_clips

log = logging.getLogger(__name__)

FACE_SAMPLE_FPS = 4.0  # MediaPipe runs on frames sampled at this rate


def _set_progress(
    job_id: str,
    stage: str | None = None,
    progress: int | None = None,
    status: str | None = None,
    error: str | None = None,
) -> None:
    session = SessionLocal()
    try:
        job = session.get(Job, job_id)
        if job is None:
            raise ValueError(f"job {job_id} not found in database")
        if stage is not None:
            job.stage = stage
        if progress is not None:
            job.progress = int(progress)
        if status is not None:
            job.status = status
        if error is not None:
            job.error = error
        session.commit()
    finally:
        session.close()


def _friendly_error(exc: BaseException) -> str:
    msg = str(exc)
    lowered = msg.lower()
    name = type(exc).__name__
    if "ffmpeg" in lowered:
        return (
            "Video rendering failed (ffmpeg error). The source file may be "
            "corrupt or in an unsupported format."
        )
    if "cuda" in lowered or "out of memory" in lowered:
        return (
            "The GPU ran out of memory during transcription. Try a smaller "
            "Whisper model (WHISPER_MODEL)."
        )
    if "nosuchkey" in lowered or "404" in msg:
        return "Source video not found in storage. Please re-upload the video."
    if "no speech" in lowered:
        return "No speech was detected in the video, so no clips could be made."
    return f"Processing failed: {name}: {msg[:300]}"


def _sample_face_detections(
    video_path: str, start: float, end: float, src_fps: float
) -> dict[int, list[dict]]:
    """Sample frames across [start, end) and run MediaPipe on each.

    Returns {frame_index: [detections]} with sparse frame indices.
    """
    cap = cv2.VideoCapture(video_path)
    detections: dict[int, list[dict]] = {}
    try:
        t = start
        step = 1.0 / FACE_SAMPLE_FPS
        while t < end:
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
            ok, frame = cap.read()
            if not ok or frame is None:
                break
            fidx = int(round(t * src_fps))
            detections[fidx] = detect_faces_bgr(frame)
            t += step
    finally:
        cap.release()
    return detections


def _probe_video(video_path: str) -> tuple[int, int, float]:
    cap = cv2.VideoCapture(video_path)
    try:
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
    finally:
        cap.release()
    if w <= 0 or h <= 0:
        raise RuntimeError("could not read video dimensions (file may be corrupt)")
    return w, h, fps


@celery_app.task(name="process_video_job", bind=True, max_retries=0)
def process_video_job(self, job_id: str) -> dict:
    t_start = time.time()
    os.makedirs(settings.upload_tmp_dir, exist_ok=True)
    tmpdir = tempfile.mkdtemp(prefix=f"job_{job_id}_", dir=settings.upload_tmp_dir)
    stage = "TRANSCRIBE"
    try:
        log.info("job_id=%s stage=START msg='job started'", job_id)

        session = SessionLocal()
        try:
            job = session.get(Job, job_id)
            if job is None:
                raise ValueError(f"job {job_id} not found in database")
            num_shorts = job.num_shorts
            language = job.language or "auto"
            dmin, dmax = job.clip_duration_min, job.clip_duration_max
        finally:
            session.close()

        _set_progress(job_id, stage="TRANSCRIBE", progress=5, status="processing")
        storage = StorageClient.from_settings(settings)

        # -- download source -------------------------------------------------
        local_src = os.path.join(tmpdir, "source.mp4")
        storage.download_file(storage.source_key(job_id), local_src)

        # -- TRANSCRIBE -------------------------------------------------------
        wav_path = os.path.join(tmpdir, "audio.wav")
        extract_audio(local_src, wav_path)
        _set_progress(job_id, stage="TRANSCRIBE", progress=12)

        tres = transcribe_audio(wav_path, settings.whisper_model, language)
        segments, words = tres["segments"], tres["words"]
        if not segments:
            raise RuntimeError("no speech detected in video")
        log.info(
            "job_id=%s stage=TRANSCRIBE segments=%d words=%d lang=%s elapsed=%.1fs",
            job_id, len(segments), len(words), tres["language"], time.time() - t_start,
        )
        _set_progress(job_id, stage="TRANSCRIBE", progress=35)

        # -- CANDIDATE_GENERATION --------------------------------------------
        stage = "CANDIDATE_GENERATION"
        energy = audio_energy(wav_path)
        durations = sorted({dmin, (dmin + dmax) // 2, dmax})
        candidates = generate_candidates(segments, words, energy, durations)
        if not candidates:
            raise RuntimeError("no clip candidates matched the requested durations")
        log.info(
            "job_id=%s stage=CANDIDATE_GENERATION candidates=%d elapsed=%.1fs",
            job_id, len(candidates), time.time() - t_start,
        )
        _set_progress(job_id, stage="CANDIDATE_GENERATION", progress=40)

        # -- VIRAL_SCORING ----------------------------------------------------
        stage = "VIRAL_SCORING"
        scored = [
            {**c, "score": score_candidate(c, segments, words, energy)}
            for c in candidates
        ]
        _set_progress(job_id, stage="VIRAL_SCORING", progress=50)

        top = select_top_clips(scored, num_shorts)
        if not top:
            raise RuntimeError("clip selection produced no results")
        log.info(
            "job_id=%s stage=VIRAL_SCORING selected=%d top_score=%.1f elapsed=%.1fs",
            job_id, len(top), top[0]["score"]["total"], time.time() - t_start,
        )

        src_w, src_h, src_fps = _probe_video(local_src)
        n = len(top)

        # -- per-clip pipeline -------------------------------------------------
        for i, cand in enumerate(top):
            clip_id = uuid.uuid4().hex[:12]
            c_start, c_end = cand["start"], cand["end"]
            dur = c_end - c_start
            frac = (i + 1) / n

            # FACE_TRACKING
            stage = "FACE_TRACKING"
            dets = _sample_face_detections(local_src, c_start, c_end, src_fps)
            track = pick_speaker_track(dets)
            _set_progress(job_id, stage="FACE_TRACKING", progress=int(50 + 15 * frac))

            # REFRAIMING
            stage = "REFRAIMING"
            total_frames = max(1, int(round(dur * src_fps)))
            crops = plan_crop(track, src_w, src_h, src_fps, total_frames, mode="single")
            crop_plan_path = os.path.join(tmpdir, f"crop_{clip_id}.json")
            with open(crop_plan_path, "w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "fps": src_fps,
                        "src_w": src_w,
                        "src_h": src_h,
                        "duration": dur,
                        "crops": [list(c) for c in crops],
                    },
                    fh,
                )
            _set_progress(job_id, stage="REFRAIMING", progress=int(65 + 5 * frac))

            # CAPTIONS
            stage = "CAPTIONS"
            ass_text = build_ass(words, c_start, c_end)
            ass_path = os.path.join(tmpdir, f"{clip_id}.ass")
            write_ass(ass_path, ass_text)
            _set_progress(job_id, stage="CAPTIONS", progress=int(70 + 5 * frac))

            # RENDER
            stage = "RENDER"
            out_path = os.path.join(tmpdir, f"{clip_id}.mp4")
            cmd = build_ffmpeg_cmd(
                local_src,
                out_path,
                crop_plan_path,
                ass_path,
                codec=settings.video_codec,
                crf=settings.video_crf,
            )
            run_ffmpeg(cmd)

            # titles/hooks from this clip's own transcript slice (facts only)
            clip_text = " ".join(
                s["text"] for s in segments if s["end"] > c_start and s["start"] < c_end
            )
            meta = generate_title_hook(
                clip_text,
                settings.llm_provider,
                settings.llm_base_url,
                settings.llm_api_key,
                settings.llm_model,
            )

            # upload + DB row
            clip_key = storage.clip_key(job_id, clip_id)
            storage.upload_file(out_path, clip_key)
            session = SessionLocal()
            try:
                session.add(
                    Clip(
                        id=clip_id,
                        job_id=job_id,
                        title=meta["title"],
                        hook=meta["hook"],
                        description=meta["description"],
                        score=cand["score"]["total"],
                        duration=dur,
                        start_time=c_start,
                        end_time=c_end,
                        s3_key=clip_key,
                    )
                )
                session.commit()
            finally:
                session.close()

            _set_progress(job_id, stage="RENDER", progress=int(75 + 20 * frac))
            log.info(
                "job_id=%s stage=RENDER clip=%d/%d clip_id=%s score=%.1f elapsed=%.1fs",
                job_id, i + 1, n, clip_id, cand["score"]["total"], time.time() - t_start,
            )

        # -- FINALIZE -----------------------------------------------------------
        stage = "FINALIZE"
        _set_progress(job_id, stage="FINALIZE", progress=100, status="done")
        log.info(
            "job_id=%s stage=DONE clips=%d elapsed=%.1fs",
            job_id, len(top), time.time() - t_start,
        )
        return {"job_id": job_id, "clips": len(top)}

    except Exception as exc:
        log.error(
            "job_id=%s stage=%s failed: %s\n%s",
            job_id, stage, exc, traceback.format_exc(),
        )
        try:
            _set_progress(
                job_id, stage="FAILED", status="failed", error=_friendly_error(exc)
            )
        except Exception:
            log.exception("job_id=%s could not write failure state to DB", job_id)
        raise
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
