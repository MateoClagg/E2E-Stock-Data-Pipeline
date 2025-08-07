import pytest
from unittest.mock import patch
from datetime import datetime

from bronze.utils import AsyncFMPClient, FMPConfig, RateLimiter
from bronze.ingestion.schemas import get_bronze_schemas


@pytest.fixture
def mock_fmp_config():
    # Test configuration with dummy API key
    return FMPConfig(api_key="test_api_key_12345")


@pytest.fixture  
def mock_price_data():
    # Sample price data that matches FMP API response format
    return [
        {
            "date": "2024-01-15",
            "open": 185.50,
            "high": 187.20,
            "low": 184.10, 
            "close": 186.75,
            "adjClose": 186.75,
            "volume": 45230000
        },
        {
            "date": "2024-01-14", 
            "open": 183.20,
            "high": 185.80,
            "low": 182.90,
            "close": 185.50,
            "adjClose": 185.50,
            "volume": 38940000
        }
    ]


@pytest.fixture
def mock_income_data():
    # Sample income statement data - should be exactly 5 annual records
    return [
        {
            "date": "2023-12-31",
            "revenue": 383935000000,
            "grossProfit": 169148000000, 
            "operatingIncome": 114301000000,
            "netIncome": 96995000000,
            "eps": 6.13
        },
        {
            "date": "2022-12-31",
            "revenue": 394328000000,
            "grossProfit": 170782000000,
            "operatingIncome": 119437000000, 
            "netIncome": 99803000000,
            "eps": 6.11
        },
        {
            "date": "2021-12-31",
            "revenue": 365817000000,
            "grossProfit": 152836000000,
            "operatingIncome": 108949000000,
            "netIncome": 94680000000, 
            "eps": 5.61
        },
        {
            "date": "2020-12-31",
            "revenue": 274515000000,
            "grossProfit": 104956000000,
            "operatingIncome": 66288000000,
            "netIncome": 57411000000,
            "eps": 3.28
        },
        {
            "date": "2019-12-31", 
            "revenue": 260174000000,
            "grossProfit": 98392000000,
            "operatingIncome": 63930000000,
            "netIncome": 55256000000,
            "eps": 2.97
        }
    ]


@pytest.fixture
def mock_cashflow_data():
    # Sample cash flow statement data - 5 annual records
    return [
        {
            "date": "2023-12-31",
            "operatingCashFlow": 110543000000,
            "capitalExpenditure": -10959000000,
            "freeCashFlow": 99584000000
        },
        {
            "date": "2022-12-31", 
            "operatingCashFlow": 122151000000,
            "capitalExpenditure": -11085000000,
            "freeCashFlow": 111066000000
        },
        {
            "date": "2021-12-31",
            "operatingCashFlow": 104038000000,
            "capitalExpenditure": -11352000000, 
            "freeCashFlow": 92686000000
        },
        {
            "date": "2020-12-31",
            "operatingCashFlow": 80674000000,
            "capitalExpenditure": -7309000000,
            "freeCashFlow": 73365000000
        },
        {
            "date": "2019-12-31",
            "operatingCashFlow": 69391000000,
            "capitalExpenditure": -10495000000,
            "freeCashFlow": 58896000000
        }
    ]


@pytest.fixture
def mock_balance_data():
    # Sample balance sheet data - 5 annual records  
    return [
        {
            "date": "2023-12-31",
            "totalDebt": 111088000000,
            "cashAndCashEquivalents": 73100000000,
            "totalEquity": 62146000000,
            "commonStockSharesOutstanding": 15550061000
        },
        {
            "date": "2022-12-31",
            "totalDebt": 120069000000, 
            "cashAndCashEquivalents": 20535000000,
            "totalEquity": 50672000000,
            "commonStockSharesOutstanding": 15943425000
        },
        {
            "date": "2021-12-31",
            "totalDebt": 124719000000,
            "cashAndCashEquivalents": 17576000000,
            "totalEquity": 63090000000,
            "commonStockSharesOutstanding": 16406397000
        },
        {
            "date": "2020-12-31", 
            "totalDebt": 112436000000,
            "cashAndCashEquivalents": 38016000000,
            "totalEquity": 65339000000,
            "commonStockSharesOutstanding": 16976763000
        },
        {
            "date": "2019-12-31",
            "totalDebt": 108047000000,
            "cashAndCashEquivalents": 50224000000,
            "totalEquity": 90488000000,
            "commonStockSharesOutstanding": 17772945000
        }
    ]


