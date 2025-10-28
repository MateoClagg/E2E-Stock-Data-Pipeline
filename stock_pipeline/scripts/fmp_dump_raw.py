#!/usr/bin/env python3
"""
FMP raw data dumper for Bronze ingestion (S3 → Auto Loader → Delta).

Fetches raw API responses and writes NDJSON snapshots to S3 with metadata.
Designed for idempotent daily runs with date partitioning.

Usage:
  # Daily ingestion (default)
  python fmp_dump_raw.py --date 2024-10-24 --endpoints owner_earnings,income,treasury_rates
  python fmp_dump_raw.py --date today --endpoints all --force

  # Treasury rates backfill (5 years)
  python fmp_dump_raw.py --endpoints treasury_rates --backfill-days 1825 --force
  python fmp_dump_raw.py --endpoints treasury_rates --from-date 2019-10-25 --to-date 2024-10-25

S3 Layout:
  Treasury: raw/fmp/treasury_rates/dt=YYYY-MM-DD/treasury-rates-YYYY-MM-DD.ndjson.gz
  Statements: raw/fmp/statements/{type}/symbol={SYM}/{SYM}-{type}.ndjson.gz (overwrites daily)
"""

import argparse
import asyncio
import gzip
import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional

import aiohttp
import boto3
from dotenv import load_dotenv
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

# Import trading day utilities
from stock_pipeline.scripts.utils.dates import (
    get_previous_trading_day,
    get_trading_days,
    is_trading_day,
)

load_dotenv()


# ============================================================================
# Configuration
# ============================================================================

class Config:
    """Runtime configuration from environment variables."""

    FMP_API_KEY: str = os.getenv("FMP_API_KEY", "")
    S3_BUCKET: str = os.getenv("S3_BUCKET", "")
    S3_RAW_PREFIX: str = os.getenv("S3_RAW_PREFIX", "raw")
    AWS_REGION: str = os.getenv("AWS_DEFAULT_REGION", "us-east-1")

    RATE_LIMIT_SECONDS: float = float(os.getenv("RATE_LIMIT_SECONDS", "0.2"))
    MAX_WORKERS: int = int(os.getenv("MAX_WORKERS", "10"))

    @classmethod
    def validate(cls):
        if not cls.FMP_API_KEY:
            raise ValueError("FMP_API_KEY required")
        if not cls.S3_BUCKET:
            raise ValueError("S3_BUCKET required")


# ============================================================================
# Endpoint Registry
# ============================================================================

ENDPOINTS = {
    "owner_earnings": {
        "url_template": "https://financialmodelingprep.com/stable/owner-earnings",
        "params": {"symbol": "{symbol}", "limit": 5},
        "per_symbol": True,
        "s3_path": "raw/fmp/owner_earnings/symbol={symbol}/{symbol}-owner-earnings.ndjson.gz",
    },
    "income": {
        "url_template": "https://financialmodelingprep.com/api/v3/income-statement/{symbol}",
        "params": {"period": "annual", "limit": 5},
        "per_symbol": True,
        "s3_path": "raw/fmp/statements/income/symbol={symbol}/{symbol}-income.ndjson.gz",
    },
    "balance_sheet": {
        "url_template": "https://financialmodelingprep.com/api/v3/balance-sheet-statement/{symbol}",
        "params": {"period": "annual", "limit": 5},
        "per_symbol": True,
        "s3_path": "raw/fmp/statements/balance_sheet/symbol={symbol}/{symbol}-balance.ndjson.gz",
    },
    "cash_flow": {
        "url_template": "https://financialmodelingprep.com/api/v3/cash-flow-statement/{symbol}",
        "params": {"period": "annual", "limit": 5},
        "per_symbol": True,
        "s3_path": "raw/fmp/statements/cash_flow/symbol={symbol}/{symbol}-cashflow.ndjson.gz",
    },
    "treasury_rates": {
        "url_template": "https://financialmodelingprep.com/stable/treasury-rates",
        "params": {},
        "per_symbol": False,
        "supports_backfill": True,  # Supports from/to date parameters
        "s3_path": "raw/fmp/treasury_rates/dt={date}/treasury-rates-{date}.ndjson.gz",
    },
}


# ============================================================================
# Rate Limiter
# ============================================================================

