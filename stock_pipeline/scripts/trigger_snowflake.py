import os
import snowflake.connector

conn = snowflake.connector.connect(
    user=os.getenv("SNOWFLAKE_USER"),
    password=os.getenv("SNOWFLAKE_PASSWORD"),
    account=os.getenv("SNOWFLAKE_ACCOUNT"),
    warehouse=os.getenv("SNOWFLAKE_WAREHOUSE"),
    database=os.getenv("SNOWFLAKE_DATABASE"),
    schema=os.getenv("SNOWFLAKE_SCHEMA")
)

try:
    cursor = conn.cursor()
    cursor.execute("CALL load_stock_prices()")  # Or your dynamic SQL
    print("✅ Snowflake procedure triggered successfully.")
finally:
    cursor.close()
    conn.close()
