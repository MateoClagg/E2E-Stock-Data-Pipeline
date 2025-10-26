"""
Date utility functions for ingestion pipeline.

Uses pandas_market_calendars for accurate trading day calculations.
"""

from datetime import datetime, timedelta
from typing import List, Tuple

import pandas as pd
import pandas_market_calendars as mcal


def get_nyse_calendar():
    """Get NYSE trading calendar."""
    return mcal.get_calendar('NYSE')


def split_date_range_by_month(from_date: str, to_date: str) -> List[Tuple[str, str]]:
    """
    Split a date range into monthly chunks.

    Args:
        from_date: Start date YYYY-MM-DD
        to_date: End date YYYY-MM-DD

    Returns:
        List of (start, end) tuples for each month

    Example:
        >>> split_date_range_by_month("2024-01-15", "2024-03-20")
        [
            ("2024-01-15", "2024-01-31"),
            ("2024-02-01", "2024-02-29"),
            ("2024-03-01", "2024-03-20"),
        ]
    """
    start = datetime.strptime(from_date, "%Y-%m-%d")
    end = datetime.strptime(to_date, "%Y-%m-%d")

    chunks = []
    current = start

    while current <= end:
        # Find last day of current month
        if current.month == 12:
            next_month = current.replace(year=current.year + 1, month=1, day=1)
        else:
            next_month = current.replace(month=current.month + 1, day=1)

        month_end = next_month - timedelta(days=1)

        # Chunk is from current to min(month_end, end)
        chunk_end = min(month_end, end)
        chunks.append((current.strftime("%Y-%m-%d"), chunk_end.strftime("%Y-%m-%d")))

        # Move to next month
        current = next_month

    return chunks


def get_trading_days(from_date: str, to_date: str, exchange: str = "NYSE") -> List[str]:
    """
    Get list of valid trading days between dates.

    Args:
        from_date: Start date YYYY-MM-DD
        to_date: End date YYYY-MM-DD
        exchange: Exchange calendar (default: NYSE)

    Returns:
        List of trading day strings YYYY-MM-DD (excludes weekends/holidays)
    """
    calendar = mcal.get_calendar(exchange)
    schedule = calendar.schedule(start_date=from_date, end_date=to_date)

    trading_days = schedule.index.strftime("%Y-%m-%d").tolist()
    return trading_days


def get_last_n_trading_days(n_days: int, end_date: str = None, exchange: str = "NYSE") -> Tuple[str, str]:
    """
    Get date range for last N trading days.

    Args:
        n_days: Number of trading days to go back
        end_date: End date YYYY-MM-DD (default: yesterday)
        exchange: Exchange calendar (default: NYSE)

    Returns:
        Tuple of (from_date, to_date) as strings YYYY-MM-DD

    Example:
        >>> get_last_n_trading_days(5)
        ('2024-09-23', '2024-09-27')  # 5 trading days ending yesterday
    """
    if end_date:
        end = pd.Timestamp(end_date)
    else:
        # Default to yesterday
        end = pd.Timestamp.now().normalize() - pd.Timedelta(days=1)

    # Get calendar and find valid schedule up to end date
    calendar = mcal.get_calendar(exchange)

    # Look back extra days to ensure we get enough trading days
    # (accounting for weekends/holidays)
    lookback_days = int(n_days * 1.5) + 10  # Buffer for holidays
    start_search = end - pd.Timedelta(days=lookback_days)

    schedule = calendar.schedule(start_date=start_search, end_date=end)
    trading_days = schedule.index

    if len(trading_days) < n_days:
        # Need to go back further
        lookback_days = n_days * 2 + 20
        start_search = end - pd.Timedelta(days=lookback_days)
        schedule = calendar.schedule(start_date=start_search, end_date=end)
        trading_days = schedule.index

    # Get last n_days
    if len(trading_days) >= n_days:
        last_n = trading_days[-n_days:]
        from_date = last_n[0].strftime("%Y-%m-%d")
        to_date = last_n[-1].strftime("%Y-%m-%d")
    else:
        # Fallback if not enough trading days
        from_date = trading_days[0].strftime("%Y-%m-%d") if len(trading_days) > 0 else end.strftime("%Y-%m-%d")
        to_date = end.strftime("%Y-%m-%d")

    return from_date, to_date


def is_trading_day(date: str, exchange: str = "NYSE") -> bool:
    """
    Check if a date is a valid trading day.

    Args:
        date: Date string YYYY-MM-DD
        exchange: Exchange calendar (default: NYSE)

    Returns:
        True if trading day, False otherwise
    """
    calendar = mcal.get_calendar(exchange)
    schedule = calendar.schedule(start_date=date, end_date=date)
    return len(schedule) > 0


def get_previous_trading_day(date: str = None, exchange: str = "NYSE") -> str:
    """
    Get the previous trading day before a given date.

    Args:
        date: Date string YYYY-MM-DD (default: today)
        exchange: Exchange calendar (default: NYSE)

    Returns:
        Previous trading day as YYYY-MM-DD
    """
    if date:
        current = pd.Timestamp(date)
    else:
        current = pd.Timestamp.now().normalize()

    # Look back up to 10 days to find previous trading day
    calendar = mcal.get_calendar(exchange)
    start_search = current - pd.Timedelta(days=10)
    schedule = calendar.schedule(start_date=start_search, end_date=current)

    # Get all trading days before current
    trading_days = schedule.index[schedule.index < current]

    if len(trading_days) > 0:
        return trading_days[-1].strftime("%Y-%m-%d")
    else:
        # Fallback: just go back 1 day
        return (current - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
