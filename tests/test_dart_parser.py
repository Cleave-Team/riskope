from riskope.dart.client import DartClient, _decode_dart_html, extract_risk_section_from_text


def test_extract_risk_section_standard():
    text = (
        "## 2. 회사의 개황\n"
        "some overview content\n"
        "## 3. 사업의 위험\n"
        "가. 시장 위험에 관한 사항\n"
        "당사는 환율 변동에 따른 외화 환산 손익 변동 위험에 노출되어 있습니다. "
        "이에 따라 환율 변동이 당사의 재무 상태 및 경영 성과에 중대한 영향을 미칠 수 있습니다.\n"
        "## 4. 재무에 관한 사항\n"
        "financial info here\n"
    )
    section = extract_risk_section_from_text(text)
    assert section is not None
    assert "시장 위험" in section
    assert "환율 변동" in section
    assert "재무에 관한 사항" not in section


def test_extract_risk_section_bold_format():
    text = (
        "**회사의 개황**\n"
        "overview\n"
        "**사업의 위험**\n"
        "나. 경기 변동에 따른 매출 감소 위험이 존재합니다. "
        "글로벌 경기 둔화 및 수요 감소가 예상되며 이에 따른 실적 악화가 우려됩니다. "
        "이러한 상황은 당사의 영업 이익에 부정적인 영향을 줄 수 있습니다.\n"
        "**4. 재무에 관한 사항**\n"
        "balance sheet\n"
    )
    section = extract_risk_section_from_text(text)
    assert section is not None
    assert "경기 변동" in section
    assert "balance sheet" not in section


def test_extract_risk_section_not_found():
    text = "## 1. 회사의 개요\n개요 내용\n## 2. 재무에 관한 사항\n재무 내용\n"
    section = extract_risk_section_from_text(text)
    assert section is None


def test_extract_risk_section_too_short():
    text = "## 3. 사업의 위험\n짧은 내용\n## 4. 재무에 관한 사항\n"
    section = extract_risk_section_from_text(text)
    assert section is None


def test_decode_dart_html_utf8():
    korean_text = "사업의 위험에 관한 사항입니다."
    raw = korean_text.encode("utf-8")
    decoded = _decode_dart_html(raw)
    assert "사업의 위험" in decoded


def test_decode_dart_html_cp949():
    korean_text = "사업의 위험에 관한 사항입니다."
    raw = korean_text.encode("cp949")
    decoded = _decode_dart_html(raw)
    assert "사업의 위험" in decoded


def test_extract_risk_section_korean_enumeration():
    text = (
        "## II. 사업의 내용\n"
        "사업 내용...\n"
        "## 가. 사업의 위험\n"
        "당사의 주요 리스크 요인으로는 금리 변동에 따른 순이자마진 축소 가능성이 있으며, "
        "이는 수익성에 직접적인 영향을 미칠 수 있습니다. "
        "또한 부동산 시장 하락 시 담보가치 하락으로 인한 부실채권 증가 위험이 존재합니다.\n"
        "## 나. 회사의 개황\n"
        "회사 개황...\n"
    )
    section = extract_risk_section_from_text(text)
    assert section is not None
    assert "금리 변동" in section
    assert "회사의 개황" not in section


def test_extract_risk_section_roman_numeral_end():
    text = (
        "# II. 사업의 내용\n"
        "## 1. 사업의 위험\n"
        "반도체 시장은 수요와 공급의 주기적 변동에 따라 시황이 급격히 변동할 수 있으며, "
        "이에 따라 당사의 매출 및 이익에 상당한 영향을 미칠 수 있습니다. "
        "또한 환율 변동에 따른 수출 가격 경쟁력 약화 위험도 존재합니다.\n"
        "# III. 재무에 관한 사항\n"
        "재무 정보...\n"
    )
    section = extract_risk_section_from_text(text)
    assert section is not None
    assert "반도체" in section
    assert "재무에 관한 사항" not in section


def test_extract_risk_section_subsection_with_number():
    text = (
        "앞부분 내용...\n"
        "2. 사업의 위험\n"
        "가. 산업 위험\n"
        "글로벌 경기 둔화가 지속될 경우 당사의 주력 수출 제품 수요 감소가 불가피하며, "
        "원자재 가격 상승으로 인한 원가 부담 증가가 수익성 악화로 이어질 수 있습니다. "
        "특히 중국 시장 의존도가 높아 중국 경제 둔화 시 매출 감소 폭이 클 것으로 예상됩니다.\n"
        "3. 주요 재무에 관한 사항\n"
        "재무...\n"
    )
    section = extract_risk_section_from_text(text)
    assert section is not None
    assert "원자재" in section


