#!/usr/bin/env python3
"""
FMP price data ingestion → S3 Parquet (Bronze layer).

Optimized for cost: API rate limiting runs locally (not on Databricks).
Writes day-partitioned Parquet files to S3 for downstream Auto Loader ingestion.

S3 Layout:
  s3://{S3_BUCKET}/raw/fmp/prices/dt=YYYY-MM-DD/prices-YYYY-MM-DD.parquet

Features:
- Async fetch with exponential backoff + jitter (tenacity)
- Polars for fast DataFrame operations
- Metadata enrichment: as_of_date, fetched_at, source, endpoint, request_id, hash
- Idempotent: skips existing day files unless --force
- S3 encryption (AES256) and proper content-type
- Emits metrics.json to s3://{S3_BUCKET}/logs/ingest/date={YYYY-MM-DD}/prices-run-{ts}.json
"""

import argparse
import asyncio
import hashlib
import json
import logging
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

import aiohttp
import boto3
import polars as pl
import pyarrow.parquet as pq
from botocore.exceptions import ClientError
from dotenv import load_dotenv
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    wait_random,
)

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("fmp_prices")


# ============================================================================
# Configuration & Environment
# ============================================================================

class Config:
    """Runtime configuration from environment variables."""

    FMP_API_KEY: str = os.getenv("FMP_API_KEY", "")
    S3_BUCKET: str = os.getenv("S3_BUCKET", "")
    S3_RAW_PREFIX: str = os.getenv("S3_RAW_PREFIX", "raw/fmp")
    AWS_REGION: str = os.getenv("AWS_DEFAULT_REGION", "us-east-1")

    # Rate limiting (can be small(0.1-0.2s) with paid tier)
    RATE_LIMIT_SECONDS: float = float(os.getenv("RATE_LIMIT_SECONDS", "0.2"))
    MAX_WORKERS: int = int(os.getenv("MAX_WORKERS", "10"))

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

def build_s3_key_daily(trade_date: str, prefix: str = "raw/fmp/prices") -> str:
    """
    Build S3 key for daily data with dt= partition (all symbols in one file).

    Args:
        trade_date: Date string YYYY-MM-DD
        prefix: S3 prefix (default: raw/fmp/prices)

    Returns:
        S3 key like: raw/fmp/prices/dt=2024-10-24/prices-2024-10-24.parquet
    """
    dt = datetime.strptime(trade_date, "%Y-%m-%d")
    key = f"{prefix}/dt={dt:%Y-%m-%d}/prices-{dt:%Y-%m-%d}.parquet"
    return key


def s3_file_exists(s3_client, bucket: str, key: str) -> bool:
    """Check if S3 file exists (race-safe)."""
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as e:
        if e.response.get("ResponseMetadata", {}).get("HTTPStatusCode") == 404:
            return False
        # Default false for other errors; allow write/retry
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
    """Async FMP API client with retry logic + jitter."""

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
        wait=wait_exponential(multiplier=1, min=1, max=60) + wait_random(0, 1),  # jitter
        stop=stop_after_attempt(5),
        before_sleep=before_sleep_log(log, logging.WARNING),
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
                log.error(f"FMP API error for {symbol}: {data['Error Message']}")
                return []
            else:
                log.warning(f"Unexpected FMP response for {symbol}: {data}")
                return []


# ============================================================================
# Data Processing with Polars
# ============================================================================

