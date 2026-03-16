"""CLI 엔트리포인트."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from rich.console import Console
from rich.logging import RichHandler

from riskope.config import Settings, get_settings
from riskope.pipeline.orchestrator import RiskExtractionPipeline

console = Console()


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[RichHandler(rich_tracebacks=True, console=console)],
    )
    # 외부 라이브러리 로그 레벨 조정
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="riskope",
        description="DART 공시 기반 택소노미 정렬 리스크 팩터 추출 엔진",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="상세 로그 출력")

    subparsers = parser.add_subparsers(dest="command", help="실행할 명령")

    # --- extract: 단일 접수번호 ---
    extract_parser = subparsers.add_parser("extract", help="단일 접수번호에서 리스크 추출")
    extract_parser.add_argument("rcept_no", help="DART 접수번호")
    extract_parser.add_argument("--corp-name", default="", help="기업명 (로깅용)")

    # --- company: 기업 코드로 조회 ---
    company_parser = subparsers.add_parser("company", help="기업의 사업보고서에서 리스크 추출")
    company_parser.add_argument("corp_code", help="DART 고유번호")
    company_parser.add_argument("--bgn-de", required=True, help="시작일 YYYYMMDD")
    company_parser.add_argument("--end-de", required=True, help="종료일 YYYYMMDD")

    # --- taxonomy: 택소노미 확인 ---
    subparsers.add_parser("taxonomy", help="택소노미 카테고리 목록 출력")

    # --- refine: 택소노미 개선 ---
    refine_parser = subparsers.add_parser("refine", help="파이프라인 실행 후 택소노미 개선 수행")
    refine_parser.add_argument("rcept_no", help="DART 접수번호")
    refine_parser.add_argument("--corp-name", default="", help="기업명 (로깅용)")
    refine_parser.add_argument("--top-n", type=int, default=3, help="개선할 상위 카테고리 수 (기본: 3)")

    # --- SEC: SEC 10-K 리스크 추출 ---
    sec_extract_parser = subparsers.add_parser("sec-extract", help="SEC 10-K에서 리스크 추출 (ticker 지정)")
    sec_extract_parser.add_argument("ticker", help="종목 티커 (예: AAPL)")
    sec_extract_parser.add_argument("--filing-date", default=None, help="filing date 필터 (YYYY-MM-DD)")
    sec_extract_parser.add_argument("--period-end", default=None, help="period end date 필터 (YYYY-MM-DD)")

    sec_company_parser = subparsers.add_parser("sec-company", help="SEC 10-K 여러 연도 리스크 추출")
    sec_company_parser.add_argument("ticker", help="종목 티커 (예: AAPL)")
    sec_company_parser.add_argument("--start-date", default=None, help="시작일 (YYYY-MM-DD)")
    sec_company_parser.add_argument("--end-date", default=None, help="종료일 (YYYY-MM-DD)")

    # --- evaluate: Massive 정답셋 비교 평가 ---
    eval_parser = subparsers.add_parser("evaluate", help="Massive API 정답셋과 파이프라인 결과 비교 평가")
    eval_parser.add_argument("profiles", nargs="+", help="파이프라인 출력 JSON 파일 경로")
    eval_parser.add_argument("--tickers", default=None, help="비교할 티커 (쉼표 구분, 미지정 시 JSON에서 추출)")

    # --- corp-update: DART 기업 목록 업데이트 ---
    corp_update_parser = subparsers.add_parser("corp-update", help="DART 기업 목록 다운로드/업데이트")
    corp_update_parser.add_argument("--force", action="store_true", help="전체 재임베딩")

    # --- corp-search: 기업 검색 ---
    corp_search_parser = subparsers.add_parser("corp-search", help="DART 기업 검색")
    corp_search_parser.add_argument("query", help="검색어 (기업명, corp_code, stock_code)")
    corp_search_parser.add_argument(
        "--mode",
        choices=["auto", "exact", "fts", "semantic", "hybrid"],
        default="auto",
        help="검색 모드 (기본: auto)",
    )
    corp_search_parser.add_argument("--limit", type=int, default=10, help="결과 수 (기본: 10)")

    # --- cluster: 산업 클러스터링 검증 ---
    cluster_parser = subparsers.add_parser("cluster", help="산업 클러스터링 검증 (Section 4.3)")
    cluster_parser.add_argument(
        "--profiles",
        nargs="+",
        required=True,
        help="CompanyRiskProfile JSON 파일 경로들",
    )
    cluster_parser.add_argument(
        "--industry-map",
        required=True,
        help='산업 코드 매핑 JSON 파일 (예: {"SK하이닉스": "26"})',
    )
    cluster_parser.add_argument(
        "--level",
        choices=["primary", "secondary", "tertiary"],
        default="tertiary",
        help="택소노미 레벨 (기본: tertiary)",
    )

    args = parser.parse_args()
    _setup_logging(verbose=args.verbose)

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    if args.command == "taxonomy":
        _cmd_taxonomy()
    elif args.command == "extract":
        asyncio.run(_cmd_extract(args.rcept_no, args.corp_name))
    elif args.command == "company":
        asyncio.run(_cmd_company(args.corp_code, args.bgn_de, args.end_de))
    elif args.command == "refine":
        asyncio.run(_cmd_refine(args.rcept_no, args.corp_name, args.top_n))
    elif args.command == "evaluate":
        asyncio.run(_cmd_evaluate(args.profiles, args.tickers))
    elif args.command == "sec-extract":
        asyncio.run(_cmd_sec_extract(args.ticker, args.filing_date, args.period_end))
    elif args.command == "sec-company":
        asyncio.run(_cmd_sec_company(args.ticker, args.start_date, args.end_date))
    elif args.command == "corp-update":
        asyncio.run(_cmd_corp_update(args.force))
    elif args.command == "corp-search":
        asyncio.run(_cmd_corp_search(args.query, args.mode, args.limit))
    elif args.command == "cluster":
        _cmd_cluster(args.profiles, args.industry_map, args.level)


def _cmd_taxonomy() -> None:
    """택소노미 카테고리 목록 출력."""
    from rich.table import Table

    from riskope.taxonomy.loader import load_taxonomy

    settings = get_settings()
    categories = load_taxonomy(settings.taxonomy_path_en, settings.taxonomy_path_kr)

    table = Table(title=f"리스크 택소노미 ({len(categories)}개 카테고리)")
    table.add_column("#", justify="right", style="dim")
    table.add_column("Primary", style="cyan")
    table.add_column("Secondary", style="green")
    table.add_column("Tertiary", style="bold")

    for i, cat in enumerate(categories, 1):
        table.add_row(str(i), cat.primary, cat.secondary, cat.tertiary)

    console.print(table)


async def _cmd_extract(rcept_no: str, corp_name: str) -> None:
    """단일 접수번호 파이프라인 실행."""
    settings = get_settings()
    _validate_keys(settings)

    pipeline = RiskExtractionPipeline(settings)
    profile = await pipeline.run_for_document(rcept_no, corp_name)

    if profile:
        pipeline.save_results([profile])
        pipeline.print_summary([profile])
    else:
        console.print("[red]리스크 추출 실패[/]")
        sys.exit(1)


async def _cmd_company(corp_code: str, bgn_de: str, end_de: str) -> None:
    """기업 코드 기반 파이프라인 실행."""
    settings = get_settings()
    _validate_keys(settings)

    pipeline = RiskExtractionPipeline(settings)
    profiles = await pipeline.run_for_company(corp_code, bgn_de, end_de)

    if profiles:
        pipeline.save_results(profiles)
        pipeline.print_summary(profiles)
    else:
        console.print("[red]리스크 추출 결과 없음[/]")
        sys.exit(1)


async def _cmd_refine(rcept_no: str, corp_name: str, top_n: int) -> None:
    from rich.table import Table

    settings = get_settings()
    _validate_keys(settings)

    pipeline = RiskExtractionPipeline(settings)
    profile = await pipeline.run_for_document(rcept_no, corp_name)

    if not profile:
        console.print("[red]리스크 추출 실패 — 개선 불가[/]")
        sys.exit(1)

    candidates = pipeline.get_refinement_candidates(top_n=top_n)
    if not candidates:
        console.print("[yellow]저품질 매핑이 없어 개선 대상 카테고리가 없습니다[/]")
        return

    console.print(f"\n[bold blue]택소노미 개선 대상: {len(candidates)}개 카테고리[/]")

    results = []
    for category_key, low_count in candidates:
        console.print(f"\n[dim]개선 중: {category_key} (저품질 {low_count}건)...[/]")
        result = await pipeline.run_refinement(category_key)
        if result:
            results.append(result)

    if not results:
        console.print("[yellow]개선 결과 없음[/]")
        return

    table = Table(title="택소노미 개선 결과")
    table.add_column("카테고리", style="cyan", max_width=40)
    table.add_column("원래 Description", max_width=30)
    table.add_column("개선 Description", max_width=30)
    table.add_column("원래 분리도", justify="right")
    table.add_column("개선 분리도", justify="right")
    table.add_column("개선율", justify="right", style="bold")
    table.add_column("저품질 수", justify="right")

    for r in results:
        table.add_row(
            r.category_key,
            r.original_description[:30] + "..." if len(r.original_description) > 30 else r.original_description,
            r.refined_description[:30] + "..." if len(r.refined_description) > 30 else r.refined_description,
            f"{r.original_separation:.4f}",
            f"{r.refined_separation:.4f}",
            f"{r.improvement_pct:+.1f}%",
            str(r.num_low_quality_mappings),
        )

    console.print(table)


async def _cmd_evaluate(profile_paths: list[str], tickers_str: str | None) -> None:
    from pathlib import Path

    from riskope.evaluation.evaluator import (
        MassiveGroundTruthFetcher,
        evaluate_single,
        extract_categories_from_ground_truth,
        extract_categories_from_profile,
        load_profile_from_json,
        print_aggregate_evaluation,
        print_company_evaluation,
    )
    from riskope.evaluation.metrics import AggregateEvaluation

    settings = get_settings()
    if not settings.massive_api_key:
        console.print("[red]RISKOPE_MASSIVE_API_KEY 환경변수를 설정해주세요[/]")
        sys.exit(1)

    fetcher = MassiveGroundTruthFetcher(api_key=settings.massive_api_key)
    agg = AggregateEvaluation()

    for path_str in profile_paths:
        profiles = load_profile_from_json(Path(path_str))
        for profile in profiles:
            ticker = profile.corp_name
            filing_date = profile.filing_date or ""

            console.print(f"\n[bold]Fetching ground truth for {ticker}...[/]")
            gt_results = await fetcher.fetch_ground_truth(ticker=ticker, filing_date=filing_date or None)

            if not gt_results:
                console.print(f"  [yellow]No ground truth found for {ticker}[/]")
                continue

            gt_date = gt_results[0].get("filing_date", "") if gt_results else ""
            gt_cats = extract_categories_from_ground_truth(gt_results, filing_date=gt_date)
            pred_cats = extract_categories_from_profile(profile)

            ev = evaluate_single(pred_cats, gt_cats, ticker=ticker, filing_date=gt_date)
            agg.companies.append(ev)
            print_company_evaluation(ev)

    if agg.companies:
        console.print()
        print_aggregate_evaluation(agg)
    else:
        console.print("[red]No evaluations completed[/]")


async def _cmd_sec_extract(ticker: str, filing_date: str | None, period_end: str | None) -> None:
    from riskope.pipeline.sec_orchestrator import SecRiskExtractionPipeline

    settings = get_settings()
    _validate_sec_keys(settings)

    pipeline = SecRiskExtractionPipeline(settings)
    profile = await pipeline.run_for_ticker(ticker, filing_date=filing_date, period_end=period_end)

    if profile:
        pipeline.save_results([profile])
        pipeline.print_summary([profile])
    else:
        console.print("[red]Risk extraction failed[/]")
        sys.exit(1)


async def _cmd_sec_company(ticker: str, start_date: str | None, end_date: str | None) -> None:
    from riskope.pipeline.sec_orchestrator import SecRiskExtractionPipeline

    settings = get_settings()
    _validate_sec_keys(settings)

    pipeline = SecRiskExtractionPipeline(settings)
    profiles = await pipeline.run_for_company(ticker, start_date=start_date, end_date=end_date)

    if profiles:
        pipeline.save_results(profiles)
        pipeline.print_summary(profiles)
    else:
        console.print("[red]No risk extraction results[/]")
        sys.exit(1)


def _cmd_cluster(profile_paths: list[str], industry_map_path: str, level: str) -> None:
    import json
    from pathlib import Path

    from rich.table import Table

    from riskope.clustering.validator import IndustryClusteringValidator
    from riskope.models import CompanyRiskProfile

    profiles: list[CompanyRiskProfile] = []
    for p in profile_paths:
        path = Path(p)
        if not path.exists():
            console.print(f"[red]파일 없음: {path}[/]")
            sys.exit(1)
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            profiles.extend(CompanyRiskProfile.model_validate(item) for item in data)
        else:
            profiles.append(CompanyRiskProfile.model_validate(data))

    map_path = Path(industry_map_path)
    if not map_path.exists():
        console.print(f"[red]산업 코드 매핑 파일 없음: {map_path}[/]")
        sys.exit(1)
    industry_codes: dict[str, str] = json.loads(map_path.read_text(encoding="utf-8"))

    validator = IndustryClusteringValidator(taxonomy_level=level)
    result = validator.validate(profiles, industry_codes, level)

    table = Table(title="산업 클러스터링 검증 결과 (Section 4.3)")
    table.add_column("지표", style="cyan")
    table.add_column("값", justify="right", style="bold")

    table.add_row("기업 수", str(result.n_companies))
    table.add_row("카테고리 수", str(result.n_categories))
    table.add_row("택소노미 레벨", result.taxonomy_level)
    table.add_row("동일 산업 평균 유사도", f"{result.same_industry_mean_similarity:.4f}")
    table.add_row("다른 산업 평균 유사도", f"{result.diff_industry_mean_similarity:.4f}")
    table.add_row("상대적 증가율", f"{result.relative_increase_pct:.1f}%")
    table.add_row("Cohen's d", f"{result.cohens_d:.3f}")
    table.add_row("AUC-ROC", f"{result.auc_score:.3f}")
    table.add_row("p-value", f"{result.p_value:.2e}")

    console.print(table)


async def _cmd_corp_update(force: bool) -> None:
    """DART 기업 목록 다운로드/업데이트."""
    from openai import AsyncOpenAI

    from riskope.dart.corp_index import DartCorpIndex

    settings = get_settings()
    _validate_keys(settings)

    index = DartCorpIndex(
        dart_api_key=settings.dart_api_key,
        openai_client=AsyncOpenAI(api_key=settings.openai_api_key),
        embedding_model=settings.embedding_model,
        embedding_dimensions=settings.embedding_dimensions,
    )
    stats = await index.update(force=force)

    from rich.table import Table

    table = Table(title="DART 기업 목록 업데이트 결과")
    table.add_column("항목", style="cyan")
    table.add_column("값", justify="right", style="bold")
    table.add_row("전체", str(stats.total))
    table.add_row("신규", str(stats.new))
    table.add_row("변경", str(stats.changed))
    table.add_row("삭제", str(stats.deleted))
    table.add_row("임베딩 생성", str(stats.embedded))
    console.print(table)


async def _cmd_corp_search(query: str, mode: str, limit: int) -> None:
    """DART 기업 검색."""
    from openai import AsyncOpenAI

    from riskope.dart.corp_index import DartCorpIndex

    settings = get_settings()
    if mode in ("semantic", "hybrid", "auto"):
        if not settings.openai_api_key:
            console.print("[red]RISKOPE_OPENAI_API_KEY 환경변수를 설정해주세요[/]")
            sys.exit(1)

    index = DartCorpIndex(
        dart_api_key=settings.dart_api_key,
        openai_client=AsyncOpenAI(api_key=settings.openai_api_key),
        embedding_model=settings.embedding_model,
        embedding_dimensions=settings.embedding_dimensions,
    )
    results = await index.search(query, mode=mode, limit=limit)

    if not results:
        console.print("[yellow]검색 결과 없음[/]")
        return

    from rich.table import Table

    table = Table(title=f"기업 검색 결과: '{query}' (mode={mode})")
    table.add_column("#", justify="right", style="dim")
    table.add_column("고유번호", style="cyan")
    table.add_column("기업명", style="bold")
    table.add_column("영문명")
    table.add_column("종목코드", style="green")
    table.add_column("점수", justify="right")

    for i, r in enumerate(results, 1):
        score_str = f"{r['score']:.4f}" if r.get("score") is not None else "-"
        table.add_row(
            str(i),
            r["corp_code"],
            r["corp_name"],
            r.get("corp_eng_name", ""),
            r.get("stock_code", "") or "-",
            score_str,
        )

    console.print(table)


def _validate_keys(settings: Settings) -> None:
    """필수 API 키 검증."""
    if not settings.dart_api_key:
        console.print("[red]RISKOPE_DART_API_KEY 환경변수를 설정해주세요[/]")
        sys.exit(1)
    if not settings.openai_api_key:
        console.print("[red]RISKOPE_OPENAI_API_KEY 환경변수를 설정해주세요[/]")
        sys.exit(1)


def _validate_sec_keys(settings: Settings) -> None:
    """SEC 파이프라인 필수 API 키 검증."""
    if not settings.massive_api_key:
        console.print("[red]RISKOPE_MASSIVE_API_KEY 환경변수를 설정해주세요[/]")
        sys.exit(1)
    if not settings.openai_api_key:
        console.print("[red]RISKOPE_OPENAI_API_KEY 환경변수를 설정해주세요[/]")
        sys.exit(1)


if __name__ == "__main__":
    main()
