#!/usr/bin/env python3
"""
Local async ingestion script for FMP stock data → S3 Parquet.

Optimized for cost: API rate limiting runs locally (not on Databricks).
Writes day-partitioned Parquet files to S3 for downstream Auto Loader ingestion.

S3 Layout:
  s3://{S3_BUCKET}/raw/prices/symbol={SYM}/year={YYYY}/month={MM}/day={DD}/{SYM}-{YYYY}-{MM}-{DD}.parquet

Features:
- Async fetch with exponential backoff (tenacity)
- Polars for fast DataFrame operations
- Idempotent: skips existing day files unless --force
- Emits metrics.json to s3://{S3_BUCKET}/logs/ingest/date={YYYY-MM-DD}/run-{ts}.json
"""

import argparse
import asyncio
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

import aiohttp
import boto3
import polars as pl
import pyarrow as pa
import pyarrow.parquet as pq
from dotenv import load_dotenv
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

# Load environment variables
load_dotenv()


# ============================================================================
# Configuration & Environment
# ============================================================================

class Config:
    """Runtime configuration from environment variables."""

    FMP_API_KEY: str = os.getenv("FMP_API_KEY", "")
    S3_BUCKET: str = os.getenv("S3_BUCKET", "")
    S3_RAW_PREFIX: str = os.getenv("S3_RAW_PREFIX", "raw")
    AWS_REGION: str = os.getenv("AWS_DEFAULT_REGION", "us-east-1")

    # Rate limiting (12-15s between batches for free tier)
    RATE_LIMIT_SECONDS: float = float(os.getenv("RATE_LIMIT_SECONDS"))
    MAX_WORKERS: int = int(os.getenv("MAX_WORKERS"))

    FMP_BASE_URL: str = "https://financialmodelingprep.com/api/v3"

    @classmethod
    def validate(cls):
        """Validate required environment variables."""
        if not cls.FMP_API_KEY:
            raise ValueError("FMP_API_KEY environment variable required")
        if not cls.S3_BUCKET:
            raise ValueError("S3_BUCKET environment variable required")


# ============================================================================
# S3 Path Utilities
# ============================================================================

def build_s3_key_daily(symbol: str, trade_date: str, prefix: str = "raw/prices") -> str:
    """
    Build S3 key for daily incremental data.

    Args:
        symbol: Stock ticker (e.g., AAPL)
        trade_date: Date string YYYY-MM-DD
        prefix: S3 prefix (default: raw/prices)

    Returns:
        S3 key like: raw/prices/symbol=AAPL/year=2024/month=09/AAPL-2024-09-15.parquet
    """
    dt = datetime.strptime(trade_date, "%Y-%m-%d")
    year, month, day = dt.year, dt.month, dt.day

    key = (
        f"{prefix}/"
        f"symbol={symbol}/"
        f"year={year:04d}/"
        f"month={month:02d}/"
        f"{symbol}-{year:04d}-{month:02d}-{day:02d}.parquet"
    )
    return key


def build_s3_key_yearly(symbol: str, year: int, prefix: str = "raw/prices") -> str:
    """
    Build S3 key for yearly backfill data.

    Args:
        symbol: Stock ticker (e.g., AAPL)
        year: Year (e.g., 2024)
        prefix: S3 prefix (default: raw/prices)

    Returns:
        S3 key like: raw/prices/symbol=AAPL/year=2024/AAPL-2024.parquet
    """
    key = (
        f"{prefix}/"
        f"symbol={symbol}/"
        f"year={year:04d}/"
        f"{symbol}-{year:04d}.parquet"
    )
    return key


def s3_file_exists(s3_client, bucket: str, key: str) -> bool:
    """Check if S3 file exists."""
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except s3_client.exceptions.ClientError:
        return False


# ============================================================================
# FMP API Client with Retry Logic
# ============================================================================

class RateLimiter:
    """Token-bucket rate limiter for async API calls."""

    def __init__(self, rate_limit_seconds: float):
        self.rate_limit_seconds = rate_limit_seconds
        self.last_request_time = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self):
        """Wait before allowing next request."""
        async with self._lock:
            now = time.time()
            elapsed = now - self.last_request_time
            if elapsed < self.rate_limit_seconds:
                wait_time = self.rate_limit_seconds - elapsed
                await asyncio.sleep(wait_time)
            self.last_request_time = time.time()