class RateLimiter:
    """Token-bucket rate limiter."""

    def __init__(self, rate_limit_seconds: float):
        self.rate_limit_seconds = rate_limit_seconds
        self.last_request_time = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self):
        async with self._lock:
            import time
            now = time.time()
            elapsed = now - self.last_request_time
            if elapsed < self.rate_limit_seconds:
                await asyncio.sleep(self.rate_limit_seconds - elapsed)
            self.last_request_time = time.time()


# ============================================================================
# FMP Client
# ============================================================================

class FMPClient:
    """Async FMP API client with retry logic."""

    def __init__(self, api_key: str, rate_limiter: RateLimiter):
        self.api_key = api_key
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
    async def fetch(
        self, endpoint: str, url: str, params: Dict
    ) -> tuple[List[Dict], int]:
        """
        Fetch from FMP API.

        Returns:
            (data_list, http_status)
        """
        await self.rate_limiter.acquire()

        params["apikey"] = self.api_key

        if not self.session:
            raise RuntimeError("Session not initialized")

        async with self.session.get(url, params=params, timeout=30) as response:
            status = response.status
            data = await response.json()

            if isinstance(data, list):
                return data, status
            elif isinstance(data, dict) and "Error Message" in data:
                print(f"❌ API error for {endpoint}: {data['Error Message']}")
                return [], status
            else:
                print(f"⚠️  Unexpected response for {endpoint}")
                return [], status


# ============================================================================
# Record Builder
# ============================================================================

def build_record(
    endpoint: str,
    symbol: Optional[str],
    as_of_date: str,
    payload_obj: Dict,
    fetched_at: datetime,
    http_status: int,
    request_id: str,
) -> Dict:
    """
    Build a Bronze NDJSON record with metadata.

    Schema:
      - symbol: nullable string
      - as_of_date: DATE (snapshot date)
      - endpoint: string
      - payload: string (JSON)
      - fetched_at: timestamp
      - source: string
      - http_status: int
      - request_id: string
      - fiscal_period_end: DATE (if in payload)
      - filing_date: DATE (if in payload)
      - hash: string (sha256 of payload)
    """
    payload_json = json.dumps(payload_obj, sort_keys=True)
    payload_hash = hashlib.sha256(payload_json.encode()).hexdigest()

    # Extract fiscal metadata if present
    fiscal_period_end = payload_obj.get("date") or payload_obj.get("fiscalDateEnding")
    filing_date = payload_obj.get("fillingDate") or payload_obj.get("filingDate")

    record = {
        "symbol": symbol,
        "as_of_date": as_of_date,
        "endpoint": endpoint,
        "payload": payload_json,
        "fetched_at": fetched_at.isoformat(),
        "source": "FMP",
        "http_status": http_status,
        "request_id": request_id,
        "fiscal_period_end": fiscal_period_end,
        "filing_date": filing_date,
        "hash": payload_hash,
    }

    return record


# ============================================================================
# S3 Operations
# ============================================================================

def s3_key_exists(s3_client, bucket: str, key: str) -> bool:
    """Check if S3 object exists."""
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except s3_client.exceptions.ClientError:
        return False


def write_ndjson_to_s3(
    records: List[Dict],
    s3_key: str,
    s3_client,
    bucket: str,
    force: bool = False,
) -> bool:
    """
    Write NDJSON records to S3 with gzip compression.

    Returns:
        True if written, False if skipped
    """
    if not force and s3_key_exists(s3_client, bucket, s3_key):
        return False

    # Build NDJSON content
    ndjson_lines = [json.dumps(r) for r in records]
    ndjson_content = "\n".join(ndjson_lines)

    # Gzip compress
    compressed = gzip.compress(ndjson_content.encode("utf-8"))

    # Upload to S3
    s3_client.put_object(
        Bucket=bucket,
        Key=s3_key,
        Body=compressed,
        ContentType="application/x-ndjson",
        ContentEncoding="gzip",
    )

    return True


# ============================================================================
# Ingestion Logic
# ============================================================================

