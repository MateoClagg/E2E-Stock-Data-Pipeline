import pandas as pd

df = pd.read_parquet("stock_pipeline/daily/2025-06-29/merged.parquet")
print(df.head())
print(df["symbol"].value_counts())