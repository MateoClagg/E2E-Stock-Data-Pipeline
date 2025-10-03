"""
Pytest configuration for stock-pipeline tests.
"""
import pytest


def pytest_addoption(parser):
    """Add custom pytest command-line options."""
    parser.addoption(
        "--runlive",
        action="store_true",
        default=False,
        help="Run integration tests against live FMP API and S3"
    )


def pytest_configure(config):
    """Register custom pytest markers."""
    config.addinivalue_line(
        "markers", "integration: mark test as integration test requiring live API or S3"
    )


def pytest_collection_modifyitems(config, items):
    """Skip integration tests unless --runlive flag is provided."""
    if config.getoption("--runlive"):
        return

    skip_integration = pytest.mark.skip(reason="need --runlive option to run integration tests")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)