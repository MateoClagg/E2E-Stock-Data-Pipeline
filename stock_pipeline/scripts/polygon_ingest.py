import os
import requests
import pandas as pd
import logging
import time
import random
import csv
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from pathlib import Path

# Load environment variables from .env
load_dotenv()
api_key = os.getenv("POLYGON_API_KEY")

# Configure logging to both file and console
os.makedirs("stock_pipeline/logs", exist_ok=True)
logging.basicConfig(
    filename="stock_pipeline/logs/ingestion.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logging.getLogger().addHandler(logging.StreamHandler())

# Constants
TICKER_FILE = "stock_pipeline/config/tickers.csv"  # CSV with list of tickers
FROM_DATE = "2020-01-01"                           # Start date for data (max range = 2 years on free plan)
TO_DATE = (datetime.now(timezone.utc) - timedelta(days=1, hours=6)).strftime("%Y-%m-%d")

# Create daily output directory
DAILY_DIR = Path(f"stock_pipeline/daily/{TO_DATE}")
DAILY_DIR.mkdir(parents=True, exist_ok=True)

PARQUET_PATH = DAILY_DIR / "merged.parquet"       # Output Parquet file path
QA_LOG_PATH = DAILY_DIR / "qa_log.csv"            # Per-ticker QA log path


# API Request + DataFrame Builder
def fetch_and_return(symbol: str) -> pd.DataFrame | None:
   
    # Fetch daily aggregate bars from Polygon API for a single symbol.
    url = (
        f"https://api.polygon.io/v2/aggs/ticker/{symbol}/range/1/day/"
        f"{FROM_DATE}/{TO_DATE}?adjusted=true&sort=asc&limit=50000&apiKey={api_key}"
    )

    try:
        res = requests.get(url)
        res.raise_for_status()
        data = res.json()

        if "results" not in data or not data["results"]:
            logging.error(f"❌ No valid data for {symbol}: {data}")
            return None

        # Convert to DataFrame and clean columns
        df = pd.DataFrame(data["results"])
        df["timestamp"] = pd.to_datetime(df["t"], unit="ms", origin="unix", errors="raise")
        df.drop(columns="t", inplace=True)
        df = df.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
        df = df[["timestamp", "open", "high", "low", "close", "volume"]]
        df["symbol"] = symbol

        # Basic QA checks before returning
        if df["volume"].sum() == 0 or len(df) < 10:
            logging.warning(f"⚠️ Skipping {symbol}: empty or invalid data")
            return None

        # Explicit typing
        df = df.astype({
            "timestamp": "datetime64[ns]",
            "open": "float",
            "high": "float",
            "low": "float",
            "close": "float",
            "volume": "int",
            "symbol": "string"
        })

        return df

    except Exception as e:
        logging.exception(f"❌ {symbol}: Exception occurred")
        return None


# Ticker File Loader
def load_ticker_list(path: str) -> list[str]:
    df = pd.read_csv(path)
    return df["symbol"].dropna().str.strip().unique().tolist()


# DataFrame QA Validator
def validate_df(df: pd.DataFrame, symbol: str) -> bool:
    if df is None or df.empty:
        logging.warning(f"{symbol}: empty DataFrame")
        return False
    if df["timestamp"].isnull().any():
        logging.error(f"{symbol}: NULL timestamps detected")
        return False
    if df["volume"].sum() == 0:
        logging.warning(f"{symbol}: Zero volume data")
        return False
    return True


# Main Ingestion Routine
if __name__ == "__main__":
    tickers = load_ticker_list(TICKER_FILE)
    final_data = []

    # Write QA log header if it doesn't exist
    if not QA_LOG_PATH.exists():
        with open(QA_LOG_PATH, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["symbol", "timestamp_min", "timestamp_max", "rows", "status", "message"])

    # Loop through each ticker and ingest one-by-one
    for i, symbol in enumerate(tickers):
        if i % 50 == 0:
            logging.info(f"🧭 Progress: {i}/{len(tickers)} tickers")

        try:
            df = fetch_and_return(symbol)
            quality_check = validate_df(df, symbol)

            if quality_check:
                final_data.append(df)
                logging.info(f"✅ {symbol} ingested")

                # Log successful QA result
                with open(QA_LOG_PATH, "a", newline="") as f:
                    writer = csv.writer(f)
                    writer.writerow([
                        symbol,
                        df["timestamp"].min(),
                        df["timestamp"].max(),
                        len(df),
                        "SUCCESS",
                        ""
                    ])
            else:
                # Log failed QA result
                with open(QA_LOG_PATH, "a", newline="") as f:
                    writer = csv.writer(f)
                    writer.writerow([symbol, "", "", 0, "FAIL", "Validation failed"])

        except Exception as e:
            logging.error(f"❌ {symbol} failed: {e}")
            # Log exception to QA log
            with open(QA_LOG_PATH, "a", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([symbol, "", "", 0, "FAIL", str(e)])

        # Wait 12–15 seconds to stay under free API rate limit
        time.sleep(random.uniform(12, 15))

    # Merge and save output
    if final_data:
        # Concatenate all valid DataFrames
        full_df = pd.concat(final_data, ignore_index=True)

        # Convert timestamp to ISO string (ensures Snowflake compatibility)
        full_df["timestamp"] = full_df["timestamp"].dt.strftime('%Y-%m-%d %H:%M:%S')

        # Final schema enforcement before write
        expected_cols = ['timestamp', 'open', 'high', 'low', 'close', 'volume', 'symbol']
        if list(full_df.columns) != expected_cols:
            raise ValueError(f"❌ Unexpected schema: {full_df.columns.tolist()}")

        # Write merged data to Parquet
        full_df.to_parquet(PARQUET_PATH, index=False)

        # Summary log
        logging.info(f"📦 Merged data saved to {PARQUET_PATH}")
        logging.info(f"🔍 Final row count: {len(full_df)}")
        logging.info(f"🕒 Time range: {full_df['timestamp'].min()} to {full_df['timestamp'].max()}")
        logging.info(f"📈 Symbols loaded: {full_df['symbol'].nunique()}")
    else:
        logging.warning("⚠️ No data collected.")
