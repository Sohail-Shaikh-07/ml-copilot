"""Tests for Hugging Face token request helpers."""

from __future__ import annotations

from types import SimpleNamespace

from app.auth import bearer_token_from_header, clean_hf_token, resolve_hf_request_token


def test_clean_hf_token_trims_and_drops_newlines() -> None:
    assert clean_hf_token("  hf_token\n") == "hf_token"
    assert clean_hf_token("   ") is None


def test_bearer_token_from_header_handles_bearer_prefix() -> None:
    assert bearer_token_from_header("Bearer hf_token") == "hf_token"
    assert bearer_token_from_header("Token hf_token") is None


def test_resolve_hf_request_token_prefers_header_over_cookie() -> None:
    request = SimpleNamespace(
        headers={
            "Authorization": "Bearer header-token",
            "X-HF-Token": "fallback-token",
        },
        cookies={"hf_access_token": "cookie-token"},
    )

    assert resolve_hf_request_token(request, include_env_fallback=False) == "header-token"


def test_resolve_hf_request_token_uses_custom_header_then_cookie() -> None:
    request = SimpleNamespace(
        headers={"X-HF-Token": "  header-token  "},
        cookies={"hf_access_token": "cookie-token"},
    )

    assert resolve_hf_request_token(request, include_env_fallback=False) == "header-token"
