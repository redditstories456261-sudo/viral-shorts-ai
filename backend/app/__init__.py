"""Backend application package.

Ensures the project root (the directory containing ``backend/``) is on
``sys.path`` so the shared contract package (``shared``) can be imported
with plain absolute imports like ``from shared.config import settings``.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

__all__: list[str] = []
