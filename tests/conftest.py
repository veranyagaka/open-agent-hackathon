"""
tests/conftest.py

Unit tests never touch the network: every test runs in csv mode.

A developer's .env may set STOCKWHY_DATA_SOURCE=zetaris (llm_client loads .env
on import, without overriding variables that are already set). Setting csv here,
before any test module is imported, wins over that, and the session fixture
keeps it so for module-scoped fixtures too. Tests that exercise Zetaris mode set
the variable themselves and mock scripts.check_zetaris.run_sql.
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ["STOCKWHY_DATA_SOURCE"] = "csv"
os.environ.pop("SAMPLE_MODE", None)


@pytest.fixture(autouse=True)
def _world_model_in_tmp(tmp_path, monkeypatch):
    monkeypatch.setenv("STOCKWHY_WORLD_MODEL_DB", str(tmp_path / "world_model.sqlite3"))


@pytest.fixture(scope="session", autouse=True)
def _force_csv_data_source():
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("STOCKWHY_DATA_SOURCE", "csv")
        mp.delenv("SAMPLE_MODE", raising=False)
        yield
