import requests
import time
from datetime import datetime, timedelta
import pytz
from utils.logger import logger


class NewsFilter:
    def __init__(self):
        self.api_url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
        self.cache_duration_seconds = 4 * 3600  # 4 hours
        self.cached_news = None   # FIX #11: None sentinel distinguishes "never fetched" from "empty"
        self.last_fetch_time = 0

    def fetch_news(self):
        current_time = time.time()

        # ── FIX #11 — Startup Race Condition Fix ─────────────────
        # Use `is not None` ONLY as the "already fetched" sentinel.
        # An empty list is a valid result (no high-impact events this week).
        # On first run self.cached_news is None → always attempt fetch.
        cache_is_fresh = (
            self.cached_news is not None and
            self.last_fetch_time > 0 and
            current_time - self.last_fetch_time < self.cache_duration_seconds
        )
        if cache_is_fresh:
            return self.cached_news

        try:
            response = requests.get(self.api_url, timeout=10)
            response.raise_for_status()
            data = response.json()

            filtered_events = []
            for item in data:
                if item.get("country") == "USD" and item.get("impact") == "High":
                    try:
                        event_time = datetime.fromisoformat(item["date"]).astimezone(pytz.utc)
                        filtered_events.append({
                            "title": item.get("title"),
                            "time": event_time
                        })
                    except Exception as e:
                        logger.error(f"[SYSTEM] Error parsing news date '{item.get('date')}': {e}")

            self.cached_news = filtered_events
            self.last_fetch_time = current_time
            logger.info(f"[SYSTEM] Fetched {len(filtered_events)} High-Impact USD news events for this week.")
            return self.cached_news

        except Exception as e:
            logger.error(f"[SYSTEM] Failed to fetch news data: {e}")
            # On API failure: return existing cache if available, else empty list.
            # We do NOT update self.cached_news so next tick retries the fetch.
            return self.cached_news if self.cached_news is not None else []

    def is_news_active(self, window_minutes=30):
        try:
            news_events = self.fetch_news()
            if not news_events:
                return False

            now_utc = datetime.now(pytz.utc)
            for event in news_events:
                event_time = event["time"]
                time_diff  = abs((now_utc - event_time).total_seconds()) / 60.0
                if time_diff <= window_minutes:
                    logger.warning(
                        f"[WARNING] Signal suppressed. Inside High-Impact News Window: "
                        f"{event['title']} (Time Diff: {time_diff:.1f} mins)"
                    )
                    return True
            return False
        except Exception as e:
            logger.error(f"[SYSTEM] Error checking news status: {e}")
            return False
