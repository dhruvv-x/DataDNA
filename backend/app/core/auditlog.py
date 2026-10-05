"""
Writes rows into the audit_log table (S3). Every security-relevant action goes through write().

prev_hash and entry_hash stay empty until S11, which will fill them here in this one place.
The caller commits. Never put passwords, tokens or raw failed emails in the payload.
"""
import hashlib
import hmac
import uuid

from psycopg.types.json import Jsonb

from app.core import settings


def email_fingerprint(email: str) -> str:
    """
    Keyed hash (HMAC-SHA256) of a lower-cased email. It lets you spot repeated attempts on the
    same address without storing the address. A plain SHA-256 would be useless for this: anyone
    with the log could hash a list of guessed staff emails and compare. The key is derived from
    JWT_SECRET, so without the secret the values cannot be checked against guesses.
    Changing JWT_SECRET changes the fingerprints (old and new entries no longer match each other).
    """
    key = hmac.new(settings.jwt_secret().encode("utf-8"), b"audit-email-fingerprint-v1", hashlib.sha256).digest()
    return hmac.new(key, email.strip().lower()[:300].encode("utf-8"), hashlib.sha256).hexdigest()


def write(
    conn,
    *,
    actor_id: uuid.UUID | None,
    actor_role: str | None,
    action: str,
    entity_type: str,
    entity_id: str | uuid.UUID | None = None,
    payload: dict | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO audit_log (actor_id, actor_role, action, entity_type, entity_id, payload)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (
            actor_id,
            actor_role,
            action,
            entity_type,
            str(entity_id) if entity_id is not None else None,
            Jsonb(payload or {}),
        ),
    )
