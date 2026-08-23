"""Web scraping layer built on Scrapling (https://github.com/D4Vinci/Scrapling).

All outbound page fetching in Orbit goes through this module so rate
limits, user agents, and parsing stay consistent.
"""

from dataclasses import dataclass

from scrapling.fetchers import Fetcher


@dataclass
class ScrapeResult:
    url: str
    status: int
    reason: str
    body: str


def scrape(url: str, *, stealth: bool = False) -> ScrapeResult:
    """Fetch a page. `stealth=True` uses Scrapling's anti-bot fetcher
    (requires browsers installed via `scrapling install`)."""
    if stealth:
        from scrapling.fetchers import StealthyFetcher

        response = StealthyFetcher.fetch(url)
    else:
        response = Fetcher.get(url)

    body = response.body
    if isinstance(body, bytes):
        body = body.decode("utf-8", errors="replace")

    return ScrapeResult(
        url=url,
        status=response.status,
        reason=getattr(response, "reason", "") or "",
        body=body,
    )
