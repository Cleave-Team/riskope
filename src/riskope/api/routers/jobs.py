from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from riskope.api.db.models import AnalysisJob
from riskope.api.db.session import get_db
from riskope.api.schemas import JobResponse

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


@router.get("/{job_id}")
async def get_job_status(
    job_id: str,
    db: AsyncSession = Depends(get_db),
) -> JobResponse:
    try:
        job_uuid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="잘못된 job ID 형식입니다")

    job = await db.get(AnalysisJob, job_uuid)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id}을 찾을 수 없습니다")

    return JobResponse(
        job_id=str(job.id),
        status=job.status,
        progress=job.progress,
        error_message=job.error_message,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
    )
