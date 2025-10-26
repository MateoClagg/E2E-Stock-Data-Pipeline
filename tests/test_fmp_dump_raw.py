"""
Unit tests for FMP raw data dumper (statements + treasury rates).

Tests NDJSON record building, S3 path generation, and treasury backfill logic.
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
import json
import hashlib

# Import functions from ingestion script
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "stock_pipeline" / "scripts"))

from fmp_dump_raw import (
    build_record,
    ENDPOINTS,
)


class TestRecordBuilder:
    """Test NDJSON record construction with metadata."""

    @pytest.fixture
    def sample_income_payload(self):
        """Sample FMP income statement API response."""
        return {
            "date": "2023-12-31",
            "symbol": "AAPL",
            "revenue": 383285000000,
            "netIncome": 96995000000,
            "fillingDate": "2024-01-26",
        }

    @pytest.fixture
    def sample_treasury_payload(self):
        """Sample FMP treasury rates API response."""
        return {
            "date": "2024-10-25",
            "month1": 4.54,
            "month3": 4.52,
            "month6": 4.45,
            "year1": 4.21,
            "year2": 4.05,
            "year3": 3.98,
            "year5": 3.92,
            "year7": 3.96,
            "year10": 4.08,
            "year30": 4.35,
        }

    def test_build_record_income_statement(self, sample_income_payload):
        """Test building record for income statement."""
        endpoint = "income"
        symbol = "AAPL"
        as_of_date = "2024-10-26"
        fetched_at = datetime(2024, 10, 26, 8, 0, 0, tzinfo=timezone.utc)
        http_status = 200
        request_id = "test-request-123"

        record = build_record(
            endpoint=endpoint,
            symbol=symbol,
            as_of_date=as_of_date,
            payload_obj=sample_income_payload,
            fetched_at=fetched_at,
            http_status=http_status,
            request_id=request_id,
        )

        # Check required fields
        assert record["symbol"] == "AAPL"
        assert record["as_of_date"] == "2024-10-26"
        assert record["endpoint"] == "income"
        assert record["source"] == "FMP"
        assert record["http_status"] == 200
        assert record["request_id"] == "test-request-123"

        # Check payload is JSON string
        assert isinstance(record["payload"], str)
        payload_dict = json.loads(record["payload"])
        assert payload_dict["revenue"] == 383285000000

        # Check fiscal metadata extracted
        assert record["fiscal_period_end"] == "2023-12-31"
        assert record["filing_date"] == "2024-01-26"

        # Check hash
        assert isinstance(record["hash"], str)
        assert len(record["hash"]) == 64  # SHA256 hex length

    def test_build_record_treasury_rates(self, sample_treasury_payload):
        """Test building record for treasury rates (no symbol)."""
        endpoint = "treasury_rates"
        symbol = None  # Treasury is market-wide
        as_of_date = "2024-10-25"
        fetched_at = datetime(2024, 10, 25, 8, 0, 0, tzinfo=timezone.utc)
        http_status = 200
        request_id = "test-request-456"

        record = build_record(
            endpoint=endpoint,
            symbol=symbol,
            as_of_date=as_of_date,
            payload_obj=sample_treasury_payload,
            fetched_at=fetched_at,
            http_status=http_status,
            request_id=request_id,
        )

        # Check symbol is null for treasury
        assert record["symbol"] is None
        assert record["endpoint"] == "treasury_rates"
        assert record["as_of_date"] == "2024-10-25"

        # Check payload contains rates
        payload_dict = json.loads(record["payload"])
        assert payload_dict["year10"] == 4.08
        assert payload_dict["year30"] == 4.35

        # Check fiscal metadata (treasury has date but no filing)
        assert record["fiscal_period_end"] == "2024-10-25"

    def test_build_record_hash_deterministic(self, sample_income_payload):
        """Test that hash is deterministic for same payload."""
        endpoint = "income"
        symbol = "AAPL"
        as_of_date = "2024-10-26"
        fetched_at = datetime(2024, 10, 26, 8, 0, 0, tzinfo=timezone.utc)
        http_status = 200
        request_id = "test-request-1"

        record1 = build_record(
            endpoint, symbol, as_of_date, sample_income_payload,
            fetched_at, http_status, request_id
        )

        # Build again with different request_id and timestamp
        record2 = build_record(
            endpoint, symbol, as_of_date, sample_income_payload,
            datetime(2024, 10, 27, 8, 0, 0, tzinfo=timezone.utc),  # Different time
            http_status, "different-request-id"
        )

        # Hash should be the same (only depends on payload)
        assert record1["hash"] == record2["hash"]

    def test_build_record_hash_different_payloads(self, sample_income_payload):
        """Test that different payloads produce different hashes."""
        endpoint = "income"
        symbol = "AAPL"
        as_of_date = "2024-10-26"
        fetched_at = datetime(2024, 10, 26, 8, 0, 0, tzinfo=timezone.utc)
        http_status = 200
        request_id = "test-request"

        record1 = build_record(
            endpoint, symbol, as_of_date, sample_income_payload,
            fetched_at, http_status, request_id
        )

        # Modify payload slightly
        modified_payload = sample_income_payload.copy()
        modified_payload["revenue"] = 999999999

        record2 = build_record(
            endpoint, symbol, as_of_date, modified_payload,
            fetched_at, http_status, request_id
        )

        # Hashes should be different
        assert record1["hash"] != record2["hash"]

    def test_build_record_missing_fiscal_metadata(self):
        """Test handling of payload without fiscal metadata."""
        payload = {"someField": "someValue"}  # No date or filing fields

        record = build_record(
            endpoint="income",
            symbol="TEST",
            as_of_date="2024-10-26",
            payload_obj=payload,
            fetched_at=datetime.now(timezone.utc),
            http_status=200,
            request_id="test",
        )

        # Should still build record with null fiscal metadata
        assert record["fiscal_period_end"] is None
        assert record["filing_date"] is None


class TestEndpointConfiguration:
    """Test endpoint registry configuration."""

    def test_all_endpoints_have_required_fields(self):
        """Test that all endpoints have required configuration."""
        required_fields = {"url_template", "params", "per_symbol", "s3_path"}

        for endpoint_name, config in ENDPOINTS.items():
            for field in required_fields:
                assert field in config, f"{endpoint_name} missing {field}"

    def test_per_symbol_endpoints_have_symbol_placeholder(self):
        """Test that per-symbol endpoints have symbol placeholder in URL or params."""
        for endpoint_name, config in ENDPOINTS.items():
            if config["per_symbol"]:
                # Check if {symbol} is in URL template OR in params
                has_symbol_in_url = "{symbol}" in config["url_template"]
                has_symbol_in_params = any("{symbol}" in str(v) for v in config.get("params", {}).values())

                assert has_symbol_in_url or has_symbol_in_params, \
                    f"{endpoint_name} is per_symbol but has no {{symbol}} in URL or params"

    def test_s3_paths_use_correct_extensions(self):
        """Test that all S3 paths use .ndjson.gz extension."""
        for endpoint_name, config in ENDPOINTS.items():
            s3_path = config["s3_path"]
            assert s3_path.endswith(".ndjson.gz"), \
                f"{endpoint_name} S3 path should end with .ndjson.gz"

    def test_statements_have_no_date_partition(self):
        """Test that statement endpoints don't have dt= partition."""
        statement_endpoints = ["income", "balance_sheet", "cash_flow", "owner_earnings"]

        for endpoint_name in statement_endpoints:
            s3_path = ENDPOINTS[endpoint_name]["s3_path"]
            assert "dt=" not in s3_path, \
                f"{endpoint_name} should not have dt= partition (overwrites daily)"
            assert "symbol=" in s3_path, \
                f"{endpoint_name} should have symbol= partition"

    def test_treasury_has_date_partition(self):
        """Test that treasury rates has dt= partition."""
        treasury_path = ENDPOINTS["treasury_rates"]["s3_path"]
        assert "dt=" in treasury_path, "treasury_rates should have dt= partition"
        assert "symbol=" not in treasury_path, "treasury_rates is market-wide, no symbol"

    def test_treasury_supports_backfill(self):
        """Test that treasury rates is configured for backfill."""
        assert ENDPOINTS["treasury_rates"].get("supports_backfill") is True


