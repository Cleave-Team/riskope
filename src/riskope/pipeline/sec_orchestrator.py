"""SEC 10-K 파이프라인 오케스트레이터.

논문의 원래 파이프라인을 SEC 10-K Item 1A에 적용.
Massive.com API로 데이터를 가져오고,
영문 프롬프트 + EN-only 임베딩으로 3-Stage 파이프라인을 실행한다.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from google import genai
from langfuse.openai import AsyncOpenAI
from rich.console import Console
from rich.table import Table

from riskope.config import Settings
from riskope.models import CompanyRiskProfile, JudgeResult, RefinementResult
from riskope.pipeline.chunker import TextChunker
from riskope.pipeline.dedup import deduplicate_and_finalize
from riskope.pipeline.extractor import RiskExtractor
from riskope.pipeline.judge import MappingJudge
from riskope.pipeline.mapper import TaxonomyMapper
from riskope.pipeline.refiner import TaxonomyRefiner
from riskope.sec.client import MassiveSecClient
from riskope.taxonomy.loader import load_taxonomy
from riskope.tracing import flush_traces, observe

logger = logging.getLogger(__name__)
console = Console()

_LOCALE = "en"


class SecRiskExtractionPipeline:
    """SEC 10-K → 3-Stage 리스크 추출 파이프라인."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

        self._gemini = genai.Client(api_key=settings.gemini_api_key)
        self._openai = AsyncOpenAI(api_key=settings.openai_api_key)
        self._sec = MassiveSecClient(api_key=settings.massive_api_key)

        self._chunker = TextChunker(
            max_chars=settings.chunk_max_chars,
            overlap_chars=settings.chunk_overlap_chars,
        )
        self._extractor = RiskExtractor(
            gemini_client=self._gemini,
            model=settings.extraction_model,
            max_retries=settings.extraction_max_retries,
            locale=_LOCALE,
        )
        self._mapper = TaxonomyMapper(
            client=self._openai,
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
            locale=_LOCALE,
        )
        self._judge = MappingJudge(
            gemini_client=self._gemini,
            model=settings.judge_model,
            threshold=settings.judge_threshold,
            max_concurrent=settings.max_concurrent_judge,
            locale=_LOCALE,
        )

        self._refiner = TaxonomyRefiner(
            gemini_client=self._gemini,
            openai_client=self._openai,
            analysis_model=settings.extraction_model,
            embedding_model=settings.embedding_model,
            embedding_dimensions=settings.embedding_dimensions,
        )

        self._taxonomy_loaded = False
        self._all_judge_results: list[JudgeResult] = []

    async def _ensure_taxonomy(self) -> None:
        if self._taxonomy_loaded:
            return

        console.print("[bold blue]Loading taxonomy...[/]")
        categories = load_taxonomy(
            en_path=self._settings.taxonomy_path_en,
            kr_path=None,
        )
        console.print(f"  {len(categories)} categories loaded")

        console.print("[bold blue]Pre-computing taxonomy embeddings (EN-only)...[/]")
        await self._mapper.precompute_taxonomy(categories)
        console.print("  Taxonomy embeddings ready")

        self._taxonomy_loaded = True

    @observe(name="sec-risk-pipeline")
    async def run_for_ticker(
        self,
        ticker: str,
        filing_date: str | None = None,
        period_end: str | None = None,
    ) -> CompanyRiskProfile | None:
        """단일 ticker에 대해 전체 파이프라인 실행."""
        await self._ensure_taxonomy()

        label = f"{ticker}"
        if filing_date:
            label += f" (filing_date={filing_date})"

        console.print(f"\n[bold green]▶ {label}[/]")
        console.print("  [dim]Fetching Item 1A from Massive API...[/]")
        risk_text = await self._sec.fetch_risk_factors(
            ticker=ticker,
            filing_date=filing_date,
            period_end=period_end,
        )
        if not risk_text:
            console.print("  [red]✗ Risk factors section not found[/]")
            return None

        console.print(f"  Item 1A: {len(risk_text):,} chars")

        return await self._run_pipeline(
            risk_text=risk_text,
            corp_name=ticker,
            rcept_no=f"sec-{ticker}",
            filing_date=filing_date or "",
        )

    @observe(name="sec-multi-report-pipeline")
    async def run_for_company(
        self,
        ticker: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[CompanyRiskProfile]:
        """특정 기업의 여러 연도 10-K에 대해 파이프라인 실행."""
        filings = await self._sec.find_filings(
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
        )

        if not filings:
            console.print("[red]No 10-K filings found[/]")
            return []

        console.print(f"[bold]{len(filings)} filings found for {ticker}[/]")

        profiles: list[CompanyRiskProfile] = []
        for filing in filings:
            risk_text = await self._sec.fetch_risk_factors_for_filing(filing)
            if not risk_text:
                continue

            await self._ensure_taxonomy()

            profile = await self._run_pipeline(
                risk_text=risk_text,
                corp_name=ticker,
                rcept_no=f"sec-{ticker}-{filing.get('period_end', '')}",
                filing_date=filing.get("filing_date", ""),
            )
            if profile:
                profile.corp_code = filing.get("cik", "")
                profile.report_year = filing.get("period_end", "")[:4]
                profile.filing_date = filing.get("filing_date", "")
                profiles.append(profile)

        return profiles

    async def _run_pipeline(
        self,
        risk_text: str,
        corp_name: str,
        rcept_no: str,
        filing_date: str,
    ) -> CompanyRiskProfile | None:
        chunks = self._chunker.chunk(risk_text)
        if len(chunks) > 1:
            console.print(f"  Chunked: {len(chunks)} chunks ({len(risk_text):,} chars)")

        console.print("  [dim]Stage 1: LLM risk extraction...[/]")
        if len(chunks) > 1:
            chunk_results = []
            for i, chunk_text in enumerate(chunks, 1):
                logger.info("Chunk %d/%d extraction (%d chars)", i, len(chunks), len(chunk_text))
                result = await self._extractor.extract(chunk_text)
                chunk_results.append(result)
            extraction = self._chunker.merge_extraction_results(chunk_results)
        else:
            extraction = await self._extractor.extract(risk_text)

        if not extraction.risks:
            console.print("  [red]✗ No risks extracted[/]")
            return None

        console.print(f"  Stage 1: {len(extraction.risks)} risks extracted")

        console.print("  [dim]Stage 2: Taxonomy mapping...[/]")
        mappings = await self._mapper.map_risks(extraction.risks)
        console.print(f"  Stage 2: {len(mappings)} mappings")

        console.print("  [dim]Stage 3: LLM Judge validation...[/]")
        judge_results = await self._judge.evaluate_all(mappings)
        self._all_judge_results.extend(judge_results)
        passed_results = self._judge.filter_passed(judge_results)
        console.print(f"  Stage 3: {len(passed_results)}/{len(judge_results)} passed")

        score_dist = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        for r in judge_results:
            score_dist[r.quality_score.value] = score_dist.get(r.quality_score.value, 0) + 1
        dist_str = " | ".join(f"{k}:{v}" for k, v in sorted(score_dist.items()))
        console.print(f"  Score distribution: {dist_str}")

        risk_factors = deduplicate_and_finalize(passed_results)
        console.print(f"  [bold]Final: {len(risk_factors)} risk factors[/]")

        flush_traces()
        return CompanyRiskProfile(
            corp_code="",
            corp_name=corp_name,
            rcept_no=rcept_no,
            report_year="",
            filing_date=filing_date,
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

    def save_results(self, profiles: list[CompanyRiskProfile], output_dir: Path | None = None) -> Path:
        out_dir = output_dir or self._settings.output_dir
        out_dir.mkdir(parents=True, exist_ok=True)

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
            filename = "sec_risk_profiles.json"

        safe_filename = "".join(c if c.isalnum() or c in "-_." else "_" for c in filename)
        output_file = out_dir / safe_filename
        data = [p.model_dump() for p in profiles]

        output_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        console.print(f"\n[bold green]Saved: {output_file}[/]")
        return output_file

    @staticmethod
    def print_summary(profiles: list[CompanyRiskProfile]) -> None:
        table = Table(title="SEC Risk Extraction Summary")
        table.add_column("Ticker", style="cyan")
        table.add_column("Year", style="green")
        table.add_column("Text Length", justify="right")
        table.add_column("Stage1 Extracted", justify="right")
        table.add_column("Stage3 Passed", justify="right")
        table.add_column("Final", justify="right", style="bold")

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
