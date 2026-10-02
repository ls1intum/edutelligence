"""Decrypt per-link deploy keys for trusted checkout (outside the agent sandbox).

Matches logos-webservice ``RepoCredentialCrypto``: AES-GCM, 12-byte IV prefix,
Base64 ciphertext, key from ``LOGOS_REPO_CREDENTIALS_KEY`` (32 raw bytes) or —
only when ``LOGOS_REPO_CREDENTIALS_DEV_FALLBACK=true`` — SHA-256 of the
documented development passphrase.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import text

from . import db

logger = logging.getLogger(__name__)

ENV_KEY = "LOGOS_REPO_CREDENTIALS_KEY"
ENV_DEV_FALLBACK = "LOGOS_REPO_CREDENTIALS_DEV_FALLBACK"
DEV_DEFAULT_PASSPHRASE = "logos-dev-repo-credentials-key-do-not-use-in-prod"
IV_BYTES = 12


def _aes_key() -> bytes | None:
    raw_env = os.environ.get(ENV_KEY, "").strip()
    if raw_env:
        # Strict standard alphabet first — b64decode without validate=True
        # silently strips URL-safe -/_ and can accept truncated keys.
        try:
            key = base64.b64decode(raw_env, validate=True)
        except Exception:
            key = base64.urlsafe_b64decode(raw_env)
        if len(key) != 32:
            raise ValueError(f"{ENV_KEY} must decode to 32 bytes, got {len(key)}")
        return key
    if os.environ.get(ENV_DEV_FALLBACK, "").lower() == "true":
        return hashlib.sha256(DEV_DEFAULT_PASSPHRASE.encode("utf-8")).digest()
    return None


def decrypt_pem(encoded: str) -> str:
    key = _aes_key()
    if key is None:
        raise ValueError(f"{ENV_KEY} is unset; cannot decrypt repository credentials")
    blob = base64.b64decode(encoded)
    if len(blob) <= IV_BYTES:
        raise ValueError("ciphertext too short")
    iv, ct = blob[:IV_BYTES], blob[IV_BYTES:]
    return AESGCM(key).decrypt(iv, ct, None).decode("utf-8")


async def load_deploy_key_pem(team_repository_id: int) -> str | None:
    """Return the decrypted deploy-key PEM for a non-revoked credential, or None."""
    async with db.sessionmaker()() as conn:
        row = (
            (
                await conn.execute(
                    text("""
                    SELECT encrypted_private_key
                      FROM team_repository_credentials
                     WHERE team_repository_id = :id
                       AND revoked_at IS NULL
                       AND encrypted_private_key IS NOT NULL
                       AND encrypted_private_key <> ''
                    """),
                    {"id": team_repository_id},
                )
            )
            .mappings()
            .first()
        )
    if row is None:
        return None
    try:
        return decrypt_pem(str(row["encrypted_private_key"]))
    except Exception as exc:
        logger.warning(
            "could not decrypt deploy key for team_repository %s: %s",
            team_repository_id,
            exc,
        )
        return None


def write_deploy_key_file(pem: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    text_pem = pem if pem.endswith("\n") else pem + "\n"
    dest.write_text(text_pem, encoding="utf-8")
    dest.chmod(0o600)
    return dest
