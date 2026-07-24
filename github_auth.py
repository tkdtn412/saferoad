#!/usr/bin/env python3
"""GitHub OAuth login helpers for the Safe Road server.

Requires a GitHub OAuth App (https://github.com/settings/developers).
Configure it through environment variables:

    GITHUB_CLIENT_ID       OAuth app client id
    GITHUB_CLIENT_SECRET   OAuth app client secret
    GITHUB_CALLBACK_URL    optional, defaults to http://localhost:8000/auth/github/callback
"""
import json
import os
import secrets
import time
import urllib.parse
import urllib.request

AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
TOKEN_URL = "https://github.com/login/oauth/access_token"
USER_API_URL = "https://api.github.com/user"

SESSION_COOKIE = "saferoad_session"
STATE_TTL_SECONDS = 600

_pending_states = {}
_sessions = {}


def client_id():
    return os.environ.get("GITHUB_CLIENT_ID", "")


def client_secret():
    return os.environ.get("GITHUB_CLIENT_SECRET", "")


def callback_url():
    return os.environ.get("GITHUB_CALLBACK_URL", "http://localhost:8000/auth/github/callback")


def is_configured():
    return bool(client_id() and client_secret())


def _purge_expired_states():
    deadline = time.monotonic() - STATE_TTL_SECONDS
    for state, created in list(_pending_states.items()):
        if created < deadline:
            _pending_states.pop(state, None)


def build_authorize_url():
    """Return the GitHub authorize URL for a new login attempt."""
    _purge_expired_states()
    state = secrets.token_urlsafe(24)
    _pending_states[state] = time.monotonic()
    query = urllib.parse.urlencode(
        {
            "client_id": client_id(),
            "redirect_uri": callback_url(),
            "scope": "read:user",
            "state": state,
        }
    )
    return f"{AUTHORIZE_URL}?{query}"


def consume_state(state):
    _purge_expired_states()
    return _pending_states.pop(state, None) is not None


def _post_json(url, fields, headers):
    data = urllib.parse.urlencode(fields).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def _get_json(url, headers):
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def exchange_code_for_user(code):
    """Trade the OAuth callback code for the GitHub user profile."""
    token_payload = _post_json(
        TOKEN_URL,
        {
            "client_id": client_id(),
            "client_secret": client_secret(),
            "code": code,
            "redirect_uri": callback_url(),
        },
        {"Accept": "application/json"},
    )
    access_token = token_payload.get("access_token")
    if not access_token:
        raise ValueError(token_payload.get("error_description", "GitHub did not return an access token."))

    profile = _get_json(
        USER_API_URL,
        {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {access_token}",
            "User-Agent": "safe-road-prototype",
        },
    )
    return {
        "github_id": profile.get("id"),
        "login": profile.get("login"),
        "name": profile.get("name") or profile.get("login"),
        "avatar_url": profile.get("avatar_url"),
    }


def create_session(user):
    token = secrets.token_urlsafe(32)
    _sessions[token] = user
    return token


def get_session_user(token):
    if not token:
        return None
    return _sessions.get(token)


def destroy_session(token):
    _sessions.pop(token, None)


def session_token_from_cookie_header(cookie_header):
    if not cookie_header:
        return None
    for part in cookie_header.split(";"):
        name, _, value = part.strip().partition("=")
        if name == SESSION_COOKIE:
            return value
    return None
