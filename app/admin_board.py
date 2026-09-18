"""Admin board + VVIP tip feed.

Endpoints, matching the requested feature shape:
  - POST /auth/signup, POST /auth/login          — email/password accounts
  - GET  /tips                                    — public feed: free tips in
    full, VVIP tips as locked teasers unless the caller is VVIP or admin
  - GET  /tips/record?days=30                     — won/lost strip from
    settled tips in the window
  - POST/PUT/DELETE /admin/tips[/…]               — admin-only tip authoring
  - POST /admin/tips/{id}/settle                  — mark Won/Lost/Void
  - GET  /admin/members, POST /admin/members/{id}/vvip — member list + VVIP toggle

Authorization is enforced in this router itself (a FastAPI dependency calling
Store.has_role() fresh on every request) rather than in the UI — the same
guarantee the original request's "row-level security" was after, adapted to
a plain-SQL backend instead of a Postgres/RLS one (see app/store.py's module
docstring for why Lovable Cloud specifically isn't applicable here).
"""
from __future__ import annotations
import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field

from .auth import AuthConfig, hash_password, verify_password, issue_token, make_auth_dependencies
from .store import Store
from .appwrite_sync import AppwriteSync

TIER = Literal["free", "vvip"]
STATUS = Literal["pending", "won", "lost", "void"]


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TipCreateRequest(BaseModel):
    match: str
    kickoff_time: str
    market: str
    selection: str
    odds: float | None = None
    confidence: float | None = None
    notes: str | None = None
    tier: TIER = "free"


class TipUpdateRequest(BaseModel):
    match: str | None = None
    kickoff_time: str | None = None
    market: str | None = None
    selection: str | None = None
    odds: float | None = None
    confidence: float | None = None
    notes: str | None = None
    tier: TIER | None = None


class SettleRequest(BaseModel):
    status: Literal["won", "lost", "void"]


class VvipToggleRequest(BaseModel):
    vvip: bool


def bootstrap_admin(store: Store, email: str, password: str) -> None:
    """Grants the admin role to a configured bootstrap account if no admin
    exists yet at all — otherwise there'd be no way to create the first admin
    without already having admin access."""
    if not email or not password or store.any_admin_exists():
        return
    profile = store.get_profile_by_email(email)
    if profile:
        user_id = profile["user_id"]
    else:
        password_hash, salt = hash_password(password)
        user_id = store.create_profile(email, password_hash, salt)
    store.grant_role(user_id, "admin")


def _serialize_tip(tip: dict, can_see_vvip: bool) -> dict:
    base = {
        "id": tip["id"], "match": tip["match"], "kickoff_time": tip["kickoff_time"],
        "market": tip["market"], "tier": tip["tier"], "status": tip["status"],
    }
    if tip["tier"] == "free" or can_see_vvip:
        base.update({
            "selection": tip["selection"], "odds": tip["odds"], "confidence": tip["confidence"],
            "notes": tip["notes"], "locked": False,
        })
    else:
        base.update({"locked": True, "teaser": "VVIP pick — unlock with a VVIP membership"})
    return base


def build_admin_router(store: Store, config: AuthConfig, sync: AppwriteSync | None = None) -> APIRouter:
    router = APIRouter()
    get_current_user_id, get_current_user_id_optional, require_role = make_auth_dependencies(store, config)
    require_admin = require_role("admin")

    @router.post("/auth/signup")
    def signup(payload: SignupRequest):
        if store.get_profile_by_email(payload.email):
            raise HTTPException(409, "An account with that email already exists")
        password_hash, salt = hash_password(payload.password)
        user_id = store.create_profile(payload.email, password_hash, salt)
        if sync:
            sync.sync_profile(user_id, payload.email, [])
        return {"user_id": user_id, "token": issue_token(user_id, config), "roles": []}

    @router.post("/auth/login")
    def login(payload: LoginRequest):
        profile = store.get_profile_by_email(payload.email)
        if not profile or not verify_password(payload.password, profile["password_hash"], profile["password_salt"]):
            raise HTTPException(401, "Invalid email or password")
        return {
            "user_id": profile["user_id"],
            "token": issue_token(profile["user_id"], config),
            "roles": store.roles_for(profile["user_id"]),
        }

    @router.get("/tips")
    def public_tips(user_id: str | None = Depends(get_current_user_id_optional)):
        can_see_vvip = bool(user_id) and (store.has_role(user_id, "vvip") or store.has_role(user_id, "admin"))
        return [_serialize_tip(t, can_see_vvip) for t in store.list_tips()]

    @router.get("/tips/record")
    def record_strip(days: int = 30):
        since = time.time() - days * 86400
        settled = store.settled_tips_since(since)
        won = sum(1 for t in settled if t["status"] == "won")
        lost = sum(1 for t in settled if t["status"] == "lost")
        total = won + lost
        return {"days": days, "won": won, "lost": lost, "win_rate": (won / total) if total else None}

    @router.get("/admin/tips")
    def admin_list_tips(admin_id: str = Depends(require_admin)):
        return store.list_tips()

    @router.post("/admin/tips")
    def create_tip(payload: TipCreateRequest, admin_id: str = Depends(require_admin)):
        tip = store.create_tip(**payload.model_dump(), created_by=admin_id)
        if sync:
            sync.sync_tip(tip)
        return tip

    @router.put("/admin/tips/{tip_id}")
    def update_tip(tip_id: str, payload: TipUpdateRequest, admin_id: str = Depends(require_admin)):
        if not store.get_tip(tip_id):
            raise HTTPException(404, "Tip not found")
        fields = {k: v for k, v in payload.model_dump().items() if v is not None}
        tip = store.update_tip(tip_id, **fields)
        if sync:
            sync.sync_tip(tip)
        return tip

    @router.post("/admin/tips/{tip_id}/settle")
    def settle_tip(tip_id: str, payload: SettleRequest, admin_id: str = Depends(require_admin)):
        if not store.get_tip(tip_id):
            raise HTTPException(404, "Tip not found")
        tip = store.update_tip(tip_id, status=payload.status)
        if sync:
            sync.sync_tip(tip)
        return tip

    @router.delete("/admin/tips/{tip_id}")
    def delete_tip(tip_id: str, admin_id: str = Depends(require_admin)):
        if not store.delete_tip(tip_id):
            raise HTTPException(404, "Tip not found")
        if sync:
            sync.delete_tip(tip_id)
        return {"deleted": True}

    @router.get("/admin/members")
    def list_members(admin_id: str = Depends(require_admin)):
        return store.list_members()

    @router.post("/admin/members/{user_id}/vvip")
    def set_vvip(user_id: str, payload: VvipToggleRequest, admin_id: str = Depends(require_admin)):
        profile = store.get_profile(user_id)
        if not profile:
            raise HTTPException(404, "Member not found")
        if payload.vvip:
            store.grant_role(user_id, "vvip")
        else:
            store.revoke_role(user_id, "vvip")
        roles = store.roles_for(user_id)
        if sync:
            sync.sync_profile(user_id, profile["email"], roles)
        return {"user_id": user_id, "roles": roles}

    return router


# Public alias so other modules (e.g. the Streamlit dashboard) can reuse the
# same locked-teaser serialization instead of re-implementing it.
serialize_tip = _serialize_tip