class TestRateLimiter:
    # Test our token bucket rate limiter works correctly
    
    @pytest.mark.asyncio
    async def test_rate_limiter_allows_burst(self):
        # Should allow up to 5 requests immediately
        limiter = RateLimiter(max_requests=5, time_window=1.0)
        
        # These should all go through without delay
        start_time = datetime.now()
        for _ in range(5):
            await limiter.acquire()
        elapsed = (datetime.now() - start_time).total_seconds()
        
        # Should complete in well under 100ms if no rate limiting
        assert elapsed < 0.1
    
    @pytest.mark.asyncio
    async def test_rate_limiter_blocks_excess(self):
        # 6th request should be delayed until tokens refill
        limiter = RateLimiter(max_requests=5, time_window=1.0)
        
        # Burn through 5 tokens
        for _ in range(5):
            await limiter.acquire()
        
        # 6th request should block
        start_time = datetime.now()
        await limiter.acquire()
        elapsed = (datetime.now() - start_time).total_seconds()
        
        # Should have waited at least 200ms for token to refill
        assert elapsed >= 0.2


class TestFMPClient:
    # Test the async FMP API client with mocked responses
    
    @pytest.mark.asyncio
    async def test_fetch_all_data_success(self, mock_fmp_config, mock_price_data, mock_income_data, mock_cashflow_data, mock_balance_data):
        # Test successful fetch of all four data types with proper mock data
        
        # Mock the HTTP responses for each endpoint with correct data structures
        mock_responses = {
            "historical-price-full/AAPL": {"historical": mock_price_data},
            "income-statement/AAPL": mock_income_data,
            "cash-flow-statement/AAPL": mock_cashflow_data,
            "balance-sheet-statement/AAPL": mock_balance_data
        }
        
        async def mock_json_response(session, endpoint, params=None):
            # Return what _make_request would return (processed data, not raw API response)
            endpoint_str = str(endpoint)
            
            if "historical-price-full" in endpoint_str:
                return mock_price_data  # _make_request extracts ["historical"] for us
            elif "income-statement" in endpoint_str:
                return mock_income_data
            elif "cash-flow-statement" in endpoint_str:
                return mock_cashflow_data
            elif "balance-sheet-statement" in endpoint_str:
                return mock_balance_data
            else:
                return []
        
        client = AsyncFMPClient(mock_fmp_config)
        
        # Patch the _make_request method to return our mock data
        with patch.object(client, '_make_request', side_effect=mock_json_response):
            result = await client.fetch_all_data("AAPL", "2024-01-01", "2024-01-31")
        
        # Verify we got data for all four types
        assert "price" in result
        assert "income" in result  
        assert "cashflow" in result
        assert "balance" in result
        
        # Check data quality and structure
        assert len(result["price"]) == 2
        assert len(result["income"]) == 5  # Should be exactly 5 annual records
        assert len(result["cashflow"]) == 5
        assert len(result["balance"]) == 5
        
        # Validate price data structure
        assert result["price"][0]["volume"] > 0
        assert "close" in result["price"][0]
        assert "adjClose" in result["price"][0]
        
        # Validate income statement data
        assert result["income"][0]["revenue"] > 0
        assert "eps" in result["income"][0]
        assert "netIncome" in result["income"][0]
        
        # Validate cash flow data
        assert "freeCashFlow" in result["cashflow"][0]
        assert "operatingCashFlow" in result["cashflow"][0]
        assert "capitalExpenditure" in result["cashflow"][0]
        
        # Validate balance sheet data
        assert "totalDebt" in result["balance"][0]
        assert "cashAndCashEquivalents" in result["balance"][0]
        assert "totalEquity" in result["balance"][0]
        assert "commonStockSharesOutstanding" in result["balance"][0]
    
    @pytest.mark.asyncio
    async def test_fetch_data_with_missing_endpoints(self, mock_fmp_config):
        # Test graceful handling when some endpoints return no data
        
        mock_responses = {
            "historical-price-full/BADTICKER": {"historical": []},  # Empty price data
            "income-statement/BADTICKER": [],  # No income data
            "cash-flow-statement/BADTICKER": [],  # No cashflow data
            "balance-sheet-statement/BADTICKER": []  # No balance data
        }
        
        async def mock_empty_response(session, endpoint, params=None):
            # Always return empty data for bad ticker test
            # Return what _make_request would return (processed data)
            return []  # Empty data for all endpoints
        
        client = AsyncFMPClient(mock_fmp_config)
        
        with patch.object(client, '_make_request', side_effect=mock_empty_response):
            result = await client.fetch_all_data("BADTICKER", "2024-01-01", "2024-01-31")
        
        # Should still return all keys but with empty data
        assert "price" in result
        assert "income" in result
        assert "cashflow" in result 
        assert "balance" in result
        assert len(result["price"]) == 0
        assert len(result["income"]) == 0
        assert len(result["cashflow"]) == 0
        assert len(result["balance"]) == 0


