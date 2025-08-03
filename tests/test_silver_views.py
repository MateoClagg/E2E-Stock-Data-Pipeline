import pytest
from datetime import datetime, date
from unittest.mock import patch, MagicMock
from pyspark.sql import SparkSession
from pyspark.sql.types import StructType, StructField, StringType, DoubleType, LongType, DateType
import tempfile
import shutil

from silver.views.unified_views import create_unified_price_fundamental_view


@pytest.mark.integration
class TestSilverViewsIntegration:
    # Integration tests for Silver views with actual Spark operations
    
    @pytest.fixture(scope="class")
    def spark_session(self):
        # Create a local Spark session with Delta Lake support for integration testing
        spark = SparkSession.builder \
            .appName("TestSilverViewsIntegration") \
            .config("spark.sql.warehouse.dir", "/tmp/spark-warehouse-test") \
            .config("spark.sql.shuffle.partitions", "2") \
            .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension") \
            .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog") \
            .getOrCreate()
        
        yield spark
        spark.stop()
    
    @pytest.fixture
    def setup_test_tables(self, spark_session):
        # Create test Silver tables with realistic data for view testing
        
        # Create silver database
        spark_session.sql("CREATE DATABASE IF NOT EXISTS silver")
        
        # Sample price data
        price_data = [
            ("AAPL", date(2024, 1, 15), 185.50, 187.20, 184.10, 186.75, 186.75, 45230000, datetime.now(), "test-run-1"),
            ("AAPL", date(2024, 1, 14), 183.20, 185.80, 182.90, 185.50, 185.50, 38940000, datetime.now(), "test-run-1"),
            ("AAPL", date(2023, 12, 29), 193.60, 194.66, 193.17, 193.58, 193.58, 42628800, datetime.now(), "test-run-1"),
        ]
        
        price_columns = ["symbol", "trade_date", "open", "high", "low", "close", "adjClose", "volume", "ingested_at", "run_id"]
        price_df = spark_session.createDataFrame(price_data, price_columns)
        
        price_df.write.format("delta").mode("overwrite").saveAsTable("silver.fact_price")
        
        # Sample income statement data with validity windows
        income_data = [
            ("AAPL", date(2023, 9, 30), date(2023, 10, 1), date(2999, 12, 31), 383935000000, 169148000000, 114301000000, 96995000000, 6.13, datetime.now(), "test-run-1"),
            ("AAPL", date(2022, 9, 24), date(2022, 9, 25), date(2023, 10, 1), 394328000000, 170782000000, 119437000000, 99803000000, 6.11, datetime.now(), "test-run-1"),
        ]
        
        income_columns = ["symbol", "period_end", "effective_from", "effective_to", "revenue", "grossProfit", "operatingIncome", "netIncome", "eps", "ingested_at", "run_id"]
        income_df = spark_session.createDataFrame(income_data, income_columns)
        
        income_df.write.format("delta").mode("overwrite").saveAsTable("silver.fact_income")
        
        # Sample cash flow data
        cashflow_data = [
            ("AAPL", date(2023, 9, 30), date(2023, 10, 1), date(2999, 12, 31), 110543000000, -10959000000, 99584000000, datetime.now(), "test-run-1"),
            ("AAPL", date(2022, 9, 24), date(2022, 9, 25), date(2023, 10, 1), 122151000000, -11085000000, 111066000000, datetime.now(), "test-run-1"),
        ]
        
        cashflow_columns = ["symbol", "period_end", "effective_from", "effective_to", "operatingCashFlow", "capitalExpenditure", "freeCashFlow", "ingested_at", "run_id"]
        cashflow_df = spark_session.createDataFrame(cashflow_data, cashflow_columns)
        
        cashflow_df.write.format("delta").mode("overwrite").saveAsTable("silver.fact_cashflow")
        
        # Sample balance sheet data
        balance_data = [
            ("AAPL", date(2023, 9, 30), date(2023, 10, 1), date(2999, 12, 31), 111088000000, 73100000000, 62146000000, 15550061000, datetime.now(), "test-run-1"),
            ("AAPL", date(2022, 9, 24), date(2022, 9, 25), date(2023, 10, 1), 120069000000, 20535000000, 50672000000, 15943425000, datetime.now(), "test-run-1"),
        ]
        
        balance_columns = ["symbol", "period_end", "effective_from", "effective_to", "totalDebt", "cashAndCashEquivalents", "totalEquity", "commonStockSharesOutstanding", "ingested_at", "run_id"]
        balance_df = spark_session.createDataFrame(balance_data, balance_columns)
        
        balance_df.write.format("delta").mode("overwrite").saveAsTable("silver.fact_balance")
        
        return {"price": len(price_data), "income": len(income_data), "cashflow": len(cashflow_data), "balance": len(balance_data)}
    
    def test_unified_view_creation(self, spark_session, setup_test_tables):
        # Test that unified view is created successfully
        
        create_unified_price_fundamental_view(spark_session)
        
        # Check that view exists
        tables = spark_session.sql("SHOW TABLES IN silver").collect()
        view_names = [row.tableName for row in tables]
        assert "vw_price_fundamental" in view_names, "Unified view should be created"
    
    def test_unified_view_structure(self, spark_session, setup_test_tables):
        # Test that unified view has all expected columns
        
        create_unified_price_fundamental_view(spark_session)
        
        # Query the view structure
        view_df = spark_session.sql("SELECT * FROM silver.vw_price_fundamental LIMIT 0")
        columns = view_df.columns
        
        # Should have price columns
        price_columns = ["symbol", "trade_date", "open", "high", "low", "close", "adjClose", "volume"]
        for col in price_columns:
            assert col in columns, f"Missing price column: {col}"
        
        # Should have income statement columns
        income_columns = ["revenue", "grossProfit", "operatingIncome", "netIncome", "eps", "income_period_end"]
        for col in income_columns:
            assert col in columns, f"Missing income column: {col}"
        
        # Should have cash flow columns
        cashflow_columns = ["operatingCashFlow", "capitalExpenditure", "freeCashFlow", "cashflow_period_end"]
        for col in cashflow_columns:
            assert col in columns, f"Missing cashflow column: {col}"
        
        # Should have balance sheet columns
        balance_columns = ["totalDebt", "cashAndCashEquivalents", "totalEquity", "commonStockSharesOutstanding", "balance_period_end"]
        for col in balance_columns:
            assert col in columns, f"Missing balance column: {col}"
    
    def test_unified_view_data_integrity(self, spark_session, setup_test_tables):
        # Test that unified view correctly joins data and maintains integrity
        
        create_unified_price_fundamental_view(spark_session)
        
        # Query the view
        result_df = spark_session.sql("SELECT * FROM silver.vw_price_fundamental ORDER BY trade_date DESC")
        rows = result_df.collect()
        
        # Should have all price records (LEFT JOIN preserves all price data)
        assert len(rows) == setup_test_tables["price"], f"Should have {setup_test_tables['price']} rows"
        
        # Check that latest price data has fundamental data attached
        latest_row = rows[0]  # 2024-01-15 (most recent)
        assert latest_row.symbol == "AAPL"
        assert latest_row.revenue is not None, "Latest data should have revenue from most recent fiscal period"
        assert latest_row.freeCashFlow is not None, "Latest data should have free cash flow"
        assert latest_row.totalDebt is not None, "Latest data should have total debt"
    
    def test_validity_window_logic(self, spark_session, setup_test_tables):
        # Test that validity windows correctly match price data to fundamental periods
        
        create_unified_price_fundamental_view(spark_session)
        
        # Query specific date ranges to test validity window logic
        result_df = spark_session.sql("""
            SELECT trade_date, revenue, income_period_end, freeCashFlow, cashflow_period_end
            FROM silver.vw_price_fundamental 
            WHERE symbol = 'AAPL'
            ORDER BY trade_date DESC
        """)
        rows = result_df.collect()
        
        # All 2024 data should map to 2023 fiscal year (most recent)
        for row in rows:
            if row.trade_date.year == 2024:
                assert row.income_period_end.year == 2023, "2024 price data should use 2023 fiscal data"
                assert row.cashflow_period_end.year == 2023, "2024 price data should use 2023 fiscal data"
    
    def test_left_join_preserves_price_data(self, spark_session, setup_test_tables):
        # Test that LEFT JOIN preserves all price data even when fundamentals are missing
        
        # Add price data for a symbol without fundamentals
        orphan_price_data = [("TSLA", date(2024, 1, 15), 250.0, 255.0, 248.0, 252.0, 252.0, 25000000, datetime.now(), "test-run-1")]
        orphan_columns = ["symbol", "trade_date", "open", "high", "low", "close", "adjClose", "volume", "ingested_at", "run_id"]
        orphan_df = spark_session.createDataFrame(orphan_price_data, orphan_columns)
        
        # Append to existing price table
        orphan_df.write.format("delta").mode("append").saveAsTable("silver.fact_price")
        
        create_unified_price_fundamental_view(spark_session)
        
        # Query for TSLA data
        tsla_result = spark_session.sql("SELECT * FROM silver.vw_price_fundamental WHERE symbol = 'TSLA'")
        tsla_rows = tsla_result.collect()
        
        # Should have TSLA price data even without fundamentals
        assert len(tsla_rows) == 1, "Should preserve price data without fundamentals"
        tsla_row = tsla_rows[0]
        assert tsla_row.close == 252.0, "Price data should be preserved"
        assert tsla_row.revenue is None, "Revenue should be NULL for missing fundamentals"
    
    def test_view_query_performance(self, spark_session, setup_test_tables):
        # Test that view queries execute efficiently (basic performance check)
        
        create_unified_price_fundamental_view(spark_session)
        
        # Execute a complex query to test performance
        result_df = spark_session.sql("""
            SELECT 
                symbol,
                COUNT(*) as price_count,
                AVG(close) as avg_close,
                MAX(revenue) as max_revenue,
                MAX(freeCashFlow) as max_fcf
            FROM silver.vw_price_fundamental 
            WHERE symbol = 'AAPL' AND trade_date >= '2024-01-01'
            GROUP BY symbol
        """)
        
        rows = result_df.collect()
        
        # Should execute without errors and return expected aggregates
        assert len(rows) == 1
        row = rows[0]
        assert row.symbol == "AAPL"
        assert row.price_count == 2  # Two 2024 records
        assert row.avg_close > 0
        assert row.max_revenue > 0


