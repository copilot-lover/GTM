"""Onboarding flow endpoints — tracks and completes initial setup."""

import json
import logging
import os
import subprocess
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field

import app.db as db
from app.core.deps import audit, get_current_user, require_workspace
from app.core.security import create_token, hash_password

router = APIRouter(prefix="/onboarding", tags=["onboarding"])

logger = logging.getLogger(__name__)

# n8n workflows directory (relative to backend)
N8N_WORKFLOWS_DIR = Path(__file__).resolve().parents[3] / "n8n" / "workflows"


class OnboardingStatus(BaseModel):
    completed: bool
    step: str
    has_user: bool
    has_workspace: bool


@router.get("/status")
def get_onboarding_status(user: dict = Depends(get_current_user)) -> OnboardingStatus:
    """Check if onboarding is complete for the current user/workspace."""
    with db.get_pool().connection() as conn:
        conn.row_factory = db.dict_row
        ws = conn.execute(
            "SELECT onboarding_completed, onboarding_step FROM workspaces WHERE id = %s",
            (user["workspace_id"],),
        ).fetchone()
        if not ws:
            raise HTTPException(404, "workspace not found")
        # Check if user exists (should always be true if authenticated)
        usr = conn.execute(
            "SELECT 1 FROM users WHERE id = %s", (user["id"],)
        ).fetchone()
    return OnboardingStatus(
        completed=ws["onboarding_completed"],
        step=ws["onboarding_step"],
        has_user=usr is not None,
        has_workspace=True,
    )


class CompleteOnboardingRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    display_name: str | None = None
    workspace_name: str = "Orbit"


@router.post("/complete")
def complete_onboarding(req: CompleteOnboardingRequest):
    """Create admin user, workspace, and mark onboarding complete. Atomic via DB constraints."""
    if len(req.password) < 10:
        raise HTTPException(422, "password must be at least 10 characters")
    with db.get_pool().connection() as conn:
        conn.row_factory = db.dict_row
        try:
            # Create user (email is UNIQUE in DB - handles race)
            user = conn.execute(
                """INSERT INTO users (email, password_hash, display_name)
                   VALUES (%s,%s,%s) RETURNING id, email, display_name""",
                (req.email.lower(), hash_password(req.password), req.display_name),
            ).fetchone()
            # Create workspace
            ws = conn.execute(
                "INSERT INTO workspaces (name, onboarding_completed, onboarding_step) VALUES (%s, true, 'complete') RETURNING id, name",
                (req.workspace_name,),
            ).fetchone()
            # Link user as owner
            conn.execute(
                """INSERT INTO workspace_members (workspace_id, user_id, role)
                   VALUES (%s,%s,'owner')""",
                (ws["id"], user["id"]),
            )
            audit(
                conn,
                actor_type="user",
                actor_id=str(user["id"]),
                action="onboard",
                entity="workspace",
                entity_id=str(ws["id"]),
                workspace_id=str(ws["id"]),
            )
        except Exception as e:
            # Check if it's a unique violation on email
            if "duplicate key value violates unique constraint" in str(e) and "users_email_key" in str(e):
                raise HTTPException(409, "email already registered")
            raise
    return {
        "token": create_token(str(user["id"]), str(ws["id"])),
        "user": {"id": user["id"], "email": user["email"], "display_name": user["display_name"]},
        "workspace": {"id": ws["id"], "name": ws["name"]},
    }


class UpdateStepRequest(BaseModel):
    step: str


@router.post("/step")
def update_onboarding_step(req: UpdateStepRequest, user: dict = Depends(require_workspace)):
    """Update the current onboarding step (for wizard progress tracking)."""
    valid_steps = ["welcome", "settings", "mailboxes", "agents", "complete"]
    if req.step not in valid_steps:
        raise HTTPException(400, f"invalid step, must be one of {valid_steps}")
    with db.get_pool().connection() as conn:
        conn.execute(
            "UPDATE workspaces SET onboarding_step = %s WHERE id = %s",
            (req.step, user["workspace_id"]),
        )
    return {"ok": True, "step": req.step}


class SyncWorkflowsResponse(BaseModel):
    synced: list[str]
    failed: list[dict[str, str]]


@router.post("/sync-workflows", response_model=SyncWorkflowsResponse)
def sync_n8n_workflows(user: dict = Depends(require_workspace)):
    """
    Sync n8n workflow templates from the local filesystem to n8n instance.
    Uses n8n CLI import. Requires N8N_URL and N8N_API_KEY env vars.
    """
    n8n_url = os.environ.get("N8N_URL", "http://localhost:5678")
    n8n_api_key = os.environ.get("N8N_API_KEY")
    if not n8n_api_key:
        raise HTTPException(503, "N8N_API_KEY not configured")

    if not N8N_WORKFLOWS_DIR.exists():
        raise HTTPException(404, f"Workflows directory not found: {N8N_WORKFLOWS_DIR}")

    synced = []
    failed = []

    for workflow_file in N8N_WORKFLOWS_DIR.glob("*.json"):
        try:
            # Validate JSON first
            with open(workflow_file) as f:
                workflow_data = json.load(f)

            # Use n8n CLI to import (requires n8n installed and in PATH)
            # n8n import:workflow --input=file.json
            result = subprocess.run(
                ["n8n", "import:workflow", "--input", str(workflow_file)],
                capture_output=True,
                text=True,
                timeout=30,
                env={**os.environ, "N8N_URL": n8n_url, "N8N_API_KEY": n8n_api_key},
            )
            if result.returncode == 0:
                synced.append(workflow_file.name)
                logger.info("Synced workflow: %s", workflow_file.name)
            else:
                failed.append({"file": workflow_file.name, "error": result.stderr})
                logger.error("Failed to sync %s: %s", workflow_file.name, result.stderr)
        except subprocess.TimeoutExpired:
            failed.append({"file": workflow_file.name, "error": "timeout"})
        except json.JSONDecodeError as e:
            failed.append({"file": workflow_file.name, "error": f"invalid JSON: {e}"})
        except Exception as e:
            failed.append({"file": workflow_file.name, "error": str(e)})

    return SyncWorkflowsResponse(synced=synced, failed=failed)