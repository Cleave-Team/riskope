from __future__ import annotations

from fastapi import APIRouter

from riskope.api.schemas import TaxonomyCategoryResponse
from riskope.config import get_settings
from riskope.taxonomy.loader import load_taxonomy

router = APIRouter(prefix="/api/v1", tags=["taxonomy"])


@router.get("/taxonomy")
async def get_taxonomy() -> list[TaxonomyCategoryResponse]:
    settings = get_settings()
    categories = load_taxonomy(en_path=settings.taxonomy_path_en, kr_path=settings.taxonomy_path_kr)
    return [
        TaxonomyCategoryResponse(
            primary=c.primary,
            secondary=c.secondary,
            tertiary=c.tertiary,
            description=c.description,
        )
        for c in categories
    ]


@router.get("/health")
async def health_check():
    return {"status": "ok"}
