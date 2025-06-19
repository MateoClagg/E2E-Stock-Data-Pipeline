import os
import requests
import pandas as pd
import logging
import time
from datetime import datetime, date, timedelta
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("POLYGON_API_KEY")

# setup global logging
logging.basicConfig(
        filename="C:/E2E-Stock-Data-Pipeline/stock_pipeline/logs/ingestion.log",
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
        )
logging.getLogger().addHandler(logging.StreamHandler())

tickers = ["AAPL", "MSFT", "TSLA", "GOOGL", "NVDA"]
from_date = "2020-01-01"
to_date = datetime.today().strftime("%Y-%m-%d")

def fetch_and_save(symbol):

    # Configure API Call
    url = (
    f"https://api.polygon.io/v2/aggs/ticker/{symbol}/range/1/day/"
    f"{from_date}/{to_date}?adjusted=true&sort=asc&limit=50000&apiKey={api_key}"
    )


    try:
        # Call the API to get JSON
        response = requests.get(url)
        data = response.json()

        # Basic QA check: is the "results" key present
        if "results" not in data:
            logging.error(f"❌ Error for {symbol}: {data}")
            return None

        df = pd.DataFrame(data["results"])
        df["timestamp"] = pd.to_datetime(df["t"], unit="ms")

        df = df.rename(columns={
            "o": "open",
            "h": "high",
            "l": "low",
            "c": "close",
            "v": "volume"
        })

        df = df[["timestamp", "open", "high", "low", "close", "volume"]]
        df["symbol"] = symbol

        # Example: reject if volume = 0 or rows < 10
        if df["volume"].sum() == 0 or len(df) < 10:
            logging.warning(f"⚠️ Skipping {symbol}: suspicious data")
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

        print(df.head)

        filename = f"C:/E2E-Stock-Data-Pipeline/stock_pipeline/storage/raw/{symbol}_daily_full.parquet"

        df.to_parquet(filename, index=False, engine="pyarrow", coerce_timestamps="ms")

        logging.info(f"✅ Saved {symbol} to {filename}")

        return filename
    
    except Exception as e:
        logging.exception(f"❌ {symbol}: Exception occurred")
        return None
    
# Loop through tickers
for symbol in tickers:
    fetch_and_save(symbol)
    

