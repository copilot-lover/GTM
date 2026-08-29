"""Provider protocols + registry.

The in-app provider layer replaces the old n8n boundary: every external
integration (job sources, enrichment, email finding/verification, LLM,
email transport) sits behind one of these interfaces. Implementations are
looked up by name via the registry; tests install fixture overrides that
take precedence over real registrations.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


class ProviderUnavailable(Exception):
    """Raised when a provider is not configured (e.g. missing API key)."""


@dataclass
class VerificationResult:
    email: str
    result: str
    confidence: float = 0.0
    raw: dict = field(default_factory=dict)


@dataclass
class LLMResponse:
    content: str
    model_used: str
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    cost_usd: float = 0.0


@dataclass
class SendResult:
    ok: bool
    provider_message_id: str | None = None
    error: str | None = None


class JobSourceProvider(ABC):
    @abstractmethod
    def search(self, query: str, filters: dict | None = None) -> list[dict]:
        """Return job postings matching query/filters as plain dicts."""


class EnrichmentProvider(ABC):
    @abstractmethod
    def enrich_company(self, company: dict) -> dict:
        """Return enriched company fields for the given company dict."""


class EmailFinderProvider(ABC):
    @abstractmethod
    def find_email(self, company: dict, contact_name: str,
                   title: str | None = None) -> dict | None:
        """Return {'email': ..., 'confidence': ...} or None if not found."""


class EmailVerificationProvider(ABC):
    @abstractmethod
    def verify(self, email: str) -> VerificationResult:
        """Classify an email address; never raises on bad input."""


class LLMProvider(ABC):
    @abstractmethod
    def complete(self, system: str, user: str,
                 model_tier: str = "cheap") -> LLMResponse:
        """Run a chat completion; model_tier is 'cheap'|'strong'|'frontier'."""


class EmailSendingProvider(ABC):
    @abstractmethod
    def send(self, *, from_addr: str, to: str, subject: str, body_text: str,
             body_html: str | None = None,
             message_id: str | None = None) -> SendResult:
        """Transmit one message; returns provider message id or error."""


class CRMProvider(ABC):
    @abstractmethod
    def upsert_company(self, company_data: dict) -> dict | None:
        """Create or update a company record."""

    @abstractmethod
    def upsert_contact(self, contact_data: dict) -> dict | None:
        """Create or update a contact record."""

    @abstractmethod
    def create_opportunity(self, opp_data: dict) -> dict | None:
        """Create an opportunity/deal record."""

    @abstractmethod
    def get_contact(self, contact_id: str) -> dict | None:
        """Retrieve a contact by ID."""

    @abstractmethod
    def search_contacts(self, query: str) -> dict | None:
        """Search contacts by query string."""


class CalendarProvider(ABC):
    @abstractmethod
    def create_event(self, event_data: dict) -> dict | None:
        """Create a calendar event."""

    @abstractmethod
    def get_availability(self, start: str, end: str) -> dict | None:
        """Get available slots in a time range."""

    @abstractmethod
    def book_slot(self, slot: dict, contact: dict) -> dict | None:
        """Book a specific slot for a contact."""


class Registry:
    """Name -> provider instance. Fixture overrides shadow registrations."""

    def __init__(self) -> None:
        self._providers: dict[str, object] = {}
        self._overrides: dict[str, object] = {}

    def register(self, name: str, provider: object) -> None:
        self._providers[name] = provider

    def override(self, name: str, provider: object) -> None:
        self._overrides[name] = provider

    def clear_overrides(self) -> None:
        self._overrides.clear()

    def get(self, name: str):
        if name in self._overrides:
            return self._overrides[name]
        if name in self._providers:
            return self._providers[name]
        raise ProviderUnavailable(f"no provider registered as '{name}'")


registry = Registry()
register = registry.register
get = registry.get
