"""Tests for AuthManager."""
from __future__ import annotations

import os
import tempfile
import time

import pytest

from vortexvpn.core.auth import AuthManager, AuthError


@pytest.fixture
def auth(tmp_path) -> AuthManager:
    db = str(tmp_path / "auth.db")
    return AuthManager(db_path=db, hmac_secret=b"test-secret-32-bytes-fixed-len!!")


def test_create_and_authenticate(auth: AuthManager) -> None:
    auth.create_user("alice", "strong-password-123")
    user = auth.authenticate("alice", "strong-password-123")
    assert user.username == "alice"
    assert user.is_active


def test_wrong_password_rejected(auth: AuthManager) -> None:
    auth.create_user("bob", "correct-password")
    with pytest.raises(AuthError):
        auth.authenticate("bob", "wrong-password")


def test_short_password_rejected(auth: AuthManager) -> None:
    with pytest.raises(AuthError):
        auth.create_user("charlie", "short")


def test_duplicate_user_rejected(auth: AuthManager) -> None:
    auth.create_user("dave", "password-123")
    with pytest.raises(AuthError):
        auth.create_user("dave", "another-password")


def test_token_round_trip(auth: AuthManager) -> None:
    user = auth.create_user("eve", "password-123", is_admin=True)
    token = auth.issue_token(user)
    token_str = token.to_string()
    verified = auth.verify_token(token_str)
    assert verified.username == "eve"
    assert verified.is_admin


def test_invalid_token_rejected(auth: AuthManager) -> None:
    with pytest.raises(AuthError):
        auth.verify_token("garbage.token.value")


def test_set_active(auth: AuthManager) -> None:
    auth.create_user("frank", "password-123")
    assert auth.set_active("frank", False)
    with pytest.raises(AuthError):
        auth.authenticate("frank", "password-123")


def test_delete_user(auth: AuthManager) -> None:
    auth.create_user("grace", "password-123")
    assert auth.delete_user("grace")
    assert auth.get_user("grace") is None


def test_bandwidth_accounting(auth: AuthManager) -> None:
    auth.create_user("heidi", "password-123")
    auth.add_bandwidth_used("heidi", 1024)
    auth.add_bandwidth_used("heidi", 2048)
    user = auth.get_user("heidi")
    assert user is not None
    assert user.bandwidth_used_bytes == 3072


def test_fail2ban_after_threshold(auth: AuthManager) -> None:
    auth.create_user("ivan", "password-123")
    for _ in range(5):
        with pytest.raises(AuthError):
            auth.authenticate("ivan", "wrong")
    # After 5 failures, even correct password must be rejected
    with pytest.raises(AuthError) as exc_info:
        auth.authenticate("ivan", "password-123")
    assert "banned" in str(exc_info.value).lower() or "invalid" in str(exc_info.value).lower()
