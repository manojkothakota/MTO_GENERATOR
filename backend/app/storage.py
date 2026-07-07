"""
In-memory job store. Sufficient for this assessment (single-process,
no persistence required). Documented as a limitation in the README.
"""
import uuid
from typing import Dict

from app.models import Job, JobStatus, MTOResult

_JOBS: Dict[str, Job] = {}


def create_job(filename: str) -> Job:
    job = Job(job_id=str(uuid.uuid4()), status=JobStatus.PROCESSING, filename=filename)
    _JOBS[job.job_id] = job
    return job


def get_job(job_id: str) -> Job | None:
    return _JOBS.get(job_id)


def complete_job(job_id: str, result: MTOResult) -> None:
    job = _JOBS[job_id]
    job.status = JobStatus.DONE
    job.result = result


def fail_job(job_id: str, error: str) -> None:
    job = _JOBS[job_id]
    job.status = JobStatus.ERROR
    job.error = error
