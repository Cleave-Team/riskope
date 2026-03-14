"""DART 전자공시시스템 클라이언트.

xgram-signal-collector의 dart_disclosure 패턴을 따름:
- httpx async 직접 사용
- 2-step viewer 접근 (main.do → viewer.do)
- tree node 기반 섹션별 fetch (UTF-8 인코딩)
- cp949/utf-8 인코딩 자동 감지 (전문 fallback용)
- markdownify로 HTML → markdown 변환
"""

from __future__ import annotations

import asyncio
import logging
import re
import warnings

import httpx
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from markdownify import markdownify

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

logger = logging.getLogger(__name__)

DART_API_URL = "https://opendart.fss.or.kr/api"
DART_VIEWER_BASE = "https://dart.fss.or.kr"

_USER_AGENT = "Mozilla/5.0 (compatible; riskope/0.1)"

# main.do JavaScript tree node 파싱 정규식
_TREE_NODE_RE = re.compile(
    r"var\s+(node\d+)\s*=\s*\{\};\s*\n"
    r"\s*\1\['text'\]\s*=\s*\"(.*?)\";\s*\n"
    r"\s*\1\['id'\]\s*=\s*\"(.*?)\";\s*\n"
    r"\s*\1\['rcpNo'\]\s*=\s*\"(.*?)\";\s*\n"
    r"\s*\1\['dcmNo'\]\s*=\s*\"(.*?)\";\s*\n"
    r"\s*\1\['eleId'\]\s*=\s*\"(.*?)\";\s*\n"
    r"\s*\1\['offset'\]\s*=\s*\"(.*?)\";\s*\n"
    r"\s*\1\['length'\]\s*=\s*\"(.*?)\";\s*\n"
    r"\s*\1\['dtd'\]\s*=\s*\"(.*?)\"",
)

# 위험 섹션 노드 매칭 패턴
_PAT_SAUP_RISK = re.compile(r"사업의\s*위험")           # 1순위: 전용 리스크 섹션 (Item 1A 대응)
_PAT_RISK_MGMT = re.compile(r"위험관리\s*(?:및|&)\s*파생거래")  # 재무 리스크
_PAT_SAUP_CONTENT = re.compile(r"사업의\s*내용")        # 사업 전체 (사업+기술+규제 리스크 포함)


def _decode_dart_html(raw: bytes) -> str:
    """DART HTML 바이트를 한글이 가장 많이 보이는 인코딩으로 디코딩."""
    hangul_re = re.compile(r"[\uac00-\ud7a3]")
    cjk_re = re.compile(r"[\u4e00-\u9fff]")

    utf8_text = raw.decode("utf-8", errors="replace")
    cp949_text = None
    try:
        cp949_text = raw.decode("cp949")
    except (UnicodeDecodeError, ValueError):
        pass

    if cp949_text is None:
        return utf8_text

    utf8_hangul = len(hangul_re.findall(utf8_text))
    cp949_hangul = len(hangul_re.findall(cp949_text))
    utf8_cjk = len(cjk_re.findall(utf8_text))

    if cp949_hangul > utf8_hangul and utf8_cjk > utf8_hangul:
        return cp949_text
    return utf8_text


