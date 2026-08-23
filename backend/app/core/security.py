import hashlib
import hmac
import os
import time

import jwt

from app.config import get_settings


# --- passwords (PBKDF2-HMAC-SHA256, stdlib only) ---

def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return f"pbkdf2_sha256$200000${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(iters)
        )
        return hmac.compare_digest(dk.hex(), hash_hex)
    except (ValueError, TypeError):
        return False


# --- JWT sessions ---

def create_token(user_id: str, workspace_id: str) -> str:
    s = get_settings()
    now = int(time.time())
    payload = {
        "sub": user_id,
        "ws": workspace_id,
        "iat": now,
        "exp": now + s.jwt_expires_minutes * 60,
    }
    return jwt.encode(payload, s.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
