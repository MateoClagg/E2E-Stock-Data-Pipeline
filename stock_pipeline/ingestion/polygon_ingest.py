import os
import requests
import pandas as pd
import logging
import subprocess
from datetime import datetime
from dotenv import load_dotenv
from pathlib import Path

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
TO_DATE = datetime.today().strftime("%Y-%m-%d")

LOCAL_DIR = Path("stock_pipeline/storage/raw")
DBFS_DIR = "dbfs:/FileStore/stock_pipeline"

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
        df["timestamp"] = pd.to_datetime(df["t"], unit="ms")
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

        LOCAL_DIR.mkdir(parents=True, exist_ok=True)
        path = LOCAL_DIR / f"{symbol}_daily_full.parquet"
        df.to_parquet(path, index=False, engine="pyarrow", coerce_timestamps="ms")
        logging.info(f"✅ {symbol} saved to {path}")
        return path

    except Exception as e:
        logging.exception(f"❌ {symbol}: Exception occurred")
        return None

def upload_to_dbfs(local_path: Path):
    remote_path = f"{DBFS_DIR}/{local_path.name}"
    databricks_config_path = os.path.expanduser("~/.databricks/config")
    env = os.environ.copy()
    env["DATABRICKS_CONFIG_FILE"] = databricks_config_path

    try:
        subprocess.run(
            ["databricks", "fs", "cp", str(local_path), remote_path, "--overwrite"],
            check=True,
            env=env
        )
        logging.info(f"🚀 Uploaded to {remote_path}")
    except subprocess.CalledProcessError as e:
        logging.error(f"❌ Failed to upload {local_path} to DBFS: {e}")


if __name__ == "__main__":
    for ticker in TICKERS:
        path = fetch_and_save(ticker)
        if path:
            upload_to_dbfs(path)
