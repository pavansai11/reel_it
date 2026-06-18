"""End-to-end API test: upload -> job (inline) -> status -> result -> action.

This is the integration check for Phase 5 -- the whole flywheel loop over HTTP.
With RUN_JOBS_INLINE=true the pipeline runs synchronously inside POST /job, so by
the time it returns the reel is rendered.
"""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client(sample_dir):
    from app.db import init_db
    from app.main import app

    init_db()
    return TestClient(app)


def _files(sample_dir: Path):
    out = []
    for p in sorted(sample_dir.iterdir()):
        ctype = "video/mp4" if p.suffix == ".mp4" else "image/jpeg"
        out.append(("files", (p.name, p.read_bytes(), ctype)))
    return out


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_full_flow(client, sample_dir):
    # 1. upload
    r = client.post("/upload", files=_files(sample_dir))
    assert r.status_code == 200, r.text
    body = r.json()
    asset_ids = [a["id"] for a in body["assets"]]
    assert len(asset_ids) >= 4

    # 2. create job (runs inline -> renders synchronously)
    r = client.post("/job", json={"vibe": "energetic", "asset_ids": asset_ids})
    assert r.status_code == 200, r.text
    job_id = r.json()["job_id"]

    # 3. status should be done
    r = client.get(f"/job/{job_id}/status")
    assert r.status_code == 200
    status = r.json()
    assert status["status"] == "done", status
    assert status["stage_progress"] == 1.0

    # 4. result has a url + an EDL
    r = client.get(f"/job/{job_id}/result")
    assert r.status_code == 200
    result = r.json()
    assert result["result_url"]
    assert result["edl"] and result["edl"]["decisions"]

    # the rendered file exists on disk and is non-trivial
    from app.storage import get_storage, result_key

    path = get_storage().local_path(result_key(job_id))
    assert Path(path).exists() and Path(path).stat().st_size > 50_000

    # 5. flywheel: log actions
    for action in ("downloaded", "accepted"):
        r = client.post(f"/job/{job_id}/action", json={"action": action})
        assert r.status_code == 200

    # action was persisted
    from app.db import session_scope
    from app.models import UserAction

    with session_scope() as s:
        n = s.query(UserAction).filter(UserAction.job_id == job_id).count()
    assert n == 2


def test_unknown_vibe_rejected(client, sample_dir):
    r = client.post("/upload", files=_files(sample_dir))
    asset_ids = [a["id"] for a in r.json()["assets"]]
    r = client.post("/job", json={"vibe": "nonsense", "asset_ids": asset_ids})
    assert r.status_code == 400


def test_bad_action_rejected(client, sample_dir):
    r = client.post("/upload", files=_files(sample_dir))
    asset_ids = [a["id"] for a in r.json()["assets"]]
    job_id = client.post("/job", json={"vibe": "energetic", "asset_ids": asset_ids}).json()["job_id"]
    r = client.post(f"/job/{job_id}/action", json={"action": "explode"})
    assert r.status_code == 400
