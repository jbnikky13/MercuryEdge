from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
import urllib.request
import xml.etree.ElementTree as ET

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class NewsRisk:
    high_impact: bool
    label: str
    reason: str
    event_time: datetime | None = None


def _parse_rss(url: str) -> list[tuple[str, datetime | None]]:
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "MercuryEdge/1.0"})
        with urllib.request.urlopen(request, timeout=10) as response:
            root = ET.fromstring(response.read())
        items = []
        for item in root.findall(".//item"):
            title = (item.findtext("title") or "").strip()
            published = item.findtext("pubDate")
            dt = None
            if published:
                try:
                    from email.utils import parsedate_to_datetime
                    dt = parsedate_to_datetime(published).astimezone(timezone.utc)
                except Exception:
                    pass
            items.append((title, dt))
        return items
    except Exception as exc:
        log.warning("Economic news feed unavailable: %s", exc)
        return []


def nfp_risk(now: datetime | None = None) -> NewsRisk:
    """Detect NFP-related headlines in a +/- 24h window.

    News is a risk filter, not a directional signal. If the feed is unavailable,
    MercuryEdge continues with technical analysis rather than inventing news.
    """
    now = now or datetime.now(timezone.utc)
    feeds = [
        "https://www.forexfactory.com/rss.php",
        "https://www.dailyfx.com/feeds/forex.xml",
    ]
    keywords = ("nonfarm payroll", "non-farm payroll", "nfp", "employment report")
    for feed in feeds:
        for title, published in _parse_rss(feed):
            lower = title.lower()
            if not any(keyword in lower for keyword in keywords):
                continue
            if published is None or abs((published - now).total_seconds()) <= 24 * 3600:
                return NewsRisk(True, "NFP RISK", title, published)
    return NewsRisk(False, "NO NFP ALERT", "No nearby NFP headline detected")


def should_reduce_risk(category: str, risk: NewsRisk) -> bool:
    """NFP primarily affects USD pairs and USD-sensitive commodities."""
    if not risk.high_impact:
        return False
    return category in {"forex", "commodity"}
