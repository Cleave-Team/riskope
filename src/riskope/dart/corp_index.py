"""DART 기업 고유번호 검색 엔진.

DART API에서 기업 목록을 다운로드하여 LanceDB에 임베딩과 함께 저장하고,
exact / FTS / semantic / hybrid 검색을 지원한다.

S3 연동 전략:
- 쓰기(update): 로컬 + S3 네이티브 경로에 동시 저장
- 읽기(검색): 로컬 LanceDB에서 쿼리 (latency 최소화)
- startup: S3 → 로컬 복사 (로컬에 없을 때만)
"""

from __future__ import annotations

import io
import logging
import shutil
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path

import httpx
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

_DART_CORP_CODE_URL = "https://opendart.fss.or.kr/api/corpCode.xml"

_THIS_DIR = Path(__file__).resolve().parent.parent.parent.parent
_DEFAULT_DATA_DIR = _THIS_DIR / "data" if (_THIS_DIR / "data").exists() else Path("/app/data")

_TABLE_NAME = "dart_corps"
_S3_DB_PREFIX = "dart/corp_index/corp.lancedb"


@dataclass
class UpdateStats:
    total: int = 0
    new: int = 0
    changed: int = 0
    deleted: int = 0
    embedded: int = 0


class DartCorpIndex:
    """DART 기업 고유번호 목록 LanceDB 검색 엔진."""

    def __init__(
        self,
        dart_api_key: str,
        openai_client: AsyncOpenAI,
        embedding_model: str = "text-embedding-3-small",
        embedding_dimensions: int = 1536,
        data_dir: Path | None = None,
    ) -> None:
        self._dart_api_key = dart_api_key
        self._client = openai_client
        self._model = embedding_model
        self._dimensions = embedding_dimensions
        self._data_dir = data_dir or _DEFAULT_DATA_DIR

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _db_path(self) -> Path:
        return self._data_dir / "corp.lancedb"

    def _open_db(self):
        import lancedb

        self._data_dir.mkdir(parents=True, exist_ok=True)
        return lancedb.connect(str(self._db_path()))

    def _table_exists(self) -> bool:
        try:
            db = self._open_db()
            tables = db.list_tables()
            table_list = tables.tables if hasattr(tables, "tables") else list(tables)
            return _TABLE_NAME in table_list
        except Exception:
            return False

    def _open_table(self):
        db = self._open_db()
        return db.open_table(_TABLE_NAME)

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

    async def _download_corp_list(self) -> list[dict]:
        """DART API에서 기업 고유번호 ZIP을 다운로드하여 파싱."""
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(
                _DART_CORP_CODE_URL,
                params={"crtfc_key": self._dart_api_key},
            )
            resp.raise_for_status()

        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            xml_name = zf.namelist()[0]
            xml_bytes = zf.read(xml_name)

        root = ET.fromstring(xml_bytes)
        corps: list[dict] = []
        for item in root.iter("list"):
            corps.append(
                {
                    "corp_code": (item.findtext("corp_code") or "").strip(),
                    "corp_name": (item.findtext("corp_name") or "").strip(),
                    "corp_eng_name": (item.findtext("corp_eng_name") or "").strip(),
                    "stock_code": (item.findtext("stock_code") or "").strip(),
                    "modify_date": (item.findtext("modify_date") or "").strip(),
                }
            )
        return corps

    # ------------------------------------------------------------------
    # S3 네이티브 연동
    # ------------------------------------------------------------------

    def _s3_db_uri(self) -> str:
        """S3 LanceDB URI. (예: s3://riskope-filings/dart/corp_index/corp.lancedb)"""
        from riskope.config import get_settings

        settings = get_settings()
        return f"s3://{settings.s3_bucket}/{_S3_DB_PREFIX}"

    def _open_s3_db(self):
        """S3 네이티브 LanceDB 연결."""
        import lancedb

        from riskope.config import get_settings

        settings = get_settings()
        storage_options = {}
        if settings.s3_access_key:
            storage_options["aws_access_key_id"] = settings.s3_access_key
            storage_options["aws_secret_access_key"] = settings.s3_secret_key
        storage_options["region"] = settings.s3_region

        return lancedb.connect(self._s3_db_uri(), storage_options=storage_options)

    def upload_to_s3(self) -> None:
        """로컬 LanceDB 테이블을 S3 네이티브 경로에 동기화."""
        if not self._table_exists():
            logger.warning("업로드할 로컬 테이블 없음")
            return

        local_table = self._open_table()
        arrow_table = local_table.to_arrow()

        s3_db = self._open_s3_db()
        s3_db.create_table(_TABLE_NAME, data=arrow_table, mode="overwrite")

        logger.info("S3 동기화 완료: %s (%d rows)", self._s3_db_uri(), arrow_table.num_rows)

    def download_from_s3(self) -> bool:
        """S3 LanceDB에서 로컬로 테이블 복사.

        Returns:
            True면 복원 성공, False면 S3에 데이터 없거나 실패.
        """
        db_path = self._db_path()
        if db_path.exists() and self._table_exists():
            logger.info("로컬 LanceDB 이미 존재, S3 다운로드 스킵: %s", db_path)
            return True

        try:
            s3_db = self._open_s3_db()
            s3_tables = s3_db.list_tables()
            table_list = s3_tables.tables if hasattr(s3_tables, "tables") else list(s3_tables)
            if _TABLE_NAME not in table_list:
                logger.info("S3에 corp index 테이블 없음, 건너뜀")
                return False

            s3_table = s3_db.open_table(_TABLE_NAME)
            arrow_table = s3_table.to_arrow()
        except Exception:
            logger.warning("S3 LanceDB 접근 실패", exc_info=True)
            return False

        # 로컬에 저장
        local_db = self._open_db()
        local_db.create_table(_TABLE_NAME, data=arrow_table, mode="overwrite")

        # FTS 인덱스 생성
        try:
            local_table = local_db.open_table(_TABLE_NAME)
            local_table.create_fts_index("corp_name", replace=True)
        except Exception:
            logger.warning("FTS 인덱스 생성 실패", exc_info=True)

        logger.info("S3에서 corp index 복원 완료: %s (%d rows)", db_path, arrow_table.num_rows)
        return True

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def update(self, force: bool = False) -> UpdateStats:
        """DART 기업 목록을 다운로드하여 LanceDB에 저장/업데이트."""
        logger.info("DART 기업 목록 다운로드 중...")
        new_corps = await self._download_corp_list()
        logger.info("다운로드 완료: %d건", len(new_corps))

        stats = UpdateStats(total=len(new_corps))

        # 기존 데이터 로드
        existing: dict[str, dict] = {}
        if not force and self._table_exists():
            try:
                table = self._open_table()
                arrow = table.to_arrow()
                codes = arrow.column("corp_code").to_pylist()
                names = arrow.column("corp_name").to_pylist()
                eng_names = arrow.column("corp_eng_name").to_pylist()
                vectors = arrow.column("vector").to_pylist()
                for idx, code in enumerate(codes):
                    existing[code] = {
                        "corp_name": names[idx],
                        "corp_eng_name": eng_names[idx],
                        "vector": vectors[idx],
                    }
            except Exception:
                logger.warning("기존 테이블 로드 실패, 전체 재구성", exc_info=True)
                existing = {}

        # 델타 계산
        need_embed_indices: list[int] = []
        reuse_vectors: dict[int, list[float]] = {}

        for i, corp in enumerate(new_corps):
            code = corp["corp_code"]
            old = existing.pop(code, None)
            if old is None:
                stats.new += 1
                need_embed_indices.append(i)
            elif force or old["corp_name"] != corp["corp_name"] or old["corp_eng_name"] != corp["corp_eng_name"]:
                stats.changed += 1
                need_embed_indices.append(i)
            else:
                reuse_vectors[i] = old["vector"]

        stats.deleted = len(existing)  # remaining in existing = deleted

        # 임베딩
        if need_embed_indices:
            texts = [
                f"{new_corps[i]['corp_name']} {new_corps[i]['corp_eng_name']}"
                for i in need_embed_indices
            ]
            logger.info("임베딩 생성 중: %d건...", len(texts))
            embeddings = await self._embed_batch(texts)
            stats.embedded = len(embeddings)
            embed_map = dict(zip(need_embed_indices, embeddings))
        else:
            embed_map = {}
            logger.info("변경 없음, 임베딩 스킵")

        # 전체 데이터 구성
        data: list[dict] = []
        for i, corp in enumerate(new_corps):
            vector = embed_map.get(i) or reuse_vectors.get(i)
            if vector is None:
                # force=False인데 기존 데이터에도 없는 경우 (발생하면 안 됨)
                vector = [0.0] * self._dimensions
            data.append(
                {
                    "corp_code": corp["corp_code"],
                    "corp_name": corp["corp_name"],
                    "corp_eng_name": corp["corp_eng_name"],
                    "stock_code": corp["stock_code"],
                    "modify_date": corp["modify_date"],
                    "vector": vector,
                }
            )

        # LanceDB에 저장
        db = self._open_db()
        db.create_table(_TABLE_NAME, data=data, mode="overwrite")

        # FTS 인덱스 생성
        try:
            table = db.open_table(_TABLE_NAME)
            table.create_fts_index("corp_name", replace=True)
            logger.info("FTS 인덱스 생성 완료")
        except Exception:
            logger.warning("FTS 인덱스 생성 실패 (tantivy 미설치?)", exc_info=True)

        logger.info(
            "기업 목록 업데이트 완료: total=%d, new=%d, changed=%d, deleted=%d, embedded=%d",
            stats.total, stats.new, stats.changed, stats.deleted, stats.embedded,
        )

        # S3 백업
        try:
            self.upload_to_s3()
        except Exception:
            logger.warning("S3 백업 실패 (업데이트 자체는 성공)", exc_info=True)

        return stats

    def search_exact(
        self, corp_code: str | None = None, stock_code: str | None = None
    ) -> list[dict]:
        """corp_code 또는 stock_code로 정확 검색."""
        if not self._table_exists():
            return []

        table = self._open_table()
        arrow = table.to_arrow()

        results: list[dict] = []
        codes = arrow.column("corp_code").to_pylist()
        names = arrow.column("corp_name").to_pylist()
        eng_names = arrow.column("corp_eng_name").to_pylist()
        stock_codes = arrow.column("stock_code").to_pylist()
        modify_dates = arrow.column("modify_date").to_pylist()

        for i in range(arrow.num_rows):
            if corp_code and codes[i] == corp_code:
                results.append(self._row_dict(codes[i], names[i], eng_names[i], stock_codes[i], modify_dates[i]))
            elif stock_code and stock_codes[i] == stock_code:
                results.append(self._row_dict(codes[i], names[i], eng_names[i], stock_codes[i], modify_dates[i]))

        return results

    def search_fts(self, query: str, limit: int = 10) -> list[dict]:
        """전문 검색 (FTS)."""
        if not self._table_exists():
            return []
        try:
            table = self._open_table()
            rows = table.search(query, query_type="fts").limit(limit).to_list()
            return [self._from_row(r) for r in rows]
        except Exception:
            logger.warning("FTS 검색 실패, 빈 결과 반환", exc_info=True)
            return []

    async def search_semantic(self, query: str, limit: int = 10) -> list[dict]:
        """시맨틱(벡터) 검색."""
        if not self._table_exists():
            return []
        embeddings = await self._embed_batch([query])
        query_vector = embeddings[0]
        table = self._open_table()
        rows = table.search(query_vector).limit(limit).to_list()
        return [self._from_row(r) for r in rows]

    async def search_hybrid(self, query: str, limit: int = 10) -> list[dict]:
        """하이브리드 검색 (FTS + 벡터, RRF 병합)."""
        if not self._table_exists():
            return []

        # LanceDB native hybrid 시도
        try:
            embeddings = await self._embed_batch([query])
            query_vector = embeddings[0]
            table = self._open_table()
            rows = table.search(query, query_type="hybrid", vector=query_vector).limit(limit).to_list()
            return [self._from_row(r) for r in rows]
        except Exception:
            pass

        # Fallback: RRF 병합
        fts_results = self.search_fts(query, limit=limit * 2)
        sem_results = await self.search_semantic(query, limit=limit * 2)
        return self._rrf_merge(fts_results, sem_results, limit)

    async def search(self, query: str, mode: str = "auto", limit: int = 10) -> list[dict]:
        """통합 검색. mode: auto, exact, fts, semantic, hybrid."""
        if mode == "auto":
            stripped = query.strip()
            if stripped.isdigit() and len(stripped) == 8:
                return self.search_exact(corp_code=stripped)
            if stripped.isdigit() and len(stripped) == 6:
                return self.search_exact(stock_code=stripped)
            return await self.search_hybrid(stripped, limit=limit)
        elif mode == "exact":
            stripped = query.strip()
            if len(stripped) == 8 and stripped.isdigit():
                return self.search_exact(corp_code=stripped)
            if len(stripped) == 6 and stripped.isdigit():
                return self.search_exact(stock_code=stripped)
            return self.search_exact(corp_code=stripped)
        elif mode == "fts":
            return self.search_fts(query, limit=limit)
        elif mode == "semantic":
            return await self.search_semantic(query, limit=limit)
        elif mode == "hybrid":
            return await self.search_hybrid(query, limit=limit)
        else:
            raise ValueError(f"Unknown search mode: {mode}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_dict(
        corp_code: str, corp_name: str, corp_eng_name: str, stock_code: str, modify_date: str, score: float | None = None
    ) -> dict:
        d: dict = {
            "corp_code": corp_code,
            "corp_name": corp_name,
            "corp_eng_name": corp_eng_name,
            "stock_code": stock_code,
            "modify_date": modify_date,
        }
        if score is not None:
            d["score"] = score
        return d

    @staticmethod
    def _from_row(row: dict) -> dict:
        score = row.get("_relevance_score") or row.get("_distance")
        return {
            "corp_code": row.get("corp_code", ""),
            "corp_name": row.get("corp_name", ""),
            "corp_eng_name": row.get("corp_eng_name", ""),
            "stock_code": row.get("stock_code", ""),
            "modify_date": row.get("modify_date", ""),
            **({"score": float(score)} if score is not None else {}),
        }

    @staticmethod
    def _rrf_merge(
        list_a: list[dict], list_b: list[dict], limit: int, k: int = 60
    ) -> list[dict]:
        """Reciprocal Rank Fusion으로 두 결과 리스트를 병합."""
        scores: dict[str, float] = {}
        items: dict[str, dict] = {}

        for rank, item in enumerate(list_a):
            code = item["corp_code"]
            scores[code] = scores.get(code, 0) + 1.0 / (k + rank + 1)
            items[code] = item

        for rank, item in enumerate(list_b):
            code = item["corp_code"]
            scores[code] = scores.get(code, 0) + 1.0 / (k + rank + 1)
            items[code] = item

        sorted_codes = sorted(scores, key=lambda c: scores[c], reverse=True)[:limit]
        results: list[dict] = []
        for code in sorted_codes:
            d = items[code].copy()
            d["score"] = scores[code]
            results.append(d)
        return results
