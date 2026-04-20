"""Encrypt/decrypt stored credentials using Fernet (symmetric AES). Requires APP_SECRET_KEY in the environment."""

from __future__ import annotations

import os

from cryptography.fernet import Fernet, InvalidToken


class SecretKeyError(RuntimeError):
    """Raised when APP_SECRET_KEY is missing or invalid."""


def _fernet() -> Fernet:
    raw = os.getenv("APP_SECRET_KEY", "").strip()
    if not raw:
        raise SecretKeyError(
            "APP_SECRET_KEY is not set. Generate one with: "
            "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    try:
        return Fernet(raw.encode("utf-8"))
    except (ValueError, TypeError) as exc:
        raise SecretKeyError(
            "APP_SECRET_KEY must be a valid Fernet key (44-character URL-safe base64)."
        ) from exc


def encrypt_secret(plaintext: str) -> str:
    if plaintext is None or plaintext == "":
        return ""
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(ciphertext: str) -> str:
    if ciphertext is None or ciphertext == "":
        return ""
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise SecretKeyError(
            "Could not decrypt secrets. APP_SECRET_KEY may have changed or data is corrupted."
        ) from exc


def is_encryption_configured() -> bool:
    return bool(os.getenv("APP_SECRET_KEY", "").strip())
