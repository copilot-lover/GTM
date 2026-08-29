"""Email verification provider adapters: ZeroBounce, Hunter.

All implement EmailVerificationProvider.verify(email: str) -> VerificationResult.
Local pre-checks BEFORE provider call (syntax + DNS + disposable + spam trap).
CircuitBreaker(threshold=5), retry_with_backoff(3). Fixture fallback.
Confidence: local=60 max, provider=90.
"""

import logging
import os
import re
from typing import Any

import httpx

from app.providers.base import EmailVerificationProvider, ProviderUnavailable, VerificationResult
from app.providers.fixtures import FixtureVerifier
from app.providers.resilience import CircuitBreaker, retry_with_backoff_sync

log = logging.getLogger(__name__)

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")

DISPOSABLE_DOMAINS = {
    "mailinator.com", "guerrillamail.com", "10minutemail.com", "tempmail.com",
    "throwaway.email", "fakeinbox.com", "trashmail.com", "yopmail.com",
    "getnada.com", "maildrop.cc", "dispostable.com", "temp-mail.org",
    "emailondeck.com", "mintemail.com", "spamgourmet.com", "sharklasers.com",
    "grr.la", "bccto.me", "chacuo.net", "mytemp.email", "emailfake.com",
}

SPAM_TRAP_KEYWORDS = {
    "abuse", "postmaster", "hostmaster", "webmaster", "admin", "root",
    "noreply", "no-reply", "donotreply", "do-not-reply", "bounce",
    "spam", "trap", "honeypot",
}


def local_prechecks(email: str) -> dict:
    """Run local validation checks: syntax, DNS, disposable, spam trap heuristics."""
    checks = {
        "syntax_ok": False,
        "dns_ok": False,
        "disposable": False,
        "spam_trap_risk": False,
    }
    confidence = 0

    if not EMAIL_RE.match(email):
        return checks, 0

    checks["syntax_ok"] = True
    confidence = 30

    domain = email.split("@")[1].lower()
    local_part = email.split("@")[0].lower()

    if domain in DISPOSABLE_DOMAINS:
        checks["disposable"] = True

    if any(kw in local_part for kw in SPAM_TRAP_KEYWORDS):
        checks["spam_trap_risk"] = True

    try:
        import dns.resolver
        answers = dns.resolver.resolve(domain, "MX")
        if answers:
            checks["dns_ok"] = True
            confidence = 60
    except Exception:
        pass

    return checks, confidence


class ZeroBounceAdapter(EmailVerificationProvider):
    def __init__(self):
        self.api_key = os.getenv("ZEROBOUNCE_API_KEY")
        self.base_url = "https://api.zerobounce.net/v2"
        self.breaker = CircuitBreaker(failure_threshold=5, reset_timeout=60.0)
        self._fixture = FixtureVerifier(result="valid", confidence=0.95)
        if not self.api_key:
            log.warning("ZEROBOUNCE_API_KEY not set; will use fixture fallback")

    def verify(self, email: str) -> VerificationResult:
        log.info("zerobounce verify start", extra={"email": email})
        local_checks, local_confidence = local_prechecks(email)

        if not local_checks["syntax_ok"]:
            return VerificationResult(
                email=email,
                result="invalid",
                confidence=0,
                raw={"provider": "local", "local_checks": local_checks},
            )

        if local_checks["disposable"]:
            return VerificationResult(
                email=email,
                result="disposable",
                confidence=local_confidence,
                raw={"provider": "local", "local_checks": local_checks},
            )

        if local_checks["spam_trap_risk"]:
            return VerificationResult(
                email=email,
                result="spam_trap",
                confidence=local_confidence,
                raw={"provider": "local", "local_checks": local_checks},
            )

        if not self.api_key:
            result = self._fixture.verify(email)
            return VerificationResult(
                email=result.email,
                result=result.result,
                confidence=result.confidence,
                raw={"provider": "fixture", "local_checks": local_checks, **result.raw},
            )

        def _call():
            self.breaker.check()
            params = {"api_key": self.api_key, "email": email}
            with httpx.Client(timeout=30.0) as client:
                resp = client.get(f"{self.base_url}/validate", params=params)
                resp.raise_for_status()
                return resp.json()

        try:
            data = retry_with_backoff_sync(_call, attempts=3, base_delay=1.0, jitter=0.5)
            self.breaker.record_success()
            result = self._parse_response(data, email, local_checks)
            log.info("zerobounce verify success", extra={"email": email, "result": result.result})
            return result
        except Exception as e:
            self.breaker.record_failure()
            log.warning("zerobounce verify failed, using fixture", extra={"email": email, "error": str(e)})
            result = self._fixture.verify(email)
            return VerificationResult(
                email=result.email,
                result=result.result,
                confidence=result.confidence,
                raw={"provider": "fixture", "local_checks": local_checks, **result.raw},
            )

    def _parse_response(self, data: dict, email: str, local_checks: dict) -> VerificationResult:
        status = data.get("status", "unknown").lower()
        confidence_map = {
            "valid": 0.9,
            "invalid": 0.9,
            "catch-all": 0.7,
            "accept_all": 0.7,
            "unknown": 0.5,
            "spamtrap": 0.1,
            "abuse": 0.1,
            "do_not_mail": 0.2,
        }
        result_map = {
            "valid": "valid",
            "invalid": "invalid",
            "catch-all": "accept_all",
            "accept_all": "accept_all",
            "unknown": "unknown",
            "spamtrap": "spam_trap",
            "abuse": "abuse",
            "do_not_mail": "risky",
        }
        return VerificationResult(
            email=email,
            result=result_map.get(status, "unknown"),
            confidence=confidence_map.get(status, 0.5),
            raw={"provider": "zerobounce", "local_checks": local_checks, "raw": data},
        )