# ---------------------------------------------------------------------------
# Tree node 파싱 테스트
# ---------------------------------------------------------------------------

_SAMPLE_MAIN_HTML = """
<html><body>
<script>
var node1 = {};
node1['text'] = "I. 회사의 개요";
node1['id'] = "1";
node1['rcpNo'] = "20240315000957";
node1['dcmNo'] = "9723371";
node1['eleId'] = "1";
node1['offset'] = "0";
node1['length'] = "50000";
node1['dtd'] = "dart4.xsd";
tree.add(node1, 0);

var node2 = {};
node2['text'] = "II. 사업의 내용";
node2['id'] = "5";
node2['rcpNo'] = "20240315000957";
node2['dcmNo'] = "9723371";
node2['eleId'] = "5";
node2['offset'] = "50000";
node2['length'] = "120000";
node2['dtd'] = "dart4.xsd";
tree.add(node2, 0);

var node3 = {};
node3['text'] = "5. 위험관리 및 파생거래";
node3['id'] = "14";
node3['rcpNo'] = "20240315000957";
node3['dcmNo'] = "9723371";
node3['eleId'] = "14";
node3['offset'] = "274672";
node3['length'] = "92478";
node3['dtd'] = "dart4.xsd";
tree.add(node3, node2);
</script>
</body></html>
"""


def test_parse_tree_nodes():
    nodes = DartClient._parse_tree_nodes(_SAMPLE_MAIN_HTML)
    assert len(nodes) == 3
    assert nodes[0]["text"] == "I. 회사의 개요"
    assert nodes[0]["eleId"] == "1"
    assert nodes[2]["text"] == "5. 위험관리 및 파생거래"
    assert nodes[2]["dcmNo"] == "9723371"
    assert nodes[2]["offset"] == "274672"
    assert nodes[2]["length"] == "92478"


def test_parse_tree_nodes_empty():
    nodes = DartClient._parse_tree_nodes("<html><body>no nodes</body></html>")
    assert nodes == []


def test_find_risk_nodes_multi_sections():
    """사업의 위험이 없으면 사업의 내용 + 위험관리 모두 반환."""
    nodes = DartClient._parse_tree_nodes(_SAMPLE_MAIN_HTML)
    result = DartClient._find_risk_nodes(nodes)
    assert len(result) == 2
    texts = [n["text"] for n in result]
    assert any("사업의 내용" in t for t in texts)
    assert any("위험관리" in t for t in texts)


def test_find_risk_nodes_saup_risk_alone():
    """사업의 위험이 있으면 그것만 반환 (단독 충분)."""
    nodes = [
        {"text": "II. 사업의 내용", "id": "1", "rcpNo": "x", "dcmNo": "x",
         "eleId": "1", "offset": "0", "length": "100", "dtd": "d"},
        {"text": "3. 사업의 위험", "id": "2", "rcpNo": "x", "dcmNo": "x",
         "eleId": "2", "offset": "100", "length": "200", "dtd": "d"},
        {"text": "5. 위험관리 및 파생거래", "id": "3", "rcpNo": "x", "dcmNo": "x",
         "eleId": "3", "offset": "300", "length": "50", "dtd": "d"},
    ]
    result = DartClient._find_risk_nodes(nodes)
    assert len(result) == 1
    assert "사업의 위험" in result[0]["text"]


def test_find_risk_nodes_saup_content_only():
    """위험관리 노드 없으면 사업의 내용만 반환."""
    nodes = [
        {"text": "I. 회사의 개요", "id": "1", "rcpNo": "x", "dcmNo": "x",
         "eleId": "1", "offset": "0", "length": "100", "dtd": "d"},
        {"text": "II. 사업의 내용", "id": "2", "rcpNo": "x", "dcmNo": "x",
         "eleId": "2", "offset": "100", "length": "200", "dtd": "d"},
    ]
    result = DartClient._find_risk_nodes(nodes)
    assert len(result) == 1
    assert "사업의 내용" in result[0]["text"]


def test_find_risk_nodes_empty():
    """매칭 노드가 없으면 빈 리스트."""
    nodes = [
        {"text": "I. 회사의 개요", "id": "1", "rcpNo": "x", "dcmNo": "x",
         "eleId": "1", "offset": "0", "length": "100", "dtd": "d"},
        {"text": "III. 재무에 관한 사항", "id": "2", "rcpNo": "x", "dcmNo": "x",
         "eleId": "2", "offset": "100", "length": "200", "dtd": "d"},
    ]
    result = DartClient._find_risk_nodes(nodes)
    assert result == []
