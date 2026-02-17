"""Shared fixtures for memex tests."""
import pytest

@pytest.fixture
def tmp_db_path(tmp_path):
    """Path for a temporary database directory."""
    db_dir = tmp_path / "test-db"
    db_dir.mkdir()
    return str(db_dir)
