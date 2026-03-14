"""Massive.com SEC API 클라이언트.

논문 Section 4.1 — Massive.com의 SEC AI-Ready APIs로
10-K Item 1A (Risk Factors) 섹션의 clean plain text를 직접 제공받는다.
"""

from __future__ import annotations

import asyncio
import logging

import httpx

logger = logging.getLogger(__name__)

MASSIVE_API_BASE = "https://api.massive.com"
MASSIVE_10K_SECTIONS = "/stocks/filings/10-K/vX/sections"

_USER_AGENT = "Mozilla/5.0 (compatible; riskope/0.1)"


class MassiveSecClient:
    """Massive.com SEC API를 통해 10-K Item 1A를 가져오는 async 클라이언트."""

    def __init__(self, api_key: str, concurrency: int = 5) -> None:
        self._api_key = api_key
        self._semaphore = asyncio.Semaphore(concurrency)

    def _base_params(self) -> dict[str, str]:
        return {"apiKey": self._api_key}

    async def fetch_risk_factors(
        self,
        ticker: str,
        filing_date: str | None = None,
        period_end: str | None = None,
    ) -> str | None:
        """특정 기업의 10-K Item 1A (Risk Factors) 텍스트를 가져온다.

        Args:
            ticker: 종목 티커 (예: "AAPL").
            filing_date: filing date 필터 (YYYY-MM-DD).
            period_end: period end date 필터 (YYYY-MM-DD).

        Returns:
            Item 1A plain text. 없으면 None.
        """
        async with self._semaphore:
            params = {
                **self._base_params(),
                "ticker": ticker,
                "section": "risk_factors",
                "limit": "1",
                "sort": "period_end.desc",
            }
            if filing_date:
                params["filing_date"] = filing_date
            if period_end:
                params["period_end"] = period_end

            async with httpx.AsyncClient(
                timeout=60.0,
                follow_redirects=True,
                headers={"User-Agent": _USER_AGENT},
            ) as client:
                try:
                    resp = await client.get(
                        f"{MASSIVE_API_BASE}{MASSIVE_10K_SECTIONS}",
                        params=params,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                except Exception:
                    logger.exception("Massive API 요청 실패: ticker=%s", ticker)
                    return None

            results = data.get("results", [])
            if not results:
                logger.warning("Risk factors 없음: ticker=%s", ticker)
                return None

            text = results[0].get("text", "")
            if not text or len(text) < 100:
                logger.warning("Risk factors 텍스트 너무 짧음: ticker=%s, %d자", ticker, len(text))
                return None

            logger.info(
                "Risk factors 가져옴: ticker=%s, filing_date=%s, %d자",
                ticker,
                results[0].get("filing_date", ""),
                len(text),
            )
            return text

    async def find_filings(
        self,
        ticker: str,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        """특정 기업의 10-K filing 목록을 조회한다.

        Args:
            ticker: 종목 티커.
            start_date: 시작일 (YYYY-MM-DD).
            end_date: 종료일 (YYYY-MM-DD).
            limit: 최대 결과 수.

        Returns:
            filing 메타데이터 리스트.
        """
        all_items: list[dict] = []

        async with self._semaphore:
            params = {
                **self._base_params(),
                "ticker": ticker,
                "section": "risk_factors",
                "limit": str(limit),
                "sort": "period_end.desc",
            }
            if start_date:
                params["filing_date.gte"] = start_date
            if end_date:
                params["filing_date.lte"] = end_date

            async with httpx.AsyncClient(
                timeout=60.0,
                follow_redirects=True,
                headers={"User-Agent": _USER_AGENT},
            ) as client:
                url: str | None = f"{MASSIVE_API_BASE}{MASSIVE_10K_SECTIONS}"
                is_first = True

                while url:
                    try:
                        if is_first:
                            resp = await client.get(url, params=params)
                            is_first = False
                        else:
                            resp = await client.get(url)
                        resp.raise_for_status()
                        data = resp.json()
                    except Exception:
                        logger.exception("Massive API filing 목록 요청 실패: ticker=%s", ticker)
                        break

                    results = data.get("results", [])
                    all_items.extend(results)

                    url = data.get("next_url")
                    if url:
                        await asyncio.sleep(0.3)

        logger.info("10-K filings %d건 조회: ticker=%s", len(all_items), ticker)
        return all_items

    async def fetch_risk_factors_for_filing(self, filing: dict) -> str | None:
        """find_filings 결과의 개별 filing에서 risk factors 텍스트를 추출한다.

        Args:
            filing: find_filings()에서 반환된 dict.

        Returns:
            Item 1A plain text. 없으면 None.
        """
        text = filing.get("text", "")
        if text and len(text) >= 100:
            return text

        ticker = filing.get("ticker", "")
        filing_date = filing.get("filing_date", "")
        if ticker and filing_date:
            return await self.fetch_risk_factors(ticker=ticker, filing_date=filing_date)

        return None
