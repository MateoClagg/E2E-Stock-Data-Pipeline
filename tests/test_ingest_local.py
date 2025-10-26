"""
Unit tests for local S3 ingestion script.

Tests data validation, S3 key building, and Polars transformations.
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import polars as pl

# Import functions from ingestion script
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "stock_pipeline" / "scripts"))

from ingest_fmp_prices import (
    build_s3_key_daily,
    prices_to_polars,
    group_by_day,
)


class TestS3KeyBuilder:
    """Test S3 key generation for day-level partitioning."""

    def test_build_s3_key_daily(self):
        """Test daily S3 key structure (all symbols combined per day)."""
        key = build_s3_key_daily("2024-09-15")
        expected = "raw/fmp/prices/dt=2024-09-15/prices-2024-09-15.parquet"
        assert key == expected

    def test_build_s3_key_daily_custom_prefix(self):
        """Test custom S3 prefix for daily."""
        key = build_s3_key_daily("2024-01-01", prefix="staging/fmp/prices")
        expected = "staging/fmp/prices/dt=2024-01-01/prices-2024-01-01.parquet"
        assert key == expected


class TestPolarsTransformations:
    """Test data validation and Polars DataFrame operations."""

    @pytest.fixture
    def sample_fmp_prices(self):
        """Sample FMP API price response."""
        return [
            {
                "date": "2024-09-15",
                "open": 226.47,
                "high": 228.77,
                "low": 225.77,
                "close": 228.03,
                "adjClose": 228.03,
                "volume": 48542700,
            },
            {
                "date": "2024-09-14",
                "open": 225.01,
                "high": 226.50,
                "low": 224.27,
                "close": 225.77,
                "adjClose": 225.77,
                "volume": 43568100,
            },
        ]

    def test_prices_to_polars_basic(self, sample_fmp_prices):
        """Test conversion from FMP JSON to Polars DataFrame."""
        fetched_at = datetime.now(timezone.utc)
        request_id = "test-request-123"
        df = prices_to_polars("AAPL", sample_fmp_prices, fetched_at, request_id)

        assert not df.is_empty()
        assert len(df) == 2
        assert "symbol" in df.columns
        assert "fetched_at" in df.columns
        assert "request_id" in df.columns
        assert "file_hash" in df.columns
        assert df["symbol"][0] == "AAPL"
        assert df["request_id"][0] == request_id

    def test_prices_to_polars_validation_filters_invalid(self):
        """Test that invalid rows are filtered out."""
        invalid_prices = [
            {
                "date": "2024-09-15",
                "open": 100.0,
                "high": 105.0,
                "low": 99.0,
                "close": 102.0,
                "volume": 1000000,
            },
            {
                "date": None,  # Invalid: null date
                "open": 100.0,
                "high": 105.0,
                "low": 99.0,
                "close": 102.0,
                "volume": 1000000,
            },
            {
                "date": "2024-09-14",
                "open": 100.0,
                "high": 105.0,
                "low": 99.0,
                "close": 102.0,
                "volume": -500,  # Invalid: negative volume
            },
        ]

        fetched_at = datetime.now(timezone.utc)
        request_id = "test-request"
        df = prices_to_polars("TEST", invalid_prices, fetched_at, request_id)

        # Only 1 valid row should remain
        assert len(df) == 1
        assert df["as_of_date"][0] == "2024-09-15"

    def test_prices_to_polars_empty_input(self):
        """Test handling of empty price list."""
        fetched_at = datetime.now(timezone.utc)
        request_id = "test-request"
        df = prices_to_polars("EMPTY", [], fetched_at, request_id)

        assert df.is_empty()

    def test_prices_to_polars_sorted_by_date(self, sample_fmp_prices):
        """Test that DataFrame is sorted by date descending."""
        fetched_at = datetime.now(timezone.utc)
        request_id = "test-request"
        df = prices_to_polars("AAPL", sample_fmp_prices, fetched_at, request_id)

        dates = df["as_of_date"].to_list()
        assert dates == sorted(dates, reverse=True)


class TestGroupByDay:
    """Test grouping DataFrame by trade date (combines all symbols per day)."""

    def test_group_by_day_basic(self):
        """Test basic grouping by day."""
        dfs = [
            pl.DataFrame({
                "symbol": ["AAPL", "AAPL"],
                "as_of_date": ["2024-09-15", "2024-09-14"],
                "close": [228.03, 225.77],
            }),
            pl.DataFrame({
                "symbol": ["MSFT"],
                "as_of_date": ["2024-09-15"],
                "close": [420.50],
            }),
        ]

        grouped = group_by_day(dfs)

        assert len(grouped) == 2
        assert "2024-09-15" in grouped
        assert "2024-09-14" in grouped
        assert len(grouped["2024-09-15"]) == 2  # AAPL + MSFT
        assert len(grouped["2024-09-14"]) == 1  # AAPL only

    def test_group_by_day_empty_list(self):
        """Test grouping empty list."""
        grouped = group_by_day([])

        assert len(grouped) == 0


class TestDataValidation:
    """Test data quality validations."""

    def test_non_negative_volume_validation(self):
        """Test that negative volumes are filtered."""
        prices = [
            {"date": "2024-09-15", "open": 100, "high": 105, "low": 99, "close": 102, "volume": -1000},
        ]
        fetched_at = datetime.now(timezone.utc)
        request_id = "test-request"
        df = prices_to_polars("TEST", prices, fetched_at, request_id)

        assert df.is_empty()

    def test_non_null_symbol_date(self):
        """Test that null symbol/date are filtered."""
        prices = [
            {"date": None, "open": 100, "high": 105, "low": 99, "close": 102, "volume": 1000},
        ]
        fetched_at = datetime.now(timezone.utc)
        request_id = "test-request"
        df = prices_to_polars("TEST", prices, fetched_at, request_id)

        assert df.is_empty()


class TestDateUtilities:
    """Test date utility functions."""

    def test_trading_days_import(self):
        """Test that trading day utilities can be imported."""
        from stock_pipeline.scripts.utils.dates import get_trading_days, is_trading_day

        # Basic smoke test
        trading_days = get_trading_days("2024-09-01", "2024-09-30")
        assert len(trading_days) > 0
        assert len(trading_days) < 31  # Should exclude weekends

        # Test known trading day
        assert is_trading_day("2024-09-16")  # Monday

        # Test known non-trading day
        assert not is_trading_day("2024-09-14")  # Saturday

    def test_last_n_trading_days(self):
        """Test getting last N trading days."""
        from stock_pipeline.scripts.utils.dates import get_last_n_trading_days

        from_date, to_date = get_last_n_trading_days(5, end_date="2024-09-20")

        # Should return 5 trading days
        from stock_pipeline.scripts.utils.dates import get_trading_days
        days = get_trading_days(from_date, to_date)
        assert len(days) == 5


class TestSchemaLocking:
    """Test that output schema is locked to prevent drift."""

    def test_locked_column_output(self):
        """Test that only expected columns are in final output."""
        sample_prices = [
            {
                "date": "2024-09-15",
                "open": 226.47,
                "high": 228.77,
                "low": 225.77,
                "close": 228.03,
                "volume": 48542700,
                "extra_field": "should_be_ignored",  # Extra field from API
            },
        ]

        fetched_at = datetime.now(timezone.utc)
        request_id = "test-request"
        df = prices_to_polars("AAPL", sample_prices, fetched_at, request_id)

        # Expected locked columns (from ingest_fmp_prices.py)
        expected_cols = {
            "symbol", "as_of_date", "open", "high", "low", "close", "volume",
            "fetched_at", "source", "endpoint", "request_id", "file_hash"
        }

        actual_cols = set(df.columns)

        # Should have exactly the locked columns
        assert actual_cols == expected_cols

        # Should NOT have extra_field
        assert "extra_field" not in df.columns
