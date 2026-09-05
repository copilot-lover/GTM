from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, HttpUrl

from app.core.deps import require_workspace
from app.services import scraping

router = APIRouter(prefix="/scrape", tags=["scrape"])

_BLOCKED_SCHEMES = {"file", "gopher", "ftp"}
_BLOCKED_HOSTS = {"169.254.169.254", "metadata.google.internal", "localhost", "127.0.0.1"}


def _is_private_host(hostname: str) -> bool:
    if hostname.startswith("169.254.") or hostname.startswith("10."):
        return True
    if hostname.startswith("172."):
        try:
            second = int(hostname.split(".")[1])
            if 16 <= second <= 31:
                return True
        except (IndexError, ValueError):
            pass
    if hostname.startswith("192.168."):
        return True
    if hostname == "0.0.0.0" or hostname.endswith(".internal"):
        return True
    # IPv6 loopback and mapped IPv4 loopback
    if hostname in ("::1", "::ffff:127.0.0.1", "0:0:0:0:0:0:0:1"):
        return True
    if hostname.startswith("::ffff:10.") or hostname.startswith("::ffff:172.") or hostname.startswith("::ffff:192.168."):
        return True
    return False


class ScrapeRequest(BaseModel):
    url: HttpUrl
    stealth: bool = False


@router.post("")
def scrape(req: ScrapeRequest, user: dict = Depends(require_workspace)) -> dict:
    """Internal endpoint used by n8n workflows to fetch page content."""
    from urllib.parse import urlparse
    parsed = urlparse(str(req.url))
    if parsed.scheme.lower() in _BLOCKED_SCHEMES:
        raise HTTPException(400, f"blocked scheme: {parsed.scheme}")
    hostname = (parsed.hostname or "").lower()
    if hostname in _BLOCKED_HOSTS or _is_private_host(hostname):
        raise HTTPException(400, "blocked host")
    try:
        result = scraping.scrape(str(req.url), stealth=req.stealth)
    except Exception:
        raise HTTPException(status_code=502, detail="scrape failed")
    return {
        "url": result.url,
        "status": result.status,
        "reason": result.reason,
        "body": result.body,
    }
