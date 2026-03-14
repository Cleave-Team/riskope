"""TaxonomyMapper 테스트 — OpenAI 임베딩 + LanceDB 캐시 기반 택소노미 매핑."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from riskope.models import ExtractedRisk, TaxonomyCategory
from riskope.pipeline.mapper import TaxonomyMapper


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_category(primary: str, secondary: str, tertiary: str, desc: str, desc_kr: str = "") -> TaxonomyCategory:
    return TaxonomyCategory(
        primary=primary,
        secondary=secondary,
        tertiary=tertiary,
        description=desc,
        description_kr=desc_kr,
        key=f"{primary}/{secondary}/{tertiary}",
    )


@dataclass
class _FakeEmbeddingItem:
    embedding: list[float]


@dataclass
class _FakeEmbedResponse:
    data: list[_FakeEmbeddingItem]


def _make_fake_openai_embed(dim: int = 1536):
    async def _create(model: str, input: list[str], dimensions: int = dim):
        items = []
        for text in input:
            rng = np.random.RandomState(hash(text) % 2**31)
            vec = rng.randn(dimensions).tolist()
            items.append(_FakeEmbeddingItem(embedding=vec))
        return _FakeEmbedResponse(data=items)

    return _create


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.fixture
def mapper(tmp_path: Path):
    mock_client = MagicMock()
    mock_client.embeddings = MagicMock()
    mock_client.embeddings.create = AsyncMock(side_effect=_make_fake_openai_embed())

    m = TaxonomyMapper(
        client=mock_client,
        model="text-embedding-3-small",
        dimensions=1536,
        data_dir=tmp_path / "test_data",
    )
    return m


@pytest.fixture
def sample_categories() -> list[TaxonomyCategory]:
    return [
        _make_category(
            "Strategic", "Market", "Competition Risk", "Risk of losing market share", "시장점유율 하락 위험"
        ),
        _make_category(
            "Financial", "Credit", "Default Risk", "Risk of counterparty default", "거래상대방 채무불이행 위험"
        ),
        _make_category("Operational", "Tech", "Cyber Risk", "Risk of cybersecurity breach", "사이버보안 침해 위험"),
    ]


@pytest.mark.asyncio
async def test_precompute_taxonomy(mapper, sample_categories):
    await mapper.precompute_taxonomy(sample_categories)

    assert mapper._category_embeddings is not None
    assert mapper._category_embeddings.shape == (3, 1536)
    assert len(mapper._categories) == 3


@pytest.mark.asyncio
async def test_map_risks_returns_mappings(mapper, sample_categories):
    await mapper.precompute_taxonomy(sample_categories)

    risks = [
        ExtractedRisk(tag="시장 경쟁 심화", supporting_quote="경쟁이 심화되어 시장점유율이 하락할 위험이 있습니다."),
        ExtractedRisk(
            tag="사이버 공격", supporting_quote="해킹 등 사이버 공격으로 인한 정보 유출 가능성이 존재합니다."
        ),
    ]

    mappings = await mapper.map_risks(risks)

    assert len(mappings) == 2
    for m in mappings:
        assert m.extracted_risk in risks
        assert m.category in sample_categories
        assert m.similarity_score > -1.0


@pytest.mark.asyncio
async def test_map_risks_empty_input(mapper, sample_categories):
    await mapper.precompute_taxonomy(sample_categories)
    mappings = await mapper.map_risks([])
    assert mappings == []


@pytest.mark.asyncio
async def test_map_risks_without_precompute_raises(mapper):
    risks = [ExtractedRisk(tag="test", supporting_quote="test quote")]
    with pytest.raises(RuntimeError, match="precompute_taxonomy"):
        await mapper.map_risks(risks)


@pytest.mark.asyncio
async def test_embed_calls_openai_with_correct_params(mapper, sample_categories):
    await mapper.precompute_taxonomy(sample_categories)

    embed_mock = mapper._client.embeddings.create
    assert embed_mock.call_count >= 1

    for call in embed_mock.call_args_list:
        assert call.kwargs["model"] == "text-embedding-3-small"
        assert call.kwargs["dimensions"] == 1536
        assert isinstance(call.kwargs["input"], list)


def test_mapper_stores_config():
    mock_client = MagicMock()
    m = TaxonomyMapper(client=mock_client, model="text-embedding-3-large", dimensions=3072)
    assert m._model == "text-embedding-3-large"
    assert m._dimensions == 3072


@pytest.mark.asyncio
async def test_lancedb_cache_hit_skips_api(tmp_path: Path, sample_categories):
    """두 번째 precompute_taxonomy 호출 시 LanceDB 캐시에서 로드하여 API 호출 없음."""
    mock_client = MagicMock()
    mock_client.embeddings = MagicMock()
    mock_client.embeddings.create = AsyncMock(side_effect=_make_fake_openai_embed())

    mapper1 = TaxonomyMapper(
        client=mock_client,
        model="text-embedding-3-small",
        dimensions=1536,
        data_dir=tmp_path / "shared_data",
    )
    await mapper1.precompute_taxonomy(sample_categories)
    first_call_count = mock_client.embeddings.create.call_count
    assert first_call_count >= 1

    mapper2 = TaxonomyMapper(
        client=mock_client,
        model="text-embedding-3-small",
        dimensions=1536,
        data_dir=tmp_path / "shared_data",
    )
    await mapper2.precompute_taxonomy(sample_categories)

    assert mock_client.embeddings.create.call_count == first_call_count
    assert mapper2._category_embeddings is not None
    assert mapper2._category_embeddings.shape == (3, 1536)
    assert mapper1._category_embeddings is not None
    np.testing.assert_allclose(mapper1._category_embeddings, mapper2._category_embeddings, atol=1e-6)


@pytest.mark.asyncio
async def test_lancedb_creates_db_directory(tmp_path: Path, sample_categories):
    """precompute_taxonomy가 LanceDB 디렉토리를 자동 생성하는지 확인."""
    mock_client = MagicMock()
    mock_client.embeddings = MagicMock()
    mock_client.embeddings.create = AsyncMock(side_effect=_make_fake_openai_embed())

    data_dir = tmp_path / "new_data"
    mapper = TaxonomyMapper(
        client=mock_client,
        model="text-embedding-3-small",
        dimensions=1536,
        data_dir=data_dir,
    )
    await mapper.precompute_taxonomy(sample_categories)

    db_path = data_dir / "taxonomy.lancedb"
    assert db_path.exists()