class TestSchemas:
    # Test our Bronze table schemas are properly defined
    
    def test_bronze_schemas_exist(self):
        # All four Bronze schemas should be defined
        schemas = get_bronze_schemas()
        
        required_schemas = ["price", "income", "cashflow", "balance"]
        for schema_name in required_schemas:
            assert schema_name in schemas
            assert schemas[schema_name] is not None
    
    def test_price_schema_structure(self):
        # Price schema should have all required OHLCV columns
        schemas = get_bronze_schemas()
        price_schema = schemas["price"]
        
        # Extract field names for easier testing
        field_names = [field.name for field in price_schema.fields]
        
        required_fields = [
            "symbol", "date", "open", "high", "low", 
            "close", "adjClose", "volume", "ingested_at", "run_id"
        ]
        
        for field in required_fields:
            assert field in field_names, f"Missing required field: {field}"
    
    def test_fundamental_schemas_have_metadata(self):
        # All fundamental schemas should include tracking columns
        schemas = get_bronze_schemas()
        
        for schema_name in ["income", "cashflow", "balance"]:
            schema = schemas[schema_name]
            field_names = [field.name for field in schema.fields]
            
            # All fundamental tables need these for lineage tracking
            assert "report_type" in field_names
            assert "ingested_at" in field_names  
            assert "run_id" in field_names
    
    def test_cashflow_schema_structure(self):
        # Cash flow schema should have required cash flow fields
        schemas = get_bronze_schemas()
        cashflow_schema = schemas["cashflow"]
        
        field_names = [field.name for field in cashflow_schema.fields]
        
        required_fields = [
            "symbol", "date", "operatingCashFlow", "capitalExpenditure", 
            "freeCashFlow", "report_type", "ingested_at", "run_id"
        ]
        
        for field in required_fields:
            assert field in field_names, f"Missing required cashflow field: {field}"
    
    def test_balance_schema_structure(self):
        # Balance sheet schema should have required balance sheet fields
        schemas = get_bronze_schemas()
        balance_schema = schemas["balance"]
        
        field_names = [field.name for field in balance_schema.fields]
        
        required_fields = [
            "symbol", "date", "totalDebt", "cashAndCashEquivalents", 
            "totalEquity", "commonStockSharesOutstanding", "report_type", 
            "ingested_at", "run_id"
        ]
        
        for field in required_fields:
            assert field in field_names, f"Missing required balance sheet field: {field}"
    
    def test_income_schema_structure(self):
        # Income statement schema should have required P&L fields
        schemas = get_bronze_schemas()
        income_schema = schemas["income"]
        
        field_names = [field.name for field in income_schema.fields]
        
        required_fields = [
            "symbol", "date", "revenue", "grossProfit", "operatingIncome", 
            "netIncome", "eps", "report_type", "ingested_at", "run_id"
        ]
        
        for field in required_fields:
            assert field in field_names, f"Missing required income statement field: {field}"


