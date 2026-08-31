"""The version the API reports must be the version that was stamped.

These were two independent facts until 2026-08-31: app/main.py carried a
hardcoded literal while build-version.json was moved by zbump. They drifted by
one build, and nothing noticed - the stamp was not in the image, so the rebuild
hashed identically, compose never recreated the container, and the deploy
reported success while /health kept answering the previous version.

A wrong version is worse than no version: it makes a stale container look
current. So this asserts the two agree, and CI fails the moment they do not.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

# Importing app.main constructs GeoDatabases, which mkdirs the data dir. The
# default is /data, writable in the container and not on a CI runner, so point
# it somewhere disposable BEFORE the import - the same order test_lookup.py
# uses when it sets these inside its fixture.
os.environ.setdefault("EVO_LOCATE_SKIP_BOOT_DOWNLOAD", "1")
os.environ.setdefault("EVO_LOCATE_DATA_DIR", tempfile.mkdtemp(prefix="evolocate-version-"))

from app.main import VERSION, app  # noqa: E402

STAMP = Path(__file__).resolve().parent.parent / "build-version.json"


def test_version_matches_the_build_stamp():
    stamp = json.loads(STAMP.read_text(encoding="utf-8"))["version"].lstrip("v")
    assert VERSION == stamp, (
        f"app reports {VERSION!r} but build-version.json says {stamp!r} - "
        "the stamp is the source of truth; do not hardcode the version"
    )


def test_version_is_a_five_segment_stamp_not_a_fallback():
    # "unknown" means the stamp could not be read - a real failure, not a pass.
    parts = VERSION.split(".")
    assert len(parts) == 5 and all(p.isdigit() for p in parts), VERSION


def test_health_reports_that_same_version():
    from fastapi.testclient import TestClient

    # Status is not asserted: with no databases present /health is legitimately
    # degraded. The version it reports must be right either way - a stale
    # container answering "ok" is exactly the case this guards.
    with TestClient(app) as client:
        body = client.get("/health").json()
    assert body["version"] == VERSION
