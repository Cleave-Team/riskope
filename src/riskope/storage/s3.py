from __future__ import annotations

import logging
from functools import lru_cache

import boto3
from botocore.exceptions import ClientError

from riskope.config import get_settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_s3_client():
    settings = get_settings()
    return boto3.client(
        "s3",
        region_name=settings.s3_region,
        aws_access_key_id=settings.s3_access_key or None,
        aws_secret_access_key=settings.s3_secret_key or None,
    )


def build_s3_path(corp_code: str, report_year: int, rcept_no: str) -> str:
    return f"dart/filings/{corp_code}/{report_year}/{rcept_no}.md"


def upload_markdown(content: str, corp_code: str, report_year: int, rcept_no: str) -> str:
    settings = get_settings()
    s3_key = build_s3_path(corp_code, report_year, rcept_no)

    try:
        _get_s3_client().put_object(
            Bucket=settings.s3_bucket,
            Key=s3_key,
            Body=content.encode("utf-8"),
            ContentType="text/markdown; charset=utf-8",
        )
        full_path = f"s3://{settings.s3_bucket}/{s3_key}"
        logger.info("S3 업로드 완료: %s (%d bytes)", full_path, len(content))
        return full_path
    except ClientError:
        logger.exception("S3 업로드 실패: %s", s3_key)
        raise


def download_markdown(s3_path: str) -> str | None:
    settings = get_settings()
    s3_key = s3_path.replace(f"s3://{settings.s3_bucket}/", "")

    try:
        resp = _get_s3_client().get_object(Bucket=settings.s3_bucket, Key=s3_key)
        return resp["Body"].read().decode("utf-8")
    except ClientError:
        logger.warning("S3 다운로드 실패: %s", s3_key)
        return None