class DartClient:
    """DART API를 통해 사업보고서의 위험 섹션을 추출하는 async 클라이언트."""

    def __init__(self, api_key: str, concurrency: int = 5) -> None:
        self._api_key = api_key
        self._semaphore = asyncio.Semaphore(concurrency)

    async def find_annual_reports(
        self,
        corp_code: str | None = None,
        bgn_de: str | None = None,
        end_de: str | None = None,
        page_count: int = 100,
    ) -> list[dict]:
        """DART API에서 사업보고서 목록 조회.

        Args:
            corp_code: DART 고유번호 (미지정 시 전체).
            bgn_de: 시작일 YYYYMMDD.
            end_de: 종료일 YYYYMMDD.
            page_count: 페이지당 건수.

        Returns:
            사업보고서 메타데이터 리스트.
        """
        all_items: list[dict] = []

        async with httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers={"User-Agent": _USER_AGENT},
        ) as client:
            page_no = 1
            while True:
                params: dict[str, str] = {
                    "crtfc_key": self._api_key,
                    "pblntf_ty": "A",
                    "pblntf_detail_ty": "A001",  # 사업보고서
                    "last_reprt_at": "Y",
                    "page_no": str(page_no),
                    "page_count": str(page_count),
                }
                if corp_code:
                    params["corp_code"] = corp_code
                if bgn_de:
                    params["bgn_de"] = bgn_de
                if end_de:
                    params["end_de"] = end_de

                try:
                    resp = await client.get(f"{DART_API_URL}/list.json", params=params)
                    resp.raise_for_status()
                    data = resp.json()
                except Exception:
                    logger.exception("DART API 요청 실패 (page %d)", page_no)
                    break

                status = data.get("status", "")
                if status == "013":
                    break
                if status != "000":
                    logger.warning("DART API 에러: status=%s, message=%s", status, data.get("message", ""))
                    break

                items = data.get("list", [])
                if not items:
                    break

                all_items.extend(items)

                total_page = int(data.get("total_page", 1))
                if page_no >= total_page:
                    break

                page_no += 1
                await asyncio.sleep(0.5)

        logger.info("사업보고서 %d건 조회", len(all_items))
        return all_items

    async def fetch_document_text(self, rcept_no: str) -> str | None:
        """DART viewer를 통해 공시 문서 전문 텍스트(markdown) 추출.

        xgram 패턴: main.do → viewDoc() 파싱 → viewer.do → HTML → markdown.

        Args:
            rcept_no: 접수번호.

        Returns:
            문서 전문 markdown 텍스트. 실패 시 None.
        """
        async with self._semaphore:
            async with httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
                headers={"User-Agent": _USER_AGENT},
            ) as client:
                return await self._fetch_full_document(client, rcept_no)

    async def fetch_risk_section(self, rcept_no: str) -> str | None:
        """사업보고서에서 '사업의 위험' 섹션만 추출.

        tree node 기반으로 위험 섹션을 직접 fetch하고,
        fallback 시에만 전문에서 regex 추출.

        Args:
            rcept_no: 접수번호.

        Returns:
            위험 섹션 markdown 텍스트. 찾지 못하면 None.
        """
        async with self._semaphore:
            async with httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
                headers={"User-Agent": _USER_AGENT},
            ) as client:
                text, used_fallback = await self._fetch_risk_content(client, rcept_no)

        if not text:
            return None

        if used_fallback:
            # 전문 또는 상위 섹션 — regex로 위험 섹션 추출 필요
            return extract_risk_section_from_text(text)
        else:
            # 이미 특정 위험 노드를 fetch함
            return text if len(text) >= 100 else None

    # ------------------------------------------------------------------
    # Static helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_tree_nodes(html: str) -> list[dict]:
        """main.do HTML에서 JavaScript tree node 메타데이터 추출."""
        nodes: list[dict] = []
        for m in _TREE_NODE_RE.finditer(html):
            nodes.append({
                "text": m.group(2),
                "id": m.group(3),
                "rcpNo": m.group(4),
                "dcmNo": m.group(5),
                "eleId": m.group(6),
                "offset": m.group(7),
                "length": m.group(8),
                "dtd": m.group(9),
            })
        return nodes

    @staticmethod
    def _find_risk_nodes(nodes: list[dict]) -> list[dict]:
        """위험 관련 tree node를 포괄적으로 선택.

        논문의 Item 1A 대응: 한국 보고서에서는 사업·기술·규제 리스크가
        여러 섹션에 분산되어 있으므로 복수 섹션을 가져옴.

        전략:
        1. '사업의 위험' 존재 → 그것만 반환 (US Item 1A 대응, 단독 충분)
        2. 그 외 → '사업의 내용' + '위험관리 및 파생거래' 모두 반환
        """
        # 1순위: 사업의 위험 (전용 리스크 섹션이 있으면 단독 충분)
        for node in nodes:
            if _PAT_SAUP_RISK.search(node["text"]):
                return [node]

        # 2순위: 사업의 내용 + 위험관리 및 파생거래 (둘 다 가져와서 합침)
        result: list[dict] = []
        for node in nodes:
            if _PAT_SAUP_CONTENT.search(node["text"]):
                result.append(node)
                break
        for node in nodes:
            if _PAT_RISK_MGMT.search(node["text"]):
                result.append(node)
                break

        return result

    # ------------------------------------------------------------------
    # Internal fetch methods
    # ------------------------------------------------------------------

    async def _fetch_main_page(
        self,
        client: httpx.AsyncClient,
        rcept_no: str,
    ) -> str | None:
        """main.do 페이지 HTML을 가져온다."""
        main_url = f"{DART_VIEWER_BASE}/dsaf001/main.do?rcpNo={rcept_no}"
        resp = await client.get(main_url)
        resp.raise_for_status()
        return resp.text

    async def _fetch_viewer_section(
        self,
        client: httpx.AsyncClient,
        node: dict,
    ) -> str:
        """tree node 정보로 viewer.do에서 특정 섹션 HTML을 가져와 markdown 변환."""
        viewer_url = (
            f"{DART_VIEWER_BASE}/report/viewer.do"
            f"?rcpNo={node['rcpNo']}&dcmNo={node['dcmNo']}"
            f"&eleId={node['eleId']}&offset={node['offset']}"
            f"&length={node['length']}&dtd={node['dtd']}"
        )
        resp = await client.get(viewer_url)
        resp.raise_for_status()

        # 섹션별 fetch는 UTF-8로 정상 인코딩됨
        html_text = resp.content.decode("utf-8", errors="replace")
        return self._html_to_markdown(html_text)

    async def _fetch_risk_content(
        self,
        client: httpx.AsyncClient,
        rcept_no: str,
    ) -> tuple[str | None, bool]:
        """위험 관련 콘텐츠를 tree node 기반으로 포괄적 fetch.

        논문의 Item 1A 대응: 한국 보고서는 리스크가 여러 섹션에 분산되므로
        '사업의 내용' + '위험관리 및 파생거래'를 모두 가져와서 합침.

        Returns:
            (텍스트, used_fallback) 튜플.
            used_fallback=True이면 전문 문서이므로 regex 추출 필요.
        """
        try:
            # Step 1: main.do 페이지 가져오기
            main_html = await self._fetch_main_page(client, rcept_no)
            if not main_html:
                return None, True

            # Step 2: tree node 파싱
            nodes = self._parse_tree_nodes(main_html)

            if nodes:
                # Step 3: 위험 관련 노드 선택 (복수 가능)
                risk_nodes = self._find_risk_nodes(nodes)

                if risk_nodes:
                    sections: list[str] = []
                    node_names: list[str] = []
                    for node in risk_nodes:
                        await asyncio.sleep(0.5)
                        text = await self._fetch_viewer_section(client, node)
                        if text and len(text) >= 50:
                            sections.append(text)
                            node_names.append(node["text"])

                    if sections:
                        combined = "\n\n---\n\n".join(sections)
                        logger.info(
                            "tree node fetch 성공: %s (rcept_no=%s, %d섹션, %d자)",
                            node_names, rcept_no, len(sections), len(combined),
                        )
                        return combined, False

            # Step 4: tree node 없으면 viewDoc fallback (전문)
            logger.info("tree node 없음, viewDoc fallback 사용: rcept_no=%s", rcept_no)
            match = re.search(
                r'viewDoc\s*\(\s*["\'](\d+)["\']\s*,\s*["\'](\d+)["\']',
                main_html,
            )
            if not match:
                logger.warning("dcmNo를 찾을 수 없음: rcept_no=%s", rcept_no)
                return None, True

            dcm_no = match.group(2)
            await asyncio.sleep(0.5)

            viewer_url = (
                f"{DART_VIEWER_BASE}/report/viewer.do"
                f"?rcpNo={rcept_no}&dcmNo={dcm_no}"
                f"&eleId=0&offset=0&length=0&dtd=HTML"
            )
            resp = await client.get(viewer_url)
            resp.raise_for_status()

            html_text = _decode_dart_html(resp.content)
            text = self._html_to_markdown(html_text)
            return text, True

        except Exception:
            logger.exception("위험 섹션 추출 실패: rcept_no=%s", rcept_no)
            return None, True

    async def _fetch_full_document(
        self,
        client: httpx.AsyncClient,
        rcept_no: str,
    ) -> str | None:
        """전문 문서 fetch (fetch_document_text용, 기존 동작 유지)."""
        try:
            main_html = await self._fetch_main_page(client, rcept_no)
            if not main_html:
                return None

            match = re.search(
                r'viewDoc\s*\(\s*["\'](\d+)["\']\s*,\s*["\'](\d+)["\']',
                main_html,
            )
            if not match:
                logger.warning("dcmNo를 찾을 수 없음: rcept_no=%s", rcept_no)
                return None

            dcm_no = match.group(2)
            await asyncio.sleep(0.5)

            viewer_url = (
                f"{DART_VIEWER_BASE}/report/viewer.do"
                f"?rcpNo={rcept_no}&dcmNo={dcm_no}"
                f"&eleId=0&offset=0&length=0&dtd=HTML"
            )
            resp = await client.get(viewer_url)
            resp.raise_for_status()

            html_text = _decode_dart_html(resp.content)
            return self._html_to_markdown(html_text)

        except Exception:
            logger.exception("viewer 추출 실패: rcept_no=%s", rcept_no)
            return None

    @staticmethod
    def _html_to_markdown(html_text: str) -> str:
        """HTML → clean markdown 변환."""
        soup = BeautifulSoup(html_text, "html.parser")
        for tag in soup.find_all(["style", "script"]):
            tag.decompose()
        return markdownify(str(soup), strip=["img"]).strip()


