import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path
import subprocess
import logging

# Config
DAILY_BASE = Path("stock_pipeline/daily")
DAYS_TO_KEEP = 14
S3_BUCKET = "e2e-stock-pipeline-data"
S3_PREFIX = "stock_pipeline/daily"

# Setup logging
logging.basicConfig(
    filename="stock_pipeline/logs/cleanup.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logging.getLogger().addHandler(logging.StreamHandler())

def folder_exists_in_s3(s3_path: str) -> bool:
    result = subprocess.run(
        ["aws", "s3", "ls", s3_path],
        capture_output=True,
        text=True
    )
    return result.returncode == 0 and result.stdout.strip() != ""

def archive_and_cleanup():
    cutoff = datetime.utcnow() - timedelta(days=DAYS_TO_KEEP)

    for folder in DAILY_BASE.glob("*"):
        try:
            folder_date = datetime.strptime(folder.name, "%Y-%m-%d")
            if folder_date < cutoff:
                s3_path = f"s3://{S3_BUCKET}/{S3_PREFIX}/{folder.name}/"

                if folder_exists_in_s3(s3_path):
                    logging.info(f"⏩ Skipping upload for {folder.name}: already archived")
                else:
                    logging.info(f"📤 Uploading {folder.name} to {s3_path}")
                    subprocess.run(["aws", "s3", "cp", str(folder), s3_path, "--recursive"], check=True)

                # Always delete local folder after upload check
                shutil.rmtree(folder)
                logging.info(f"🧹 Deleted local folder: {folder}")

        except ValueError:
            continue  # Non-date folder name, skip


if __name__ == "__main__":
    archive_and_cleanup()
