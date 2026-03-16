import logging

from fastapi import FastAPI

from riskope.api.routers import companies, jobs, taxonomy

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Riskope DART Risk Factors API",
        version="0.1.0",
        description="DART 사업보고서 기반 택소노미 정렬 리스크 팩터 추출 API",
    )

    app.include_router(companies.router)
    app.include_router(jobs.router)
    app.include_router(taxonomy.router)

    return app


app = create_app()
