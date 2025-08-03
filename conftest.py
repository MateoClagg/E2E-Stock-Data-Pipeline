import pytest


def pytest_addoption(parser):
    """Add --runlive flag to enable integration tests."""
    parser.addoption(
        "--runlive", 
        action="store_true", 
        default=False, 
        help="Run integration tests against live APIs"
    )


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "integration: mark test as integration test requiring live API or Spark"
    )
    config.addinivalue_line(
        "markers", "spark: mark test as requiring Spark session"
    )


def pytest_collection_modifyitems(config, items):
    """Skip integration tests unless --runlive is specified."""
    if config.getoption("--runlive"):
        return
    
    skip_integration = pytest.mark.skip(reason="need --runlive option to run")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)