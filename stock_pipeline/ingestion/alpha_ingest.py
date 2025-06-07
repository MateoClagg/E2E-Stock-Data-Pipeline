import os
import requests
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("ALPHA_VANTAGE_API_KEY")

tickers = ["AAPL", "MSFT", "TSLA", "GOOGL", "NVDA"]
interval="5min"
outputsize="compact"

def fetch_and_save(symbol):

    # Call the API to get JSON
    url = (
        "https://www.alphavantage.co/query"
        f"?function=TIME_SERIES_INTRADAY"
        f"&symbol={symbol}"
        f"&interval={interval}"
        f"&outputsize={outputsize}"
        f"&apikey={api_key}"
    )
    
    response = requests.get(url)
    data = response.json()

    # Basic QA check: is the time series key present?
    key = f"Time Series ({interval})"
    if key not in data:
        print(f"❌ Error for {symbol}: {data}")
        return None

    # extract time series index key
    time_series = data["Time Series (5min)"]

    # Pass JSON data into DF
    df = pd.DataFrame.from_dict(time_series, orient="index")

    # Clean column names
    df = df.rename(columns={
        "1. open": "open",
        "2. high": "high",
        "3. low": "low",
        "4. close": "close",
        "5. volume": "volume"
    })

    # Reset the index and make timestamp a column
    df.index = pd.to_datetime(df.index)
    df.reset_index(inplace=True)
    df.rename(columns={"index": "timestamp"}, inplace=True)

    # Convert numeric columns from string to float/int
    df[["open", "high", "low", "close"]] = df[["open", "high", "low", "close"]].astype(float)
    df["volume"] = df["volume"].astype(int)
    df["symbol"] = symbol

    # Example: reject if volume = 0 or rows < 10
    if df["volume"].sum() == 0 or len(df) < 10:
        print(f"⚠️ Skipping {symbol}: suspicious data")
        return None

    timestamp = pd.Timestamp.utcnow().strftime("%Y%m%d%H%M%S")
    filename = f"storage/raw/{symbol}_prices_{timestamp}.csv"

    df.to_csv(filename, index=False)
    print(f"✅ Saved {symbol} to {filename}")
    return filename