import pathlib

import pytest

from agent_app.doubles import FakeERP

FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture
def erp() -> FakeERP:
    return FakeERP.from_fixtures(FIXTURES / "erp")


@pytest.fixture
def fixtures_dir() -> pathlib.Path:
    return FIXTURES
