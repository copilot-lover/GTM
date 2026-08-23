from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, HttpUrl

from app.services import scraping

router = APIRouter(prefix="/scrape", tags=["scrape"])


class ScrapeRequest(BaseModel):
    url: HttpUrl
    stealth: bool = False


@router.post("")
def scrape(req: ScrapeRequest) -> dict:
    """Internal endpoint used by n8n workflows to fetch page content."""
    try:
        result = scraping.scrape(str(req.url), stealth=req.stealth)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"scrape failed: {type(e).__name__}: {e}")
    return {
        "url": result.url,
        "status": result.status,
        "reason": result.reason,
        "body": result.body,
    }
