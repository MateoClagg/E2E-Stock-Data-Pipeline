from dotenv import load_dotenv
import os

# Load .env file
load_dotenv()

# Alpha Vantage
ALPHA_VANTAGE_KEY = os.getenv("ALPHA_VANTAGE_API_KEY")

# Snowflake
SNOWFLAKE_CONFIG = {
    "sfURL": os.getenv("SNOWFLAKE_ACCOUNT"),
    "sfUser": os.getenv("SNOWFLAKE_USER"),
    "sfPassword": os.getenv("SNOWFLAKE_PASSWORD"),
    "sfDatabase": os.getenv("SNOWFLAKE_DATABASE"),
    "sfSchema": os.getenv("SNOWFLAKE_SCHEMA"),
    "sfWarehouse": os.getenv("SNOWFLAKE_WAREHOUSE"),
}

# Optional
ENV = os.getenv("ENV", "development")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
