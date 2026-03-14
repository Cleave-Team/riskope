import pytest

from riskope.api.service import extract_report_year, is_annual_report


class TestExtractReportYear:
    def test_standard_format(self):
        assert extract_report_year("사업보고서 (2023.12)", "20240314") == 2023

    def test_no_space(self):
        assert extract_report_year("사업보고서(2023.12)", "20240314") == 2023

    def test_amendment_prefix(self):
        assert extract_report_year("[기재정정]사업보고서 (2023.12)", "20240415") == 2023

    def test_fallback_q1_filing(self):
        assert extract_report_year("사업보고서", "20240314") == 2023

    def test_fallback_q2_filing(self):
        assert extract_report_year("사업보고서", "20240601") == 2024

    def test_year_only_in_parens(self):
        assert extract_report_year("사업보고서 (2022)", "20230315") == 2022


class TestIsAnnualReport:
    def test_annual_report(self):
        assert is_annual_report("사업보고서 (2023.12)") is True

    def test_amendment(self):
        assert is_annual_report("[기재정정]사업보고서 (2023.12)") is True

    def test_semi_annual(self):
        assert is_annual_report("반기보고서 (2023.06)") is False

    def test_quarterly(self):
        assert is_annual_report("분기보고서 (2023.09)") is False

    def test_unrelated(self):
        assert is_annual_report("합병등종료보고서") is False
