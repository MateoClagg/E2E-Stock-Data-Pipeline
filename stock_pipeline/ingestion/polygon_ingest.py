import os
import requests
import pandas as pd
import logging
import subprocess
from datetime import datetime
from dotenv import load_dotenv
from pathlib import Path
from datetime import timedelta

# Load environment variables
load_dotenv()
api_key = os.getenv("POLYGON_API_KEY")

# Make logging directory if needed
os.makedirs("stock_pipeline/logs", exist_ok=True)

# Logging setup
logging.basicConfig(
    filename="stock_pipeline/logs/ingestion.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logging.getLogger().addHandler(logging.StreamHandler())

TICKERS = ["AAPL", "MSFT", "TSLA", "GOOGL", "NVDA"]
FROM_DATE = "2020-01-01"
TO_DATE = (datetime.utcnow() - timedelta(hours=6)).strftime("%Y-%m-%d")

LOCAL_DIR = Path("stock_pipeline/storage/raw")

def fetch_and_save(symbol: str) -> Path | None:
    url = (
        f"https://api.polygon.io/v2/aggs/ticker/{symbol}/range/1/day/"
        f"{FROM_DATE}/{TO_DATE}?adjusted=true&sort=asc&limit=50000&apiKey={api_key}"
    )

    try:
        res = requests.get(url)
        res.raise_for_status()
        data = res.json()

        if "results" not in data:
            logging.error(f"❌ Missing 'results' for {symbol}: {data}")
            return None

        df = pd.DataFrame(data["results"])

        df["timestamp"] = pd.to_datetime(df["t"], unit="ms", origin="unix", errors="raise")
        df.drop(columns="t", inplace=True)

        df = df.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
        df = df[["timestamp", "open", "high", "low", "close", "volume"]]
        df["symbol"] = symbol

        if df["volume"].sum() == 0 or len(df) < 10:
            logging.warning(f"⚠️ Skipping {symbol}: empty or invalid data")
            return None

        df = df.astype({
            "timestamp": "datetime64[ns]",
            "open": "float",
            "high": "float",
            "low": "float",
            "close": "float",
            "volume": "int",
            "symbol": "string"
        })

        print(df["timestamp"].min(), df["timestamp"].max())

        (LOCAL_DIR / TO_DATE).mkdir(parents=True, exist_ok=True)
        
        path = LOCAL_DIR / TO_DATE / f"{symbol}_daily_full.parquet"
        df["timestamp"] = df["timestamp"].dt.strftime('%Y-%m-%d %H:%M:%S')
        df.to_parquet(path, index=False, engine="pyarrow")
        logging.info(f"✅ {symbol} saved to {path}")
        print(df.dtypes)
        print(df.head(3))
        return path

    except Exception as e:
        logging.exception(f"❌ {symbol}: Exception occurred")
        return None


if __name__ == "__main__":
    for ticker in TICKERS:
        path = fetch_and_save(ticker)
        