async def ingest_endpoint_symbol(
    client: FMPClient,
    endpoint: str,
    endpoint_config: Dict,
    symbol: str,
    as_of_date: str,
    s3_client,
    bucket: str,
    force: bool,
) -> Dict:
    """
    Ingest one endpoint for one symbol.

    Returns:
        Dict with symbol, endpoint, files_written, records_written, errors
    """
    try:
        # Build URL and params
        url = endpoint_config["url_template"].format(symbol=symbol)
        params = {k: v.format(symbol=symbol) if isinstance(v, str) else v
                  for k, v in endpoint_config["params"].items()}

        # Fetch data
        request_id = str(uuid.uuid4())
        fetched_at = datetime.now(timezone.utc)
        data_list, http_status = await client.fetch(endpoint, url, params)

        if not data_list:
            return {
                "symbol": symbol,
                "endpoint": endpoint,
                "files_written": 0,
                "records_written": 0,
                "errors": ["No data returned"],
            }

        # Build records
        records = [
            build_record(
                endpoint=endpoint,
                symbol=symbol,
                as_of_date=as_of_date,
                payload_obj=obj,
                fetched_at=fetched_at,
                http_status=http_status,
                request_id=request_id,
            )
            for obj in data_list
        ]

        # Build S3 key
        s3_key = endpoint_config["s3_path"].format(
            date=as_of_date,
            symbol=symbol,
        )

        # Write to S3
        written = write_ndjson_to_s3(records, s3_key, s3_client, bucket, force)

        return {
            "symbol": symbol,
            "endpoint": endpoint,
            "files_written": 1 if written else 0,
            "records_written": len(records) if written else 0,
            "skipped": not written,
            "errors": [],
        }

    except Exception as e:
        return {
            "symbol": symbol,
            "endpoint": endpoint,
            "files_written": 0,
            "records_written": 0,
            "errors": [str(e)],
        }


async def ingest_endpoint_market_wide(
    client: FMPClient,
    endpoint: str,
    endpoint_config: Dict,
    as_of_date: str,
    s3_client,
    bucket: str,
    force: bool,
) -> Dict:
    """
    Ingest market-wide endpoint (e.g., treasury rates) for a single day.

    Returns:
        Dict with endpoint, files_written, records_written, errors
    """
    try:
        # Build URL and params
        url = endpoint_config["url_template"]
        params = endpoint_config["params"].copy()

        # For treasury rates, add date filter to get specific day only
        if endpoint == "treasury_rates":
            params["from"] = as_of_date
            params["to"] = as_of_date

        # Fetch data
        request_id = str(uuid.uuid4())
        fetched_at = datetime.now(timezone.utc)
        data_list, http_status = await client.fetch(endpoint, url, params)

        if not data_list:
            return {
                "endpoint": endpoint,
                "files_written": 0,
                "records_written": 0,
                "errors": ["No data returned"],
            }

        # Build records
        records = [
            build_record(
                endpoint=endpoint,
                symbol=None,
                as_of_date=as_of_date,
                payload_obj=obj,
                fetched_at=fetched_at,
                http_status=http_status,
                request_id=request_id,
            )
            for obj in data_list
        ]

        # Build S3 key
        s3_key = endpoint_config["s3_path"].format(date=as_of_date)

        # Write to S3
        written = write_ndjson_to_s3(records, s3_key, s3_client, bucket, force)

        return {
            "endpoint": endpoint,
            "files_written": 1 if written else 0,
            "records_written": len(records) if written else 0,
            "skipped": not written,
            "errors": [],
        }

    except Exception as e:
        return {
            "endpoint": endpoint,
            "files_written": 0,
            "records_written": 0,
            "errors": [str(e)],
        }