# ---------------------------------------------------------------------------
# 위험 섹션 파싱 (markdown 기반)
# ---------------------------------------------------------------------------

_RISK_START_PATTERNS = [
    re.compile(r"#+\s*(?:\d+\.?\s*)?(?:[가-힣]\.?\s*)?사업의?\s*위험", re.IGNORECASE),
    re.compile(r"\*\*\s*(?:\d+\.?\s*)?사업의?\s*위험\s*\*\*"),
    re.compile(r"(?:^|\n)\s*(?:\d+\.?\s*|[가-힣]\.?\s*)?사업의\s*위험", re.MULTILINE),
]

_NEXT_SECTION_PATTERNS = [
    re.compile(
        r"^#+\s*(?:\d+\.?\s*)?(?:[가-힣]\.?\s*)?(?:재무|회사의?\s*개황|기타|주주|임원|이사)",
        re.MULTILINE,
    ),
    re.compile(r"^#+\s*(?:II|III|IV|V)[\.\s]", re.MULTILINE),
    re.compile(
        r"^\*\*\s*(?:\d+\.?\s*)?(?:재무|회사|기타\s*투자)",
        re.MULTILINE,
    ),
    re.compile(
        r"(?:^|\n)\s*(?:\d+\.?\s*|[가-힣]\.?\s*)(?:주요\s*)?재무에\s*관한\s*사항",
        re.MULTILINE,
    ),
]


def extract_risk_section_from_text(text: str) -> str | None:
    """markdown 텍스트에서 '사업의 위험' 섹션만 추출."""
    start_pos = None
    for pattern in _RISK_START_PATTERNS:
        match = pattern.search(text)
        if match:
            start_pos = match.start()
            break

    if start_pos is None:
        logger.warning("'사업의 위험' 섹션을 찾을 수 없음")
        return None

    remaining = text[start_pos:]
    end_pos = len(remaining)

    for pattern in _NEXT_SECTION_PATTERNS:
        search_start = remaining.find("\n", 0)
        if search_start == -1:
            search_start = 100
        match = pattern.search(remaining, pos=search_start)
        if match and match.start() < end_pos:
            end_pos = match.start()

    section = remaining[:end_pos].strip()

    if len(section) < 100:
        logger.warning("위험 섹션이 너무 짧음: %d자", len(section))
        return None

    return section
