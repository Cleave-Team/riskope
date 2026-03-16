import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from riskope.api.routers import companies, corp_search, jobs, taxonomy

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- startup ---
    try:
        from openai import AsyncOpenAI

        from riskope.config import get_settings
        from riskope.dart.corp_index import DartCorpIndex

        settings = get_settings()
        index = DartCorpIndex(
            dart_api_key=settings.dart_api_key,
            openai_client=AsyncOpenAI(api_key=settings.openai_api_key),
            embedding_model=settings.embedding_model,
            embedding_dimensions=settings.embedding_dimensions,
        )
        restored = index.download_from_s3()
        if not restored and not index._table_exists():
            logger.info("Startup: corp index 없음 — DART에서 초기 구축 시작")
            await index.update()
    except Exception:
        logger.warning("Startup: corp index 초기화 실패 (서비스는 계속 실행)", exc_info=True)

    yield
    # --- shutdown ---


def create_app() -> FastAPI:
    app = FastAPI(
        title="Riskope DART Risk Factors API",
        version="0.1.0",
        description="DART 사업보고서 기반 택소노미 정렬 리스크 팩터 추출 API",
        lifespan=lifespan,
    )

    app.include_router(companies.router)
    app.include_router(corp_search.router)
    app.include_router(jobs.router)
    app.include_router(taxonomy.router)

    return app


app = create_app()