async def ingest_treasury_rates_backfill(
    client: FMPClient,
    endpoint: str,
    endpoint_config: Dict,
    from_date: str,
    to_date: str,
    s3_client,
    bucket: str,
    force: bool,
) -> List[Dict]:
    """
    Backfill treasury rates for a date range.

    Fetches data for the entire range in one API call, then splits into daily files.

    Returns:
        List of result dicts (one per day)
    """
    try:
        # Build URL with date range params
        url = endpoint_config["url_template"]
        params = {
            "from": from_date,
            "to": to_date,
        }

        # Fetch data for entire range
        request_id = str(uuid.uuid4())
        fetched_at = datetime.now(timezone.utc)
        data_list, http_status = await client.fetch(endpoint, url, params)

        if not data_list:
            return [{
                "endpoint": endpoint,
                "files_written": 0,
                "records_written": 0,
                "errors": ["No data returned for date range"],
            }]

        # Group data by date
        from collections import defaultdict
        data_by_date = defaultdict(list)

        for obj in data_list:
            # Extract date from payload (treasury rates have 'date' field)
            date_str = obj.get("date")
            if date_str:
                data_by_date[date_str].append(obj)

        if not data_by_date:
            return [{
                "endpoint": endpoint,
                "files_written": 0,
                "records_written": 0,
                "errors": ["No valid dates found in response"],
            }]

        # Write one file per day (parallelized)
        async def write_day(date_str: str, day_data: List[Dict]) -> Dict:
            """Write one day's treasury data to S3."""
            # Build records for this day
            records = [
                build_record(
                    endpoint=endpoint,
                    symbol=None,
                    as_of_date=date_str,
                    payload_obj=obj,
                    fetched_at=fetched_at,
                    http_status=http_status,
                    request_id=request_id,
                )
                for obj in day_data
            ]

            # Build S3 key
            s3_key = endpoint_config["s3_path"].format(date=date_str)

            # Write to S3
            written = write_ndjson_to_s3(records, s3_key, s3_client, bucket, force)

            return {
                "endpoint": endpoint,
                "date": date_str,
                "files_written": 1 if written else 0,
                "records_written": len(records) if written else 0,
                "skipped": not written,
                "errors": [],
            }

        # Parallelize S3 writes
        write_tasks = [write_day(date_str, day_data) for date_str, day_data in sorted(data_by_date.items())]
        results = await asyncio.gather(*write_tasks)

        return list(results)

    except Exception as e:
        return [{
            "endpoint": endpoint,
            "files_written": 0,
            "records_written": 0,
            "errors": [str(e)],
        }]


# ============================================================================
# Main Orchestration
# ============================================================================

def load_symbols(symbols_file: str) -> List[str]:
    """Load symbols from local or S3 file."""
    if symbols_file.startswith("s3://"):
        parts = symbols_file.replace("s3://", "").split("/", 1)
        bucket = parts[0]
        key = parts[1] if len(parts) > 1 else ""

        s3_client = boto3.client("s3", region_name=Config.AWS_REGION)
        obj = s3_client.get_object(Bucket=bucket, Key=key)
        content = obj["Body"].read().decode("utf-8")
    else:
        with open(symbols_file, "r") as f:
            content = f.read()

    # Parse lines and skip header if present
    lines = [line.strip().upper() for line in content.splitlines() if line.strip()]
    # Skip first line if it's a header (contains 'symbol' or 'ticker')
    if lines and lines[0].lower() in ['symbol', 'ticker']:
        lines = lines[1:]

    return lines


