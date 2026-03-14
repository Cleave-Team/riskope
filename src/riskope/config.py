"""설정 관리 — 환경변수 및 기본값."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    """환경 변수에서 로드하는 애플리케이션 설정."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="RISKOPE_",
        extra="ignore",
    )

    # --- API Keys ---
    dart_api_key: str = Field(default="", description="DART Open API 키")
    openai_api_key: str = Field(default="", description="OpenAI API 키")
    massive_api_key: str = Field(default="", description="Massive.com SEC API 키")

    # --- Database ---
    postgres_host: str = Field(default="localhost", validation_alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, validation_alias="POSTGRES_PORT")
    postgres_user: str = Field(default="riskope", validation_alias="POSTGRES_USER")
    postgres_password: str = Field(default="riskope", validation_alias="POSTGRES_PASSWORD")
    postgres_database: str = Field(default="riskope", validation_alias="POSTGRES_DATABASE")

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_database}"
        )

    # --- S3 ---
    s3_bucket: str = Field(default="riskope-filings", description="S3 버킷명")
    s3_region: str = Field(default="ap-northeast-2", description="S3 리전")
    s3_access_key: str = Field(default="", description="AWS access key (빈 값이면 IAM role)")
    s3_secret_key: str = Field(default="", description="AWS secret key")

    # --- LLM 설정 ---
    extraction_model: str = Field(
        default="gpt-4o",
        description="Stage 1 리스크 추출에 사용할 모델",
    )
    judge_model: str = Field(
        default="gpt-4o-mini",
        description="Stage 3 LLM-as-Judge에 사용할 모델",
    )

    # --- 임베딩 설정 ---
    embedding_model: str = Field(
        default="text-embedding-3-small",
        description="OpenAI 임베딩 모델",
    )
    embedding_dimensions: int = Field(
        default=1536,
        description="임베딩 벡터 차원수",
    )

    # --- 파이프라인 설정 ---
    judge_threshold: int = Field(
        default=4,
        description="Stage 3 통과 최소 품질 점수 (1-5)",
    )
    max_concurrent_judge: int = Field(
        default=10,
        description="Stage 3 동시 평가 수",
    )

    # --- 청킹 설정 ---
    chunk_max_chars: int = Field(
        default=12000,
        description="청크 최대 문자 수",
    )
    chunk_overlap_chars: int = Field(
        default=1000,
        description="청크 간 겹침 문자 수",
    )

    # --- 재시도 설정 ---
    extraction_max_retries: int = Field(
        default=3,
        description="Stage 1 추출 최대 재시도 횟수",
    )

    # --- 택소노미 ---
    taxonomy_path_en: Path = Field(
        default=PROJECT_ROOT / "docs" / "massive_risk_categories.md",
        description="영문 택소노미 마크다운 경로",
    )
    taxonomy_path_kr: Path = Field(
        default=PROJECT_ROOT / "docs" / "massive_risk_categories_kr.md",
        description="한국어 택소노미 마크다운 경로",
    )

    # --- 출력 ---
    output_dir: Path = Field(
        default=PROJECT_ROOT / "output",
        description="결과 출력 디렉토리",
    )


def get_settings() -> Settings:
    """싱글턴 설정 인스턴스 반환."""
    return Settings()