def prices_to_polars(
    symbol: str, prices: List[Dict], ingest_ts: datetime
) -> pl.DataFrame:
    """
    Convert FMP price list to validated Polars DataFrame with metadata enrichment.

    Adds:
    - as_of_date (DATE): parsed from 'date' field
    - fetched_at (TIMESTAMP): ingestion timestamp
    - source: 'FMP'
    - endpoint: 'historical-price-full'
    - request_id: uuid4
    - hash: sha256 of row content for de-dupe

    Args:
        symbol: Stock ticker
        prices: List of price dicts from FMP API
        ingest_ts: Ingestion timestamp for lineage

    Returns:
        Validated Polars DataFrame with metadata
    """
    if not prices:
        return pl.DataFrame()

    # Add metadata to each record
    for record in prices:
        record["symbol"] = symbol
        record["fetched_at"] = ingest_ts.isoformat()
        record["source"] = "FMP"
        record["endpoint"] = "historical-price-full"

    df = pl.DataFrame(prices)

    # Ensure required columns
    required_cols = ["symbol", "date", "open", "high", "low", "close", "volume"]
    if any(c not in df.columns for c in required_cols):
        log.warning(f"Missing columns for {symbol}")
        return pl.DataFrame()

    # Type casting and transformations
    df = (
        df
        .with_columns([
            # Parse date string to DATE type
            pl.col("date").str.strptime(pl.Date, "%Y-%m-%d", strict=False).alias("as_of_date"),
            # Parse fetched_at to TIMESTAMP
            pl.col("fetched_at").str.strptime(pl.Datetime, strict=False),
            # Cast price/volume columns
            pl.col("open").cast(pl.Float64),
            pl.col("high").cast(pl.Float64),
            pl.col("low").cast(pl.Float64),
            pl.col("close").cast(pl.Float64),
            pl.col("volume").cast(pl.Int64),
            # Generate request_id
            pl.lit(str(uuid.uuid4())).alias("request_id"),
        ])
        .filter(
            pl.col("as_of_date").is_not_null() &
            (pl.col("volume") >= 0)
        )
        # De-dupe any duplicate dates from API
        .unique(subset=["symbol", "as_of_date"], keep="last")
        .sort("as_of_date")
    )

    if df.is_empty():
        return df

    # Add content hash for file-level lineage (not row-level)
    payload_cols = ["symbol", "as_of_date", "open", "high", "low", "close", "volume"]
    content_csv = df.select(payload_cols).to_pandas().to_csv(index=False)
    content_hash = hashlib.sha256(content_csv.encode("utf-8")).hexdigest()
    df = df.with_columns(pl.lit(content_hash).alias("file_hash"))

    # Lock output schema (prevent drift if FMP adds fields)
    final_cols = [
        "symbol",           # string
        "as_of_date",       # date
        "open",             # float64
        "high",             # float64
        "low",              # float64
        "close",            # float64
        "volume",           # int64
        "fetched_at",       # timestamp
        "source",           # string
        "endpoint",         # string
        "request_id",       # string
        "file_hash",        # string
    ]

    return df.select(final_cols)


def group_by_day(dfs: List[pl.DataFrame]) -> Dict[str, pl.DataFrame]:
    """
    Group multiple DataFrames by trade date (combines all symbols per day).

    Args:
        dfs: List of Polars DataFrames from different symbols

    Returns:
        Dict mapping date string -> combined DataFrame for that day
    """
    if not dfs:
        return {}

    # Concatenate all DataFrames
    combined_df = pl.concat(dfs, how="vertical")

    if combined_df.is_empty():
        return {}

    grouped = {}
    for date_val in combined_df["as_of_date"].unique().sort():
        date_str = str(date_val)
        day_df = combined_df.filter(pl.col("as_of_date") == date_val)
        grouped[date_str] = day_df

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
    Write DataFrame to S3 as Parquet with encryption.

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

        # Upload with encryption and content-type
        s3_client.upload_file(
            tmp_path, bucket, s3_key,
            ExtraArgs={
                "ContentType": "application/octet-stream",
                "ServerSideEncryption": "AES256"
            }
        )

        log.info(f"✓ Wrote {s3_key}")
        return s3_key
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# ============================================================================
# Orchestration: Ingest Single Symbol
# ============================================================================

async def fetch_symbol_data(
    client: FMPClient,
    symbol: str,
    from_date: str,
    to_date: str,
    ingest_ts: datetime,
) -> tuple[Optional[pl.DataFrame], Dict]:
    """
    Fetch and validate data for one symbol.

    Returns:
        (DataFrame or None, result dict)
    """
    try:
        # Fetch price data
        prices = await client.fetch_prices(symbol, from_date, to_date)

        if not prices:
            return None, {
                "symbol": symbol,
                "rows_fetched": 0,
                "errors": ["No data returned from API"],
            }

        # Convert to Polars DataFrame with metadata
        df = prices_to_polars(symbol, prices, ingest_ts)

        if df.is_empty():
            return None, {
                "symbol": symbol,
                "rows_fetched": 0,
                "errors": ["No valid data after validation"],
            }

        return df, {
            "symbol": symbol,
            "rows_fetched": len(df),
            "errors": [],
        }

    except Exception as e:
        log.error(f"Error fetching {symbol}: {e}")
        return None, {
            "symbol": symbol,
            "rows_fetched": 0,
            "errors": [str(e)],
        }


