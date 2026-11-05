from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
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
    data_available: bool = True


def _parse_rss(url: str) -> list[tuple[str, datetime | None]] | None:
    """Return parsed feed items, or None when the feed could not be verified."""
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
        log.warning("Economic news feed unavailable (%s): %s", url, exc)
        return None


def nfp_risk(now: datetime | None = None) -> NewsRisk:
    """Detect nearby NFP headlines without inventing a directional bias.

    A successful RSS response only verifies that a headline feed responded; it
    does not verify consensus forecasts, BLS actuals, unemployment, wages, or
    revisions. Those values must remain explicitly unavailable until a trusted
    structured source is integrated.
    """
    now = now or datetime.now(timezone.utc)
    feeds = [
        "https://www.forexfactory.com/rss.php",
        "https://www.dailyfx.com/feeds/forex.xml",
    ]
    keywords = ("nonfarm payroll", "non-farm payroll", "nfp", "employment report")
    successful_feed = False
    for feed in feeds:
        items = _parse_rss(feed)
        if items is None:
            continue
        successful_feed = True
        for title, published in items:
            lower = title.lower()
            if not any(keyword in lower for keyword in keywords):
                continue
            if published is None or abs((published - now).total_seconds()) <= 24 * 3600:
                return NewsRisk(
                    True, "NFP RISK",
                    f"{title} | Forecast/actual labor data: UNAVAILABLE (headline feed only)",
                    published, True,
                )

    if not successful_feed:
        return NewsRisk(
            False, "NFP DATA UNAVAILABLE",
            "Economic news feeds could not be reached; NFP event, forecast and actual data are unverified.",
            None, False,
        )

    return NewsRisk(
        False, "NO NFP HEADLINE DETECTED",
        "Headline feeds responded, but no nearby NFP headline was found. This does not verify the economic calendar or forecast/actual figures.",
        None, True,
    )


def should_reduce_risk(category: str, risk: NewsRisk, symbol: str | None = None) -> bool:
    """Apply the NFP score haircut only to USD-exposed markets."""
    if not risk.high_impact:
        return False
    if category == "forex":
        return bool(symbol and "USD" in symbol.upper())
    return category == "commodity"
