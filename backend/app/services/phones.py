"""Phone normalization (E.164) and company dedupe helpers."""

import re
import unicodedata

DIGITS = re.compile(r"\D")


def normalize_phone(raw: str | None, default_country_code: str = "+1") -> str | None:
    """Normalize a US-centric phone number to E.164. Returns None if unusable."""
    if not raw:
        return None
    cleaned = DIGITS.sub("", unicodedata.normalize("NFKC", str(raw)))
    if not cleaned:
        return None
    if raw.strip().startswith("+"):
        return f"+{cleaned}"
    if len(cleaned) == 10:
        return f"{default_country_code}{cleaned}"
    if len(cleaned) == 11 and cleaned.startswith("1"):
        return f"+{cleaned}"
    return f"{default_country_code}{cleaned}" if len(cleaned) >= 10 else None


def dedupe_key(business_name: str, city: str | None, state: str | None) -> tuple[str, str, str]:
    """Canonical identity: (lower(business_name), city, state)."""
    return (
        business_name.strip().lower(),
        (city or "").strip().lower(),
        (state or "").strip().lower(),
    )