class FMPClient:
    """Async FMP API client with retry logic."""

    def __init__(self, api_key: str, rate_limiter: RateLimiter):
        self.api_key = api_key
        self.base_url = Config.FMP_BASE_URL
        self.rate_limiter = rate_limiter
        self.session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    @retry(
        retry=retry_if_exception_type((aiohttp.ClientError, asyncio.TimeoutError)),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(3),
    )
    async def fetch_prices(
        self, symbol: str, from_date: str, to_date: str
    ) -> List[Dict]:
        """
        Fetch historical price data for a symbol.

        Args:
            symbol: Stock ticker
            from_date: Start date YYYY-MM-DD
            to_date: End date YYYY-MM-DD

        Returns:
            List of daily price records
        """
        await self.rate_limiter.acquire()

        url = f"{self.base_url}/historical-price-full/{symbol}"
        params = {
            "apikey": self.api_key,
            "from": from_date,
            "to": to_date,
        }

        if not self.session:
            raise RuntimeError("Session not initialized. Use 'async with' context.")

        async with self.session.get(url, params=params, timeout=30) as response:
            response.raise_for_status()
            data = await response.json()

            # FMP returns {"historical": [...]} or error dict
            if isinstance(data, dict) and "historical" in data:
                return data["historical"]
            elif isinstance(data, dict) and "Error Message" in data:
                print(f"❌ FMP API error for {symbol}: {data['Error Message']}")
                return []
            else:
                print(f"⚠️  Unexpected FMP response for {symbol}: {data}")
                return []


# ============================================================================
# Data Processing with Polars
# ============================================================================

def prices_to_polars(
    symbol: str, prices: List[Dict], ingest_ts: datetime
) -> pl.DataFrame:
    """
    Convert FMP price list to validated Polars DataFrame.

    Validations:
    - Non-null symbol, date
    - Non-negative volume
    - Monotonic date ordering

    Args:
        symbol: Stock ticker
        prices: List of price dicts from FMP API
        ingest_ts: Ingestion timestamp for lineage

    Returns:
        Validated Polars DataFrame
    """
    if not prices:
        return pl.DataFrame()

    # Add symbol and ingest_ts to each record
    for record in prices:
        record["symbol"] = symbol
        record["ingest_ts"] = ingest_ts

    df = pl.DataFrame(prices)

    # Validations
    if df.is_empty():
        return df

    # Ensure required columns
    required_cols = ["symbol", "date", "open", "high", "low", "close", "volume"]
    missing_cols = set(required_cols) - set(df.columns)
    if missing_cols:
        print(f"⚠️  Missing columns for {symbol}: {missing_cols}")
        return pl.DataFrame()

    # Filter out invalid rows
    df = df.filter(
        (pl.col("symbol").is_not_null()) &
        (pl.col("date").is_not_null()) &
        (pl.col("volume") >= 0)
    )

    # Sort by date descending (FMP returns newest first)
    df = df.sort("date", descending=True)

    return df


def group_by_day(df: pl.DataFrame) -> Dict[str, pl.DataFrame]:
    """
    Group DataFrame by trade date.

    Args:
        df: Polars DataFrame with 'date' column

    Returns:
        Dict mapping date string -> DataFrame for that day
    """
    if df.is_empty():
        return {}

    grouped = {}
    for date_str in df["date"].unique().sort(descending=True):
        day_df = df.filter(pl.col("date") == date_str)
        grouped[str(date_str)] = day_df

    return grouped


def group_by_year(df: pl.DataFrame) -> Dict[int, pl.DataFrame]:
    """
    Group DataFrame by year for backfill mode.

    Args:
        df: Polars DataFrame with 'date' column

    Returns:
        Dict mapping year (int) -> DataFrame for that year
    """
    if df.is_empty():
        return {}

    # Extract year from date column
    df = df.with_columns(
        pl.col("date").str.slice(0, 4).cast(pl.Int32).alias("year")
    )

    grouped = {}
    for year in df["year"].unique().sort(descending=True):
        year_df = df.filter(pl.col("year") == year).drop("year")
        grouped[int(year)] = year_df

    return grouped