class HunterVerifyAdapter(EmailVerificationProvider):
    def __init__(self):
        self.api_key = os.getenv("HUNTER_API_KEY")
        self.base_url = "https://api.hunter.io/v2"
        self.breaker = CircuitBreaker(failure_threshold=5, reset_timeout=60.0)
        self._fixture = FixtureVerifier(result="valid", confidence=0.95)
        if not self.api_key:
            log.warning("HUNTER_API_KEY not set; will use fixture fallback")

    def verify(self, email: str) -> VerificationResult:
        log.info("hunter_verify verify start", extra={"email": email})
        local_checks, local_confidence = local_prechecks(email)

        if not local_checks["syntax_ok"]:
            return VerificationResult(
                email=email,
                result="invalid",
                confidence=0,
                raw={"provider": "local", "local_checks": local_checks},
            )

        if local_checks["disposable"]:
            return VerificationResult(
                email=email,
                result="disposable",
                confidence=local_confidence,
                raw={"provider": "local", "local_checks": local_checks},
            )

        if local_checks["spam_trap_risk"]:
            return VerificationResult(
                email=email,
                result="spam_trap",
                confidence=local_confidence,
                raw={"provider": "local", "local_checks": local_checks},
            )

        if not self.api_key:
            result = self._fixture.verify(email)
            return VerificationResult(
                email=result.email,
                result=result.result,
                confidence=result.confidence,
                raw={"provider": "fixture", "local_checks": local_checks, **result.raw},
            )

        def _call():
            self.breaker.check()
            params = {"api_key": self.api_key, "email": email}
            with httpx.Client(timeout=30.0) as client:
                resp = client.get(f"{self.base_url}/email-verifier", params=params)
                resp.raise_for_status()
                return resp.json()

        try:
            data = retry_with_backoff_sync(_call, attempts=3, base_delay=1.0, jitter=0.5)
            self.breaker.record_success()
            result = self._parse_response(data, email, local_checks)
            log.info("hunter_verify verify success", extra={"email": email, "result": result.result})
            return result
        except Exception as e:
            self.breaker.record_failure()
            log.warning("hunter_verify verify failed, using fixture", extra={"email": email, "error": str(e)})
            result = self._fixture.verify(email)
            return VerificationResult(
                email=result.email,
                result=result.result,
                confidence=result.confidence,
                raw={"provider": "fixture", "local_checks": local_checks, **result.raw},
            )

    def _parse_response(self, data: dict, email: str, local_checks: dict) -> VerificationResult:
        result_data = data.get("data", {})
        status = result_data.get("result", "unknown").lower()
        score = result_data.get("score", 0)
        confidence_map = {
            "deliverable": 0.9,
            "undeliverable": 0.9,
            "risky": 0.6,
            "unknown": 0.5,
        }
        result_map = {
            "deliverable": "valid",
            "undeliverable": "invalid",
            "risky": "risky",
            "unknown": "unknown",
        }
        return VerificationResult(
            email=email,
            result=result_map.get(status, "unknown"),
            confidence=confidence_map.get(status, max(0.5, score / 100.0)),
            raw={"provider": "hunter", "local_checks": local_checks, "raw": result_data},
        )


def register_providers():
    from app.providers import registry
    try:
        registry.register("zerobounce", ZeroBounceAdapter())
    except Exception as e:
        log.warning(f"ZeroBounceAdapter registration failed: {e}")
    try:
        registry.register("hunter_verify", HunterVerifyAdapter())
    except Exception as e:
        log.warning(f"HunterVerifyAdapter registration failed: {e}")