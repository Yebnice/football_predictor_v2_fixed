"""Optional one-way sync of this app's SQLite data into Appwrite.

Scope, stated plainly: this mirrors profiles (email + roles, never the
password hash) and tips into an Appwrite database as a best-effort push after
each write. It is NOT a backend swap — SQLite (app/store.py) stays the
source of truth this app reads from; Appwrite is a synced copy, useful for a
cloud/multi-device backup or for a separate frontend (e.g. one built in
Lovable, which is Supabase-based, not Appwrite-based, so this is a distinct
integration from that) to read the same tip data. There is no sync in the
other direction: changes made directly in the Appwrite console will not flow
back into this app's SQLite database.

Uses the official `appwrite` Python SDK (verified against v24.0.0's actual
method signatures while building this — see the accompanying setup guide for
exact Appwrite Console steps). Lazily imported so it stays an optional
dependency, matching the pattern used for SofascoreProvider.
"""
from __future__ import annotations
import logging
from typing import Any

logger = logging.getLogger("football_predictor.appwrite_sync")


class AppwriteSync:
    def __init__(self, endpoint: str, project_id: str, api_key: str, database_id: str,
                 profiles_collection_id: str, tips_collection_id: str):
        self.database_id = database_id
        self.profiles_collection_id = profiles_collection_id
        self.tips_collection_id = tips_collection_id
        self._configured = bool(endpoint and project_id and api_key and database_id
                                 and profiles_collection_id and tips_collection_id)
        self._databases = None
        if self._configured:
            try:
                from appwrite.client import Client
                from appwrite.services.databases import Databases
            except ImportError as exc:
                raise ImportError(
                    "Appwrite sync is configured (APPWRITE_* env vars set) but the 'appwrite' "
                    "package isn't installed. Run: pip install -r requirements-optional.txt"
                ) from exc
            client = Client().set_endpoint(endpoint).set_project(project_id).set_key(api_key)
            self._databases = Databases(client)

    def is_configured(self) -> bool:
        return self._configured

    def _safe_upsert(self, collection_id: str, document_id: str, data: dict[str, Any]) -> None:
        """Push one document, swallowing failures — Appwrite is a mirror, not
        the source of truth, so a sync hiccup must never break the primary
        SQLite-backed request that triggered it."""
        if not self._configured:
            return
        try:
            self._databases.upsert_document(
                database_id=self.database_id, collection_id=collection_id,
                document_id=document_id, data=data,
            )
        except ConnectionError as exc:
            logger.error("Appwrite connection error for %s/%s: %s", collection_id, document_id, exc)
        except TimeoutError as exc:
            logger.warning("Appwrite timeout for %s/%s: %s", collection_id, document_id, exc)
        except Exception as exc:  # noqa: BLE001 - deliberately broad: never let sync break the request
            logger.warning("Appwrite sync failed for %s/%s: %s", collection_id, document_id, exc)

    def _safe_delete(self, collection_id: str, document_id: str) -> None:
        if not self._configured:
            return
        try:
            self._databases.delete_document(database_id=self.database_id, collection_id=collection_id,
                                             document_id=document_id)
        except ConnectionError as exc:
            logger.error("Appwrite connection error during delete for %s/%s: %s", collection_id, document_id, exc)
        except TimeoutError as exc:
            logger.warning("Appwrite timeout during delete for %s/%s: %s", collection_id, document_id, exc)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Appwrite delete failed for %s/%s: %s", collection_id, document_id, exc)

    def sync_profile(self, user_id: str, email: str, roles: list[str]) -> None:
        self._safe_upsert(self.profiles_collection_id, user_id, {"email": email, "roles": roles})

    def sync_tip(self, tip: dict[str, Any]) -> None:
        # Appwrite document IDs must not exceed 36 chars and use a limited
        # charset; our own tip ids are uuid4 hex strings, which already fit.
        self._safe_upsert(self.tips_collection_id, tip["id"], {
            "match": tip["match"], "kickoff_time": tip["kickoff_time"], "market": tip["market"],
            "selection": tip["selection"], "odds": tip.get("odds"), "confidence": tip.get("confidence"),
            "notes": tip.get("notes"), "tier": tip["tier"], "status": tip["status"],
        })

    def delete_tip(self, tip_id: str) -> None:
        self._safe_delete(self.tips_collection_id, tip_id)
