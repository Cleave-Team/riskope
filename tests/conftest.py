from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def project_root() -> Path:
    return PROJECT_ROOT


@pytest.fixture()
def en_taxonomy_path(project_root: Path) -> Path:
    return project_root / "docs" / "massive_risk_categories.md"


@pytest.fixture()
def kr_taxonomy_path(project_root: Path) -> Path:
    return project_root / "docs" / "massive_risk_categories_kr.md"
