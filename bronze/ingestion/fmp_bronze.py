#!/usr/bin/env python3

import argparse
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, List

# Import shared utilities
from ingestion.utils import AsyncFMPClient, FMPConfig
from bronze.utils import create_spark_session, write_bronze_data
from bronze.ingestion.schemas import get_bronze_schemas


async def ingest_ticker_bronze(client: AsyncFMPClient, spark, symbol: str, 
                              from_date: str, to_date: str, schemas: Dict) -> Dict:
    # Ingest all data types for one ticker and write to Bronze S3 buckets
    # Returns summary stats for logging and monitoring
    
    print(f"🔄 Processing {symbol} for Bronze layer...")
    
    # Fetch all four data types concurrently to minimize total API call time
    data = await client.fetch_all_data(symbol, from_date, to_date)
    
    # Prepare metadata that gets added to every record for data lineage
    ingest_date = datetime.now(timezone.utc).date()
    run_metadata = {
        "symbol": symbol,
        "ingested_at": client.ingested_at,
        "run_id": client.run_id,
        "ingest_date": ingest_date
    }
    
    # Write each data type to its Bronze bucket with proper schema validation
    paths_written = []
    record_counts = {}
    
    for table_type in ["price", "income", "cashflow", "balance"]:
        table_data = data.get(table_type, [])
        if table_data:
            # Add symbol to each record since it's not always in the API response
            for record in table_data:
                record["symbol"] = symbol
            
            path = write_bronze_data(spark, table_data, schemas[table_type], 
                                   table_type, symbol, run_metadata)
            if path:
                paths_written.append(path)
            record_counts[table_type] = len(table_data)
        else:
            record_counts[table_type] = 0
    
    return {
        "symbol": symbol,
        "record_counts": record_counts,
        "paths_written": paths_written
    }


async def main():
    # Bronze layer ingestion pipeline
    # Fetches raw data from FMP API and writes to Bronze S3 buckets
    # with proper partitioning and metadata for downstream processing
    
    parser = argparse.ArgumentParser(description="FMP Bronze Layer Ingestion")
    parser.add_argument("--tickers", required=True, help="Comma-separated ticker symbols")
    parser.add_argument("--backfill", action="store_true", help="Fetch 5-year history")
    
    args = parser.parse_args()
    
    # Parse ticker list and normalize to uppercase
    tickers = [t.strip().upper() for t in args.tickers.split(",")]
    print(f"🎯 Starting Bronze ingestion for {len(tickers)} tickers: {', '.join(tickers)}")
    
    # Calculate date range based on mode
    if args.backfill:
        # Backfill mode: get 5 years of history
        to_date = datetime.now().strftime("%Y-%m-%d")
        from_date = (datetime.now() - timedelta(days=5*365)).strftime("%Y-%m-%d")
        print(f"📅 Backfill mode: {from_date} to {to_date}")
    else:
        # Daily mode: just get yesterday's data (today's data might not be complete)
        yesterday = datetime.now() - timedelta(days=1)
        from_date = to_date = yesterday.strftime("%Y-%m-%d")
        print(f"📅 Daily mode: {from_date}")
    
    # Initialize components
    config = FMPConfig(api_key=os.getenv("FMP_API_KEY"))
    client = AsyncFMPClient(config)
    spark = create_spark_session()
    schemas = get_bronze_schemas()
    
    # Process all tickers concurrently - rate limiting handles the API limits automatically
    tasks = [ingest_ticker_bronze(client, spark, ticker, from_date, to_date, schemas) 
             for ticker in tickers]
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Generate summary report for monitoring and debugging
    summary = {
        "layer": "bronze",
        "run_id": client.run_id,
        "ingested_at": client.ingested_at.isoformat(),
        "date_range": {"from": from_date, "to": to_date},
        "results": [r for r in results if not isinstance(r, Exception)],
        "errors": [str(r) for r in results if isinstance(r, Exception)]
    }
    
    # Write summary to logs directory for future reference
    os.makedirs("logs", exist_ok=True)
    with open(f"logs/bronze_ingestion_{client.run_id}.json", "w") as f:
        json.dump(summary, f, indent=2, default=str)
    
    print(f"\n✅ Bronze ingestion complete! Summary: logs/bronze_ingestion_{client.run_id}.json")
    print("🔄 Next step: Run Silver transformations to clean and structure this data")
    
    # Clean up Spark resources
    spark.stop()


if __name__ == "__main__":
    asyncio.run(main())