"""
FastAPI backend for the Isometric -> MTO generator.

Design note (documented per brief Section 3.2): we process the upload
synchronously inside POST /api/upload and store the finished job
immediately, rather than running a background worker. For a single
Gemini call (a few seconds) this keeps the design simple; GET /api/mto/{id}
still exists per the suggested contract so the frontend polls a stable
shape, and the same endpoint would work unchanged if we later moved
extraction to a background task/queue (a documented "next step").
"""
import csv
import io
import os

from pathlib import Path
from dotenv import load_dotenv

# encoding="utf-8-sig" tolerates a UTF-8 BOM, which Notepad on Windows
# silently adds when saving .env — without this, os.getenv("GEMINI_API_KEY")
# can return None even though the file "looks" correct. We also point
# dotenv_path explicitly at backend/.env so it doesn't depend on cwd.
load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env", encoding="utf-8-sig")

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse

from app.models import JobStatus
from app.pipeline import run_pipeline
from app import storage

MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB, per brief 3.1
ALLOWED_CONTENT_TYPES = {"image/png", "image/jpeg", "image/jpg", "application/pdf"}

app = FastAPI(title="Isometric MTO Generator API")

origins = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    provider = os.getenv("AI_PROVIDER", "").strip().lower()
    if not provider:
        if os.getenv("GROQ_API_KEY"):
            provider = "groq"
        elif os.getenv("GEMINI_API_KEY"):
            provider = "gemini"
        else:
            provider = "mock"
    return {"status": "ok", "active_provider": provider}


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{file.content_type}'. "
                   f"Allowed: PNG, JPG, PDF.",
        )

    contents = await file.read()
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File too large ({len(contents) / 1_000_000:.1f} MB). Max 20 MB.",
        )
    if len(contents) == 0:
        raise HTTPException(status_code=400, detail="Empty file.")

    job = storage.create_job(filename=file.filename)

    try:
        result = run_pipeline(contents, file.content_type, file.filename)
        storage.complete_job(job.job_id, result)
    except Exception as exc:  # belt-and-suspenders; run_pipeline shouldn't raise
        storage.fail_job(job.job_id, str(exc))
        raise HTTPException(status_code=500, detail=f"Processing failed: {exc}")

    return {"job_id": job.job_id}


@app.get("/api/mto/{job_id}")
def get_mto(job_id: str):
    job = storage.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job.status == JobStatus.ERROR:
        return JSONResponse(
            status_code=500,
            content={"status": job.status, "error": job.error},
        )
    return {
        "status": job.status,
        "filename": job.filename,
        "result": job.result.model_dump() if job.result else None,
    }


@app.get("/api/mto/{job_id}/csv")
def get_mto_csv(job_id: str):
    job = storage.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job.status != JobStatus.DONE or job.result is None:
        raise HTTPException(status_code=400, detail="MTO not ready.")

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        "item_no", "category", "description", "size_nps", "schedule_rating",
        "material_spec", "end_type", "quantity", "unit", "length_m",
        "confidence", "remarks",
    ])
    for item in job.result.items:
        writer.writerow([
            item.item_no, item.category.value, item.description, item.size_nps,
            item.schedule_rating, item.material_spec, item.end_type,
            item.quantity, item.unit.value, item.length_m, item.confidence,
            item.remarks,
        ])
    buffer.seek(0)

    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=mto_{job_id[:8]}.csv"},
    )
