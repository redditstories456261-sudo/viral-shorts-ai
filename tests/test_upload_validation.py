"""Tests for POST /api/upload/init validation (mime type + size limits).

Strategy, per the test plan:
  1. If the backend exposes validation as importable helper functions
     (secure/sanitize filename, mime check, size check), exercise them directly.
  2. Always exercise the HTTP contract via FastAPI TestClient.

Only boto3 / celery are mocked (external services) - never app logic.
"""

import importlib

import pytest

# ---------------------------------------------------------------------------
# 1. Direct helper tests (run only if the backend exposes such functions)
# ---------------------------------------------------------------------------

_HELPER_MODULE_CANDIDATES = [
    "backend.app.api.routes",  # actual location of secure_filename
    "backend.app.routers.upload",
    "backend.app.api.upload",
    "backend.app.api.routes.upload",
    "backend.app.utils.validation",
    "backend.app.validation",
]

_INTERESTING_NAMES = (
    "secure_filename",
    "sanitize_filename",
    "validate_mime_type",
    "validate_mime",
    "validate_file_size",
    "validate_size",
    "validate_upload",
)


def _load_helpers():
    for modname in _HELPER_MODULE_CANDIDATES:
        try:
            module = importlib.import_module(modname)
        except ImportError:
            continue
        found = {
            name: getattr(module, name)
            for name in _INTERESTING_NAMES
            if callable(getattr(module, name, None))
        }
        if found:
            return module, found
    return None, {}


_HELPERS_MODULE, _HELPERS = _load_helpers()


def _helper_or_skip(*names):
    """Return the first exposed helper among *names*, else skip the test."""
    for name in names:
        if name in _HELPERS:
            return _HELPERS[name]
    pytest.skip(f"backend does not expose any of {names} as importable functions")


def test_secure_filename_strips_path_traversal():
    fn = _helper_or_skip("secure_filename", "sanitize_filename")
    cleaned = fn("../../etc/passwd")
    assert ".." not in cleaned
    assert "/" not in cleaned and "\\" not in cleaned
    assert cleaned, "sanitised filename must not be empty"


def test_secure_filename_keeps_plain_name():
    fn = _helper_or_skip("secure_filename", "sanitize_filename")
    assert fn("my clip (final).mp4").endswith(".mp4")


def test_mime_validation_rejects_text_plain():
    fn = _helper_or_skip("validate_mime_type", "validate_mime", "validate_upload")
    with pytest.raises(Exception):
        fn("text/plain", 1024)


def test_mime_validation_accepts_mp4():
    fn = _helper_or_skip("validate_mime_type", "validate_mime", "validate_upload")
    fn("video/mp4", 1024)  # must not raise


def test_size_validation_rejects_oversize():
    fn = _helper_or_skip("validate_file_size", "validate_size", "validate_upload")
    with pytest.raises(Exception):
        fn("video/mp4", 50 * 1024**3)  # 50 GiB - over any sane upload limit


# ---------------------------------------------------------------------------
# 2. HTTP contract tests via TestClient
# ---------------------------------------------------------------------------

def _init_payload(filename="clip.mp4", mime="video/mp4", size=50 * 1024**2):
    return {"filename": filename, "mime_type": mime, "total_size": size}


def test_init_rejects_text_plain_mime(api_client):
    resp = api_client.post("/api/upload/init", json=_init_payload(mime="text/plain"))
    assert resp.status_code == 422, resp.text


def test_init_rejects_oversize_total_size(api_client):
    # Limit is settings.max_upload_gb (default 5 GB); 50 GB must be rejected.
    resp = api_client.post(
        "/api/upload/init", json=_init_payload(size=50 * 1024**3)
    )
    assert resp.status_code == 422, resp.text


def test_init_rejects_empty_filename(api_client):
    resp = api_client.post("/api/upload/init", json=_init_payload(filename=""))
    assert resp.status_code in (400, 422), resp.text


def test_init_accepts_good_mp4(api_client):
    resp = api_client.post("/api/upload/init", json=_init_payload())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("upload_id"), f"no upload_id in {body}"
