"""Password hashing, JWT sessions, and role-check dependencies for the admin/VVIP board.

Design choices worth being explicit about:
  - Password hashing uses stdlib `hashlib.scrypt` (a real, slow, salted KDF)
    rather than pulling in passlib/bcrypt as a new dependency — this project
    already has enough optional heavy dependencies (Sofascore/Playwright);
    scrypt is a legitimate, unglamorous choice for this scope.
  - JWTs carry only `sub` (user id) and an expiry — no role claims. Every
    protected route re-checks the caller's roles against the database on each
    request via `Store.has_role()`, so revoking VVIP or admin access takes
    effect immediately rather than waiting for a token to expire. This is
    what "checks are server-side, not just hidden UI" means in practice here.
"""
from __future__ import annotations
import hashlib
import hmac
import os
import time
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, Header

from .store import Store

SCRYPT_N, SCRYPT_R, SCRYPT_P, SCRYPT_DKLEN = 2**14, 8, 1, 32


def hash_password(password: str) -> tuple[str, str]:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=SCRYPT_DKLEN)
    return digest.hex(), salt.hex()


def verify_password(password: str, password_hash: str, password_salt: str) -> bool:
    salt = bytes.fromhex(password_salt)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=SCRYPT_DKLEN)
    return hmac.compare_digest(digest.hex(), password_hash)


@dataclass
class AuthConfig:
    jwt_secret: str
    jwt_expiry_hours: float = 24.0


def issue_token(user_id: str, config: AuthConfig) -> str:
    now = time.time()
    payload = {"sub": user_id, "iat": now, "exp": now + config.jwt_expiry_hours * 3600}
    return jwt.encode(payload, config.jwt_secret, algorithm="HS256")


def decode_token(token: str, config: AuthConfig) -> str:
    try:
        payload = jwt.decode(token, config.jwt_secret, algorithms=["HS256"])
        user_id = payload.get("sub")
        if not isinstance(user_id, str) or not user_id:
            raise HTTPException(401, "Invalid session: missing subject")
        return user_id
    except HTTPException:
        raise
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid or expired session")

def make_auth_dependencies(store: Store, config: AuthConfig):
    """Builds FastAPI dependencies bound to a specific Store/AuthConfig — a
    factory rather than module-level globals so tests can wire up an isolated
    in-memory store per test without patching module state."""

    def _extract_token(authorization: str | None) -> str:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(401, "Missing or malformed Authorization header (expected 'Bearer <token>')")
        return authorization.split(" ", 1)[1]

    def get_current_user_id(authorization: str | None = Header(default=None)) -> str:
        token = _extract_token(authorization)
        return decode_token(token, config)

    def get_current_user_id_optional(authorization: str | None = Header(default=None)) -> str | None:
        if not authorization:
            return None
        try:
            return get_current_user_id(authorization)
        except HTTPException:
            return None

    def require_role(role: str):
        def _dependency(user_id: str = Depends(get_current_user_id)) -> str:
            if not store.has_role(user_id, role):
                raise HTTPException(403, f"Requires the '{role}' role")
            return user_id
        return _dependency

    return get_current_user_id, get_current_user_id_optional, require_role
