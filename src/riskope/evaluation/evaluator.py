from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import httpx
from rich.console import Console
from rich.table import Table

from riskope.evaluation.metrics import AggregateEvaluation, CompanyEvaluation
from riskope.models import CompanyRiskProfile
from riskope.sec.client import MASSIVE_API_BASE

logger = logging.getLogger(__name__)
console = Console()

_RISK_FACTORS_PATH = "/stocks/filings/vX/risk-factors"


class MassiveGroundTruthFetcher:
    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def fetch_ground_truth(
        self,
        ticker: str,
        filing_date: str | None = None,
    ) -> list[dict]:
        params: dict[str, str] = {
            "apiKey": self._api_key,
            "ticker": ticker,
            "limit": "200",
            "sort": "filing_date.desc",
        }
        if filing_date:
            params["filing_date"] = filing_date

        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            try:
                resp = await client.get(
                    f"{MASSIVE_API_BASE}{_RISK_FACTORS_PATH}",
                    params=params,
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception:
                logger.exception("Massive Risk Factors API 요청 실패: ticker=%s", ticker)
                return []

        return data.get("results", [])


def extract_categories_from_ground_truth(
    results: list[dict],
    filing_date: str | None = None,
) -> set[str]:
    if filing_date:
        results = [r for r in results if r.get("filing_date") == filing_date]
    elif results:
        latest_date = max(r.get("filing_date", "") for r in results)
        results = [r for r in results if r.get("filing_date") == latest_date]

    return {r["tertiary_category"] for r in results if "tertiary_category" in r}


def extract_categories_from_profile(profile: CompanyRiskProfile) -> set[str]:
    return {rf.tertiary for rf in profile.risk_factors}


def load_profile_from_json(path: Path) -> list[CompanyRiskProfile]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return [CompanyRiskProfile(**item) for item in data]
    return [CompanyRiskProfile(**data)]


def evaluate_single(
    predicted: set[str],
    ground_truth: set[str],
    ticker: str = "",
    filing_date: str = "",
) -> CompanyEvaluation:
    return CompanyEvaluation(
        ticker=ticker,
        filing_date=filing_date,
        predicted_categories=predicted,
        ground_truth_categories=ground_truth,
    )


def print_company_evaluation(ev: CompanyEvaluation) -> None:
    console.print(f"\n[bold cyan]{ev.ticker}[/] (filing: {ev.filing_date})")
    console.print(f"  Predicted: {len(ev.predicted_categories)} | Ground Truth: {len(ev.ground_truth_categories)}")
    console.print(f"  TP: {len(ev.true_positives)} | FP: {len(ev.false_positives)} | FN: {len(ev.false_negatives)}")
    console.print(
        f"  Precision: {ev.precision:.3f} | Recall: {ev.recall:.3f} | F1: {ev.f1:.3f} | Jaccard: {ev.jaccard:.3f}"
    )

    if ev.false_positives:
        console.print("  [yellow]False Positives (predicted but not in ground truth):[/]")
        for fp in sorted(ev.false_positives):
            console.print(f"    - {fp}")

    if ev.false_negatives:
        console.print("  [red]False Negatives (in ground truth but missed):[/]")
        for fn in sorted(ev.false_negatives):
            console.print(f"    - {fn}")


def print_aggregate_evaluation(agg: AggregateEvaluation) -> None:
    table = Table(title="Evaluation Summary")
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")

    table.add_row("Companies evaluated", str(len(agg.companies)))
    table.add_row("Macro Precision", f"{agg.macro_precision:.3f}")
    table.add_row("Macro Recall", f"{agg.macro_recall:.3f}")
    table.add_row("Macro F1", f"{agg.macro_f1:.3f}")
    table.add_row("Micro Precision", f"{agg.micro_precision:.3f}")
    table.add_row("Micro Recall", f"{agg.micro_recall:.3f}")
    table.add_row("Micro F1", f"{agg.micro_f1:.3f}")
    table.add_row("Mean Jaccard", f"{agg.mean_jaccard:.3f}")

    console.print(table)

    per_company = Table(title="Per-Company Results")
    per_company.add_column("Ticker", style="cyan")
    per_company.add_column("Pred", justify="right")
    per_company.add_column("GT", justify="right")
    per_company.add_column("TP", justify="right")
    per_company.add_column("FP", justify="right")
    per_company.add_column("FN", justify="right")
    per_company.add_column("Precision", justify="right")
    per_company.add_column("Recall", justify="right")
    per_company.add_column("F1", justify="right", style="bold")

    for c in agg.companies:
        per_company.add_row(
            c.ticker,
            str(len(c.predicted_categories)),
            str(len(c.ground_truth_categories)),
            str(len(c.true_positives)),
            str(len(c.false_positives)),
            str(len(c.false_negatives)),
            f"{c.precision:.3f}",
            f"{c.recall:.3f}",
            f"{c.f1:.3f}",
        )

    console.print(per_company)
