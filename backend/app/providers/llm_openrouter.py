"""OpenRouter chat-completion LLM provider with an ordered model fallback chain.

Model chain comes from settings.llm_model_chain (comma-separated). complete()
walks the chain in order, retrying the next model on network errors,
HTTP >= 500, and 429s; non-retryable HTTP errors (4xx) abort immediately.

Tiering hook: 'cheap' starts at chain[0]; 'strong' uses the
LLM_STRONG_MODEL env override when set (else chain[0] — documented default);
'frontier' starts at the last model of the chain. Fallback continues through
the chain from the starting point.

If no API key is configured, construction raises ProviderUnavailable so tests
use fixtures instead. A `transport` callable may be injected for tests:
transport(payload: dict) -> dict with OpenRouter's response shape.
"""

import os
import time

from app.config import get_settings
from app.providers.base import LLMProvider, LLMResponse, ProviderUnavailable

RETRYABLE_STATUS = {429}


def _default_transport(payload: dict) -> dict:
    import httpx

    api_key = get_settings().llm_api_key or os.environ.get("OPENROUTER_API_KEY", "")
    resp = httpx.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json=payload,
        timeout=60.0,
    )
    if resp.status_code >= 400:
        raise OpenRouterError(resp.status_code, resp.text[:500])
    return resp.json()


class OpenRouterError(Exception):
    def __init__(self, status_code: int, body: str):
        self.status_code = status_code
        super().__init__(f"openrouter http {status_code}: {body}")


class OpenRouterChatLLM(LLMProvider):
    def __init__(self, transport=None):
        if not (get_settings().llm_api_key or os.environ.get("OPENROUTER_API_KEY")):
            raise ProviderUnavailable(
                "OPENROUTER_API_KEY/LLM_API_KEY not set; use a fixture provider"
            )
        self._transport = transport or _default_transport

    @staticmethod
    def chain() -> list[str]:
        return get_settings().llm_model_chain_list

    def _models_for_tier(self, model_tier: str) -> list[str]:
        chain = self.chain()
        if model_tier == "strong":
            override = os.environ.get("LLM_STRONG_MODEL")
            first = override if override else chain[0]
            return [first] + [m for m in chain if m != first]
        if model_tier == "frontier":
            return list(reversed(chain))
        return list(chain)

    def complete(self, system: str, user: str,
                 model_tier: str = "cheap") -> LLMResponse:
        models = self._models_for_tier(model_tier)
        payload_messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        last_error: Exception | None = None
        for model in models:
            started = time.monotonic()
            try:
                data = self._transport({
                    "model": model,
                    "messages": payload_messages,
                })
            except OpenRouterError as exc:
                last_error = exc
                if exc.status_code < 500 and exc.status_code not in RETRYABLE_STATUS:
                    raise
                continue
            except Exception as exc:  # network-level failure: try next model
                last_error = exc
                continue
            # Robustness: some free-tier models may return empty or malformed payloads
            if not data.get("choices") or not isinstance(data["choices"], list) or not data["choices"][0].get("message"):
                raise OpenRouterError(502, f"malformed llm response missing choices: {str(data)[:200]}")
            usage = data.get("usage", {})
            tokens_in = int(usage.get("prompt_tokens") or 0)
            tokens_out = int(usage.get("completion_tokens") or 0)
            model_used = data.get("model") or model
            content = data["choices"][0]["message"]["content"]
            from app.services.llm import estimate_cost

            return LLMResponse(
                content=content,
                model_used=model_used,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                latency_ms=int((time.monotonic() - started) * 1000),
                cost_usd=round(estimate_cost(model_used, tokens_in, tokens_out), 6),
            )
        raise ProviderUnavailable(f"all models failed; last error: {last_error}")
