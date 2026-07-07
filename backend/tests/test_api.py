"""
Meaningful-but-small test suite:
- schema validation (Pydantic models)
- mock MTO generator produces valid, internally-consistent data
- endpoint happy path (upload -> job -> mto -> csv) using mock pipeline
  (no GEMINI_API_KEY set in test env, so run_pipeline uses the mock path)
"""
import os
import io

os.environ.pop("GEMINI_API_KEY", None)  # force mock mode for these tests

from fastapi.testclient import TestClient
from app.main import app
from app.mock_data import build_mock_mto
from app.models import MTOItem, Category, Unit

client = TestClient(app)


def test_mock_mto_is_valid_and_consistent():
    result = build_mock_mto("test.png")
    assert result.mode == "mock"
    assert len(result.items) > 0
    pipe_rows = [i for i in result.items if i.category == Category.PIPE]
    assert all(i.unit == Unit.EA or i.category != Category.PIPE for i in result.items if i.category != Category.PIPE)
    # pipe is quantified by length
    assert all(p.length_m is not None for p in pipe_rows)
    # summary total pipe length matches item length
    assert result.summary.total_pipe_length_m == sum(p.length_m for p in pipe_rows)


def test_mtoitem_rejects_bad_category():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        MTOItem(item_no=1, category="NOT_A_CATEGORY", description="x",
                 size_nps='6"', quantity=1, unit="EA")


def test_health_endpoint():
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_upload_rejects_bad_content_type():
    resp = client.post(
        "/api/upload",
        files={"file": ("test.txt", io.BytesIO(b"hello"), "text/plain")},
    )
    assert resp.status_code == 400


def test_upload_happy_path_mock_mode():
    # A 1x1 PNG's worth of bytes is enough; the mock pipeline never
    # actually reads pixel data when no GEMINI_API_KEY is configured.
    fake_png = io.BytesIO(
        b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    )
    resp = client.post(
        "/api/upload",
        files={"file": ("test.png", fake_png, "image/png")},
    )
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    mto_resp = client.get(f"/api/mto/{job_id}")
    assert mto_resp.status_code == 200
    body = mto_resp.json()
    assert body["status"] == "done"
    assert body["result"]["mode"] == "mock"
    assert len(body["result"]["items"]) > 0

    csv_resp = client.get(f"/api/mto/{job_id}/csv")
    assert csv_resp.status_code == 200
    assert csv_resp.headers["content-type"].startswith("text/csv")
    assert b"item_no" in csv_resp.content
