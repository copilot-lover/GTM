"""Provider-agnostic LLM adapter (spec AD-11).
Cheap/frontier model tiering via agents table config. Structured-JSON helper
with one automatic correction retry, then raises ReviewRequired (fail-closed).
"""

import json
import os
import re
import time

import httpx

import app.db as db


class MissingConfiguration(Exception):
    pass


class BudgetExceeded(Exception):
    pass


class ReviewRequired(Exception):
    """Agent output failed validation after retry — route to human review."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


# rough $/1k tokens for cost ledger estimates; update as pricing changes
PRICING = {
    "gpt-4o-mini": (0.00015, 0.0006),
    "gpt-4o": (0.0025, 0.01),
    "gpt-4.1-mini": (0.0004, 0.0016),
    "gpt-5-mini": (0.0004, 0.0016),
    "claude-haiku": (0.0008, 0.004),
    "claude-sonnet": (0.003, 0.015),
}

CHEAP_MODELS = {"openai": "gpt-4o-mini", "anthropic": "claude-haiku"}
FRONTIER_MODELS = {"openai": "gpt-4o", "anthropic": "claude-sonnet"}

DEFAULT_TIERS = {
    "qualification_agent": "cheap",
    "enrichment_agent": "cheap",
    "website_audit_agent": "cheap",
    "offer_selection_agent": "cheap",
    "reply_classification_agent": "cheap",
    "hiring_intent_qualifier": "cheap",
    "email_critic_agent": "cheap",
    "email_personalization_agent": "frontier",
    "sales_manager_agent": "frontier",
}


def _api_key(provider: str) -> str:
    key = os.environ.get("OPENAI_API_KEY" if provider == "openai" else "ANTHROPIC_API_KEY", "")
    if not key:
        raise MissingConfiguration(f"{provider} API key not configured")
    return key


def resolve_model(agent_name: str) -> tuple[str, str]:
    """Returns (provider, model) from env overrides or default tiering."""
    provider_env = os.environ.get("ORBIT_LLM_PROVIDER", "openai")
    tier = DEFAULT_TIERS.get(agent_name, "cheap")
    model_env = os.environ.get(
        "ORBIT_FRONTIER_MODEL" if tier == "frontier" else "ORBIT_CHEAP_MODEL"
    )
    models = FRONTIER_MODELS if tier == "frontier" else CHEAP_MODELS
    return provider_env, model_env or models[provider_env]


def check_budget(workspace_id: str | None) -> None:
    limit = float(os.environ.get("AI_DAILY_BUDGET_USD", "10"))
    with db.get_pool().connection() as conn:
        row = conn.execute(
            """SELECT COALESCE(SUM(cost_usd),0) AS spent FROM agent_runs
               WHERE started_at >= date_trunc('day', now())
               AND (%s::uuid IS NULL OR workspace_id = %s::uuid)""",
            (workspace_id, workspace_id),
        ).fetchone()
    spent = float(row["spent"] or 0)
    if spent >= limit:
        raise BudgetExceeded(f"daily AI budget spent: ${spent:.2f} / ${limit:.2f}")


def estimate_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    pin, pout = PRICING.get(model, (0.001, 0.002))
    return (tokens_in * pin + tokens_out * pout) / 1000


def complete(
    *,
    agent_name: str,
    system: str,
    user: str,
    workspace_id: str | None = None,
    max_tokens: int = 1200,
) -> dict:
    """Single-purpose LLM call. Returns {content, tokens_in, tokens_out, model}."""
    provider, model = resolve_model(agent_name)
    key = _api_key(provider)

    # budget soft alert at 80%
    try:
        check_budget(workspace_id)
    except BudgetExceeded:
        raise

    started = time.time()
    if provider == "openai":
        resp = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": model,
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": user}],
                "max_tokens": max_tokens,
            },
            timeout=90,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        tokens_in, tokens_out = usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
    else:
        resp = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
            json={
                "model": model,
                "max_tokens": max_tokens,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
            timeout=90,
        )
        resp.raise_for_status()
        data = resp.json()
        content = "".join(b.get("text", "") for b in data.get("content", []))
        usage = data.get("usage", {})
        tokens_in, tokens_out = usage.get("input_tokens", 0), usage.get("output_tokens", 0)

    latency_ms = int((time.time() - started) * 1000)
    record_run(
        agent_name=agent_name,
        trigger="llm_call",
        input_ref={"chars": len(user)},
        output_ref={"chars": len(content)},
        status="success",
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=estimate_cost(model, tokens_in, tokens_out),
        latency_ms=latency_ms,
        workspace_id=workspace_id,
    )
    return {
        "content": content,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "model": model,
        "cost_usd": estimate_cost(model, tokens_in, tokens_out),
    }


def extract_json(content: str) -> dict:
    """Pull the first JSON object out of an LLM response."""
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if not match:
        raise ValueError("no JSON object found in response")
    return json.loads(match.group(0))


def structured_complete(
    *, agent_name: str, system: str, user: str, required_keys: list[str],
    workspace_id: str | None = None, max_tokens: int = 1200,
) -> dict:
    """LLM call validated against required keys; one correction retry, then fail-closed."""
    result = complete(
        agent_name=agent_name, system=system + (
            "\nRespond with ONLY a valid JSON object containing exactly these keys: "
            + ", ".join(required_keys)
        ),
        user=user, workspace_id=workspace_id, max_tokens=max_tokens,
    )
    try:
        parsed = extract_json(result["content"])
        missing = [k for k in required_keys if k not in parsed]
        if not missing:
            return parsed
        errors = [f"missing keys: {missing}"]
    except (ValueError, json.JSONDecodeError) as e:
        errors = [f"invalid JSON: {e}"]
        parsed = None

    # one correction retry
    correction = (
        f"Your previous response was invalid ({'; '.join(errors)}). "
        f"Return ONLY corrected JSON with these exact keys: {', '.join(required_keys)}.\n\n"
        f"Previous response:\n{result['content'][:2000]}"
    )
    result2 = complete(
        agent_name=agent_name, system=system, user=user + "\n\n" + correction,
        workspace_id=workspace_id, max_tokens=max_tokens,
    )
    try:
        parsed2 = extract_json(result2["content"])
        missing2 = [k for k in required_keys if k not in parsed2]
        if not missing2:
            return parsed2
        raise ReviewRequired([f"missing keys after retry: {missing2}"])
    except (ValueError, json.JSONDecodeError) as e:
        raise ReviewRequired([f"invalid JSON after retry: {e}"])


def record_run(
    *, agent_name: str, trigger: str, input_ref: dict, output_ref: dict,
    status: str, tokens_in: int = 0, tokens_out: int = 0, cost_usd: float = 0.0,
    latency_ms: int | None = None, error: str | None = None,
    workspace_id: str | None = None,
) -> None:
    with db.get_pool().connection() as conn:
        conn.execute(
            """INSERT INTO agent_runs
               (workspace_id, agent_name, trigger, input_ref, output_ref, status,
                tokens_in, tokens_out, cost_usd, latency_ms, error, finished_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, now())""",
            (
                workspace_id, agent_name, trigger,
                db_json(input_ref), db_json(output_ref), status,
                tokens_in, tokens_out, cost_usd, latency_ms, error,
            ),
        )


def db_json(value) -> str | None:
    import json

    return json.dumps(value) if value is not None else None
