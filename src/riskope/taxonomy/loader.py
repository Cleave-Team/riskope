"""마크다운 택소노미 파일을 파싱하여 구조화된 카테고리 목록으로 변환."""

from __future__ import annotations

import functools
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from riskope.models import TaxonomyCategory

logger = logging.getLogger(__name__)


@dataclass
class KrLabel:
    """한글 카테고리 이름 및 설명."""

    primary_kr: str = ""
    secondary_kr: str = ""
    tertiary_kr: str = ""
    description_kr: str = ""


@functools.lru_cache(maxsize=1)
def load_kr_lookup(en_path: Path, kr_path: Path) -> dict[str, KrLabel]:
    """EN key → 한글 이름/설명 매핑 딕셔너리를 빌드한다 (캐시됨).

    EN 파일의 snake_case 키와 KR 파일의 원본 한글 이름을 인덱스 기반으로 매칭.
    """
    en_categories = _parse_markdown(en_path)
    kr_raw = _parse_markdown_raw(kr_path)

    lookup: dict[str, KrLabel] = {}

    if len(en_categories) != len(kr_raw):
        logger.warning(
            "EN(%d)과 KR(%d) 카테고리 수 불일치 — KR lookup 비활성화",
            len(en_categories),
            len(kr_raw),
        )
        return lookup

    for en_cat, kr_entry in zip(en_categories, kr_raw):
        lookup[en_cat.key] = KrLabel(
            primary_kr=kr_entry["primary"],
            secondary_kr=kr_entry["secondary"],
            tertiary_kr=kr_entry["tertiary"],
            description_kr=kr_entry["description"],
        )

    return lookup


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


def _to_snake_case(name: str) -> str:
    normalized = re.sub(r"[()·,]", "", name)
    normalized = re.sub(r"\s+", "_", normalized.strip())
    return normalized.lower()


def _parse_markdown(path: Path) -> list[TaxonomyCategory]:
    """단일 마크다운 파일에서 카테고리를 파싱."""
    text = path.read_text(encoding="utf-8")

    categories: list[TaxonomyCategory] = []
    current_primary = ""
    current_secondary = ""

    primary_pattern = re.compile(r"^##\s+\d+\.\s+(.+)$", re.MULTILINE)
    secondary_pattern = re.compile(r"^###\s+\d+-[a-z]\.\s+(.+)$", re.MULTILINE)
    row_pattern = re.compile(
        r"^\|\s*\d+\s*\|\s*\*\*(.+?)\*\*\s*\|\s*(.+?)\s*\|$",
        re.MULTILINE,
    )

    lines = text.split("\n")
    for line in lines:
        primary_match = primary_pattern.match(line)
        if primary_match:
            current_primary = _to_snake_case(primary_match.group(1).strip())
            continue

        secondary_match = secondary_pattern.match(line)
        if secondary_match:
            current_secondary = _to_snake_case(secondary_match.group(1).strip())
            continue

        row_match = row_pattern.match(line)
        if row_match and current_primary and current_secondary:
            tertiary = _to_snake_case(row_match.group(1).strip())
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


def _parse_markdown_raw(path: Path) -> list[dict[str, str]]:
    """마크다운 파일에서 원본 이름을 보존하여 파싱 (snake_case 변환 없음)."""
    text = path.read_text(encoding="utf-8")

    entries: list[dict[str, str]] = []
    current_primary = ""
    current_secondary = ""

    primary_pattern = re.compile(r"^##\s+\d+\.\s+(.+)$", re.MULTILINE)
    secondary_pattern = re.compile(r"^###\s+\d+-[a-z]\.\s+(.+)$", re.MULTILINE)
    row_pattern = re.compile(
        r"^\|\s*\d+\s*\|\s*\*\*(.+?)\*\*\s*\|\s*(.+?)\s*\|$",
        re.MULTILINE,
    )

    for line in text.split("\n"):
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
            entries.append({
                "primary": current_primary,
                "secondary": current_secondary,
                "tertiary": row_match.group(1).strip(),
                "description": row_match.group(2).strip(),
            })

    return entries