async def main():
    parser = argparse.ArgumentParser(
        description="FMP raw data dumper for Bronze ingestion"
    )
    parser.add_argument(
        "--date",
        default="today",
        help="Snapshot date (YYYY-MM-DD or 'today')",
    )
    parser.add_argument(
        "--endpoints",
        default="all",
        help="Comma-separated endpoints or 'all'",
    )
    parser.add_argument(
        "--symbols-file",
        default="stock_pipeline/config/tickers.csv",
        help="Path to symbols file",
    )
    parser.add_argument(
        "--backfill-days",
        type=int,
        help="Backfill N days for treasury rates (only applies to treasury_rates endpoint)",
    )
    parser.add_argument(
        "--from-date",
        help="Start date for treasury rates backfill (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--to-date",
        help="End date for treasury rates backfill (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing S3 objects",
    )

    args = parser.parse_args()

    # Validate config
    Config.validate()

    # Parse date and backfill range
    if args.date == "today":
        # Use today if trading day, else previous trading day
        # (assumes script runs after market close)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if is_trading_day(today):
            as_of_date = today
            print(f"📅 Using today (trading day) for snapshot: {as_of_date}")
        else:
            as_of_date = get_previous_trading_day()
            print(f"📅 Using previous trading day for snapshot (today is weekend/holiday): {as_of_date}")
    else:
        as_of_date = args.date

    # Determine if treasury rates backfill is requested
    treasury_backfill_from = None
    treasury_backfill_to = None

    if args.backfill_days:
        from datetime import timedelta
        to_dt = datetime.now(timezone.utc)
        from_dt = to_dt - timedelta(days=args.backfill_days)
        treasury_backfill_from = from_dt.strftime("%Y-%m-%d")
        treasury_backfill_to = to_dt.strftime("%Y-%m-%d")
        print(f"📅 Treasury backfill range: {treasury_backfill_from} to {treasury_backfill_to}")
    elif args.from_date and args.to_date:
        treasury_backfill_from = args.from_date
        treasury_backfill_to = args.to_date
        print(f"📅 Treasury backfill range: {treasury_backfill_from} to {treasury_backfill_to}")
    else:
        print(f"📅 Snapshot date: {as_of_date}")

    # Parse endpoints
    if args.endpoints == "all":
        endpoints_to_run = list(ENDPOINTS.keys())
    else:
        endpoints_to_run = [e.strip() for e in args.endpoints.split(",")]

    print(f"🔗 Endpoints: {', '.join(endpoints_to_run)}")

    # Load symbols
    symbols = load_symbols(args.symbols_file)
    print(f"📊 Loaded {len(symbols)} symbols")

    # Initialize clients
    s3_client = boto3.client("s3", region_name=Config.AWS_REGION)
    rate_limiter = RateLimiter(Config.RATE_LIMIT_SECONDS)

    import time
    start_time = time.time()

    all_results = []

    async with FMPClient(Config.FMP_API_KEY, rate_limiter) as fmp_client:
        semaphore = asyncio.Semaphore(Config.MAX_WORKERS)

        for endpoint in endpoints_to_run:
            if endpoint not in ENDPOINTS:
                print(f"⚠️  Unknown endpoint: {endpoint}")
                continue

            endpoint_config = ENDPOINTS[endpoint]

            if endpoint_config["per_symbol"]:
                # Per-symbol endpoint
                async def bounded_ingest(sym: str):
                    async with semaphore:
                        return await ingest_endpoint_symbol(
                            fmp_client, endpoint, endpoint_config, sym,
                            as_of_date, s3_client, Config.S3_BUCKET, args.force
                        )

                results = await asyncio.gather(*[bounded_ingest(s) for s in symbols])
                all_results.extend(results)
            else:
                # Market-wide endpoint
                # Check if this is treasury_rates with backfill requested
                if (endpoint == "treasury_rates" and
                    treasury_backfill_from and treasury_backfill_to and
                    endpoint_config.get("supports_backfill")):
                    # Use backfill function
                    print(f"🔄 Backfilling treasury rates: {treasury_backfill_from} to {treasury_backfill_to}")
                    results = await ingest_treasury_rates_backfill(
                        fmp_client, endpoint, endpoint_config,
                        treasury_backfill_from, treasury_backfill_to,
                        s3_client, Config.S3_BUCKET, args.force
                    )
                    all_results.extend(results)
                    print(f"✅ Treasury backfill complete: {len(results)} days written")
                else:
                    # Regular single-day ingestion
                    result = await ingest_endpoint_market_wide(
                        fmp_client, endpoint, endpoint_config,
                        as_of_date, s3_client, Config.S3_BUCKET, args.force
                    )
                    all_results.append(result)

    elapsed_time = time.time() - start_time

    # Calculate metrics
    total_files = sum(r.get("files_written", 0) for r in all_results)
    total_records = sum(r.get("records_written", 0) for r in all_results)
    total_skipped = sum(1 for r in all_results if r.get("skipped"))
    total_errors = sum(1 for r in all_results if r.get("errors"))

    # Write metrics
    metrics = {
        "run_id": datetime.now(timezone.utc).isoformat(),
        "as_of_date": as_of_date,
        "endpoints": endpoints_to_run,
        "symbols_count": len(symbols),
        "files_written": total_files,
        "records_written": total_records,
        "errors": total_errors,
        "duration_seconds": round(elapsed_time, 2),
        "results": all_results,
    }

    metrics_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    metrics_ts = int(time.time())
    metrics_key = f"logs/ingest/date={metrics_date}/run-{metrics_ts}.json"

    s3_client.put_object(
        Bucket=Config.S3_BUCKET,
        Key=metrics_key,
        Body=json.dumps(metrics, indent=2),
        ContentType="application/json",
    )

    # Print summary
    print("\n" + "="*60)
    print("✅ FMP Raw Ingestion Complete")
    print("="*60)
    print(f"📁 Files written: {total_files}")
    print(f"⏭️  Files skipped: {total_skipped}")
    print(f"📝 Records written: {total_records:,}")
    print(f"❌ Errors: {total_errors}")
    print(f"⏱️  Duration: {elapsed_time:.1f}s")
    print(f"📋 Metrics: s3://{Config.S3_BUCKET}/{metrics_key}")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(main())
