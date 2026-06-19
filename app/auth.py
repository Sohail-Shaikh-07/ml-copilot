"""Shared Hugging Face token helpers."""

from __future__ import annotations

import os
from typing import Any


def clean_hf_token(token: str | None) -> str | None:
    """Normalize token strings and drop empty values."""
    if token is None:
        return None
    cleaned = token.replace("\r", "").replace("\n", "").strip()
    return cleaned or None


def bearer_token_from_header(auth_header: str | None) -> str | None:
    """Extract a bearer token from an Authorization header."""
    if not auth_header or not auth_header.startswith("Bearer "):
        return None
    return clean_hf_token(auth_header[7:])


def get_cached_hf_token() -> str | None:
    """Return the token from huggingface_hub's own cache lookup."""
    try:
        from huggingface_hub import get_token

        return clean_hf_token(get_token())
    except Exception:
        return None


def resolve_hf_token(
    *candidates: str | None,
    include_cached: bool = True,
) -> str | None:
    """Return the first usable token from explicit candidates."""
    for token in candidates:
        cleaned = clean_hf_token(token)
        if cleaned:
            return cleaned
    if include_cached:
        return get_cached_hf_token()
    return None


def resolve_hf_request_token(
    request: Any,
    *,
    include_env_fallback: bool = True,
) -> str | None:
    """Resolve the HF token attached to a request, if any."""
    token = bearer_token_from_header(request.headers.get("Authorization", ""))
    if token:
        return token

    token = clean_hf_token(request.headers.get("X-HF-Token"))
    if token:
        return token

    token = clean_hf_token(request.cookies.get("hf_access_token"))
    if token:
        return token

    if include_env_fallback:
        return resolve_hf_token(
            os.environ.get("HF_TOKEN"),
            os.environ.get("HUGGING_FACE_HUB_TOKEN"),
        )
    return None
