"""마크다운 택소노미 파일을 파싱하여 구조화된 카테고리 목록으로 변환."""

from __future__ import annotations

import re
from pathlib import Path

from riskope.models import TaxonomyCategory


def load_taxonomy(en_path: Path, kr_path: Path | None = None) -> list[TaxonomyCategory]:
    """영문/한국어 택소노미 마크다운을 파싱하여 TaxonomyCategory 리스트 반환.

    EN/KR 파일의 키가 서로 다른 언어이므로 위치(인덱스) 기반으로 매칭한다.
    두 파일 모두 동일한 순서로 140개 카테고리를 가지고 있어야 한다.
    """
    en_categories = _parse_markdown(en_path)

    kr_descriptions: list[str] = []
    if kr_path and kr_path.exists():
        kr_categories = _parse_markdown(kr_path)
        if len(kr_categories) == len(en_categories):
            kr_descriptions = [cat.description for cat in kr_categories]
        else:
            import logging

            logging.getLogger(__name__).warning(
                "EN(%d)과 KR(%d) 카테고리 수 불일치 — KR 설명 생략",
                len(en_categories),
                len(kr_categories),
            )

    categories: list[TaxonomyCategory] = []
    for i, cat in enumerate(en_categories):
        categories.append(
            TaxonomyCategory(
                primary=cat.primary,
                secondary=cat.secondary,
                tertiary=cat.tertiary,
                description=cat.description,
                description_kr=kr_descriptions[i] if i < len(kr_descriptions) else "",
                key=cat.key,
            )
        )

    return categories


def _parse_markdown(path: Path) -> list[TaxonomyCategory]:
    """단일 마크다운 파일에서 카테고리를 파싱."""
    text = path.read_text(encoding="utf-8")

    categories: list[TaxonomyCategory] = []
    current_primary = ""
    current_secondary = ""

    # ## N. Primary Category
    primary_pattern = re.compile(r"^##\s+\d+\.\s+(.+)$", re.MULTILINE)
    # ### N-x. Secondary Category
    secondary_pattern = re.compile(r"^###\s+\d+-[a-z]\.\s+(.+)$", re.MULTILINE)
    # 테이블 행: | N | **Tertiary** | Description |
    row_pattern = re.compile(
        r"^\|\s*\d+\s*\|\s*\*\*(.+?)\*\*\s*\|\s*(.+?)\s*\|$",
        re.MULTILINE,
    )

    lines = text.split("\n")
    for line in lines:
        primary_match = primary_pattern.match(line)
        if primary_match:
            current_primary = primary_match.group(1).strip()
            continue

        secondary_match = secondary_pattern.match(line)
        if secondary_match:
            current_secondary = secondary_match.group(1).strip()
            continue

        row_match = row_pattern.match(line)
        if row_match and current_primary and current_secondary:
            tertiary = row_match.group(1).strip()
            description = row_match.group(2).strip()
            key = f"{current_primary}/{current_secondary}/{tertiary}"

            categories.append(
                TaxonomyCategory(
                    primary=current_primary,
                    secondary=current_secondary,
                    tertiary=tertiary,
                    description=description,
                    key=key,
                )
            )

    return categories