class TestS3PathBuilding:
    """Test S3 path generation for different endpoints."""

    def test_income_statement_s3_path(self):
        """Test income statement S3 path format."""
        config = ENDPOINTS["income"]
        s3_path = config["s3_path"]

        # Should have placeholders
        assert "{symbol}" in s3_path
        assert "{date}" not in s3_path  # No date partition for statements

        # Format the path
        formatted = s3_path.format(symbol="AAPL")
        assert "symbol=AAPL" in formatted
        assert "AAPL-income.ndjson.gz" in formatted

    def test_treasury_rates_s3_path(self):
        """Test treasury rates S3 path format."""
        config = ENDPOINTS["treasury_rates"]
        s3_path = config["s3_path"]

        # Should have date placeholder
        assert "{date}" in s3_path
        assert "{symbol}" not in s3_path

        # Format the path
        formatted = s3_path.format(date="2024-10-25")
        assert "dt=2024-10-25" in formatted
        assert "treasury-rates-2024-10-25.ndjson.gz" in formatted

    def test_owner_earnings_s3_path(self):
        """Test owner earnings S3 path format."""
        config = ENDPOINTS["owner_earnings"]
        s3_path = config["s3_path"]

        formatted = s3_path.format(symbol="MSFT")
        assert "symbol=MSFT" in formatted
        assert "MSFT-owner-earnings.ndjson.gz" in formatted