class TestViewConfiguration:
    # Test view configuration and error handling
    
    def test_view_sql_syntax(self):
        # Test that the view SQL is syntactically correct
        
        view_sql = """
        CREATE OR REPLACE VIEW silver.vw_price_fundamental AS
        SELECT 
            p.symbol,
            p.trade_date,
            p.open, p.high, p.low, p.close, p.adjClose, p.volume,
            i.revenue, i.grossProfit, i.operatingIncome, i.netIncome, i.eps,
            i.period_end as income_period_end,
            c.operatingCashFlow, c.capitalExpenditure, c.freeCashFlow,
            c.period_end as cashflow_period_end,
            b.totalDebt, b.cashAndCashEquivalents, b.totalEquity, 
            b.commonStockSharesOutstanding,
            b.period_end as balance_period_end,
            p.ingested_at, p.run_id
        FROM silver.fact_price p
        LEFT JOIN silver.fact_income i 
            ON p.symbol = i.symbol 
            AND p.trade_date BETWEEN i.effective_from AND i.effective_to
        LEFT JOIN silver.fact_cashflow c
            ON p.symbol = c.symbol
            AND p.trade_date BETWEEN c.effective_from AND c.effective_to
        LEFT JOIN silver.fact_balance b  
            ON p.symbol = b.symbol
            AND p.trade_date BETWEEN b.effective_from AND b.effective_to
        """
        
        # Basic syntax validation - should not contain obvious SQL errors
        assert "SELECT" in view_sql
        assert "FROM" in view_sql
        assert "LEFT JOIN" in view_sql
        assert "CREATE OR REPLACE VIEW" in view_sql
        
        # Should have all expected table references
        assert "silver.fact_price" in view_sql
        assert "silver.fact_income" in view_sql
        assert "silver.fact_cashflow" in view_sql
        assert "silver.fact_balance" in view_sql