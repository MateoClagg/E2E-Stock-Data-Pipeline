from pyspark.sql import SparkSession
from silver.transformations.validity_windows import create_spark_session


def create_unified_price_fundamental_view(spark: SparkSession) -> None:
    # Create unified view that LEFT JOINs price data with all fundamental tables
    # This gives us a complete picture - daily prices enriched with the most
    # recent fundamental data that was available at that point in time
    # Uses LEFT JOINs so we always get price data even if fundamentals are missing
    
    view_sql = """
    CREATE OR REPLACE VIEW silver.vw_price_fundamental AS
    SELECT 
        p.symbol,
        p.trade_date,
        p.open, p.high, p.low, p.close, p.adjClose, p.volume,
        
        -- Income statement metrics (revenue, profitability)
        i.revenue, i.grossProfit, i.operatingIncome, i.netIncome, i.eps,
        i.period_end as income_period_end,
        
        -- Cash flow metrics (operating cash, capex, free cash flow)
        c.operatingCashFlow, c.capitalExpenditure, c.freeCashFlow,
        c.period_end as cashflow_period_end,
        
        -- Balance sheet metrics (debt, cash, equity, shares outstanding)
        b.totalDebt, b.cashAndCashEquivalents, b.totalEquity, 
        b.commonStockSharesOutstanding,
        b.period_end as balance_period_end,
        
        p.ingested_at, p.run_id
        
    FROM silver.fact_price p
    
    -- LEFT JOIN ensures we get all price data even if fundamentals are missing
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
    
    spark.sql(view_sql)
    print("✅ Created silver.vw_price_fundamental unified view")


def create_all_views(spark: SparkSession) -> None:
    # Create all Silver layer views for analytics
    
    print("🔄 Creating Silver views...")
    
    # Main unified view combining all data types
    create_unified_price_fundamental_view(spark)
    
    print("✅ All Silver views created successfully!")


def main():
    # Main Silver views pipeline
    # Creates analytical views on top of Silver tables
    
    print("🎯 Starting Silver views creation...")
    
    spark = create_spark_session()
    
    try:
        create_all_views(spark)
        print("\n✅ Silver layer complete! Data ready for analysis and Gold layer.")
        
    finally:
        # Clean up Spark resources
        spark.stop()


if __name__ == "__main__":
    main()