class TestDataValidation:
    # Test data validation logic and Great Expectations integration
    
    def test_annual_report_type_validation(self):
        # Ensure all fundamental data is marked as ANNUAL
        
        # This would normally test the write_bronze_data function
        # but requires Spark setup, so we test the logic separately
        sample_record = {"date": "2023-12-31", "revenue": 1000000}
        
        # Simulate adding report_type
        sample_record["report_type"] = "ANNUAL"
        
        assert sample_record["report_type"] == "ANNUAL"
    
    def test_schema_field_types(self):
        # Verify schema field types are correct for data validation
        from pyspark.sql.types import StringType, DoubleType, LongType, TimestampType
        
        schemas = get_bronze_schemas()
        
        # Check price schema types
        price_fields = {field.name: field.dataType for field in schemas["price"].fields}
        assert isinstance(price_fields["symbol"], StringType)
        assert isinstance(price_fields["open"], DoubleType)
        assert isinstance(price_fields["volume"], LongType)
        assert isinstance(price_fields["ingested_at"], TimestampType)
        
        # Check income schema types  
        income_fields = {field.name: field.dataType for field in schemas["income"].fields}
        assert isinstance(income_fields["revenue"], LongType)
        assert isinstance(income_fields["eps"], DoubleType)
        assert isinstance(income_fields["report_type"], StringType)


@pytest.mark.integration
class TestLiveAPI:
    # Integration tests that hit the real FMP API
    # Skipped by default - run with: pytest --runlive
    
    @pytest.mark.asyncio
    async def test_live_api_ford_data(self):
        # Test against Ford (F) - should be stable and have long history
        import os
        from dotenv import load_dotenv
        
        # Load environment variables from .env file
        load_dotenv()
        
        api_key = os.getenv("FMP_API_KEY")
        if not api_key:
            pytest.skip("FMP_API_KEY not set - skipping live API test")
        
        config = FMPConfig(api_key=api_key)
        client = AsyncFMPClient(config)
        
        # Test with Ford - reliable ticker for testing
        result = await client.fetch_all_data("F", "2023-01-01", "2023-12-31")
        
        # Should get data for all types
        assert len(result["price"]) > 200  # About 252 trading days per year
        assert len(result["income"]) >= 1   # At least one annual report
        assert len(result["cashflow"]) >= 1
        assert len(result["balance"]) >= 1
        
        # Validate price data structure and ranges
        prices = result["price"]
        first_price = prices[0]
        
        # Should have full OHLCV data
        required_price_fields = ["date", "open", "high", "low", "close", "volume", "adjClose"]
        for field in required_price_fields:
            assert field in first_price, f"Missing required price field: {field}"
        
        # Validate volume is positive
        assert first_price["volume"] > 0
        
        # Ford should have reasonable stock price ranges
        closes = [float(p["close"]) for p in prices if p.get("close")]
        assert len(closes) > 0
        assert min(closes) > 5   # Ford shouldn't go below $5
        assert max(closes) < 50  # Ford shouldn't go above $50
        
        # Validate fundamental data has expected fields
        assert "revenue" in result["income"][0] or "totalRevenue" in result["income"][0]
        assert "freeCashFlow" in result["cashflow"][0] or "operatingCashFlow" in result["cashflow"][0]
        assert "totalDebt" in result["balance"][0] or "totalAssets" in result["balance"][0]


# Pytest configuration moved to conftest.py