class TestDataValidation:
    """Test data quality validations."""

    def test_record_has_all_required_fields(self):
        """Test that all required fields are present in record."""
        payload = {"date": "2024-10-25", "revenue": 100000}

        record = build_record(
            endpoint="income",
            symbol="TEST",
            as_of_date="2024-10-26",
            payload_obj=payload,
            fetched_at=datetime.now(timezone.utc),
            http_status=200,
            request_id="test-123",
        )

        required_fields = {
            "symbol", "as_of_date", "endpoint", "payload",
            "fetched_at", "source", "http_status", "request_id",
            "fiscal_period_end", "filing_date", "hash"
        }

        for field in required_fields:
            assert field in record, f"Missing required field: {field}"

    def test_fetched_at_is_iso_format(self):
        """Test that fetched_at is in ISO format string."""
        payload = {"date": "2024-10-25"}
        fetched_at = datetime(2024, 10, 26, 12, 30, 45, tzinfo=timezone.utc)

        record = build_record(
            endpoint="income",
            symbol="TEST",
            as_of_date="2024-10-26",
            payload_obj=payload,
            fetched_at=fetched_at,
            http_status=200,
            request_id="test",
        )

        # Should be ISO format string
        assert isinstance(record["fetched_at"], str)
        assert "2024-10-26T12:30:45" in record["fetched_at"]

    def test_payload_is_valid_json_string(self):
        """Test that payload is valid JSON string."""
        payload = {
            "date": "2024-10-25",
            "revenue": 1000000,
            "nested": {"key": "value"}
        }

        record = build_record(
            endpoint="income",
            symbol="TEST",
            as_of_date="2024-10-26",
            payload_obj=payload,
            fetched_at=datetime.now(timezone.utc),
            http_status=200,
            request_id="test",
        )

        # Should be valid JSON string
        assert isinstance(record["payload"], str)
        parsed = json.loads(record["payload"])
        assert parsed["revenue"] == 1000000
        assert parsed["nested"]["key"] == "value"


class TestHashComputation:
    """Test SHA256 hash computation for deduplication."""

    def test_hash_is_sha256(self):
        """Test that hash is SHA256 (64 character hex)."""
        payload = {"test": "data"}

        record = build_record(
            endpoint="income",
            symbol="TEST",
            as_of_date="2024-10-26",
            payload_obj=payload,
            fetched_at=datetime.now(timezone.utc),
            http_status=200,
            request_id="test",
        )

        # SHA256 hex digest is 64 characters
        assert len(record["hash"]) == 64
        assert all(c in "0123456789abcdef" for c in record["hash"])

    def test_hash_matches_manual_computation(self):
        """Test that hash matches manual SHA256 computation."""
        payload = {"date": "2024-10-25", "value": 12345}

        record = build_record(
            endpoint="income",
            symbol="TEST",
            as_of_date="2024-10-26",
            payload_obj=payload,
            fetched_at=datetime.now(timezone.utc),
            http_status=200,
            request_id="test",
        )

        # Manually compute hash
        payload_json = json.dumps(payload, sort_keys=True)
        expected_hash = hashlib.sha256(payload_json.encode()).hexdigest()

        assert record["hash"] == expected_hash

    def test_hash_uses_sorted_keys(self):
        """Test that hash uses sorted keys (order-independent)."""
        payload1 = {"z": 1, "a": 2, "m": 3}
        payload2 = {"a": 2, "m": 3, "z": 1}  # Same data, different order

        record1 = build_record(
            "income", "TEST", "2024-10-26", payload1,
            datetime.now(timezone.utc), 200, "test1"
        )

        record2 = build_record(
            "income", "TEST", "2024-10-26", payload2,
            datetime.now(timezone.utc), 200, "test2"
        )

        # Hashes should be identical despite different key order
        assert record1["hash"] == record2["hash"]
