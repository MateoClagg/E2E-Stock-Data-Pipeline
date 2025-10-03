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

from ingest_local_to_s3 import (
    build_s3_key_daily,
    build_s3_key_yearly,
    prices_to_polars,
    group_by_day,
    group_by_year,
)


class TestS3KeyBuilder:
    """Test S3 key generation for day-level partitioning."""

    def test_build_s3_key_daily(self):
        """Test daily S3 key structure."""
        key = build_s3_key_daily("AAPL", "2024-09-15")
        expected = "raw/prices/symbol=AAPL/year=2024/month=09/AAPL-2024-09-15.parquet"
        assert key == expected

    def test_build_s3_key_daily_custom_prefix(self):
        """Test custom S3 prefix for daily."""
        key = build_s3_key_daily("MSFT", "2024-01-01", prefix="staging/prices")
        expected = "staging/prices/symbol=MSFT/year=2024/month=01/MSFT-2024-01-01.parquet"
        assert key == expected

    def test_build_s3_key_yearly(self):
        """Test yearly S3 key structure for backfill."""
        key = build_s3_key_yearly("AAPL", 2024)
        expected = "raw/prices/symbol=AAPL/year=2024/AAPL-2024.parquet"
        assert key == expected

    def test_build_s3_key_yearly_custom_prefix(self):
        """Test custom S3 prefix for yearly."""
        key = build_s3_key_yearly("TSLA", 2023, prefix="staging/prices")
        expected = "staging/prices/symbol=TSLA/year=2023/TSLA-2023.parquet"
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
        ingest_ts = datetime.now(timezone.utc)
        df = prices_to_polars("AAPL", sample_fmp_prices, ingest_ts)

        assert not df.is_empty()
        assert len(df) == 2
        assert "symbol" in df.columns
        assert "ingest_ts" in df.columns
        assert df["symbol"][0] == "AAPL"

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

        ingest_ts = datetime.now(timezone.utc)
        df = prices_to_polars("TEST", invalid_prices, ingest_ts)

        # Only 1 valid row should remain
        assert len(df) == 1
        assert df["date"][0] == "2024-09-15"

    def test_prices_to_polars_empty_input(self):
        """Test handling of empty price list."""
        ingest_ts = datetime.now(timezone.utc)
        df = prices_to_polars("EMPTY", [], ingest_ts)

        assert df.is_empty()

    def test_prices_to_polars_sorted_by_date(self, sample_fmp_prices):
        """Test that DataFrame is sorted by date descending."""
        ingest_ts = datetime.now(timezone.utc)
        df = prices_to_polars("AAPL", sample_fmp_prices, ingest_ts)

        dates = df["date"].to_list()
        assert dates == sorted(dates, reverse=True)


class TestGroupByDay:
    """Test grouping DataFrame by trade date."""

    def test_group_by_day_basic(self):
        """Test basic grouping by day."""
        df = pl.DataFrame({
            "symbol": ["AAPL", "AAPL", "AAPL"],
            "date": ["2024-09-15", "2024-09-14", "2024-09-15"],
            "close": [228.03, 225.77, 228.50],
        })

        grouped = group_by_day(df)

        assert len(grouped) == 2
        assert "2024-09-15" in grouped
        assert "2024-09-14" in grouped
        assert len(grouped["2024-09-15"]) == 2
        assert len(grouped["2024-09-14"]) == 1

    def test_group_by_day_empty_df(self):
        """Test grouping empty DataFrame."""
        df = pl.DataFrame()
        grouped = group_by_day(df)

        assert len(grouped) == 0


class TestDataValidation:
    """Test data quality validations."""

    def test_non_negative_volume_validation(self):
        """Test that negative volumes are filtered."""
        prices = [
            {"date": "2024-09-15", "open": 100, "high": 105, "low": 99, "close": 102, "volume": -1000},
        ]
        ingest_ts = datetime.now(timezone.utc)
        df = prices_to_polars("TEST", prices, ingest_ts)

        assert df.is_empty()

    def test_non_null_symbol_date(self):
        """Test that null symbol/date are filtered."""
        prices = [
            {"date": None, "open": 100, "high": 105, "low": 99, "close": 102, "volume": 1000},
        ]
        ingest_ts = datetime.now(timezone.utc)
        df = prices_to_polars("TEST", prices, ingest_ts)

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


@pytest.mark.integration
class TestS3Operations:
    """Integration tests for S3 operations (requires AWS credentials and S3_BUCKET env var)."""

    @pytest.fixture
    def s3_client(self):
        """Create real S3 client from environment."""
        import boto3
        import os

        # Skip if no credentials
        if not os.getenv("S3_BUCKET"):
            pytest.skip("S3_BUCKET not set - skipping integration test")

        return boto3.client("s3")

    @pytest.fixture
    def test_bucket(self):
        """Get test bucket from environment."""
        import os
        bucket = os.getenv("S3_BUCKET")
        if not bucket:
            pytest.skip("S3_BUCKET not set - skipping integration test")
        return bucket

    def test_write_parquet_to_s3_success(self, s3_client, test_bucket):
        """Test successful S3 write with real AWS."""
        from ingest_local_to_s3 import write_parquet_to_s3, build_s3_key_daily

        # Create test DataFrame
        df = pl.DataFrame({
            "symbol": ["TEST", "TEST"],
            "date": ["2024-09-15", "2024-09-15"],
            "open": [100.0, 100.5],
            "high": [105.0, 105.5],
            "low": [99.0, 99.5],
            "close": [102.0, 102.5],
            "adjClose": [102.0, 102.5],
            "volume": [1000000, 1000100],
            "ingest_ts": [datetime.now(timezone.utc), datetime.now(timezone.utc)],
        })

        # Build S3 key
        s3_key = build_s3_key_daily("TEST", "2024-09-15")

        # Test write with force=True (overwrite if exists)
        result = write_parquet_to_s3(
            df=df,
            s3_key=s3_key,
            s3_client=s3_client,
            bucket=test_bucket,
            force=True
        )

        # Verify write succeeded
        assert result is not None
        assert "symbol=TEST" in result
        assert "2024-09-15.parquet" in result

        # Verify file exists in S3
        s3_client.head_object(Bucket=test_bucket, Key=result)

    def test_write_parquet_to_s3_skip_existing(self, s3_client, test_bucket):
        """Test that existing files are skipped unless force=True."""
        from ingest_local_to_s3 import write_parquet_to_s3, build_s3_key_daily

        # Create test DataFrame
        df = pl.DataFrame({
            "symbol": ["TEST"],
            "date": ["2024-09-15"],
            "close": [102.0],
            "volume": [1000000],
            "ingest_ts": [datetime.now(timezone.utc)],
        })

        # Build S3 key
        s3_key = build_s3_key_daily("TEST", "2024-09-15")

        # First write
        result1 = write_parquet_to_s3(
            df=df,
            s3_key=s3_key,
            s3_client=s3_client,
            bucket=test_bucket,
            force=True
        )
        assert result1 is not None

        # Second write without force should skip
        result2 = write_parquet_to_s3(
            df=df,
            s3_key=s3_key,
            s3_client=s3_client,
            bucket=test_bucket,
            force=False
        )
        assert result2 is None  # Skipped
