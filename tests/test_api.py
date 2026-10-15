"""API contract tests for the Viral Shorts AI backend (FastAPI TestClient).

Covers: health, POST /api/jobs validation, unknown job progress -> 404,
unknown clip download -> 404.

Only boto3 / celery are mocked (external services) - never app logic.
"""

# Endpoint shapes below follow the real backend (shared/schemas.py):
#   GET  /api/health
#   POST /api/jobs  {"upload_id", "language", "num_shorts",
#                    "clip_duration_min", "clip_duration_max"}
#   GET  /api/jobs/{id}/progress
#   GET  /api/clips/{id}/download


def _job_payload(**overrides):
    payload = {
        "upload_id": "f" * 32,  # well-formed but not completed -> 422 at route level
        "language": "en",
        "num_shorts": 3,
        "clip_duration_min": 30,
        "clip_duration_max": 60,
    }
    payload.update(overrides)
    return payload


def test_health_returns_200(api_client):
    resp = api_client.get("/api/health")
    assert resp.status_code == 200, resp.text


def test_create_job_rejects_invalid_language(api_client):
    resp = api_client.post("/api/jobs", json=_job_payload(language="xx"))
    assert resp.status_code == 422, resp.text


def test_create_job_rejects_too_many_shorts(api_client):
    resp = api_client.post("/api/jobs", json=_job_payload(num_shorts=99))
    assert resp.status_code == 422, resp.text


def test_create_job_rejects_zero_shorts(api_client):
    resp = api_client.post("/api/jobs", json=_job_payload(num_shorts=0))
    assert resp.status_code == 422, resp.text


def test_create_job_rejects_invalid_clip_duration(api_client):
    resp = api_client.post("/api/jobs", json=_job_payload(clip_duration_min=999))
    assert resp.status_code == 422, resp.text


def test_create_job_rejects_min_above_max(api_client):
    resp = api_client.post(
        "/api/jobs",
        json=_job_payload(clip_duration_min=60, clip_duration_max=30),
    )
    assert resp.status_code == 422, resp.text


def test_unknown_job_progress_returns_404(api_client):
    resp = api_client.get("/api/jobs/job_does_not_exist_123/progress")
    assert resp.status_code == 404, resp.text


def test_unknown_clip_download_returns_404(api_client):
    resp = api_client.get("/api/clips/clip_does_not_exist_123/download")
    assert resp.status_code == 404, resp.text
