from pathlib import Path

from riskope.taxonomy.loader import load_taxonomy


def test_load_en_only(en_taxonomy_path: Path):
    categories = load_taxonomy(en_taxonomy_path)
    assert len(categories) == 140

    first = categories[0]
    assert first.primary == "Governance And Stakeholder"
    assert first.secondary == "Organizational And Management"
    assert first.tertiary == "Performance Management And Accountability"
    assert first.key == "Governance And Stakeholder/Organizational And Management/Performance Management And Accountability"
    assert first.description_kr == ""

    last = categories[-1]
    assert last.primary == "Strategic And Competitive"
    assert last.secondary == "Market Position And Competition"
    assert last.tertiary == "Competitive Pressure And Market Share Loss"


def test_load_en_kr(en_taxonomy_path: Path, kr_taxonomy_path: Path):
    categories = load_taxonomy(en_taxonomy_path, kr_taxonomy_path)
    assert len(categories) == 140
    for cat in categories:
        assert cat.description_kr != "", f"Missing KR description for {cat.key}"


def test_kr_descriptions_match_positionally(en_taxonomy_path: Path, kr_taxonomy_path: Path):
    categories = load_taxonomy(en_taxonomy_path, kr_taxonomy_path)
    assert "성과 관리" in categories[0].description_kr
    assert "경쟁" in categories[139].description_kr


def test_parse_markdown_structure(en_taxonomy_path: Path):
    categories = load_taxonomy(en_taxonomy_path)

    primaries = {c.primary for c in categories}
    assert len(primaries) == 7

    secondaries = {(c.primary, c.secondary) for c in categories}
    assert len(secondaries) > 7

    for cat in categories:
        assert cat.key == f"{cat.primary}/{cat.secondary}/{cat.tertiary}"
        assert cat.description != ""
