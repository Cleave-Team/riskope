"""파이프라인 오케스트레이터 — 3-Stage 파이프라인 전체 흐름 통합."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from openai import AsyncOpenAI
from rich.console import Console
from rich.table import Table

from riskope.config import Settings
from riskope.dart.client import DartClient
from riskope.models import CompanyRiskProfile, JudgeResult, RefinementResult
from riskope.pipeline.chunker import TextChunker
from riskope.pipeline.dedup import deduplicate_and_finalize
from riskope.pipeline.extractor import RiskExtractor
from riskope.pipeline.judge import MappingJudge
from riskope.pipeline.mapper import TaxonomyMapper
from riskope.pipeline.refiner import TaxonomyRefiner
from riskope.taxonomy.loader import load_taxonomy

logger = logging.getLogger(__name__)
console = Console()


class RiskExtractionPipeline:
    """DART 공시 → 3-Stage 리스크 추출 파이프라인."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

        self._openai = AsyncOpenAI(api_key=settings.openai_api_key)
        self._dart = DartClient(api_key=settings.dart_api_key)

        self._chunker = TextChunker(
            max_chars=settings.chunk_max_chars,
            overlap_chars=settings.chunk_overlap_chars,
        )
        self._extractor = RiskExtractor(
            client=self._openai,
            model=settings.extraction_model,
            max_retries=settings.extraction_max_retries,
        )
        self._mapper = TaxonomyMapper(
            client=self._openai,
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
        )
        self._judge = MappingJudge(
            client=self._openai,
            model=settings.judge_model,
            threshold=settings.judge_threshold,
            max_concurrent=settings.max_concurrent_judge,
        )

        self._refiner = TaxonomyRefiner(
            client=self._openai,
            analysis_model=settings.extraction_model,
            embedding_model=settings.embedding_model,
            embedding_dimensions=settings.embedding_dimensions,
        )

        self._taxonomy_loaded = False
        self._all_judge_results: list[JudgeResult] = []

    async def _ensure_taxonomy(self) -> None:
        """택소노미가 로드되지 않았으면 로드 + 임베딩 사전 계산."""
        if self._taxonomy_loaded:
            return

        console.print("[bold blue]택소노미 로드 중...[/]")
        categories = load_taxonomy(
            en_path=self._settings.taxonomy_path_en,
            kr_path=self._settings.taxonomy_path_kr,
        )
        console.print(f"  {len(categories)}개 카테고리 로드 완료")

        console.print("[bold blue]택소노미 임베딩 사전 계산 중...[/]")
        await self._mapper.precompute_taxonomy(categories)
        console.print("  임베딩 사전 계산 완료")

        self._taxonomy_loaded = True

    async def run_for_document(self, rcept_no: str, corp_name: str = "") -> CompanyRiskProfile | None:
        """단일 접수번호에 대해 전체 파이프라인 실행.

        Args:
            rcept_no: DART 접수번호.
            corp_name: 기업명 (로깅용).

        Returns:
            추출된 리스크 프로필. 실패 시 None.
        """
        await self._ensure_taxonomy()

        label = f"{corp_name} ({rcept_no})" if corp_name else rcept_no

        # --- DART 문서 가져오기 ---
        console.print(f"\n[bold green]▶ {label}[/]")
        console.print("  [dim]DART 문서 가져오는 중...[/]")
        risk_text = await self._dart.fetch_risk_section(rcept_no)
        if not risk_text:
            console.print("  [red]✗ 위험 섹션을 찾을 수 없음[/]")
            return None

        console.print(f"  위험 섹션: {len(risk_text):,}자")

        # --- 텍스트 청킹 ---
        chunks = self._chunker.chunk(risk_text)
        if len(chunks) > 1:
            console.print(f"  텍스트 청킹: {len(chunks)}개 청크 (원문 {len(risk_text):,}자)")

        # --- Stage 1: LLM 추출 ---
        console.print("  [dim]Stage 1: LLM 리스크 추출...[/]")
        if len(chunks) > 1:
            chunk_results = []
            for i, chunk_text in enumerate(chunks, 1):
                logger.info("청크 %d/%d 추출 중 (%d자)", i, len(chunks), len(chunk_text))
                result = await self._extractor.extract(chunk_text)
                chunk_results.append(result)
            extraction = self._chunker.merge_extraction_results(chunk_results)
        else:
            extraction = await self._extractor.extract(risk_text)

        if not extraction.risks:
            console.print("  [red]✗ 리스크를 추출하지 못함[/]")
            return None

        console.print(f"  Stage 1: {len(extraction.risks)}개 리스크 추출")

        # --- Stage 2: 임베딩 매핑 ---
        console.print("  [dim]Stage 2: 택소노미 매핑...[/]")
        mappings = await self._mapper.map_risks(extraction.risks)
        console.print(f"  Stage 2: {len(mappings)}개 매핑 생성")

        # --- Stage 3: LLM Judge ---
        console.print("  [dim]Stage 3: LLM Judge 검증...[/]")
        judge_results = await self._judge.evaluate_all(mappings)
        self._all_judge_results.extend(judge_results)
        passed_results = self._judge.filter_passed(judge_results)
        console.print(f"  Stage 3: {len(passed_results)}/{len(judge_results)}개 통과")

        score_dist = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        for r in judge_results:
            score_dist[r.quality_score.value] = score_dist.get(r.quality_score.value, 0) + 1
        dist_str = " | ".join(f"{k}점:{v}" for k, v in sorted(score_dist.items()))
        console.print(f"  점수 분포: {dist_str}")

        # --- 중복제거 & 최종 출력 ---
        risk_factors = deduplicate_and_finalize(passed_results)
        console.print(f"  [bold]최종: {len(risk_factors)}개 리스크 팩터[/]")

        self._print_token_summary(extraction.usage)

        return CompanyRiskProfile(
            corp_code="",
            corp_name=corp_name,
            rcept_no=rcept_no,
            report_year="",
            risk_factors=risk_factors,
            raw_text_length=len(risk_text),
            total_extracted=len(extraction.risks),
            total_mapped=len(mappings),
            total_validated=len(risk_factors),
            score_distribution={k: v for k, v in score_dist.items() if v > 0},
        )

    def get_refinement_candidates(self, top_n: int = 5) -> list[tuple[str, int]]:
        return self._refiner.identify_problematic_categories(self._all_judge_results, top_n=top_n)

    async def run_refinement(self, category_key: str) -> RefinementResult | None:
        return await self._refiner.refine_category(category_key, self._all_judge_results)

    async def run_for_company(
        self,
        corp_code: str,
        bgn_de: str,
        end_de: str,
    ) -> list[CompanyRiskProfile]:
        """특정 기업의 사업보고서들에 대해 파이프라인 실행.

        Args:
            corp_code: DART 고유번호.
            bgn_de: 시작일 YYYYMMDD.
            end_de: 종료일 YYYYMMDD.

        Returns:
            연도별 리스크 프로필 목록.
        """
        reports = await self._dart.find_annual_reports(
            corp_code=corp_code,
            bgn_de=bgn_de,
            end_de=end_de,
        )

        if not reports:
            console.print("[red]사업보고서를 찾을 수 없습니다[/]")
            return []

        console.print(f"[bold]{len(reports)}개 사업보고서 발견[/]")

        profiles: list[CompanyRiskProfile] = []
        for report in reports:
            profile = await self.run_for_document(
                rcept_no=report["rcept_no"],
                corp_name=report.get("corp_name", ""),
            )
            if profile:
                profile.corp_code = report.get("corp_code", "")
                profile.report_year = report.get("rcept_dt", "")[:4]
                profile.filing_date = report.get("rcept_dt", "")
                profiles.append(profile)

        return profiles

    def save_results(self, profiles: list[CompanyRiskProfile], output_dir: Path | None = None) -> Path:
        """결과를 JSON 파일로 저장.

        파일명: {기업명}_{접수번호}.json (단일) 또는 {기업명}_{연도범위}.json (복수)

        Args:
            profiles: 리스크 프로필 목록.
            output_dir: 출력 디렉토리 (기본값: settings.output_dir).

        Returns:
            저장된 파일 경로.
        """
        out_dir = output_dir or self._settings.output_dir
        out_dir.mkdir(parents=True, exist_ok=True)

        # 파일명 결정
        if len(profiles) == 1:
            p = profiles[0]
            name = p.corp_name or p.rcept_no
            suffix = p.report_year or p.rcept_no
            filename = f"{name}_{suffix}.json"
        elif profiles:
            name = profiles[0].corp_name or "multi"
            years = sorted({p.report_year for p in profiles if p.report_year})
            suffix = f"{years[0]}-{years[-1]}" if years else "results"
            filename = f"{name}_{suffix}.json"
        else:
            filename = "risk_profiles.json"

        # 안전한 파일명 (특수문자 제거)
        safe_filename = "".join(c if c.isalnum() or c in "-_." else "_" for c in filename)
        output_file = out_dir / safe_filename
        data = [p.model_dump() for p in profiles]

        output_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        console.print(f"\n[bold green]결과 저장: {output_file}[/]")
        return output_file

    def _print_token_summary(self, extraction_usage: dict) -> None:
        stage1 = extraction_usage
        stage3 = self._judge.total_usage

        s1_total = stage1.get("total_tokens", 0)
        s3_total = stage3.get("total_tokens", 0)
        grand_total = s1_total + s3_total

        if grand_total > 0:
            console.print(f"  [dim]토큰 사용: Stage1={s1_total:,} | Stage3={s3_total:,} | 합계={grand_total:,}[/]")

    @staticmethod
    def print_summary(profiles: list[CompanyRiskProfile]) -> None:
        """결과 요약 테이블 출력."""
        table = Table(title="리스크 추출 결과 요약")
        table.add_column("기업명", style="cyan")
        table.add_column("연도", style="green")
        table.add_column("원문 길이", justify="right")
        table.add_column("Stage1 추출", justify="right")
        table.add_column("Stage3 통과", justify="right")
        table.add_column("최종", justify="right", style="bold")

        for p in profiles:
            table.add_row(
                p.corp_name,
                p.report_year,
                f"{p.raw_text_length:,}",
                str(p.total_extracted),
                str(p.total_validated),
                str(len(p.risk_factors)),
            )

        console.print(table)