# ============================================================================
# S3 Write Operations
# ============================================================================

def write_parquet_to_s3(
    df: pl.DataFrame,
    s3_key: str,
    s3_client,
    bucket: str,
    force: bool = False,
) -> Optional[str]:
    """
    Write DataFrame to S3 as Parquet.

    Args:
        df: Polars DataFrame
        s3_key: Full S3 key path
        s3_client: boto3 S3 client
        bucket: S3 bucket name
        force: If True, overwrite existing files

    Returns:
        S3 key if written, None if skipped
    """
    # Idempotency: skip if exists unless --force
    if not force and s3_file_exists(s3_client, bucket, s3_key):
        return None

    # Convert Polars → PyArrow → Parquet bytes
    arrow_table = df.to_arrow()

    # Write to local temp file, then upload
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        pq.write_table(arrow_table, tmp_path, compression="snappy")
        s3_client.upload_file(tmp_path, bucket, s3_key)
        return s3_key
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# ============================================================================
# Orchestration: Ingest Single Symbol
# ============================================================================

async def ingest_symbol(
    client: FMPClient,
    symbol: str,
    from_date: str,
    to_date: str,
    s3_client,
    bucket: str,
    force: bool,
    ingest_ts: datetime,
    backfill_mode: bool = False,
) -> Dict:
    """
    Ingest one symbol: fetch → validate → write to S3.

    In backfill mode: writes one file per year
    In daily mode: writes one file per day

    Returns:
        Dict with symbol, files_written, rows_written, errors
    """
    try:
        # Fetch price data
        prices = await client.fetch_prices(symbol, from_date, to_date)

        if not prices:
            return {
                "symbol": symbol,
                "files_written": 0,
                "rows_written": 0,
                "errors": ["No data returned from API"],
            }

        # Convert to Polars DataFrame
        df = prices_to_polars(symbol, prices, ingest_ts)

        if df.is_empty():
            return {
                "symbol": symbol,
                "files_written": 0,
                "rows_written": 0,
                "errors": ["No valid data after validation"],
            }

        files_written = []
        total_rows = 0

        if backfill_mode:
            # Backfill: write one file per year
            year_groups = group_by_year(df)
            for year, year_df in year_groups.items():
                s3_key = build_s3_key_yearly(symbol, year, prefix=Config.S3_RAW_PREFIX + "/prices")
                result_key = write_parquet_to_s3(year_df, s3_key, s3_client, bucket, force)
                if result_key:
                    files_written.append(result_key)
                    total_rows += len(year_df)
        else:
            # Daily: write one file per day
            day_groups = group_by_day(df)
            for trade_date, day_df in day_groups.items():
                s3_key = build_s3_key_daily(symbol, trade_date, prefix=Config.S3_RAW_PREFIX + "/prices")
                result_key = write_parquet_to_s3(day_df, s3_key, s3_client, bucket, force)
                if result_key:
                    files_written.append(result_key)
                    total_rows += len(day_df)

        return {
            "symbol": symbol,
            "files_written": len(files_written),
            "rows_written": total_rows,
            "errors": [],
        }

    except Exception as e:
        return {
            "symbol": symbol,
            "files_written": 0,
            "rows_written": 0,
            "errors": [str(e)],
        }


# ============================================================================
# Main Orchestration
# ============================================================================

def load_tickers(tickers_path: str) -> List[str]:
    """
    Load tickers from file (local or S3).

    Supports:
    - Local CSV: stock_pipeline/config/tickers.csv
    - S3 path: s3://bucket/path/to/tickers.csv

    Returns:
        List of ticker symbols (uppercase)
    """
    if tickers_path.startswith("s3://"):
        # Parse S3 path
        parts = tickers_path.replace("s3://", "").split("/", 1)
        bucket = parts[0]
        key = parts[1] if len(parts) > 1 else ""

        s3_client = boto3.client("s3", region_name=Config.AWS_REGION)
        obj = s3_client.get_object(Bucket=bucket, Key=key)
        content = obj["Body"].read().decode("utf-8")

        # Parse CSV (assume one ticker per line or comma-separated)
        tickers = [line.strip().upper() for line in content.splitlines() if line.strip()]
    else:
        # Local file
        with open(tickers_path, "r") as f:
            content = f.read()
        tickers = [line.strip().upper() for line in content.splitlines() if line.strip()]

    return tickers


