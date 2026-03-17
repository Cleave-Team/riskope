"""Stage 2: 임베딩 기반 택소노미 매핑.

논문 설계:
- 택소노미 카테고리 description을 사전 임베딩
- 추출된 리스크의 supporting_quote를 런타임 임베딩
- 코사인 유사도로 nearest neighbor 매핑
- Task instruction으로 임베딩 품질 향상
- 택소노미 임베딩은 LanceDB에 저장하여 재사용
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import numpy as np
from openai import AsyncOpenAI

from riskope.models import ExtractedRisk, TaxonomyCategory, TaxonomyMapping
from riskope.tracing import observe

logger = logging.getLogger(__name__)

_TASK_INSTRUCTION_KR = "한국어 기업 사업보고서의 리스크 텍스트를 가장 적합한 택소노미 카테고리로 분류하세요."

_TASK_INSTRUCTION_EN = "Classify risk factor text from an annual report into the most appropriate taxonomy category."

_TASK_INSTRUCTIONS = {"kr": _TASK_INSTRUCTION_KR, "en": _TASK_INSTRUCTION_EN}

# 기본 캐시 디렉토리
_THIS_DIR = Path(__file__).resolve().parent.parent.parent.parent
_DEFAULT_DATA_DIR = _THIS_DIR / "data" if (_THIS_DIR / "data").exists() else Path("/app/data")


class TaxonomyMapper:
    """Stage 2: 임베딩 유사도로 추출된 리스크를 택소노미에 매핑."""

    def __init__(
        self,
        client: AsyncOpenAI,
        model: str = "text-embedding-3-small",
        dimensions: int = 1536,
        data_dir: Path | None = None,
        locale: str = "kr",
    ) -> None:
        self._client = client
        self._model = model
        self._dimensions = dimensions
        self._data_dir = data_dir or _DEFAULT_DATA_DIR
        self._locale = locale
        self._task_instruction = _TASK_INSTRUCTIONS.get(locale, _TASK_INSTRUCTION_KR)

        self._categories: list[TaxonomyCategory] = []
        self._category_embeddings: np.ndarray | None = None

    def _table_name(self, categories: list[TaxonomyCategory]) -> str:
        """택소노미 + 모델 + 차원수 + locale 기반 LanceDB 테이블 이름 생성."""
        parts = [
            self._model,
            str(self._dimensions),
            self._locale,
            *(f"{c.primary}/{c.secondary}/{c.tertiary}" for c in categories),
        ]
        content = "\n".join(parts)
        h = hashlib.sha256(content.encode()).hexdigest()[:16]
        return f"taxonomy_{h}"

    def _db_path(self) -> Path:
        """LanceDB 데이터베이스 경로."""
        return self._data_dir / "taxonomy.lancedb"

    def _open_db(self):
        """LanceDB 데이터베이스 연결."""
        import lancedb

        self._data_dir.mkdir(parents=True, exist_ok=True)
        return lancedb.connect(str(self._db_path()))

    def _load_from_db(self, table_name: str) -> np.ndarray | None:
        """LanceDB에서 택소노미 임베딩 로드."""
        try:
            db = self._open_db()
            existing_tables = db.list_tables()
            table_list = existing_tables.tables if hasattr(existing_tables, "tables") else list(existing_tables)
            if table_name not in table_list:
                return None

            table = db.open_table(table_name)
            arrow_table = table.to_arrow()

            if arrow_table.num_rows != len(self._categories):
                logger.warning(
                    "LanceDB 테이블 행 수 불일치 (%d != %d), 재계산 필요",
                    arrow_table.num_rows,
                    len(self._categories),
                )
                return None

            # category_key 순서로 정렬하여 self._categories와 일치시킴
            key_order = {cat.key: i for i, cat in enumerate(self._categories)}
            keys = arrow_table.column("category_key").to_pylist()
            vectors = arrow_table.column("vector").to_pylist()
            embeddings = np.zeros((len(self._categories), self._dimensions), dtype=np.float32)

            for row_idx, key in enumerate(keys):
                idx = key_order.get(key)
                if idx is None:
                    logger.warning(
                        "LanceDB에 알 수 없는 카테고리 키: %s, 재계산 필요",
                        key,
                    )
                    return None
                embeddings[idx] = np.array(vectors[row_idx], dtype=np.float32)

            logger.info("택소노미 임베딩 LanceDB 로드: 테이블=%s", table_name)
            return embeddings
        except Exception:
            logger.warning("LanceDB 로드 실패, 재계산 필요", exc_info=True)
            return None

    def _save_to_db(
        self,
        table_name: str,
        categories: list[TaxonomyCategory],
        embeddings: np.ndarray,
    ) -> None:
        """택소노미 임베딩을 LanceDB에 저장."""
        try:
            db = self._open_db()

            data = []
            for i, cat in enumerate(categories):
                data.append(
                    {
                        "category_key": cat.key,
                        "primary": cat.primary,
                        "secondary": cat.secondary,
                        "tertiary": cat.tertiary,
                        "description": cat.description,
                        "description_kr": cat.description_kr or "",
                        "vector": embeddings[i].tolist(),
                    }
                )

            # mode="overwrite"로 기존 테이블 대체
            db.create_table(table_name, data=data, mode="overwrite")
            logger.info(
                "택소노미 임베딩 LanceDB 저장: 테이블=%s, %d 카테고리",
                table_name,
                len(categories),
            )
        except Exception:
            logger.error("LanceDB 저장 실패", exc_info=True)
            raise

    @observe(name="stage2-precompute-taxonomy")
    async def precompute_taxonomy(self, categories: list[TaxonomyCategory]) -> None:
        """택소노미 카테고리 description을 사전 임베딩 계산.

        LanceDB 캐시가 존재하면 API 호출 없이 로드.

        Args:
            categories: 택소노미 카테고리 목록 (140개).
        """
        self._categories = categories
        table_name = self._table_name(categories)

        # LanceDB에서 로드 시도
        cached = self._load_from_db(table_name)
        if cached is not None:
            self._category_embeddings = cached
            return

        # API로 임베딩 계산
        if self._locale == "en":
            texts = [f"{self._task_instruction}\n\n{cat.description}" for cat in categories]
        else:
            texts = [
                f"{self._task_instruction}\n\n{cat.description}\n{cat.description_kr}"
                if cat.description_kr
                else f"{self._task_instruction}\n\n{cat.description}"
                for cat in categories
            ]

        embeddings = await self._embed_batch(texts)
        self._category_embeddings = np.array(embeddings)

        # LanceDB에 저장
        self._save_to_db(table_name, categories, self._category_embeddings)

        logger.info(
            "택소노미 임베딩 사전 계산 완료: %d 카테고리, shape=%s",
            len(categories),
            self._category_embeddings.shape,
        )

    @observe(name="stage2-taxonomy-mapping")
    async def map_risks(self, risks: list[ExtractedRisk]) -> list[TaxonomyMapping]:
        """추출된 리스크들을 택소노미에 매핑.

        Args:
            risks: Stage 1에서 추출된 리스크 목록.

        Returns:
            각 리스크에 대한 택소노미 매핑 결과.
        """
        if self._category_embeddings is None:
            raise RuntimeError("precompute_taxonomy()를 먼저 호출하세요")

        if not risks:
            return []

        # supporting_quote 임베딩 (task instruction 포함)
        texts = [f"{self._task_instruction}\n\n{r.supporting_quote}" for r in risks]
        risk_embeddings = np.array(await self._embed_batch(texts))

        # 코사인 유사도 매트릭스 계산 (정규화 후 dot product)
        risk_norms = risk_embeddings / np.linalg.norm(risk_embeddings, axis=1, keepdims=True)
        cat_norms = self._category_embeddings / np.linalg.norm(self._category_embeddings, axis=1, keepdims=True)
        similarity_matrix = risk_norms @ cat_norms.T  # (n_risks, n_categories)

        # 각 리스크에 대해 최고 유사도 카테고리 매핑
        mappings: list[TaxonomyMapping] = []
        best_indices = np.argmax(similarity_matrix, axis=1)

        for i, risk in enumerate(risks):
            best_idx = int(best_indices[i])
            score = float(similarity_matrix[i, best_idx])

            mappings.append(
                TaxonomyMapping(
                    extracted_risk=risk,
                    category=self._categories[best_idx],
                    similarity_score=score,
                )
            )

        logger.info("Stage 2 완료: %d개 리스크 → 택소노미 매핑", len(mappings))
        return mappings

    async def _embed_batch(self, texts: list[str], batch_size: int = 100) -> list[list[float]]:
        """텍스트 배치를 임베딩. OpenAI API 배치 제한 고려."""
        all_embeddings: list[list[float]] = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            response = await self._client.embeddings.create(
                model=self._model,
                input=batch,
                dimensions=self._dimensions,
            )
            batch_embeddings = [item.embedding for item in response.data]
            all_embeddings.extend(batch_embeddings)

        return all_embeddings
