from typing import Dict
from pyspark.sql.types import (
    StructType, StructField, StringType, DoubleType, 
    LongType, TimestampType
)


def get_bronze_schemas() -> Dict[str, StructType]:
    # Price data schema - daily OHLCV with volume
    price_schema = StructType([
        StructField("symbol", StringType(), False),
        StructField("date", StringType(), False),  # Will convert to DateType in Silver
        StructField("open", DoubleType(), True),
        StructField("high", DoubleType(), True),
        StructField("low", DoubleType(), True),
        StructField("close", DoubleType(), True),
        StructField("adjClose", DoubleType(), True),
        StructField("volume", LongType(), True),
        # Metadata columns for lineage tracking
        StructField("ingested_at", TimestampType(), False),
        StructField("run_id", StringType(), False),
    ])
    
    # Income statement has the core P&L metrics we care about
    income_schema = StructType([
        StructField("symbol", StringType(), False),
        StructField("date", StringType(), False),  # Fiscal period end date
        StructField("revenue", LongType(), True),
        StructField("grossProfit", LongType(), True),
        StructField("operatingIncome", LongType(), True),
        StructField("netIncome", LongType(), True),
        StructField("eps", DoubleType(), True),
        StructField("report_type", StringType(), False),  # Always "ANNUAL"
        StructField("ingested_at", TimestampType(), False),
        StructField("run_id", StringType(), False),
    ])
    
    # Cash flow focuses on FCF and operating cash flow
    cashflow_schema = StructType([
        StructField("symbol", StringType(), False),
        StructField("date", StringType(), False),
        StructField("operatingCashFlow", LongType(), True),
        StructField("capitalExpenditure", LongType(), True),
        StructField("freeCashFlow", LongType(), True),
        StructField("report_type", StringType(), False),
        StructField("ingested_at", TimestampType(), False),
        StructField("run_id", StringType(), False),
    ])
    
    # Balance sheet has debt, cash, equity for financial health analysis
    balance_schema = StructType([
        StructField("symbol", StringType(), False),
        StructField("date", StringType(), False),
        StructField("totalDebt", LongType(), True),
        StructField("cashAndCashEquivalents", LongType(), True),
        StructField("totalEquity", LongType(), True),
        StructField("commonStockSharesOutstanding", LongType(), True),
        StructField("report_type", StringType(), False),
        StructField("ingested_at", TimestampType(), False),
        StructField("run_id", StringType(), False),
    ])
    
    return {
        "price": price_schema,
        "income": income_schema,
        "cashflow": cashflow_schema,
        "balance": balance_schema
    }