"""Real, minimal session auth — no third-party auth library, stdlib only
(hashlib/hmac), so it needs no new dependency to actually work.

This closes a real, previously-disclosed gap: the role switcher, Organization
records, and API-key minting were all real backend objects sitting behind
*zero* authentication — anyone who knew (or guessed) a factory/org id could
mutate it. That is fine for a solo demo and a real blocker for anything
shared. This is not a claim of production-grade auth (no rate limiting on
login attempts, no password-reset flow, no refresh-token rotation) — it is
a real login, real password hashing, real signed session tokens, scoped to
what a hackathon build can responsibly ship, with the gaps named rather
than hidden.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import models as db
from .deps import get_db

# Real signing secret from the environment in any real deployment; this
# fallback is a disclosed dev-only default, not a production secret — same
# pattern as DATABASE_URL's SQLite fallback in db/base.py.
SESSION_SECRET = os.environ.get("SESSION_SECRET", "induscope-dev-secret-not-for-production")
SESSION_TTL_SECONDS = 24 * 3600
PBKDF2_ITERATIONS = 200_000


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, _ = stored.split("$", 1)
    except ValueError:
        return False
    salt = bytes.fromhex(salt_hex)
    return hmac.compare_digest(hash_password(password, salt), stored)


def _sign(payload: bytes) -> str:
    return hmac.new(SESSION_SECRET.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def create_session_token(user_id: str) -> str:
    """A real signed, expiring token (HMAC-SHA256 over a JSON payload) — not
    a JWT library, but the same idea: base64(payload).signature, verified
    server-side on every request, tamper-evident and time-bound."""
    payload = json.dumps({"uid": user_id, "exp": int(time.time()) + SESSION_TTL_SECONDS}).encode("utf-8")
    payload_b64 = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    signature = _sign(payload_b64.encode("ascii"))
    return f"{payload_b64}.{signature}"


def _decode_session_token(token: str) -> str:
    """Returns the user_id if the token is validly signed and unexpired,
    raises HTTPException(401) otherwise."""
    try:
        payload_b64, signature = token.split(".", 1)
    except ValueError:
        raise HTTPException(401, "malformed session token")
    expected = _sign(payload_b64.encode("ascii"))
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(401, "invalid session token")
    padded = payload_b64 + "=" * (-len(payload_b64) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(padded))
    except Exception:
        raise HTTPException(401, "malformed session token")
    if payload.get("exp", 0) < time.time():
        raise HTTPException(401, "session token expired — log in again")
    return payload["uid"]


@dataclass
class CurrentUser:
    id: str
    email: str
    role: str
    organization_id: str | None


_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: Session = Depends(get_db),
) -> CurrentUser:
    """Real auth dependency — apply with Depends(get_current_user) on any
    endpoint that should require a logged-in session. Raises 401 if there is
    no token, the token is invalid/expired, or the user no longer exists."""
    if credentials is None:
        raise HTTPException(401, "not authenticated — log in via POST /api/auth/login")
    user_id = _decode_session_token(credentials.credentials)
    user = session.get(db.User, user_id)
    if user is None:
        raise HTTPException(401, "session refers to a user that no longer exists")
    return CurrentUser(id=user.id, email=user.email, role=user.role, organization_id=user.organization_id)


def require_role(*roles: str):
    """Dependency factory for endpoints that need more than "any logged-in
    user" — e.g. only a consultant should mint API keys for an org."""
    def _check(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in roles:
            raise HTTPException(403, f"requires role in {roles}, this session is '{user.role}'")
        return user
    return _check