async def main():
    """Main ingestion pipeline."""
    parser = argparse.ArgumentParser(
        description="Ingest FMP stock data to S3 (local async, no Spark)"
    )
    parser.add_argument(
        "--tickers-path",
        default="stock_pipeline/config/tickers.csv",
        help="Path to tickers file (local or s3://...)",
    )
    parser.add_argument(
        "--from-date",
        help="Start date YYYY-MM-DD (default: yesterday)",
    )
    parser.add_argument(
        "--to-date",
        help="End date YYYY-MM-DD (default: yesterday)",
    )
    parser.add_argument(
        "--backfill-days",
        type=int,
        help="Backfill N days from today (overrides --from-date)",
    )
    parser.add_argument(
        "--backfill",
        action="store_true",
        help="Backfill mode: write yearly Parquet files (not daily)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing S3 files",
    )

    args = parser.parse_args()

    # Validate config
    Config.validate()

    # Calculate date range
    if args.backfill_days:
        to_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        from_date = (datetime.now() - timedelta(days=args.backfill_days)).strftime("%Y-%m-%d")
    elif args.from_date and args.to_date:
        from_date = args.from_date
        to_date = args.to_date
    else:
        # Default: yesterday only
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        from_date = to_date = yesterday

    print(f"📅 Date range: {from_date} to {to_date}")

    # Load tickers
    tickers = load_tickers(args.tickers_path)
    print(f"📊 Loaded {len(tickers)} tickers from {args.tickers_path}")

    # Initialize clients
    s3_client = boto3.client("s3", region_name=Config.AWS_REGION)
    rate_limiter = RateLimiter(Config.RATE_LIMIT_SECONDS)
    ingest_ts = datetime.now(timezone.utc)

    start_time = time.time()

    # Process tickers with bounded concurrency
    async with FMPClient(Config.FMP_API_KEY, rate_limiter) as fmp_client:
        semaphore = asyncio.Semaphore(Config.MAX_WORKERS)

        async def bounded_ingest(symbol: str):
            async with semaphore:
                return await ingest_symbol(
                    fmp_client, symbol, from_date, to_date,
                    s3_client, Config.S3_BUCKET, args.force, ingest_ts,
                    backfill_mode=args.backfill
                )

        results = await asyncio.gather(*[bounded_ingest(t) for t in tickers])

    # Calculate metrics
    elapsed_time = time.time() - start_time
    total_files = sum(r["files_written"] for r in results)
    total_rows = sum(r["rows_written"] for r in results)
    total_errors = sum(1 for r in results if r["errors"])

    # Build metrics payload
    metrics = {
        "run_id": ingest_ts.isoformat(),
        "date_range": {"from": from_date, "to": to_date},
        "symbols_processed": len(tickers),
        "files_written": total_files,
        "rows_written": total_rows,
        "errors": total_errors,
        "duration_seconds": round(elapsed_time, 2),
        "results": results,
    }

    # Write metrics to S3
    metrics_date = datetime.now().strftime("%Y-%m-%d")
    metrics_ts = int(time.time())
    metrics_key = f"logs/ingest/date={metrics_date}/run-{metrics_ts}.json"

    s3_client.put_object(
        Bucket=Config.S3_BUCKET,
        Key=metrics_key,
        Body=json.dumps(metrics, indent=2),
        ContentType="application/json",
    )

    # Print summary
    mode = "backfill (yearly)" if args.backfill else "daily"
    print("\n" + "="*60)
    print(f"✅ Ingestion Complete ({mode})")
    print("="*60)
    print(f"📊 Symbols: {len(tickers)}")
    print(f"📁 Files written: {total_files}")
    print(f"📝 Rows written: {total_rows:,}")
    print(f"❌ Errors: {total_errors}")
    print(f"⏱️  Duration: {elapsed_time:.1f}s")
    print(f"📋 Metrics: s3://{Config.S3_BUCKET}/{metrics_key}")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(main())
