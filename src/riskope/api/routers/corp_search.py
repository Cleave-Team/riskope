"""DART 기업 검색 API 라우터."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from openai import AsyncOpenAI

from riskope.api.schemas import CorpSearchMode, CorpSearchResponse, CorpSearchResult, CorpUpdateResponse
from riskope.config import get_settings
from riskope.dart.corp_index import DartCorpIndex

router = APIRouter(prefix="/api/v1/corps", tags=["corps"])


def _get_index() -> DartCorpIndex:
    settings = get_settings()
    openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
    return DartCorpIndex(
        dart_api_key=settings.dart_api_key,
        openai_client=openai_client,
        embedding_model=settings.embedding_model,
        embedding_dimensions=settings.embedding_dimensions,
    )


@router.post("/update", response_model=CorpUpdateResponse)
async def update_corp_index(force: bool = False):
    """DART 기업 목록을 다운로드하여 검색 인덱스를 업데이트합니다."""
    index = _get_index()
    stats = await index.update(force=force)
    return CorpUpdateResponse(
        total=stats.total,
        new=stats.new,
        changed=stats.changed,
        deleted=stats.deleted,
        embedded=stats.embedded,
    )


@router.get("/search", response_model=CorpSearchResponse)
async def search_corps(
    q: str = Query(..., description="검색어"),
    mode: CorpSearchMode = Query(CorpSearchMode.hybrid, description="검색 모드"),
    limit: int = Query(10, ge=1, le=100, description="결과 수"),
):
    """기업 검색 (FTS / semantic / hybrid)."""
    index = _get_index()
    results = await index.search(q, mode=mode.value, limit=limit)
    return CorpSearchResponse(
        query=q,
        mode=mode,
        results=[CorpSearchResult(**r) for r in results],
        total=len(results),
    )


@router.get("/by-code/{corp_code}", response_model=CorpSearchResult)
async def get_by_corp_code(corp_code: str):
    """DART 고유번호(8자리)로 기업 조회."""
    index = _get_index()
    results = index.search_exact(corp_code=corp_code)
    if not results:
        raise HTTPException(status_code=404, detail=f"corp_code={corp_code} not found")
    return CorpSearchResult(**results[0])


@router.get("/by-stock/{stock_code}", response_model=CorpSearchResult)
async def get_by_stock_code(stock_code: str):
    """종목코드(6자리)로 기업 조회."""
    index = _get_index()
    results = index.search_exact(stock_code=stock_code)
    if not results:
        raise HTTPException(status_code=404, detail=f"stock_code={stock_code} not found")
    return CorpSearchResult(**results[0])
