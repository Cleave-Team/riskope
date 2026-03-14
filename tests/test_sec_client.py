from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from riskope.sec.client import MassiveSecClient


@pytest.fixture()
def client():
    return MassiveSecClient(api_key="test-key")


def _make_mock_response(json_data: dict, status_code: int = 200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.raise_for_status = MagicMock()
    resp.json.return_value = json_data
    return resp


class TestBaseParams:
    def test_api_key_in_params(self, client: MassiveSecClient):
        params = client._base_params()
        assert params["apiKey"] == "test-key"


class TestFetchRiskFactors:
    @pytest.mark.asyncio()
    async def test_returns_text_on_success(self, client: MassiveSecClient):
        mock_resp = _make_mock_response(
            {
                "status": "OK",
                "results": [{"ticker": "AAPL", "filing_date": "2024-11-01", "text": "A" * 200}],
            }
        )

        with patch("riskope.sec.client.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.get.return_value = mock_resp
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_http

            result = await client.fetch_risk_factors("AAPL")

        assert result is not None
        assert len(result) == 200

    @pytest.mark.asyncio()
    async def test_returns_none_on_empty_results(self, client: MassiveSecClient):
        mock_resp = _make_mock_response({"status": "OK", "results": []})

        with patch("riskope.sec.client.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.get.return_value = mock_resp
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_http

            result = await client.fetch_risk_factors("INVALID")

        assert result is None

    @pytest.mark.asyncio()
    async def test_returns_none_on_short_text(self, client: MassiveSecClient):
        mock_resp = _make_mock_response(
            {
                "status": "OK",
                "results": [{"ticker": "X", "text": "too short"}],
            }
        )

        with patch("riskope.sec.client.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.get.return_value = mock_resp
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_http

            result = await client.fetch_risk_factors("X")

        assert result is None

    @pytest.mark.asyncio()
    async def test_returns_none_on_api_error(self, client: MassiveSecClient):
        with patch("riskope.sec.client.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.get.side_effect = Exception("connection error")
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_http

            result = await client.fetch_risk_factors("AAPL")

        assert result is None

    @pytest.mark.asyncio()
    async def test_passes_filing_date_param(self, client: MassiveSecClient):
        mock_resp = _make_mock_response(
            {
                "status": "OK",
                "results": [{"ticker": "MSFT", "filing_date": "2024-07-27", "text": "B" * 200}],
            }
        )

        with patch("riskope.sec.client.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.get.return_value = mock_resp
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_http

            await client.fetch_risk_factors("MSFT", filing_date="2024-07-27")

            call_kwargs = mock_http.get.call_args
            params = call_kwargs.kwargs.get("params", {})
            assert params["filing_date"] == "2024-07-27"
            assert params["ticker"] == "MSFT"
            assert params["apiKey"] == "test-key"


class TestFetchRiskFactorsForFiling:
    @pytest.mark.asyncio()
    async def test_returns_text_directly_if_present(self, client: MassiveSecClient):
        filing = {"ticker": "AAPL", "filing_date": "2024-01-01", "text": "C" * 200}
        result = await client.fetch_risk_factors_for_filing(filing)
        assert result == "C" * 200

    @pytest.mark.asyncio()
    async def test_returns_none_for_empty_filing(self, client: MassiveSecClient):
        filing = {"ticker": "", "filing_date": "", "text": ""}
        result = await client.fetch_risk_factors_for_filing(filing)
        assert result is None
