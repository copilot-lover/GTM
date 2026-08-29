from app.providers import fixtures, resilience
from app.providers import enrichment as enrichment_providers
from app.providers import email_verification as email_verification_providers
from app.providers import email_finder as email_finder_providers
from app.providers.base import (
    EmailFinderProvider,
    EmailSendingProvider,
    EmailVerificationProvider,
    EnrichmentProvider,
    JobSourceProvider,
    LLMProvider,
    LLMResponse,
    ProviderUnavailable,
    Registry,
    SendResult,
    VerificationResult,
    get,
    register,
    registry,
)

# Register real providers (they handle missing API keys gracefully)
enrichment_providers.register_providers()
email_verification_providers.register_providers()
email_finder_providers.register_providers()

__all__ = [
    "fixtures",
    "resilience",
    "EmailFinderProvider",
    "EmailSendingProvider",
    "EmailVerificationProvider",
    "EnrichmentProvider",
    "JobSourceProvider",
    "LLMProvider",
    "LLMResponse",
    "ProviderUnavailable",
    "Registry",
    "registry",
    "register",
    "get",
    "SendResult",
    "VerificationResult",
]