# ============================================================================
# Main Orchestration
# ============================================================================

def load_tickers(tickers_path: str) -> List[str]:
    """
    Load tickers from file (local or S3).

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
        description="Ingest FMP price data to S3 (local async, no Spark)"
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

    log.info(f"📅 Date range: {from_date} to {to_date}")
    log.info(f"📂 S3 prefix: s3://{Config.S3_BUCKET}/{Config.S3_RAW_PREFIX}/prices/")

    # Load tickers
    tickers = load_tickers(args.tickers_path)
    log.info(f"📊 Loaded {len(tickers)} tickers from {args.tickers_path}")

    # Initialize clients
    s3_client = boto3.client("s3", region_name=Config.AWS_REGION)
    rate_limiter = RateLimiter(Config.RATE_LIMIT_SECONDS)
    ingest_ts = datetime.now(timezone.utc)

    start_time = time.time()

    # Fetch data for all tickers with bounded concurrency
    async with FMPClient(Config.FMP_API_KEY, rate_limiter) as fmp_client:
        semaphore = asyncio.Semaphore(Config.MAX_WORKERS)

        async def bounded_fetch(symbol: str):
            async with semaphore:
                return await fetch_symbol_data(
                    fmp_client, symbol, from_date, to_date, ingest_ts
                )

        fetch_results = await asyncio.gather(*[bounded_fetch(t) for t in tickers])

    # Separate DataFrames and results
    dfs = [df for df, _ in fetch_results if df is not None]
    results = [result for _, result in fetch_results]

    log.info(f"✓ Fetched data for {len(dfs)}/{len(tickers)} symbols")

    # Group all symbols by day and write one file per day
    if dfs:
        day_groups = group_by_day(dfs)
        files_written = []

        for trade_date, day_df in day_groups.items():
            s3_key = build_s3_key_daily(trade_date, prefix=Config.S3_RAW_PREFIX + "/prices")
            result_key = write_parquet_to_s3(day_df, s3_key, s3_client, Config.S3_BUCKET, args.force)
            if result_key:
                files_written.append(result_key)

        log.info(f"✓ Wrote {len(files_written)} daily files")
    else:
        files_written = []
        log.warning("No data to write")

    # Calculate metrics
    elapsed_time = time.time() - start_time
    total_rows = sum(r["rows_fetched"] for r in results)
    total_errors = sum(1 for r in results if r["errors"])

    # Build metrics payload
    metrics = {
        "run_id": ingest_ts.isoformat(),
        "data_type": "prices",
        "endpoint": "historical-price-full",
        "date_range": {"from": from_date, "to": to_date},
        "symbols_processed": len(tickers),
        "files_written": len(files_written),
        "rows_written": total_rows,
        "errors": total_errors,
        "duration_seconds": round(elapsed_time, 2),
        "s3_prefix": f"s3://{Config.S3_BUCKET}/{Config.S3_RAW_PREFIX}/prices/",
        "symbol_results": results,
    }

    # Write metrics to S3
    metrics_date = datetime.now().strftime("%Y-%m-%d")
    metrics_ts = int(time.time())
    metrics_key = f"logs/ingest/date={metrics_date}/prices-run-{metrics_ts}.json"

    s3_client.put_object(
        Bucket=Config.S3_BUCKET,
        Key=metrics_key,
        Body=json.dumps(metrics, indent=2),
        ContentType="application/json",
    )

    # Print summary
    print("\n" + "="*60)
    print(f"✅ Price Ingestion Complete")
    print("="*60)
    print(f"📊 Symbols: {len(tickers)}")
    print(f"📁 Files written: {len(files_written)} (1 per day, all symbols combined)")
    print(f"📝 Rows written: {total_rows:,}")
    print(f"❌ Errors: {total_errors}")
    print(f"⏱️  Duration: {elapsed_time:.1f}s")
    print(f"📂 S3 Prefix: s3://{Config.S3_BUCKET}/{Config.S3_RAW_PREFIX}/prices/")
    print(f"📋 Metrics: s3://{Config.S3_BUCKET}/{metrics_key}")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(main())
